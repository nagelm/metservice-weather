"""Repair issues for deprecated entities and entries."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from typing import Any

from homeassistant.components.automation import (
    automations_with_device,
    automations_with_entity,
)
from homeassistant.components.script import scripts_with_device, scripts_with_entity
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import slugify

from . import MetServiceConfigEntry
from .const import DOMAIN
from .coordinator import WeatherUpdateCoordinator
from .entity import _marine_device_name
from .weather_current_conditions_sensors import (
    current_condition_sensor_descriptions_public,
)

_LOGGER = logging.getLogger(__name__)

_LEARN_MORE_URL = "https://github.com/nagelm/metservice-weather/releases"

DEPRECATED_SENSOR_REPLACEMENTS: dict[str, str] = {
    "uvIndex": "uv_risk",
    "weather_warnings": "warning_level",
    "pressureTendencyTrend": "pressure_trend",
    "wind_strength": "wind_strength_level",
    "fire_season": "fire_season_status",
    "fire_danger": "fire_danger_level",
    "moon_phase": "moon_phase_current",
    "moon_phase_date": "moon_phase_current",
    "sunrise": "sunrise_at",
    "sunset": "sunset_at",
    "moonrise": "moonrise_at",
    "moonset": "moonset_at",
    "pollen_levels": "pollen",
    "pollen_type": "pollen",
}

_MAX_LISTED_REFERENCES = 10

_REPLACEMENT_DISPLAY_NAMES: dict[str, str] = {
    "uv_risk": "UV index",
    "warning_level": "Warnings",
    "pressure_trend": "Pressure tendency",
    "wind_strength_level": "Wind strength",
    "fire_season_status": "Fire season",
    "fire_danger_level": "Fire danger",
    "moon_phase_current": "Moon phase",
    "sunrise_at": "Sunrise",
    "sunset_at": "Sunset",
    "moonrise_at": "Moonrise",
    "moonset_at": "Moonset",
    "pollen": "Pollen",
}


_REPLACEMENT_DETAIL_HINTS: dict[str, str] = {
    "warning_level": (
        " — for the full warning text, use the Warning details sensor: "
        "its active_warnings attribute carries every active warning's name, "
        "detail text, and threat period, untruncated"
    ),
}


def _format_references(references: list[str]) -> str:
    """Comma-join reference entity_ids, capped with a "+N more" suffix."""
    if len(references) <= _MAX_LISTED_REFERENCES:
        return ", ".join(references)
    shown = references[:_MAX_LISTED_REFERENCES]
    extra = len(references) - _MAX_LISTED_REFERENCES
    return f"{', '.join(shown)} (+{extra} more)"


def _referencing_items(hass: HomeAssistant, entity_id: str) -> list[str]:
    """Return automation/script entity_ids that reference entity_id."""
    references: list[str] = []
    if "automation" in hass.config.components:
        references.extend(automations_with_entity(hass, entity_id))
    if "script" in hass.config.components:
        references.extend(scripts_with_entity(hass, entity_id))
    return references


def async_merge_entity_options(
    ent_reg: er.EntityRegistry,
    entity_id: str,
    *,
    updates: dict[str, Any] | None = None,
    remove_keys: Iterable[str] = (),
) -> None:
    """Merge changes into a registry entry's DOMAIN-scoped options."""
    reg_entry = ent_reg.async_get(entity_id)
    if reg_entry is None:
        return
    merged = dict(reg_entry.options.get(DOMAIN) or {})
    for key in remove_keys:
        merged.pop(key, None)
    if updates:
        merged.update(updates)
    ent_reg.async_update_entity_options(entity_id, DOMAIN, merged or None)


async def async_check_deprecated_entities(
    hass: HomeAssistant,
    entry: MetServiceConfigEntry,
) -> None:
    """Clear removed-entity issues nothing references any more."""
    try:
        removed_entity_prefix = f"removed_entity_{entry.entry_id}_"
        issue_reg = ir.async_get(hass)
        for (issue_domain, issue_id), issue in list(issue_reg.issues.items()):
            if issue_domain != DOMAIN or not issue_id.startswith(removed_entity_prefix):
                continue
            stored_entity_id = (issue.data or {}).get("entity_id")
            if not stored_entity_id or not _referencing_items(hass, stored_entity_id):
                ir.async_delete_issue(hass, DOMAIN, issue_id)
    except Exception:
        _LOGGER.debug(
            "Deprecated-entity repair check failed; continuing without it",
            exc_info=True,
        )


_GENERIC_REMOVED_REPLACEMENT_FALLBACK = (
    "no direct replacement — see the release notes for what changed"
)

_DEPRECATED_SENSOR_REPLACEMENTS_LOWER = {
    key.lower(): new_key for key, new_key in DEPRECATED_SENSOR_REPLACEMENTS.items()
}


def _removed_entity_replacement_text(key: str) -> str:
    """Return replacement wording for a removed entity's unique_id key suffix."""
    new_key = _DEPRECATED_SENSOR_REPLACEMENTS_LOWER.get(key.lower())
    if new_key is None:
        return _GENERIC_REMOVED_REPLACEMENT_FALLBACK
    return _REPLACEMENT_DISPLAY_NAMES[new_key] + _REPLACEMENT_DETAIL_HINTS.get(
        new_key, ""
    )


async def async_check_removed_entity(
    hass: HomeAssistant,
    entry: MetServiceConfigEntry,
    coordinator: WeatherUpdateCoordinator,
    reg_entry: er.RegistryEntry,
) -> None:
    """Warn when a stale registry row about to be removed is still referenced."""
    try:
        entity_id = reg_entry.entity_id
        issue_id = f"removed_entity_{entry.entry_id}_{slugify(entity_id)}"
        references = _referencing_items(hass, entity_id)
        if not references:
            ir.async_delete_issue(hass, DOMAIN, issue_id)
            return

        prefix = f"{coordinator.location}_".lower()
        unique_id = reg_entry.unique_id or ""
        key = unique_id.removeprefix(prefix)

        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            is_persistent=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key="removed_entity",
            learn_more_url=_LEARN_MORE_URL,
            translation_placeholders={
                "entity_id": entity_id,
                "references": _format_references(references),
                "replacement": _removed_entity_replacement_text(key),
            },
            data={"entity_id": entity_id},
        )
    except Exception:
        _LOGGER.debug(
            "Removed-entity repair check failed for %s; continuing without it",
            getattr(reg_entry, "entity_id", "<unknown>"),
            exc_info=True,
        )


def _raw_config_json(hass: HomeAssistant, entity_id: str) -> str | None:
    """Return a best-effort JSON dump of an automation/script's raw YAML config."""
    try:
        domain = entity_id.split(".", 1)[0]
        component = hass.data[domain]
        entity = component.get_entity(entity_id)
        raw_config = getattr(entity, "raw_config", None)
        if raw_config is None:
            return None
        return json.dumps(raw_config, default=str)
    except AttributeError, KeyError, TypeError:
        return None


async def async_check_removed_forecast_attributes(
    hass: HomeAssistant,
    entry: MetServiceConfigEntry,
    coordinator: WeatherUpdateCoordinator,
) -> None:
    """Warn when an automation/script still reads forecast_hourly/forecast_daily."""
    issue_id = f"forecast_attributes_{entry.entry_id}"
    try:
        ent_reg = er.async_get(hass)
        unique_id = f"{coordinator.location}_weather".lower()
        entity_id = ent_reg.async_get_entity_id("weather", DOMAIN, unique_id)
        if entity_id is None:
            ir.async_delete_issue(hass, DOMAIN, issue_id)
            return

        offenders = [
            reference
            for reference in _referencing_items(hass, entity_id)
            if (raw_json := _raw_config_json(hass, reference)) is not None
            and ("forecast_hourly" in raw_json or "forecast_daily" in raw_json)
        ]

        if not offenders:
            ir.async_delete_issue(hass, DOMAIN, issue_id)
            return

        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="forecast_attributes_removed",
            learn_more_url=_LEARN_MORE_URL,
            translation_placeholders={"references": _format_references(offenders)},
        )
    except Exception:
        _LOGGER.debug(
            "Removed-forecast-attributes repair check failed; continuing without it",
            exc_info=True,
        )


_MARINE_SENSOR_KEYS: frozenset[str] = frozenset(
    description.key
    for description in current_condition_sensor_descriptions_public
    if description.device == "marine"
)

_MARINE_REFERENCE_TOKENS: tuple[str, ...] = ("tides_high", "surf_", "boating_")


def _device_referencing_items(hass: HomeAssistant, device_id: str) -> list[str]:
    """Return automation/script entity_ids with a trigger/condition/action on device_id."""
    references: list[str] = []
    if "automation" in hass.config.components:
        references.extend(automations_with_device(hass, device_id))
    if "script" in hass.config.components:
        references.extend(scripts_with_device(hass, device_id))
    return references


async def async_check_marine_device_move(
    hass: HomeAssistant,
    entry: MetServiceConfigEntry,
    coordinator: WeatherUpdateCoordinator,
) -> None:
    """Warn when a DEVICE-based automation/script still targets the old location device for marine sensors."""
    issue_id = f"marine_device_move_{entry.entry_id}"
    try:
        if not (
            coordinator.enable_tides
            or coordinator.enable_boating
            or coordinator.enable_surf
        ):
            ir.async_delete_issue(hass, DOMAIN, issue_id)
            return

        dev_reg = dr.async_get(hass)
        device = dev_reg.async_get_device_by_identifier(
            (DOMAIN, coordinator.location), entry.entry_id
        )
        if device is None:
            ir.async_delete_issue(hass, DOMAIN, issue_id)
            return

        candidates = _device_referencing_items(hass, device.id)
        if not candidates:
            ir.async_delete_issue(hass, DOMAIN, issue_id)
            return

        ent_reg = er.async_get(hass)
        marine_entity_ids = {
            entity_id
            for key in _MARINE_SENSOR_KEYS
            if (
                entity_id := ent_reg.async_get_entity_id(
                    "sensor", DOMAIN, f"{coordinator.location}_{key}".lower()
                )
            )
            is not None
        }

        offenders = [
            reference
            for reference in candidates
            if (raw_json := _raw_config_json(hass, reference)) is not None
            and (
                any(entity_id in raw_json for entity_id in marine_entity_ids)
                or any(token in raw_json for token in _MARINE_REFERENCE_TOKENS)
            )
        ]

        if not offenders:
            ir.async_delete_issue(hass, DOMAIN, issue_id)
            return

        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="marine_device_move",
            learn_more_url=_LEARN_MORE_URL,
            translation_placeholders={
                "references": _format_references(offenders),
                "marine_device": _marine_device_name(
                    coordinator.marine_region_slug, coordinator.location_name
                ),
            },
        )
    except Exception:
        _LOGGER.debug(
            "Marine-device-move repair check failed; continuing without it",
            exc_info=True,
        )
