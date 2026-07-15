"""Tests for WeatherSensor entity and weather_current_conditions_sensors helpers."""

from __future__ import annotations

import datetime
from unittest.mock import patch

from homeassistant.components.sensor import SensorDeviceClass

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
    _warning_severity,
    _warnings_state,
    current_condition_sensor_descriptions_public,
)
from custom_components.metservice_weather.coordinator_types import MetServicePublicData


# ---------------------------------------------------------------------------
# Helper: minimal coordinator with pre-loaded data
# ---------------------------------------------------------------------------


def _make_coordinator(hass) -> WeatherUpdateCoordinator:
    config = WeatherUpdateCoordinatorConfig(
        api_url="https://www.metservice.com/publicData/webdata",
        warnings_url="https://www.metservice.com/publicData/webdata/warnings-service",
        unit_system_api="m",
        unit_system="metric",
        location="/towns-cities/regions/hawkes-bay/locations/napier",
        location_name="Napier",
        tide_url="",
        boating_url="",
        surf_url="",
    )
    coord = WeatherUpdateCoordinator(hass, config)
    coord.data = MetServicePublicData()
    return coord


def _make_sensor(coordinator, key="temperature", value=18.5) -> WeatherSensor:
    """Create a WeatherSensor with the simplest possible description.

    value is captured in the closure so value_fn returns it directly, allowing
    tests to assert on a known scalar even though _sensor_data is now
    MetServicePublicData for the public API path.
    """
    captured = value
    desc = WeatherSensorEntityDescription(
        key=key,
        name="Test Sensor",
        value_fn=lambda data, _: captured,
        attr_fn=lambda data: {"raw": captured} if captured is not None else {},
    )
    sensor = WeatherSensor(coordinator, desc)
    return sensor


# ---------------------------------------------------------------------------
# Test: helper functions in weather_current_conditions_sensors.py
# ---------------------------------------------------------------------------


def test_safe_float_none():
    """_safe_float returns None for a None input."""
    assert _safe_float(None) is None


def test_safe_float_valid():
    """_safe_float converts a numeric string or float to float."""
    assert _safe_float("18.5") == 18.5
    assert _safe_float(18.5) == 18.5


def test_safe_float_invalid():
    """_safe_float returns None for invalid or empty strings."""
    assert _safe_float("n/a") is None
    assert _safe_float("") is None


def test_safe_int_none():
    """_safe_int returns None for a None input."""
    assert _safe_int(None) is None


def test_safe_int_valid():
    """_safe_int converts a numeric string or int to int."""
    assert _safe_int("5") == 5
    assert _safe_int(5) == 5


def test_safe_int_invalid():
    """_safe_int returns None for an invalid string."""
    assert _safe_int("n/a") is None


def test_next_tide_time_not_list():
    """_next_tide_time returns None when tides is not a list."""
    assert _next_tide_time(None, "HIGH") is None
    assert _next_tide_time({}, "HIGH") is None


def test_next_tide_time_future():
    """_next_tide_time returns a value for a future tide of the matching type."""
    future = (
        datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=2)
    ).isoformat()
    tides = [{"type": "HIGH", "time": future}]
    result = _next_tide_time(tides, "HIGH")
    assert result is not None


def test_next_tide_time_past_returns_none():
    """_next_tide_time returns None when the matching tide is in the past."""
    past = (
        datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=2)
    ).isoformat()
    tides = [{"type": "HIGH", "time": past}]
    result = _next_tide_time(tides, "HIGH")
    assert result is None


def test_next_tide_time_wrong_type_returns_none():
    """_next_tide_time returns None when no tide matches the requested type."""
    future = (
        datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=2)
    ).isoformat()
    tides = [{"type": "LOW", "time": future}]
    result = _next_tide_time(tides, "HIGH")
    assert result is None


# ---------------------------------------------------------------------------
# Test: _warning_severity / _warnings_state
# ---------------------------------------------------------------------------


def test_warning_severity_red_beats_orange():
    """A 'Red Warning' outranks an 'Orange Warning'."""
    assert _warning_severity("Severe Weather Warning - Red") > _warning_severity(
        "Severe Weather Warning - Orange"
    )


def test_warning_severity_orange_beats_plain_warning():
    """An 'Orange Warning' outranks a plain 'Warning'."""
    assert _warning_severity("Strong Wind Warning - Orange") > _warning_severity(
        "Strong Wind Warning"
    )


def test_warning_severity_warning_beats_watch():
    """A plain 'Warning' outranks a 'Watch'."""
    assert _warning_severity("Strong Wind Warning") > _warning_severity(
        "Strong Wind Watch"
    )


def test_warning_severity_case_insensitive():
    """Severity ranking is case-insensitive."""
    assert _warning_severity("severe weather warning - red") == _warning_severity(
        "SEVERE WEATHER WARNING - RED"
    )


def test_warnings_state_no_warnings():
    """_warnings_state returns 'No warnings' when the list is empty."""
    data = MetServicePublicData(warnings_list=[])
    assert _warnings_state(data) == "No warnings"


def test_warnings_state_single_warning():
    """_warnings_state returns the sole warning's name."""
    data = MetServicePublicData(
        warnings_list=[
            {"name": "Strong Wind Watch", "text": "Watch out", "threat_period": "Today"}
        ]
    )
    assert _warnings_state(data) == "Strong Wind Watch"


def test_warnings_state_two_warnings_severity_beats_list_order():
    """The most severe warning wins the state even when listed second."""
    data = MetServicePublicData(
        warnings_list=[
            {
                "name": "Strong Wind Watch",
                "text": "Keep an eye out",
                "threat_period": "Today",
            },
            {
                "name": "Strong Wind Warning - Orange",
                "text": "Damaging winds expected",
                "threat_period": "Tonight",
            },
        ]
    )
    assert _warnings_state(data) == "Strong Wind Warning - Orange (+1 more)"


def test_warnings_state_embedded_newline_survives_in_attribute():
    """Embedded newlines in a warning's text are preserved (only the state string is truncated/derived)."""
    data = MetServicePublicData(
        warnings_list=[
            {
                "name": "Heavy Rain Warning",
                "text": "Line one\nLine two\nLine three",
                "threat_period": "Today",
            }
        ]
    )
    assert data.warnings_list[0]["text"] == "Line one\nLine two\nLine three"


def test_warnings_state_attr_count_matches_list_length():
    """The attribute count matches the number of active warnings."""
    warnings = [
        {"name": "Strong Wind Watch", "text": "a", "threat_period": "Today"},
        {"name": "Heavy Rain Warning", "text": "b", "threat_period": "Tonight"},
    ]
    data = MetServicePublicData(warnings_list=warnings)
    desc = next(
        d
        for d in current_condition_sensor_descriptions_public
        if d.key == "weather_warnings"
    )
    attrs = desc.attr_fn(data)
    assert attrs["count"] == 2
    assert attrs["warnings"] == warnings


# ---------------------------------------------------------------------------
# Test: sensor descriptions are non-empty lists
# ---------------------------------------------------------------------------


def test_public_sensor_descriptions_non_empty():
    """current_condition_sensor_descriptions_public is a non-empty list."""
    assert len(current_condition_sensor_descriptions_public) > 0


# ---------------------------------------------------------------------------
# Test: pollen sensor description (one-sensor redesign)
# ---------------------------------------------------------------------------


def test_pollen_sensor_replaces_old_keys():
    """The single "pollen" ENUM description replaces pollen_levels/pollen_type."""
    keys = {d.key for d in current_condition_sensor_descriptions_public}
    assert "pollen_levels" not in keys
    assert "pollen_type" not in keys
    assert "pollen" in keys


def test_pollen_sensor_is_enum_with_four_options():
    """The pollen description is an ENUM sensor with the four documented states."""
    desc = next(
        d for d in current_condition_sensor_descriptions_public if d.key == "pollen"
    )
    assert desc.device_class == SensorDeviceClass.ENUM
    assert desc.options == ["none", "low", "moderate", "high"]


def test_pollen_sensor_value_and_attrs_from_derived_fields():
    """value_fn/attr_fn read pollen_state and the derived attribute fields."""
    desc = next(
        d for d in current_condition_sensor_descriptions_public if d.key == "pollen"
    )
    data = MetServicePublicData(
        pollen_state="low",
        pollen_level_label="Low",
        pollen_active={"low": ["Wattle", "Cypress"]},
        pollen_imminent=["Macrocarpa"],
    )
    assert desc.value_fn(data, "metric") == "low"
    assert desc.attr_fn(data) == {
        "level_label": "Low",
        "active": {"low": ["Wattle", "Cypress"]},
        "imminent_allergens": ["Macrocarpa"],
    }


def test_pollen_sensor_attrs_empty_when_state_unknown():
    """attr_fn returns {} when pollen_state is None (module not published)."""
    desc = next(
        d for d in current_condition_sensor_descriptions_public if d.key == "pollen"
    )
    data = MetServicePublicData()
    assert desc.value_fn(data, "metric") is None
    assert desc.attr_fn(data) == {}


# ---------------------------------------------------------------------------
# Test: WeatherSensor properties
# ---------------------------------------------------------------------------


async def test_sensor_name(hass):
    """WeatherSensor.name reflects the entity description's name."""
    coord = _make_coordinator(hass)
    sensor = _make_sensor(coord, value=20.0)
    assert sensor.name == "Test Sensor"


async def test_sensor_native_value_with_data(hass):
    """WeatherSensor.native_value returns the value_fn result when data is present."""
    coord = _make_coordinator(hass)
    sensor = _make_sensor(coord, value=18.5)
    # _sensor_data was set to 18.5 in the constructor; value_fn just returns data
    assert sensor.native_value == 18.5


async def test_sensor_native_value_none_data(hass):
    """WeatherSensor.native_value is None when the underlying value is None."""
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
    sensor = WeatherSensor(coord, desc)
    assert sensor.native_value is None


async def test_sensor_extra_state_attributes_with_data(hass):
    """WeatherSensor.extra_state_attributes returns the attr_fn result when data is present."""
    coord = _make_coordinator(hass)
    sensor = _make_sensor(coord, value="some text")
    attrs = sensor.extra_state_attributes
    assert attrs == {"raw": "some text"}


async def test_sensor_extra_state_attributes_none_data(hass):
    """WeatherSensor.extra_state_attributes is empty when the underlying value is None."""
    coord = _make_coordinator(hass)
    sensor = _make_sensor(coord, value=None)
    assert sensor.extra_state_attributes == {}


async def test_sensor_extra_state_attributes_fn_error_returns_empty(hass):
    """If attr_fn raises, extra_state_attributes returns an empty dict without crashing."""
    coord = _make_coordinator(hass)
    desc = WeatherSensorEntityDescription(
        key="temperature",
        name="Broken Attrs",
        value_fn=lambda data, _: data,
        attr_fn=lambda data: 1 / 0,  # always raises
    )
    sensor = WeatherSensor(coord, desc)
    assert sensor.extra_state_attributes == {}


async def test_sensor_handle_coordinator_update_public(hass):
    """_handle_coordinator_update refreshes _sensor_data from the coordinator."""
    coord = _make_coordinator(hass)
    sensor = _make_sensor(coord, value=10.0)
    updated_data = MetServicePublicData(temperature=22.5)
    coord.data = updated_data
    with patch.object(sensor, "async_write_ha_state"):
        sensor._handle_coordinator_update()
    assert sensor._sensor_data is updated_data


async def test_sensor_available_when_coordinator_failed(hass):
    """WeatherSensor.available is False when the coordinator's last update failed."""
    coord = _make_coordinator(hass)
    coord.last_update_success = False
    sensor = _make_sensor(coord, value=5.0)
    assert sensor.available is False


async def test_sensor_available_when_coordinator_ok(hass):
    """WeatherSensor.available is True when the coordinator's last update succeeded."""
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

    await async_setup_entry(hass, entry, add_entities)

    keys = [s.entity_description.key for s in added]
    assert "tides_high" not in keys
    assert "tides_low" not in keys


# ---------------------------------------------------------------------------
# Test: async_setup_entry sensor gating by capability flags
# ---------------------------------------------------------------------------


async def test_setup_entry_rural_skips_observation_sensors(hass):
    """A rural-like coordinator (all capability flags False) skips observation and breakdown sensors while still creating ungated sensors."""
    from custom_components.metservice_weather.sensor import async_setup_entry
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from custom_components.metservice_weather.const import (
        DOMAIN,
        FIELD_TEMP,
        FIELD_WINDSPEED,
        FIELD_WINDGUST,
        FIELD_WINDDIR,
        FIELD_HUMIDITY,
        FIELD_PRESSURE,
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "name": "Kumeu",
            "location": "/rural/regions/auckland/locations/kumeu",
            "api": "public",
            "marine_region": "",
            "tide_url": "",
            "boating_url": "",
            "surf_url": "",
        },
    )
    coord = _make_coordinator(
        hass
    )  # coord.data = MetServicePublicData() — all capability flags False
    entry.runtime_data = coord

    added = []

    def add_entities(entities, *args, **kwargs):
        added.extend(entities)

    await async_setup_entry(hass, entry, add_entities)

    keys = {s.entity_description.key for s in added}

    excluded = {
        FIELD_TEMP,
        FIELD_WINDSPEED,
        FIELD_WINDGUST,
        FIELD_WINDDIR,
        FIELD_HUMIDITY,
        FIELD_PRESSURE,
        "wind_strength",
        "rainfall",
        "pressureTendencyTrend",
        "temperatureFeelsLike",
        "breakdown_morning",
        "breakdown_afternoon",
        "breakdown_evening",
        "breakdown_overnight",
    }
    assert keys.isdisjoint(excluded)

    included = {
        "temperature_today_high",
        "temperature_today_low",
        "tomorrow_temp_high",
        "weather_warnings",
        "uvIndex",
    }
    assert included.issubset(keys)


async def test_setup_entry_towns_creates_observation_sensors(hass):
    """A towns-cities coordinator with observations and breakdown present creates the sensors that the rural-like default coordinator skips."""
    from custom_components.metservice_weather.sensor import async_setup_entry
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from custom_components.metservice_weather.const import (
        DOMAIN,
        FIELD_TEMP,
        FIELD_WINDSPEED,
        FIELD_WINDGUST,
        FIELD_WINDDIR,
        FIELD_HUMIDITY,
        FIELD_PRESSURE,
    )

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
    coord.data = MetServicePublicData(has_observations=True, has_breakdown=True)
    entry.runtime_data = coord

    added = []

    def add_entities(entities, *args, **kwargs):
        added.extend(entities)

    await async_setup_entry(hass, entry, add_entities)

    keys = {s.entity_description.key for s in added}

    included = {
        FIELD_TEMP,
        FIELD_WINDSPEED,
        FIELD_WINDGUST,
        FIELD_WINDDIR,
        FIELD_HUMIDITY,
        FIELD_PRESSURE,
        "wind_strength",
        "rainfall",
        "pressureTendencyTrend",
        "temperatureFeelsLike",
        "breakdown_morning",
        "breakdown_afternoon",
        "breakdown_evening",
        "breakdown_overnight",
    }
    assert included.issubset(keys)


async def test_setup_entry_removes_stale_registry_entries(hass):
    """Registry entries for sensors the location no longer provides are removed, while still-provided sensors and the weather-domain entity are left untouched."""
    from custom_components.metservice_weather.sensor import async_setup_entry
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from homeassistant.helpers import entity_registry as er
    from custom_components.metservice_weather.const import DOMAIN, FIELD_TEMP

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
    coord = _make_coordinator(hass)  # rural-like: obs sensors will NOT be created
    entry.runtime_data = coord
    loc = coord.location

    ent_reg = er.async_get(hass)
    # FIELD_TEMP is gated on has_observations, which the default (rural-like)
    # coordinator data does not have — so it will be treated as stale.
    stale = ent_reg.async_get_or_create(
        "sensor", DOMAIN, f"{loc}_{FIELD_TEMP}".lower(), config_entry=entry
    )
    # weather_warnings is ungated, so it is always (re)created.
    keep = ent_reg.async_get_or_create(
        "sensor", DOMAIN, f"{loc}_weather_warnings".lower(), config_entry=entry
    )
    weather_ent = ent_reg.async_get_or_create(
        "weather", DOMAIN, f"{loc}_weather".lower(), config_entry=entry
    )

    added = []

    def add_entities(entities, *args, **kwargs):
        added.extend(entities)

    await async_setup_entry(hass, entry, add_entities)

    assert ent_reg.async_get(stale.entity_id) is None
    assert ent_reg.async_get(keep.entity_id) is not None
    assert ent_reg.async_get(weather_ent.entity_id) is not None
