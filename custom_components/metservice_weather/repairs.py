"""Repair flows for MetService Weather.

Only one fixable repair exists today: entity_id_reclaim (see deprecation.py's
async_check_entity_id_reclaim). It is a single confirm-and-rename step —
everything the flow needs (the current, suffixed entity_id and the free
canonical entity_id it should become) travels in the issue's ``data``
mapping, which the repairs flow manager hands to ``async_create_fix_flow``
and then stamps onto the created flow as ``flow.data`` again. This module
reads it straight from the ``data`` argument instead, since that value is
available before the flow manager finishes wiring the instance up.
"""

from __future__ import annotations

from typing import Any

from homeassistant import data_entry_flow
from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er


class EntityIdReclaimRepairFlow(RepairsFlow):
    """Single-step confirm flow: rename a suffixed entity_id onto its now-free canonical id."""

    def __init__(self, current_entity_id: str, new_entity_id: str) -> None:
        """Capture the rename this flow performs on confirm."""
        self._current_entity_id = current_entity_id
        self._new_entity_id = new_entity_id

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        """Handle the first (and only) step of the flow."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        """Show a confirmation form, then perform the rename on submit.

        Renaming via the registry API (rather than asking the user to do it
        from the UI) is safe here specifically because the detector that
        raised this issue already established nothing references the
        current entity_id — see async_check_entity_id_reclaim's docstring.
        A registry row that has since disappeared (e.g. the location or the
        sensor was removed between the issue being raised and the user
        clicking Fix) is a silent no-op rather than an error.
        """
        if user_input is not None:
            ent_reg = er.async_get(self.hass)
            if ent_reg.async_get(self._current_entity_id) is not None:
                ent_reg.async_update_entity(
                    self._current_entity_id, new_entity_id=self._new_entity_id
                )
            return self.async_create_entry(data={})

        return self.async_show_form(
            step_id="confirm",
            description_placeholders={
                "current_entity_id": self._current_entity_id,
                "new_entity_id": self._new_entity_id,
            },
        )


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, Any] | None,
) -> RepairsFlow:
    """Create the fix flow for a fixable MetService Weather repair issue.

    entity_id_reclaim is the only fixable issue type this integration
    raises (see deprecation.py), so issue_id itself doesn't need to be
    inspected — the issue's stored data is enough to build the flow.
    """
    data = data or {}
    return EntityIdReclaimRepairFlow(
        current_entity_id=data["current_entity_id"],
        new_entity_id=data["new_entity_id"],
    )
