"""Repair flows for MetService Weather."""

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
        """Show a confirmation form, then perform the renames on submit."""
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
    """Create the fix flow for a fixable MetService Weather repair issue."""
    data = data or {}
    return EntityIdReclaimRepairFlow(renames=list(data.get("renames") or []))
