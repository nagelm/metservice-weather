"""Tests for MetService weather entities (public and mobile)."""
from __future__ import annotations

from unittest.mock import patch


from custom_components.metservice_weather.coordinator import (
    WeatherUpdateCoordinator,
    WeatherUpdateCoordinatorConfig,
)
from custom_components.metservice_weather.const import (
    RESULTS_CURRENT,
    RESULTS_FORECAST_DAILY,
    CONDITION_MAP,
    DOMAIN,
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
    coord.data = {RESULTS_CURRENT: {}, RESULTS_FORECAST_DAILY: {}}
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
    assert entity.name == "Napier Forecast"


async def test_public_entity_unique_id(hass):
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)
    assert "napier" in entity.unique_id.lower()


async def test_public_entity_temperature(hass):
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)
    with patch.object(coord, "get_current_public", return_value=18.5):
        assert entity.native_temperature == 18.5


async def test_public_entity_pressure(hass):
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)
    with patch.object(coord, "get_current_public", return_value=1013.0):
        assert entity.native_pressure == 1013.0


async def test_public_entity_humidity(hass):
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)
    with patch.object(coord, "get_current_public", return_value=75):
        assert entity.humidity == 75


async def test_public_entity_humidity_none(hass):
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)
    with patch.object(coord, "get_current_public", return_value=None):
        assert entity.humidity is None


async def test_public_entity_wind_speed(hass):
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)
    with patch.object(coord, "get_current_public", return_value=25.0):
        assert entity.native_wind_speed == 25.0


async def test_public_entity_wind_bearing(hass):
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)
    with patch.object(coord, "get_current_public", return_value="NW"):
        assert entity.wind_bearing == "NW"


async def test_public_entity_condition_mapped(hass):
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)
    entity.hass = hass
    with patch.object(coord, "get_current_public", return_value="rain"), \
         patch("custom_components.metservice_weather.weather.sun_helper.is_up", return_value=True):
        cond = entity.condition
    assert cond == CONDITION_MAP["rain"]


async def test_public_entity_condition_clear_night(hass):
    """'fine' at night → 'clear-night'."""
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)
    entity.hass = hass
    with patch.object(coord, "get_current_public", return_value="fine"), \
         patch("custom_components.metservice_weather.weather.sun_helper.is_up", return_value=False):
        cond = entity.condition
    assert cond == "clear-night"


async def test_public_entity_condition_unknown_passthrough(hass):
    """Unmapped condition is passed through as-is."""
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)
    entity.hass = hass
    with patch.object(coord, "get_current_public", return_value="unknown-condition"), \
         patch("custom_components.metservice_weather.weather.sun_helper.is_up", return_value=True):
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

async def test_public_forecast_hourly_empty_when_no_data(hass):
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)
    with patch.object(coord, "get_current_public", return_value=None):
        result = entity.forecast_hourly
    assert result == []


async def test_public_forecast_hourly_with_data(hass):
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)

    hourly_data = [
        {
            "date": "2024-06-15T10:00:00+12:00",
            "temperature": 18.0,
            "rainfall": 0.0,
            "wind": {"speed": 15.0, "direction": "NW"},
        },
        {
            "date": "2024-06-15T22:00:00+12:00",
            "temperature": 12.0,
            "rainfall": 0.0,
            "wind": {"speed": 10.0, "direction": "SW"},
        },
    ]

    def _mock_get(field):
        if field == "hourly_temp":
            return hourly_data
        if field == "hourly_obs":
            return 2
        if field == "hourly_skip":
            return 0
        return None

    with patch.object(coord, "get_current_public", side_effect=_mock_get):
        result = entity.forecast_hourly

    assert len(result) == 2
    assert result[0]["temperature"] == 18.0


async def test_public_forecast_hourly_heavy_rain_icon(hass):
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)

    hourly_data = [{
        "date": "2024-06-15T10:00:00+12:00",
        "temperature": 10.0,
        "rainfall": 10.0,  # > 6 → pouring
        "wind": {"speed": 5.0, "direction": "N"},
    }]

    def _mock_get(field):
        if field == "hourly_temp":
            return hourly_data
        if field == "hourly_obs":
            return 1
        if field == "hourly_skip":
            return 0
        return None

    with patch.object(coord, "get_current_public", side_effect=_mock_get):
        result = entity.forecast_hourly

    assert result[0]["condition"] == "pouring"


async def test_public_forecast_hourly_light_rain_icon(hass):
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)

    hourly_data = [{
        "date": "2024-06-15T10:00:00+12:00",
        "temperature": 12.0,
        "rainfall": 2.0,  # > 0 and <= 6 → rainy
        "wind": {"speed": 5.0, "direction": "N"},
    }]

    def _mock_get(field):
        if field == "hourly_temp":
            return hourly_data
        if field == "hourly_obs":
            return 1
        if field == "hourly_skip":
            return 0
        return None

    with patch.object(coord, "get_current_public", side_effect=_mock_get):
        result = entity.forecast_hourly

    assert result[0]["condition"] == "rainy"


async def test_public_forecast_hourly_windy_icon(hass):
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)

    hourly_data = [{
        "date": "2024-06-15T14:00:00+12:00",
        "temperature": 15.0,
        "rainfall": 0.0,
        "wind": {"speed": 50.0, "direction": "SW"},  # > 40 → windy
    }]

    def _mock_get(field):
        if field == "hourly_temp":
            return hourly_data
        if field == "hourly_obs":
            return 1
        if field == "hourly_skip":
            return 0
        return None

    with patch.object(coord, "get_current_public", side_effect=_mock_get):
        result = entity.forecast_hourly

    assert result[0]["condition"] == "windy"


async def test_public_forecast_hourly_night_icon(hass):
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)

    hourly_data = [{
        "date": "2024-06-15T22:00:00+12:00",
        "temperature": 8.0,
        "rainfall": 0.0,
        "wind": {"speed": 5.0, "direction": "N"},
    }]

    def _mock_get(field):
        if field == "hourly_temp":
            return hourly_data
        if field == "hourly_obs":
            return 1
        if field == "hourly_skip":
            return 0
        return None

    with patch.object(coord, "get_current_public", side_effect=_mock_get):
        result = entity.forecast_hourly

    assert result[0]["condition"] == "clear-night"


async def test_public_forecast_hourly_backup_fields(hass):
    """When primary hourly fields are None, backup fields are used."""
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)

    hourly_data = [{
        "date": "2024-06-15T10:00:00+12:00",
        "temperature": 14.0,
        "rainfall": 0.0,
        "wind": {"speed": 10.0, "direction": "N"},
    }]

    def _mock_get(field):
        if field in ("hourly_temp", "hourly_obs", "hourly_skip"):
            return None
        if field == "hourly_bkp_temp":
            return hourly_data
        if field == "hourly_bkp_obs":
            return 1
        if field == "hourly_bkp_skip":
            return 0
        return None

    with patch.object(coord, "get_current_public", side_effect=_mock_get):
        result = entity.forecast_hourly

    assert len(result) == 1


# ---------------------------------------------------------------------------
# Test: MetServiceForecastPublic forecast_daily
# ---------------------------------------------------------------------------

async def test_public_forecast_daily_empty_when_no_days(hass):
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)
    with patch.object(coord, "get_forecast_daily_public", return_value=0):
        result = entity.forecast_daily
    assert result == []


async def test_public_forecast_daily_with_data(hass):
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)

    def _mock_daily(field, day):
        if field == "":
            return 2
        if field == "daily_condition":
            return "fine"
        if field == "daily_temp_high":
            return 22.0
        if field == "daily_temp_low":
            return 12.0
        if field == "daily_datetime":
            return "2024-06-15"
        if field == "daily_description":
            return "Sunny day"
        if field == "daily_rainfall_low":
            return 0.0
        if field == "daily_rainfall_high":
            return 1.0
        return None

    with patch.object(coord, "get_forecast_daily_public", side_effect=_mock_daily):
        result = entity.forecast_daily

    assert len(result) == 2
    assert result[0]["temperature"] == 22.0
    assert result[0]["templow"] == 12.0
    assert result[0]["condition"] == CONDITION_MAP["fine"]


async def test_public_forecast_daily_backup_temp_fields(hass):
    """Rural areas: backup temp/datetime fields used when primary is None."""
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)

    def _mock_daily(field, day):
        if field == "":
            return 1
        if field in ("daily_temp_high", "daily_temp_low", "daily_datetime"):
            return None
        if field == "daily_bkp_temp_high":
            return 20.0
        if field == "daily_bkp_temp_low":
            return 10.0
        if field == "daily_bkp_datetime":
            return "2024-06-15"
        if field == "daily_condition":
            return "cloudy"
        if field in ("daily_rainfall_low", "daily_rainfall_high", "daily_description"):
            return None
        return None

    with patch.object(coord, "get_forecast_daily_public", side_effect=_mock_daily):
        result = entity.forecast_daily

    assert result[0]["temperature"] == 20.0


async def test_public_async_forecast_hourly(hass):
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)
    with patch.object(coord, "get_current_public", return_value=None):
        result = await entity.async_forecast_hourly()
    assert result == []


async def test_public_async_forecast_daily(hass):
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)
    with patch.object(coord, "get_forecast_daily_public", return_value=0):
        result = await entity.async_forecast_daily()
    assert result == []


async def test_public_extra_state_attributes(hass):
    coord = _make_coordinator(hass)
    entity = MetServiceForecastPublic(coord)
    with patch.object(coord, "get_current_public", return_value=None), \
         patch.object(coord, "get_forecast_daily_public", return_value=0):
        attrs = entity.extra_state_attributes
    assert "forecast_hourly" in attrs
    assert "forecast_daily" in attrs


# ---------------------------------------------------------------------------
# Test: MetServiceForecastMobile properties
# ---------------------------------------------------------------------------

async def test_mobile_entity_name(hass):
    coord = _make_coordinator(hass, api_type="mobile")
    entity = MetServiceForecastMobile(coord)
    assert entity.name == "Napier Forecast"


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
    assert result[0]["temperature"] == 18.0


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


async def test_mobile_extra_state_attributes(hass):
    coord = _make_coordinator(hass, api_type="mobile")
    entity = MetServiceForecastMobile(coord)
    with patch.object(coord, "get_current_mobile", return_value=None), \
         patch.object(coord, "get_forecast_daily_mobile", return_value=0):
        attrs = entity.extra_state_attributes
    assert "forecast_hourly" in attrs
    assert "forecast_daily" in attrs


async def test_entity_unavailable_when_coordinator_fails(hass):
    coord = _make_coordinator(hass)
    coord.last_update_success = False
    entity = MetServiceForecastPublic(coord)
    assert entity.available is False
