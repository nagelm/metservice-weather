"""Repair issues for entities/entries deprecated across the v0.9.x -> v1.0+, v2026.7.1, and v2026.9.0 transitions.

Five retroactive, evidence-driven detectors live here (a sixth,
legacy-entry, lives in __init__.py since it runs before any coordinator
exists):

* Deprecated sensors (historical) — every sensor key whose state format
  changed in v2026.7.1 was forked: the OLD key kept its v2026.7.0 behaviour
  and a NEW sibling sensor carried the new behaviour. The 14 OLD
  descriptions were removed outright in v2026.9.0 (see
  weather_current_conditions_sensors.py) — any registry row for one of them
  is now just an ordinary stale row, cleaned up by sensor.py's
  async_setup_entry stale-registry sweep like any other (with
  async_check_removed_entity, below, raising a repair first if it's still
  referenced). async_check_deprecated_entities therefore no longer runs a
  disable/hide usage sweep — it only clears any deprecated_entity /
  deprecated_sweep_v2 / hidden_deprecated issues an earlier integration
  version may have left behind, then hands off to the removed-entity sweep
  and the entity-ID reclaim detector below.
* Removed entity still referenced — generic catch for ANY 0.9.x-era or
  2026.9.0-deprecated entity a stale-registry cleanup is about to delete
  (sensor or weather domain), not just the sensors tracked below.
* Removed forecast attributes — v0.9.x exposed forecast_hourly/
  forecast_daily as weather-entity attributes; both were removed in
  favour of the weather.get_forecasts action.
* Marine device move — tide/boating/surf sensors moved off the shared
  location device onto their own marine device. entity_id references are
  unaffected, but a DEVICE-based automation trigger/condition/action built
  against the old location device silently stops working for anything
  marine-related, since the device it targets no longer owns those
  entities.
* Entity-ID reclaim — a replacement sensor that couldn't mint its
  canonical entity_id at v2026.7.1 (because a still-present deprecated
  sensor's registry row already held it) got a suffixed id instead (e.g.
  `sensor.napier_moon_phase_2`). Now that the deprecated sensors are gone,
  the canonical id may be free; this is the one FIXABLE issue in the
  integration — see async_check_entity_id_reclaim and repairs.py.

All are warning/error severity except the fixable entity-ID reclaim issue,
self-clearing once the underlying condition stops being true, and wrapped
so a failure in any of them can never break setup.

`async_merge_entity_options` below is the shared read-merge-write helper
behind every entry.options[DOMAIN] write in the integration — currently
only sensor.py's seasonal-disable stamp for CONF_AUTO_HIDE_SEASONAL, kept
here as a small, self-contained registry-options helper other detectors
may still want.

`_usage_signals` — the broad, multi-source usage detector originally built
for the (now-removed) deprecated-sensor disable/hide sweep — is kept and
reused by the entity-ID reclaim detector's "is anything still referencing
the old, suffixed entity_id" check: renaming an entity_id is a more
consequential, automatic action than hiding a sensor, so it deserves the
broadest evidence gathering available (automations, scripts, scenes,
groups, dashboards, other integrations' config entries, voice exposure,
HomeKit, even an in-process listener) before the fix flow is allowed to
just go ahead and rename it.
"""

from __future__ import annotations

import json
import logging
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
    "moon_phase": "moon_phase_current",
    "moon_phase_date": "moon_phase_current",
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

# Explicit display names for every replacement sensor key in
# DEPRECATED_SENSOR_REPLACEMENTS.values(), sourced from the name= field of
# that successor's WeatherSensorEntityDescription in
# weather_current_conditions_sensors.py. _friendly_key's mechanical
# snake_case -> Title Case conversion diverges from several real display
# names (e.g. uv_risk's sensor is named "UV index", not "Uv Risk"; moon_phase's
# replacement, moon_phase_current, is named "Moon phase"), so this map is
# the source of truth for repair-issue replacement text.
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
    """Return a human-readable form of a snake_case replacement sensor key.

    Fallback only — _REPLACEMENT_DISPLAY_NAMES is the source of truth for
    every key in DEPRECATED_SENSOR_REPLACEMENTS.values(); this mechanical
    conversion covers any key that map doesn't (yet) have an entry for.
    """
    return " ".join(
        word.upper() if word == "uv" else word.capitalize() for word in key.split("_")
    )


def _replacement_display_name(key: str) -> str:
    """Return the replacement sensor's display name for repair-issue text."""
    return _REPLACEMENT_DISPLAY_NAMES.get(key, _friendly_key(key))


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


# ---------------------------------------------------------------------------
# Usage detector for the deprecated-sensor disable/hide sweep
# ---------------------------------------------------------------------------

# hass.data key holding HA core's private, undocumented
# async_track_state_change_event bookkeeping. Reaching into this is a
# best-effort, conservative veto only: current core stores a small
# dataclass here (not a plain dict), so the isinstance guard below means
# this signal is inert on it — but it costs nothing to keep, and picks up
# a live signal again for free if a future/older core version's shape
# happens to be a plain dict keyed by entity_id.
_TRACK_STATE_CHANGE_DATA_KEY = "track_state_change_data"


def _dump_json(value: Any) -> str | None:
    """Best-effort JSON dump for substring matching; None on failure.

    Never logged or persisted anywhere — only ever substring-tested against
    an entity_id and then discarded.
    """
    try:
        return json.dumps(value, default=str)
    except (TypeError, ValueError):
        return None


def _config_entries_referencing(hass: HomeAssistant, entity_id: str) -> list[str]:
    """Return "{domain}: {title}" for other integrations' entries that mention entity_id.

    Covers template/derivative/utility_meter/min_max/statistics-style
    helpers built through a config entry, and any other integration that
    happens to store the entity_id in its entry data/options. Our own
    entries and HomeKit are excluded — HomeKit gets its own explicit
    "homekit" signal (see _homekit_includes) since that's more meaningful
    to a user than a generic "homekit: <bridge name>" helper line. Each
    entry is independently guarded so one malformed entry can't hide
    evidence from another.
    """
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
    """Return True when a HomeKit config entry's options mention entity_id.

    Covers an explicit include_entities filter entry. Each HomeKit entry is
    independently guarded.
    """
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
    """Best-effort check for an in-process state-change listener on entity_id.

    See _TRACK_STATE_CHANGE_DATA_KEY's docstring — the isinstance guard
    means an unexpected (or simply different-version) shape safely
    contributes no signal instead of raising.
    """
    callbacks = hass.data.get(_TRACK_STATE_CHANGE_DATA_KEY)
    if isinstance(callbacks, dict):
        return bool(callbacks.get(entity_id))
    return False


async def _dashboards_referencing(hass: HomeAssistant, entity_id: str) -> list[str]:
    """Return a title/url_path for every Lovelace dashboard whose config mentions entity_id.

    Only runs once "lovelace" has loaded. LOVELACE_DATA's exact storage
    location has moved before across HA versions; imported defensively
    here with a fallback to the plain "lovelace" string key so this keeps
    working either way (in current core LOVELACE_DATA is a HassKey that
    compares equal to that string regardless). Each dashboard's
    async_load() is independently guarded — it can raise (e.g.
    ConfigNotFound for a strategy dashboard) or return falsy, either of
    which simply contributes no evidence from that one dashboard.
    """
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
    """Return a dict of usage evidence for entity_id; an empty dict means UNUSED.

    Far broader than _referencing_items (automations/scripts only), which
    still backs the other detectors in this module unchanged. Every source
    is independently wrapped in try/except: a source that fails (missing
    component, private API shape changed, entity unknown to a helper,
    etc.) simply contributes no signal, the same fail-open behaviour
    _referencing_items already relies on for automations/scripts.

    Possible keys: "automations", "scripts", "scenes", "groups"
    (list[str] entity/service ids), "dashboards", "helpers", "voice"
    (list[str] human-readable evidence), "homekit", "listeners" (bool).
    """
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
    """Render a usage-signals dict as a concise, semicolon-joined evidence summary.

    List-valued sources (automations/scripts/scenes/groups/dashboards/
    helpers/voice) are rendered as "<label>: <joined items>", mirroring the
    entity_id list style the old "references" placeholder used. The two
    boolean sources (homekit, listeners) contribute a fixed phrase instead,
    since they carry no list of their own to join.
    """
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
    """Merge changes into a registry entry's DOMAIN-scoped options.

    entity_registry.async_update_entity_options replaces a domain's whole
    options dict on every call, so every write against entry.options[DOMAIN]
    goes through this helper instead of calling that API directly: it reads
    the entry's current DOMAIN options, applies `updates` on top, drops any
    `remove_keys`, and writes the merged result back. That matters because
    more than one concern can share the same entry.options[DOMAIN] mapping
    over an entity's lifetime — currently sensor.py's seasonal-disable stamp
    ({"seasonal_disabled": True}) for CONF_AUTO_HIDE_SEASONAL — and going
    through the read-merge-write here is what stops one concern's write from
    clobbering another's keys. A no-op if the entity has no registry row.
    """
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
    """Clear obsolete pre-2026.9.0 deprecation issues, then run the follow-on detectors.

    The 14 deprecated sensor descriptions this function used to run a
    disable/hide usage sweep over no longer exist as of v2026.9.0 (see
    weather_current_conditions_sensors.py) — any registry row for one of
    them is now an ordinary stale row, cleaned up by sensor.py's
    async_setup_entry stale-registry sweep before this function is even
    called. There is therefore nothing left for a sweep to decide here.
    This function instead:

    1. Clears any deprecated_entity / deprecated_sweep_v2 / hidden_deprecated
       issues an earlier integration version may have left in the issue
       registry for this entry (ir.async_delete_issue is idempotent, so
       this is a no-op once they're gone).
    2. Sweeps and self-clears any "removed_entity" issue (detector 1, below)
       for this entry whose stored entity_id is no longer referenced —
       self-corrected users see nothing.
    3. Runs the entity-ID reclaim detector (async_check_entity_id_reclaim,
       below), which is independently exception-guarded.

    Wrapped in a broad except so a failure in this best-effort check can
    never break sensor setup.
    """
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
    return (
        _replacement_display_name(new_key)
        if new_key
        else _GENERIC_REMOVED_REPLACEMENT_FALLBACK
    )


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


# ---------------------------------------------------------------------------
# Detector 4: marine sensors moved to their own device
# ---------------------------------------------------------------------------

# The 14 tide/boating/surf sensor keys, derived from the descriptions
# themselves (device="marine") rather than hand-duplicated here, so this
# stays in sync automatically if the marine sensor set ever changes. Also
# asserted against directly in test_sensor.py.
_MARINE_SENSOR_KEYS: frozenset[str] = frozenset(
    description.key
    for description in current_condition_sensor_descriptions_public
    if description.device == "marine"
)

# Fallback tokens for flagging a device-automation whose raw_config doesn't
# literally contain one of this entry's marine entity_ids (e.g. it isn't
# registered, or the automation only stores a device_id + trigger
# type/subtype rather than a full entity_id) but still clearly targets
# something marine, based on the unique-id key vocabulary used across the
# marine sensors.
_MARINE_REFERENCE_TOKENS: tuple[str, ...] = ("tides_high", "surf_", "boating_")


def _device_referencing_items(hass: HomeAssistant, device_id: str) -> list[str]:
    """Return automation/script entity_ids with a trigger/condition/action on device_id.

    Mirrors _referencing_items, but for DEVICE-based automation references
    instead of entity-based ones — each owning component is only queried
    once loaded, since calling automations_with_device/scripts_with_device
    before the component is set up raises.
    """
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
    """Warn when a DEVICE-based automation/script still targets the old location device for marine sensors.

    Tide, boating, and surf sensors used to live on the shared location
    device; they now live on their own marine device (see entity.py's
    MetServiceEntity). Unique IDs and entity_ids are unchanged, so an
    entity_id-based trigger/condition/action keeps working untouched — but
    a DEVICE-based one recorded against the old location device silently
    stops covering those entities, since HA re-homes the registry rows to
    the new device without updating any automation.

    Only called when this entry has at least one marine service configured
    (see sensor.py); also self-clears if that configuration is later
    removed entirely, since there is then no meaningful marine device to
    point users at. Every automation/script referencing the location
    DEVICE is a candidate; a candidate is only flagged if its raw YAML
    config also mentions one of this entry's marine entity_ids, or a
    marine unique-key token, so unrelated device-automations (e.g. one
    that triggers off the same device's temperature sensor) stay silent.

    Wrapped in a broad except so a failure in this best-effort check can
    never break setup.
    """
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
        device = dev_reg.async_get_device(identifiers={(DOMAIN, coordinator.location)})
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


# ---------------------------------------------------------------------------
# Detector 5: entity-ID reclaim (the one FIXABLE issue — see repairs.py)
# ---------------------------------------------------------------------------

# Every replacement sensor key from DEPRECATED_SENSOR_REPLACEMENTS.values(),
# resolved to its live WeatherSensorEntityDescription — used to read the
# replacement's display name= for both the canonical object_id computation
# and the issue's sensor_name placeholder. Built once at import time from
# the same list sensor.py builds entities from, so it stays in sync
# automatically if a replacement sensor's name= ever changes.
_REPLACEMENT_DESCRIPTIONS_BY_KEY: dict[str, WeatherSensorEntityDescription] = {
    description.key: description
    for description in current_condition_sensor_descriptions_public
}


def _reclaim_issue_id(entry_id: str, key: str) -> str:
    """Return the fixable entity_id_reclaim issue_id for a replacement key."""
    return f"entity_id_reclaim_{entry_id}_{key}"


def _reclaim_referenced_issue_id(entry_id: str, key: str) -> str:
    """Return the non-fixable entity_id_reclaim_referenced issue_id for a replacement key."""
    return f"entity_id_reclaim_referenced_{entry_id}_{key}"


def _clear_reclaim_issues(hass: HomeAssistant, entry_id: str, key: str) -> None:
    """Delete both the fixable and non-fixable reclaim issue variants for key.

    Called for every short-circuit ("nothing to reclaim right now") branch
    in async_check_entity_id_reclaim, so a key that was previously flagged
    self-clears the instant the underlying condition stops being true —
    row removed, already canonical, or the canonical id got taken by
    something else in the meantime.
    """
    ir.async_delete_issue(hass, DOMAIN, _reclaim_issue_id(entry_id, key))
    ir.async_delete_issue(hass, DOMAIN, _reclaim_referenced_issue_id(entry_id, key))


async def async_check_entity_id_reclaim(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: WeatherUpdateCoordinator,
) -> None:
    """Offer to rename a replacement sensor onto its now-free canonical entity_id.

    Context: on installs that upgraded through v2026.7.1 while still on an
    earlier integration version, a replacement sensor could sometimes not
    mint its canonical entity_id because the deprecated sensor's registry
    row already held it — so it got a suffixed id instead (e.g.
    `sensor.napier_moon_phase_2`). Now that the deprecated set is removed
    (v2026.9.0), the canonical id may be free.

    For every DISTINCT replacement key in DEPRECATED_SENSOR_REPLACEMENTS's
    values (moon_phase/moon_phase_date both point at moon_phase_current,
    pollen_levels/pollen_type both point at pollen — each is only checked
    once):

    1. Resolve the replacement's own registry row via its unique_id
       (`f"{coordinator.location}_{key}".lower()`, sensor domain). No row
       (location doesn't have this sensor, or setup hasn't added it yet)
       -> self-clear and skip.
    2. Compute the canonical object_id: `slugify(f"{device_name}
       {description.name}")`, where device_name is the row's device's
       display name (name_by_user, falling back to name) and
       description.name is the replacement's own name= in
       weather_current_conditions_sensors.py — the same recipe HA's entity
       platform uses to mint an entity_id from has_entity_name +
       original_name. No device row, or the row's object_id already equals
       the canonical one -> self-clear and skip.
    3. The canonical entity_id (`sensor.<canonical_object_id>`) must be
       FREE (no registry row already holds it) -> self-clear and skip
       otherwise; renaming onto an occupied id would collide.
    4. Referenced check on the CURRENT (suffixed) entity_id, via the same
       broad, multi-source _usage_signals detector the old deprecated-
       sensor sweep used (automations, scripts, scenes, groups,
       dashboards, other integrations' config entries, voice exposure,
       HomeKit, an in-process listener) — a much higher bar than plain
       automation/script references, appropriate for an action (automatic
       rename) more consequential than hiding a sensor:
       * Not referenced -> a FIXABLE, WARNING-severity entity_id_reclaim
         issue is created/refreshed, naming the current and new entity_id
         and the sensor's display name. Its one-step confirm fix flow
         (repairs.py) performs the rename via
         er.async_update_entity(..., new_entity_id=...) when submitted.
       * Referenced -> a non-fixable, WARNING-severity
         entity_id_reclaim_referenced issue is created/refreshed instead,
         listing the evidence found and explaining that renaming here
         would silently break those references (Home Assistant only
         rewrites automations for UI-driven renames) — the user has to
         rename it by hand once they've dealt with the references.

    Every run, whichever issue variant no longer applies to a key is
    deleted, so a key flips cleanly between "fixable", "referenced", and
    "nothing to reclaim" as its underlying state changes.

    Wrapped in a broad except so a failure in this best-effort check can
    never break sensor setup.
    """
    try:
        ent_reg = er.async_get(hass)
        dev_reg = dr.async_get(hass)

        for key in sorted(set(DEPRECATED_SENSOR_REPLACEMENTS.values())):
            description = _REPLACEMENT_DESCRIPTIONS_BY_KEY.get(key)
            if description is None:
                _clear_reclaim_issues(hass, entry.entry_id, key)
                continue

            unique_id = f"{coordinator.location}_{key}".lower()
            entity_id = ent_reg.async_get_entity_id("sensor", DOMAIN, unique_id)
            if entity_id is None:
                _clear_reclaim_issues(hass, entry.entry_id, key)
                continue

            reg_entry = ent_reg.async_get(entity_id)
            if reg_entry is None:
                _clear_reclaim_issues(hass, entry.entry_id, key)
                continue

            device = (
                dev_reg.async_get(reg_entry.device_id) if reg_entry.device_id else None
            )
            device_name = (device.name_by_user or device.name) if device else None
            if not device_name:
                _clear_reclaim_issues(hass, entry.entry_id, key)
                continue

            canonical_object_id = slugify(f"{device_name} {description.name}")
            current_object_id = entity_id.split(".", 1)[1]
            if current_object_id == canonical_object_id:
                _clear_reclaim_issues(hass, entry.entry_id, key)
                continue

            canonical_entity_id = f"sensor.{canonical_object_id}"
            if ent_reg.async_get(canonical_entity_id) is not None:
                _clear_reclaim_issues(hass, entry.entry_id, key)
                continue

            signals = await _usage_signals(hass, entity_id)
            placeholders = {
                "current_entity_id": entity_id,
                "new_entity_id": canonical_entity_id,
                "sensor_name": description.name,
            }

            if not signals:
                ir.async_delete_issue(
                    hass, DOMAIN, _reclaim_referenced_issue_id(entry.entry_id, key)
                )
                ir.async_create_issue(
                    hass,
                    DOMAIN,
                    _reclaim_issue_id(entry.entry_id, key),
                    is_fixable=True,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key="entity_id_reclaim",
                    learn_more_url=_LEARN_MORE_URL,
                    translation_placeholders=placeholders,
                    data={
                        "current_entity_id": entity_id,
                        "new_entity_id": canonical_entity_id,
                    },
                )
            else:
                ir.async_delete_issue(
                    hass, DOMAIN, _reclaim_issue_id(entry.entry_id, key)
                )
                ir.async_create_issue(
                    hass,
                    DOMAIN,
                    _reclaim_referenced_issue_id(entry.entry_id, key),
                    is_fixable=False,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key="entity_id_reclaim_referenced",
                    learn_more_url=_LEARN_MORE_URL,
                    translation_placeholders={
                        **placeholders,
                        "references": _format_evidence(signals),
                    },
                )
    except Exception:
        _LOGGER.debug(
            "Entity-ID reclaim repair check failed; continuing without it",
            exc_info=True,
        )
