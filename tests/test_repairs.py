"""Tests for the entity-ID reclaim repair — Part 3 of the v2026.9.0 deprecated-sensor removal.

Covers deprecation.py's async_check_entity_id_reclaim detector (exercised
through its public entry point, async_check_deprecated_entities, for
realism — this is exactly how sensor.py's async_setup_entry invokes it)
and repairs.py's EntityIdReclaimRepairFlow fix flow, driven through the
real HA repairs flow manager so the issue-deletion side effect
(RepairsFlowManager.async_finish_flow) is exercised too, not just asserted
by hand.
"""

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
    WeatherUpdateCoordinatorConfig,
)
from custom_components.metservice_weather.coordinator_types import MetServicePublicData
from custom_components.metservice_weather.deprecation import (
    async_check_deprecated_entities,
)
from custom_components.metservice_weather.repairs import EntityIdReclaimRepairFlow

LOCATION = "/towns-cities/regions/hawkes-bay/locations/napier"

_AUTOMATIONS_PATCH = (
    "custom_components.metservice_weather.deprecation.automations_with_entity"
)
_SCRIPTS_PATCH = "custom_components.metservice_weather.deprecation.scripts_with_entity"

# uv_risk is used as the representative replacement key throughout: its
# description.name is "UV index", so slugify("Napier UV index") ->
# "napier_uv_index" is the canonical entity_id every test below targets.
_RECLAIM_KEY = "uv_risk"
_RECLAIM_SENSOR_NAME = "UV index"
_CANONICAL_ENTITY_ID = "sensor.napier_uv_index"


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
    suggested_object_id: str = "napier_uv_risk_2",
    with_device: bool = True,
) -> er.RegistryEntry:
    """Create a suffixed registry row for `key`, simulating the v2026.7.1 collision.

    with_device=False omits device_id, for the "no device" self-clear test.
    """
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


def _fixable_issue_id(entry: MockConfigEntry, key: str = _RECLAIM_KEY) -> str:
    return f"entity_id_reclaim_{entry.entry_id}_{key}"


def _referenced_issue_id(entry: MockConfigEntry, key: str = _RECLAIM_KEY) -> str:
    return f"entity_id_reclaim_referenced_{entry.entry_id}_{key}"


async def _async_setup_full(
    hass, entry: MockConfigEntry, data: MetServicePublicData
) -> WeatherUpdateCoordinator:
    """Run the real config-entry setup (coordinator + weather + sensor platforms).

    Only the fix-flow-driving test needs this (rather than calling
    async_check_deprecated_entities directly, like the detection-only tests
    above): HA's repairs flow manager only looks up a fix-flow platform for
    a domain that's actually a loaded top-level component
    (LazyIntegrationPlatforms.async_get_platform gates on
    hass.config.top_level_components) — calling the detector function
    directly never makes "metservice_weather" a loaded component, so the
    flow manager would silently fall back to repairs' generic
    ConfirmRepairFlow instead of finding repairs.py.
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
# Detection: fixable branch (unreferenced -> fixable issue)
# ---------------------------------------------------------------------------


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
    assert issue.translation_placeholders["current_entity_id"] == reg_entry.entity_id
    assert issue.translation_placeholders["new_entity_id"] == _CANONICAL_ENTITY_ID
    assert issue.translation_placeholders["sensor_name"] == _RECLAIM_SENSOR_NAME
    assert issue.data == {
        "current_entity_id": reg_entry.entity_id,
        "new_entity_id": _CANONICAL_ENTITY_ID,
    }
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, _referenced_issue_id(entry)) is None
    )


async def test_fixable_issue_fix_flow_renames_entity_and_clears_issue(hass):
    """Driving the fix flow through the real repairs flow manager renames the entity_id and clears the issue.

    Uses _async_setup_full (real config-entry setup) rather than calling
    async_check_deprecated_entities directly — see that helper's docstring
    for why the flow manager needs the component genuinely loaded.
    """
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
    # RepairsFlowManager.async_finish_flow deletes the issue on CREATE_ENTRY.
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


# ---------------------------------------------------------------------------
# Detection: referenced branch (referenced -> non-fixable issue, no rename)
# ---------------------------------------------------------------------------


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
    assert "automation.uv_check" in issue.translation_placeholders["references"]
    assert issue.translation_placeholders["current_entity_id"] == reg_entry.entity_id
    assert issue.translation_placeholders["new_entity_id"] == _CANONICAL_ENTITY_ID
    assert issue.translation_placeholders["sensor_name"] == _RECLAIM_SENSOR_NAME
    assert ir.async_get(hass).async_get_issue(DOMAIN, _fixable_issue_id(entry)) is None

    ent_reg = er.async_get(hass)
    assert ent_reg.async_get(reg_entry.entity_id) is not None
    assert ent_reg.async_get(_CANONICAL_ENTITY_ID) is None


# ---------------------------------------------------------------------------
# Detection: no-op branches (self-clearing)
# ---------------------------------------------------------------------------


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
        # Must not raise.
        await async_check_deprecated_entities(hass, entry, coord)

    assert (
        ir.async_get(hass).async_get_issue(
            DOMAIN, f"entity_id_reclaim_{entry.entry_id}_ghost_replacement"
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
        # Must not raise, even though every key "resolves" to a
        # non-existent entity_id.
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
        # Must not raise.
        await async_check_deprecated_entities(hass, entry, coord)


# ---------------------------------------------------------------------------
# Self-clear: an existing issue for a key whose row has since become
# canonical (by whatever means) is deleted on the next run.
# ---------------------------------------------------------------------------


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
            "current_entity_id": reg_entry.entity_id,
            "new_entity_id": _CANONICAL_ENTITY_ID,
        },
    )
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None

    # The row is renamed onto the canonical id by some other means (e.g.
    # the user did it manually from the UI before ever seeing the repair).
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


# ---------------------------------------------------------------------------
# repairs.py: EntityIdReclaimRepairFlow direct-instantiation edge case
# ---------------------------------------------------------------------------


async def test_fix_flow_is_noop_when_row_already_gone(hass):
    """If the entity_id disappears between the issue being raised and Fix being clicked, the flow no-ops instead of erroring."""
    flow = EntityIdReclaimRepairFlow(
        current_entity_id="sensor.napier_uv_risk_2",
        new_entity_id=_CANONICAL_ENTITY_ID,
    )
    flow.hass = hass

    result = await flow.async_step_confirm(user_input={})

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert er.async_get(hass).async_get(_CANONICAL_ENTITY_ID) is None
