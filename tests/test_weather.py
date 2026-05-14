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
    MetServiceForecastMobile,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_coordinator(hass, api_type="public", tide_url="", boating_url="", surf_url="") -> WeatherUpdateCoordinator:
    config = WeatherUpdateCoordinatorConfig(
        api_url="https://www.metservice.com/publicData/webdata",
        warnings_url="https://www.metservice.com/publicData/webdata/warnings-service",
        api_key="",
        api_type=api_type,
        unit_system_api="m",
        unit_system="metric",
        location="/towns-cities/regions/hawkes-bay/locations/napier",
        location_name="Napier",
        latitude="-39.49",
        longitude="176.91",
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


async def test_weather_setup_entry_mobile(hass):
    from custom_components.metservice_weather.weather import async_setup_entry
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "name": "Mobile",
            "location": "/towns-cities/regions/auckland/locations/auckland",
            "api": "mobile",
            "mobile_api_key": "key",
            "marine_region": "",
            "tide_url": "",
            "boating_url": "",
            "surf_url": "",
        },
    )
    coord = _make_coordinator(hass, api_type="mobile")
    entry.runtime_data = coord

    added = []

    def add_entities(entities, *args, **kwargs):
        added.extend(entities)

    await async_setup_entry(hass, entry, add_entities)
    assert len(added) == 1
    assert isinstance(added[0], MetServiceForecastMobile)


# ---------------------------------------------------------------------------
# Test: MetServiceForecastPublic properties
# ---------------------------------------------------------------------------

async def test_public_entity_name(hass):
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)
    assert entity.name == "Forecast"


async def test_public_entity_unique_id(hass):
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)
    assert "napier" in entity.unique_id.lower()


async def test_public_entity_temperature(hass):
    coord = _make_coordinator(hass)
    coord.data = MetServicePublicData(temperature=18.5)
    entity = MetServiceForecastPublic(coord)
    assert entity.native_temperature == 18.5


async def test_public_entity_pressure(hass):
    coord = _make_coordinator(hass)
    coord.data = MetServicePublicData(pressure=1013.0)
    entity = MetServiceForecastPublic(coord)
    assert entity.native_pressure == 1013.0


async def test_public_entity_humidity(hass):
    coord = _make_coordinator(hass)
    coord.data = MetServicePublicData(humidity=75)
    entity = MetServiceForecastPublic(coord)
    assert entity.humidity == 75


async def test_public_entity_humidity_none(hass):
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)
    assert entity.humidity is None


async def test_public_entity_wind_speed(hass):
    coord = _make_coordinator(hass)
    coord.data = MetServicePublicData(wind_speed=25.0)
    entity = MetServiceForecastPublic(coord)
    assert entity.native_wind_speed == 25.0


async def test_public_entity_wind_bearing(hass):
    coord = _make_coordinator(hass)
    coord.data = MetServicePublicData(wind_direction="NW")
    entity = MetServiceForecastPublic(coord)
    assert entity.wind_bearing == "NW"


async def test_public_entity_condition_mapped(hass):
    coord = _make_coordinator(hass)
    coord.data = MetServicePublicData(condition="rain")
    entity = MetServiceForecastPublic(coord)
    entity.hass = hass
    with patch("custom_components.metservice_weather.weather.sun_helper.is_up", return_value=True):
        cond = entity.condition
    assert cond == CONDITION_MAP["rain"]


async def test_public_entity_condition_clear_night(hass):
    """'fine' at night → 'clear-night'."""
    coord = _make_coordinator(hass)
    coord.data = MetServicePublicData(condition="fine")
    entity = MetServiceForecastPublic(coord)
    entity.hass = hass
    with patch("custom_components.metservice_weather.weather.sun_helper.is_up", return_value=False):
        cond = entity.condition
    assert cond == "clear-night"


async def test_public_entity_condition_unknown_passthrough(hass):
    """Unmapped condition is passed through as-is."""
    coord = _make_coordinator(hass)
    coord.data = MetServicePublicData(condition="unknown-condition")
    entity = MetServiceForecastPublic(coord)
    entity.hass = hass
    with patch("custom_components.metservice_weather.weather.sun_helper.is_up", return_value=True):
        cond = entity.condition
    assert cond == "unknown-condition"


async def test_public_entity_temperature_units(hass):
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)
    assert entity.native_temperature_unit is not None


async def test_public_entity_pressure_units(hass):
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)
    assert entity.native_pressure_unit is not None


async def test_public_entity_wind_speed_units(hass):
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)
    assert entity.native_wind_speed_unit is not None


async def test_public_entity_precipitation_units(hass):
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
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)
    result = entity.forecast_hourly
    assert result == []


async def test_public_forecast_hourly_with_data(hass):
    coord = _make_coordinator(hass)
    coord.data = MetServicePublicData(
        hourly_entries=[
            HourlyEntry(datetime="2024-06-15T10:00:00+12:00", temperature=18.0, rainfall=0.0, wind_speed=15.0, wind_direction="NW"),
            HourlyEntry(datetime="2024-06-15T22:00:00+12:00", temperature=12.0, rainfall=0.0, wind_speed=10.0, wind_direction="SW"),
        ],
        hourly_obs=2,
        hourly_skip=0,
    )
    entity = MetServiceForecastPublic(coord)
    result = entity.forecast_hourly
    assert len(result) == 2
    assert result[0]["native_temperature"] == 18.0


async def test_public_forecast_hourly_heavy_rain_icon(hass):
    coord = _make_coordinator(hass)
    coord.data = _hourly_data(datetime="2024-06-15T10:00:00+12:00", temperature=10.0, rainfall=10.0, wind_speed=5.0, wind_direction="N")
    entity = MetServiceForecastPublic(coord)
    assert entity.forecast_hourly[0]["condition"] == "pouring"


async def test_public_forecast_hourly_light_rain_icon(hass):
    coord = _make_coordinator(hass)
    coord.data = _hourly_data(datetime="2024-06-15T10:00:00+12:00", temperature=12.0, rainfall=2.0, wind_speed=5.0, wind_direction="N")
    entity = MetServiceForecastPublic(coord)
    assert entity.forecast_hourly[0]["condition"] == "rainy"


async def test_public_forecast_hourly_windy_icon(hass):
    coord = _make_coordinator(hass)
    coord.data = _hourly_data(datetime="2024-06-15T14:00:00+12:00", temperature=15.0, rainfall=0.0, wind_speed=50.0, wind_direction="SW")
    entity = MetServiceForecastPublic(coord)
    assert entity.forecast_hourly[0]["condition"] == "windy"


async def test_public_forecast_hourly_night_icon(hass):
    coord = _make_coordinator(hass)
    coord.data = _hourly_data(datetime="2024-06-15T22:00:00+12:00", temperature=8.0, rainfall=0.0, wind_speed=5.0, wind_direction="N")
    entity = MetServiceForecastPublic(coord)
    assert entity.forecast_hourly[0]["condition"] == "clear-night"


async def test_public_forecast_hourly_skip_offsets_start(hass):
    """hourly_skip causes the first N entries to be excluded."""
    coord = _make_coordinator(hass)
    coord.data = MetServicePublicData(
        hourly_entries=[
            HourlyEntry(datetime="2024-06-15T08:00:00+12:00", temperature=10.0, rainfall=0.0, wind_speed=5.0),
            HourlyEntry(datetime="2024-06-15T10:00:00+12:00", temperature=18.0, rainfall=0.0, wind_speed=5.0),
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
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)
    result = entity.forecast_daily
    assert result == []


async def test_public_forecast_daily_with_data(hass):
    coord = _make_coordinator(hass)
    coord.data = MetServicePublicData(
        daily_entries=[
            DailyEntry(condition="fine", temp_high=22.0, temp_low=12.0, datetime="2024-06-15", description="Sunny day", rainfall_low=0.0, rainfall_high=1.0),
            DailyEntry(condition="cloudy", temp_high=18.0, temp_low=10.0, datetime="2024-06-16"),
        ]
    )
    entity = MetServiceForecastPublic(coord)
    result = entity.forecast_daily
    assert len(result) == 2
    assert result[0]["native_temperature"] == 22.0
    assert result[0]["native_templow"] == 12.0
    assert result[0]["condition"] == CONDITION_MAP["fine"]


async def test_public_forecast_daily_precipitation_fields(hass):
    """rainfall_low is mapped to the standard native_precipitation key."""
    coord = _make_coordinator(hass)
    coord.data = MetServicePublicData(
        daily_entries=[DailyEntry(condition="rain", temp_high=15.0, temp_low=8.0, datetime="2024-06-15", rainfall_low=2.0, rainfall_high=8.0)]
    )
    entity = MetServiceForecastPublic(coord)
    result = entity.forecast_daily
    assert result[0]["native_precipitation"] == 2.0
    assert "precipitation_low_mm" not in result[0]
    assert "precipitation_high_mm" not in result[0]


async def test_public_async_forecast_hourly(hass):
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)
    result = await entity.async_forecast_hourly()
    assert result == []


async def test_public_async_forecast_daily(hass):
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)
    result = await entity.async_forecast_daily()
    assert result == []


async def test_public_extra_state_attributes_is_none(hass):
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)
    assert entity.extra_state_attributes is None


# ---------------------------------------------------------------------------
# Test: MetServiceForecastMobile properties
# ---------------------------------------------------------------------------

async def test_mobile_entity_name(hass):
    coord = _make_coordinator(hass, api_type="mobile")
    entity = MetServiceForecastMobile(coord)
    assert entity.name == "Forecast"


async def test_mobile_entity_temperature(hass):
    coord = _make_coordinator(hass, api_type="mobile")
    entity = MetServiceForecastMobile(coord)
    with patch.object(coord, "get_current_mobile", return_value=16.0):
        assert entity.native_temperature == 16.0


async def test_mobile_entity_pressure(hass):
    coord = _make_coordinator(hass, api_type="mobile")
    entity = MetServiceForecastMobile(coord)
    with patch.object(coord, "get_current_mobile", return_value=1010.0):
        assert entity.native_pressure == 1010.0


async def test_mobile_entity_humidity(hass):
    coord = _make_coordinator(hass, api_type="mobile")
    entity = MetServiceForecastMobile(coord)
    with patch.object(coord, "get_current_mobile", return_value=80):
        assert entity.humidity == 80


async def test_mobile_entity_wind_speed(hass):
    coord = _make_coordinator(hass, api_type="mobile")
    entity = MetServiceForecastMobile(coord)
    with patch.object(coord, "get_current_mobile", return_value=30.0):
        assert entity.native_wind_speed == 30.0


async def test_mobile_entity_wind_bearing(hass):
    coord = _make_coordinator(hass, api_type="mobile")
    entity = MetServiceForecastMobile(coord)
    with patch.object(coord, "get_current_mobile", return_value="SE"):
        assert entity.wind_bearing == "SE"


async def test_mobile_entity_condition_mapped(hass):
    coord = _make_coordinator(hass, api_type="mobile")
    entity = MetServiceForecastMobile(coord)
    entity.hass = hass
    with patch.object(coord, "get_current_mobile", return_value="cloudy"), \
         patch("custom_components.metservice_weather.weather.sun_helper.is_up", return_value=True):
        cond = entity.condition
    assert cond == "cloudy"


async def test_mobile_entity_condition_clear_night(hass):
    coord = _make_coordinator(hass, api_type="mobile")
    entity = MetServiceForecastMobile(coord)
    entity.hass = hass
    with patch.object(coord, "get_current_mobile", return_value="fine"), \
         patch("custom_components.metservice_weather.weather.sun_helper.is_up", return_value=False):
        cond = entity.condition
    assert cond == "clear-night"


async def test_mobile_entity_units(hass):
    coord = _make_coordinator(hass, api_type="mobile")
    entity = MetServiceForecastMobile(coord)
    assert entity.native_temperature_unit is not None
    assert entity.native_pressure_unit is not None
    assert entity.native_wind_speed_unit is not None
    assert entity.native_precipitation_unit is not None


# ---------------------------------------------------------------------------
# Test: MetServiceForecastMobile forecasts
# ---------------------------------------------------------------------------

async def test_mobile_forecast_hourly_empty_when_no_data(hass):
    coord = _make_coordinator(hass, api_type="mobile")
    entity = MetServiceForecastMobile(coord)
    with patch.object(coord, "get_current_mobile", return_value=None):
        result = entity.forecast_hourly
    assert result == []


async def test_mobile_forecast_hourly_with_data(hass):
    coord = _make_coordinator(hass, api_type="mobile")
    entity = MetServiceForecastMobile(coord)

    hourly_data = [
        {
            "dateISO": "2024-06-15T10:00:00+12:00",
            "temperature": 18.0,
            "rainFall": 0.0,
            "windSpeed": 20.0,
            "windDir": "NW",
        },
        {
            "dateISO": "2024-06-15T22:00:00+12:00",
            "temperature": 11.0,
            "rainFall": 0.0,
            "windSpeed": 10.0,
            "windDir": "S",
        },
    ]

    with patch.object(coord, "get_current_mobile", return_value=hourly_data):
        result = entity.forecast_hourly

    assert len(result) == 2
    assert result[0]["native_temperature"] == 18.0


async def test_mobile_forecast_hourly_heavy_rain(hass):
    coord = _make_coordinator(hass, api_type="mobile")
    entity = MetServiceForecastMobile(coord)

    hourly_data = [{
        "dateISO": "2024-06-15T14:00:00+12:00",
        "temperature": 10.0,
        "rainFall": 8.0,  # > 6 → pouring
        "windSpeed": 5.0,
        "windDir": "N",
    }]

    with patch.object(coord, "get_current_mobile", return_value=hourly_data):
        result = entity.forecast_hourly

    assert result[0]["condition"] == "pouring"


async def test_mobile_forecast_hourly_light_rain(hass):
    coord = _make_coordinator(hass, api_type="mobile")
    entity = MetServiceForecastMobile(coord)

    hourly_data = [{
        "dateISO": "2024-06-15T14:00:00+12:00",
        "temperature": 12.0,
        "rainFall": 3.0,  # > 0 and <= 6 → rainy
        "windSpeed": 5.0,
        "windDir": "N",
    }]

    with patch.object(coord, "get_current_mobile", return_value=hourly_data):
        result = entity.forecast_hourly

    assert result[0]["condition"] == "rainy"


async def test_mobile_forecast_hourly_windy(hass):
    coord = _make_coordinator(hass, api_type="mobile")
    entity = MetServiceForecastMobile(coord)

    hourly_data = [{
        "dateISO": "2024-06-15T14:00:00+12:00",
        "temperature": 15.0,
        "rainFall": 0.0,
        "windSpeed": 50.0,  # > 40 → windy
        "windDir": "SW",
    }]

    with patch.object(coord, "get_current_mobile", return_value=hourly_data):
        result = entity.forecast_hourly

    assert result[0]["condition"] == "windy"


async def test_mobile_forecast_hourly_night(hass):
    coord = _make_coordinator(hass, api_type="mobile")
    entity = MetServiceForecastMobile(coord)

    hourly_data = [{
        "dateISO": "2024-06-15T22:00:00+12:00",
        "temperature": 8.0,
        "rainFall": 0.0,
        "windSpeed": 5.0,
        "windDir": "N",
    }]

    with patch.object(coord, "get_current_mobile", return_value=hourly_data):
        result = entity.forecast_hourly

    assert result[0]["condition"] == "clear-night"


async def test_mobile_forecast_daily_empty(hass):
    coord = _make_coordinator(hass, api_type="mobile")
    entity = MetServiceForecastMobile(coord)
    with patch.object(coord, "get_forecast_daily_mobile", return_value=0):
        result = entity.forecast_daily
    assert result == []


async def test_mobile_forecast_daily_with_data(hass):
    coord = _make_coordinator(hass, api_type="mobile")
    entity = MetServiceForecastMobile(coord)

    def _mock_daily(field, day):
        if field == "":
            return 2
        if field == "daily_condition":
            return "rain"
        if field == "daily_temp_high":
            return 15.0
        if field == "daily_temp_low":
            return 8.0
        if field == "daily_datetime":
            return "2024-06-15"
        if field == "daily_description":
            return "Rainy day"
        return None

    with patch.object(coord, "get_forecast_daily_mobile", side_effect=_mock_daily):
        result = entity.forecast_daily

    assert len(result) == 2
    assert result[0]["condition"] == CONDITION_MAP["rain"]


async def test_mobile_async_forecast_hourly(hass):
    coord = _make_coordinator(hass, api_type="mobile")
    entity = MetServiceForecastMobile(coord)
    with patch.object(coord, "get_current_mobile", return_value=None):
        result = await entity.async_forecast_hourly()
    assert result == []


async def test_mobile_async_forecast_daily(hass):
    coord = _make_coordinator(hass, api_type="mobile")
    entity = MetServiceForecastMobile(coord)
    with patch.object(coord, "get_forecast_daily_mobile", return_value=0):
        result = await entity.async_forecast_daily()
    assert result == []


async def test_mobile_extra_state_attributes_is_none(hass):
    coord = _make_coordinator(hass, api_type="mobile")
    entity = MetServiceForecastMobile(coord)
    assert entity.extra_state_attributes is None


async def test_entity_unavailable_when_coordinator_fails(hass):
    coord = _make_coordinator(hass)
    coord.last_update_success = False
    entity = MetServiceForecastPublic(coord)
    assert entity.available is False


# ---------------------------------------------------------------------------
# Test: forecast caching — public
# ---------------------------------------------------------------------------

async def test_public_async_forecast_hourly_populates_cache(hass):
    coord = _make_coordinator(hass)
    coord.data = MetServicePublicData(
        hourly_entries=[HourlyEntry(datetime="2024-06-15T10:00:00+12:00", temperature=20.0, rainfall=0.0, wind_speed=10.0)],
        hourly_obs=1,
        hourly_skip=0,
    )
    entity = MetServiceForecastPublic(coord)
    assert entity._forecast_hourly_cache is None
    result = await entity.async_forecast_hourly()
    assert result is not None and len(result) == 1
    assert entity._forecast_hourly_cache is result


async def test_public_async_forecast_daily_populates_cache(hass):
    coord = _make_coordinator(hass)
    coord.data = MetServicePublicData(
        daily_entries=[DailyEntry(condition="fine", temp_high=22.0, temp_low=12.0, datetime="2024-06-15")]
    )
    entity = MetServiceForecastPublic(coord)
    assert entity._forecast_daily_cache is None
    result = await entity.async_forecast_daily()
    assert result is not None and len(result) == 1
    assert entity._forecast_daily_cache is result


async def test_public_async_forecast_hourly_returns_same_object_on_second_call(hass):
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)
    result1 = await entity.async_forecast_hourly()
    result2 = await entity.async_forecast_hourly()
    assert result1 is result2


async def test_public_async_forecast_daily_returns_same_object_on_second_call(hass):
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)
    result1 = await entity.async_forecast_daily()
    result2 = await entity.async_forecast_daily()
    assert result1 is result2


async def test_public_handle_coordinator_update_clears_cache(hass):
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
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)
    entity.hass = hass
    with patch.object(entity, "async_write_ha_state"), \
         patch.object(entity, "async_update_listeners", new_callable=AsyncMock) as mock_listeners:
        entity._handle_coordinator_update()
    mock_listeners.assert_called_once_with(None)


# ---------------------------------------------------------------------------
# Test: forecast caching — mobile
# ---------------------------------------------------------------------------

async def test_mobile_async_forecast_hourly_populates_cache(hass):
    coord = _make_coordinator(hass, api_type="mobile")
    entity = MetServiceForecastMobile(coord)
    hourly_data = [{"dateISO": "2024-06-15T10:00:00+12:00", "temperature": 18.0, "rainFall": 0.0, "windSpeed": 10.0, "windDir": "N"}]
    assert entity._forecast_hourly_cache is None
    with patch.object(coord, "get_current_mobile", return_value=hourly_data):
        result = await entity.async_forecast_hourly()
    assert result is not None and len(result) == 1
    assert entity._forecast_hourly_cache is result


async def test_mobile_async_forecast_daily_populates_cache(hass):
    coord = _make_coordinator(hass, api_type="mobile")
    entity = MetServiceForecastMobile(coord)

    def _mock_daily(field, day):
        if field == "":
            return 1
        if field == "daily_condition":
            return "fine"
        if field == "daily_temp_high":
            return 20.0
        if field == "daily_temp_low":
            return 10.0
        if field == "daily_datetime":
            return "2024-06-15"
        if field == "daily_description":
            return None
        return None

    assert entity._forecast_daily_cache is None
    with patch.object(coord, "get_forecast_daily_mobile", side_effect=_mock_daily):
        result = await entity.async_forecast_daily()
    assert result is not None and len(result) == 1
    assert entity._forecast_daily_cache is result


async def test_mobile_handle_coordinator_update_clears_cache(hass):
    coord = _make_coordinator(hass, api_type="mobile")
    entity = MetServiceForecastMobile(coord)
    entity.hass = hass
    entity._forecast_hourly_cache = []
    entity._forecast_daily_cache = []
    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()
    assert entity._forecast_hourly_cache is None
    assert entity._forecast_daily_cache is None


async def test_mobile_handle_coordinator_update_schedules_listeners(hass):
    coord = _make_coordinator(hass, api_type="mobile")
    entity = MetServiceForecastMobile(coord)
    entity.hass = hass
    with patch.object(entity, "async_write_ha_state"), \
         patch.object(entity, "async_update_listeners", new_callable=AsyncMock) as mock_listeners:
        entity._handle_coordinator_update()
    mock_listeners.assert_called_once_with(None)
