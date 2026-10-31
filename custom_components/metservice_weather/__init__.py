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
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from .coordinator import WeatherUpdateCoordinator, WeatherUpdateCoordinatorConfig
from .entity import async_register_location_device
from .const import (
    DOMAIN,
    LOCATION_PATH_RE,
    PUBLIC_URL,
    PUBLIC_WARNINGS_URL,
    API_METRIC,
)

PLATFORMS: Final = [Platform.WEATHER, Platform.SENSOR]

type MetServiceConfigEntry = ConfigEntry[WeatherUpdateCoordinator]

_LOGGER = logging.getLogger(__name__)

_CONF_API = "api"

# Keys v0.9 and pre-v0.9.15 entries stored that nothing reads any more.
_LEGACY_DATA_KEYS: Final = (
    "api_key",
    "mobile_api_key",
    "enable_tides",
    "tide_region_url",
    "boating_region",
)


def _is_location_path(location: object) -> bool:
    """Return True when location is a public-API location path."""
    return (
        isinstance(location, str) and LOCATION_PATH_RE.fullmatch(location) is not None
    )


_LEGACY_ENTRY_LEARN_MORE_URL = "https://github.com/nagelm/metservice-weather/releases"


def _check_legacy_entry(hass: HomeAssistant, entry: MetServiceConfigEntry) -> None:
    """Create or clear a repair issue for a pre-v1.0.0 entry."""
    issue_id = f"legacy_entry_{entry.entry_id}"
    try:
        api = entry.data.get(_CONF_API)
        location = entry.data.get(CONF_LOCATION)
        if api == "mobile":
            reason = "the private mobile API, which was removed in v1.0.0"
        elif not _is_location_path(location):
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
    """Re-key entities registered by v0.9.x onto the current unique_id format."""
    try:
        location = entry.data.get(CONF_LOCATION)
        if not _is_location_path(location):
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

    weathercoordinator = WeatherUpdateCoordinator(hass, config, entry)
    await weathercoordinator.async_config_entry_first_refresh()

    entry.runtime_data = weathercoordinator

    weathercoordinator.location_device_id = async_register_location_device(
        hass, entry, weathercoordinator
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _remove_empty_devices(hass, entry)
    return True


@callback
def _remove_empty_devices(hass: HomeAssistant, entry: MetServiceConfigEntry) -> None:
    """Detach this entry from its devices that no longer have any entities.

    Left behind when marine data is turned off or Reconfigure changes the location.
    """
    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)
    for device in dr.async_entries_for_config_entry(dev_reg, entry.entry_id):
        if not er.async_entries_for_device(
            ent_reg, device.id, include_disabled_entities=True
        ):
            _LOGGER.debug("Removing device %s, which has no entities left", device.name)
            dev_reg.async_update_device(
                device.id, remove_config_entry_id=entry.entry_id
            )


async def async_unload_entry(hass: HomeAssistant, entry: MetServiceConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


def _reenable_warning_details(
    hass: HomeAssistant, entry: MetServiceConfigEntry
) -> None:
    """Re-enable a Warning details row that releases before 2026.9.0 shipped disabled."""
    ent_reg = er.async_get(hass)
    entity_id = ent_reg.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.data[CONF_LOCATION]}_warning_details".lower()
    )
    reg_entry = ent_reg.async_get(entity_id) if entity_id else None
    if (
        reg_entry is not None
        and reg_entry.disabled_by == er.RegistryEntryDisabler.INTEGRATION
    ):
        ent_reg.async_update_entity(reg_entry.entity_id, disabled_by=None)


async def async_migrate_entry(
    hass: HomeAssistant, config_entry: MetServiceConfigEntry
) -> bool:
    """Migrate an older config entry to the current version, once.

    1.1 -> 1.2: re-key v0.9 entities, re-enable Warning details, drop legacy keys.
    An entry without a public location path (a v0.9 mobile entry) stays at 1.1
    until Reconfigure gives it one.
    """
    _LOGGER.debug(
        "Migrating config entry from version %s.%s",
        config_entry.version,
        config_entry.minor_version,
    )
    if config_entry.version > 1:
        return False
    if config_entry.minor_version < 2 and _is_location_path(
        config_entry.data.get(CONF_LOCATION)
    ):
        await _async_migrate_legacy_unique_ids(hass, config_entry)
        _reenable_warning_details(hass, config_entry)
        data = {
            key: value
            for key, value in config_entry.data.items()
            if key not in _LEGACY_DATA_KEYS
        }
        hass.config_entries.async_update_entry(config_entry, data=data, minor_version=2)
    return True
