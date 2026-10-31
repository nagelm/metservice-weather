"""Sensor platform for MetService weather."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, cast
from collections.abc import Callable
import datetime as dt
from homeassistant.util import dt as dt_util

from .helpers import safe_float as _safe_float, safe_int as _safe_int
from .sensor_states import (
    _FIRE_DANGER_OPTIONS,
    _FIRE_SEASON_OPTIONS,
    _MOON_PHASE_CURRENT_OPTIONS,
    _PRESSURE_TREND_OPTIONS,
    _UV_RISK_OPTIONS,
    _WIND_STRENGTH_OPTIONS,
    _fire_danger_state,
    _fire_season_state,
    _moon_phase_enum_state,
    _pressure_trend_state,
    _uv_alert_level_state,
    _wind_strength_state,
)
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
    MAX_LENGTH_STATE_STATE,
    PERCENTAGE,
    UnitOfTemperature,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfPrecipitationDepth,
)
from homeassistant.helpers.typing import StateType

_LOGGER = logging.getLogger(__name__)


def _next_tide_entry(data: list | None, tide_type: str) -> dict | None:
    """Return the next-upcoming tide entry dict of the given type, or None."""
    if not isinstance(data, list):
        return None
    now = dt_util.utcnow()
    for entry in data:
        if entry.get("type") == tide_type:
            t = dt_util.parse_datetime(entry["time"])
            if t is not None and t > now:
                return entry
    return None


def _next_tide_time(data: list | None, tide_type: str) -> dt.datetime | None:
    """Return the next upcoming tide time of the given type, or None if unavailable."""
    entry = _next_tide_entry(data, tide_type)
    if entry is None:
        return None
    return dt_util.parse_datetime(entry["time"])


def _tide_attrs(data: Any, tide_type: str) -> dict[str, StateType]:
    """Return height_m for the tide entry the value_fn selected."""
    entry = _next_tide_entry(data.tides, tide_type)
    return {"height_m": _safe_float(entry.get("height"))} if entry else {}


_TIDE_DIRECTION_BY_TYPE = {"HIGH": "rising", "LOW": "falling"}


def _next_tide_event(data: list | None) -> dict | None:
    """Return the next upcoming tide entry of either type, or None."""
    if not isinstance(data, list):
        return None
    now = dt_util.utcnow()
    for entry in data:
        if not isinstance(entry, dict):
            continue
        t = dt_util.parse_datetime(entry.get("time") or "")
        if t is not None and t > now:
            return entry
    return None


def _tide_direction_state(tides: list | None) -> str | None:
    """Direction the tide is moving: next event HIGH means rising, LOW falling."""
    entry = _next_tide_event(tides)
    if entry is None:
        return None
    return _TIDE_DIRECTION_BY_TYPE.get(entry.get("type"))


def _tide_table_attr(data: Any) -> dict[str, Any]:
    """Full-day tide table for the opt-in carrier sensor."""
    if not isinstance(data.tides, list) or not data.tides:
        return {}
    return {
        "tide_table": [
            {"type": t.get("type"), "time": t.get("time"), "height": t.get("height")}
            for t in data.tides
            if isinstance(t, dict)
        ]
    }


def _warning_severity(name: str) -> int:
    """Rank a MetService warning name: Red > Orange > other Warning > Watch."""
    lowered = name.lower()
    if re.search(r"\bred\b", lowered):
        return 3
    if re.search(r"\borange\b", lowered):
        return 2
    if "warning" in lowered:
        return 1
    return 0


def _warnings_severity_number(data: Any) -> int:
    """Numeric severity: 0 none / 1 watch / 2 warning / 3 orange / 4 red."""
    warnings = data.warnings_list
    if not warnings:
        return 0
    return 1 + max(_warning_severity(w.get("name", "")) for w in warnings)


def _warnings_state(data: Any) -> str:
    """Most severe warning name, with a (+N more) suffix when several are active."""
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


def _uv_attrs(data: Any) -> dict[str, StateType]:
    """Return UV detail attributes, populated only when the state itself mapped."""
    if _uv_alert_level_state(data.uv_alert_level) is None:
        return {}
    return {
        "alert_label": data.uv_alert_level,
        "status_class": data.uv_status_class,
        "advice": data.uv_message,
        "protection_window_start": data.uv_window_start_at or data.uv_window_start_raw,
        "protection_window_end": data.uv_window_end_at or data.uv_window_end_raw,
        "has_alert": data.uv_has_alert,
    }


def _long_text_state(text: str | None, fallback: str | None = None) -> str | None:
    """Fit MetService prose into HA's 255-character state limit."""
    if isinstance(text, str) and len(text) > MAX_LENGTH_STATE_STATE:
        return f"{text[: MAX_LENGTH_STATE_STATE - 3]}..."
    return text or fallback


def _full_text_attr(text: str | None) -> dict[str, StateType]:
    """Return full_description, present only when _long_text_state cut the text."""
    if isinstance(text, str) and len(text) > MAX_LENGTH_STATE_STATE:
        return {"full_description": text}
    return {}


def _has_observations(coordinator: Any) -> bool:
    """Location is not rural, so it has a weather station.

    A station location whose observations are missing from one response keeps
    its sensors; they read unknown until the data comes back.
    """
    return coordinator.data is not None and not coordinator.data.is_rural


def _has_breakdown(coordinator: Any) -> bool:
    """Morning/afternoon/evening/overnight sensors exist once there is data.

    They read unknown on a day the forecast carries no breakdown.
    """
    return coordinator.data is not None


def _tides_enabled(coordinator: Any) -> bool:
    return coordinator.enable_tides


def _boating_enabled(coordinator: Any) -> bool:
    return coordinator.enable_boating


def _surf_enabled(coordinator: Any) -> bool:
    return coordinator.enable_surf


@dataclass(frozen=True, kw_only=True)
class WeatherRequiredKeysMixin:
    """Mixin for required keys."""

    value_fn: Callable[[Any], StateType]


@dataclass(frozen=True, kw_only=True)
class WeatherSensorEntityDescription(SensorEntityDescription, WeatherRequiredKeysMixin):
    """Describes MetService Sensor entity."""

    attr_fn: Callable[[dict[str, Any]], dict[str, StateType]] = field(
        default=lambda _: {}
    )
    exists_fn: Callable[[Any], bool] = field(default=lambda _: True)
    seasonal: bool = False
    device: str = "location"


def _temperature(**kwargs: Any) -> WeatherSensorEntityDescription:
    """Describe a temperature measurement in metric units."""
    return WeatherSensorEntityDescription(
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=1,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        **kwargs,
    )


def _wind_speed(**kwargs: Any) -> WeatherSensorEntityDescription:
    """Describe a wind speed measurement in metric units."""
    return WeatherSensorEntityDescription(
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.WIND_SPEED,
        suggested_display_precision=1,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        **kwargs,
    )


def _rainfall(**kwargs: Any) -> WeatherSensorEntityDescription:
    """Describe a rainfall measurement in metric units."""
    return WeatherSensorEntityDescription(
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.PRECIPITATION,
        suggested_display_precision=1,
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        **kwargs,
    )


current_condition_sensor_descriptions_public = [
    WeatherSensorEntityDescription(
        key="validTimeLocal",
        translation_key="valid_time_local",
        name="Forecast issued",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: (
            dt.datetime.fromisoformat(data.issued_at)
            if isinstance(data.issued_at, str)
            else None
        ),
    ),
    WeatherSensorEntityDescription(
        key=FIELD_DESCRIPTION,
        translation_key="weather_description",
        name="Weather description",
        value_fn=lambda data: _long_text_state(data.forecast_text, "No description"),
        attr_fn=lambda data: _full_text_attr(data.forecast_text),
    ),
    WeatherSensorEntityDescription(
        key=FIELD_HUMIDITY,
        translation_key="relative_humidity",
        name="Relative humidity",
        exists_fn=_has_observations,
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda data: _safe_int(data.humidity),
    ),
    WeatherSensorEntityDescription(
        key="uv_risk",
        translation_key="uv_risk",
        name="UV index",
        seasonal=True,
        device_class=SensorDeviceClass.ENUM,
        options=_UV_RISK_OPTIONS,
        value_fn=lambda data: _uv_alert_level_state(data.uv_alert_level),
        attr_fn=_uv_attrs,
    ),
    WeatherSensorEntityDescription(
        key=FIELD_WINDDIR,
        translation_key="wind_direction",
        name="Wind direction",
        exists_fn=_has_observations,
        value_fn=lambda data: cast(str, data.wind_direction),
    ),
    _temperature(
        key="temperatureFeelsLike",
        translation_key="temperature_feels_like",
        name="Temperature feel",
        exists_fn=_has_observations,
        value_fn=lambda data: _safe_float(data.feels_like),
    ),
    _temperature(
        key=FIELD_TEMP,
        translation_key="temperature",
        name="Temperature",
        exists_fn=_has_observations,
        value_fn=lambda data: _safe_float(data.temperature),
    ),
    WeatherSensorEntityDescription(
        key=FIELD_PRESSURE,
        translation_key="pressure",
        name="Pressure",
        exists_fn=_has_observations,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.PRESSURE,
        suggested_display_precision=1,
        native_unit_of_measurement=UnitOfPressure.MBAR,
        value_fn=lambda data: _safe_float(data.pressure),
    ),
    _wind_speed(
        key=FIELD_WINDGUST,
        translation_key="wind_gust",
        name="Wind gust",
        exists_fn=_has_observations,
        value_fn=lambda data: _safe_float(data.wind_gust),
    ),
    _wind_speed(
        key=FIELD_WINDSPEED,
        translation_key="wind_speed",
        name="Wind speed",
        exists_fn=_has_observations,
        value_fn=lambda data: _safe_float(data.wind_speed),
    ),
    _rainfall(
        key="rainfall",
        translation_key="rainfall",
        name="Rain last hour",
        exists_fn=_has_observations,
        value_fn=lambda data: _safe_float(data.rainfall),
    ),
    _rainfall(
        key="rain_next_8_hours",
        translation_key="rain_next_8_hours",
        name="Rain next 8 hours",
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.rain_next_8h_mm,
    ),
    _rainfall(
        key="rain_next_24_hours",
        translation_key="rain_next_24_hours",
        name="Rain next 24 hours",
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.rain_next_24h_mm,
    ),
    WeatherSensorEntityDescription(
        key="next_rain_at",
        translation_key="next_rain_at",
        name="Next rain expected",
        entity_registry_enabled_default=False,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: (
            dt.datetime.fromisoformat(data.next_rain_at)
            if isinstance(data.next_rain_at, str)
            else None
        ),
        attr_fn=lambda data: {
            **(
                {"precision": data.next_rain_precision}
                if data.next_rain_precision
                else {}
            ),
            **(
                {
                    "outlook": (
                        "rain_expected" if data.next_rain_at else "no_rain_expected"
                    ),
                    "forecast_horizon": data.rain_forecast_horizon,
                }
                if data.rain_forecast_horizon
                else {}
            ),
        },
    ),
    WeatherSensorEntityDescription(
        key="pressure_trend",
        translation_key="pressure_trend",
        name="Pressure tendency",
        exists_fn=_has_observations,
        device_class=SensorDeviceClass.ENUM,
        options=_PRESSURE_TREND_OPTIONS,
        value_fn=lambda data: _pressure_trend_state(data.pressure_trend),
    ),
    WeatherSensorEntityDescription(
        key="pollen",
        translation_key="pollen",
        name="Pollen",
        device_class=SensorDeviceClass.ENUM,
        options=["none", "low", "moderate", "high"],
        value_fn=lambda data: data.pollen_state,
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
    WeatherSensorEntityDescription(
        key="warning_level",
        translation_key="warning_level",
        name="Warnings",
        device_class=SensorDeviceClass.ENUM,
        options=["none", "watch", "warning", "orange", "red"],
        value_fn=lambda data: _warnings_enum_state(data),
        attr_fn=lambda data: {
            "headline": _warnings_state(data),
            "count": len(data.warnings_list),
            "severity_level": _warnings_severity_number(data),
        },
    ),
    WeatherSensorEntityDescription(
        key="warning_details",
        translation_key="warning_details",
        name="Warning details",
        value_fn=lambda data: len(data.warnings_list),
        attr_fn=lambda data: {"active_warnings": data.warnings_list},
    ),
    WeatherSensorEntityDescription(
        key="fire_season_status",
        translation_key="fire_season_status",
        name="Fire season",
        seasonal=True,
        device_class=SensorDeviceClass.ENUM,
        options=_FIRE_SEASON_OPTIONS,
        value_fn=lambda data: _fire_season_state(data.fire_season_status),
        attr_fn=lambda data: (
            {"scope": data.fire_season_short, "detail": data.fire_season_text}
            if _fire_season_state(data.fire_season_status) is not None
            else {}
        ),
    ),
    WeatherSensorEntityDescription(
        key="fire_danger_level",
        translation_key="fire_danger_level",
        name="Fire danger",
        seasonal=True,
        device_class=SensorDeviceClass.ENUM,
        options=_FIRE_DANGER_OPTIONS,
        value_fn=lambda data: _fire_danger_state(
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
        name="Clothes drying morning",
        seasonal=True,
        value_fn=lambda data: (
            cast(str, data.drying_morning) if data.drying_morning else None
        ),
    ),
    WeatherSensorEntityDescription(
        key="drying_index_afternoon",
        translation_key="drying_index_afternoon",
        name="Clothes drying afternoon",
        seasonal=True,
        value_fn=lambda data: (
            cast(str, data.drying_afternoon) if data.drying_afternoon else None
        ),
    ),
    WeatherSensorEntityDescription(
        key="drying_next_good_day",
        translation_key="drying_next_good_day",
        name="Clothes drying next good day",
        seasonal=True,
        value_fn=lambda data: (
            cast(str, data.drying_next_good_day) if data.drying_next_good_day else None
        ),
    ),
    WeatherSensorEntityDescription(
        key="tides_high",
        translation_key="tides_high",
        name="Next high tide",
        exists_fn=_tides_enabled,
        device="marine",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: _next_tide_time(data.tides, "HIGH"),
        attr_fn=lambda data: _tide_attrs(data, "HIGH"),
    ),
    WeatherSensorEntityDescription(
        key="tides_low",
        translation_key="tides_low",
        name="Next low tide",
        exists_fn=_tides_enabled,
        device="marine",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: _next_tide_time(data.tides, "LOW"),
        attr_fn=lambda data: _tide_attrs(data, "LOW"),
    ),
    WeatherSensorEntityDescription(
        key="tide_direction",
        translation_key="tide_direction",
        name="Tide direction",
        entity_registry_enabled_default=False,
        exists_fn=_tides_enabled,
        device="marine",
        device_class=SensorDeviceClass.ENUM,
        options=["rising", "falling"],
        value_fn=lambda data: _tide_direction_state(data.tides),
        attr_fn=_tide_table_attr,
    ),
    WeatherSensorEntityDescription(
        key="boating_status",
        translation_key="boating_status",
        name="Boating conditions",
        exists_fn=_boating_enabled,
        device="marine",
        value_fn=lambda data: (
            cast(str, data.boating_status) if data.boating_status else None
        ),
    ),
    WeatherSensorEntityDescription(
        key="boating_forecast",
        translation_key="boating_forecast",
        name="Boating forecast",
        exists_fn=_boating_enabled,
        device="marine",
        value_fn=lambda data: _long_text_state(data.boating_forecast),
        attr_fn=lambda data: _full_text_attr(data.boating_forecast),
    ),
    WeatherSensorEntityDescription(
        key="surf_conditions",
        translation_key="surf_conditions",
        name="Surf conditions",
        exists_fn=_surf_enabled,
        device="marine",
        value_fn=lambda data: (
            cast(str, data.surf_conditions) if data.surf_conditions else None
        ),
    ),
    WeatherSensorEntityDescription(
        key="surf_rating",
        translation_key="surf_rating",
        name="Surf rating",
        exists_fn=_surf_enabled,
        device="marine",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda data: _safe_int(data.surf_rating),
    ),
    WeatherSensorEntityDescription(
        key="surf_wave_height",
        translation_key="surf_wave_height",
        name="Surf wave height",
        exists_fn=_surf_enabled,
        device="marine",
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.DISTANCE,
        suggested_display_precision=1,
        native_unit_of_measurement="m",
        value_fn=lambda data: _safe_float(data.surf_wave_height),
    ),
    WeatherSensorEntityDescription(
        key="surf_set_face",
        translation_key="surf_set_face",
        name="Surf set face",
        exists_fn=_surf_enabled,
        device="marine",
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.DISTANCE,
        suggested_display_precision=1,
        native_unit_of_measurement="m",
        value_fn=lambda data: _safe_float(data.surf_set_face),
    ),
    WeatherSensorEntityDescription(
        key="surf_swell_direction",
        translation_key="surf_swell_direction",
        name="Surf swell direction",
        exists_fn=_surf_enabled,
        device="marine",
        value_fn=lambda data: (
            cast(str, data.surf_swell_direction) if data.surf_swell_direction else None
        ),
    ),
    WeatherSensorEntityDescription(
        key="surf_swell_height",
        translation_key="surf_swell_height",
        name="Surf swell height",
        exists_fn=_surf_enabled,
        device="marine",
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.DISTANCE,
        suggested_display_precision=1,
        native_unit_of_measurement="m",
        value_fn=lambda data: _safe_float(data.surf_swell_height),
    ),
    WeatherSensorEntityDescription(
        key="surf_wind_direction",
        translation_key="surf_wind_direction",
        name="Surf wind direction",
        exists_fn=_surf_enabled,
        device="marine",
        value_fn=lambda data: (
            cast(str, data.surf_wind_direction) if data.surf_wind_direction else None
        ),
    ),
    WeatherSensorEntityDescription(
        key="surf_wind_speed",
        translation_key="surf_wind_speed",
        name="Surf wind speed",
        exists_fn=_surf_enabled,
        device="marine",
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.WIND_SPEED,
        suggested_display_precision=0,
        native_unit_of_measurement="kn",
        value_fn=lambda data: _safe_int(data.surf_wind_speed),
    ),
    WeatherSensorEntityDescription(
        key="surf_wind_gust",
        translation_key="surf_wind_gust",
        name="Surf wind gust",
        exists_fn=_surf_enabled,
        device="marine",
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.WIND_SPEED,
        suggested_display_precision=0,
        native_unit_of_measurement="kn",
        value_fn=lambda data: _safe_int(data.surf_wind_gust),
    ),
    WeatherSensorEntityDescription(
        key="surf_period",
        translation_key="surf_period",
        name="Surf period",
        exists_fn=_surf_enabled,
        device="marine",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        native_unit_of_measurement="s",
        value_fn=lambda data: _safe_int(data.surf_period),
    ),
    WeatherSensorEntityDescription(
        key="wind_strength_level",
        translation_key="wind_strength_level",
        name="Wind strength",
        exists_fn=_has_observations,
        device_class=SensorDeviceClass.ENUM,
        options=_WIND_STRENGTH_OPTIONS,
        value_fn=lambda data: _wind_strength_state(data.wind_strength),
    ),
    _temperature(
        key="temperature_today_high",
        translation_key="temperature_today_high",
        name="High temperature today",
        value_fn=lambda data: _safe_float(data.temp_today_high),
    ),
    _temperature(
        key="temperature_today_low",
        translation_key="temperature_today_low",
        name="Low temperature today",
        value_fn=lambda data: _safe_float(data.temp_today_low),
    ),
    WeatherSensorEntityDescription(
        key="condition_today",
        translation_key="condition_today",
        name="Condition today",
        value_fn=lambda data: cast(str, data.condition) if data.condition else None,
        attr_fn=lambda data: {
            "daily_conditions": [
                {
                    "date": entry.datetime[:10] if entry.datetime else None,
                    "condition": entry.condition,
                }
                for entry in data.daily_entries
                if entry.condition
            ]
        },
    ),
    WeatherSensorEntityDescription(
        key="tomorrow_condition",
        translation_key="tomorrow_condition",
        name="Condition tomorrow",
        value_fn=lambda data: (
            cast(str, data.tomorrow_condition) if data.tomorrow_condition else None
        ),
    ),
    _temperature(
        key="tomorrow_temp_high",
        translation_key="tomorrow_temp_high",
        name="High temperature tomorrow",
        value_fn=lambda data: _safe_float(data.tomorrow_temp_high),
    ),
    _temperature(
        key="tomorrow_temp_low",
        translation_key="tomorrow_temp_low",
        name="Low temperature tomorrow",
        value_fn=lambda data: _safe_float(data.tomorrow_temp_low),
    ),
    WeatherSensorEntityDescription(
        key="tomorrow_description",
        translation_key="tomorrow_description",
        name="Weather description tomorrow",
        value_fn=lambda data: _long_text_state(data.tomorrow_description),
        attr_fn=lambda data: _full_text_attr(data.tomorrow_description),
    ),
    WeatherSensorEntityDescription(
        key="breakdown_morning",
        translation_key="breakdown_morning",
        name="Condition morning",
        exists_fn=_has_breakdown,
        value_fn=lambda data: (
            cast(str, data.breakdown_morning) if data.breakdown_morning else None
        ),
    ),
    WeatherSensorEntityDescription(
        key="breakdown_afternoon",
        translation_key="breakdown_afternoon",
        name="Condition afternoon",
        exists_fn=_has_breakdown,
        value_fn=lambda data: (
            cast(str, data.breakdown_afternoon) if data.breakdown_afternoon else None
        ),
    ),
    WeatherSensorEntityDescription(
        key="breakdown_evening",
        translation_key="breakdown_evening",
        name="Condition evening",
        exists_fn=_has_breakdown,
        value_fn=lambda data: (
            cast(str, data.breakdown_evening) if data.breakdown_evening else None
        ),
    ),
    WeatherSensorEntityDescription(
        key="breakdown_overnight",
        translation_key="breakdown_overnight",
        name="Condition overnight",
        exists_fn=_has_breakdown,
        value_fn=lambda data: (
            cast(str, data.breakdown_overnight) if data.breakdown_overnight else None
        ),
    ),
    WeatherSensorEntityDescription(
        key="sunrise_at",
        translation_key="sunrise_at",
        name="Sunrise",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: (
            dt.datetime.fromisoformat(data.sunrise_at)
            if isinstance(data.sunrise_at, str)
            else None
        ),
        attr_fn=lambda data: {"display": data.sunrise} if data.sunrise else {},
    ),
    WeatherSensorEntityDescription(
        key="sunset_at",
        translation_key="sunset_at",
        name="Sunset",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: (
            dt.datetime.fromisoformat(data.sunset_at)
            if isinstance(data.sunset_at, str)
            else None
        ),
        attr_fn=lambda data: {"display": data.sunset} if data.sunset else {},
    ),
    WeatherSensorEntityDescription(
        key="moonrise_at",
        translation_key="moonrise_at",
        name="Moonrise",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: (
            dt.datetime.fromisoformat(data.moonrise_at)
            if isinstance(data.moonrise_at, str)
            else None
        ),
        attr_fn=lambda data: {"display": data.moonrise} if data.moonrise else {},
    ),
    WeatherSensorEntityDescription(
        key="moonset_at",
        translation_key="moonset_at",
        name="Moonset",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: (
            dt.datetime.fromisoformat(data.moonset_at)
            if isinstance(data.moonset_at, str)
            else None
        ),
        attr_fn=lambda data: {"display": data.moonset} if data.moonset else {},
    ),
    WeatherSensorEntityDescription(
        key="moon_phase_current",
        translation_key="moon_phase_current",
        name="Moon phase",
        device_class=SensorDeviceClass.ENUM,
        options=_MOON_PHASE_CURRENT_OPTIONS,
        value_fn=lambda data: data.moon_phase_current,
        attr_fn=lambda data: {
            **(
                {"next_phase": _moon_phase_enum_state(data.moon_phase)}
                if _moon_phase_enum_state(data.moon_phase) is not None
                else {}
            ),
            **(
                {"next_phase_at": data.moon_phase_date}
                if isinstance(data.moon_phase_date, str)
                else {}
            ),
        },
    ),
]
