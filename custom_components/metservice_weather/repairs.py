"""Repair flows for MetService Weather.

Only one fixable repair exists today: entity_id_reclaim (see deprecation.py's
async_check_entity_id_reclaim). It is a single confirm step that renames
EVERY unreferenced reclaim candidate for the config entry in one go — the
batch (a list of {current_entity_id, new_entity_id, sensor_name} dicts)
travels in the issue's ``data`` mapping, which the repairs flow manager
hands to ``async_create_fix_flow`` and then stamps onto the created flow as
``flow.data`` again. This module reads it straight from the ``data``
argument instead, since that value is available before the flow manager
finishes wiring the instance up.
"""

from __future__ import annotations

from typing import Any

from homeassistant import data_entry_flow
from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er


class EntityIdReclaimRepairFlow(RepairsFlow):
    """Single confirm step renaming every reclaim candidate onto its canonical id."""

    def __init__(self, renames: list[dict[str, str]]) -> None:
        """Capture the batch of renames this flow performs on confirm."""
        self._renames = renames

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        """Handle the first (and only) step of the flow."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        """Show a confirmation form, then perform the renames on submit.

        Renaming via the registry API (rather than asking the user to do it
        from the UI) is safe here specifically because the detector that
        raised this issue already established nothing references the
        current entity_ids — see async_check_entity_id_reclaim's docstring.
        Each rename is re-guarded at submit time: a row that has since
        disappeared, or a canonical id that has since been taken, skips
        that one rename silently rather than erroring the whole batch.
        """
        if user_input is not None:
            ent_reg = er.async_get(self.hass)
            for rename in self._renames:
                current = rename["current_entity_id"]
                new = rename["new_entity_id"]
                if (
                    ent_reg.async_get(current) is not None
                    and ent_reg.async_get(new) is None
                ):
                    ent_reg.async_update_entity(current, new_entity_id=new)
            return self.async_create_entry(data={})

        return self.async_show_form(
            step_id="confirm",
            description_placeholders={
                "count": str(len(self._renames)),
                "renames": "\n".join(
                    f"- **{r['sensor_name']}**: `{r['current_entity_id']}` → "
                    f"`{r['new_entity_id']}`"
                    for r in self._renames
                ),
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
    return EntityIdReclaimRepairFlow(renames=list(data.get("renames") or []))
