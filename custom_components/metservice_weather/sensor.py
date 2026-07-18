"""Sensor Support for MetService weather service.

For more details about this platform, please refer to the documentation at
https://github.com/nagelm/metservice-weather.
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
    DEPRECATED_SENSOR_REPLACEMENTS,
    async_check_deprecated_entities,
    async_check_marine_device_move,
    async_check_removed_entity,
    async_merge_entity_options,
)

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

# Written into a seasonally-disabled row's DOMAIN-scoped registry options
# (entry.options[DOMAIN], merged via deprecation.async_merge_entity_options
# so the deprecation sweep's own "swept"/"swept_version" keys are never
# disturbed) whenever CONF_AUTO_HIDE_SEASONAL disables+hides a dataless
# seasonal sensor's row. Presence of this key (rather than disabled_by/
# hidden_by alone) is what lets a later run tell "we disabled this because
# it's seasonally dataless" apart from a user's own choice or some other
# mechanism's disable (e.g. the deprecation sweep, for an unrelated key).
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
    entry: ConfigEntry,
    unique_id: str,
) -> None:
    """Disable + hide a dataless seasonal sensor's registry row, stamping it as ours.

    Pre-creates the row when none exists yet (a fresh install, or one whose
    row a pre-2026.8 install's old remove-outright behaviour deleted).
    Creation kwargs alone are NOT trusted for the disable: when a deleted
    snapshot exists for the unique_id, async_get_or_create restores the
    snapshot's old disabled_by/hidden_by over whatever creation passes —
    exactly the upgrade path from the old remove-outright behaviour — so a
    just-created row is always brought to disabled+hidden explicitly here.

    Ownership rules are unchanged: USER-set flags (including ones restored
    from a deleted snapshot) always win, and a PRE-EXISTING row that is
    already disabled by anything (the user, this stamp from a prior run, or
    an unrelated mechanism such as the deprecation sweep) is left as-is;
    hidden_by is likewise only set while still None.
    """
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
    """Undo a seasonal-disable stamp: un-disable/un-hide (INTEGRATION-only) and unstamp.

    Shared by the resume listener (data starts flowing again) and the
    option-OFF setup path (the user turned auto-disable back off): only
    disabled_by/hidden_by values still equal to INTEGRATION are cleared —
    a user who has since taken ownership of either field keeps their own
    choice. The stamp itself is always removed once this runs, regardless
    of whether either field needed clearing.
    """
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
    ent_reg: er.EntityRegistry, entry: ConfigEntry
) -> None:
    """Undo every seasonal-disable stamp for this entry (CONF_AUTO_HIDE_SEASONAL is off).

    Walks every sensor-domain registry row belonging to this config entry
    rather than just the live SENSOR_DESCRIPTIONS, so a row the option
    previously stamped is restored even if it no longer corresponds to a
    description this run for any reason.
    """
    for reg_entry in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        if reg_entry.domain != SENSOR_DOMAIN:
            continue
        if not (reg_entry.options.get(DOMAIN) or {}).get(_SEASONAL_STAMP_KEY):
            continue
        _async_clear_seasonal_stamp(ent_reg, reg_entry.entity_id)


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

    Every exists_fn-passing description gets a WeatherSensor built for it —
    seasonal ones (UV, fire danger, clothes drying) included — so the stale-
    registry cleanup above never touches them. When CONF_AUTO_HIDE_SEASONAL
    is enabled, every dataless seasonal description whose key isn't one of
    DEPRECATED_SENSOR_REPLACEMENTS' OLD keys (those no longer correspond to
    any live description as of v2026.9.0 — this guard is now vacuous but
    stays as a harmless belt-and-braces check) instead has its registry row
    disabled and hidden — INTEGRATION-owned, stamped via
    deprecation.async_merge_entity_options — before async_add_entities runs.
    Home Assistant's entity platform never instantiates an entity whose
    registry row is already disabled, so the sensor stays out of the state
    machine without losing its history or settings. A fresh install (or a
    row a pre-2026.8 install's old remove-outright behaviour deleted) is
    pre-created born disabled+hidden. A row the user (or anything else) has
    already taken ownership of is left untouched. A coordinator listener
    then re-checks every stamped description on each update and, once one
    gains data, clears its disabled_by/hidden_by (only where still
    INTEGRATION-owned), removes the stamp, and adds it live via
    async_add_entities — no restart required. Turning the option back off
    restores every row this mechanism ever stamped, in one setup pass.

    After entities are added, async_check_deprecated_entities clears any
    leftover pre-2026.9.0 deprecation issues for this entry and runs the
    entity-ID reclaim detector — see deprecation.py for the full detail.
    When any marine service is configured, async_check_marine_device_move
    similarly raises (or clears) a repair issue for any DEVICE-based
    automation/script still targeting the old location device for marine
    (tide/boating/surf) sensors, which moved to their own marine device.
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

    sensors = [
        WeatherSensor(coordinator, description)
        for description in SENSOR_DESCRIPTIONS
        if description.exists_fn(coordinator)
    ]

    ent_reg = er.async_get(hass)
    expected_unique_ids = {sensor.unique_id for sensor in sensors}
    for reg_entry in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        if (
            reg_entry.domain == SENSOR_DOMAIN
            and reg_entry.unique_id not in expected_unique_ids
        ):
            await async_check_removed_entity(hass, entry, coordinator, reg_entry)
            ent_reg.async_remove(reg_entry.entity_id)

    stamped_seasonal: dict[str, WeatherSensorEntityDescription] = {}
    if auto_hide_seasonal:
        for sensor in sensors:
            description = sensor.entity_description
            if not description.seasonal:
                continue
            if description.key in DEPRECATED_SENSOR_REPLACEMENTS:
                continue
            if not _seasonal_is_dataless(description):
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
        """Re-enable + add previously-disabled seasonal sensors once they have data.

        Only rows still carrying our seasonal stamp are cleared here — see
        _async_clear_seasonal_stamp — so a user who has since taken
        ownership of a row's disabled_by/hidden_by keeps their own choice
        (the entity simply won't be instantiated by async_add_entities
        below if it's still disabled for that reason). Descriptions are
        popped from stamped_seasonal as they're resumed, so repeated
        coordinator updates never process the same sensor twice.
        """
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
    # Bulky machine-payload attributes on the opt-in carrier sensors
    # (tide_direction, warning_details) stay live in the state machine but
    # are never written to the recorder. Matching is by attribute name
    # across the whole class, so these names must stay unique to their
    # carriers.
    _unrecorded_attributes = frozenset({"tide_table", "active_warnings"})
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
