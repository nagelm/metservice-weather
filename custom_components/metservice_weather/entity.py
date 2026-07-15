"""Base entity for MetService weather integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import WeatherUpdateCoordinator


class MetServiceEntity(CoordinatorEntity[WeatherUpdateCoordinator]):
    """Base class providing shared DeviceInfo for all MetService entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: WeatherUpdateCoordinator) -> None:
        """Attach the shared MetService device info to the entity."""
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.location)},
            name=coordinator.location_name,
            manufacturer=MANUFACTURER,
            model="MetService Public API",
            configuration_url="https://www.metservice.com",
        )
