"""Tests for the deprecated-entity repair issue check (deprecation.py)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.util import slugify

from custom_components.metservice_weather.const import DOMAIN
from custom_components.metservice_weather.coordinator import (
    WeatherUpdateCoordinator,
    WeatherUpdateCoordinatorConfig,
)
from custom_components.metservice_weather.coordinator_types import MetServicePublicData
from custom_components.metservice_weather.deprecation import (
    DEPRECATED_SENSOR_REPLACEMENTS,
    _GENERIC_REMOVED_REPLACEMENT_FALLBACK,
    _REPLACEMENT_DISPLAY_NAMES,
    _config_entries_referencing,
    _dump_json,
    _format_evidence,
    _format_references,
    _friendly_key,
    _homekit_includes,
    _replacement_display_name,
    _usage_signals,
    async_check_deprecated_entities,
    async_check_marine_device_move,
    async_check_removed_entity,
    async_check_removed_forecast_attributes,
)

LOCATION = "/towns-cities/regions/hawkes-bay/locations/napier"

_AUTOMATIONS_PATCH = (
    "custom_components.metservice_weather.deprecation.automations_with_entity"
)
_SCRIPTS_PATCH = "custom_components.metservice_weather.deprecation.scripts_with_entity"
_SCENES_PATCH = "custom_components.metservice_weather.deprecation.scenes_with_entity"
_GROUPS_PATCH = "custom_components.metservice_weather.deprecation.groups_with_entity"
_VOICE_PATCH = (
    "custom_components.metservice_weather.deprecation.async_get_entity_settings"
)
_AUTOMATIONS_DEVICE_PATCH = (
    "custom_components.metservice_weather.deprecation.automations_with_device"
)
_SCRIPTS_DEVICE_PATCH = (
    "custom_components.metservice_weather.deprecation.scripts_with_device"
)


class _FakeDashboard:
    """Minimal stand-in for a Lovelace LovelaceConfig object."""

    def __init__(self, config, view_config=None, load_error=None):
        self.config = config
        self._view_config = view_config
        self._load_error = load_error

    async def async_load(self, force):
        if self._load_error is not None:
            raise self._load_error
        return self._view_config


class _FakeLovelaceData:
    """Minimal stand-in for homeassistant.components.lovelace.LovelaceData."""

    def __init__(self, dashboards: dict):
        self.dashboards = dashboards


class _FakeAutomationEntity:
    """Minimal stand-in for AutomationEntity/ScriptEntity exposing raw_config."""

    def __init__(self, raw_config):
        self.raw_config = raw_config


class _FakeEntityComponent:
    """Minimal stand-in for EntityComponent exposing get_entity."""

    def __init__(self, entities: dict):
        self._entities = entities

    def get_entity(self, entity_id):
        return self._entities.get(entity_id)


# ---------------------------------------------------------------------------
# Helper: minimal coordinator + config entry (mirrors test_sensor.py)
# ---------------------------------------------------------------------------


def _make_coordinator(
    hass, tide_url="", boating_url="", surf_url=""
) -> WeatherUpdateCoordinator:
    config = WeatherUpdateCoordinatorConfig(
        api_url="https://www.metservice.com/publicData/webdata",
        warnings_url="https://www.metservice.com/publicData/webdata/warnings-service",
        unit_system_api="m",
        unit_system="metric",
        location=LOCATION,
        location_name="Napier",
        tide_url=tide_url,
        boating_url=boating_url,
        surf_url=surf_url,
    )
    coord = WeatherUpdateCoordinator(hass, config)
    coord.data = MetServicePublicData()
    return coord


def _make_entry() -> MockConfigEntry:
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
        },
    )


def _issue_id(entry: MockConfigEntry, old_key: str) -> str:
    return f"deprecated_entity_{entry.entry_id}_{old_key}"


# ---------------------------------------------------------------------------
# Test: DEPRECATED_SENSOR_REPLACEMENTS data contract
# ---------------------------------------------------------------------------


def test_deprecated_sensor_replacements_covers_all_fourteen_old_keys():
    """Every OLD key from the fork table is mapped, pollen_levels/pollen_type -> pollen."""
    assert set(DEPRECATED_SENSOR_REPLACEMENTS) == {
        "uvIndex",
        "weather_warnings",
        "pressureTendencyTrend",
        "wind_strength",
        "fire_season",
        "fire_danger",
        "moon_phase",
        "moon_phase_date",
        "sunrise",
        "sunset",
        "moonrise",
        "moonset",
        "pollen_levels",
        "pollen_type",
    }
    assert DEPRECATED_SENSOR_REPLACEMENTS["pollen_levels"] == "pollen"
    assert DEPRECATED_SENSOR_REPLACEMENTS["pollen_type"] == "pollen"
    assert DEPRECATED_SENSOR_REPLACEMENTS["uvIndex"] == "uv_risk"


# ---------------------------------------------------------------------------
# Test: _friendly_key / _format_references helpers
# ---------------------------------------------------------------------------


def test_friendly_key_formats_snake_case_with_uv_uppercased():
    """Snake_case keys become title-cased words, with 'uv' specially uppercased."""
    assert _friendly_key("uv_risk") == "UV Risk"
    assert _friendly_key("warning_level") == "Warning Level"
    assert _friendly_key("pollen") == "Pollen"


def test_replacement_display_names_cover_every_replacement_key():
    """_REPLACEMENT_DISPLAY_NAMES has an entry for every value in DEPRECATED_SENSOR_REPLACEMENTS."""
    assert set(DEPRECATED_SENSOR_REPLACEMENTS.values()) <= set(
        _REPLACEMENT_DISPLAY_NAMES
    )


def test_replacement_display_name_diverges_from_friendly_key_for_uv_risk():
    """_replacement_display_name uses the real sensor name, not _friendly_key's mechanical guess."""
    assert _friendly_key("uv_risk") == "UV Risk"
    assert _replacement_display_name("uv_risk") == "UV index"


def test_replacement_display_name_diverges_from_friendly_key_for_warning_level():
    """warning_level's real sensor name is "Warnings", not "Warning Level"."""
    assert _friendly_key("warning_level") == "Warning Level"
    assert _replacement_display_name("warning_level") == "Warnings"


def test_replacement_display_name_moon_sensors_map_to_moon_phase_current():
    """Both deprecated moon sensors replace to moon_phase_current ("Moon phase")."""
    assert DEPRECATED_SENSOR_REPLACEMENTS["moon_phase"] == "moon_phase_current"
    assert DEPRECATED_SENSOR_REPLACEMENTS["moon_phase_date"] == "moon_phase_current"
    assert _replacement_display_name("moon_phase_current") == "Moon phase"


def test_replacement_display_name_falls_back_to_friendly_key_for_unmapped_key():
    """A key with no explicit entry in _REPLACEMENT_DISPLAY_NAMES falls back to _friendly_key."""
    assert _replacement_display_name("some_unmapped_key") == _friendly_key(
        "some_unmapped_key"
    )


def test_format_references_short_list_joins_with_commas():
    """A reference list at or under the cap is comma-joined verbatim."""
    assert (
        _format_references(["automation.a", "automation.b"])
        == "automation.a, automation.b"
    )


def test_format_references_caps_long_list_with_suffix():
    """A reference list over the cap is truncated with a '+N more' suffix."""
    refs = [f"automation.a{i}" for i in range(15)]
    result = _format_references(refs)
    assert result.endswith("(+5 more)")
    assert all(f"automation.a{i}" in result for i in range(10))
    assert "automation.a14" not in result


# ---------------------------------------------------------------------------
# Test: async_check_deprecated_entities — v2026.9.0 rework. No deprecated
# sensor descriptions remain (see weather_current_conditions_sensors.py), so
# this function no longer runs a disable/hide usage sweep; it only clears
# any leftover pre-2026.9.0 deprecation issues and hands off to the
# entity-ID reclaim detector (async_check_entity_id_reclaim, exercised
# through async_check_deprecated_entities here to prove the wiring; its own
# behaviour is covered in detail in tests/test_repairs.py).
# ---------------------------------------------------------------------------


def _hidden_notice_id(entry: MockConfigEntry) -> str:
    return f"hidden_deprecated_{entry.entry_id}"


def _sweep_notice_id(entry: MockConfigEntry) -> str:
    return f"deprecated_sweep_v2_{entry.entry_id}"


async def test_leftover_deprecated_entity_issues_cleared_for_every_old_key(hass):
    """A leftover deprecated_entity issue from a pre-2026.9.0 install is cleared for every OLD key."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)

    for old_key in DEPRECATED_SENSOR_REPLACEMENTS:
        ir.async_create_issue(
            hass,
            DOMAIN,
            _issue_id(entry, old_key),
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key="deprecated_entity",
        )

    await async_check_deprecated_entities(hass, entry, coord)

    for old_key in DEPRECATED_SENSOR_REPLACEMENTS:
        assert (
            ir.async_get(hass).async_get_issue(DOMAIN, _issue_id(entry, old_key))
            is None
        )


async def test_leftover_deprecated_sweep_v2_issue_cleared(hass):
    """A leftover deprecated_sweep_v2 summary issue is cleared."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)

    notice_id = _sweep_notice_id(entry)
    ir.async_create_issue(
        hass,
        DOMAIN,
        notice_id,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="deprecated_sweep_v2",
        translation_placeholders={
            "disabled_count": "1",
            "disabled_entity_ids": "sensor.napier_uvindex",
            "hidden_count": "0",
            "hidden_entity_ids": "none",
        },
    )
    assert ir.async_get(hass).async_get_issue(DOMAIN, notice_id) is not None

    await async_check_deprecated_entities(hass, entry, coord)

    assert ir.async_get(hass).async_get_issue(DOMAIN, notice_id) is None


async def test_leftover_hidden_deprecated_issue_cleared(hass):
    """A leftover pre-2026.7.1 'hidden_deprecated' issue is cleared."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)

    legacy_id = _hidden_notice_id(entry)
    ir.async_create_issue(
        hass,
        DOMAIN,
        legacy_id,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="hidden_deprecated",
        translation_placeholders={"count": "1", "entity_ids": "sensor.napier_uvindex"},
    )
    assert ir.async_get(hass).async_get_issue(DOMAIN, legacy_id) is not None

    await async_check_deprecated_entities(hass, entry, coord)

    assert ir.async_get(hass).async_get_issue(DOMAIN, legacy_id) is None


async def test_cleanup_is_idempotent_when_nothing_left_to_clear(hass):
    """A safe no-op when no leftover deprecation issues exist for this entry."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)

    # Must not raise, and must not create anything new.
    await async_check_deprecated_entities(hass, entry, coord)

    for old_key in DEPRECATED_SENSOR_REPLACEMENTS:
        assert (
            ir.async_get(hass).async_get_issue(DOMAIN, _issue_id(entry, old_key))
            is None
        )
    assert ir.async_get(hass).async_get_issue(DOMAIN, _sweep_notice_id(entry)) is None
    assert ir.async_get(hass).async_get_issue(DOMAIN, _hidden_notice_id(entry)) is None


async def test_exception_inside_cleanup_does_not_propagate(hass):
    """A failure anywhere inside the cleanup step is swallowed, never raised out of setup."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)

    with patch(
        "custom_components.metservice_weather.deprecation.ir.async_get",
        side_effect=RuntimeError("boom"),
    ):
        # Must not raise.
        await async_check_deprecated_entities(hass, entry, coord)


async def test_deprecated_entities_check_invokes_entity_id_reclaim_detector(hass):
    """async_check_deprecated_entities hands off to the entity-ID reclaim detector.

    Full reclaim-detector behaviour (fixable vs. referenced vs. self-clear)
    is covered in tests/test_repairs.py — this just proves the wiring, using
    a plain AsyncMock (no side_effect) so the call itself is observed
    without exercising async_check_entity_id_reclaim's own, independent
    exception guard.
    """
    entry = _make_entry()
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)

    with patch(
        "custom_components.metservice_weather.deprecation.async_check_entity_id_reclaim",
        new=AsyncMock(),
    ) as mock_reclaim:
        await async_check_deprecated_entities(hass, entry, coord)

    mock_reclaim.assert_called_once_with(hass, entry, coord)


# ---------------------------------------------------------------------------
# Part 2: removal rehearsal — the real v2026.9.0 upgrade path, via genuine
# config-entry setup (coordinator + weather + sensor platforms), not a
# hand-rolled add_entities callback. This is what actually happens the
# first time an existing install with an old, still-registered deprecated
# sensor row starts up on v2026.9.0: sensor.py's stale-registry cleanup
# removes it (having asked async_check_removed_entity to raise a repair
# first if it's still referenced).
# ---------------------------------------------------------------------------


async def _async_setup_full(
    hass, entry: MockConfigEntry, data: MetServicePublicData
) -> WeatherUpdateCoordinator:
    """Run the real config-entry setup (coordinator + weather + sensor platforms).

    Mirrors test_seasonal_gating.py's helper of the same name.
    _async_update_data is patched so the coordinator's `.data` ends up
    holding exactly the MetServicePublicData passed in, with no real
    network I/O.
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


async def test_2026_9_upgrade_removes_referenced_deprecated_row_with_repair(hass):
    """A re-enabled, still-referenced deprecated row is removed on real setup, with a removed_entity repair naming the reference and the replacement."""
    entry = _make_entry()
    entry.add_to_hass(hass)

    ent_reg = er.async_get(hass)
    unique_id = f"{LOCATION}_uvIndex".lower()
    stale = ent_reg.async_get_or_create("sensor", DOMAIN, unique_id, config_entry=entry)
    # Simulate an install where this row survived enabled — e.g. it was
    # never swept by an older integration version, or the user re-enabled
    # it themselves at some point.
    ent_reg.async_update_entity(stale.entity_id, disabled_by=None)
    entity_id = stale.entity_id
    assert ent_reg.async_get(entity_id).disabled_by is None

    hass.config.components.add("automation")
    hass.config.components.add("script")
    with (
        patch(_AUTOMATIONS_PATCH, return_value=["automation.check_uv"]),
        patch(_SCRIPTS_PATCH, return_value=[]),
    ):
        await _async_setup_full(hass, entry, MetServicePublicData())

    # The row is gone from the registry.
    assert ent_reg.async_get(entity_id) is None
    assert ent_reg.async_get_entity_id("sensor", DOMAIN, unique_id) is None

    # A removed_entity repair was raised naming the reference and the
    # replacement's display name.
    issue_id = f"removed_entity_{entry.entry_id}_{slugify(entity_id)}"
    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.translation_placeholders["entity_id"] == entity_id
    assert "automation.check_uv" in issue.translation_placeholders["references"]
    assert issue.translation_placeholders["replacement"] == "UV index"

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_2026_9_upgrade_removes_unreferenced_deprecated_row_silently(hass):
    """An unreferenced deprecated row is removed on real setup with no removed_entity issue raised."""
    entry = _make_entry()
    entry.add_to_hass(hass)

    ent_reg = er.async_get(hass)
    unique_id = f"{LOCATION}_uvIndex".lower()
    stale = ent_reg.async_get_or_create("sensor", DOMAIN, unique_id, config_entry=entry)
    entity_id = stale.entity_id

    hass.config.components.add("automation")
    hass.config.components.add("script")
    with (
        patch(_AUTOMATIONS_PATCH, return_value=[]),
        patch(_SCRIPTS_PATCH, return_value=[]),
    ):
        await _async_setup_full(hass, entry, MetServicePublicData())

    assert ent_reg.async_get_entity_id("sensor", DOMAIN, unique_id) is None

    issue_id = f"removed_entity_{entry.entry_id}_{slugify(entity_id)}"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


# ---------------------------------------------------------------------------
# Test: _usage_signals — one test per evidence source, plus failure paths
# ---------------------------------------------------------------------------

_UV_ENTITY_ID = "sensor.napier_uvindex"


async def test_usage_signals_empty_when_nothing_matches(hass):
    """No source contributing anything means UNUSED (empty dict)."""
    assert await _usage_signals(hass, _UV_ENTITY_ID) == {}


async def test_usage_signals_combines_automations_and_scripts(hass):
    """Automation and script references are collected under their own separate keys."""
    hass.config.components.add("automation")
    hass.config.components.add("script")
    with (
        patch(_AUTOMATIONS_PATCH, return_value=["automation.a"]),
        patch(_SCRIPTS_PATCH, return_value=["script.b"]),
    ):
        signals = await _usage_signals(hass, _UV_ENTITY_ID)
    assert signals["automations"] == ["automation.a"]
    assert signals["scripts"] == ["script.b"]


async def test_usage_signals_detects_scene_reference(hass):
    """A scene that references the entity shows up under the "scenes" signal."""
    hass.config.components.add("scene")
    with patch(_SCENES_PATCH, return_value=["scene.evening"]):
        signals = await _usage_signals(hass, _UV_ENTITY_ID)
    assert signals["scenes"] == ["scene.evening"]


async def test_usage_signals_scene_not_loaded_contributes_no_signal(hass):
    """Without the "scene" component loaded, scenes_with_entity is never even called."""
    with patch(_SCENES_PATCH) as mock_scenes:
        signals = await _usage_signals(hass, _UV_ENTITY_ID)
        mock_scenes.assert_not_called()
    assert "scenes" not in signals


async def test_usage_signals_detects_group_reference(hass):
    """A group that references the entity shows up under the "groups" signal."""
    hass.config.components.add("group")
    with patch(_GROUPS_PATCH, return_value=["group.weather"]):
        signals = await _usage_signals(hass, _UV_ENTITY_ID)
    assert signals["groups"] == ["group.weather"]


async def test_usage_signals_detects_dashboard_reference(hass):
    """A Lovelace dashboard whose loaded config mentions the entity is detected, named by its title."""
    hass.config.components.add("lovelace")
    dash = _FakeDashboard(
        config={"title": "Home"},
        view_config={
            "views": [{"cards": [{"type": "entity", "entity": _UV_ENTITY_ID}]}]
        },
    )
    hass.data["lovelace"] = _FakeLovelaceData({"home": dash})

    signals = await _usage_signals(hass, _UV_ENTITY_ID)
    assert signals["dashboards"] == ["Home"]


async def test_usage_signals_dashboard_default_title_falls_back_to_url_path(hass):
    """A dashboard with no registered title (e.g. the default dashboard) falls back to url_path/'default'."""
    hass.config.components.add("lovelace")
    dash = _FakeDashboard(
        config=None,
        view_config={"views": [{"cards": [{"entity": _UV_ENTITY_ID}]}]},
    )
    hass.data["lovelace"] = _FakeLovelaceData({None: dash})

    signals = await _usage_signals(hass, _UV_ENTITY_ID)
    assert signals["dashboards"] == ["default"]


async def test_usage_signals_dashboard_load_failure_contributes_no_signal(hass):
    """A dashboard whose async_load() raises (e.g. a strategy dashboard) is silently skipped."""
    hass.config.components.add("lovelace")
    hass.data["lovelace"] = _FakeLovelaceData(
        {None: _FakeDashboard(config=None, load_error=RuntimeError("boom"))}
    )

    signals = await _usage_signals(hass, _UV_ENTITY_ID)
    assert "dashboards" not in signals


async def test_usage_signals_dashboard_not_loaded_contributes_no_signal(hass):
    """When "lovelace" hasn't loaded at all, this source is skipped without touching hass.data."""
    signals = await _usage_signals(hass, _UV_ENTITY_ID)
    assert "dashboards" not in signals


async def test_usage_signals_detects_helper_config_entry_reference(hass):
    """A derivative/utility_meter/etc-style helper config entry counts as usage evidence."""
    helper_entry = MockConfigEntry(
        domain="derivative", title="Rainfall rate", data={"source": _UV_ENTITY_ID}
    )
    helper_entry.add_to_hass(hass)

    signals = await _usage_signals(hass, _UV_ENTITY_ID)
    assert signals["helpers"] == ["derivative: Rainfall rate"]


async def test_usage_signals_helper_scan_excludes_own_domain_and_homekit(hass):
    """Our own config entries and HomeKit entries never show up under 'helpers'."""
    own_entry = MockConfigEntry(
        domain=DOMAIN, title="Napier", data={"entity": _UV_ENTITY_ID}
    )
    own_entry.add_to_hass(hass)
    homekit_entry = MockConfigEntry(
        domain="homekit",
        title="Bridge",
        options={"filter": {"include_entities": [_UV_ENTITY_ID]}},
    )
    homekit_entry.add_to_hass(hass)

    signals = await _usage_signals(hass, _UV_ENTITY_ID)
    assert "helpers" not in signals
    assert signals["homekit"] is True


async def test_usage_signals_helper_scan_skips_malformed_entry_but_keeps_others(hass):
    """A config entry whose data can't be JSON-dumped (e.g. circular) is skipped, not fatal."""
    circular: dict = {}
    circular["self"] = circular
    bad_entry = MockConfigEntry(domain="derivative", title="Bad", data=circular)
    bad_entry.add_to_hass(hass)
    good_entry = MockConfigEntry(
        domain="derivative", title="Good", data={"source": _UV_ENTITY_ID}
    )
    good_entry.add_to_hass(hass)

    signals = await _usage_signals(hass, _UV_ENTITY_ID)
    assert signals["helpers"] == ["derivative: Good"]


async def test_usage_signals_detects_homekit_include(hass):
    """A HomeKit entry whose options mention the entity sets the "homekit" signal."""
    homekit_entry = MockConfigEntry(
        domain="homekit",
        title="Bridge",
        options={"filter": {"include_entities": [_UV_ENTITY_ID]}},
    )
    homekit_entry.add_to_hass(hass)

    signals = await _usage_signals(hass, _UV_ENTITY_ID)
    assert signals["homekit"] is True


async def test_usage_signals_detects_voice_exposure(hass):
    """An assistant with should_expose=True lists that assistant under the "voice" signal."""
    with patch(
        _VOICE_PATCH,
        return_value={
            "conversation": {"should_expose": True},
            "cloud.alexa": {"should_expose": False},
        },
    ):
        signals = await _usage_signals(hass, _UV_ENTITY_ID)
    assert signals["voice"] == ["conversation"]


async def test_usage_signals_voice_exposure_not_ready_contributes_no_signal(hass):
    """exposed_entities raises HomeAssistantError before it's finished loading — that's not a bug."""
    with patch(_VOICE_PATCH, side_effect=HomeAssistantError("not ready")):
        signals = await _usage_signals(hass, _UV_ENTITY_ID)
    assert "voice" not in signals


async def test_usage_signals_detects_in_process_listener(hass):
    """A non-empty callback list keyed by entity_id in the private bookkeeping dict counts as usage."""
    hass.data["track_state_change_data"] = {_UV_ENTITY_ID: [object()]}

    signals = await _usage_signals(hass, _UV_ENTITY_ID)
    assert signals["listeners"] is True


async def test_usage_signals_listener_veto_ignores_non_dict_shape(hass):
    """Current core stores a dataclass here, not a dict — the isinstance guard means no signal, no crash."""

    class _NotADict:
        pass

    hass.data["track_state_change_data"] = _NotADict()

    signals = await _usage_signals(hass, _UV_ENTITY_ID)
    assert "listeners" not in signals


async def test_usage_signals_listener_veto_failure_contributes_no_signal(hass):
    """A raising .get() on the (dict-shaped) bookkeeping object degrades to no signal, not a crash."""

    class _BrokenDict(dict):
        def get(self, *args, **kwargs):
            raise RuntimeError("boom")

    hass.data["track_state_change_data"] = _BrokenDict()

    signals = await _usage_signals(hass, _UV_ENTITY_ID)
    assert "listeners" not in signals


async def test_usage_signals_automations_lookup_failure_contributes_no_signal(hass):
    """automations_with_entity raising degrades to no signal, not a crash."""
    hass.config.components.add("automation")
    with patch(_AUTOMATIONS_PATCH, side_effect=RuntimeError("boom")):
        signals = await _usage_signals(hass, _UV_ENTITY_ID)
    assert "automations" not in signals


async def test_usage_signals_scripts_lookup_failure_contributes_no_signal(hass):
    """scripts_with_entity raising degrades to no signal, not a crash."""
    hass.config.components.add("script")
    with patch(_SCRIPTS_PATCH, side_effect=RuntimeError("boom")):
        signals = await _usage_signals(hass, _UV_ENTITY_ID)
    assert "scripts" not in signals


async def test_usage_signals_scenes_lookup_failure_contributes_no_signal(hass):
    """scenes_with_entity raising degrades to no signal, not a crash."""
    hass.config.components.add("scene")
    with patch(_SCENES_PATCH, side_effect=RuntimeError("boom")):
        signals = await _usage_signals(hass, _UV_ENTITY_ID)
    assert "scenes" not in signals


async def test_usage_signals_groups_lookup_failure_contributes_no_signal(hass):
    """groups_with_entity raising degrades to no signal, not a crash."""
    hass.config.components.add("group")
    with patch(_GROUPS_PATCH, side_effect=RuntimeError("boom")):
        signals = await _usage_signals(hass, _UV_ENTITY_ID)
    assert "groups" not in signals


async def test_usage_signals_dashboards_lookup_failure_contributes_no_signal(hass):
    """A failure inside _dashboards_referencing itself degrades to no signal, not a crash."""
    with patch(
        "custom_components.metservice_weather.deprecation._dashboards_referencing",
        side_effect=RuntimeError("boom"),
    ):
        signals = await _usage_signals(hass, _UV_ENTITY_ID)
    assert "dashboards" not in signals


async def test_usage_signals_helpers_lookup_failure_contributes_no_signal(hass):
    """A failure inside _config_entries_referencing itself degrades to no signal, not a crash."""
    with patch(
        "custom_components.metservice_weather.deprecation._config_entries_referencing",
        side_effect=RuntimeError("boom"),
    ):
        signals = await _usage_signals(hass, _UV_ENTITY_ID)
    assert "helpers" not in signals


async def test_usage_signals_homekit_lookup_failure_contributes_no_signal(hass):
    """A failure inside _homekit_includes itself degrades to no signal, not a crash."""
    with patch(
        "custom_components.metservice_weather.deprecation._homekit_includes",
        side_effect=RuntimeError("boom"),
    ):
        signals = await _usage_signals(hass, _UV_ENTITY_ID)
    assert "homekit" not in signals


async def test_usage_signals_dashboard_empty_config_contributes_no_signal(hass):
    """A dashboard whose async_load() returns falsy (not raising) is silently skipped."""
    hass.config.components.add("lovelace")
    hass.data["lovelace"] = _FakeLovelaceData(
        {None: _FakeDashboard(config=None, view_config=None)}
    )

    signals = await _usage_signals(hass, _UV_ENTITY_ID)
    assert "dashboards" not in signals


async def test_usage_signals_dashboard_without_entity_contributes_no_signal(hass):
    """A dashboard that loads fine but never mentions entity_id contributes nothing."""
    hass.config.components.add("lovelace")
    dash = _FakeDashboard(
        config={"title": "Home"},
        view_config={"views": [{"cards": [{"entity": "sensor.other"}]}]},
    )
    hass.data["lovelace"] = _FakeLovelaceData({"home": dash})

    signals = await _usage_signals(hass, _UV_ENTITY_ID)
    assert "dashboards" not in signals


async def test_dashboards_referencing_falls_back_when_lovelace_data_not_importable(
    hass, monkeypatch
):
    """If LOVELACE_DATA isn't importable (older core), the plain "lovelace" string key is used instead."""
    import homeassistant.components.lovelace as lovelace_module

    monkeypatch.delattr(lovelace_module, "LOVELACE_DATA")
    hass.config.components.add("lovelace")
    hass.data["lovelace"] = _FakeLovelaceData({})

    signals = await _usage_signals(hass, _UV_ENTITY_ID)
    assert "dashboards" not in signals


def test_dump_json_returns_none_for_circular_reference():
    """json.dumps can't serialise a self-referencing structure even with default=str."""
    circular: dict = {}
    circular["self"] = circular
    assert _dump_json(circular) is None


def test_config_entries_referencing_swallows_per_entry_exception(hass):
    """A per-entry failure (e.g. _dump_json itself blowing up) is skipped, not fatal to the scan."""
    entry_x = MockConfigEntry(
        domain="derivative", title="X", data={"source": _UV_ENTITY_ID}
    )
    entry_x.add_to_hass(hass)

    with patch(
        "custom_components.metservice_weather.deprecation._dump_json",
        side_effect=RuntimeError("boom"),
    ):
        assert _config_entries_referencing(hass, _UV_ENTITY_ID) == []


def test_homekit_includes_swallows_per_entry_exception(hass):
    """A per-entry failure while scanning HomeKit entries is skipped, not fatal."""
    homekit_entry = MockConfigEntry(domain="homekit", title="Bridge", options={})
    homekit_entry.add_to_hass(hass)

    with patch(
        "custom_components.metservice_weather.deprecation._dump_json",
        side_effect=RuntimeError("boom"),
    ):
        assert _homekit_includes(hass, _UV_ENTITY_ID) is False


def test_format_evidence_includes_homekit_and_listeners():
    """The two boolean-only sources render as fixed phrases, not joined lists."""
    text = _format_evidence({"homekit": True, "listeners": True})
    assert "HomeKit" in text
    assert "an in-process listener" in text


def test_format_evidence_empty_signals_says_no_specific_usage():
    """An empty signals dict renders as an explicit "no specific usage detected" fallback."""
    assert _format_evidence({}) == "no specific usage detected"


# ---------------------------------------------------------------------------
# Detector 1: async_check_removed_entity (removed entity still referenced)
# ---------------------------------------------------------------------------


def _removed_issue_id(entry: MockConfigEntry, entity_id: str) -> str:
    return f"removed_entity_{entry.entry_id}_{slugify(entity_id)}"


async def test_removed_entity_issue_created_when_referenced(hass):
    """A stale row about to be removed, still referenced, gets a removed_entity issue with a known replacement."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)

    ent_reg = er.async_get(hass)
    reg_entry = ent_reg.async_get_or_create(
        "sensor", DOMAIN, f"{coord.location}_uvIndex".lower(), config_entry=entry
    )

    hass.config.components.add("automation")
    hass.config.components.add("script")
    with (
        patch(_AUTOMATIONS_PATCH, return_value=["automation.check_uv"]),
        patch(_SCRIPTS_PATCH, return_value=[]),
    ):
        await async_check_removed_entity(hass, entry, coord, reg_entry)

    issue_id = _removed_issue_id(entry, reg_entry.entity_id)
    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.translation_placeholders["entity_id"] == reg_entry.entity_id
    assert "automation.check_uv" in issue.translation_placeholders["references"]
    assert issue.translation_placeholders["replacement"] == "UV index"
    assert issue.severity == ir.IssueSeverity.WARNING
    assert issue.is_fixable is False
    assert issue.data == {"entity_id": reg_entry.entity_id}


async def test_removed_entity_unknown_key_uses_generic_replacement_fallback(hass):
    """A removed entity whose unique_id key isn't in DEPRECATED_SENSOR_REPLACEMENTS gets generic wording."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)

    ent_reg = er.async_get(hass)
    # Pre-fork unique_id scheme (comma-separated, no location_ prefix) —
    # no recognisable key suffix at all.
    reg_entry = ent_reg.async_get_or_create(
        "weather", DOMAIN, "napier,weather", config_entry=entry
    )

    hass.config.components.add("automation")
    with (
        patch(_AUTOMATIONS_PATCH, return_value=["automation.dashboard_card"]),
        patch(_SCRIPTS_PATCH, return_value=[]),
    ):
        await async_check_removed_entity(hass, entry, coord, reg_entry)

    issue_id = _removed_issue_id(entry, reg_entry.entity_id)
    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert (
        issue.translation_placeholders["replacement"]
        == _GENERIC_REMOVED_REPLACEMENT_FALLBACK
    )


async def test_self_corrected_user_removed_entity_without_references_stays_silent(hass):
    """A stale row with no automation/script references never gets a removed_entity issue."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)

    ent_reg = er.async_get(hass)
    reg_entry = ent_reg.async_get_or_create(
        "sensor", DOMAIN, f"{coord.location}_uvIndex".lower(), config_entry=entry
    )

    hass.config.components.add("automation")
    hass.config.components.add("script")
    with (
        patch(_AUTOMATIONS_PATCH, return_value=[]),
        patch(_SCRIPTS_PATCH, return_value=[]),
    ):
        await async_check_removed_entity(hass, entry, coord, reg_entry)

    issue_id = _removed_issue_id(entry, reg_entry.entity_id)
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_self_corrected_user_removed_entity_issue_clears_once_dereferenced(hass):
    """A pre-existing removed_entity issue is swept away by async_check_deprecated_entities once nothing references it."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)

    entity_id = "sensor.napier_uvindex"
    issue_id = _removed_issue_id(entry, entity_id)
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="removed_entity",
        data={"entity_id": entity_id},
    )
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None

    hass.config.components.add("automation")
    hass.config.components.add("script")
    with (
        patch(_AUTOMATIONS_PATCH, return_value=[]),
        patch(_SCRIPTS_PATCH, return_value=[]),
    ):
        await async_check_deprecated_entities(hass, entry, coord)

    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_removed_entity_issue_left_untouched_while_still_referenced(hass):
    """The sweep in async_check_deprecated_entities leaves a removed_entity issue alone while still referenced."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)

    entity_id = "sensor.napier_uvindex"
    issue_id = _removed_issue_id(entry, entity_id)
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="removed_entity",
        data={"entity_id": entity_id},
    )

    hass.config.components.add("automation")
    hass.config.components.add("script")
    with (
        patch(_AUTOMATIONS_PATCH, return_value=["automation.still_using_it"]),
        patch(_SCRIPTS_PATCH, return_value=[]),
    ):
        await async_check_deprecated_entities(hass, entry, coord)

    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None


async def test_removed_entity_exception_inside_check_does_not_propagate(hass):
    """A failure anywhere inside the removed-entity check is swallowed, never raised out of setup."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)

    ent_reg = er.async_get(hass)
    reg_entry = ent_reg.async_get_or_create(
        "sensor", DOMAIN, f"{coord.location}_uvIndex".lower(), config_entry=entry
    )

    with patch(
        "custom_components.metservice_weather.deprecation._referencing_items",
        side_effect=RuntimeError("boom"),
    ):
        # Must not raise.
        await async_check_removed_entity(hass, entry, coord, reg_entry)

    issue_id = _removed_issue_id(entry, reg_entry.entity_id)
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


# ---------------------------------------------------------------------------
# Detector 3: async_check_removed_forecast_attributes (old issue #11)
# ---------------------------------------------------------------------------


def _forecast_issue_id(entry: MockConfigEntry) -> str:
    return f"forecast_attributes_{entry.entry_id}"


async def test_forecast_attributes_issue_created_when_automation_reads_forecast_hourly(
    hass,
):
    """A referencing automation whose raw_config mentions forecast_hourly triggers the issue."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)

    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create(
        "weather", DOMAIN, f"{coord.location}_weather".lower(), config_entry=entry
    )

    hass.config.components.add("automation")
    hass.data["automation"] = _FakeEntityComponent(
        {
            "automation.storm_watch": _FakeAutomationEntity(
                {
                    "alias": "Storm watch",
                    "trigger": [
                        {"platform": "state", "entity_id": "weather.napier_weather"}
                    ],
                    "action": [
                        {
                            "service": "notify.notify",
                            "data_template": {
                                "message": "{{ state_attr('weather.napier_weather', "
                                "'forecast_hourly') }}"
                            },
                        }
                    ],
                }
            )
        }
    )

    with patch(_AUTOMATIONS_PATCH, return_value=["automation.storm_watch"]):
        await async_check_removed_forecast_attributes(hass, entry, coord)

    issue = ir.async_get(hass).async_get_issue(DOMAIN, _forecast_issue_id(entry))
    assert issue is not None
    assert "automation.storm_watch" in issue.translation_placeholders["references"]
    assert issue.severity == ir.IssueSeverity.WARNING
    assert issue.is_fixable is False


async def test_forecast_attributes_issue_created_for_forecast_daily_in_script(hass):
    """A referencing script whose raw_config mentions forecast_daily also triggers the issue."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)

    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create(
        "weather", DOMAIN, f"{coord.location}_weather".lower(), config_entry=entry
    )

    hass.config.components.add("script")
    hass.data["script"] = _FakeEntityComponent(
        {
            "script.log_forecast": _FakeAutomationEntity(
                {
                    "alias": "Log forecast",
                    "sequence": [
                        {
                            "service": "logbook.log",
                            "data_template": {
                                "message": "{{ state_attr('weather.napier_weather', "
                                "'forecast_daily') }}"
                            },
                        }
                    ],
                }
            )
        }
    )

    with patch(_SCRIPTS_PATCH, return_value=["script.log_forecast"]):
        await async_check_removed_forecast_attributes(hass, entry, coord)

    issue = ir.async_get(hass).async_get_issue(DOMAIN, _forecast_issue_id(entry))
    assert issue is not None
    assert "script.log_forecast" in issue.translation_placeholders["references"]


async def test_self_corrected_user_forecast_attributes_without_forecast_string_stays_silent(
    hass,
):
    """A referencing automation whose raw_config never mentions forecast_hourly/forecast_daily stays silent and clears a pre-existing issue."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)

    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create(
        "weather", DOMAIN, f"{coord.location}_weather".lower(), config_entry=entry
    )

    issue_id = _forecast_issue_id(entry)
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="forecast_attributes_removed",
    )
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None

    hass.config.components.add("automation")
    hass.data["automation"] = _FakeEntityComponent(
        {
            "automation.storm_watch": _FakeAutomationEntity(
                {
                    "alias": "Storm watch",
                    "trigger": [],
                    "action": [{"service": "notify.notify"}],
                }
            )
        }
    )

    with patch(_AUTOMATIONS_PATCH, return_value=["automation.storm_watch"]):
        await async_check_removed_forecast_attributes(hass, entry, coord)

    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_forecast_attributes_raw_config_access_raising_is_swallowed(hass):
    """A raw_config lookup that raises degrades to no detection for that reference — no issue, no crash."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)

    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create(
        "weather", DOMAIN, f"{coord.location}_weather".lower(), config_entry=entry
    )

    class _BrokenComponent:
        def get_entity(self, entity_id):
            raise AttributeError("boom")

    hass.config.components.add("automation")
    hass.data["automation"] = _BrokenComponent()

    with patch(_AUTOMATIONS_PATCH, return_value=["automation.storm_watch"]):
        # Must not raise.
        await async_check_removed_forecast_attributes(hass, entry, coord)

    assert ir.async_get(hass).async_get_issue(DOMAIN, _forecast_issue_id(entry)) is None


async def test_forecast_attributes_none_raw_config_is_treated_as_no_detection(hass):
    """A referencing entity with raw_config=None (not yet loaded) is skipped, not treated as a match."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)

    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create(
        "weather", DOMAIN, f"{coord.location}_weather".lower(), config_entry=entry
    )

    hass.config.components.add("automation")
    hass.data["automation"] = _FakeEntityComponent(
        {"automation.storm_watch": _FakeAutomationEntity(None)}
    )

    with patch(_AUTOMATIONS_PATCH, return_value=["automation.storm_watch"]):
        await async_check_removed_forecast_attributes(hass, entry, coord)

    assert ir.async_get(hass).async_get_issue(DOMAIN, _forecast_issue_id(entry)) is None


async def test_forecast_attributes_missing_component_key_is_swallowed(hass):
    """A reference whose owning component was never registered in hass.data degrades to no detection."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)

    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create(
        "weather", DOMAIN, f"{coord.location}_weather".lower(), config_entry=entry
    )

    hass.config.components.add("automation")
    # No hass.data["automation"] entry at all.
    with patch(_AUTOMATIONS_PATCH, return_value=["automation.storm_watch"]):
        # Must not raise.
        await async_check_removed_forecast_attributes(hass, entry, coord)

    assert ir.async_get(hass).async_get_issue(DOMAIN, _forecast_issue_id(entry)) is None


async def test_forecast_attributes_no_weather_entity_registered_stays_silent(hass):
    """When the entry's weather entity has no registry row yet, the check is a safe no-op."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)

    await async_check_removed_forecast_attributes(hass, entry, coord)

    assert ir.async_get(hass).async_get_issue(DOMAIN, _forecast_issue_id(entry)) is None


async def test_forecast_attributes_exception_inside_check_does_not_propagate(hass):
    """A failure anywhere inside the forecast-attributes check is swallowed, never raised out of setup."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)

    with patch(
        "custom_components.metservice_weather.deprecation.er.async_get",
        side_effect=RuntimeError("boom"),
    ):
        # Must not raise.
        await async_check_removed_forecast_attributes(hass, entry, coord)


# ---------------------------------------------------------------------------
# Detector 4: async_check_marine_device_move (marine sensors moved off the
# location device onto their own marine device)
# ---------------------------------------------------------------------------

_TIDE_URL = (
    "https://www.metservice.com/publicData/webdata/marine/regions/"
    "kapiti-wellington/tides/locations/wellington"
)


def _marine_issue_id(entry: MockConfigEntry) -> str:
    return f"marine_device_move_{entry.entry_id}"


def _make_location_device(
    hass, entry: MockConfigEntry, coord: WeatherUpdateCoordinator
):
    """Create the location device row, mirroring MetServiceEntity's DeviceInfo."""
    return dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, coord.location)},
        name=coord.location_name,
    )


async def test_marine_device_move_issue_created_when_referenced_via_marine_entity_id(
    hass,
):
    """A device automation whose raw_config mentions a registered marine entity_id is flagged."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass, tide_url=_TIDE_URL)

    device = _make_location_device(hass, entry, coord)
    ent_reg = er.async_get(hass)
    tides_high = ent_reg.async_get_or_create(
        "sensor", DOMAIN, f"{coord.location}_tides_high".lower(), config_entry=entry
    )

    hass.config.components.add("automation")
    hass.data["automation"] = _FakeEntityComponent(
        {
            "automation.tide_alert": _FakeAutomationEntity(
                {
                    "alias": "Tide alert",
                    "trigger": [
                        {
                            "platform": "device",
                            "device_id": device.id,
                            "domain": "sensor",
                            "entity_id": tides_high.entity_id,
                            "type": "value",
                        }
                    ],
                }
            )
        }
    )

    with (
        patch(_AUTOMATIONS_DEVICE_PATCH, return_value=["automation.tide_alert"]),
        patch(_SCRIPTS_DEVICE_PATCH, return_value=[]),
    ):
        await async_check_marine_device_move(hass, entry, coord)

    issue = ir.async_get(hass).async_get_issue(DOMAIN, _marine_issue_id(entry))
    assert issue is not None
    assert "automation.tide_alert" in issue.translation_placeholders["references"]
    assert issue.translation_placeholders["marine_device"] == "Kapiti and Wellington"
    assert issue.severity == ir.IssueSeverity.WARNING
    assert issue.is_fixable is False


async def test_marine_device_move_issue_created_via_script_and_token_only_match(hass):
    """A script device-reference is also checked, and a marine token alone (no entity_id) still flags."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass, boating_url=_TIDE_URL.replace("tides", "boating"))

    device = _make_location_device(hass, entry, coord)

    hass.config.components.add("script")
    hass.data["script"] = _FakeEntityComponent(
        {
            "script.check_boating": _FakeAutomationEntity(
                {
                    "alias": "Check boating",
                    "sequence": [
                        {
                            "condition": "device",
                            "device_id": device.id,
                            "domain": "sensor",
                            "type": "boating_status",
                        }
                    ],
                }
            )
        }
    )

    with (
        patch(_AUTOMATIONS_DEVICE_PATCH, return_value=[]),
        patch(_SCRIPTS_DEVICE_PATCH, return_value=["script.check_boating"]),
    ):
        await async_check_marine_device_move(hass, entry, coord)

    issue = ir.async_get(hass).async_get_issue(DOMAIN, _marine_issue_id(entry))
    assert issue is not None
    assert "script.check_boating" in issue.translation_placeholders["references"]


async def test_marine_device_move_silent_when_device_automation_has_no_marine_content(
    hass,
):
    """A device automation that references the location device for unrelated content stays silent."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass, tide_url=_TIDE_URL)

    device = _make_location_device(hass, entry, coord)

    hass.config.components.add("automation")
    hass.data["automation"] = _FakeEntityComponent(
        {
            "automation.temp_alert": _FakeAutomationEntity(
                {
                    "alias": "Temperature alert",
                    "trigger": [
                        {
                            "platform": "device",
                            "device_id": device.id,
                            "domain": "sensor",
                            "entity_id": "sensor.napier_temperature",
                            "type": "value",
                        }
                    ],
                }
            )
        }
    )

    with (
        patch(_AUTOMATIONS_DEVICE_PATCH, return_value=["automation.temp_alert"]),
        patch(_SCRIPTS_DEVICE_PATCH, return_value=[]),
    ):
        await async_check_marine_device_move(hass, entry, coord)

    assert ir.async_get(hass).async_get_issue(DOMAIN, _marine_issue_id(entry)) is None


async def test_marine_device_move_silent_when_no_marine_configured(hass):
    """No marine service configured -> stays silent even if a device automation looks marine-related."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)  # tide_url/boating_url/surf_url all default ""
    assert not (coord.enable_tides or coord.enable_boating or coord.enable_surf)

    device = _make_location_device(hass, entry, coord)

    hass.config.components.add("automation")
    hass.data["automation"] = _FakeEntityComponent(
        {
            "automation.stale_tide_trigger": _FakeAutomationEntity(
                {
                    "alias": "Stale tide trigger",
                    "trigger": [
                        {
                            "platform": "device",
                            "device_id": device.id,
                            "domain": "sensor",
                            "entity_id": f"{coord.location}_tides_high".lower(),
                            "type": "tides_high",
                        }
                    ],
                }
            )
        }
    )

    with patch(_AUTOMATIONS_DEVICE_PATCH) as mock_automations:
        await async_check_marine_device_move(hass, entry, coord)
        # No marine service configured -> short-circuits before ever
        # looking up the device or its referencing automations.
        mock_automations.assert_not_called()

    assert ir.async_get(hass).async_get_issue(DOMAIN, _marine_issue_id(entry)) is None


async def test_marine_device_move_silent_when_location_device_missing(hass):
    """No location device row yet (e.g. entities not added) is a safe, self-clearing no-op."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass, tide_url=_TIDE_URL)

    issue_id = _marine_issue_id(entry)
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="marine_device_move",
    )

    with patch(_AUTOMATIONS_DEVICE_PATCH) as mock_automations:
        await async_check_marine_device_move(hass, entry, coord)
        mock_automations.assert_not_called()

    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_marine_device_move_issue_cleared_when_references_vanish(hass):
    """A pre-existing issue is deleted once nothing references the location device anymore."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass, tide_url=_TIDE_URL)

    _make_location_device(hass, entry, coord)

    issue_id = _marine_issue_id(entry)
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="marine_device_move",
    )
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None

    hass.config.components.add("automation")
    hass.config.components.add("script")
    with (
        patch(_AUTOMATIONS_DEVICE_PATCH, return_value=[]),
        patch(_SCRIPTS_DEVICE_PATCH, return_value=[]),
    ):
        await async_check_marine_device_move(hass, entry, coord)

    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_marine_device_move_exception_inside_check_does_not_propagate(hass):
    """A failure anywhere inside the marine-device-move check is swallowed, never raised out of setup."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass, tide_url=_TIDE_URL)

    with patch(
        "custom_components.metservice_weather.deprecation.dr.async_get",
        side_effect=RuntimeError("boom"),
    ):
        # Must not raise.
        await async_check_marine_device_move(hass, entry, coord)
