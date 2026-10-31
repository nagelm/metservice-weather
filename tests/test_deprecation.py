"""Tests for the deprecated-entity repair issue check (deprecation.py)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.util import slugify

from custom_components.metservice_weather.const import DOMAIN
from custom_components.metservice_weather.coordinator import (
    WeatherUpdateCoordinator,
)
from custom_components.metservice_weather.coordinator_types import MetServicePublicData
from custom_components.metservice_weather.deprecation import (
    DEPRECATED_SENSOR_REPLACEMENTS,
    _GENERIC_REMOVED_REPLACEMENT_FALLBACK,
    _REPLACEMENT_DISPLAY_NAMES,
    _format_references,
    async_check_deprecated_entities,
    async_check_marine_device_move,
    async_check_removed_entity,
    async_check_removed_forecast_attributes,
)
from custom_components.metservice_weather.weather_current_conditions_sensors import (
    current_condition_sensor_descriptions_public,
)
from tests.conftest import make_coordinator

LOCATION = "/towns-cities/regions/hawkes-bay/locations/napier"

_AUTOMATIONS_PATCH = (
    "custom_components.metservice_weather.deprecation.automations_with_entity"
)
_SCRIPTS_PATCH = "custom_components.metservice_weather.deprecation.scripts_with_entity"
_AUTOMATIONS_DEVICE_PATCH = (
    "custom_components.metservice_weather.deprecation.automations_with_device"
)
_SCRIPTS_DEVICE_PATCH = (
    "custom_components.metservice_weather.deprecation.scripts_with_device"
)


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


_make_coordinator = make_coordinator


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


def test_replacement_display_names_match_en_json():
    """Every replacement's repair name matches the name Home Assistant shows."""
    en = Path(__file__).parents[1] / (
        "custom_components/metservice_weather/translations/en.json"
    )
    names = json.loads(en.read_text(encoding="utf-8"))["entity"]["sensor"]
    translation_keys = {
        d.key: d.translation_key for d in current_condition_sensor_descriptions_public
    }
    for key in set(DEPRECATED_SENSOR_REPLACEMENTS.values()):
        assert _REPLACEMENT_DISPLAY_NAMES[key] == names[translation_keys[key]]["name"]


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


async def test_exception_inside_cleanup_does_not_propagate(hass):
    """A failure anywhere inside the cleanup step is swallowed, never raised out of setup."""
    entry = _make_entry()
    entry.add_to_hass(hass)

    with patch(
        "custom_components.metservice_weather.deprecation.ir.async_get",
        side_effect=RuntimeError("boom"),
    ):
        await async_check_deprecated_entities(hass, entry)


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


async def test_2026_9_upgrade_removes_referenced_deprecated_row_with_repair(hass):
    """A re-enabled, still-referenced deprecated row is removed on real setup, with a removed_entity repair naming the reference and the replacement."""
    entry = _make_entry()
    entry.add_to_hass(hass)

    ent_reg = er.async_get(hass)
    unique_id = f"{LOCATION}_uvIndex".lower()
    stale = ent_reg.async_get_or_create("sensor", DOMAIN, unique_id, config_entry=entry)
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

    assert ent_reg.async_get(entity_id) is None
    assert ent_reg.async_get_entity_id("sensor", DOMAIN, unique_id) is None

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
    assert issue.is_persistent is True
    assert issue.data == {"entity_id": reg_entry.entity_id}


async def test_removed_weather_warnings_replacement_names_warning_details(hass):
    """weather_warnings removal points at Warning details for the full text."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)

    ent_reg = er.async_get(hass)
    reg_entry = ent_reg.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{coord.location}_weather_warnings".lower(),
        config_entry=entry,
    )

    hass.config.components.add("automation")
    hass.config.components.add("script")
    with (
        patch(_AUTOMATIONS_PATCH, return_value=["automation.storm_alert"]),
        patch(_SCRIPTS_PATCH, return_value=[]),
    ):
        await async_check_removed_entity(hass, entry, coord, reg_entry)

    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, _removed_issue_id(entry, reg_entry.entity_id)
    )
    assert issue is not None
    replacement = issue.translation_placeholders["replacement"]
    assert replacement.startswith("Warnings")
    assert "Warning details" in replacement
    assert "active_warnings" in replacement


async def test_removed_entity_unknown_key_uses_generic_replacement_fallback(hass):
    """A removed entity whose unique_id key isn't in DEPRECATED_SENSOR_REPLACEMENTS gets generic wording."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)

    ent_reg = er.async_get(hass)
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
        await async_check_deprecated_entities(hass, entry)

    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_removed_entity_issue_left_untouched_while_still_referenced(hass):
    """The sweep in async_check_deprecated_entities leaves a removed_entity issue alone while still referenced."""
    entry = _make_entry()
    entry.add_to_hass(hass)

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
        await async_check_deprecated_entities(hass, entry)

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
        await async_check_removed_entity(hass, entry, coord, reg_entry)

    issue_id = _removed_issue_id(entry, reg_entry.entity_id)
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


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
    with patch(_AUTOMATIONS_PATCH, return_value=["automation.storm_watch"]):
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
        await async_check_removed_forecast_attributes(hass, entry, coord)


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
        await async_check_marine_device_move(hass, entry, coord)
