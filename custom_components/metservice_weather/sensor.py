"""Sensor Support for MetService weather service.

For more details about this platform, please refer to the documentation at
https://github.com/ciejer/metservice-weather.
"""
from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util.unit_system import METRIC_SYSTEM

from typing import Any

from .coordinator import WeatherUpdateCoordinator

from .const import (
    CONF_ATTRIBUTION,
    DOMAIN,
    MANUFACTURER,
)
from .weather_current_conditions_sensors import (
    current_condition_sensor_descriptions_public,
    current_condition_sensor_descriptions_mobile,
    WeatherSensorEntityDescription,
)

_LOGGER = logging.getLogger(__name__)

# Declaration of supported MetService observation/condition sensors
SENSOR_DESCRIPTIONS_PUBLIC: tuple[
    WeatherSensorEntityDescription, ...
] = current_condition_sensor_descriptions_public
SENSOR_DESCRIPTIONS_MOBILE: tuple[
    WeatherSensorEntityDescription, ...
] = current_condition_sensor_descriptions_mobile


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Add MetService entities from a config_entry."""
    coordinator: WeatherUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    if entry.data["api"] == "mobile":
        sensors = [
            WeatherSensor(coordinator, description)
            for description in SENSOR_DESCRIPTIONS_MOBILE
        ]
    else:
        sensors = [
            WeatherSensor(coordinator, description)
            for description in SENSOR_DESCRIPTIONS_PUBLIC
        ]

    async_add_entities(sensors)


class WeatherSensor(CoordinatorEntity, SensorEntity):
    """Implementing the MetService sensor."""

    _attr_has_entity_name = True
    _attr_attribution = CONF_ATTRIBUTION
    entity_description: WeatherSensorEntityDescription

    def __init__(
        self,
        coordinator: WeatherUpdateCoordinator,
        description: WeatherSensorEntityDescription,
    ):
        """Initialize MetService sensors."""
        super().__init__(coordinator)
        self.entity_description = description

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.location)},
            name=coordinator.location_name,
            manufacturer=MANUFACTURER,
        )

        self._attr_unique_id = (
            f"{self.coordinator.location_name},{description.key}".lower()
        )
        self._unit_system = coordinator.unit_system
        if self.coordinator.api_type == 'mobile':
            self._sensor_data = coordinator.get_current_mobile(description.key)
        else:
            self._sensor_data = coordinator.get_current_public(description.key)
        self._attr_native_unit_of_measurement = self.entity_description.unit_fn(
            self.coordinator.hass.config.units is METRIC_SYSTEM
        )

    @property
    def available(self) -> bool:
        """Return if weather data is available."""
        return self.coordinator.data is not None

    @property
    def name(self):
        """Return the name of the sensor."""
        return self.entity_description.name

    @property
    def native_value(self) -> StateType:
        """Return the state."""
        if not self._sensor_data:
            _LOGGER.debug("Sensor '%s' has no data.", self.name)
            return None
        try:
            return self.entity_description.value_fn(self._sensor_data, self._unit_system)
        except Exception as e:
            _LOGGER.error("Error processing state for sensor '%s': %s", self.name, e)
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        if not self._sensor_data:
            return {}
        try:
            return self.entity_description.attr_fn(self._sensor_data)
        except Exception as e:
            _LOGGER.error("Error processing attributes for sensor '%s': %s", self.name, e)
            return {}


    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle data update."""
        if self.coordinator.api_type == 'mobile':
            self._sensor_data = self.coordinator.get_current_mobile(self.entity_description.key)
        else:
            self._sensor_data = self.coordinator.get_current_public(self.entity_description.key)
        self.async_write_ha_state()
