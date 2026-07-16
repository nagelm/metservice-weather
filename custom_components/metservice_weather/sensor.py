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
from .deprecation import (
    async_check_deprecated_entities,
    async_check_marine_device_move,
    async_check_removed_entity,
)

from .const import CONF_ATTRIBUTION, CONF_AUTO_HIDE_SEASONAL
from .weather_current_conditions_sensors import (
    current_condition_sensor_descriptions_public,
    WeatherSensorEntityDescription,
)

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

SENSOR_DESCRIPTIONS: tuple[WeatherSensorEntityDescription, ...] = (
    current_condition_sensor_descriptions_public
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[WeatherUpdateCoordinator],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add MetService entities from a config_entry.

    Each description's exists_fn decides whether the configured location
    supports that sensor (marine sensors need a configured marine location;
    observation sensors need a weather station, which rural locations lack).
    Registry entries for sensors the location no longer provides are removed
    so users aren't left with permanently-unknown entities. Before each
    removal, async_check_removed_entity raises a (self-clearing) repair
    issue if the entity being deleted is still referenced by an automation
    or script.

    When CONF_AUTO_HIDE_SEASONAL is enabled, seasonal descriptions (UV, fire
    danger, clothes drying) that currently have no data are skipped at setup
    instead of being created in an always-unknown state — the stale-registry
    cleanup below removes any leftover registry entries for them. A
    coordinator listener re-checks the skipped descriptions on every update
    and creates them once MetService resumes publishing data.

    After entities are added, async_check_deprecated_entities raises (or
    clears) repair issues for any pre-v2026.7.1 sensor still referenced by
    an automation or script. When any marine service is configured,
    async_check_marine_device_move similarly raises (or clears) a repair
    issue for any DEVICE-based automation/script still targeting the old
    location device for marine (tide/boating/surf) sensors, which moved to
    their own marine device.
    """
    coordinator: WeatherUpdateCoordinator = entry.runtime_data
    auto_hide_seasonal = entry.data.get(CONF_AUTO_HIDE_SEASONAL, False)

    def _seasonal_is_dataless(description: WeatherSensorEntityDescription) -> bool:
        """Return True when a seasonal description currently has no data."""
        if coordinator.data is None:
            return True
        try:
            return (
                description.value_fn(coordinator.data, coordinator.unit_system) is None
            )
        except Exception:
            return True

    skipped_seasonal: dict[str, WeatherSensorEntityDescription] = {}
    sensors = []
    for description in SENSOR_DESCRIPTIONS:
        if not description.exists_fn(coordinator):
            continue
        if (
            auto_hide_seasonal
            and description.seasonal
            and _seasonal_is_dataless(description)
        ):
            skipped_seasonal[description.key] = description
            continue
        sensors.append(WeatherSensor(coordinator, description))

    ent_reg = er.async_get(hass)
    expected_unique_ids = {sensor.unique_id for sensor in sensors}
    for reg_entry in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        if (
            reg_entry.domain == SENSOR_DOMAIN
            and reg_entry.unique_id not in expected_unique_ids
        ):
            await async_check_removed_entity(hass, entry, coordinator, reg_entry)
            ent_reg.async_remove(reg_entry.entity_id)

    async_add_entities(sensors)

    await async_check_deprecated_entities(hass, entry, coordinator)

    if (
        coordinator.enable_tides
        or coordinator.enable_boating
        or coordinator.enable_surf
    ):
        await async_check_marine_device_move(hass, entry, coordinator)

    if not skipped_seasonal:
        return

    @callback
    def _add_seasonal_sensors_with_data() -> None:
        """Create previously-skipped seasonal sensors once they have data.

        Descriptions are popped from skipped_seasonal as they are created,
        so repeated coordinator updates never create the same sensor twice.
        """
        ready_keys = [
            key
            for key, description in skipped_seasonal.items()
            if not _seasonal_is_dataless(description)
        ]
        if not ready_keys:
            return
        new_sensors = [
            WeatherSensor(coordinator, skipped_seasonal.pop(key)) for key in ready_keys
        ]
        async_add_entities(new_sensors)

    unsub = coordinator.async_add_listener(_add_seasonal_sensors_with_data)
    entry.async_on_unload(unsub)


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
        super().__init__(coordinator, device=description.device)
        self.entity_description = description

        self._attr_unique_id = f"{self.coordinator.location}_{description.key}".lower()
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
            return self.entity_description.value_fn(
                self._sensor_data, self._unit_system
            )
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
            _LOGGER.error(
                "Error processing attributes for sensor '%s': %s", self.name, e
            )
            return {}

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle data update."""
        self._sensor_data = self.coordinator.data
        self.async_write_ha_state()
