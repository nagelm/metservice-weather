"""Sensor platform for MetService weather."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, cast
from collections.abc import Callable
import datetime
from homeassistant.util import dt as dt_util

from .helpers import safe_float as _safe_float, safe_int as _safe_int
from .const import (
    FIELD_DESCRIPTION,
    FIELD_HUMIDITY,
    FIELD_PRESSURE,
    FIELD_TEMP,
    FIELD_WINDDIR,
    FIELD_WINDGUST,
    FIELD_WINDSPEED,
)
from homeassistant.components.sensor import (
    SensorEntityDescription,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    UnitOfTemperature,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfPrecipitationDepth,
)
from homeassistant.helpers.typing import StateType

_LOGGER = logging.getLogger(__name__)


_MOON_PHASE_NAMES: dict[str, str] = {
    "NEW": "New Moon",
    "FIRST": "First Quarter",
    "FULL": "Full Moon",
    "LAST": "Last Quarter",
}


def _warn_once(logged: set[str], category: str, raw: str) -> None:
    """Log one warning per runtime per unmapped raw value in a category.

    HA raises if an ENUM sensor reports a state outside its declared
    `options`, so every raw-value → enum mapping in this module must fall
    back to None on an unrecognised value instead of passing it through —
    this is the shared "tell us about it once" side effect for that path.
    """
    if raw in logged:
        return
    logged.add(raw)
    _LOGGER.warning(
        "Unknown MetService %s %r — please report at "
        "https://github.com/nagelm/metservice-weather/issues",
        category,
        raw,
    )


def _next_tide_entry(data: list | None, tide_type: str) -> dict | None:
    """Return the next-upcoming tide entry dict of the given type, or None.

    Shared by the tide sensors' value_fn (via _next_tide_time) and attr_fn
    (_tide_attrs) so the selected entry can never diverge between the two.
    """
    if not isinstance(data, list):
        return None
    now = dt_util.utcnow()
    for entry in data:
        if entry.get("type") == tide_type:
            t = dt_util.parse_datetime(entry["time"])
            if t is not None and t > now:
                return entry
    return None


def _next_tide_time(data: list | None, tide_type: str) -> datetime.datetime | None:
    """Return the next upcoming tide time of the given type, or None if unavailable."""
    entry = _next_tide_entry(data, tide_type)
    if entry is None:
        return None
    return dt_util.parse_datetime(entry["time"])


def _tide_attrs(data: Any, tide_type: str) -> dict[str, StateType]:
    """Return height_m for the tide entry the value_fn selected."""
    entry = _next_tide_entry(data.tides, tide_type)
    return {"height_m": _safe_float(entry.get("height"))} if entry else {}


def _warning_severity(name: str) -> int:
    """Rank a MetService warning name: Red > Orange > other Warning > Watch."""
    lowered = name.lower()
    if "red" in lowered:
        return 3
    if "orange" in lowered:
        return 2
    if "warning" in lowered:
        return 1
    return 0


def _warnings_state(data: Any) -> str:
    """Most severe warning name, with a (+N more) suffix when several are active.

    Used as the headline state of the deprecated weather_warnings sensor and
    as the "headline" attribute on the warning_level ENUM sensor — kept as
    its own helper (rather than inlined) so its 255-char truncation stays
    independently testable.
    """
    warnings = data.warnings_list
    if not warnings:
        return "No warnings"
    top = max(warnings, key=lambda w: _warning_severity(w.get("name", "")))
    extra = len(warnings) - 1
    state = top.get("name") or "Warning"
    if extra:
        state = f"{state} (+{extra} more)"
    return state[:255]


_WARNING_ENUM_BY_RANK: dict[int, str] = {
    0: "watch",
    1: "warning",
    2: "orange",
    3: "red",
}


def _warnings_enum_state(data: Any) -> str:
    """Return the top-ranked active warning as an enum state, or "none" when clear."""
    warnings = data.warnings_list
    if not warnings:
        return "none"
    top_rank = max(_warning_severity(w.get("name", "")) for w in warnings)
    return _WARNING_ENUM_BY_RANK[top_rank]


# ---------------------------------------------------------------------------
# UV alert level
# ---------------------------------------------------------------------------

_UV_ALERT_LEVEL_MAP: dict[str, str] = {
    "low": "low",
    "moderate": "moderate",
    "high": "high",
    "very high": "very_high",
    "extreme": "extreme",
}
_UNKNOWN_UV_ALERT_LEVELS_LOGGED: set[str] = set()


def _uv_alert_level_state(raw: str | None) -> str | None:
    """Map MetService's uvAlertLevel label to the uv_risk ENUM sensor's state."""
    if not raw:
        return None
    mapped = _UV_ALERT_LEVEL_MAP.get(raw.strip().lower())
    if mapped is None:
        _warn_once(_UNKNOWN_UV_ALERT_LEVELS_LOGGED, "UV alert level", raw)
        return None
    return mapped


def _uv_attrs(data: Any) -> dict[str, StateType]:
    """Return UV detail attributes, populated only when the state itself mapped.

    status_class is the one upstream field independent of the state's source
    label; its in-season vocabulary is unverified, so it stays exposed until
    a summer capture shows whether it carries anything the state doesn't.
    """
    if _uv_alert_level_state(data.uv_alert_level) is None:
        return {}
    return {
        "status_class": data.uv_status_class,
        "advice": data.uv_message,
        "protection_window_start": data.uv_window_start_at or data.uv_window_start_raw,
        "protection_window_end": data.uv_window_end_at or data.uv_window_end_raw,
        "has_alert": data.uv_has_alert,
    }


# ---------------------------------------------------------------------------
# Pressure tendency trend
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Wind strength
# ---------------------------------------------------------------------------

# Live MetService values observed to date: "Light winds", "Moderate", "Fresh".
# The remaining entries are the plausible rest of MetService's Beaufort-style
# scale, included defensively; unknown raw values warn once and read unknown.
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


# ---------------------------------------------------------------------------
# Fire season / fire danger
# ---------------------------------------------------------------------------

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
            # The state comes from the index; the label is expected to mirror
            # it. If NIWA ever pairs a richer wording with a known index the
            # enum would silently drop it — warn so it gets reported instead.
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


# ---------------------------------------------------------------------------
# Moon phase
# ---------------------------------------------------------------------------

_MOON_PHASE_ENUM_OPTIONS = ["new", "first_quarter", "full", "last_quarter"]
_MOON_PHASE_ENUM_MAP: dict[str, str] = {
    "NEW": "new",
    "FIRST": "first_quarter",
    "FULL": "full",
    "LAST": "last_quarter",
}
_UNKNOWN_MOON_PHASE_LOGGED: set[str] = set()

# HA core's moon-phase ENUM vocabulary, used by the moon_phase_current
# sensor. Values are derived in the normalizer (coordinator_types.py); this
# module only declares them as the ENUM sensor's options.
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
    """Map the raw NEW/FIRST/FULL/LAST phase token to its ENUM state.

    The API publishes only the next principal phase event, so these four
    tokens are the entire vocabulary; anything else is unrecognised.
    """
    if not raw:
        return None
    mapped = _MOON_PHASE_ENUM_MAP.get(raw)
    if mapped is None:
        _warn_once(_UNKNOWN_MOON_PHASE_LOGGED, "moon phase", raw)
        return None
    return mapped


def _has_observations(coordinator: Any) -> bool:
    """Location has a weather station (rural pages have none)."""
    return coordinator.data is not None and coordinator.data.has_observations


def _has_breakdown(coordinator: Any) -> bool:
    """Location's forecast carries morning/afternoon/evening/overnight conditions."""
    return coordinator.data is not None and coordinator.data.has_breakdown


def _tides_enabled(coordinator: Any) -> bool:
    return coordinator.enable_tides


def _boating_enabled(coordinator: Any) -> bool:
    return coordinator.enable_boating


def _surf_enabled(coordinator: Any) -> bool:
    return coordinator.enable_surf


@dataclass(frozen=True, kw_only=True)
class WeatherRequiredKeysMixin:
    """Mixin for required keys."""

    value_fn: Callable[[dict[str, Any], str], StateType]


@dataclass(frozen=True, kw_only=True)
class WeatherSensorEntityDescription(SensorEntityDescription, WeatherRequiredKeysMixin):
    """Describes MetService Sensor entity."""

    attr_fn: Callable[[dict[str, Any]], dict[str, StateType]] = field(
        default=lambda _: {}
    )
    unit_fn: Callable[[bool], str | None] = field(default=lambda _: None)
    # Receives the WeatherUpdateCoordinator; return False to skip creating
    # this entity for the configured location.
    exists_fn: Callable[[Any], bool] = field(default=lambda _: True)
    # Seasonal products are server-stripped part of the year; never
    # structurally gated via exists_fn.
    seasonal: bool = False
    # Which device registry entry this sensor is grouped under: "location"
    # (default) is the town/rural page device; "marine" is the separate
    # device for tide/boating/surf sensors, which describe the selected
    # marine region rather than the town. See entity.py's MetServiceEntity.
    device: str = "location"


current_condition_sensor_descriptions_public = [
    WeatherSensorEntityDescription(
        key="validTimeLocal",
        translation_key="valid_time_local",
        name="Forecast Description Updated Time",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data, _: (
            datetime.datetime.fromisoformat(data.issued_at)
            if isinstance(data.issued_at, str)
            else None
        ),
    ),
    WeatherSensorEntityDescription(
        key=FIELD_DESCRIPTION,
        translation_key="weather_description",
        name="Weather Description",
        value_fn=lambda data, _: (
            f"{data.forecast_text[:252]}..."
            if isinstance(data.forecast_text, str) and len(data.forecast_text) > 255
            else (data.forecast_text or "No description")
        ),
        attr_fn=lambda data: (
            {"full_description": data.forecast_text}
            if isinstance(data.forecast_text, str) and len(data.forecast_text) > 255
            else {}
        ),
    ),
    WeatherSensorEntityDescription(
        key=FIELD_HUMIDITY,
        translation_key="relative_humidity",
        name="Relative Humidity",
        exists_fn=_has_observations,
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        unit_fn=lambda _: PERCENTAGE,
        value_fn=lambda data, _: _safe_int(data.humidity),
    ),
    # Deprecated — superseded by uv_risk; keeps its v2026.7.0 behaviour for existing installs.
    WeatherSensorEntityDescription(
        key="uvIndex",
        translation_key="uv_index",
        name="UV Index (deprecated)",
        seasonal=True,
        entity_registry_enabled_default=False,
        entity_registry_visible_default=False,
        value_fn=lambda data, _: cast(
            str, data.uv_index.replace("status-", "") if data.uv_index else None
        ),
    ),
    WeatherSensorEntityDescription(
        key="uv_risk",
        translation_key="uv_risk",
        name="UV Index",
        seasonal=True,
        device_class=SensorDeviceClass.ENUM,
        options=["low", "moderate", "high", "very_high", "extreme"],
        value_fn=lambda data, _: _uv_alert_level_state(data.uv_alert_level),
        attr_fn=_uv_attrs,
    ),
    WeatherSensorEntityDescription(
        key=FIELD_WINDDIR,
        translation_key="wind_direction",
        name="Wind Direction",
        exists_fn=_has_observations,
        value_fn=lambda data, _: cast(str, data.wind_direction),
    ),
    WeatherSensorEntityDescription(
        key="temperatureFeelsLike",
        translation_key="temperature_feels_like",
        name="Temperature - Feels Like",
        exists_fn=_has_observations,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=1,
        unit_fn=lambda metric: (
            UnitOfTemperature.CELSIUS if metric else UnitOfTemperature.FAHRENHEIT
        ),
        value_fn=lambda data, _: _safe_float(data.feels_like),
    ),
    WeatherSensorEntityDescription(
        key=FIELD_TEMP,
        translation_key="temperature",
        name="Temperature",
        exists_fn=_has_observations,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=1,
        unit_fn=lambda metric: (
            UnitOfTemperature.CELSIUS if metric else UnitOfTemperature.FAHRENHEIT
        ),
        value_fn=lambda data, _: _safe_float(data.temperature),
    ),
    WeatherSensorEntityDescription(
        key=FIELD_PRESSURE,
        translation_key="pressure",
        name="Pressure",
        exists_fn=_has_observations,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.PRESSURE,
        suggested_display_precision=1,
        unit_fn=lambda metric: UnitOfPressure.MBAR if metric else UnitOfPressure.INHG,
        value_fn=lambda data, _: _safe_float(data.pressure),
    ),
    WeatherSensorEntityDescription(
        key=FIELD_WINDGUST,
        translation_key="wind_gust",
        name="Wind Gust",
        exists_fn=_has_observations,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.WIND_SPEED,
        suggested_display_precision=1,
        unit_fn=lambda metric: (
            UnitOfSpeed.KILOMETERS_PER_HOUR if metric else UnitOfSpeed.MILES_PER_HOUR
        ),
        value_fn=lambda data, _: _safe_float(data.wind_gust),
    ),
    WeatherSensorEntityDescription(
        key=FIELD_WINDSPEED,
        translation_key="wind_speed",
        name="Wind Speed",
        exists_fn=_has_observations,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.WIND_SPEED,
        suggested_display_precision=1,
        unit_fn=lambda metric: (
            UnitOfSpeed.KILOMETERS_PER_HOUR if metric else UnitOfSpeed.MILES_PER_HOUR
        ),
        value_fn=lambda data, _: _safe_float(data.wind_speed),
    ),
    WeatherSensorEntityDescription(
        key="rainfall",
        translation_key="rainfall",
        name="Rainfall",
        exists_fn=_has_observations,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.PRECIPITATION,
        suggested_display_precision=1,
        unit_fn=lambda _: UnitOfPrecipitationDepth.MILLIMETERS,
        value_fn=lambda data, _: _safe_float(data.rainfall),
    ),
    # --- Rain windows (summed from the forecast hourly slice) ---
    WeatherSensorEntityDescription(
        key="rain_next_8_hours",
        translation_key="rain_next_8_hours",
        name="Rain — Next 8 Hours",
        entity_registry_enabled_default=False,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.PRECIPITATION,
        suggested_display_precision=1,
        unit_fn=lambda _: UnitOfPrecipitationDepth.MILLIMETERS,
        value_fn=lambda data, _: data.rain_next_8h_mm,
    ),
    WeatherSensorEntityDescription(
        key="rain_next_24_hours",
        translation_key="rain_next_24_hours",
        name="Rain — Next 24 Hours",
        entity_registry_enabled_default=False,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.PRECIPITATION,
        suggested_display_precision=1,
        unit_fn=lambda _: UnitOfPrecipitationDepth.MILLIMETERS,
        value_fn=lambda data, _: data.rain_next_24h_mm,
    ),
    WeatherSensorEntityDescription(
        key="next_rain_at",
        translation_key="next_rain_at",
        name="Next Rain Expected",
        entity_registry_enabled_default=False,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data, _: (
            datetime.datetime.fromisoformat(data.next_rain_at)
            if isinstance(data.next_rain_at, str)
            else None
        ),
    ),
    # Deprecated — superseded by pressure_trend; keeps its v2026.7.0 behaviour for existing installs.
    WeatherSensorEntityDescription(
        key="pressureTendencyTrend",
        translation_key="pressure_tendency_trend",
        name="Pressure Tendency Trend (deprecated)",
        exists_fn=_has_observations,
        entity_registry_enabled_default=False,
        entity_registry_visible_default=False,
        value_fn=lambda data, _: cast(str, data.pressure_trend),
    ),
    WeatherSensorEntityDescription(
        key="pressure_trend",
        translation_key="pressure_trend",
        name="Pressure Tendency Trend",
        exists_fn=_has_observations,
        device_class=SensorDeviceClass.ENUM,
        options=_PRESSURE_TREND_OPTIONS,
        value_fn=lambda data, _: _pressure_trend_state(data.pressure_trend),
    ),
    WeatherSensorEntityDescription(
        key="pollen",
        translation_key="pollen",
        name="Pollen",
        device_class=SensorDeviceClass.ENUM,
        options=["none", "low", "moderate", "high"],
        value_fn=lambda data, _: data.pollen_state,
        attr_fn=lambda data: (
            {
                **{
                    f"{level}_allergens": ", ".join(data.pollen_active.get(level, []))
                    for level in ("low", "moderate", "high")
                    if data.pollen_active.get(level)
                },
                **(
                    {"imminent_allergens": ", ".join(data.pollen_imminent)}
                    if data.pollen_imminent
                    else {}
                ),
            }
            if data.pollen_state is not None
            else {}
        ),
    ),
    # Deprecated — superseded by pollen; keeps its v2026.7.0 behaviour for existing installs.
    WeatherSensorEntityDescription(
        key="pollen_levels",
        translation_key="pollen_levels",
        name="Pollen Levels (deprecated)",
        entity_registry_enabled_default=False,
        entity_registry_visible_default=False,
        value_fn=lambda data, _: cast(str, data.pollen_level),
    ),
    # Deprecated — superseded by pollen; keeps its v2026.7.0 behaviour for existing installs.
    WeatherSensorEntityDescription(
        key="pollen_type",
        translation_key="pollen_type",
        name="Pollen Type (deprecated)",
        entity_registry_enabled_default=False,
        entity_registry_visible_default=False,
        value_fn=lambda data, _: (
            cast(
                str,
                ". ".join(
                    i.capitalize()
                    for i in data.pollen_type.lstrip(" ")[0:254].split(". ")
                ),
            )
            if data.pollen_type
            else None
        ),
    ),
    # Deprecated — superseded by warning_level; keeps its v2026.7.0 behaviour for existing installs.
    WeatherSensorEntityDescription(
        key="weather_warnings",
        translation_key="weather_warnings",
        name="MetService Weather Warnings (deprecated)",
        entity_registry_enabled_default=False,
        entity_registry_visible_default=False,
        value_fn=lambda data, _: (
            (data.weather_warnings[:252] + "...")
            if len(data.weather_warnings) > 255
            else data.weather_warnings
        ),
        attr_fn=lambda data: {"warnings": data.weather_warnings},
    ),
    WeatherSensorEntityDescription(
        key="warning_level",
        translation_key="warning_level",
        name="MetService Weather Warnings",
        device_class=SensorDeviceClass.ENUM,
        options=["none", "watch", "warning", "orange", "red"],
        value_fn=lambda data, _: _warnings_enum_state(data),
        attr_fn=lambda data: {
            "headline": _warnings_state(data),
            "count": len(data.warnings_list),
            "warnings": data.warnings_list,
        },
    ),
    # Deprecated — superseded by fire_season_status; keeps its v2026.7.0 behaviour for existing installs.
    WeatherSensorEntityDescription(
        key="fire_season",
        translation_key="fire_season",
        name="Fire Season (deprecated)",
        seasonal=True,
        entity_registry_enabled_default=False,
        entity_registry_visible_default=False,
        value_fn=lambda data, _: cast(str, data.fire_season),
    ),
    WeatherSensorEntityDescription(
        key="fire_season_status",
        translation_key="fire_season_status",
        name="Fire Season",
        seasonal=True,
        device_class=SensorDeviceClass.ENUM,
        options=_FIRE_SEASON_OPTIONS,
        value_fn=lambda data, _: _fire_season_state(data.fire_season_status),
        attr_fn=lambda data: (
            {"scope": data.fire_season_short, "detail": data.fire_season_text}
            if _fire_season_state(data.fire_season_status) is not None
            else {}
        ),
    ),
    # Deprecated — superseded by fire_danger_level; keeps its v2026.7.0 behaviour for existing installs.
    WeatherSensorEntityDescription(
        key="fire_danger",
        translation_key="fire_danger",
        name="Fire Danger (deprecated)",
        seasonal=True,
        entity_registry_enabled_default=False,
        entity_registry_visible_default=False,
        value_fn=lambda data, _: cast(str, data.fire_danger),
    ),
    WeatherSensorEntityDescription(
        key="fire_danger_level",
        translation_key="fire_danger_level",
        name="Fire Danger",
        seasonal=True,
        device_class=SensorDeviceClass.ENUM,
        options=_FIRE_DANGER_OPTIONS,
        value_fn=lambda data, _: _fire_danger_state(
            data.fire_danger_index, data.fire_danger
        ),
        attr_fn=lambda data: (
            {
                "index": data.fire_danger_index,
                "guidance": data.fire_danger_text,
                "tomorrow": data.fire_danger_forecast,
            }
            if _fire_danger_state(data.fire_danger_index, data.fire_danger) is not None
            else {}
        ),
    ),
    WeatherSensorEntityDescription(
        key="drying_index_morning",
        translation_key="drying_index_morning",
        name="Clothes Drying Time - Morning",
        seasonal=True,
        value_fn=lambda data, _: (
            cast(str, data.drying_morning) if data.drying_morning else None
        ),
    ),
    WeatherSensorEntityDescription(
        key="drying_index_afternoon",
        translation_key="drying_index_afternoon",
        name="Clothes Drying Time - Afternoon",
        seasonal=True,
        value_fn=lambda data, _: (
            cast(str, data.drying_afternoon) if data.drying_afternoon else None
        ),
    ),
    WeatherSensorEntityDescription(
        key="drying_next_good_day",
        translation_key="drying_next_good_day",
        name="Clothes Drying - Next Good Day",
        seasonal=True,
        value_fn=lambda data, _: (
            cast(str, data.drying_next_good_day) if data.drying_next_good_day else None
        ),
    ),
    WeatherSensorEntityDescription(
        key="tides_high",
        translation_key="tides_high",
        name="Next High Tide",
        exists_fn=_tides_enabled,
        device="marine",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data, _: _next_tide_time(data.tides, "HIGH"),
        attr_fn=lambda data: _tide_attrs(data, "HIGH"),
    ),
    WeatherSensorEntityDescription(
        key="tides_low",
        translation_key="tides_low",
        name="Next Low Tide",
        exists_fn=_tides_enabled,
        device="marine",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data, _: _next_tide_time(data.tides, "LOW"),
        attr_fn=lambda data: _tide_attrs(data, "LOW"),
    ),
    WeatherSensorEntityDescription(
        key="boating_status",
        translation_key="boating_status",
        name="Boating Conditions",
        exists_fn=_boating_enabled,
        device="marine",
        value_fn=lambda data, _: (
            cast(str, data.boating_status) if data.boating_status else None
        ),
    ),
    WeatherSensorEntityDescription(
        key="boating_forecast",
        translation_key="boating_forecast",
        name="Boating Forecast",
        exists_fn=_boating_enabled,
        device="marine",
        value_fn=lambda data, _: (
            f"{data.boating_forecast[:252]}..."
            if isinstance(data.boating_forecast, str)
            and len(data.boating_forecast) > 255
            else (data.boating_forecast or None)
        ),
    ),
    # --- Surf (from regional surf page marker data) ---
    WeatherSensorEntityDescription(
        key="surf_conditions",
        translation_key="surf_conditions",
        name="Surf Conditions",
        exists_fn=_surf_enabled,
        device="marine",
        value_fn=lambda data, _: (
            cast(str, data.surf_conditions) if data.surf_conditions else None
        ),
    ),
    WeatherSensorEntityDescription(
        key="surf_rating",
        translation_key="surf_rating",
        name="Surf Rating",
        exists_fn=_surf_enabled,
        device="marine",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda data, _: _safe_int(data.surf_rating),
    ),
    WeatherSensorEntityDescription(
        key="surf_wave_height",
        translation_key="surf_wave_height",
        name="Surf Wave Height",
        exists_fn=_surf_enabled,
        device="marine",
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.DISTANCE,
        suggested_display_precision=1,
        unit_fn=lambda _: "m",
        value_fn=lambda data, _: _safe_float(data.surf_wave_height),
    ),
    WeatherSensorEntityDescription(
        key="surf_set_face",
        translation_key="surf_set_face",
        name="Surf Set Face",
        exists_fn=_surf_enabled,
        device="marine",
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.DISTANCE,
        suggested_display_precision=1,
        unit_fn=lambda _: "m",
        value_fn=lambda data, _: _safe_float(data.surf_set_face),
    ),
    WeatherSensorEntityDescription(
        key="surf_swell_direction",
        translation_key="surf_swell_direction",
        name="Surf Swell Direction",
        exists_fn=_surf_enabled,
        device="marine",
        value_fn=lambda data, _: (
            cast(str, data.surf_swell_direction) if data.surf_swell_direction else None
        ),
    ),
    WeatherSensorEntityDescription(
        key="surf_swell_height",
        translation_key="surf_swell_height",
        name="Surf Swell Height",
        exists_fn=_surf_enabled,
        device="marine",
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.DISTANCE,
        suggested_display_precision=1,
        unit_fn=lambda _: "m",
        value_fn=lambda data, _: _safe_float(data.surf_swell_height),
    ),
    WeatherSensorEntityDescription(
        key="surf_wind_direction",
        translation_key="surf_wind_direction",
        name="Surf Wind Direction",
        exists_fn=_surf_enabled,
        device="marine",
        value_fn=lambda data, _: (
            cast(str, data.surf_wind_direction) if data.surf_wind_direction else None
        ),
    ),
    WeatherSensorEntityDescription(
        key="surf_wind_speed",
        translation_key="surf_wind_speed",
        name="Surf Wind Speed",
        exists_fn=_surf_enabled,
        device="marine",
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.WIND_SPEED,
        suggested_display_precision=0,
        unit_fn=lambda _: "kn",
        value_fn=lambda data, _: _safe_int(data.surf_wind_speed),
    ),
    WeatherSensorEntityDescription(
        key="surf_wind_gust",
        translation_key="surf_wind_gust",
        name="Surf Wind Gust",
        exists_fn=_surf_enabled,
        device="marine",
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.WIND_SPEED,
        suggested_display_precision=0,
        unit_fn=lambda _: "kn",
        value_fn=lambda data, _: _safe_int(data.surf_wind_gust),
    ),
    WeatherSensorEntityDescription(
        key="surf_period",
        translation_key="surf_period",
        name="Surf Period",
        exists_fn=_surf_enabled,
        device="marine",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        unit_fn=lambda _: "s",
        value_fn=lambda data, _: _safe_int(data.surf_period),
    ),
    # --- Wind and clothing (from currentConditions module) ---
    # Deprecated — superseded by wind_strength_level; keeps its v2026.7.0 behaviour for existing installs.
    WeatherSensorEntityDescription(
        key="wind_strength",
        translation_key="wind_strength",
        name="Wind Strength (deprecated)",
        exists_fn=_has_observations,
        entity_registry_enabled_default=False,
        entity_registry_visible_default=False,
        value_fn=lambda data, _: (
            cast(str, data.wind_strength) if data.wind_strength else None
        ),
    ),
    WeatherSensorEntityDescription(
        key="wind_strength_level",
        translation_key="wind_strength_level",
        name="Wind Strength",
        exists_fn=_has_observations,
        device_class=SensorDeviceClass.ENUM,
        options=_WIND_STRENGTH_OPTIONS,
        value_fn=lambda data, _: _wind_strength_state(data.wind_strength),
    ),
    WeatherSensorEntityDescription(
        key="temperature_today_high",
        translation_key="temperature_today_high",
        name="Today's High Temperature",
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=1,
        unit_fn=lambda metric: (
            UnitOfTemperature.CELSIUS if metric else UnitOfTemperature.FAHRENHEIT
        ),
        value_fn=lambda data, _: _safe_float(data.temp_today_high),
    ),
    WeatherSensorEntityDescription(
        key="temperature_today_low",
        translation_key="temperature_today_low",
        name="Today's Low Temperature",
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=1,
        unit_fn=lambda metric: (
            UnitOfTemperature.CELSIUS if metric else UnitOfTemperature.FAHRENHEIT
        ),
        value_fn=lambda data, _: _safe_float(data.temp_today_low),
    ),
    # --- Tomorrow's forecast (injected from 7-day data) ---
    WeatherSensorEntityDescription(
        key="tomorrow_condition",
        translation_key="tomorrow_condition",
        name="Tomorrow — Condition",
        value_fn=lambda data, _: (
            cast(str, data.tomorrow_condition) if data.tomorrow_condition else None
        ),
    ),
    WeatherSensorEntityDescription(
        key="tomorrow_temp_high",
        translation_key="tomorrow_temp_high",
        name="Tomorrow — High Temperature",
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=1,
        unit_fn=lambda metric: (
            UnitOfTemperature.CELSIUS if metric else UnitOfTemperature.FAHRENHEIT
        ),
        value_fn=lambda data, _: _safe_float(data.tomorrow_temp_high),
    ),
    WeatherSensorEntityDescription(
        key="tomorrow_temp_low",
        translation_key="tomorrow_temp_low",
        name="Tomorrow — Low Temperature",
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=1,
        unit_fn=lambda metric: (
            UnitOfTemperature.CELSIUS if metric else UnitOfTemperature.FAHRENHEIT
        ),
        value_fn=lambda data, _: _safe_float(data.tomorrow_temp_low),
    ),
    WeatherSensorEntityDescription(
        key="tomorrow_description",
        translation_key="tomorrow_description",
        name="Tomorrow — Description",
        value_fn=lambda data, _: (
            f"{data.tomorrow_description[:252]}..."
            if isinstance(data.tomorrow_description, str)
            and len(data.tomorrow_description) > 255
            else (data.tomorrow_description or None)
        ),
    ),
    # --- Sub-day condition breakdown (from twoDayForecast module) ---
    WeatherSensorEntityDescription(
        key="breakdown_morning",
        translation_key="breakdown_morning",
        name="Today — Morning Condition",
        exists_fn=_has_breakdown,
        value_fn=lambda data, _: (
            cast(str, data.breakdown_morning) if data.breakdown_morning else None
        ),
    ),
    WeatherSensorEntityDescription(
        key="breakdown_afternoon",
        translation_key="breakdown_afternoon",
        name="Today — Afternoon Condition",
        exists_fn=_has_breakdown,
        value_fn=lambda data, _: (
            cast(str, data.breakdown_afternoon) if data.breakdown_afternoon else None
        ),
    ),
    WeatherSensorEntityDescription(
        key="breakdown_evening",
        translation_key="breakdown_evening",
        name="Today — Evening Condition",
        exists_fn=_has_breakdown,
        value_fn=lambda data, _: (
            cast(str, data.breakdown_evening) if data.breakdown_evening else None
        ),
    ),
    WeatherSensorEntityDescription(
        key="breakdown_overnight",
        translation_key="breakdown_overnight",
        name="Today — Overnight Condition",
        exists_fn=_has_breakdown,
        value_fn=lambda data, _: (
            cast(str, data.breakdown_overnight) if data.breakdown_overnight else None
        ),
    ),
    # --- Sun and moon (from sunAndMoon module) ---
    # Deprecated — superseded by sunrise_at; keeps its v2026.7.0 behaviour for existing installs.
    WeatherSensorEntityDescription(
        key="sunrise",
        translation_key="sunrise",
        name="Sunrise (deprecated)",
        entity_registry_enabled_default=False,
        entity_registry_visible_default=False,
        value_fn=lambda data, _: cast(str, data.sunrise) if data.sunrise else None,
    ),
    WeatherSensorEntityDescription(
        key="sunrise_at",
        translation_key="sunrise_at",
        name="Sunrise",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data, _: (
            datetime.datetime.fromisoformat(data.sunrise_at)
            if isinstance(data.sunrise_at, str)
            else None
        ),
        attr_fn=lambda data: {"display": data.sunrise} if data.sunrise else {},
    ),
    # Deprecated — superseded by sunset_at; keeps its v2026.7.0 behaviour for existing installs.
    WeatherSensorEntityDescription(
        key="sunset",
        translation_key="sunset",
        name="Sunset (deprecated)",
        entity_registry_enabled_default=False,
        entity_registry_visible_default=False,
        value_fn=lambda data, _: cast(str, data.sunset) if data.sunset else None,
    ),
    WeatherSensorEntityDescription(
        key="sunset_at",
        translation_key="sunset_at",
        name="Sunset",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data, _: (
            datetime.datetime.fromisoformat(data.sunset_at)
            if isinstance(data.sunset_at, str)
            else None
        ),
        attr_fn=lambda data: {"display": data.sunset} if data.sunset else {},
    ),
    # Deprecated — superseded by moonrise_at; keeps its v2026.7.0 behaviour for existing installs.
    WeatherSensorEntityDescription(
        key="moonrise",
        translation_key="moonrise",
        name="Moonrise (deprecated)",
        entity_registry_enabled_default=False,
        entity_registry_visible_default=False,
        value_fn=lambda data, _: cast(str, data.moonrise) if data.moonrise else None,
    ),
    WeatherSensorEntityDescription(
        key="moonrise_at",
        translation_key="moonrise_at",
        name="Moonrise",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data, _: (
            datetime.datetime.fromisoformat(data.moonrise_at)
            if isinstance(data.moonrise_at, str)
            else None
        ),
        attr_fn=lambda data: {"display": data.moonrise} if data.moonrise else {},
    ),
    # Deprecated — superseded by moonset_at; keeps its v2026.7.0 behaviour for existing installs.
    WeatherSensorEntityDescription(
        key="moonset",
        translation_key="moonset",
        name="Moonset (deprecated)",
        entity_registry_enabled_default=False,
        entity_registry_visible_default=False,
        value_fn=lambda data, _: cast(str, data.moonset) if data.moonset else None,
    ),
    WeatherSensorEntityDescription(
        key="moonset_at",
        translation_key="moonset_at",
        name="Moonset",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data, _: (
            datetime.datetime.fromisoformat(data.moonset_at)
            if isinstance(data.moonset_at, str)
            else None
        ),
        attr_fn=lambda data: {"display": data.moonset} if data.moonset else {},
    ),
    # Deprecated — superseded by next_moon_phase; keeps its v2026.7.0 behaviour for existing installs.
    WeatherSensorEntityDescription(
        key="moon_phase",
        translation_key="moon_phase",
        name="Moon Phase (deprecated)",
        entity_registry_enabled_default=False,
        entity_registry_visible_default=False,
        value_fn=lambda data, _: (
            _MOON_PHASE_NAMES.get(
                cast(str, data.moon_phase), cast(str, data.moon_phase)
            )
            if data.moon_phase
            else None
        ),
        attr_fn=lambda data: {"raw_phase": data.moon_phase} if data.moon_phase else {},
    ),
    WeatherSensorEntityDescription(
        key="next_moon_phase",
        # Opt-in: superseded as a default by the current-phase Moon Phase
        # sensor; enable on the device page if the next-event view is wanted.
        entity_registry_enabled_default=False,
        translation_key="next_moon_phase",
        name="Next Moon Phase",
        device_class=SensorDeviceClass.ENUM,
        options=_MOON_PHASE_ENUM_OPTIONS,
        value_fn=lambda data, _: _moon_phase_enum_state(data.moon_phase),
    ),
    WeatherSensorEntityDescription(
        key="moon_phase_current",
        translation_key="moon_phase_current",
        name="Moon Phase",
        device_class=SensorDeviceClass.ENUM,
        options=_MOON_PHASE_CURRENT_OPTIONS,
        value_fn=lambda data, _: data.moon_phase_current,
    ),
    WeatherSensorEntityDescription(
        key="moon_phase_date",
        # Opt-in: superseded as a default by the current-phase Moon Phase
        # sensor; enable on the device page if the next-event view is wanted.
        entity_registry_enabled_default=False,
        translation_key="moon_phase_date",
        name="Next Moon Phase Date",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data, _: (
            datetime.datetime.fromisoformat(data.moon_phase_date)
            if isinstance(data.moon_phase_date, str)
            else None
        ),
    ),
]
