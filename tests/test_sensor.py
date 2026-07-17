"""Tests for WeatherSensor entity and weather_current_conditions_sensors helpers."""

from __future__ import annotations

import datetime
import logging
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
    _tide_attrs,
    _warning_severity,
    _warnings_state,
    _warnings_enum_state,
    _uv_alert_level_state,
    _pressure_trend_state,
    _wind_strength_state,
    _fire_season_state,
    _fire_danger_state,
    _moon_phase_enum_state,
    _UNKNOWN_UV_ALERT_LEVELS_LOGGED,
    _UNKNOWN_PRESSURE_TREND_LOGGED,
    _UNKNOWN_WIND_STRENGTH_LOGGED,
    _UNKNOWN_FIRE_SEASON_LOGGED,
    _UNKNOWN_FIRE_DANGER_LOGGED,
    _FIRE_DANGER_LABEL_DRIFT_LOGGED,
    _UNKNOWN_MOON_PHASE_LOGGED,
    current_condition_sensor_descriptions_public,
)
from custom_components.metservice_weather.coordinator_types import MetServicePublicData


def _desc(key: str) -> WeatherSensorEntityDescription:
    """Look up a live sensor description by key, for value_fn/attr_fn tests."""
    return next(d for d in current_condition_sensor_descriptions_public if d.key == key)


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
    """The attribute count matches the number of active warnings.

    Targets the current warning_level ENUM sensor, whose attributes are
    fully flat (headline + count) — the structured list moved to the
    opt-in warning_details carrier, and the deprecated weather_warnings
    sensor keeps its v2026.7.0 shape (a single joined "warnings" string).
    """
    warnings = [
        {"name": "Strong Wind Watch", "text": "a", "threat_period": "Today"},
        {"name": "Heavy Rain Warning", "text": "b", "threat_period": "Tonight"},
    ]
    data = MetServicePublicData(warnings_list=warnings)
    desc = next(
        d
        for d in current_condition_sensor_descriptions_public
        if d.key == "warning_level"
    )
    attrs = desc.attr_fn(data)
    assert attrs["count"] == 2
    assert "warnings" not in attrs


def test_warnings_state_truncates_to_255_chars():
    """A most-severe warning name longer than 255 chars is truncated to exactly 255."""
    long_name = "Severe Weather Warning - Red " + ("x" * 300)
    data = MetServicePublicData(
        warnings_list=[{"name": long_name, "text": "Details", "threat_period": "Today"}]
    )
    state = _warnings_state(data)
    assert len(state) == 255
    assert state == long_name[:255]


# ---------------------------------------------------------------------------
# Test: sensor descriptions are non-empty lists
# ---------------------------------------------------------------------------


def test_public_sensor_descriptions_non_empty():
    """current_condition_sensor_descriptions_public is a non-empty list."""
    assert len(current_condition_sensor_descriptions_public) > 0


# ---------------------------------------------------------------------------
# Test: device="marine" is flagged on exactly the 14 marine sensors
# ---------------------------------------------------------------------------

_MARINE_SENSOR_KEYS = {
    "tides_high",
    "tides_low",
    "tide_direction",
    "boating_status",
    "boating_forecast",
    "surf_conditions",
    "surf_rating",
    "surf_wave_height",
    "surf_set_face",
    "surf_swell_direction",
    "surf_swell_height",
    "surf_wind_direction",
    "surf_wind_speed",
    "surf_wind_gust",
    "surf_period",
}


def test_marine_device_flag_covers_exactly_the_fifteen_marine_sensors():
    """device="marine" is set on exactly the 15 tide/boating/surf sensors — no more, no fewer."""
    marine_keys = {
        d.key
        for d in current_condition_sensor_descriptions_public
        if d.device == "marine"
    }
    assert marine_keys == _MARINE_SENSOR_KEYS
    assert len(_MARINE_SENSOR_KEYS) == 15


def test_non_marine_descriptions_default_to_location_device():
    """Every sensor outside the marine set stays on the default "location" device."""
    for desc in current_condition_sensor_descriptions_public:
        if desc.key not in _MARINE_SENSOR_KEYS:
            assert desc.device == "location", desc.key


# ---------------------------------------------------------------------------
# Test: pollen sensor description (one-sensor redesign)
# ---------------------------------------------------------------------------


def test_pollen_sensor_coexists_with_resurrected_deprecated_keys():
    """The "pollen" ENUM sensor coexists with the resurrected, deprecated pollen_levels/pollen_type sensors."""
    keys = {d.key for d in current_condition_sensor_descriptions_public}
    assert "pollen_levels" in keys
    assert "pollen_type" in keys
    assert "pollen" in keys


def test_pollen_sensor_is_enum_with_four_options():
    """The pollen description is an ENUM sensor with the four documented states."""
    desc = next(
        d for d in current_condition_sensor_descriptions_public if d.key == "pollen"
    )
    assert desc.device_class == SensorDeviceClass.ENUM
    assert desc.options == ["none", "low", "moderate", "high"]


def test_pollen_sensor_value_and_attrs_from_derived_fields():
    """value_fn/attr_fn read pollen_state and the derived attribute fields.

    Per-level/imminent allergen lists are flattened into joined strings;
    levels absent from pollen_active are omitted.
    """
    desc = next(
        d for d in current_condition_sensor_descriptions_public if d.key == "pollen"
    )
    data = MetServicePublicData(
        pollen_state="high",
        pollen_active={"low": ["Wattle", "Cypress"], "high": ["Ragweed"]},
        pollen_imminent=["Macrocarpa", "Pinus Radiata"],
    )
    assert desc.value_fn(data, "metric") == "high"
    assert desc.attr_fn(data) == {
        "low_allergens": "Wattle, Cypress",
        "high_allergens": "Ragweed",
        "imminent_allergens": "Macrocarpa, Pinus Radiata",
    }


def test_pollen_sensor_attrs_omit_empty_levels_and_imminent():
    """attr_fn omits empty allergen data.

    Levels absent from pollen_active (or present with an empty list) and an
    empty pollen_imminent are omitted from the attributes entirely.
    """
    desc = next(
        d for d in current_condition_sensor_descriptions_public if d.key == "pollen"
    )
    data = MetServicePublicData(
        pollen_state="low",
        pollen_active={"low": ["Wattle"], "moderate": []},
        pollen_imminent=[],
    )
    assert desc.attr_fn(data) == {
        "low_allergens": "Wattle",
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
# Test: deprecated pollen_levels/pollen_type sensors keep their v2026.7.0
# behaviour (resurrected for existing installs)
# ---------------------------------------------------------------------------


def test_deprecated_pollen_levels_is_hidden_and_disabled():
    """The resurrected pollen_levels sensor is disabled and hidden."""
    desc = _desc("pollen_levels")
    assert desc.entity_registry_enabled_default is False
    assert desc.entity_registry_visible_default is False


def test_deprecated_pollen_levels_value():
    """pollen_levels passes through the raw pollen_level field verbatim."""
    desc = _desc("pollen_levels")
    data = MetServicePublicData(pollen_level="Low")
    assert desc.value_fn(data, "metric") == "Low"


def test_deprecated_pollen_type_is_hidden_and_disabled():
    """The resurrected pollen_type sensor is disabled and hidden."""
    desc = _desc("pollen_type")
    assert desc.entity_registry_enabled_default is False
    assert desc.entity_registry_visible_default is False


def test_deprecated_pollen_type_value_capitalized_join():
    """pollen_type capitalizes each ". "-separated segment, matching v2026.7.0."""
    desc = _desc("pollen_type")
    data = MetServicePublicData(pollen_type="grass. tree")
    assert desc.value_fn(data, "metric") == "Grass. Tree"


def test_deprecated_pollen_type_none_when_absent():
    """A missing pollen_type maps to None."""
    desc = _desc("pollen_type")
    data = MetServicePublicData(pollen_type=None)
    assert desc.value_fn(data, "metric") is None


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
# Test: async_setup_entry marine device grouping
# ---------------------------------------------------------------------------


async def test_marine_skip_setup_creates_no_marine_device_entities(hass):
    """With no marine URLs configured, no entity is grouped under the marine device."""
    from custom_components.metservice_weather.sensor import async_setup_entry
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

    assert added  # sanity — ungated sensors are still created
    assert not any(s.entity_description.device == "marine" for s in added)
    marine_identifier = (DOMAIN, f"{coord.location}_marine")
    for sensor in added:
        assert sensor.device_info["identifiers"] != {marine_identifier}
        assert sensor.device_info["identifiers"] == {(DOMAIN, coord.location)}


async def test_marine_enabled_setup_groups_marine_sensors_under_their_own_device(hass):
    """Marine sensors land on a device distinct from the location device.

    Linked to it via via_device, while non-marine sensors stay on the
    location device as before.
    """
    from custom_components.metservice_weather.sensor import async_setup_entry
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from custom_components.metservice_weather.const import DOMAIN

    tide_url = (
        "https://www.metservice.com/publicData/webdata/marine/regions/"
        "kapiti-wellington/tides/locations/wellington"
    )
    boating_url = (
        "https://www.metservice.com/publicData/webdata/marine/regions/"
        "kapiti-wellington/boating/locations/wellington"
    )
    surf_url = (
        "https://www.metservice.com/publicData/webdata/marine/regions/"
        "kapiti-wellington/surf/locations/lyall-bay"
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "name": "Napier",
            "location": "/towns-cities/regions/hawkes-bay/locations/napier",
            "api": "public",
            "marine_region": "marine/regions/kapiti-wellington",
            "tide_url": tide_url,
            "boating_url": boating_url,
            "surf_url": surf_url,
        },
    )
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
    entry.runtime_data = coord

    added = []

    def add_entities(entities, *args, **kwargs):
        added.extend(entities)

    await async_setup_entry(hass, entry, add_entities)

    marine_sensors = [s for s in added if s.entity_description.device == "marine"]
    location_sensors = [s for s in added if s.entity_description.device == "location"]

    assert {s.entity_description.key for s in marine_sensors} == _MARINE_SENSOR_KEYS
    assert location_sensors  # ungated non-marine sensors are still created

    location_identifier = (DOMAIN, coord.location)
    marine_identifier = (DOMAIN, f"{coord.location}_marine")

    for sensor in marine_sensors:
        info = sensor.device_info
        assert info["identifiers"] == {marine_identifier}
        assert info["identifiers"] != {location_identifier}
        assert info["via_device"] == location_identifier
        assert info["name"] == "Kapiti and Wellington"

    for sensor in location_sensors:
        info = sensor.device_info
        assert info["identifiers"] == {location_identifier}
        assert info.get("via_device") is None


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


async def test_setup_entry_keeps_resurrected_pollen_registry_entries(hass):
    """pollen_levels/pollen_type are resurrected (deprecated), so pre-existing registry rows are kept alongside pollen."""
    from custom_components.metservice_weather.sensor import async_setup_entry
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from homeassistant.helpers import entity_registry as er
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
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)
    entry.runtime_data = coord
    loc = coord.location

    ent_reg = er.async_get(hass)
    existing_levels = ent_reg.async_get_or_create(
        "sensor", DOMAIN, f"{loc}_pollen_levels".lower(), config_entry=entry
    )
    existing_type = ent_reg.async_get_or_create(
        "sensor", DOMAIN, f"{loc}_pollen_type".lower(), config_entry=entry
    )

    added = []

    def add_entities(entities, *args, **kwargs):
        added.extend(entities)

    await async_setup_entry(hass, entry, add_entities)

    assert ent_reg.async_get(existing_levels.entity_id) is not None
    assert ent_reg.async_get(existing_type.entity_id) is not None
    unique_ids = {s.unique_id for s in added}
    assert f"{loc}_pollen_levels".lower() in unique_ids
    assert f"{loc}_pollen_type".lower() in unique_ids
    assert f"{loc}_pollen".lower() in unique_ids


# ---------------------------------------------------------------------------
# Test: new rain-window sensors (rain_next_8_hours / rain_next_24_hours /
# next_rain_at)
# ---------------------------------------------------------------------------


def test_rain_next_8_hours_value_passthrough():
    """rain_next_8_hours passes rain_next_8h_mm straight through."""
    desc = _desc("rain_next_8_hours")
    data = MetServicePublicData(rain_next_8h_mm=4.2)
    assert desc.value_fn(data, "metric") == 4.2


def test_rain_next_8_hours_none_when_insufficient_coverage():
    """rain_next_8_hours is None when the coordinator couldn't compute a window."""
    desc = _desc("rain_next_8_hours")
    data = MetServicePublicData(rain_next_8h_mm=None)
    assert desc.value_fn(data, "metric") is None


def test_rain_next_8_hours_disabled_by_default():
    """rain_next_8_hours is opt-in (not shown by default)."""
    assert _desc("rain_next_8_hours").entity_registry_enabled_default is False


def test_rain_next_24_hours_value_passthrough():
    """rain_next_24_hours passes rain_next_24h_mm straight through."""
    desc = _desc("rain_next_24_hours")
    data = MetServicePublicData(rain_next_24h_mm=12.5)
    assert desc.value_fn(data, "metric") == 12.5


def test_rain_next_24_hours_none_when_insufficient_coverage():
    """rain_next_24_hours is None when the coordinator couldn't compute a window."""
    desc = _desc("rain_next_24_hours")
    data = MetServicePublicData(rain_next_24h_mm=None)
    assert desc.value_fn(data, "metric") is None


def test_rain_next_24_hours_disabled_by_default():
    """rain_next_24_hours is opt-in (not shown by default)."""
    assert _desc("rain_next_24_hours").entity_registry_enabled_default is False


def test_next_rain_at_parses_iso_datetime():
    """next_rain_at converts the ISO string to a datetime."""
    desc = _desc("next_rain_at")
    data = MetServicePublicData(next_rain_at="2026-07-16T14:00:00+12:00")
    result = desc.value_fn(data, "metric")
    assert isinstance(result, datetime.datetime)


def test_next_rain_at_none_when_absent():
    """next_rain_at is None-safe when there's no rain in the forecast window."""
    desc = _desc("next_rain_at")
    data = MetServicePublicData(next_rain_at=None)
    assert desc.value_fn(data, "metric") is None


def test_next_rain_at_disabled_by_default():
    """next_rain_at is opt-in (not shown by default)."""
    assert _desc("next_rain_at").entity_registry_enabled_default is False


# ---------------------------------------------------------------------------
# Test: UV ENUM sensor (uvIndex, now sourced from uv_alert_level)
# ---------------------------------------------------------------------------


def test_uv_alert_level_known_mappings():
    """Every documented UV alert level label maps to its snake_case state."""
    assert _uv_alert_level_state("Low") == "low"
    assert _uv_alert_level_state("Moderate") == "moderate"
    assert _uv_alert_level_state("High") == "high"
    assert _uv_alert_level_state("Very High") == "very_high"
    assert _uv_alert_level_state("Extreme") == "extreme"
    # Case/whitespace insensitive.
    assert _uv_alert_level_state("  very high  ") == "very_high"


def test_uv_alert_level_none_when_absent():
    """A missing/empty UV alert level maps to None (not a warn-once event)."""
    assert _uv_alert_level_state(None) is None
    assert _uv_alert_level_state("") is None


def test_uv_alert_level_unknown_warns_once(caplog):
    """An unrecognised UV alert level logs one warning per runtime and returns None."""
    _UNKNOWN_UV_ALERT_LEVELS_LOGGED.discard("Cataclysmic")
    with caplog.at_level(logging.WARNING):
        assert _uv_alert_level_state("Cataclysmic") is None
        assert _uv_alert_level_state("Cataclysmic") is None
    matches = [r for r in caplog.records if "Cataclysmic" in r.getMessage()]
    assert len(matches) == 1


def test_uv_risk_description_is_enum_with_five_options():
    """uv_risk is a seasonal ENUM sensor with the five documented states."""
    desc = _desc("uv_risk")
    assert desc.device_class == SensorDeviceClass.ENUM
    assert desc.options == ["low", "moderate", "high", "very_high", "extreme"]
    assert desc.seasonal is True


def test_uv_risk_description_value_and_attrs():
    """value_fn/attr_fn read uv_alert_level and the UV detail fields."""
    desc = _desc("uv_risk")
    data = MetServicePublicData(
        uv_alert_level="Moderate",
        uv_status_class="moderate",
        uv_message="Take care",
        uv_has_alert=True,
        uv_window_start_at="2026-07-16T09:00:00+12:00",
        uv_window_end_at="2026-07-16T17:00:00+12:00",
    )
    assert desc.value_fn(data, "metric") == "moderate"
    attrs = desc.attr_fn(data)
    assert attrs["status_class"] == "moderate"
    assert attrs["advice"] == "Take care"
    assert attrs["protection_window_start"] == "2026-07-16T09:00:00+12:00"
    assert attrs["protection_window_end"] == "2026-07-16T17:00:00+12:00"
    assert attrs["has_alert"] is True
    # level_label (bijective with the state) and the manual attribution key
    # (the platform-wide _attr_attribution covers it) are deliberately absent.
    assert "level_label" not in attrs
    assert "attribution" not in attrs


def test_uv_risk_description_attrs_fall_back_to_raw_window():
    """protection_window_* falls back to the *_raw fields when *_at is None."""
    desc = _desc("uv_risk")
    data = MetServicePublicData(
        uv_alert_level="Low",
        uv_window_start_raw="9:00am",
        uv_window_end_raw="5:00pm",
    )
    attrs = desc.attr_fn(data)
    assert attrs["protection_window_start"] == "9:00am"
    assert attrs["protection_window_end"] == "5:00pm"


def test_uv_risk_description_attrs_empty_when_state_none():
    """attr_fn returns {} when the UV alert level didn't map (no data / unknown)."""
    desc = _desc("uv_risk")
    data = MetServicePublicData()
    assert desc.value_fn(data, "metric") is None
    assert desc.attr_fn(data) == {}


# ---------------------------------------------------------------------------
# Test: deprecated uvIndex sensor keeps its v2026.7.0 raw-passthrough behaviour
# ---------------------------------------------------------------------------


def test_deprecated_uv_index_is_seasonal_and_hidden():
    """The deprecated uvIndex sensor stays seasonal but is disabled/hidden."""
    desc = _desc("uvIndex")
    assert desc.seasonal is True
    assert desc.entity_registry_enabled_default is False
    assert desc.entity_registry_visible_default is False


def test_deprecated_uv_index_strips_legacy_status_prefix():
    """The deprecated uvIndex sensor still strips the legacy 'status-' prefix."""
    desc = _desc("uvIndex")
    data = MetServicePublicData(uv_index="status-moderate")
    assert desc.value_fn(data, "metric") == "moderate"


def test_deprecated_uv_index_passes_through_unprefixed_value():
    """A raw uv_index value without the legacy prefix passes straight through."""
    desc = _desc("uvIndex")
    data = MetServicePublicData(uv_index="Low")
    assert desc.value_fn(data, "metric") == "Low"


def test_deprecated_uv_index_none_when_absent():
    """A missing uv_index maps to None."""
    desc = _desc("uvIndex")
    data = MetServicePublicData(uv_index=None)
    assert desc.value_fn(data, "metric") is None


# ---------------------------------------------------------------------------
# Test: weather_warnings ENUM sensor
# ---------------------------------------------------------------------------


def test_warnings_enum_state_none_when_no_warnings():
    """No active warnings maps to the 'none' state."""
    data = MetServicePublicData(warnings_list=[])
    assert _warnings_enum_state(data) == "none"


def test_warnings_enum_state_watch():
    """A plain Watch maps to the 'watch' state."""
    data = MetServicePublicData(
        warnings_list=[
            {"name": "Strong Wind Watch", "text": "t", "threat_period": "Today"}
        ]
    )
    assert _warnings_enum_state(data) == "watch"


def test_warnings_enum_state_warning():
    """A plain Warning maps to the 'warning' state."""
    data = MetServicePublicData(
        warnings_list=[
            {"name": "Strong Wind Warning", "text": "t", "threat_period": "Today"}
        ]
    )
    assert _warnings_enum_state(data) == "warning"


def test_warnings_enum_state_orange():
    """An Orange warning maps to the 'orange' state."""
    data = MetServicePublicData(
        warnings_list=[
            {
                "name": "Strong Wind Warning - Orange",
                "text": "t",
                "threat_period": "Today",
            }
        ]
    )
    assert _warnings_enum_state(data) == "orange"


def test_warnings_enum_state_red():
    """A Red warning maps to the 'red' state."""
    data = MetServicePublicData(
        warnings_list=[
            {
                "name": "Severe Weather Warning - Red",
                "text": "t",
                "threat_period": "Today",
            }
        ]
    )
    assert _warnings_enum_state(data) == "red"


def test_warnings_enum_state_ranks_highest_regardless_of_list_order():
    """The highest-severity warning wins the enum state even when listed first."""
    data = MetServicePublicData(
        warnings_list=[
            {"name": "Strong Wind Watch", "text": "a", "threat_period": "Today"},
            {
                "name": "Severe Weather Warning - Red",
                "text": "b",
                "threat_period": "Tonight",
            },
            {
                "name": "Strong Wind Warning - Orange",
                "text": "c",
                "threat_period": "Tomorrow",
            },
        ]
    )
    assert _warnings_enum_state(data) == "red"


def test_warning_level_description_is_enum_with_five_options():
    """warning_level is an ENUM sensor with the five documented states."""
    desc = _desc("warning_level")
    assert desc.device_class == SensorDeviceClass.ENUM
    assert desc.options == ["none", "watch", "warning", "orange", "red"]


def test_warning_level_description_value_is_enum_state():
    """value_fn reports the ranked enum state, not the old headline text."""
    desc = _desc("warning_level")
    data = MetServicePublicData(
        warnings_list=[
            {
                "name": "Severe Weather Warning - Red",
                "text": "t",
                "threat_period": "Today",
            }
        ]
    )
    assert desc.value_fn(data, "metric") == "red"


def test_warning_level_description_headline_attribute():
    """The old headline text and warning count now live in attr_fn."""
    desc = _desc("warning_level")
    data = MetServicePublicData(
        warnings_list=[
            {"name": "Strong Wind Watch", "text": "a", "threat_period": "Today"},
            {
                "name": "Strong Wind Warning - Orange",
                "text": "b",
                "threat_period": "Tonight",
            },
        ]
    )
    attrs = desc.attr_fn(data)
    assert attrs["headline"] == "Strong Wind Warning - Orange (+1 more)"
    assert attrs["count"] == 2
    assert "warnings" not in attrs


def test_warning_level_description_headline_truncates_to_255():
    """The headline attribute keeps the original 255-char truncation."""
    desc = _desc("warning_level")
    long_name = "Severe Weather Warning - Red " + ("x" * 300)
    data = MetServicePublicData(
        warnings_list=[{"name": long_name, "text": "Details", "threat_period": "Today"}]
    )
    attrs = desc.attr_fn(data)
    assert len(attrs["headline"]) == 255
    assert attrs["headline"] == long_name[:255]


# ---------------------------------------------------------------------------
# Test: warning_details opt-in carrier sensor
# ---------------------------------------------------------------------------


def test_warning_details_is_optin_carrier_with_count_state():
    """warning_details is disabled by default; state = active warning count."""
    desc = _desc("warning_details")
    assert desc.entity_registry_enabled_default is False
    assert desc.device == "location"
    warnings = [
        {"name": "Strong Wind Watch", "text": "a", "threat_period": "Today"},
        {"name": "Heavy Rain Warning", "text": "b", "threat_period": "Tonight"},
    ]
    data = MetServicePublicData(warnings_list=warnings)
    assert desc.value_fn(data, "metric") == 2
    assert desc.attr_fn(data) == {"active_warnings": warnings}


def test_warning_details_zero_when_clear():
    """No active warnings: state 0 with a stable empty-list attribute."""
    desc = _desc("warning_details")
    data = MetServicePublicData(warnings_list=[])
    assert desc.value_fn(data, "metric") == 0
    assert desc.attr_fn(data) == {"active_warnings": []}


def test_carrier_payload_attributes_are_recorder_exempt():
    """The two machine-payload attribute names are excluded from the recorder.

    Matching is by attribute name class-wide, so the set must never contain
    "warnings" — that would silently stop recording the deprecated
    weather_warnings sensor's frozen attribute.
    """
    assert WeatherSensor._unrecorded_attributes == frozenset(
        {"tide_table", "active_warnings"}
    )


# ---------------------------------------------------------------------------
# Test: deprecated weather_warnings sensor keeps its exact v2026.7.0
# behaviour — the full joined `weather_warnings` string (not the
# warnings_list-derived headline used by the new warning_level sensor).
# ---------------------------------------------------------------------------


def test_deprecated_weather_warnings_is_hidden_and_disabled():
    """The deprecated weather_warnings sensor is disabled and hidden."""
    desc = _desc("weather_warnings")
    assert desc.entity_registry_enabled_default is False
    assert desc.entity_registry_visible_default is False
    assert desc.device_class is None


def test_deprecated_weather_warnings_state_is_full_joined_text():
    """The deprecated sensor's state is the full joined weather_warnings text.

    v2026.7.0 read the pre-joined `weather_warnings` string field verbatim —
    not the structured warnings_list used by the new warning_level sensor.
    """
    desc = _desc("weather_warnings")
    data = MetServicePublicData(
        weather_warnings="Strong Wind Watch. Strong Wind Warning - Orange."
    )
    assert (
        desc.value_fn(data, "metric")
        == "Strong Wind Watch. Strong Wind Warning - Orange."
    )
    attrs = desc.attr_fn(data)
    assert attrs == {"warnings": "Strong Wind Watch. Strong Wind Warning - Orange."}
    assert "count" not in attrs
    assert "headline" not in attrs


def test_deprecated_weather_warnings_no_warnings():
    """No active warnings falls back to the 'No warnings' default, matching v2026.7.0."""
    desc = _desc("weather_warnings")
    data = MetServicePublicData()  # weather_warnings defaults to "No warnings"
    assert desc.value_fn(data, "metric") == "No warnings"
    assert desc.attr_fn(data) == {"warnings": "No warnings"}


def test_deprecated_weather_warnings_truncates_to_255():
    """v2026.7.0's original string-truncation: [:252] + "..." when over 255 chars.

    This is distinct from the new warning_level headline's plain [:255]
    slice — v2026.7.0 appended an ellipsis instead of hard-cutting.
    """
    desc = _desc("weather_warnings")
    long_text = "Severe Weather Warning - Red. " + ("x" * 300)
    data = MetServicePublicData(weather_warnings=long_text)
    state = desc.value_fn(data, "metric")
    assert len(state) == 255
    assert state == long_text[:252] + "..."
    assert desc.attr_fn(data) == {"warnings": long_text}


def test_deprecated_weather_warnings_at_or_under_255_not_truncated():
    """weather_warnings text at or under 255 chars passes through unchanged."""
    desc = _desc("weather_warnings")
    exact_255 = "x" * 255
    data = MetServicePublicData(weather_warnings=exact_255)
    assert desc.value_fn(data, "metric") == exact_255


# ---------------------------------------------------------------------------
# Test: pressure_tendency_trend ENUM sensor
# ---------------------------------------------------------------------------


def test_pressure_trend_known_mappings():
    """rising/falling/stable pass through case-insensitively."""
    assert _pressure_trend_state("Rising") == "rising"
    assert _pressure_trend_state("Falling") == "falling"
    assert _pressure_trend_state("Stable") == "stable"
    assert _pressure_trend_state("  RISING  ") == "rising"


def test_pressure_trend_none_when_absent():
    """A missing/empty pressure trend maps to None."""
    assert _pressure_trend_state(None) is None
    assert _pressure_trend_state("") is None


def test_pressure_trend_unknown_warns_once(caplog):
    """An unrecognised pressure trend logs one warning per runtime and returns None."""
    _UNKNOWN_PRESSURE_TREND_LOGGED.discard("Plummeting")
    with caplog.at_level(logging.WARNING):
        assert _pressure_trend_state("Plummeting") is None
        assert _pressure_trend_state("Plummeting") is None
    matches = [r for r in caplog.records if "Plummeting" in r.getMessage()]
    assert len(matches) == 1


def test_pressure_trend_description_is_enum():
    """pressure_trend is an ENUM sensor with the three documented states."""
    desc = _desc("pressure_trend")
    assert desc.device_class == SensorDeviceClass.ENUM
    assert desc.options == ["rising", "falling", "stable"]
    data = MetServicePublicData(pressure_trend="Rising")
    assert desc.value_fn(data, "metric") == "rising"


# ---------------------------------------------------------------------------
# Test: deprecated pressureTendencyTrend sensor keeps its v2026.7.0 raw
# passthrough behaviour
# ---------------------------------------------------------------------------


def test_deprecated_pressure_tendency_trend_is_hidden_and_disabled():
    """The deprecated pressureTendencyTrend sensor is disabled and hidden."""
    desc = _desc("pressureTendencyTrend")
    assert desc.entity_registry_enabled_default is False
    assert desc.entity_registry_visible_default is False
    assert desc.device_class is None


def test_deprecated_pressure_tendency_trend_raw_passthrough():
    """The deprecated sensor passes the raw pressure trend straight through."""
    desc = _desc("pressureTendencyTrend")
    data = MetServicePublicData(pressure_trend="Rising")
    assert desc.value_fn(data, "metric") == "Rising"


# ---------------------------------------------------------------------------
# Test: wind_strength ENUM sensor
# ---------------------------------------------------------------------------


def test_wind_strength_known_mappings():
    """Every mapped wind-strength label, including the two live-probed values."""
    assert _wind_strength_state("Calm") == "calm"
    assert _wind_strength_state("Light winds") == "light_winds"
    assert _wind_strength_state("Moderate") == "moderate"
    assert _wind_strength_state("Fresh") == "fresh"
    assert _wind_strength_state("Strong") == "strong"
    assert _wind_strength_state("Gale") == "gale"
    assert _wind_strength_state("Severe Gale") == "severe_gale"
    assert _wind_strength_state("Storm") == "storm"


def test_wind_strength_none_when_absent():
    """A missing/empty wind strength maps to None."""
    assert _wind_strength_state(None) is None
    assert _wind_strength_state("") is None


def test_wind_strength_unknown_warns_once(caplog):
    """An unrecognised wind strength logs one warning per runtime and returns None."""
    _UNKNOWN_WIND_STRENGTH_LOGGED.discard("Hurricane")
    with caplog.at_level(logging.WARNING):
        assert _wind_strength_state("Hurricane") is None
        assert _wind_strength_state("Hurricane") is None
    matches = [r for r in caplog.records if "Hurricane" in r.getMessage()]
    assert len(matches) == 1


def test_wind_strength_level_description_is_enum():
    """wind_strength_level is an ENUM sensor covering the full mapped vocabulary."""
    desc = _desc("wind_strength_level")
    assert desc.device_class == SensorDeviceClass.ENUM
    assert set(desc.options) == {
        "calm",
        "light_winds",
        "moderate",
        "fresh",
        "strong",
        "gale",
        "severe_gale",
        "storm",
    }
    data = MetServicePublicData(wind_strength="Light winds")
    assert desc.value_fn(data, "metric") == "light_winds"


# ---------------------------------------------------------------------------
# Test: deprecated wind_strength sensor keeps its v2026.7.0 raw text
# ---------------------------------------------------------------------------


def test_deprecated_wind_strength_is_hidden_and_disabled():
    """The deprecated wind_strength sensor is disabled and hidden."""
    desc = _desc("wind_strength")
    assert desc.entity_registry_enabled_default is False
    assert desc.entity_registry_visible_default is False
    assert desc.device_class is None


def test_deprecated_wind_strength_raw_passthrough():
    """The deprecated sensor passes the raw wind strength text straight through."""
    desc = _desc("wind_strength")
    data = MetServicePublicData(wind_strength="Light winds")
    assert desc.value_fn(data, "metric") == "Light winds"


def test_deprecated_wind_strength_none_when_absent():
    """A missing wind strength maps to None."""
    desc = _desc("wind_strength")
    data = MetServicePublicData(wind_strength=None)
    assert desc.value_fn(data, "metric") is None


# ---------------------------------------------------------------------------
# Test: fire_season ENUM sensor
# ---------------------------------------------------------------------------


def test_fire_season_known_mappings():
    """open/restricted/prohibited pass through case-insensitively."""
    assert _fire_season_state("open") == "open"
    assert _fire_season_state("Restricted") == "restricted"
    assert _fire_season_state("PROHIBITED") == "prohibited"


def test_fire_season_none_when_absent():
    """A missing fire season status maps to None (seasonal absence, no warning)."""
    assert _fire_season_state(None) is None


def test_fire_season_unknown_warns_once(caplog):
    """An unrecognised fire season status logs one warning per runtime and returns None."""
    _UNKNOWN_FIRE_SEASON_LOGGED.discard("closed")
    with caplog.at_level(logging.WARNING):
        assert _fire_season_state("closed") is None
        assert _fire_season_state("closed") is None
    matches = [r for r in caplog.records if "closed" in r.getMessage()]
    assert len(matches) == 1


def test_fire_season_status_description_value_and_attrs():
    """value_fn/attr_fn read fire_season_status plus the scope/detail fields."""
    desc = _desc("fire_season_status")
    assert desc.seasonal is True
    assert desc.device_class == SensorDeviceClass.ENUM
    assert desc.options == ["open", "restricted", "prohibited"]
    data = MetServicePublicData(
        fire_season_status="restricted",
        fire_season_short="Restricted",
        fire_season_text="A fire permit is required.",
    )
    assert desc.value_fn(data, "metric") == "restricted"
    assert desc.attr_fn(data) == {
        "scope": "Restricted",
        "detail": "A fire permit is required.",
    }


def test_fire_season_status_description_attrs_empty_when_state_none():
    """attr_fn returns {} when there's no fire season data (off-season)."""
    desc = _desc("fire_season_status")
    data = MetServicePublicData()
    assert desc.value_fn(data, "metric") is None
    assert desc.attr_fn(data) == {}


# ---------------------------------------------------------------------------
# Test: deprecated fire_season sensor keeps its v2026.7.0 raw text
# ---------------------------------------------------------------------------


def test_deprecated_fire_season_is_seasonal_and_hidden():
    """The deprecated fire_season sensor stays seasonal but is disabled/hidden."""
    desc = _desc("fire_season")
    assert desc.seasonal is True
    assert desc.entity_registry_enabled_default is False
    assert desc.entity_registry_visible_default is False
    assert desc.device_class is None


def test_deprecated_fire_season_raw_passthrough():
    """The deprecated sensor passes the raw fire_season short text straight through."""
    desc = _desc("fire_season")
    data = MetServicePublicData(fire_season="Restricted")
    assert desc.value_fn(data, "metric") == "Restricted"


# ---------------------------------------------------------------------------
# Test: fire_danger ENUM sensor
# ---------------------------------------------------------------------------


def test_fire_danger_index_primary_mapping():
    """The 1-5 dailyObservationIndex is the primary mapping source."""
    assert _fire_danger_state(1, None) == "low"
    assert _fire_danger_state(2, None) == "moderate"
    assert _fire_danger_state(3, None) == "high"
    assert _fire_danger_state(4, None) == "very_high"
    assert _fire_danger_state(5, None) == "extreme"


def test_fire_danger_label_fallback_when_index_none():
    """The label is only consulted when the index is None."""
    assert _fire_danger_state(None, "Very High") == "very_high"
    assert _fire_danger_state(None, "Extreme") == "extreme"
    # Index present (even if unmapped) short-circuits the label fallback.
    assert _fire_danger_state(3, "Extreme") == "high"


def test_fire_danger_none_when_both_absent():
    """No index and no label maps to None without warning (seasonal absence)."""
    assert _fire_danger_state(None, None) is None


def test_fire_danger_unknown_index_warns_once(caplog):
    """An out-of-range index logs one warning per runtime and returns None."""
    _UNKNOWN_FIRE_DANGER_LOGGED.discard("9")
    with caplog.at_level(logging.WARNING):
        assert _fire_danger_state(9, "Very High") is None
        assert _fire_danger_state(9, "Very High") is None
    matches = [r for r in caplog.records if "9" in r.getMessage()]
    assert len(matches) == 1


def test_fire_danger_unknown_label_warns_once(caplog):
    """An unrecognised label (with no index) logs one warning per runtime."""
    _UNKNOWN_FIRE_DANGER_LOGGED.discard("Catastrophic")
    with caplog.at_level(logging.WARNING):
        assert _fire_danger_state(None, "Catastrophic") is None
        assert _fire_danger_state(None, "Catastrophic") is None
    matches = [r for r in caplog.records if "Catastrophic" in r.getMessage()]
    assert len(matches) == 1


def test_fire_danger_label_drift_warns_once(caplog):
    """A label that doesn't match its index's band warns once per runtime.

    The state comes from the index, so a richer label (e.g. "Very High" on
    index 3) would be silently collapsed to the enum — the tripwire warning
    is the only trace of it.
    """
    _FIRE_DANGER_LABEL_DRIFT_LOGGED.clear()
    with caplog.at_level(logging.WARNING):
        assert _fire_danger_state(3, "Very High") == "high"
        assert _fire_danger_state(3, "Very High") == "high"
    matches = [r for r in caplog.records if "Very High" in r.getMessage()]
    assert len(matches) == 1


def test_fire_danger_matching_label_does_not_warn(caplog):
    """A label matching its index's band produces no drift warning."""
    _FIRE_DANGER_LABEL_DRIFT_LOGGED.clear()
    with caplog.at_level(logging.WARNING):
        assert _fire_danger_state(3, "High") == "high"
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]


def test_fire_danger_level_description_value_and_attrs():
    """value_fn/attr_fn read fire_danger_index/fire_danger plus guidance fields."""
    desc = _desc("fire_danger_level")
    assert desc.seasonal is True
    assert desc.device_class == SensorDeviceClass.ENUM
    assert desc.options == ["low", "moderate", "high", "very_high", "extreme"]
    data = MetServicePublicData(
        fire_danger_index=3,
        fire_danger="High",
        fire_danger_text="Extreme caution.",
        fire_danger_forecast="Very High",
    )
    assert desc.value_fn(data, "metric") == "high"
    assert desc.attr_fn(data) == {
        "index": 3,
        "guidance": "Extreme caution.",
        "tomorrow": "Very High",
    }


def test_fire_danger_level_description_attrs_empty_when_state_none():
    """attr_fn returns {} when there's no fire danger data (off-season)."""
    desc = _desc("fire_danger_level")
    data = MetServicePublicData()
    assert desc.value_fn(data, "metric") is None
    assert desc.attr_fn(data) == {}


# ---------------------------------------------------------------------------
# Test: deprecated fire_danger sensor keeps its v2026.7.0 verbatim text
# ---------------------------------------------------------------------------


def test_deprecated_fire_danger_is_seasonal_and_hidden():
    """The deprecated fire_danger sensor stays seasonal but is disabled/hidden."""
    desc = _desc("fire_danger")
    assert desc.seasonal is True
    assert desc.entity_registry_enabled_default is False
    assert desc.entity_registry_visible_default is False
    assert desc.device_class is None


def test_deprecated_fire_danger_raw_passthrough():
    """The deprecated sensor passes the raw fire_danger label straight through."""
    desc = _desc("fire_danger")
    data = MetServicePublicData(fire_danger="Moderate")
    assert desc.value_fn(data, "metric") == "Moderate"


# ---------------------------------------------------------------------------
# Test: moon_phase ENUM sensor
# ---------------------------------------------------------------------------


def test_moon_phase_enum_known_mappings():
    """The four principal-phase tokens map to their snake_case states."""
    assert _moon_phase_enum_state("NEW") == "new"
    assert _moon_phase_enum_state("FIRST") == "first_quarter"
    assert _moon_phase_enum_state("FULL") == "full"
    assert _moon_phase_enum_state("LAST") == "last_quarter"


def test_moon_phase_enum_none_when_absent():
    """A missing moon phase token maps to None."""
    assert _moon_phase_enum_state(None) is None
    assert _moon_phase_enum_state("") is None


def test_moon_phase_enum_unknown_warns_once(caplog):
    """An unrecognised moon phase token logs one warning per runtime and returns None."""
    _UNKNOWN_MOON_PHASE_LOGGED.discard("WANING")
    with caplog.at_level(logging.WARNING):
        assert _moon_phase_enum_state("WANING") is None
        assert _moon_phase_enum_state("WANING") is None
    matches = [r for r in caplog.records if "WANING" in r.getMessage()]
    assert len(matches) == 1


def test_next_moon_phase_sensor_is_removed():
    """The prerelease-only next_moon_phase sensor is gone.

    Its data lives on moon_phase_current's next_phase/next_phase_at
    attributes instead.
    """
    keys = {d.key for d in current_condition_sensor_descriptions_public}
    assert "next_moon_phase" not in keys


def test_moon_phase_current_attrs_carry_next_event():
    """moon_phase_current carries the next principal event as flat attributes."""
    desc = _desc("moon_phase_current")
    data = MetServicePublicData(
        moon_phase_current="waxing_crescent",
        moon_phase="FIRST",
        moon_phase_date="2026-07-21T22:55:00+12:00",
    )
    assert desc.attr_fn(data) == {
        "next_phase": "first_quarter",
        "next_phase_at": "2026-07-21T22:55:00+12:00",
    }


def test_moon_phase_current_attrs_sparse_when_upstream_missing():
    """Attributes are omitted individually when their upstream field is absent."""
    desc = _desc("moon_phase_current")
    assert desc.attr_fn(MetServicePublicData()) == {}
    only_date = MetServicePublicData(moon_phase_date="2026-07-21T22:55:00+12:00")
    assert desc.attr_fn(only_date) == {"next_phase_at": "2026-07-21T22:55:00+12:00"}
    only_phase = MetServicePublicData(moon_phase="FULL")
    assert desc.attr_fn(only_phase) == {"next_phase": "full"}


# ---------------------------------------------------------------------------
# Test: moon_phase_current ENUM sensor
# ---------------------------------------------------------------------------


def test_moon_phase_current_description_is_enum_with_eight_options():
    """moon_phase_current is an ENUM sensor with HA core's eight-phase vocabulary, enabled by default."""
    desc = _desc("moon_phase_current")
    assert desc.name == "Moon phase"
    assert desc.translation_key == "moon_phase_current"
    assert desc.device_class == SensorDeviceClass.ENUM
    assert desc.options == [
        "new_moon",
        "waxing_crescent",
        "first_quarter",
        "waxing_gibbous",
        "full_moon",
        "waning_gibbous",
        "last_quarter",
        "waning_crescent",
    ]
    assert desc.entity_registry_enabled_default is True


def test_moon_phase_current_description_value_reads_normalized_field():
    """value_fn reads data.moon_phase_current directly — it's already normalized upstream."""
    desc = _desc("moon_phase_current")
    for state in [
        "new_moon",
        "waxing_crescent",
        "first_quarter",
        "waxing_gibbous",
        "full_moon",
        "waning_gibbous",
        "last_quarter",
        "waning_crescent",
    ]:
        data = MetServicePublicData(moon_phase_current=state)
        assert desc.value_fn(data, "metric") == state


def test_moon_phase_current_description_none_safe():
    """A missing moon_phase_current normalizes to None (reported as unknown by HA)."""
    desc = _desc("moon_phase_current")
    data = MetServicePublicData()
    assert desc.value_fn(data, "metric") is None


# ---------------------------------------------------------------------------
# Test: deprecated moon_phase sensor keeps its v2026.7.0 display-name behaviour
# ---------------------------------------------------------------------------


def test_deprecated_moon_phase_is_hidden_and_disabled():
    """The deprecated moon_phase sensor is disabled and hidden."""
    desc = _desc("moon_phase")
    assert desc.entity_registry_enabled_default is False
    assert desc.entity_registry_visible_default is False
    assert desc.device_class is None


def test_deprecated_moon_phase_display_name_and_raw_attr():
    """value_fn returns the display name; attr_fn keeps the raw phase token."""
    desc = _desc("moon_phase")
    data = MetServicePublicData(moon_phase="FULL")
    assert desc.value_fn(data, "metric") == "Full Moon"
    assert desc.attr_fn(data) == {"raw_phase": "FULL"}


def test_deprecated_moon_phase_none_safe():
    """A missing moon phase token is None-safe, with no attrs."""
    desc = _desc("moon_phase")
    data = MetServicePublicData()
    assert desc.value_fn(data, "metric") is None
    assert desc.attr_fn(data) == {}


# ---------------------------------------------------------------------------
# Test: sunrise_at/sunset_at/moonrise_at/moonset_at are TIMESTAMP sensors
# ---------------------------------------------------------------------------


def test_sunrise_at_description_parses_iso_datetime_and_display_attr():
    """sunrise_at reads sunrise_at as a datetime and keeps the am/pm string as an attr."""
    desc = _desc("sunrise_at")
    assert desc.device_class == SensorDeviceClass.TIMESTAMP
    data = MetServicePublicData(
        sunrise_at="2026-07-16T07:12:00+12:00", sunrise="7:12am"
    )
    result = desc.value_fn(data, "metric")
    assert isinstance(result, datetime.datetime)
    assert desc.attr_fn(data) == {"display": "7:12am"}


def test_sunrise_at_description_none_safe():
    """sunrise_at is None-safe with no attrs when there's no data."""
    desc = _desc("sunrise_at")
    data = MetServicePublicData()
    assert desc.value_fn(data, "metric") is None
    assert desc.attr_fn(data) == {}


def test_sunset_at_description_parses_iso_datetime_and_display_attr():
    """sunset_at reads sunset_at as a datetime and keeps the am/pm string as an attr."""
    desc = _desc("sunset_at")
    assert desc.device_class == SensorDeviceClass.TIMESTAMP
    data = MetServicePublicData(sunset_at="2026-07-16T17:23:00+12:00", sunset="5:23pm")
    result = desc.value_fn(data, "metric")
    assert isinstance(result, datetime.datetime)
    assert desc.attr_fn(data) == {"display": "5:23pm"}


def test_sunset_at_description_none_safe():
    """sunset_at is None-safe with no attrs when there's no data."""
    desc = _desc("sunset_at")
    data = MetServicePublicData()
    assert desc.value_fn(data, "metric") is None
    assert desc.attr_fn(data) == {}


def test_moonrise_at_description_parses_iso_datetime_and_display_attr():
    """moonrise_at reads moonrise_at as a datetime and keeps the am/pm string as an attr."""
    desc = _desc("moonrise_at")
    assert desc.device_class == SensorDeviceClass.TIMESTAMP
    data = MetServicePublicData(
        moonrise_at="2026-07-16T20:00:00+12:00", moonrise="8:00pm"
    )
    result = desc.value_fn(data, "metric")
    assert isinstance(result, datetime.datetime)
    assert desc.attr_fn(data) == {"display": "8:00pm"}


def test_moonrise_at_description_none_safe():
    """moonrise_at is None-safe with no attrs when there's no data."""
    desc = _desc("moonrise_at")
    data = MetServicePublicData()
    assert desc.value_fn(data, "metric") is None
    assert desc.attr_fn(data) == {}


def test_moonset_at_description_parses_iso_datetime_and_display_attr():
    """moonset_at reads moonset_at as a datetime and keeps the am/pm string as an attr."""
    desc = _desc("moonset_at")
    assert desc.device_class == SensorDeviceClass.TIMESTAMP
    data = MetServicePublicData(
        moonset_at="2026-07-16T09:00:00+12:00", moonset="9:00am"
    )
    result = desc.value_fn(data, "metric")
    assert isinstance(result, datetime.datetime)
    assert desc.attr_fn(data) == {"display": "9:00am"}


def test_moonset_at_description_none_safe():
    """moonset_at is None-safe with no attrs when there's no data."""
    desc = _desc("moonset_at")
    data = MetServicePublicData()
    assert desc.value_fn(data, "metric") is None
    assert desc.attr_fn(data) == {}


# ---------------------------------------------------------------------------
# Test: deprecated sunrise/sunset/moonrise/moonset sensors keep their
# v2026.7.0 plain am/pm string state, with no device_class
# ---------------------------------------------------------------------------


def test_deprecated_sunrise_plain_string_state_no_device_class():
    """The deprecated sunrise sensor is a plain string with no device_class."""
    desc = _desc("sunrise")
    assert desc.device_class is None
    assert desc.entity_registry_enabled_default is False
    assert desc.entity_registry_visible_default is False
    data = MetServicePublicData(sunrise="7:12am")
    assert desc.value_fn(data, "metric") == "7:12am"


def test_deprecated_sunrise_none_when_absent():
    """A missing sunrise string maps to None."""
    desc = _desc("sunrise")
    data = MetServicePublicData(sunrise=None)
    assert desc.value_fn(data, "metric") is None


def test_deprecated_sunset_plain_string_state_no_device_class():
    """The deprecated sunset sensor is a plain string with no device_class."""
    desc = _desc("sunset")
    assert desc.device_class is None
    assert desc.entity_registry_enabled_default is False
    assert desc.entity_registry_visible_default is False
    data = MetServicePublicData(sunset="5:23pm")
    assert desc.value_fn(data, "metric") == "5:23pm"


def test_deprecated_moonrise_plain_string_state_no_device_class():
    """The deprecated moonrise sensor is a plain string with no device_class."""
    desc = _desc("moonrise")
    assert desc.device_class is None
    assert desc.entity_registry_enabled_default is False
    assert desc.entity_registry_visible_default is False
    data = MetServicePublicData(moonrise="8:00pm")
    assert desc.value_fn(data, "metric") == "8:00pm"


def test_deprecated_moonset_plain_string_state_no_device_class():
    """The deprecated moonset sensor is a plain string with no device_class."""
    desc = _desc("moonset")
    assert desc.device_class is None
    assert desc.entity_registry_enabled_default is False
    assert desc.entity_registry_visible_default is False
    data = MetServicePublicData(moonset="9:00am")
    assert desc.value_fn(data, "metric") == "9:00am"


# ---------------------------------------------------------------------------
# Test: tide attribute helpers (height_m)
# ---------------------------------------------------------------------------


def test_tide_attrs_height_from_upcoming_entry():
    """height_m comes from the same upcoming entry the value_fn selects."""
    future1 = (
        datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=2)
    ).isoformat()
    future2 = (
        datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=8)
    ).isoformat()
    tides = [
        {"type": "HIGH", "time": future1, "height": "1.8"},
        {"type": "LOW", "time": future2, "height": "0.4"},
    ]
    data = MetServicePublicData(tides=tides)
    assert _tide_attrs(data, "HIGH") == {"height_m": 1.8}
    assert _tide_attrs(data, "LOW") == {"height_m": 0.4}


def test_tide_attrs_empty_when_no_upcoming_entry():
    """attr_fn returns {} when every matching tide is in the past."""
    past = (
        datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=2)
    ).isoformat()
    tides = [{"type": "HIGH", "time": past, "height": "1.8"}]
    data = MetServicePublicData(tides=tides)
    assert _tide_attrs(data, "HIGH") == {}


def test_tide_attrs_empty_when_tides_not_a_list():
    """attr_fn returns {} when tides is None (no marine location configured)."""
    data = MetServicePublicData(tides=None)
    assert _tide_attrs(data, "HIGH") == {}


# ---------------------------------------------------------------------------
# Test: tide_direction opt-in carrier sensor
# ---------------------------------------------------------------------------


def _future_tides(*types: str) -> list[dict]:
    """Build a chronological tide table starting one hour from now."""
    base = datetime.datetime.now(datetime.UTC)
    return [
        {
            "type": t,
            "time": (base + datetime.timedelta(hours=1 + i * 6)).isoformat(),
            "height": "1.5",
        }
        for i, t in enumerate(types)
    ]


def test_tide_direction_rising_when_next_event_is_high():
    """Next upcoming event HIGH means the tide is coming in (rising)."""
    desc = _desc("tide_direction")
    assert desc.device == "marine"
    assert desc.entity_registry_enabled_default is False
    assert desc.options == ["rising", "falling"]
    data = MetServicePublicData(tides=_future_tides("HIGH", "LOW"))
    assert desc.value_fn(data, "metric") == "rising"


def test_tide_direction_falling_when_next_event_is_low():
    """Next upcoming event LOW means the tide is going out (falling)."""
    desc = _desc("tide_direction")
    data = MetServicePublicData(tides=_future_tides("LOW", "HIGH"))
    assert desc.value_fn(data, "metric") == "falling"


def test_tide_direction_skips_past_events():
    """Past entries are skipped — the state comes from the first future event."""
    desc = _desc("tide_direction")
    past = (
        datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=2)
    ).isoformat()
    tides = [{"type": "HIGH", "time": past, "height": "1.8"}] + _future_tides("LOW")
    data = MetServicePublicData(tides=tides)
    assert desc.value_fn(data, "metric") == "falling"


def test_tide_direction_unknown_when_exhausted_or_absent():
    """State is None when the table is exhausted, absent, or the type is unknown."""
    desc = _desc("tide_direction")
    past = (
        datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=2)
    ).isoformat()
    assert (
        desc.value_fn(
            MetServicePublicData(tides=[{"type": "HIGH", "time": past}]), "metric"
        )
        is None
    )
    assert desc.value_fn(MetServicePublicData(tides=None), "metric") is None
    assert (
        desc.value_fn(MetServicePublicData(tides=_future_tides("KING")), "metric")
        is None
    )
    # Non-dict entries are skipped rather than crashing the derivation.
    junk_then_low = ["junk"] + _future_tides("LOW")
    assert (
        desc.value_fn(MetServicePublicData(tides=junk_then_low), "metric") == "falling"
    )


def test_tide_direction_attr_carries_full_table():
    """The carrier attribute holds the whole table; {} when there is no table."""
    desc = _desc("tide_direction")
    tides = _future_tides("HIGH", "LOW")
    data = MetServicePublicData(tides=tides)
    assert desc.attr_fn(data) == {"tide_table": tides}
    assert desc.attr_fn(MetServicePublicData(tides=None)) == {}
    assert desc.attr_fn(MetServicePublicData(tides=[])) == {}


# ---------------------------------------------------------------------------
# Test: weather description full_description attribute gating
# ---------------------------------------------------------------------------


def test_weather_description_full_attr_only_when_truncated():
    """full_description appears only when the state was actually truncated."""
    desc = _desc("wxPhraseLong")
    short = "Fine, light winds."
    long = "x" * 300
    assert desc.value_fn(MetServicePublicData(forecast_text=short), "metric") == short
    assert desc.attr_fn(MetServicePublicData(forecast_text=short)) == {}
    truncated = desc.value_fn(MetServicePublicData(forecast_text=long), "metric")
    assert len(truncated) == 255
    assert truncated.endswith("...")
    assert desc.attr_fn(MetServicePublicData(forecast_text=long)) == {
        "full_description": long
    }


def test_tides_high_description_attrs_match_value_fn_selection():
    """height_m in attr_fn always reflects the exact entry value_fn selected."""
    desc = _desc("tides_high")
    future = (
        datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=3)
    ).isoformat()
    tides = [{"type": "HIGH", "time": future, "height": "2.1"}]
    data = MetServicePublicData(tides=tides)
    value = desc.value_fn(data, "metric")
    attrs = desc.attr_fn(data)
    assert value is not None
    assert attrs["height_m"] == 2.1


def test_tides_low_description_attrs_match_value_fn_selection():
    """height_m in attr_fn always reflects the exact entry value_fn selected."""
    desc = _desc("tides_low")
    future = (
        datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=5)
    ).isoformat()
    tides = [{"type": "LOW", "time": future, "height": "0.3"}]
    data = MetServicePublicData(tides=tides)
    value = desc.value_fn(data, "metric")
    attrs = desc.attr_fn(data)
    assert value is not None
    assert attrs["height_m"] == 0.3


# ---------------------------------------------------------------------------
# Test: entity_registry default-flag policy across the whole fork
# ---------------------------------------------------------------------------

_DEPRECATED_FORK_KEYS = {
    "uvIndex",
    "weather_warnings",
    "pressureTendencyTrend",
    "wind_strength",
    "fire_season",
    "fire_danger",
    "moon_phase",
    "sunrise",
    "sunset",
    "moonrise",
    "moonset",
    "pollen_levels",
    "pollen_type",
    "moon_phase_date",
}

_NEW_FORK_KEYS = {
    "uv_risk",
    "warning_level",
    "pressure_trend",
    "wind_strength_level",
    "fire_season_status",
    "fire_danger_level",
    "sunrise_at",
    "sunset_at",
    "moonrise_at",
    "moonset_at",
}

_OPT_IN_RAIN_KEYS = {"rain_next_8_hours", "rain_next_24_hours", "next_rain_at"}


def test_deprecated_fork_keys_are_disabled_and_hidden_by_default():
    """Every deprecated fork-table sensor is disabled and hidden by default (existing registry rows stay enabled)."""
    for key in _DEPRECATED_FORK_KEYS:
        desc = _desc(key)
        assert desc.entity_registry_enabled_default is False, key
        assert desc.entity_registry_visible_default is False, key


def test_new_fork_keys_are_enabled_and_visible_by_default():
    """Every replacement sensor introduced by the fork is enabled and visible by default."""
    for key in _NEW_FORK_KEYS:
        desc = _desc(key)
        assert desc.entity_registry_enabled_default is True, key
        assert desc.entity_registry_visible_default is True, key


def test_opt_in_rain_sensors_are_disabled_but_still_visible():
    """The opt-in rain_* sensors are disabled by default but not hidden, unlike deprecated fork-table sensors."""
    for key in _OPT_IN_RAIN_KEYS:
        desc = _desc(key)
        assert desc.entity_registry_enabled_default is False, key
        assert desc.entity_registry_visible_default is True, key


def test_fork_key_sets_are_disjoint_and_cover_all_deprecated_keys():
    """The deprecated/replacement key sets don't overlap and match DEPRECATED_SENSOR_REPLACEMENTS exactly."""
    from custom_components.metservice_weather.deprecation import (
        DEPRECATED_SENSOR_REPLACEMENTS,
    )

    assert _DEPRECATED_FORK_KEYS.isdisjoint(_NEW_FORK_KEYS)
    assert set(DEPRECATED_SENSOR_REPLACEMENTS) == _DEPRECATED_FORK_KEYS
