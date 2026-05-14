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
from .coordinator import WeatherUpdateCoordinator, WeatherUpdateCoordinatorConfig
from .const import PUBLIC_URL, PUBLIC_WARNINGS_URL, API_METRIC, API_URL_METRIC

PLATFORMS: Final = [Platform.WEATHER, Platform.SENSOR]

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry[WeatherUpdateCoordinator]):
    """Set up the MetService Weather component."""
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

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    entry.runtime_data = weathercoordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry[WeatherUpdateCoordinator]) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old config entry to current version."""
    _LOGGER.debug("Migrating config entry from version %s", config_entry.version)
    if config_entry.version > 1:
        return False
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update listener."""
    await hass.config_entries.async_reload(entry.entry_id)
