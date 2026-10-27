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
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from .coordinator import WeatherUpdateCoordinator, WeatherUpdateCoordinatorConfig
from .entity import async_register_location_device
from .const import (
    DOMAIN,
    LOCATIONS,
    PUBLIC_URL,
    PUBLIC_WARNINGS_URL,
    API_METRIC,
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


async def _async_migrate_legacy_unique_ids(
    hass: HomeAssistant, entry: MetServiceConfigEntry
) -> None:
    """Re-key entities registered by v0.9.x onto the current unique_id format.

    Up to v0.9.x (including ciejer/metservice-weather v0.9) every entity's
    unique_id was "<typed name>,<key>"; v1.0.0 changed it to
    "<location path>_<key>" with no migration, so the platforms' stale-entity
    cleanup deleted every v0.9 entity on upgrade and recreated it on a new
    entity ID, losing history and breaking references. Re-keying the old
    registry entries in place keeps their entity IDs, history and
    customisations. Runs before the platforms are set up so the platforms
    find the re-keyed entries.

    Matches on the key after the last comma rather than on the typed name,
    so an entry that had to be reconfigured (mobile API, old location path)
    keeps its entities even if the name was changed. Current unique_ids and
    pre-v0.8 "<location path>,weather" rows start with "/" and are never
    matched. A target unique_id that is already registered (someone who
    crossed v1.0.0 earlier and now has both) is left alone. Wrapped in a
    broad except so it can never block setup.
    """
    try:
        location = entry.data.get(CONF_LOCATION)
        if location not in _VALID_LOCATION_VALUES:
            return
        new_prefix = f"{location}_".lower()
        ent_reg = er.async_get(hass)

        @callback
        def _rekey(reg_entry: er.RegistryEntry) -> dict[str, str] | None:
            unique_id = reg_entry.unique_id
            if "," not in unique_id or unique_id.startswith("/"):
                return None
            new_unique_id = new_prefix + unique_id.rsplit(",", 1)[1].lower()
            if ent_reg.async_get_entity_id(reg_entry.domain, DOMAIN, new_unique_id):
                return None
            _LOGGER.info(
                "Migrating %s from v0.9 unique_id %r to %r",
                reg_entry.entity_id,
                reg_entry.unique_id,
                new_unique_id,
            )
            return {"new_unique_id": new_unique_id}

        await er.async_migrate_entries(hass, entry.entry_id, _rekey)
    except Exception:
        _LOGGER.warning(
            "v0.9 unique_id migration failed; v0.9 entities may be recreated",
            exc_info=True,
        )


async def async_setup_entry(hass: HomeAssistant, entry: MetServiceConfigEntry):
    """Set up the MetService Weather component."""
    _check_legacy_entry(hass, entry)
    await _async_migrate_legacy_unique_ids(hass, entry)

    config = WeatherUpdateCoordinatorConfig(
        location=entry.data[CONF_LOCATION],
        location_name=entry.data[CONF_NAME],
        tide_url=entry.data.get("tide_url", ""),
        boating_url=entry.data.get("boating_url", ""),
        surf_url=entry.data.get("surf_url", ""),
        unit_system=API_METRIC,
        api_url=PUBLIC_URL,
        warnings_url=PUBLIC_WARNINGS_URL,
    )

    weathercoordinator = WeatherUpdateCoordinator(hass, config)
    await weathercoordinator.async_config_entry_first_refresh()

    entry.runtime_data = weathercoordinator

    # Registered before the platforms are forwarded: marine entities link
    # to this device with via_device_id, which needs the parent's registry
    # id to already exist (see entity.async_register_location_device).
    weathercoordinator.location_device_id = async_register_location_device(
        hass, entry, weathercoordinator
    )

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
