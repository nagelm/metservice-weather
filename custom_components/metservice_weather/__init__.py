"""The MetService Weather component."""

from __future__ import annotations

import logging
from typing import Final
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_NAME,
    CONF_LOCATION,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from .coordinator import WeatherUpdateCoordinator, WeatherUpdateCoordinatorConfig
from .const import (
    DOMAIN,
    LOCATIONS,
    PUBLIC_URL,
    PUBLIC_WARNINGS_URL,
    API_METRIC,
    API_URL_METRIC,
)

PLATFORMS: Final = [Platform.WEATHER, Platform.SENSOR]

type MetServiceConfigEntry = ConfigEntry[WeatherUpdateCoordinator]

_LOGGER = logging.getLogger(__name__)

# The legacy config-entry key that selected MetService's private mobile
# API, removed in v1.0.0 in favour of the public API used by every current
# location.
_CONF_API = "api"

# The current, v1.0+ set of supported public location values — used to
# flag config entries left over from the mobile-API era whose stored
# location no longer matches any of today's public location paths.
_VALID_LOCATION_VALUES = {location["value"] for location in LOCATIONS}

_LEGACY_ENTRY_LEARN_MORE_URL = "https://github.com/nagelm/metservice-weather/releases"


def _check_legacy_entry(hass: HomeAssistant, entry: MetServiceConfigEntry) -> None:
    """Create or clear a repair issue for a pre-v1.0.0 entry.

    Flags entries still using the removed mobile API, or whose stored
    location no longer matches a current public location value. Runs
    before any fetching so it never depends on network access. Either
    condition means the entry predates the public-API-only, ~150-location
    current form of the integration — this only surfaces an ERROR-severity,
    non-fixable repair issue pointing the user at Reconfigure; it does NOT
    change setup behaviour otherwise (setup still proceeds, retries, or
    fails on the real data exactly as it would without this check).
    Self-clearing: cleared as soon as the entry's data validates again
    (e.g. after Reconfigure). Wrapped in a broad except so a failure in
    this best-effort check can never block setup.
    """
    issue_id = f"legacy_entry_{entry.entry_id}"
    try:
        api = entry.data.get(_CONF_API)
        location = entry.data.get(CONF_LOCATION)
        if api == "mobile":
            reason = "the private mobile API, which was removed in v1.0.0"
        elif location not in _VALID_LOCATION_VALUES:
            reason = f"an unrecognised location value ({location!r})"
        else:
            ir.async_delete_issue(hass, DOMAIN, issue_id)
            return

        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key="legacy_entry",
            learn_more_url=_LEGACY_ENTRY_LEARN_MORE_URL,
            translation_placeholders={"reason": reason},
        )
    except Exception:
        _LOGGER.debug(
            "Legacy-entry repair check failed; continuing without it", exc_info=True
        )


async def async_setup_entry(hass: HomeAssistant, entry: MetServiceConfigEntry):
    """Set up the MetService Weather component."""
    _check_legacy_entry(hass, entry)

    config = WeatherUpdateCoordinatorConfig(
        location=entry.data[CONF_LOCATION],
        location_name=entry.data[CONF_NAME],
        tide_url=entry.data.get("tide_url", ""),
        boating_url=entry.data.get("boating_url", ""),
        surf_url=entry.data.get("surf_url", ""),
        unit_system_api=API_URL_METRIC,
        unit_system=API_METRIC,
        api_url=PUBLIC_URL,
        warnings_url=PUBLIC_WARNINGS_URL,
    )

    weathercoordinator = WeatherUpdateCoordinator(hass, config)
    await weathercoordinator.async_config_entry_first_refresh()

    entry.runtime_data = weathercoordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MetServiceConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old config entry to current version."""
    _LOGGER.debug("Migrating config entry from version %s", config_entry.version)
    if config_entry.version > 1:
        return False
    return True
