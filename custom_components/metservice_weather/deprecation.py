"""Repair issues for deprecated entities and entries."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from typing import Any

from homeassistant.components.automation import (
    automations_with_device,
    automations_with_entity,
)
from homeassistant.components.group import groups_with_entity
from homeassistant.components.homeassistant.exposed_entities import (
    async_get_entity_settings,
)
from homeassistant.components.homeassistant.scene import scenes_with_entity
from homeassistant.components.script import scripts_with_device, scripts_with_entity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import slugify

from .const import DOMAIN
from .coordinator import WeatherUpdateCoordinator
from .entity import _marine_device_name
from .weather_current_conditions_sensors import (
    WeatherSensorEntityDescription,
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


def _friendly_key(key: str) -> str:
    """Return a human-readable form of a snake_case replacement sensor key."""
    return " ".join(
        word.upper() if word == "uv" else word.capitalize() for word in key.split("_")
    )


def _replacement_display_name(key: str) -> str:
    """Return the replacement sensor's display name for repair-issue text."""
    return _REPLACEMENT_DISPLAY_NAMES.get(key, _friendly_key(key))


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


_TRACK_STATE_CHANGE_DATA_KEY = "track_state_change_data"


def _dump_json(value: Any) -> str | None:
    """Best-effort JSON dump for substring matching; None on failure."""
    try:
        return json.dumps(value, default=str)
    except (TypeError, ValueError):
        return None


def _config_entries_referencing(hass: HomeAssistant, entity_id: str) -> list[str]:
    """Return "{domain}: {title}" for other integrations' entries that mention entity_id."""
    evidence: list[str] = []
    for config_entry in hass.config_entries.async_entries():
        if config_entry.domain in (DOMAIN, "homekit"):
            continue
        try:
            data_json = _dump_json(config_entry.data)
            options_json = _dump_json(config_entry.options)
            if (data_json and entity_id in data_json) or (
                options_json and entity_id in options_json
            ):
                evidence.append(f"{config_entry.domain}: {config_entry.title}")
        except Exception:
            continue
    return evidence


def _homekit_includes(hass: HomeAssistant, entity_id: str) -> bool:
    """Return True when a HomeKit config entry's options mention entity_id."""
    for config_entry in hass.config_entries.async_entries("homekit"):
        try:
            options_json = _dump_json(config_entry.options)
            if options_json and entity_id in options_json:
                return True
        except Exception:
            continue
    return False


def _voice_assistant_exposure(hass: HomeAssistant, entity_id: str) -> list[str]:
    """Return assistant keys (e.g. "conversation", "cloud.alexa") exposing entity_id."""
    settings = async_get_entity_settings(hass, entity_id)
    return [
        assistant
        for assistant, options in settings.items()
        if options.get("should_expose")
    ]


def _has_in_process_listener(hass: HomeAssistant, entity_id: str) -> bool:
    """Best-effort check for an in-process state-change listener on entity_id."""
    callbacks = hass.data.get(_TRACK_STATE_CHANGE_DATA_KEY)
    if isinstance(callbacks, dict):
        return bool(callbacks.get(entity_id))
    return False


async def _dashboards_referencing(hass: HomeAssistant, entity_id: str) -> list[str]:
    """Return a title/url_path for every Lovelace dashboard whose config mentions entity_id."""
    if "lovelace" not in hass.config.components:
        return []

    try:
        from homeassistant.components.lovelace import LOVELACE_DATA as _lovelace_key
    except ImportError:
        _lovelace_key = "lovelace"

    lovelace_data = hass.data.get(_lovelace_key)
    dashboards = getattr(lovelace_data, "dashboards", None)
    if not dashboards:
        return []

    evidence: list[str] = []
    for url_path, dash in dashboards.items():
        try:
            config = await dash.async_load(False)
            if not config:
                continue
            config_json = _dump_json(config)
            if not config_json or entity_id not in config_json:
                continue
            dash_config = getattr(dash, "config", None)
            title = dash_config.get("title") if isinstance(dash_config, dict) else None
            evidence.append(title or url_path or "default")
        except Exception:
            continue
    return evidence


async def _usage_signals(hass: HomeAssistant, entity_id: str) -> dict[str, Any]:
    """Return a dict of usage evidence for entity_id; an empty dict means UNUSED."""
    signals: dict[str, Any] = {}

    try:
        if "automation" in hass.config.components:
            automations = automations_with_entity(hass, entity_id)
            if automations:
                signals["automations"] = automations
    except Exception:
        pass

    try:
        if "script" in hass.config.components:
            scripts = scripts_with_entity(hass, entity_id)
            if scripts:
                signals["scripts"] = scripts
    except Exception:
        pass

    try:
        if "scene" in hass.config.components:
            scenes = scenes_with_entity(hass, entity_id)
            if scenes:
                signals["scenes"] = scenes
    except Exception:
        pass

    try:
        if "group" in hass.config.components:
            groups = groups_with_entity(hass, entity_id)
            if groups:
                signals["groups"] = groups
    except Exception:
        pass

    try:
        dashboards = await _dashboards_referencing(hass, entity_id)
        if dashboards:
            signals["dashboards"] = dashboards
    except Exception:
        pass

    try:
        helpers = _config_entries_referencing(hass, entity_id)
        if helpers:
            signals["helpers"] = helpers
    except Exception:
        pass

    try:
        voice = _voice_assistant_exposure(hass, entity_id)
        if voice:
            signals["voice"] = voice
    except Exception:
        pass

    try:
        if _homekit_includes(hass, entity_id):
            signals["homekit"] = True
    except Exception:
        pass

    try:
        if _has_in_process_listener(hass, entity_id):
            signals["listeners"] = True
    except Exception:
        pass

    return signals


_EVIDENCE_LABELS: tuple[tuple[str, str], ...] = (
    ("automations", "automation"),
    ("scripts", "script"),
    ("scenes", "scene"),
    ("groups", "group"),
    ("dashboards", "dashboard"),
    ("helpers", "helper"),
    ("voice", "voice assistant"),
)


def _format_evidence(signals: dict[str, Any]) -> str:
    """Render a usage-signals dict as a concise, semicolon-joined evidence summary."""
    parts: list[str] = []
    for signal_key, singular in _EVIDENCE_LABELS:
        items = signals.get(signal_key)
        if items:
            label = singular if len(items) == 1 else f"{singular}s"
            parts.append(f"{label}: {_format_references(items)}")
    if signals.get("homekit"):
        parts.append("HomeKit")
    if signals.get("listeners"):
        parts.append("an in-process listener")
    return "; ".join(parts) if parts else "no specific usage detected"


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
    entry: ConfigEntry,
    coordinator: WeatherUpdateCoordinator,
) -> None:
    """Clear obsolete pre-2026.9.0 deprecation issues, then run the follow-on detectors."""
    try:
        ir.async_delete_issue(hass, DOMAIN, f"hidden_deprecated_{entry.entry_id}")
        ir.async_delete_issue(hass, DOMAIN, f"deprecated_sweep_v2_{entry.entry_id}")
        for old_key in DEPRECATED_SENSOR_REPLACEMENTS:
            ir.async_delete_issue(
                hass, DOMAIN, f"deprecated_entity_{entry.entry_id}_{old_key}"
            )

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

    await async_check_entity_id_reclaim(hass, entry, coordinator)


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
    return _replacement_display_name(new_key) + _REPLACEMENT_DETAIL_HINTS.get(
        new_key, ""
    )


async def async_check_removed_entity(
    hass: HomeAssistant,
    entry: ConfigEntry,
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
    except (AttributeError, KeyError, TypeError):
        return None


async def async_check_removed_forecast_attributes(
    hass: HomeAssistant,
    entry: ConfigEntry,
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
    entry: ConfigEntry,
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


_REPLACEMENT_DESCRIPTIONS_BY_KEY: dict[str, WeatherSensorEntityDescription] = {
    description.key: description
    for description in current_condition_sensor_descriptions_public
}


def _reclaim_issue_id(entry_id: str) -> str:
    """Return the per-entry consolidated fixable entity_id_reclaim issue_id."""
    return f"entity_id_reclaim_{entry_id}"


def _reclaim_referenced_issue_id(entry_id: str) -> str:
    """Return the per-entry consolidated non-fixable reclaim issue_id."""
    return f"entity_id_reclaim_referenced_{entry_id}"


def _clear_legacy_per_key_reclaim_issues(hass: HomeAssistant, entry_id: str) -> None:
    """Delete the per-key reclaim issues an a4-era run may have left behind."""
    for key in sorted(set(DEPRECATED_SENSOR_REPLACEMENTS.values())):
        ir.async_delete_issue(hass, DOMAIN, f"entity_id_reclaim_{entry_id}_{key}")
        ir.async_delete_issue(
            hass, DOMAIN, f"entity_id_reclaim_referenced_{entry_id}_{key}"
        )


def _format_rename_lines(renames: list[dict[str, str]]) -> str:
    """Render a markdown bullet list of `current` → `new` rename candidates."""
    return "\n".join(
        f"- **{r['sensor_name']}**: `{r['current_entity_id']}` → `{r['new_entity_id']}`"
        for r in renames
    )


async def async_check_entity_id_reclaim(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: WeatherUpdateCoordinator,
) -> None:
    """Offer to rename a replacement sensor onto its now-free canonical entity_id."""
    try:
        ent_reg = er.async_get(hass)
        dev_reg = dr.async_get(hass)

        _clear_legacy_per_key_reclaim_issues(hass, entry.entry_id)

        renames: list[dict[str, str]] = []
        referenced: list[dict[str, str]] = []

        for key in sorted(set(DEPRECATED_SENSOR_REPLACEMENTS.values())):
            description = _REPLACEMENT_DESCRIPTIONS_BY_KEY.get(key)
            if description is None:
                continue

            unique_id = f"{coordinator.location}_{key}".lower()
            entity_id = ent_reg.async_get_entity_id("sensor", DOMAIN, unique_id)
            if entity_id is None:
                continue

            reg_entry = ent_reg.async_get(entity_id)
            if reg_entry is None:
                continue

            device = (
                dev_reg.async_get(reg_entry.device_id) if reg_entry.device_id else None
            )
            device_name = (device.name_by_user or device.name) if device else None
            if not device_name:
                continue

            canonical_object_id = slugify(f"{device_name} {description.name}")
            current_object_id = entity_id.split(".", 1)[1]
            if not re.fullmatch(
                re.escape(canonical_object_id) + r"_\d+", current_object_id
            ):
                continue

            canonical_entity_id = f"sensor.{canonical_object_id}"
            if ent_reg.async_get(canonical_entity_id) is not None:
                continue

            candidate = {
                "current_entity_id": entity_id,
                "new_entity_id": canonical_entity_id,
                "sensor_name": description.name,
            }
            signals = await _usage_signals(hass, entity_id)
            if not signals:
                renames.append(candidate)
            else:
                referenced.append(
                    {**candidate, "references": _format_evidence(signals)}
                )

        if renames:
            ir.async_create_issue(
                hass,
                DOMAIN,
                _reclaim_issue_id(entry.entry_id),
                is_fixable=True,
                severity=ir.IssueSeverity.WARNING,
                translation_key="entity_id_reclaim",
                learn_more_url=_LEARN_MORE_URL,
                translation_placeholders={
                    "count": str(len(renames)),
                    "renames": _format_rename_lines(renames),
                },
                data={"renames": renames},
            )
        else:
            ir.async_delete_issue(hass, DOMAIN, _reclaim_issue_id(entry.entry_id))

        if referenced:
            ir.async_create_issue(
                hass,
                DOMAIN,
                _reclaim_referenced_issue_id(entry.entry_id),
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="entity_id_reclaim_referenced",
                learn_more_url=_LEARN_MORE_URL,
                translation_placeholders={
                    "count": str(len(referenced)),
                    "details": "\n".join(
                        f"- **{r['sensor_name']}**: `{r['current_entity_id']}` → "
                        f"`{r['new_entity_id']}` — referenced by: {r['references']}"
                        for r in referenced
                    ),
                },
            )
        else:
            ir.async_delete_issue(
                hass, DOMAIN, _reclaim_referenced_issue_id(entry.entry_id)
            )
    except Exception:
        _LOGGER.debug(
            "Entity-ID reclaim repair check failed; continuing without it",
            exc_info=True,
        )
