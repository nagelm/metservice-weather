"""Diagnostics support for MetService New Zealand Weather."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.core import HomeAssistant

from . import MetServiceConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: MetServiceConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    return {
        "config_entry_data": dict(entry.data),
        "coordinator_data": asdict(coordinator.data) if coordinator.data else None,
    }
