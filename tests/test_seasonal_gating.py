"""Tests for the auto_hide_seasonal onboarding option (sensor.py gating)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

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

SEASONAL_KEYS = {
    d.key for d in current_condition_sensor_descriptions_public if d.seasonal
}

LOCATION = "/towns-cities/regions/hawkes-bay/locations/napier"


def _make_coordinator(hass) -> WeatherUpdateCoordinator:
    config = WeatherUpdateCoordinatorConfig(
        api_url="https://www.metservice.com/publicData/webdata",
        warnings_url="https://www.metservice.com/publicData/webdata/warnings-service",
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
    """Run any entry.async_on_unload callbacks registered during setup."""
    await entry._async_process_on_unload(hass)


async def _async_setup_full(
    hass, entry: MockConfigEntry, data: MetServicePublicData
) -> WeatherUpdateCoordinator:
    """Run the real config-entry setup (coordinator + weather + sensor platforms)."""
    entry.add_to_hass(hass)
    with patch.object(
        WeatherUpdateCoordinator,
        "_async_update_data",
        AsyncMock(return_value=data),
    ):
        result = await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert result is True
    return entry.runtime_data


async def test_option_on_row_recreated_from_deleted_snapshot_ends_disabled(hass):
    """A row restored from a deleted (enabled) snapshot still ends disabled+hidden+stamped."""
    entry = _make_entry(auto_hide_seasonal=True)
    ent_reg = er.async_get(hass)
    unique_id = f"{LOCATION}_drying_index_morning".lower()

    pre = ent_reg.async_get_or_create(
        "sensor", DOMAIN, unique_id, suggested_object_id="napier_drying_morning"
    )
    assert pre.disabled_by is None
    ent_reg.async_remove(pre.entity_id)
    assert ent_reg.async_get_entity_id("sensor", DOMAIN, unique_id) is None

    await _async_setup_full(hass, entry, MetServicePublicData())

    entity_id = ent_reg.async_get_entity_id("sensor", DOMAIN, unique_id)
    assert entity_id is not None
    reg_entry = ent_reg.async_get(entity_id)
    assert reg_entry.disabled_by == er.RegistryEntryDisabler.INTEGRATION
    assert reg_entry.hidden_by == er.RegistryEntryHider.INTEGRATION
    assert reg_entry.options.get(DOMAIN, {}).get("seasonal_disabled") is True
    assert hass.states.get(entity_id) is None

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_option_on_user_disabled_deleted_snapshot_stays_user_owned(hass):
    """A deleted snapshot restored with USER-set flags is respected, not stamped."""
    entry = _make_entry(auto_hide_seasonal=True)
    ent_reg = er.async_get(hass)
    unique_id = f"{LOCATION}_drying_index_morning".lower()

    pre = ent_reg.async_get_or_create(
        "sensor", DOMAIN, unique_id, suggested_object_id="napier_drying_morning"
    )
    ent_reg.async_update_entity(
        pre.entity_id, disabled_by=er.RegistryEntryDisabler.USER
    )
    ent_reg.async_remove(pre.entity_id)

    await _async_setup_full(hass, entry, MetServicePublicData())

    entity_id = ent_reg.async_get_entity_id("sensor", DOMAIN, unique_id)
    assert entity_id is not None
    reg_entry = ent_reg.async_get(entity_id)
    assert reg_entry.disabled_by == er.RegistryEntryDisabler.USER
    assert not (reg_entry.options.get(DOMAIN) or {}).get("seasonal_disabled")

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


def test_exactly_six_seasonal_descriptions_marked():
    """UV/fire_season/fire_danger's replacement sensors, plus drying_*, are marked seasonal (6 total)."""
    assert {
        "uv_risk",
        "fire_season_status",
        "fire_danger_level",
        "drying_index_morning",
        "drying_index_afternoon",
        "drying_next_good_day",
    } == SEASONAL_KEYS


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


async def test_option_on_gates_each_seasonal_description_independently(hass):
    """Only the currently-dataless seasonal descriptions are disabled; one with data is left alone."""
    entry = _make_entry(auto_hide_seasonal=True)
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)
    coord.data = MetServicePublicData(uv_alert_level="Moderate")
    entry.runtime_data = coord
    loc = coord.location

    ent_reg = er.async_get(hass)
    uv_risk = ent_reg.async_get_or_create(
        "sensor", DOMAIN, f"{loc}_uv_risk".lower(), config_entry=entry
    )

    added = []

    def add_entities(entities, *args, **kwargs):
        added.extend(entities)

    await async_setup_entry(hass, entry, add_entities)

    uv_risk_entry = ent_reg.async_get(uv_risk.entity_id)
    assert uv_risk_entry.disabled_by is None
    assert uv_risk_entry.hidden_by is None
    assert "seasonal_disabled" not in (uv_risk_entry.options.get(DOMAIN) or {})

    for key in (
        "fire_season_status",
        "fire_danger_level",
        "drying_index_morning",
        "drying_index_afternoon",
        "drying_next_good_day",
    ):
        entity_id = ent_reg.async_get_entity_id(
            "sensor", DOMAIN, f"{loc}_{key}".lower()
        )
        assert entity_id is not None
        reg_entry = ent_reg.async_get(entity_id)
        assert reg_entry.disabled_by == er.RegistryEntryDisabler.INTEGRATION
        assert reg_entry.hidden_by == er.RegistryEntryHider.INTEGRATION
        assert reg_entry.options.get(DOMAIN, {}).get("seasonal_disabled") is True

    await _cleanup_listeners(hass, entry)


async def test_option_on_dataless_seasonal_disables_existing_row(hass):
    """A dataless seasonal sensor's existing row is disabled+hidden+stamped, not removed."""
    entry = _make_entry(auto_hide_seasonal=True)
    entry.add_to_hass(hass)

    ent_reg = er.async_get(hass)
    unique_id = f"{LOCATION}_uv_risk".lower()
    pre_existing = ent_reg.async_get_or_create(
        "sensor", DOMAIN, unique_id, config_entry=entry
    )
    assert pre_existing.disabled_by is None
    assert pre_existing.hidden_by is None

    coordinator = await _async_setup_full(hass, entry, MetServicePublicData())

    entity_id = ent_reg.async_get_entity_id("sensor", DOMAIN, unique_id)
    assert entity_id == pre_existing.entity_id  # row not removed, same row reused

    reg_entry = ent_reg.async_get(entity_id)
    assert reg_entry is not None
    assert reg_entry.disabled_by == er.RegistryEntryDisabler.INTEGRATION
    assert reg_entry.hidden_by == er.RegistryEntryHider.INTEGRATION
    assert reg_entry.options.get(DOMAIN, {}).get("seasonal_disabled") is True

    assert hass.states.get(entity_id) is None

    assert coordinator.location == LOCATION  # sanity: real coordinator wired up

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_option_on_dataless_seasonal_fresh_install_born_disabled(hass):
    """A dataless seasonal sensor with no prior registry row is created born disabled+hidden+stamped."""
    entry = _make_entry(auto_hide_seasonal=True)
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)  # all seasonal fields None
    entry.runtime_data = coord
    loc = coord.location

    ent_reg = er.async_get(hass)
    unique_id = f"{loc}_drying_index_morning".lower()
    assert ent_reg.async_get_entity_id("sensor", DOMAIN, unique_id) is None

    added = []

    def add_entities(entities, *args, **kwargs):
        added.extend(entities)

    await async_setup_entry(hass, entry, add_entities)

    entity_id = ent_reg.async_get_entity_id("sensor", DOMAIN, unique_id)
    assert entity_id is not None
    reg_entry = ent_reg.async_get(entity_id)
    assert reg_entry.disabled_by == er.RegistryEntryDisabler.INTEGRATION
    assert reg_entry.hidden_by == er.RegistryEntryHider.INTEGRATION
    assert reg_entry.options.get(DOMAIN, {}).get("seasonal_disabled") is True

    keys = {s.entity_description.key for s in added}
    assert "drying_index_morning" in keys

    await _cleanup_listeners(hass, entry)


async def test_option_on_resume_re_enables_and_adds_live(hass):
    """Data resuming clears disabled_by/hidden_by, drops the stamp, and adds the sensor live."""
    entry = _make_entry(auto_hide_seasonal=True)
    entry.add_to_hass(hass)

    ent_reg = er.async_get(hass)
    unique_id = f"{LOCATION}_uv_risk".lower()
    pre_existing = ent_reg.async_get_or_create(
        "sensor", DOMAIN, unique_id, config_entry=entry
    )
    ent_reg.async_update_entity_options(
        pre_existing.entity_id, DOMAIN, {"swept": "hidden"}
    )

    coordinator = await _async_setup_full(hass, entry, MetServicePublicData())

    entity_id = ent_reg.async_get_entity_id("sensor", DOMAIN, unique_id)
    reg_entry = ent_reg.async_get(entity_id)
    assert reg_entry.disabled_by == er.RegistryEntryDisabler.INTEGRATION
    assert reg_entry.hidden_by == er.RegistryEntryHider.INTEGRATION
    assert reg_entry.options[DOMAIN] == {
        "swept": "hidden",
        "seasonal_disabled": True,
    }
    assert hass.states.get(entity_id) is None

    coordinator.data = MetServicePublicData(uv_alert_level="Moderate")
    coordinator.async_update_listeners()
    await hass.async_block_till_done()

    reg_entry = ent_reg.async_get(entity_id)
    assert reg_entry.disabled_by is None
    assert reg_entry.hidden_by is None
    assert reg_entry.options[DOMAIN] == {"swept": "hidden"}
    assert hass.states.get(entity_id) is not None

    coordinator.async_update_listeners()
    await hass.async_block_till_done()
    assert hass.states.get(entity_id) is not None

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_option_on_user_disabled_seasonal_row_left_untouched(hass):
    """A seasonal row the user disabled themselves is left exactly as-is, unstamped."""
    entry = _make_entry(auto_hide_seasonal=True)
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)  # all seasonal fields None
    entry.runtime_data = coord
    loc = coord.location

    ent_reg = er.async_get(hass)
    unique_id = f"{loc}_fire_danger_level".lower()
    user_disabled = ent_reg.async_get_or_create(
        "sensor",
        DOMAIN,
        unique_id,
        config_entry=entry,
        disabled_by=er.RegistryEntryDisabler.USER,
    )

    added = []

    def add_entities(entities, *args, **kwargs):
        added.extend(entities)

    await async_setup_entry(hass, entry, add_entities)

    reg_entry = ent_reg.async_get(user_disabled.entity_id)
    assert reg_entry.disabled_by == er.RegistryEntryDisabler.USER
    assert reg_entry.hidden_by is None
    assert "seasonal_disabled" not in (reg_entry.options.get(DOMAIN) or {})

    await _cleanup_listeners(hass, entry)


async def test_option_off_restores_previously_stamped_row(hass):
    """Turning the option off un-disables/un-hides/unstamps a row this mechanism stamped, and (re)creates its sensor."""
    entry = _make_entry(auto_hide_seasonal=False)
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)  # all seasonal fields None
    entry.runtime_data = coord
    loc = coord.location

    ent_reg = er.async_get(hass)
    unique_id = f"{loc}_uv_risk".lower()
    stamped = ent_reg.async_get_or_create(
        "sensor",
        DOMAIN,
        unique_id,
        config_entry=entry,
        disabled_by=er.RegistryEntryDisabler.INTEGRATION,
        hidden_by=er.RegistryEntryHider.INTEGRATION,
    )
    ent_reg.async_update_entity_options(
        stamped.entity_id, DOMAIN, {"seasonal_disabled": True}
    )

    added = []

    def add_entities(entities, *args, **kwargs):
        added.extend(entities)

    await async_setup_entry(hass, entry, add_entities)

    reg_entry = ent_reg.async_get(stamped.entity_id)
    assert reg_entry.disabled_by is None
    assert reg_entry.hidden_by is None
    assert "seasonal_disabled" not in (reg_entry.options.get(DOMAIN) or {})

    keys = {s.entity_description.key for s in added}
    assert "uv_risk" in keys


async def test_option_on_stamped_row_with_data_at_setup_is_restored(hass):
    """A row stamped on an earlier start is restored when its sensor has data at setup."""
    entry = _make_entry(auto_hide_seasonal=True)
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)
    coord.data = MetServicePublicData(uv_alert_level="Dangerous")
    entry.runtime_data = coord

    ent_reg = er.async_get(hass)
    stamped = ent_reg.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{coord.location}_uv_risk".lower(),
        config_entry=entry,
        disabled_by=er.RegistryEntryDisabler.INTEGRATION,
        hidden_by=er.RegistryEntryHider.INTEGRATION,
    )
    ent_reg.async_update_entity_options(
        stamped.entity_id, DOMAIN, {"seasonal_disabled": True}
    )

    await async_setup_entry(hass, entry, lambda entities, *args, **kwargs: None)

    reg_entry = ent_reg.async_get(stamped.entity_id)
    assert reg_entry.disabled_by is None
    assert reg_entry.hidden_by is None
    assert "seasonal_disabled" not in (reg_entry.options.get(DOMAIN) or {})
    await _cleanup_listeners(hass, entry)


async def test_option_on_seasonal_value_fn_exception_treated_as_dataless(hass):
    """A seasonal description whose value_fn raises is disabled/stamped, not crashed on."""
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
    assert "broken_seasonal" in keys  # still built + handed to async_add_entities

    ent_reg = er.async_get(hass)
    unique_id = f"{coord.location}_broken_seasonal".lower()
    entity_id = ent_reg.async_get_entity_id("sensor", DOMAIN, unique_id)
    assert entity_id is not None
    reg_entry = ent_reg.async_get(entity_id)
    assert reg_entry.disabled_by == er.RegistryEntryDisabler.INTEGRATION
    assert reg_entry.options.get(DOMAIN, {}).get("seasonal_disabled") is True

    await _cleanup_listeners(hass, entry)
