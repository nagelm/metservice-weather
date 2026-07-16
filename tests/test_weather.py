"""Tests for MetService weather entities (public and mobile)."""

from __future__ import annotations

import logging
from unittest.mock import patch, AsyncMock


from custom_components.metservice_weather.coordinator import (
    WeatherUpdateCoordinator,
    WeatherUpdateCoordinatorConfig,
)
from custom_components.metservice_weather.const import (
    CONDITION_MAP,
    DOMAIN,
)
from custom_components.metservice_weather.coordinator_types import (
    MetServicePublicData,
    HourlyEntry,
    DailyEntry,
)
from custom_components.metservice_weather.weather import (
    MetServiceForecastPublic,
    _UNMAPPED_LOGGED,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_coordinator(
    hass, tide_url="", boating_url="", surf_url=""
) -> WeatherUpdateCoordinator:
    config = WeatherUpdateCoordinatorConfig(
        api_url="https://www.metservice.com/publicData/webdata",
        warnings_url="https://www.metservice.com/publicData/webdata/warnings-service",
        unit_system_api="m",
        unit_system="metric",
        location="/towns-cities/regions/hawkes-bay/locations/napier",
        location_name="Napier",
        tide_url=tide_url,
        boating_url=boating_url,
        surf_url=surf_url,
    )
    coord = WeatherUpdateCoordinator(hass, config)
    coord.data = MetServicePublicData()
    return coord


# ---------------------------------------------------------------------------
# Test: async_setup_entry
# ---------------------------------------------------------------------------


async def test_weather_setup_entry_public(hass):
    """async_setup_entry creates a single MetServiceForecastPublic entity."""
    from custom_components.metservice_weather.weather import async_setup_entry
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "name": "Napier",
            "location": "/towns-cities/regions/hawkes-bay/locations/napier",
            "api": "public",
            "marine_region": "",
            "tide_url": "",
            "boating_url": "",
            "surf_url": "",
        },
    )
    coord = _make_coordinator(hass)
    entry.runtime_data = coord

    added = []

    def add_entities(entities, *args, **kwargs):
        added.extend(entities)

    await async_setup_entry(hass, entry, add_entities)
    assert len(added) == 1
    assert isinstance(added[0], MetServiceForecastPublic)


# ---------------------------------------------------------------------------
# Test: MetServiceForecastPublic properties
# ---------------------------------------------------------------------------


async def test_public_entity_name(hass):
    """MetServiceForecastPublic.name is 'Forecast'."""
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)
    assert entity.name == "Forecast"


async def test_public_entity_unique_id(hass):
    """MetServiceForecastPublic.unique_id includes the location slug."""
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)
    assert "napier" in entity.unique_id.lower()


async def test_public_entity_temperature(hass):
    """native_temperature reflects coordinator.data.temperature."""
    coord = _make_coordinator(hass)
    coord.data = MetServicePublicData(temperature=18.5)
    entity = MetServiceForecastPublic(coord)
    assert entity.native_temperature == 18.5


async def test_public_entity_pressure(hass):
    """native_pressure reflects coordinator.data.pressure."""
    coord = _make_coordinator(hass)
    coord.data = MetServicePublicData(pressure=1013.0)
    entity = MetServiceForecastPublic(coord)
    assert entity.native_pressure == 1013.0


async def test_public_entity_humidity(hass):
    """Humidity reflects coordinator.data.humidity."""
    coord = _make_coordinator(hass)
    coord.data = MetServicePublicData(humidity=75)
    entity = MetServiceForecastPublic(coord)
    assert entity.humidity == 75


async def test_public_entity_properties_safe_when_data_is_none(hass):
    """Every property returns None/[] when the coordinator has no data yet.

    Regression test: with a mocked first refresh the coordinator data is None
    during entity addition, which previously raised AttributeError in CI.
    """
    coord = _make_coordinator(hass)
    coord.data = None
    entity = MetServiceForecastPublic(coord)
    assert entity.native_temperature is None
    assert entity.native_pressure is None
    assert entity.humidity is None
    assert entity.native_wind_speed is None
    assert entity.wind_bearing is None
    assert entity.condition is None
    assert entity.forecast_hourly == []
    assert entity.forecast_daily == []


async def test_public_entity_humidity_none(hass):
    """Humidity is None when coordinator.data.humidity is unset."""
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)
    assert entity.humidity is None


async def test_public_entity_wind_speed(hass):
    """native_wind_speed reflects coordinator.data.wind_speed."""
    coord = _make_coordinator(hass)
    coord.data = MetServicePublicData(wind_speed=25.0)
    entity = MetServiceForecastPublic(coord)
    assert entity.native_wind_speed == 25.0


async def test_public_entity_wind_bearing(hass):
    """wind_bearing reflects coordinator.data.wind_direction."""
    coord = _make_coordinator(hass)
    coord.data = MetServicePublicData(wind_direction="NW")
    entity = MetServiceForecastPublic(coord)
    assert entity.wind_bearing == "NW"


async def test_public_entity_condition_mapped(hass):
    """Condition maps the raw MetService condition through CONDITION_MAP while the sun is up."""
    coord = _make_coordinator(hass)
    coord.data = MetServicePublicData(condition="rain")
    entity = MetServiceForecastPublic(coord)
    entity.hass = hass
    with patch(
        "custom_components.metservice_weather.weather.sun_helper.is_up",
        return_value=True,
    ):
        cond = entity.condition
    assert cond == CONDITION_MAP["rain"]


async def test_public_entity_condition_clear_night(hass):
    """'fine' at night → 'clear-night'."""
    coord = _make_coordinator(hass)
    coord.data = MetServicePublicData(condition="fine")
    entity = MetServiceForecastPublic(coord)
    entity.hass = hass
    with patch(
        "custom_components.metservice_weather.weather.sun_helper.is_up",
        return_value=False,
    ):
        cond = entity.condition
    assert cond == "clear-night"


async def test_public_entity_condition_unknown_returns_none(hass):
    """An unmapped condition is reported as None rather than passed through."""
    _UNMAPPED_LOGGED.discard("unknown-condition")
    coord = _make_coordinator(hass)
    coord.data = MetServicePublicData(condition="unknown-condition")
    entity = MetServiceForecastPublic(coord)
    entity.hass = hass
    with patch(
        "custom_components.metservice_weather.weather.sun_helper.is_up",
        return_value=True,
    ):
        cond = entity.condition
    assert cond is None


async def test_public_entity_condition_none_returns_none(hass):
    """A None raw condition returns None without invoking the sun helper."""
    coord = _make_coordinator(hass)
    coord.data = MetServicePublicData(condition=None)
    entity = MetServiceForecastPublic(coord)
    entity.hass = hass
    with patch(
        "custom_components.metservice_weather.weather.sun_helper.is_up",
        return_value=True,
    ):
        cond = entity.condition
    assert cond is None


async def test_public_entity_condition_night_variant_falls_back_to_day_token(hass):
    """'showers-night' falls back to the 'showers' mapping ('rainy')."""
    coord = _make_coordinator(hass)
    coord.data = MetServicePublicData(condition="showers-night")
    entity = MetServiceForecastPublic(coord)
    entity.hass = hass
    with patch(
        "custom_components.metservice_weather.weather.sun_helper.is_up",
        return_value=True,
    ):
        cond = entity.condition
    assert cond == "rainy"


async def test_public_entity_condition_night_variant_of_sunny_is_clear_night(hass):
    """'fine-night' maps to 'clear-night' regardless of the sun helper's state."""
    coord = _make_coordinator(hass)
    coord.data = MetServicePublicData(condition="fine-night")
    entity = MetServiceForecastPublic(coord)
    entity.hass = hass
    with patch(
        "custom_components.metservice_weather.weather.sun_helper.is_up",
        return_value=True,
    ):
        cond = entity.condition
    assert cond == "clear-night"


async def test_public_entity_condition_unknown_logged_once(hass, caplog):
    """An unmapped condition token is only logged as a warning once per runtime."""
    _UNMAPPED_LOGGED.discard("never-seen-before")
    coord = _make_coordinator(hass)
    coord.data = MetServicePublicData(condition="never-seen-before")
    entity = MetServiceForecastPublic(coord)
    entity.hass = hass
    with (
        caplog.at_level(logging.WARNING),
        patch(
            "custom_components.metservice_weather.weather.sun_helper.is_up",
            return_value=True,
        ),
    ):
        entity.condition
        entity.condition
    matches = [r for r in caplog.records if "never-seen-before" in r.getMessage()]
    assert len(matches) == 1


async def test_public_entity_temperature_units(hass):
    """native_temperature_unit is set."""
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)
    assert entity.native_temperature_unit is not None


async def test_public_entity_pressure_units(hass):
    """native_pressure_unit is set."""
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)
    assert entity.native_pressure_unit is not None


async def test_public_entity_wind_speed_units(hass):
    """native_wind_speed_unit is set."""
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)
    assert entity.native_wind_speed_unit is not None


async def test_public_entity_precipitation_units(hass):
    """native_precipitation_unit is set."""
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)
    assert entity.native_precipitation_unit is not None


# ---------------------------------------------------------------------------
# Test: MetServiceForecastPublic forecast_hourly
# ---------------------------------------------------------------------------


def _hourly_data(**kwargs) -> MetServicePublicData:
    """Build a MetServicePublicData with one HourlyEntry for icon tests."""
    entry = HourlyEntry(**kwargs)
    return MetServicePublicData(hourly_entries=[entry], hourly_obs=1, hourly_skip=0)


async def test_public_forecast_hourly_empty_when_no_data(hass):
    """forecast_hourly is an empty list when there are no hourly entries."""
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)
    result = entity.forecast_hourly
    assert result == []


async def test_public_forecast_hourly_with_data(hass):
    """forecast_hourly converts HourlyEntry data into forecast dicts."""
    coord = _make_coordinator(hass)
    coord.data = MetServicePublicData(
        hourly_entries=[
            HourlyEntry(
                datetime="2024-06-15T10:00:00+12:00",
                temperature=18.0,
                rainfall=0.0,
                wind_speed=15.0,
                wind_direction="NW",
            ),
            HourlyEntry(
                datetime="2024-06-15T22:00:00+12:00",
                temperature=12.0,
                rainfall=0.0,
                wind_speed=10.0,
                wind_direction="SW",
            ),
        ],
        hourly_obs=2,
        hourly_skip=0,
    )
    entity = MetServiceForecastPublic(coord)
    result = entity.forecast_hourly
    assert len(result) == 2
    assert result[0]["native_temperature"] == 18.0


async def test_public_forecast_hourly_heavy_rain_icon(hass):
    """forecast_hourly maps heavy rainfall to the 'pouring' condition icon."""
    coord = _make_coordinator(hass)
    coord.data = _hourly_data(
        datetime="2024-06-15T10:00:00+12:00",
        temperature=10.0,
        rainfall=10.0,
        wind_speed=5.0,
        wind_direction="N",
    )
    entity = MetServiceForecastPublic(coord)
    assert entity.forecast_hourly[0]["condition"] == "pouring"


async def test_public_forecast_hourly_light_rain_icon(hass):
    """forecast_hourly maps light rainfall to the 'rainy' condition icon."""
    coord = _make_coordinator(hass)
    coord.data = _hourly_data(
        datetime="2024-06-15T10:00:00+12:00",
        temperature=12.0,
        rainfall=2.0,
        wind_speed=5.0,
        wind_direction="N",
    )
    entity = MetServiceForecastPublic(coord)
    assert entity.forecast_hourly[0]["condition"] == "rainy"


async def test_public_forecast_hourly_windy_icon(hass):
    """forecast_hourly maps high wind speed to the 'windy' condition icon."""
    coord = _make_coordinator(hass)
    coord.data = _hourly_data(
        datetime="2024-06-15T14:00:00+12:00",
        temperature=15.0,
        rainfall=0.0,
        wind_speed=50.0,
        wind_direction="SW",
    )
    entity = MetServiceForecastPublic(coord)
    assert entity.forecast_hourly[0]["condition"] == "windy"


async def test_public_forecast_hourly_night_icon(hass):
    """forecast_hourly maps a nighttime hour with no rain or wind to 'clear-night'."""
    coord = _make_coordinator(hass)
    coord.data = _hourly_data(
        datetime="2024-06-15T22:00:00+12:00",
        temperature=8.0,
        rainfall=0.0,
        wind_speed=5.0,
        wind_direction="N",
    )
    entity = MetServiceForecastPublic(coord)
    assert entity.forecast_hourly[0]["condition"] == "clear-night"


async def test_public_forecast_hourly_skip_offsets_start(hass):
    """hourly_skip causes the first N entries to be excluded."""
    coord = _make_coordinator(hass)
    coord.data = MetServicePublicData(
        hourly_entries=[
            HourlyEntry(
                datetime="2024-06-15T08:00:00+12:00",
                temperature=10.0,
                rainfall=0.0,
                wind_speed=5.0,
            ),
            HourlyEntry(
                datetime="2024-06-15T10:00:00+12:00",
                temperature=18.0,
                rainfall=0.0,
                wind_speed=5.0,
            ),
        ],
        hourly_obs=1,
        hourly_skip=1,
    )
    entity = MetServiceForecastPublic(coord)
    result = entity.forecast_hourly
    assert len(result) == 1
    assert result[0]["native_temperature"] == 18.0


# ---------------------------------------------------------------------------
# Test: MetServiceForecastPublic forecast_daily
# ---------------------------------------------------------------------------


async def test_public_forecast_daily_empty_when_no_days(hass):
    """forecast_daily is an empty list when there are no daily entries."""
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)
    result = entity.forecast_daily
    assert result == []


async def test_public_forecast_daily_with_data(hass):
    """forecast_daily converts DailyEntry data into forecast dicts with mapped condition."""
    coord = _make_coordinator(hass)
    coord.data = MetServicePublicData(
        daily_entries=[
            DailyEntry(
                condition="fine",
                temp_high=22.0,
                temp_low=12.0,
                datetime="2024-06-15",
                description="Sunny day",
                rain_prob_1mm=0.0,
                rain_prob_10mm=1.0,
            ),
            DailyEntry(
                condition="cloudy", temp_high=18.0, temp_low=10.0, datetime="2024-06-16"
            ),
        ]
    )
    entity = MetServiceForecastPublic(coord)
    result = entity.forecast_daily
    assert len(result) == 2
    assert result[0]["native_temperature"] == 22.0
    assert result[0]["native_templow"] == 12.0
    assert result[0]["condition"] == CONDITION_MAP["fine"]


async def test_public_forecast_daily_precipitation_probability(hass):
    """MetService publishes rainfall exceedance probabilities, so rain_prob_1mm maps to precipitation_probability, never to native_precipitation."""
    coord = _make_coordinator(hass)
    coord.data = MetServicePublicData(
        daily_entries=[
            DailyEntry(
                condition="rain",
                temp_high=15.0,
                temp_low=8.0,
                datetime="2024-06-15",
                rain_prob_1mm=50.0,
                rain_prob_10mm=5.0,
            )
        ]
    )
    entity = MetServiceForecastPublic(coord)
    result = entity.forecast_daily
    assert result[0]["precipitation_probability"] == 50
    assert "native_precipitation" not in result[0]
    assert "precipitation_low_mm" not in result[0]
    assert "precipitation_high_mm" not in result[0]


async def test_public_forecast_daily_precipitation_probability_absent_when_none(hass):
    """precipitation_probability is omitted from the forecast dict when rain_prob_1mm is None."""
    coord = _make_coordinator(hass)
    coord.data = MetServicePublicData(
        daily_entries=[
            DailyEntry(
                condition="fine",
                temp_high=20.0,
                temp_low=10.0,
                datetime="2024-06-15",
                rain_prob_1mm=None,
            )
        ]
    )
    entity = MetServiceForecastPublic(coord)
    result = entity.forecast_daily
    assert "precipitation_probability" not in result[0]


async def test_public_forecast_daily_precipitation_probability_rounds_to_int(hass):
    """precipitation_probability is rounded to the nearest int."""
    coord = _make_coordinator(hass)
    coord.data = MetServicePublicData(
        daily_entries=[
            DailyEntry(
                condition="rain",
                temp_high=15.0,
                temp_low=8.0,
                datetime="2024-06-15",
                rain_prob_1mm=32.6,
            )
        ]
    )
    entity = MetServiceForecastPublic(coord)
    result = entity.forecast_daily
    assert result[0]["precipitation_probability"] == 33
    assert isinstance(result[0]["precipitation_probability"], int)


async def test_public_forecast_daily_rain_total_sets_native_precipitation(hass):
    """rain_total_mm (a genuine amount) maps to native_precipitation, not precipitation_probability."""
    coord = _make_coordinator(hass)
    coord.data = MetServicePublicData(
        daily_entries=[
            DailyEntry(
                condition="rain",
                temp_high=15.0,
                temp_low=8.0,
                datetime="2024-06-15",
                rain_total_mm=11.8,
                rain_prob_1mm=None,
            )
        ]
    )
    entity = MetServiceForecastPublic(coord)
    result = entity.forecast_daily
    assert result[0]["native_precipitation"] == 11.8
    assert "precipitation_probability" not in result[0]


async def test_public_forecast_daily_rain_prob_only_omits_native_precipitation(hass):
    """When only rain_prob_1mm is set, precipitation_probability is present and native_precipitation is absent."""
    coord = _make_coordinator(hass)
    coord.data = MetServicePublicData(
        daily_entries=[
            DailyEntry(
                condition="rain",
                temp_high=15.0,
                temp_low=8.0,
                datetime="2024-06-15",
                rain_total_mm=None,
                rain_prob_1mm=30.0,
            )
        ]
    )
    entity = MetServiceForecastPublic(coord)
    result = entity.forecast_daily
    assert result[0]["precipitation_probability"] == 30
    assert "native_precipitation" not in result[0]


async def test_public_forecast_daily_rain_total_and_prob_both_present(hass):
    """When both rain_total_mm and rain_prob_1mm are set, both keys appear in the forecast entry."""
    coord = _make_coordinator(hass)
    coord.data = MetServicePublicData(
        daily_entries=[
            DailyEntry(
                condition="rain",
                temp_high=15.0,
                temp_low=8.0,
                datetime="2024-06-15",
                rain_total_mm=6.4,
                rain_prob_1mm=80.0,
            )
        ]
    )
    entity = MetServiceForecastPublic(coord)
    result = entity.forecast_daily
    assert result[0]["native_precipitation"] == 6.4
    assert result[0]["precipitation_probability"] == 80


async def test_public_forecast_daily_unknown_condition_is_none(hass):
    """forecast_daily reports None for an unmapped condition instead of a raw token."""
    coord = _make_coordinator(hass)
    coord.data = MetServicePublicData(
        daily_entries=[
            DailyEntry(
                condition="never-seen-before",
                temp_high=20.0,
                temp_low=10.0,
                datetime="2024-06-15",
            )
        ]
    )
    entity = MetServiceForecastPublic(coord)
    result = entity.forecast_daily
    assert result[0]["condition"] is None


async def test_public_forecast_daily_rural_style_entries_have_temps(hass):
    """Rural daily entries, populated via the _scan_forecasts fallback with no observations, still produce a full forecast entry."""
    coord = _make_coordinator(hass)
    coord.data = MetServicePublicData(
        daily_entries=[
            DailyEntry(
                condition="cloudy",
                temp_high=17.0,
                temp_low=5.0,
                datetime="2024-06-15",
                description="Regional cloudy",
            )
        ]
    )
    entity = MetServiceForecastPublic(coord)
    result = entity.forecast_daily
    assert result[0]["native_temperature"] == 17.0
    assert result[0]["native_templow"] == 5.0


async def test_public_async_forecast_hourly(hass):
    """async_forecast_hourly returns an empty list when there is no hourly data."""
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)
    result = await entity.async_forecast_hourly()
    assert result == []


async def test_public_async_forecast_daily(hass):
    """async_forecast_daily returns an empty list when there is no daily data."""
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)
    result = await entity.async_forecast_daily()
    assert result == []


async def test_public_extra_state_attributes_is_none(hass):
    """extra_state_attributes is None for the public forecast entity."""
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)
    assert entity.extra_state_attributes is None


# ---------------------------------------------------------------------------
# Test: current-conditions fallback to the nearest forecast hour
# ---------------------------------------------------------------------------


async def test_current_conditions_fall_back_to_nearest_forecast_hour(hass):
    """Without observations the nearest forecast hour supplies temp and wind."""
    from datetime import timedelta

    from homeassistant.util import dt as dt_util

    now = dt_util.now()
    coord = _make_coordinator(hass)
    coord.data = MetServicePublicData(
        temperature=None,
        hourly_entries=[
            HourlyEntry(
                datetime=(now - timedelta(hours=1)).isoformat(),
                temperature=8.0,
                wind_speed=10.0,
                wind_direction="N",
            ),
            HourlyEntry(
                datetime=now.isoformat(),
                temperature=9.5,
                wind_speed=22.0,
                wind_direction="SE",
            ),
            HourlyEntry(
                datetime=(now + timedelta(hours=1)).isoformat(),
                temperature=11.0,
                wind_speed=30.0,
                wind_direction="W",
            ),
        ],
    )
    entity = MetServiceForecastPublic(coord)
    assert entity.native_temperature == 9.5
    assert entity.native_wind_speed == 22.0
    assert entity.wind_bearing == "SE"


async def test_current_conditions_prefer_observed_readings(hass):
    """Observed station readings win over the forecast-hour fallback."""
    from homeassistant.util import dt as dt_util

    coord = _make_coordinator(hass)
    coord.data = MetServicePublicData(
        temperature=18.5,
        wind_speed=33.0,
        wind_direction="W",
        hourly_entries=[
            HourlyEntry(
                datetime=dt_util.now().isoformat(),
                temperature=9.5,
                wind_speed=22.0,
                wind_direction="SE",
            )
        ],
    )
    entity = MetServiceForecastPublic(coord)
    assert entity.native_temperature == 18.5
    assert entity.native_wind_speed == 33.0
    assert entity.wind_bearing == "W"


async def test_forecast_hour_fallback_requires_recent_entry(hass):
    """Hourly entries over 3 hours away do not masquerade as current conditions."""
    from datetime import timedelta

    from homeassistant.util import dt as dt_util

    coord = _make_coordinator(hass)
    coord.data = MetServicePublicData(
        temperature=None,
        hourly_entries=[
            HourlyEntry(
                datetime=(dt_util.now() + timedelta(hours=4)).isoformat(),
                temperature=12.0,
                wind_speed=15.0,
                wind_direction="N",
            )
        ],
    )
    entity = MetServiceForecastPublic(coord)
    assert entity.native_temperature is None
    assert entity.native_wind_speed is None
    assert entity.wind_bearing is None


async def test_forecast_hour_fallback_skips_malformed_datetimes(hass):
    """Malformed or naive hourly datetimes are skipped, not crashed on."""
    from homeassistant.util import dt as dt_util

    coord = _make_coordinator(hass)
    coord.data = MetServicePublicData(
        temperature=None,
        hourly_entries=[
            HourlyEntry(datetime="not-a-date", temperature=99.0, wind_speed=99.0),
            HourlyEntry(datetime="", temperature=98.0, wind_speed=98.0),
            # Naive timestamp (no offset) can't be compared to aware now().
            HourlyEntry(
                datetime="2024-06-15T10:00:00", temperature=97.0, wind_speed=97.0
            ),
            HourlyEntry(
                datetime=dt_util.now().isoformat(),
                temperature=9.5,
                wind_speed=22.0,
                wind_direction="SE",
            ),
        ],
    )
    entity = MetServiceForecastPublic(coord)
    assert entity.native_temperature == 9.5


async def test_forecast_hour_fallback_none_when_no_hourly_data(hass):
    """With neither observations nor hourly entries the attributes stay None."""
    coord = _make_coordinator(hass)
    coord.data = MetServicePublicData(temperature=None, hourly_entries=[])
    entity = MetServiceForecastPublic(coord)
    assert entity.native_temperature is None
    assert entity.native_wind_speed is None
    assert entity.wind_bearing is None


# ---------------------------------------------------------------------------
# Test: stale weather-domain registry cleanup
# ---------------------------------------------------------------------------


async def test_weather_setup_removes_stale_weather_registry_entries(hass):
    """Stale weather-domain registry rows are pruned; the current weather row and sensor rows survive."""
    from custom_components.metservice_weather.weather import async_setup_entry
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from homeassistant.helpers import entity_registry as er

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "name": "Napier",
            "location": "/towns-cities/regions/hawkes-bay/locations/napier",
            "api": "public",
            "marine_region": "",
            "tide_url": "",
            "boating_url": "",
            "surf_url": "",
        },
    )
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)
    entry.runtime_data = coord
    loc = coord.location

    ent_reg = er.async_get(hass)
    # The pre-fork duplicated-name weather entity's unique_id format.
    stale = ent_reg.async_get_or_create(
        "weather", DOMAIN, "napier,weather", config_entry=entry
    )
    current = ent_reg.async_get_or_create(
        "weather", DOMAIN, f"{loc}_weather".lower(), config_entry=entry
    )
    sensor_row = ent_reg.async_get_or_create(
        "sensor", DOMAIN, f"{loc}_weather_warnings".lower(), config_entry=entry
    )

    added = []

    def add_entities(entities, *args, **kwargs):
        added.extend(entities)

    await async_setup_entry(hass, entry, add_entities)

    assert ent_reg.async_get(stale.entity_id) is None
    assert ent_reg.async_get(current.entity_id) is not None
    assert ent_reg.async_get(sensor_row.entity_id) is not None
    assert len(added) == 1


async def test_weather_stale_removal_creates_removed_entity_issue_when_referenced(hass):
    """A stale weather-domain row still referenced by an automation gets a removed_entity issue before removal."""
    from custom_components.metservice_weather.weather import async_setup_entry
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from homeassistant.helpers import entity_registry as er
    from homeassistant.helpers import issue_registry as ir
    from homeassistant.util import slugify

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "name": "Napier",
            "location": "/towns-cities/regions/hawkes-bay/locations/napier",
            "api": "public",
            "marine_region": "",
            "tide_url": "",
            "boating_url": "",
            "surf_url": "",
        },
    )
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)
    entry.runtime_data = coord

    ent_reg = er.async_get(hass)
    stale = ent_reg.async_get_or_create(
        "weather", DOMAIN, "napier,weather", config_entry=entry
    )

    hass.config.components.add("automation")
    hass.config.components.add("script")
    with (
        patch(
            "custom_components.metservice_weather.deprecation.automations_with_entity",
            return_value=["automation.dashboard"],
        ),
        patch(
            "custom_components.metservice_weather.deprecation.scripts_with_entity",
            return_value=[],
        ),
    ):
        await async_setup_entry(hass, entry, lambda entities, *a, **k: None)

    assert ent_reg.async_get(stale.entity_id) is None
    issue_id = f"removed_entity_{entry.entry_id}_{slugify(stale.entity_id)}"
    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.translation_placeholders["entity_id"] == stale.entity_id
    assert "automation.dashboard" in issue.translation_placeholders["references"]


async def test_self_corrected_user_weather_stale_removal_without_references_stays_silent(
    hass,
):
    """A stale weather-domain row with no references is removed without any removed_entity issue."""
    from custom_components.metservice_weather.weather import async_setup_entry
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from homeassistant.helpers import entity_registry as er
    from homeassistant.helpers import issue_registry as ir
    from homeassistant.util import slugify

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "name": "Napier",
            "location": "/towns-cities/regions/hawkes-bay/locations/napier",
            "api": "public",
            "marine_region": "",
            "tide_url": "",
            "boating_url": "",
            "surf_url": "",
        },
    )
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)
    entry.runtime_data = coord

    ent_reg = er.async_get(hass)
    stale = ent_reg.async_get_or_create(
        "weather", DOMAIN, "napier,weather", config_entry=entry
    )

    hass.config.components.add("automation")
    hass.config.components.add("script")
    with (
        patch(
            "custom_components.metservice_weather.deprecation.automations_with_entity",
            return_value=[],
        ),
        patch(
            "custom_components.metservice_weather.deprecation.scripts_with_entity",
            return_value=[],
        ),
    ):
        await async_setup_entry(hass, entry, lambda entities, *a, **k: None)

    assert ent_reg.async_get(stale.entity_id) is None
    issue_id = f"removed_entity_{entry.entry_id}_{slugify(stale.entity_id)}"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_entity_unavailable_when_coordinator_fails(hass):
    """Available is False when the coordinator's last update failed."""
    coord = _make_coordinator(hass)
    coord.last_update_success = False
    entity = MetServiceForecastPublic(coord)
    assert entity.available is False


# ---------------------------------------------------------------------------
# Test: forecast caching — public
# ---------------------------------------------------------------------------


async def test_public_async_forecast_hourly_populates_cache(hass):
    """async_forecast_hourly populates _forecast_hourly_cache on first call."""
    coord = _make_coordinator(hass)
    coord.data = MetServicePublicData(
        hourly_entries=[
            HourlyEntry(
                datetime="2024-06-15T10:00:00+12:00",
                temperature=20.0,
                rainfall=0.0,
                wind_speed=10.0,
            )
        ],
        hourly_obs=1,
        hourly_skip=0,
    )
    entity = MetServiceForecastPublic(coord)
    assert entity._forecast_hourly_cache is None
    result = await entity.async_forecast_hourly()
    assert result is not None and len(result) == 1
    assert entity._forecast_hourly_cache is result


async def test_public_async_forecast_daily_populates_cache(hass):
    """async_forecast_daily populates _forecast_daily_cache on first call."""
    coord = _make_coordinator(hass)
    coord.data = MetServicePublicData(
        daily_entries=[
            DailyEntry(
                condition="fine", temp_high=22.0, temp_low=12.0, datetime="2024-06-15"
            )
        ]
    )
    entity = MetServiceForecastPublic(coord)
    assert entity._forecast_daily_cache is None
    result = await entity.async_forecast_daily()
    assert result is not None and len(result) == 1
    assert entity._forecast_daily_cache is result


async def test_public_async_forecast_hourly_returns_same_object_on_second_call(hass):
    """async_forecast_hourly returns the cached object on a second call."""
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)
    result1 = await entity.async_forecast_hourly()
    result2 = await entity.async_forecast_hourly()
    assert result1 is result2


async def test_public_async_forecast_daily_returns_same_object_on_second_call(hass):
    """async_forecast_daily returns the cached object on a second call."""
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)
    result1 = await entity.async_forecast_daily()
    result2 = await entity.async_forecast_daily()
    assert result1 is result2


async def test_public_handle_coordinator_update_clears_cache(hass):
    """_handle_coordinator_update clears the hourly and daily forecast caches."""
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)
    entity.hass = hass
    entity._forecast_hourly_cache = []
    entity._forecast_daily_cache = []
    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()
    assert entity._forecast_hourly_cache is None
    assert entity._forecast_daily_cache is None


async def test_public_handle_coordinator_update_schedules_listeners(hass):
    """_handle_coordinator_update schedules forecast listener updates."""
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)
    entity.hass = hass
    with (
        patch.object(entity, "async_write_ha_state"),
        patch.object(
            entity, "async_update_listeners", new_callable=AsyncMock
        ) as mock_listeners,
    ):
        entity._handle_coordinator_update()
    mock_listeners.assert_called_once_with(None)
