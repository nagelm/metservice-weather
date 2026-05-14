"""Sensor Support for MetService weather service.

For more details about this platform, please refer to the documentation at
https://github.com/ciejer/metservice-weather.
"""
from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
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
    """Add MetService entities from a config_entry."""
    coordinator: WeatherUpdateCoordinator = entry.runtime_data
    descriptions = list(SENSOR_DESCRIPTIONS)

    # Skip tide sensors when no tide location is configured
    if not coordinator.enable_tides:
        descriptions = [d for d in descriptions if d.key not in ("tides_high", "tides_low")]

    # Skip boating sensors when no boating location is configured
    if not coordinator.enable_boating:
        descriptions = [d for d in descriptions if d.key not in ("boating_status", "boating_forecast")]

    # Skip surf sensors when no surf location is configured
    _SURF_KEYS = {
        "surf_conditions", "surf_rating", "surf_wave_height", "surf_set_face",
        "surf_swell_direction", "surf_swell_height", "surf_wind_direction",
        "surf_wind_speed", "surf_wind_gust", "surf_period",
    }
    if not coordinator.enable_surf:
        descriptions = [d for d in descriptions if d.key not in _SURF_KEYS]

    sensors = [WeatherSensor(coordinator, description) for description in descriptions]
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
