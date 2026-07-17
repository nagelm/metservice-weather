"""Tests for the auto_hide_seasonal onboarding option (sensor.py gating).

CONF_AUTO_HIDE_SEASONAL used to remove seasonal sensors' registry rows
outright while MetService published no data for them. It now disables +
hides those rows instead (keeping history/settings), pre-creating them
born disabled+hidden on a fresh install, and re-enabling + live-adding them
via a coordinator listener once data resumes — see sensor.py's
async_setup_entry docstring for the full mechanism.
"""

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

# The nine descriptions the spec marks seasonal — pulled from the live
# descriptions list so this stays in sync with weather_current_conditions_sensors.py.
SEASONAL_KEYS = {
    d.key for d in current_condition_sensor_descriptions_public if d.seasonal
}

# The three OLD (deprecated) seasonal keys — left entirely to the
# deprecation sweep; our seasonal-disable mechanism must never touch them.
_DEPRECATED_SEASONAL_KEYS = {"uvIndex", "fire_season", "fire_danger"}

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
    sensor ends up stamped. These tests call async_setup_entry directly
    rather than through the full config entry lifecycle, so nothing else
    would cancel that timer — and pytest_homeassistant_custom_component
    fails the test on any timer left on the event loop afterwards.
    """
    await entry._async_process_on_unload(hass)


async def _async_setup_full(
    hass, entry: MockConfigEntry, data: MetServicePublicData
) -> WeatherUpdateCoordinator:
    """Run the real config-entry setup (coordinator + weather + sensor platforms).

    Only used by tests that need genuine entity-platform behaviour —
    specifically, whether a disabled registry row keeps its entity out of
    the state machine, and whether a re-enabled one goes live without a
    restart. That requires a real AddEntitiesCallback, which the plain
    list-capturing callback the other tests use here does not provide.

    _async_update_data (not async_config_entry_first_refresh, unlike
    test_init.py) is patched so the coordinator's `.data` ends up holding
    exactly the MetServicePublicData passed in, with no real network I/O.
    """
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


# ---------------------------------------------------------------------------
# Sanity: exactly the nine documented descriptions are marked seasonal
# ---------------------------------------------------------------------------


def test_exactly_nine_seasonal_descriptions_marked():
    """Deprecated + replacement UV/fire_season/fire_danger sensors, plus drying_*, are marked seasonal (9 total)."""
    assert {
        "uvIndex",
        "uv_risk",
        "fire_season",
        "fire_season_status",
        "fire_danger",
        "fire_danger_level",
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
# (a2) option ON, seasonal descriptions gated independently by data —
#      one with data stays untouched, the rest (still dataless) get
#      disabled+hidden+stamped
# ---------------------------------------------------------------------------


async def test_option_on_gates_each_seasonal_description_independently(hass):
    """Only the currently-dataless seasonal descriptions are disabled; one with data is left alone."""
    entry = _make_entry(auto_hide_seasonal=True)
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)
    # uv_risk's value_fn reads uv_alert_level (mapped through the ENUM
    # mapping) — give it data so it's the one description NOT dataless
    # this run; every other seasonal description stays dataless.
    coord.data = MetServicePublicData(uv_alert_level="Moderate")
    entry.runtime_data = coord
    loc = coord.location

    ent_reg = er.async_get(hass)
    # Pre-create uv_risk's row (enabled) so there's something to observe
    # staying untouched — the fake add_entities below never itself creates
    # registry rows, unlike the real entity platform.
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


# ---------------------------------------------------------------------------
# (b) option ON + no data, pre-existing enabled row — the row is disabled
#     + hidden + stamped instead of removed, and the sensor stays out of
#     the state machine
# ---------------------------------------------------------------------------


async def test_option_on_dataless_seasonal_disables_existing_row(hass):
    """A dataless seasonal sensor's existing row is disabled+hidden+stamped, not removed.

    Home Assistant's real entity platform never instantiates an entity
    whose registry row is already disabled, so the entity stays out of the
    state machine — but its row survives (unlike the old remove-outright
    behaviour), keeping history/settings intact for when data resumes.
    """
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


# ---------------------------------------------------------------------------
# (c) option ON + no data, no pre-existing row — a fresh install (or one an
#     old remove-outright install left with no row) is born disabled+hidden
# ---------------------------------------------------------------------------


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

    # The stale-registry cleanup must never have touched this unique_id —
    # it's still expected (built into `sensors`) even though it's dataless.
    keys = {s.entity_description.key for s in added}
    assert "drying_index_morning" in keys

    await _cleanup_listeners(hass, entry)


# ---------------------------------------------------------------------------
# (d) data resumes — row re-enabled, unhidden, unstamped, added live; a
#     pre-existing unrelated sweep stamp on the same row survives; firing
#     the listener again is a no-op
# ---------------------------------------------------------------------------


async def test_option_on_resume_re_enables_and_adds_live(hass):
    """Data resuming clears disabled_by/hidden_by, drops the stamp, and adds the sensor live.

    A pre-existing {"swept": "hidden"} key in the same row's DOMAIN options
    (simulating the deprecation sweep having separately touched this row)
    must survive both the initial stamp and its later removal — proving
    the merge helper never clobbers keys it doesn't own.
    """
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

    # Data resumes.
    coordinator.data = MetServicePublicData(uv_alert_level="Moderate")
    coordinator.async_update_listeners()
    await hass.async_block_till_done()

    reg_entry = ent_reg.async_get(entity_id)
    assert reg_entry.disabled_by is None
    assert reg_entry.hidden_by is None
    assert reg_entry.options[DOMAIN] == {"swept": "hidden"}
    assert hass.states.get(entity_id) is not None

    # Firing again with unchanged data must be a no-op (no crash, no
    # duplicate add — the description was already popped off the watch dict).
    coordinator.async_update_listeners()
    await hass.async_block_till_done()
    assert hass.states.get(entity_id) is not None

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


# ---------------------------------------------------------------------------
# (e) a USER-disabled seasonal row is never touched by this mechanism
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# (f) deprecated seasonal keys (uvIndex, fire_season, fire_danger) are
#     never touched by this mechanism, even when dataless — left entirely
#     to the deprecation sweep
# ---------------------------------------------------------------------------


async def test_option_on_never_stamps_deprecated_seasonal_keys(hass):
    """Deprecated seasonal keys are never disabled/stamped by the seasonal mechanism."""
    entry = _make_entry(auto_hide_seasonal=True)
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)  # all seasonal fields None -> dataless
    entry.runtime_data = coord
    loc = coord.location

    ent_reg = er.async_get(hass)
    # A pre-existing row for one deprecated key, to prove even an existing,
    # fully-enabled row is left alone by this mechanism (whatever the
    # separate deprecation sweep independently decides to do with it).
    pre_existing = ent_reg.async_get_or_create(
        "sensor", DOMAIN, f"{loc}_uvIndex".lower(), config_entry=entry
    )

    added = []

    def add_entities(entities, *args, **kwargs):
        added.extend(entities)

    await async_setup_entry(hass, entry, add_entities)

    reg_entry = ent_reg.async_get(pre_existing.entity_id)
    assert "seasonal_disabled" not in (reg_entry.options.get(DOMAIN) or {})

    for key in _DEPRECATED_SEASONAL_KEYS - {"uvIndex"}:
        entity_id = ent_reg.async_get_entity_id(
            "sensor", DOMAIN, f"{loc}_{key}".lower()
        )
        # This mechanism never pre-creates a row for a deprecated key, so
        # no row existing at all is itself proof it was never touched.
        assert entity_id is None

    await _cleanup_listeners(hass, entry)


# ---------------------------------------------------------------------------
# (g) option OFF at setup with a previously stamped row — restored in one
#     pass, and the sensor is created normally
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# value_fn raising is treated as dataless (guarded by try/except), not
# created and not propagated as an error out of async_setup_entry
# ---------------------------------------------------------------------------


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
