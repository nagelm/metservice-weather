"""Sensor Support for MetService weather service.

For more details about this platform, please refer to the documentation at
https://github.com/ciejer/metservice-weather.
"""
from __future__ import annotations

import logging

from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.util.unit_system import METRIC_SYSTEM

from typing import Any

from .coordinator import WeatherUpdateCoordinator
from .entity import MetServiceEntity

from .const import CONF_ATTRIBUTION
from .weather_current_conditions_sensors import (
    current_condition_sensor_descriptions_public,
    WeatherSensorEntityDescription,
)

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

SENSOR_DESCRIPTIONS: tuple[
    WeatherSensorEntityDescription, ...
] = current_condition_sensor_descriptions_public


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry[WeatherUpdateCoordinator], async_add_entities: AddEntitiesCallback
) -> None:
    """Add MetService entities from a config_entry.

    Each description's exists_fn decides whether the configured location
    supports that sensor (marine sensors need a configured marine location;
    observation sensors need a weather station, which rural locations lack).
    Registry entries for sensors the location no longer provides are removed
    so users aren't left with permanently-unknown entities.
    """
    coordinator: WeatherUpdateCoordinator = entry.runtime_data
    sensors = [
        WeatherSensor(coordinator, description)
        for description in SENSOR_DESCRIPTIONS
        if description.exists_fn(coordinator)
    ]

    ent_reg = er.async_get(hass)
    expected_unique_ids = {sensor.unique_id for sensor in sensors}
    for reg_entry in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        if reg_entry.domain == SENSOR_DOMAIN and reg_entry.unique_id not in expected_unique_ids:
            ent_reg.async_remove(reg_entry.entity_id)

    async_add_entities(sensors)


class WeatherSensor(MetServiceEntity, SensorEntity):
    """Implementing the MetService sensor."""

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

        self._attr_unique_id = (
            f"{self.coordinator.location}_{description.key}".lower()
        )
        self._unit_system = coordinator.unit_system
        self._sensor_data = coordinator.data
        self._attr_native_unit_of_measurement = self.entity_description.unit_fn(
            self.coordinator.hass.config.units is METRIC_SYSTEM
        )

    @property
    def native_value(self) -> StateType:
        """Return the state."""
        if self._sensor_data is None:
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
        if self._sensor_data is None:
            return {}
        try:
            return self.entity_description.attr_fn(self._sensor_data)
        except Exception as e:
            _LOGGER.error("Error processing attributes for sensor '%s': %s", self.name, e)
            return {}


    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle data update."""
        self._sensor_data = self.coordinator.data
        self.async_write_ha_state()
