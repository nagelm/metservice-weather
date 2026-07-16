"""Repair issues for entities/entries deprecated across the v0.9.x -> v1.0+ and v2026.7.1 transitions.

Three retroactive, evidence-driven detectors live here (a fourth,
legacy-entry, lives in __init__.py since it runs before any coordinator
exists):

* Deprecated sensors — every sensor key whose state format changed in
  v2026.7.1 was forked: the OLD key kept its v2026.7.0 behaviour (disabled
  and hidden by default for new installs, but left enabled for existing
  installs that already have a registry row for it) and a NEW sibling
  sensor carries the new behaviour, enabled by default. Raises a
  (self-clearing) repair issue for any existing install whose old,
  deprecated entity is still referenced by an automation or script.
* Removed entity still referenced — generic catch for ANY 0.9.x-era
  entity a stale-registry cleanup is about to delete (sensor or weather
  domain), not just the sensors tracked below.
* Removed forecast attributes — v0.9.x exposed forecast_hourly/
  forecast_daily as weather-entity attributes; both were removed in
  favour of the weather.get_forecasts action.

All three are warning/error severity, non-fixable (the fix is a config or
automation change only the user can make), self-clearing once the
underlying condition stops being true, and wrapped so a failure in any of
them can never break setup.
"""

from __future__ import annotations

import json
import logging

from homeassistant.components.automation import automations_with_entity
from homeassistant.components.script import scripts_with_entity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import slugify

from .const import DOMAIN
from .coordinator import WeatherUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

_LEARN_MORE_URL = "https://github.com/nagelm/metservice-weather/releases"

# Every OLD sensor key deprecated by the v2026.7.1 fork, mapped to the key
# of the NEW sibling sensor that carries its behaviour going forward.
# pollen_levels and pollen_type both collapse onto the single "pollen"
# enum sensor introduced alongside them.
DEPRECATED_SENSOR_REPLACEMENTS: dict[str, str] = {
    "uvIndex": "uv_risk",
    "weather_warnings": "warning_level",
    "pressureTendencyTrend": "pressure_trend",
    "wind_strength": "wind_strength_level",
    "fire_season": "fire_season_status",
    "fire_danger": "fire_danger_level",
    "moon_phase": "next_moon_phase",
    "sunrise": "sunrise_at",
    "sunset": "sunset_at",
    "moonrise": "moonrise_at",
    "moonset": "moonset_at",
    "pollen_levels": "pollen",
    "pollen_type": "pollen",
}

# Cap the reference list in the issue message so a heavily-automated
# install doesn't produce an unreadable wall of entity_ids.
_MAX_LISTED_REFERENCES = 10


def _friendly_key(key: str) -> str:
    """Return a human-readable form of a snake_case replacement sensor key."""
    return " ".join(
        word.upper() if word == "uv" else word.capitalize() for word in key.split("_")
    )


def _format_references(references: list[str]) -> str:
    """Comma-join reference entity_ids, capped with a "+N more" suffix."""
    if len(references) <= _MAX_LISTED_REFERENCES:
        return ", ".join(references)
    shown = references[:_MAX_LISTED_REFERENCES]
    extra = len(references) - _MAX_LISTED_REFERENCES
    return f"{', '.join(shown)} (+{extra} more)"


def _referencing_items(hass: HomeAssistant, entity_id: str) -> list[str]:
    """Return automation/script entity_ids that reference entity_id.

    Shared by all three detectors in this module. Each helper is only
    called once its owning component has loaded — calling
    automations_with_entity before the automation component is set up
    raises, so a missing component simply contributes no references
    rather than being treated as an error.
    """
    references: list[str] = []
    if "automation" in hass.config.components:
        references.extend(automations_with_entity(hass, entity_id))
    if "script" in hass.config.components:
        references.extend(scripts_with_entity(hass, entity_id))
    return references


async def async_check_deprecated_entities(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: WeatherUpdateCoordinator,
) -> None:
    """Create or clear repair issues for deprecated sensors still in use.

    For every deprecated sensor key: if the location has no registry row
    for it, or the row is disabled, there is nothing to warn about (a new
    install never creates it disabled-by-default; an existing install that
    already disabled it has already migrated) — any stale issue is
    cleared. Otherwise, automations/scripts referencing the entity are
    collected; a repair issue is created when there are any, and cleared
    (self-heals) once there are none.

    Also sweeps and self-clears any "removed_entity" issue (detector 1,
    below) for this entry whose stored entity_id is no longer referenced —
    self-corrected users see nothing.

    Wrapped in a broad except so a failure in this best-effort check can
    never break sensor setup.
    """
    try:
        ent_reg = er.async_get(hass)
        for old_key, new_key in DEPRECATED_SENSOR_REPLACEMENTS.items():
            issue_id = f"deprecated_entity_{entry.entry_id}_{old_key}"
            unique_id = f"{coordinator.location}_{old_key}".lower()
            entity_id = ent_reg.async_get_entity_id("sensor", DOMAIN, unique_id)
            if entity_id is None:
                ir.async_delete_issue(hass, DOMAIN, issue_id)
                continue

            reg_entry = ent_reg.async_get(entity_id)
            if reg_entry is None or reg_entry.disabled_by is not None:
                ir.async_delete_issue(hass, DOMAIN, issue_id)
                continue

            references = _referencing_items(hass, entity_id)
            if not references:
                ir.async_delete_issue(hass, DOMAIN, issue_id)
                continue

            ir.async_create_issue(
                hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="deprecated_entity",
                learn_more_url=_LEARN_MORE_URL,
                translation_placeholders={
                    "entity_id": entity_id,
                    "replacement_key": _friendly_key(new_key),
                    "references": _format_references(references),
                },
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


# ---------------------------------------------------------------------------
# Detector 1: removed entity still referenced
# ---------------------------------------------------------------------------

# Wording used when a removed entity's unique_id key suffix has no known
# entry in DEPRECATED_SENSOR_REPLACEMENTS (e.g. a fully-retired feature, or
# a pre-fork unique_id scheme that doesn't carry a recognisable key at all).
_GENERIC_REMOVED_REPLACEMENT_FALLBACK = (
    "no direct replacement — see the release notes for what changed"
)

# unique_ids are always lowercased (see WeatherSensor._attr_unique_id), so a
# key recovered from one is always lowercase too — this lets it still match
# the camelCase OLD keys in DEPRECATED_SENSOR_REPLACEMENTS (e.g. "uvIndex").
_DEPRECATED_SENSOR_REPLACEMENTS_LOWER = {
    key.lower(): new_key for key, new_key in DEPRECATED_SENSOR_REPLACEMENTS.items()
}


def _removed_entity_replacement_text(key: str) -> str:
    """Return replacement wording for a removed entity's unique_id key suffix."""
    new_key = _DEPRECATED_SENSOR_REPLACEMENTS_LOWER.get(key.lower())
    return _friendly_key(new_key) if new_key else _GENERIC_REMOVED_REPLACEMENT_FALLBACK


async def async_check_removed_entity(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: WeatherUpdateCoordinator,
    reg_entry: er.RegistryEntry,
) -> None:
    """Warn when a stale registry row about to be removed is still referenced.

    Call this immediately before ent_reg.async_remove() for any stale
    registry row a platform's setup is cleaning up (sensor or weather
    domain alike) — this is intentionally generic so it catches any
    0.9.x-era entity we delete, not just the sensors already tracked in
    DEPRECATED_SENSOR_REPLACEMENTS. When the deleted unique_id's key suffix
    matches a known replacement, the issue names it directly; otherwise it
    falls back to generic wording pointing at the release notes.

    Self-clearing: async_check_deprecated_entities sweeps for and deletes
    any removed_entity issue whose stored entity_id is no longer
    referenced, so self-corrected users see nothing.

    Wrapped in a broad except so a failure here can never block the
    removal itself or break setup.
    """
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


# ---------------------------------------------------------------------------
# Detector 3: removed weather forecast attributes (old issue #11)
# ---------------------------------------------------------------------------


def _raw_config_json(hass: HomeAssistant, entity_id: str) -> str | None:
    """Return a best-effort JSON dump of an automation/script's raw YAML config.

    Defensive by design: automation entities live in hass.data["automation"]
    and scripts in hass.data["script"] (both EntityComponent instances);
    any AttributeError/KeyError while reaching into the owning component
    degrades to "no config available" for this one reference rather than
    raising out of the detector.
    """
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
    """Warn when an automation/script still reads forecast_hourly/forecast_daily.

    v0.9.x exposed forecast_hourly and forecast_daily as weather-entity
    attributes (GH issue #11); both were removed in favour of the
    weather.get_forecasts action (HA's 2024.4 forecast direction). This
    scans the raw YAML of every automation/script referencing this entry's
    weather entity for either attribute name and raises a self-clearing
    repair issue pointing at weather.get_forecasts and the opt-in
    rain_next_8_hours/rain_next_24_hours sensors as ready-made replacements.

    Wrapped in a broad except so a failure here can never break setup.
    """
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
