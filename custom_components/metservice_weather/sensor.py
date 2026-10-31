"""Sensor Support for MetService weather service."""

from __future__ import annotations

import logging

from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN, SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from typing import Any

from .coordinator import WeatherUpdateCoordinator
from .entity import MetServiceEntity
from .deprecation import (
    async_check_deprecated_entities,
    async_check_marine_device_move,
    async_check_removed_entity,
    async_merge_entity_options,
)

from . import MetServiceConfigEntry
from .const import CONF_ATTRIBUTION, CONF_AUTO_HIDE_SEASONAL, DOMAIN
from .weather_current_conditions_sensors import (
    current_condition_sensor_descriptions_public,
    WeatherSensorEntityDescription,
)

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

SENSOR_DESCRIPTIONS: tuple[WeatherSensorEntityDescription, ...] = (
    current_condition_sensor_descriptions_public
)

_SEASONAL_STAMP_KEY = "seasonal_disabled"


def _seasonal_row_is_stamped(ent_reg: er.EntityRegistry, unique_id: str) -> bool:
    """Return True when unique_id's registry row still carries our seasonal stamp."""
    entity_id = ent_reg.async_get_entity_id(SENSOR_DOMAIN, DOMAIN, unique_id)
    if entity_id is None:
        return False
    reg_entry = ent_reg.async_get(entity_id)
    if reg_entry is None:
        return False
    return bool((reg_entry.options.get(DOMAIN) or {}).get(_SEASONAL_STAMP_KEY))


def _async_apply_seasonal_disable(
    ent_reg: er.EntityRegistry,
    entry: MetServiceConfigEntry,
    unique_id: str,
) -> None:
    """Disable + hide a dataless seasonal sensor's registry row, stamping it as ours."""
    entity_id = ent_reg.async_get_entity_id(SENSOR_DOMAIN, DOMAIN, unique_id)
    created = False
    if entity_id is None:
        reg_entry = ent_reg.async_get_or_create(
            SENSOR_DOMAIN,
            DOMAIN,
            unique_id,
            config_entry=entry,
            disabled_by=er.RegistryEntryDisabler.INTEGRATION,
            hidden_by=er.RegistryEntryHider.INTEGRATION,
        )
        entity_id = reg_entry.entity_id
        created = True

    reg_entry = ent_reg.async_get(entity_id)
    if reg_entry is None:
        return
    if (
        reg_entry.disabled_by == er.RegistryEntryDisabler.USER
        or reg_entry.hidden_by == er.RegistryEntryHider.USER
    ):
        return
    if not created and reg_entry.disabled_by is not None:
        return

    update_kwargs: dict[str, Any] = {}
    if reg_entry.disabled_by is None:
        update_kwargs["disabled_by"] = er.RegistryEntryDisabler.INTEGRATION
    if reg_entry.hidden_by is None:
        update_kwargs["hidden_by"] = er.RegistryEntryHider.INTEGRATION
    if update_kwargs:
        ent_reg.async_update_entity(entity_id, **update_kwargs)
    async_merge_entity_options(ent_reg, entity_id, updates={_SEASONAL_STAMP_KEY: True})


def _async_clear_seasonal_stamp(ent_reg: er.EntityRegistry, entity_id: str) -> None:
    """Undo a seasonal-disable stamp: un-disable/un-hide (INTEGRATION-only) and unstamp."""
    reg_entry = ent_reg.async_get(entity_id)
    if reg_entry is None:
        return
    update_kwargs: dict[str, Any] = {}
    if reg_entry.disabled_by == er.RegistryEntryDisabler.INTEGRATION:
        update_kwargs["disabled_by"] = None
    if reg_entry.hidden_by == er.RegistryEntryHider.INTEGRATION:
        update_kwargs["hidden_by"] = None
    if update_kwargs:
        ent_reg.async_update_entity(entity_id, **update_kwargs)
    async_merge_entity_options(ent_reg, entity_id, remove_keys=(_SEASONAL_STAMP_KEY,))


def _async_restore_seasonal_rows(
    ent_reg: er.EntityRegistry, entry: MetServiceConfigEntry
) -> None:
    """Undo every seasonal-disable stamp for this entry (CONF_AUTO_HIDE_SEASONAL is off)."""
    for reg_entry in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        if reg_entry.domain != SENSOR_DOMAIN:
            continue
        if not (reg_entry.options.get(DOMAIN) or {}).get(_SEASONAL_STAMP_KEY):
            continue
        _async_clear_seasonal_stamp(ent_reg, reg_entry.entity_id)


def _is_stale(
    description: WeatherSensorEntityDescription | None,
    coordinator: WeatherUpdateCoordinator,
) -> bool:
    """Return True when a registry row the integration is not creating can go.

    Only configuration decides: a retired key, a marine sensor whose station is
    not configured, or (with data in hand) an observation sensor on a rural
    location. Without data the row is kept for the next setup.
    """
    if description is None or description.device == "marine":
        return True
    return coordinator.data is not None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MetServiceConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add MetService entities from a config_entry."""
    coordinator: WeatherUpdateCoordinator = entry.runtime_data
    auto_hide_seasonal = entry.data.get(CONF_AUTO_HIDE_SEASONAL, False)

    def _seasonal_is_dataless(description: WeatherSensorEntityDescription) -> bool:
        """Return True when a seasonal description currently has no data."""
        if coordinator.data is None:
            return True
        try:
            return description.value_fn(coordinator.data) is None
        except Exception:
            return True

    sensors = [
        WeatherSensor(coordinator, description)
        for description in SENSOR_DESCRIPTIONS
        if description.exists_fn(coordinator)
    ]

    ent_reg = er.async_get(hass)
    expected_unique_ids = {sensor.unique_id for sensor in sensors}
    descriptions_by_unique_id = {
        f"{coordinator.location}_{description.key}".lower(): description
        for description in SENSOR_DESCRIPTIONS
    }
    for reg_entry in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        if (
            reg_entry.domain == SENSOR_DOMAIN
            and reg_entry.unique_id not in expected_unique_ids
            and _is_stale(
                descriptions_by_unique_id.get(reg_entry.unique_id), coordinator
            )
        ):
            await async_check_removed_entity(hass, entry, coordinator, reg_entry)
            ent_reg.async_remove(reg_entry.entity_id)

    stamped_seasonal: dict[str, WeatherSensorEntityDescription] = {}
    if auto_hide_seasonal:
        for sensor in sensors:
            description = sensor.entity_description
            if not description.seasonal:
                continue
            if not _seasonal_is_dataless(description):
                if _seasonal_row_is_stamped(ent_reg, sensor.unique_id):
                    _async_clear_seasonal_stamp(
                        ent_reg,
                        ent_reg.async_get_entity_id(
                            SENSOR_DOMAIN, DOMAIN, sensor.unique_id
                        ),
                    )
                continue
            _async_apply_seasonal_disable(ent_reg, entry, sensor.unique_id)
            if _seasonal_row_is_stamped(ent_reg, sensor.unique_id):
                stamped_seasonal[description.key] = description
    else:
        _async_restore_seasonal_rows(ent_reg, entry)

    async_add_entities(sensors)

    await async_check_deprecated_entities(hass, entry, coordinator)

    if (
        coordinator.enable_tides
        or coordinator.enable_boating
        or coordinator.enable_surf
    ):
        await async_check_marine_device_move(hass, entry, coordinator)

    if not stamped_seasonal:
        return

    @callback
    def _resume_seasonal_sensors_with_data() -> None:
        """Re-enable + add previously-disabled seasonal sensors once they have data."""
        ready_keys = [
            key
            for key, description in stamped_seasonal.items()
            if not _seasonal_is_dataless(description)
        ]
        if not ready_keys:
            return
        new_sensors = []
        for key in ready_keys:
            description = stamped_seasonal.pop(key)
            unique_id = f"{coordinator.location}_{description.key}".lower()
            entity_id = ent_reg.async_get_entity_id(SENSOR_DOMAIN, DOMAIN, unique_id)
            if entity_id is not None:
                _async_clear_seasonal_stamp(ent_reg, entity_id)
            new_sensors.append(WeatherSensor(coordinator, description))
        async_add_entities(new_sensors)

    unsub = coordinator.async_add_listener(_resume_seasonal_sensors_with_data)
    entry.async_on_unload(unsub)


class WeatherSensor(MetServiceEntity, SensorEntity):
    """Implementing the MetService sensor."""

    _attr_attribution = CONF_ATTRIBUTION
    _unrecorded_attributes = frozenset(
        {"tide_table", "active_warnings", "daily_conditions"}
    )
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
        self._sensor_data = coordinator.data

    @property
    def native_value(self) -> StateType:
        """Return the state."""
        if self._sensor_data is None:
            _LOGGER.debug("Sensor '%s' has no data.", self.name)
            return None
        try:
            return self.entity_description.value_fn(self._sensor_data)
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
