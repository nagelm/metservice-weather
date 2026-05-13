"""Tests for WeatherSensor entity and weather_current_conditions_sensors helpers."""
from __future__ import annotations

import datetime
from unittest.mock import patch


from custom_components.metservice_weather.coordinator import (
    WeatherUpdateCoordinator,
    WeatherUpdateCoordinatorConfig,
)
from custom_components.metservice_weather.sensor import WeatherSensor
from custom_components.metservice_weather.weather_current_conditions_sensors import (
    WeatherSensorEntityDescription,
    _safe_float,
    _safe_int,
    _next_tide_time,
    current_condition_sensor_descriptions_public,
    current_condition_sensor_descriptions_mobile,
)
from custom_components.metservice_weather.coordinator_types import MetServicePublicData


# ---------------------------------------------------------------------------
# Helper: minimal coordinator with pre-loaded data
# ---------------------------------------------------------------------------

def _make_coordinator(hass, api_type="public") -> WeatherUpdateCoordinator:
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
        tide_url="",
        boating_url="",
        surf_url="",
    )
    coord = WeatherUpdateCoordinator(hass, config)
    coord.data = MetServicePublicData()
    return coord


def _make_sensor(coordinator, key="temperature", value=18.5) -> WeatherSensor:
    """Create a WeatherSensor with the simplest possible description."""
    desc = WeatherSensorEntityDescription(
        key=key,
        name="Test Sensor",
        value_fn=lambda data, _: data,
        attr_fn=lambda data: {"raw": data} if data else {},
    )
    with patch.object(coordinator, "get_current_public", return_value=value):
        sensor = WeatherSensor(coordinator, desc)
    return sensor


# ---------------------------------------------------------------------------
# Test: helper functions in weather_current_conditions_sensors.py
# ---------------------------------------------------------------------------

def test_safe_float_none():
    assert _safe_float(None) is None


def test_safe_float_valid():
    assert _safe_float("18.5") == 18.5
    assert _safe_float(18.5) == 18.5


def test_safe_float_invalid():
    assert _safe_float("n/a") is None
    assert _safe_float("") is None


def test_safe_int_none():
    assert _safe_int(None) is None


def test_safe_int_valid():
    assert _safe_int("5") == 5
    assert _safe_int(5) == 5


def test_safe_int_invalid():
    assert _safe_int("n/a") is None


def test_next_tide_time_not_list():
    assert _next_tide_time(None, "HIGH") is None
    assert _next_tide_time({}, "HIGH") is None


def test_next_tide_time_future():
    future = (datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=2)).isoformat()
    tides = [{"type": "HIGH", "time": future}]
    result = _next_tide_time(tides, "HIGH")
    assert result is not None


def test_next_tide_time_past_returns_none():
    past = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=2)).isoformat()
    tides = [{"type": "HIGH", "time": past}]
    result = _next_tide_time(tides, "HIGH")
    assert result is None


def test_next_tide_time_wrong_type_returns_none():
    future = (datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=2)).isoformat()
    tides = [{"type": "LOW", "time": future}]
    result = _next_tide_time(tides, "HIGH")
    assert result is None


# ---------------------------------------------------------------------------
# Test: sensor descriptions are non-empty lists
# ---------------------------------------------------------------------------

def test_public_sensor_descriptions_non_empty():
    assert len(current_condition_sensor_descriptions_public) > 0


def test_mobile_sensor_descriptions_non_empty():
    assert len(current_condition_sensor_descriptions_mobile) > 0


# ---------------------------------------------------------------------------
# Test: WeatherSensor properties
# ---------------------------------------------------------------------------

async def test_sensor_name(hass):
    coord = _make_coordinator(hass)
    sensor = _make_sensor(coord, value=20.0)
    assert sensor.name == "Test Sensor"


async def test_sensor_native_value_with_data(hass):
    coord = _make_coordinator(hass)
    sensor = _make_sensor(coord, value=18.5)
    # _sensor_data was set to 18.5 in the constructor; value_fn just returns data
    assert sensor.native_value == 18.5


async def test_sensor_native_value_none_data(hass):
    coord = _make_coordinator(hass)
    sensor = _make_sensor(coord, value=None)
    assert sensor.native_value is None


async def test_sensor_native_value_fn_error_returns_none(hass):
    """If value_fn raises, native_value returns None without crashing."""
    coord = _make_coordinator(hass)
    desc = WeatherSensorEntityDescription(
        key="temperature",
        name="Broken Sensor",
        value_fn=lambda data, _: 1 / 0,  # always raises
    )
    with patch.object(coord, "get_current_public", return_value=10.0):
        sensor = WeatherSensor(coord, desc)
    assert sensor.native_value is None


async def test_sensor_extra_state_attributes_with_data(hass):
    coord = _make_coordinator(hass)
    sensor = _make_sensor(coord, value="some text")
    attrs = sensor.extra_state_attributes
    assert attrs == {"raw": "some text"}


async def test_sensor_extra_state_attributes_none_data(hass):
    coord = _make_coordinator(hass)
    sensor = _make_sensor(coord, value=None)
    assert sensor.extra_state_attributes == {}


async def test_sensor_extra_state_attributes_fn_error_returns_empty(hass):
    coord = _make_coordinator(hass)
    desc = WeatherSensorEntityDescription(
        key="temperature",
        name="Broken Attrs",
        value_fn=lambda data, _: data,
        attr_fn=lambda data: 1 / 0,  # always raises
    )
    with patch.object(coord, "get_current_public", return_value="val"):
        sensor = WeatherSensor(coord, desc)
    assert sensor.extra_state_attributes == {}


async def test_sensor_handle_coordinator_update_public(hass):
    coord = _make_coordinator(hass)
    sensor = _make_sensor(coord, value=10.0)
    coord.data = MetServicePublicData(temperature=22.5)
    with patch.object(coord, "get_current_public", return_value=22.5), \
         patch.object(sensor, "async_write_ha_state"):
        sensor._handle_coordinator_update()
    assert sensor._sensor_data == 22.5


async def test_sensor_handle_coordinator_update_mobile(hass):
    coord = _make_coordinator(hass, api_type="mobile")
    desc = WeatherSensorEntityDescription(
        key="temperature",
        name="Mobile Temp",
        value_fn=lambda data, _: data,
    )
    with patch.object(coord, "get_current_mobile", return_value=15.0):
        sensor = WeatherSensor(coord, desc)
    with patch.object(coord, "get_current_mobile", return_value=19.0), \
         patch.object(sensor, "async_write_ha_state"):
        sensor._handle_coordinator_update()
    assert sensor._sensor_data == 19.0


async def test_sensor_available_when_coordinator_failed(hass):
    coord = _make_coordinator(hass)
    coord.last_update_success = False
    sensor = _make_sensor(coord, value=5.0)
    assert sensor.available is False


async def test_sensor_available_when_coordinator_ok(hass):
    coord = _make_coordinator(hass)
    coord.last_update_success = True
    sensor = _make_sensor(coord, value=5.0)
    assert sensor.available is True


# ---------------------------------------------------------------------------
# Test: async_setup_entry creates expected sensors
# ---------------------------------------------------------------------------

async def test_sensor_setup_entry_public_skips_tide_sensors(hass):
    """When no tide URL, tides_high and tides_low are excluded."""
    from custom_components.metservice_weather.sensor import (
        async_setup_entry,
    )
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from custom_components.metservice_weather.const import DOMAIN

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

    with patch.object(coord, "get_current_public", return_value=None):
        await async_setup_entry(hass, entry, add_entities)

    keys = [s.entity_description.key for s in added]
    assert "tides_high" not in keys
    assert "tides_low" not in keys


async def test_sensor_setup_entry_mobile(hass):
    """Mobile API entry creates mobile sensors."""
    from custom_components.metservice_weather.sensor import async_setup_entry
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from custom_components.metservice_weather.const import DOMAIN

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

    with patch.object(coord, "get_current_mobile", return_value=None):
        await async_setup_entry(hass, entry, add_entities)

    assert len(added) > 0
    keys = [s.entity_description.key for s in added]
    assert "tides_high" not in keys
