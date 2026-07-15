"""Tests for MetService weather entities (public and mobile)."""

from __future__ import annotations

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


async def test_public_entity_condition_unknown_passthrough(hass):
    """Unmapped condition is passed through as-is."""
    coord = _make_coordinator(hass)
    coord.data = MetServicePublicData(condition="unknown-condition")
    entity = MetServiceForecastPublic(coord)
    entity.hass = hass
    with patch(
        "custom_components.metservice_weather.weather.sun_helper.is_up",
        return_value=True,
    ):
        cond = entity.condition
    assert cond == "unknown-condition"


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
