"""Diagnostics support for MetService New Zealand Weather."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import MetServiceConfigEntry

# Keys v0.9 mobile-API entries stored; they can survive a later Reconfigure.
TO_REDACT = {"api_key", "mobile_api_key"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: MetServiceConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    return {
        "config_entry_data": async_redact_data(dict(entry.data), TO_REDACT),
        "coordinator_data": asdict(coordinator.data) if coordinator.data else None,
    }
