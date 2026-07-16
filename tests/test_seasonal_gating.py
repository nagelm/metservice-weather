"""Tests for the auto_hide_seasonal onboarding option (sensor.py gating)."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.metservice_weather.sensor as sensor_module
from custom_components.metservice_weather.const import DOMAIN, CONF_AUTO_HIDE_SEASONAL
from custom_components.metservice_weather.coordinator import (
    WeatherUpdateCoordinator,
    WeatherUpdateCoordinatorConfig,
)
from custom_components.metservice_weather.coordinator_types import MetServicePublicData
from custom_components.metservice_weather.sensor import async_setup_entry
from custom_components.metservice_weather.weather_current_conditions_sensors import (
    WeatherSensorEntityDescription,
    current_condition_sensor_descriptions_public,
)

# The six descriptions the spec marks seasonal — pulled from the live
# descriptions list so this stays in sync with weather_current_conditions_sensors.py.
SEASONAL_KEYS = {
    d.key for d in current_condition_sensor_descriptions_public if d.seasonal
}

LOCATION = "/towns-cities/regions/hawkes-bay/locations/napier"


# ---------------------------------------------------------------------------
# Helper: minimal coordinator with pre-loaded data (mirrors test_sensor.py)
# ---------------------------------------------------------------------------


def _make_coordinator(hass) -> WeatherUpdateCoordinator:
    config = WeatherUpdateCoordinatorConfig(
        api_url="https://www.metservice.com/publicData/webdata",
        warnings_url="https://www.metservice.com/publicData/webdata/warnings-service",
        unit_system_api="m",
        unit_system="metric",
        location=LOCATION,
        location_name="Napier",
        tide_url="",
        boating_url="",
        surf_url="",
    )
    coord = WeatherUpdateCoordinator(hass, config)
    coord.data = MetServicePublicData()
    return coord


def _make_entry(*, auto_hide_seasonal: bool) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        data={
            "name": "Napier",
            "location": LOCATION,
            "api": "public",
            "marine_region": "",
            "tide_url": "",
            "boating_url": "",
            "surf_url": "",
            CONF_AUTO_HIDE_SEASONAL: auto_hide_seasonal,
        },
    )


async def _cleanup_listeners(hass, entry: MockConfigEntry) -> None:
    """Run any entry.async_on_unload callbacks registered during setup.

    async_setup_entry registers a coordinator listener (and therefore
    schedules a DataUpdateCoordinator refresh timer) whenever a seasonal
    sensor is skipped. These tests call async_setup_entry directly rather
    than through the full config entry lifecycle, so nothing else would
    cancel that timer — and pytest_homeassistant_custom_component fails the
    test on any timer left on the event loop afterwards.
    """
    await entry._async_process_on_unload(hass)


# ---------------------------------------------------------------------------
# Sanity: exactly the six documented descriptions are marked seasonal
# ---------------------------------------------------------------------------


def test_exactly_six_seasonal_descriptions_marked():
    """Only uvIndex/fire_season/fire_danger/drying_* are marked seasonal."""
    assert {
        "uvIndex",
        "fire_season",
        "fire_danger",
        "drying_index_morning",
        "drying_index_afternoon",
        "drying_next_good_day",
    } == SEASONAL_KEYS


# ---------------------------------------------------------------------------
# (a) option OFF + no data — seasonal sensors are still created (regression)
# ---------------------------------------------------------------------------


async def test_option_off_creates_seasonal_sensors_without_data(hass):
    """With auto_hide_seasonal off, seasonal sensors are always created."""
    entry = _make_entry(auto_hide_seasonal=False)
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)  # all seasonal fields None
    entry.runtime_data = coord

    added = []

    def add_entities(entities, *args, **kwargs):
        added.extend(entities)

    await async_setup_entry(hass, entry, add_entities)

    keys = {s.entity_description.key for s in added}
    assert SEASONAL_KEYS.issubset(keys)


# ---------------------------------------------------------------------------
# (b) option ON + no data — seasonal sensors skipped, stale registry
#     entries removed, non-seasonal ungated sensors still created
# ---------------------------------------------------------------------------


async def test_option_on_skips_dataless_seasonal_sensors(hass):
    """With auto_hide_seasonal on and no data, seasonal sensors are skipped.

    A pre-existing registry entry for one of them is cleaned up by the
    existing stale-registry pass, and non-seasonal, ungated sensors are
    still created as usual.
    """
    entry = _make_entry(auto_hide_seasonal=True)
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)  # all seasonal fields None
    entry.runtime_data = coord
    loc = coord.location

    ent_reg = er.async_get(hass)
    stale_uv = ent_reg.async_get_or_create(
        "sensor", DOMAIN, f"{loc}_uvIndex".lower(), config_entry=entry
    )

    added = []

    def add_entities(entities, *args, **kwargs):
        added.extend(entities)

    await async_setup_entry(hass, entry, add_entities)

    keys = {s.entity_description.key for s in added}
    assert keys.isdisjoint(SEASONAL_KEYS)
    assert "weather_warnings" in keys

    assert ent_reg.async_get(stale_uv.entity_id) is None

    await _cleanup_listeners(hass, entry)


# ---------------------------------------------------------------------------
# (c) option ON + UV data present, fire absent — UV created, fire not
# ---------------------------------------------------------------------------


async def test_option_on_creates_only_seasonal_sensors_with_data(hass):
    """Seasonal sensors are gated independently — only ones with data appear."""
    entry = _make_entry(auto_hide_seasonal=True)
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)
    # uvIndex's value_fn now reads uv_alert_level (mapped through the ENUM
    # mapping), not the legacy uv_index status- string.
    coord.data = MetServicePublicData(uv_alert_level="Moderate")
    entry.runtime_data = coord

    added = []

    def add_entities(entities, *args, **kwargs):
        added.extend(entities)

    await async_setup_entry(hass, entry, add_entities)

    keys = {s.entity_description.key for s in added}
    assert "uvIndex" in keys
    assert keys.isdisjoint(
        {
            "fire_season",
            "fire_danger",
            "drying_index_morning",
            "drying_index_afternoon",
            "drying_next_good_day",
        }
    )

    await _cleanup_listeners(hass, entry)


# ---------------------------------------------------------------------------
# (d) option ON, all seasonal dataless at setup, then data arrives — the
#     newly-available sensors are added exactly once (idempotent listener)
# ---------------------------------------------------------------------------


async def test_option_on_listener_adds_sensors_once_data_arrives(hass):
    """A coordinator update that supplies drying data creates those sensors.

    Firing the listener a second time with unchanged data must not create
    duplicate entities.
    """
    entry = _make_entry(auto_hide_seasonal=True)
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)  # all seasonal fields None
    entry.runtime_data = coord

    added = []

    def add_entities(entities, *args, **kwargs):
        added.extend(entities)

    await async_setup_entry(hass, entry, add_entities)

    keys_after_setup = {s.entity_description.key for s in added}
    assert keys_after_setup.isdisjoint(SEASONAL_KEYS)

    # Simulate a poll that now carries drying data, but still no UV/fire.
    coord.data = MetServicePublicData(
        drying_morning="2 hrs",
        drying_afternoon="1 hr",
        drying_next_good_day="Today",
    )
    coord.async_update_listeners()

    keys_after_first_update = [s.entity_description.key for s in added]
    for key in (
        "drying_index_morning",
        "drying_index_afternoon",
        "drying_next_good_day",
    ):
        assert keys_after_first_update.count(key) == 1
    assert "uvIndex" not in keys_after_first_update
    assert "fire_season" not in keys_after_first_update
    assert "fire_danger" not in keys_after_first_update

    # Fire again with unchanged data — must be a no-op, no duplicates.
    coord.async_update_listeners()

    keys_after_second_update = [s.entity_description.key for s in added]
    assert keys_after_second_update == keys_after_first_update

    await _cleanup_listeners(hass, entry)


# ---------------------------------------------------------------------------
# value_fn raising is treated as dataless (guarded by try/except), not
# created and not propagated as an error out of async_setup_entry
# ---------------------------------------------------------------------------


async def test_option_on_seasonal_value_fn_exception_treated_as_dataless(hass):
    """A seasonal description whose value_fn raises is skipped, not crashed on."""
    entry = _make_entry(auto_hide_seasonal=True)
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)
    entry.runtime_data = coord

    broken = WeatherSensorEntityDescription(
        key="broken_seasonal",
        name="Broken Seasonal",
        seasonal=True,
        value_fn=lambda data, _: 1 / 0,
    )

    added = []

    def add_entities(entities, *args, **kwargs):
        added.extend(entities)

    with patch.object(sensor_module, "SENSOR_DESCRIPTIONS", (broken,)):
        await async_setup_entry(hass, entry, add_entities)

    keys = {s.entity_description.key for s in added}
    assert "broken_seasonal" not in keys

    await _cleanup_listeners(hass, entry)
