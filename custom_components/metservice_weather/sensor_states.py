"""Map MetService's raw values onto the states the enum sensors publish."""

from __future__ import annotations

import logging

_LOGGER = logging.getLogger(__name__)


def _warn_once(logged: set[str], category: str, raw: str) -> None:
    """Log one warning per runtime per unmapped raw value in a category."""
    if raw in logged:
        return
    logged.add(raw)
    _LOGGER.warning(
        "Unknown MetService %s %r — please report at "
        "https://github.com/nagelm/metservice-weather/issues",
        category,
        raw,
    )


_UV_ALERT_LEVEL_MAP: dict[str, str] = {
    "low": "low",
    "moderate": "moderate",
    "high": "high",
    "very high": "very_high",
    "extreme": "extreme",
}

_UV_ALERT_LEVEL_PREFIXES: tuple[tuple[str, str], ...] = (
    ("not dangerous", "not_dangerous"),
    ("dangerous today from", "dangerous_later"),
    ("dangerous from", "dangerous_later"),
    ("dangerous", "dangerous"),
)

_UV_RISK_OPTIONS = [
    "low",
    "moderate",
    "high",
    "very_high",
    "extreme",
    "not_dangerous",
    "dangerous_later",
    "dangerous",
]

_UNKNOWN_UV_ALERT_LEVELS_LOGGED: set[str] = set()


def _uv_alert_level_state(raw: str | None) -> str | None:
    """Map MetService's uvAlertLevel label to the uv_risk ENUM sensor's state."""
    if not raw:
        return None
    key = raw.strip().lower()
    mapped = _UV_ALERT_LEVEL_MAP.get(key)
    if mapped is None:
        mapped = next(
            (
                state
                for prefix, state in _UV_ALERT_LEVEL_PREFIXES
                if key.startswith(prefix)
            ),
            None,
        )
    if mapped is None:
        _warn_once(_UNKNOWN_UV_ALERT_LEVELS_LOGGED, "UV alert level", raw)
        return None
    return mapped


_PRESSURE_TREND_OPTIONS = ["rising", "falling", "stable"]

_UNKNOWN_PRESSURE_TREND_LOGGED: set[str] = set()


def _pressure_trend_state(raw: str | None) -> str | None:
    """Map the raw observations pressure trend to its ENUM state."""
    if not raw:
        return None
    key = raw.strip().lower()
    if key in _PRESSURE_TREND_OPTIONS:
        return key
    _warn_once(_UNKNOWN_PRESSURE_TREND_LOGGED, "pressure trend", raw)
    return None


_WIND_STRENGTH_MAP: dict[str, str] = {
    "calm": "calm",
    "light winds": "light_winds",
    "moderate": "moderate",
    "fresh": "fresh",
    "strong": "strong",
    "gale": "gale",
    "severe gale": "severe_gale",
    "storm": "storm",
}

_WIND_STRENGTH_OPTIONS = [
    "calm",
    "light_winds",
    "moderate",
    "fresh",
    "strong",
    "gale",
    "severe_gale",
    "storm",
]

_UNKNOWN_WIND_STRENGTH_LOGGED: set[str] = set()


def _wind_strength_state(raw: str | None) -> str | None:
    """Map the raw observations wind strength label to its ENUM state."""
    if not raw:
        return None
    mapped = _WIND_STRENGTH_MAP.get(raw.strip().lower())
    if mapped is None:
        _warn_once(_UNKNOWN_WIND_STRENGTH_LOGGED, "wind strength", raw)
        return None
    return mapped


_FIRE_SEASON_OPTIONS = ["open", "restricted", "prohibited"]

_UNKNOWN_FIRE_SEASON_LOGGED: set[str] = set()


def _fire_season_state(raw: str | None) -> str | None:
    """Map the raw fire season status to its ENUM state."""
    if not raw:
        return None
    key = raw.strip().lower()
    if key in _FIRE_SEASON_OPTIONS:
        return key
    _warn_once(_UNKNOWN_FIRE_SEASON_LOGGED, "fire season status", raw)
    return None


_FIRE_DANGER_INDEX_MAP: dict[int, str] = {
    1: "low",
    2: "moderate",
    3: "high",
    4: "very_high",
    5: "extreme",
}

_FIRE_DANGER_OPTIONS = ["low", "moderate", "high", "very_high", "extreme"]

_UNKNOWN_FIRE_DANGER_LOGGED: set[str] = set()

_FIRE_DANGER_LABEL_DRIFT_LOGGED: set[str] = set()


def _fire_danger_state(index: int | None, label: str | None) -> str | None:
    """Map fire danger to its ENUM state: index is primary, label a fallback."""
    if index is not None:
        mapped = _FIRE_DANGER_INDEX_MAP.get(index)
        if mapped is not None:
            if (
                label
                and label.strip().lower().replace(" ", "_") != mapped
                and label not in _FIRE_DANGER_LABEL_DRIFT_LOGGED
            ):
                _FIRE_DANGER_LABEL_DRIFT_LOGGED.add(label)
                _LOGGER.warning(
                    "MetService fire danger label %r doesn't match its index "
                    "%s (%s) — please report at "
                    "https://github.com/nagelm/metservice-weather/issues",
                    label,
                    index,
                    mapped,
                )
            return mapped
        _warn_once(_UNKNOWN_FIRE_DANGER_LOGGED, "fire danger index", str(index))
        return None
    if label:
        candidate = label.strip().lower().replace(" ", "_")
        if candidate in _FIRE_DANGER_OPTIONS:
            return candidate
        _warn_once(_UNKNOWN_FIRE_DANGER_LOGGED, "fire danger label", label)
        return None
    return None


_MOON_PHASE_ENUM_MAP: dict[str, str] = {
    "NEW": "new",
    "FIRST": "first_quarter",
    "FULL": "full",
    "LAST": "last_quarter",
}

_UNKNOWN_MOON_PHASE_LOGGED: set[str] = set()

_MOON_PHASE_CURRENT_OPTIONS = [
    "new_moon",
    "waxing_crescent",
    "first_quarter",
    "waxing_gibbous",
    "full_moon",
    "waning_gibbous",
    "last_quarter",
    "waning_crescent",
]


def _moon_phase_enum_state(raw: str | None) -> str | None:
    """Map the raw NEW/FIRST/FULL/LAST phase token to its ENUM state."""
    if not raw:
        return None
    mapped = _MOON_PHASE_ENUM_MAP.get(raw)
    if mapped is None:
        _warn_once(_UNKNOWN_MOON_PHASE_LOGGED, "moon phase", raw)
        return None
    return mapped
