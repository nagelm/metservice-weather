"""Tests for the entity-ID reclaim repair."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant import data_entry_flow
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.metservice_weather.const import DOMAIN
from custom_components.metservice_weather.coordinator import (
    WeatherUpdateCoordinator,
)
from custom_components.metservice_weather.coordinator_types import MetServicePublicData
from custom_components.metservice_weather.deprecation import (
    async_check_deprecated_entities,
)
from custom_components.metservice_weather.repairs import EntityIdReclaimRepairFlow
from tests.conftest import make_coordinator

LOCATION = "/towns-cities/regions/hawkes-bay/locations/napier"

_AUTOMATIONS_PATCH = (
    "custom_components.metservice_weather.deprecation.automations_with_entity"
)
_SCRIPTS_PATCH = "custom_components.metservice_weather.deprecation.scripts_with_entity"

_RECLAIM_KEY = "uv_risk"
_RECLAIM_SENSOR_NAME = "UV index"
_CANONICAL_ENTITY_ID = "sensor.napier_uv_index"
_SUFFIXED_OBJECT_ID = "napier_uv_index_2"


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


def _make_location_device(
    hass, entry: MockConfigEntry, coord: WeatherUpdateCoordinator
):
    """Create the location device row, mirroring MetServiceEntity's DeviceInfo."""
    return dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, coord.location)},
        name=coord.location_name,
    )


def _make_suffixed_row(
    hass,
    entry: MockConfigEntry,
    coord: WeatherUpdateCoordinator,
    *,
    key: str = _RECLAIM_KEY,
    suggested_object_id: str = _SUFFIXED_OBJECT_ID,
    with_device: bool = True,
) -> er.RegistryEntry:
    """Create a suffixed registry row for `key`, simulating the v2026.7.1 collision."""
    ent_reg = er.async_get(hass)
    device_id = _make_location_device(hass, entry, coord).id if with_device else None
    unique_id = f"{coord.location}_{key}".lower()
    return ent_reg.async_get_or_create(
        "sensor",
        DOMAIN,
        unique_id,
        config_entry=entry,
        device_id=device_id,
        suggested_object_id=suggested_object_id,
    )


def _fixable_issue_id(entry: MockConfigEntry) -> str:
    return f"entity_id_reclaim_{entry.entry_id}"


def _referenced_issue_id(entry: MockConfigEntry) -> str:
    return f"entity_id_reclaim_referenced_{entry.entry_id}"


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


async def test_fixable_issue_raised_when_canonical_free_and_unreferenced(hass):
    """A suffixed replacement row with a free canonical id and no references gets a fixable reclaim issue."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)
    reg_entry = _make_suffixed_row(hass, entry, coord)

    hass.config.components.add("automation")
    hass.config.components.add("script")
    with (
        patch(_AUTOMATIONS_PATCH, return_value=[]),
        patch(_SCRIPTS_PATCH, return_value=[]),
    ):
        await async_check_deprecated_entities(hass, entry, coord)

    issue = ir.async_get(hass).async_get_issue(DOMAIN, _fixable_issue_id(entry))
    assert issue is not None
    assert issue.is_fixable is True
    assert issue.severity == ir.IssueSeverity.WARNING
    assert issue.translation_placeholders["count"] == "1"
    assert reg_entry.entity_id in issue.translation_placeholders["renames"]
    assert _CANONICAL_ENTITY_ID in issue.translation_placeholders["renames"]
    assert issue.data == {
        "renames": [
            {
                "current_entity_id": reg_entry.entity_id,
                "new_entity_id": _CANONICAL_ENTITY_ID,
                "sensor_name": _RECLAIM_SENSOR_NAME,
            }
        ]
    }
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, _referenced_issue_id(entry)) is None
    )


async def test_fixable_issue_fix_flow_renames_entity_and_clears_issue(hass):
    """Driving the fix flow through the real repairs flow manager renames the entity_id and clears the issue."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)
    reg_entry = _make_suffixed_row(hass, entry, coord)
    old_entity_id = reg_entry.entity_id

    hass.config.components.add("automation")
    hass.config.components.add("script")
    with (
        patch(_AUTOMATIONS_PATCH, return_value=[]),
        patch(_SCRIPTS_PATCH, return_value=[]),
    ):
        await _async_setup_full(hass, entry, MetServicePublicData())

    issue_id = _fixable_issue_id(entry)
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None

    assert await async_setup_component(hass, "repairs", {})
    await hass.async_block_till_done()
    flow_manager = hass.data["repairs"]["flow_manager"]

    result = await flow_manager.async_init(DOMAIN, data={"issue_id": issue_id})
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "confirm"

    result = await flow_manager.async_configure(result["flow_id"], user_input={})
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY

    ent_reg = er.async_get(hass)
    assert ent_reg.async_get(old_entity_id) is None
    assert ent_reg.async_get(_CANONICAL_ENTITY_ID) is not None
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_referenced_issue_raised_and_entity_id_unchanged(hass):
    """A suffixed replacement row that's still referenced gets a non-fixable issue and is never renamed."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)
    reg_entry = _make_suffixed_row(hass, entry, coord)

    hass.config.components.add("automation")
    hass.config.components.add("script")
    with (
        patch(_AUTOMATIONS_PATCH, return_value=["automation.uv_check"]),
        patch(_SCRIPTS_PATCH, return_value=[]),
    ):
        await async_check_deprecated_entities(hass, entry, coord)

    issue = ir.async_get(hass).async_get_issue(DOMAIN, _referenced_issue_id(entry))
    assert issue is not None
    assert issue.is_fixable is False
    assert issue.severity == ir.IssueSeverity.WARNING
    assert issue.translation_placeholders["count"] == "1"
    assert "automation.uv_check" in issue.translation_placeholders["details"]
    assert reg_entry.entity_id in issue.translation_placeholders["details"]
    assert _CANONICAL_ENTITY_ID in issue.translation_placeholders["details"]
    assert ir.async_get(hass).async_get_issue(DOMAIN, _fixable_issue_id(entry)) is None

    ent_reg = er.async_get(hass)
    assert ent_reg.async_get(reg_entry.entity_id) is not None
    assert ent_reg.async_get(_CANONICAL_ENTITY_ID) is None


async def test_no_issue_when_object_id_already_canonical(hass):
    """A row whose object_id already matches the canonical form raises nothing."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)
    _make_suffixed_row(hass, entry, coord, suggested_object_id="napier_uv_index")

    hass.config.components.add("automation")
    hass.config.components.add("script")
    with (
        patch(_AUTOMATIONS_PATCH, return_value=[]),
        patch(_SCRIPTS_PATCH, return_value=[]),
    ):
        await async_check_deprecated_entities(hass, entry, coord)

    assert ir.async_get(hass).async_get_issue(DOMAIN, _fixable_issue_id(entry)) is None
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, _referenced_issue_id(entry)) is None
    )


async def test_no_issue_when_canonical_id_already_taken(hass):
    """A row whose canonical id is already occupied by something else raises nothing, and is left alone."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)
    reg_entry = _make_suffixed_row(hass, entry, coord)

    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create(
        "sensor",
        "other_platform",
        "unrelated_unique_id",
        suggested_object_id="napier_uv_index",
    )
    assert ent_reg.async_get(_CANONICAL_ENTITY_ID) is not None

    hass.config.components.add("automation")
    hass.config.components.add("script")
    with (
        patch(_AUTOMATIONS_PATCH, return_value=[]),
        patch(_SCRIPTS_PATCH, return_value=[]),
    ):
        await async_check_deprecated_entities(hass, entry, coord)

    assert ir.async_get(hass).async_get_issue(DOMAIN, _fixable_issue_id(entry)) is None
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, _referenced_issue_id(entry)) is None
    )
    assert ent_reg.async_get(reg_entry.entity_id) is not None


async def test_no_issue_when_row_has_no_device(hass):
    """A replacement row with no device_id (shouldn't happen in practice) self-clears rather than crashing."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)
    _make_suffixed_row(hass, entry, coord, with_device=False)

    hass.config.components.add("automation")
    hass.config.components.add("script")
    with (
        patch(_AUTOMATIONS_PATCH, return_value=[]),
        patch(_SCRIPTS_PATCH, return_value=[]),
    ):
        await async_check_deprecated_entities(hass, entry, coord)

    assert ir.async_get(hass).async_get_issue(DOMAIN, _fixable_issue_id(entry)) is None
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, _referenced_issue_id(entry)) is None
    )


async def test_no_issue_when_replacement_row_absent(hass):
    """No registry row at all for a replacement key raises nothing (the common case for most keys, most runs)."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)

    await async_check_deprecated_entities(hass, entry, coord)

    assert ir.async_get(hass).async_get_issue(DOMAIN, _fixable_issue_id(entry)) is None
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, _referenced_issue_id(entry)) is None
    )


async def test_self_clear_when_replacement_description_missing(hass):
    """Defensive: a replacement key with no live description (shouldn't happen) self-clears rather than crashing."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)

    with patch(
        "custom_components.metservice_weather.deprecation.DEPRECATED_SENSOR_REPLACEMENTS",
        {"old_ghost_key": "ghost_replacement"},
    ):
        await async_check_deprecated_entities(hass, entry, coord)

    assert (
        ir.async_get(hass).async_get_issue(
            DOMAIN, f"entity_id_reclaim_{entry.entry_id}"
        )
        is None
    )


async def test_self_clear_when_registry_row_vanishes_between_lookups(hass):
    """Defensive: entity_id resolves but the row is gone by the time it's fetched — self-clears, not fatal."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)

    with patch.object(
        er.EntityRegistry, "async_get_entity_id", return_value="sensor.ghost"
    ):
        await async_check_deprecated_entities(hass, entry, coord)

    assert ir.async_get(hass).async_get_issue(DOMAIN, _fixable_issue_id(entry)) is None


async def test_exception_inside_reclaim_check_does_not_propagate(hass):
    """A failure anywhere inside the reclaim detector is swallowed, never raised out of setup."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)

    with patch(
        "custom_components.metservice_weather.deprecation.er.async_get",
        side_effect=RuntimeError("boom"),
    ):
        await async_check_deprecated_entities(hass, entry, coord)


async def test_self_clear_when_row_becomes_canonical(hass):
    """A pre-existing fixable issue is deleted once the row it names is already canonical on a later run."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)
    reg_entry = _make_suffixed_row(hass, entry, coord)

    issue_id = _fixable_issue_id(entry)
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key="entity_id_reclaim",
        data={
            "renames": [
                {
                    "current_entity_id": reg_entry.entity_id,
                    "new_entity_id": _CANONICAL_ENTITY_ID,
                    "sensor_name": _RECLAIM_SENSOR_NAME,
                }
            ]
        },
    )
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None

    ent_reg = er.async_get(hass)
    ent_reg.async_update_entity(reg_entry.entity_id, new_entity_id=_CANONICAL_ENTITY_ID)

    hass.config.components.add("automation")
    hass.config.components.add("script")
    with (
        patch(_AUTOMATIONS_PATCH, return_value=[]),
        patch(_SCRIPTS_PATCH, return_value=[]),
    ):
        await async_check_deprecated_entities(hass, entry, coord)

    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_fix_flow_is_noop_when_row_already_gone(hass):
    """If the entity_id disappears between the issue being raised and Fix being clicked, the flow no-ops instead of erroring."""
    flow = EntityIdReclaimRepairFlow(
        renames=[
            {
                "current_entity_id": "sensor." + _SUFFIXED_OBJECT_ID,
                "new_entity_id": _CANONICAL_ENTITY_ID,
                "sensor_name": _RECLAIM_SENSOR_NAME,
            }
        ]
    )
    flow.hass = hass

    result = await flow.async_step_confirm(user_input={})

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert er.async_get(hass).async_get(_CANONICAL_ENTITY_ID) is None


async def test_no_issue_for_old_era_non_suffixed_id(hass):
    """An id that differs from canonical without a numeric suffix is left alone."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)
    _make_suffixed_row(hass, entry, coord, suggested_object_id="outside_napier_uv_risk")

    hass.config.components.add("automation")
    hass.config.components.add("script")
    with (
        patch(_AUTOMATIONS_PATCH, return_value=[]),
        patch(_SCRIPTS_PATCH, return_value=[]),
    ):
        await async_check_deprecated_entities(hass, entry, coord)

    assert ir.async_get(hass).async_get_issue(DOMAIN, _fixable_issue_id(entry)) is None
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, _referenced_issue_id(entry)) is None
    )


async def test_multiple_candidates_consolidate_into_one_fixable_issue(hass):
    """Two suffixed rows produce ONE fixable issue whose fix renames both."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)
    uv_row = _make_suffixed_row(hass, entry, coord)
    moon_row = _make_suffixed_row(
        hass,
        entry,
        coord,
        key="moon_phase_current",
        suggested_object_id="napier_moon_phase_2",
    )

    hass.config.components.add("automation")
    hass.config.components.add("script")
    with (
        patch(_AUTOMATIONS_PATCH, return_value=[]),
        patch(_SCRIPTS_PATCH, return_value=[]),
    ):
        await _async_setup_full(hass, entry, MetServicePublicData())

    issue = ir.async_get(hass).async_get_issue(DOMAIN, _fixable_issue_id(entry))
    assert issue is not None
    assert issue.translation_placeholders["count"] == "2"
    assert uv_row.entity_id in issue.translation_placeholders["renames"]
    assert moon_row.entity_id in issue.translation_placeholders["renames"]
    assert len(issue.data["renames"]) == 2

    assert await async_setup_component(hass, "repairs", {})
    await hass.async_block_till_done()
    flow_manager = hass.data["repairs"]["flow_manager"]
    result = await flow_manager.async_init(
        DOMAIN, data={"issue_id": _fixable_issue_id(entry)}
    )
    result = await flow_manager.async_configure(result["flow_id"], user_input={})
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY

    ent_reg = er.async_get(hass)
    assert ent_reg.async_get(_CANONICAL_ENTITY_ID) is not None
    assert ent_reg.async_get("sensor.napier_moon_phase") is not None
    assert ent_reg.async_get(uv_row.entity_id) is None
    assert ent_reg.async_get(moon_row.entity_id) is None

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_mixed_referenced_and_unreferenced_split_across_both_issues(hass):
    """Referenced candidates land in the notice; unreferenced ones in the fixable batch."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)
    uv_row = _make_suffixed_row(hass, entry, coord)
    moon_row = _make_suffixed_row(
        hass,
        entry,
        coord,
        key="moon_phase_current",
        suggested_object_id="napier_moon_phase_2",
    )

    def _autos(hass_, entity_id):
        return ["automation.moon_watch"] if entity_id == moon_row.entity_id else []

    hass.config.components.add("automation")
    hass.config.components.add("script")
    with (
        patch(_AUTOMATIONS_PATCH, side_effect=_autos),
        patch(_SCRIPTS_PATCH, return_value=[]),
    ):
        await async_check_deprecated_entities(hass, entry, coord)

    reg = ir.async_get(hass)
    fixable = reg.async_get_issue(DOMAIN, _fixable_issue_id(entry))
    referenced = reg.async_get_issue(DOMAIN, _referenced_issue_id(entry))
    assert fixable is not None and referenced is not None
    assert fixable.translation_placeholders["count"] == "1"
    assert uv_row.entity_id in fixable.translation_placeholders["renames"]
    assert moon_row.entity_id not in fixable.translation_placeholders["renames"]
    assert referenced.translation_placeholders["count"] == "1"
    assert moon_row.entity_id in referenced.translation_placeholders["details"]
    assert "automation.moon_watch" in referenced.translation_placeholders["details"]


async def test_legacy_a4_per_key_issues_are_retired(hass):
    """The a4-era one-issue-per-key generation is deleted on every run."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coord = _make_coordinator(hass)

    for legacy_id in (
        f"entity_id_reclaim_{entry.entry_id}_uv_risk",
        f"entity_id_reclaim_referenced_{entry.entry_id}_warning_level",
    ):
        ir.async_create_issue(
            hass,
            DOMAIN,
            legacy_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="entity_id_reclaim_referenced",
        )

    await async_check_deprecated_entities(hass, entry, coord)

    reg = ir.async_get(hass)
    assert (
        reg.async_get_issue(DOMAIN, f"entity_id_reclaim_{entry.entry_id}_uv_risk")
        is None
    )
    assert (
        reg.async_get_issue(
            DOMAIN, f"entity_id_reclaim_referenced_{entry.entry_id}_warning_level"
        )
        is None
    )
