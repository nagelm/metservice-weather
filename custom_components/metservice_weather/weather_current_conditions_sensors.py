"""Sensor platform for MetService weather."""

from __future__ import annotations

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


_MOON_PHASE_NAMES: dict[str, str] = {
    "NEW": "New Moon",
    "FIRST": "First Quarter",
    "FULL": "Full Moon",
    "LAST": "Last Quarter",
}



def _next_tide_time(data: list | None, tide_type: str) -> datetime.datetime | None:
    """Return the next upcoming tide of the given type, or None if unavailable."""
    if not isinstance(data, list):
        return None
    now = dt_util.utcnow()
    for entry in data:
        if entry.get("type") == tide_type:
            t = dt_util.parse_datetime(entry["time"])
            if t is not None and t > now:
                return t
    return None

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

    attr_fn: Callable[[dict[str, Any]], dict[str, StateType]] = field(default=lambda _: {})
    unit_fn: Callable[[bool], str | None] = field(default=lambda _: None)
    # Receives the WeatherUpdateCoordinator; return False to skip creating
    # this entity for the configured location.
    exists_fn: Callable[[Any], bool] = field(default=lambda _: True)


current_condition_sensor_descriptions_public = [
    WeatherSensorEntityDescription(
        key="validTimeLocal",
        translation_key="valid_time_local",
        name="Forecast Description Updated Time",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data, _: datetime.datetime.fromisoformat(data.issued_at)
        if isinstance(data.issued_at, str)
        else None,
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
        attr_fn=lambda data: {"full_description": data.forecast_text}
        if isinstance(data.forecast_text, str) and data.forecast_text
        else {},
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
    WeatherSensorEntityDescription(
        key="uvIndex",
        translation_key="uv_index",
        name="UV Index",
        value_fn=lambda data, _: cast(
            str, data.uv_index.replace("status-", "") if data.uv_index else None
        ),
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
        unit_fn=lambda metric: UnitOfTemperature.CELSIUS
        if metric
        else UnitOfTemperature.FAHRENHEIT,
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
        unit_fn=lambda metric: UnitOfTemperature.CELSIUS
        if metric
        else UnitOfTemperature.FAHRENHEIT,
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
        unit_fn=lambda metric: UnitOfSpeed.KILOMETERS_PER_HOUR
        if metric
        else UnitOfSpeed.MILES_PER_HOUR,
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
        unit_fn=lambda metric: UnitOfSpeed.KILOMETERS_PER_HOUR
        if metric
        else UnitOfSpeed.MILES_PER_HOUR,
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
    WeatherSensorEntityDescription(
        key="pressureTendencyTrend",
        translation_key="pressure_tendency_trend",
        name="Pressure Tendency Trend",
        exists_fn=_has_observations,
        value_fn=lambda data, _: cast(str, data.pressure_trend),
    ),
    WeatherSensorEntityDescription(
        key="pollen_levels",
        translation_key="pollen_levels",
        name="Pollen Levels",
        value_fn=lambda data, _: cast(str, data.pollen_level),
    ),
    WeatherSensorEntityDescription(
        key="pollen_type",
        translation_key="pollen_type",
        name="Pollen Type",
        value_fn=lambda data, _: cast(
            str,
            ". ".join(
                i.capitalize()
                for i in data.pollen_type.lstrip(" ")[0:254].split(". ")
            ),
        )
        if data.pollen_type
        else None,
    ),
    WeatherSensorEntityDescription(
        key="weather_warnings",
        translation_key="weather_warnings",
        name="MetService Weather Warnings",
        value_fn=lambda data, _: (
            (data.weather_warnings[:252] + "...")
            if len(data.weather_warnings) > 255
            else data.weather_warnings
        ),
        attr_fn=lambda data: {"warnings": data.weather_warnings},
    ),
    WeatherSensorEntityDescription(
        key="fire_season",
        translation_key="fire_season",
        name="Fire Season",
        value_fn=lambda data, _: cast(str, data.fire_season),
    ),
    WeatherSensorEntityDescription(
        key="fire_danger",
        translation_key="fire_danger",
        name="Fire Danger",
        value_fn=lambda data, _: cast(str, data.fire_danger),
    ),
    WeatherSensorEntityDescription(
        key="drying_index_morning",
        translation_key="drying_index_morning",
        name="Clothes Drying Time - Morning",
        value_fn=lambda data, _: cast(str, data.drying_morning) if data.drying_morning else None,
    ),
    WeatherSensorEntityDescription(
        key="drying_index_afternoon",
        translation_key="drying_index_afternoon",
        name="Clothes Drying Time - Afternoon",
        value_fn=lambda data, _: cast(str, data.drying_afternoon) if data.drying_afternoon else None,
    ),
    WeatherSensorEntityDescription(
        key="drying_next_good_day",
        translation_key="drying_next_good_day",
        name="Clothes Drying - Next Good Day",
        value_fn=lambda data, _: cast(str, data.drying_next_good_day) if data.drying_next_good_day else None,
    ),
    WeatherSensorEntityDescription(
        key="tides_high",
        translation_key="tides_high",
        name="Next High Tide",
        exists_fn=_tides_enabled,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data, _: _next_tide_time(data.tides, "HIGH"),
    ),
    WeatherSensorEntityDescription(
        key="tides_low",
        translation_key="tides_low",
        name="Next Low Tide",
        exists_fn=_tides_enabled,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data, _: _next_tide_time(data.tides, "LOW"),
    ),
    WeatherSensorEntityDescription(
        key="boating_status",
        translation_key="boating_status",
        name="Boating Conditions",
        exists_fn=_boating_enabled,
        value_fn=lambda data, _: cast(str, data.boating_status) if data.boating_status else None,
    ),
    WeatherSensorEntityDescription(
        key="boating_forecast",
        translation_key="boating_forecast",
        name="Boating Forecast",
        exists_fn=_boating_enabled,
        value_fn=lambda data, _: (
            f"{data.boating_forecast[:252]}..."
            if isinstance(data.boating_forecast, str) and len(data.boating_forecast) > 255
            else (data.boating_forecast or None)
        ),
    ),
    # --- Surf (from regional surf page marker data) ---
    WeatherSensorEntityDescription(
        key="surf_conditions",
        translation_key="surf_conditions",
        name="Surf Conditions",
        exists_fn=_surf_enabled,
        value_fn=lambda data, _: cast(str, data.surf_conditions) if data.surf_conditions else None,
    ),
    WeatherSensorEntityDescription(
        key="surf_rating",
        translation_key="surf_rating",
        name="Surf Rating",
        exists_fn=_surf_enabled,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda data, _: _safe_int(data.surf_rating),
    ),
    WeatherSensorEntityDescription(
        key="surf_wave_height",
        translation_key="surf_wave_height",
        name="Surf Wave Height",
        exists_fn=_surf_enabled,
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
        value_fn=lambda data, _: cast(str, data.surf_swell_direction) if data.surf_swell_direction else None,
    ),
    WeatherSensorEntityDescription(
        key="surf_swell_height",
        translation_key="surf_swell_height",
        name="Surf Swell Height",
        exists_fn=_surf_enabled,
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
        value_fn=lambda data, _: cast(str, data.surf_wind_direction) if data.surf_wind_direction else None,
    ),
    WeatherSensorEntityDescription(
        key="surf_wind_speed",
        translation_key="surf_wind_speed",
        name="Surf Wind Speed",
        exists_fn=_surf_enabled,
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
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        unit_fn=lambda _: "s",
        value_fn=lambda data, _: _safe_int(data.surf_period),
    ),
    # --- Wind and clothing (from currentConditions module) ---
    WeatherSensorEntityDescription(
        key="wind_strength",
        translation_key="wind_strength",
        name="Wind Strength",
        exists_fn=_has_observations,
        value_fn=lambda data, _: cast(str, data.wind_strength) if data.wind_strength else None,
    ),
    WeatherSensorEntityDescription(
        key="temperature_today_high",
        translation_key="temperature_today_high",
        name="Today's High Temperature",
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=1,
        unit_fn=lambda metric: UnitOfTemperature.CELSIUS if metric else UnitOfTemperature.FAHRENHEIT,
        value_fn=lambda data, _: _safe_float(data.temp_today_high),
    ),
    WeatherSensorEntityDescription(
        key="temperature_today_low",
        translation_key="temperature_today_low",
        name="Today's Low Temperature",
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=1,
        unit_fn=lambda metric: UnitOfTemperature.CELSIUS if metric else UnitOfTemperature.FAHRENHEIT,
        value_fn=lambda data, _: _safe_float(data.temp_today_low),
    ),
    # --- Tomorrow's forecast (injected from 7-day data) ---
    WeatherSensorEntityDescription(
        key="tomorrow_condition",
        translation_key="tomorrow_condition",
        name="Tomorrow — Condition",
        value_fn=lambda data, _: cast(str, data.tomorrow_condition) if data.tomorrow_condition else None,
    ),
    WeatherSensorEntityDescription(
        key="tomorrow_temp_high",
        translation_key="tomorrow_temp_high",
        name="Tomorrow — High Temperature",
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=1,
        unit_fn=lambda metric: UnitOfTemperature.CELSIUS if metric else UnitOfTemperature.FAHRENHEIT,
        value_fn=lambda data, _: _safe_float(data.tomorrow_temp_high),
    ),
    WeatherSensorEntityDescription(
        key="tomorrow_temp_low",
        translation_key="tomorrow_temp_low",
        name="Tomorrow — Low Temperature",
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=1,
        unit_fn=lambda metric: UnitOfTemperature.CELSIUS if metric else UnitOfTemperature.FAHRENHEIT,
        value_fn=lambda data, _: _safe_float(data.tomorrow_temp_low),
    ),
    WeatherSensorEntityDescription(
        key="tomorrow_description",
        translation_key="tomorrow_description",
        name="Tomorrow — Description",
        value_fn=lambda data, _: (
            f"{data.tomorrow_description[:252]}..."
            if isinstance(data.tomorrow_description, str) and len(data.tomorrow_description) > 255
            else (data.tomorrow_description or None)
        ),
    ),
    # --- Sub-day condition breakdown (from twoDayForecast module) ---
    WeatherSensorEntityDescription(
        key="breakdown_morning",
        translation_key="breakdown_morning",
        name="Today — Morning Condition",
        exists_fn=_has_breakdown,
        value_fn=lambda data, _: cast(str, data.breakdown_morning) if data.breakdown_morning else None,
    ),
    WeatherSensorEntityDescription(
        key="breakdown_afternoon",
        translation_key="breakdown_afternoon",
        name="Today — Afternoon Condition",
        exists_fn=_has_breakdown,
        value_fn=lambda data, _: cast(str, data.breakdown_afternoon) if data.breakdown_afternoon else None,
    ),
    WeatherSensorEntityDescription(
        key="breakdown_evening",
        translation_key="breakdown_evening",
        name="Today — Evening Condition",
        exists_fn=_has_breakdown,
        value_fn=lambda data, _: cast(str, data.breakdown_evening) if data.breakdown_evening else None,
    ),
    WeatherSensorEntityDescription(
        key="breakdown_overnight",
        translation_key="breakdown_overnight",
        name="Today — Overnight Condition",
        exists_fn=_has_breakdown,
        value_fn=lambda data, _: cast(str, data.breakdown_overnight) if data.breakdown_overnight else None,
    ),
    # --- Sun and moon (from sunAndMoon module) ---
    WeatherSensorEntityDescription(
        key="sunrise",
        translation_key="sunrise",
        name="Sunrise",
        value_fn=lambda data, _: cast(str, data.sunrise) if data.sunrise else None,
    ),
    WeatherSensorEntityDescription(
        key="sunset",
        translation_key="sunset",
        name="Sunset",
        value_fn=lambda data, _: cast(str, data.sunset) if data.sunset else None,
    ),
    WeatherSensorEntityDescription(
        key="moonrise",
        translation_key="moonrise",
        name="Moonrise",
        value_fn=lambda data, _: cast(str, data.moonrise) if data.moonrise else None,
    ),
    WeatherSensorEntityDescription(
        key="moonset",
        translation_key="moonset",
        name="Moonset",
        value_fn=lambda data, _: cast(str, data.moonset) if data.moonset else None,
    ),
    WeatherSensorEntityDescription(
        key="moon_phase",
        translation_key="moon_phase",
        name="Moon Phase",
        value_fn=lambda data, _: _MOON_PHASE_NAMES.get(cast(str, data.moon_phase), cast(str, data.moon_phase))
        if data.moon_phase
        else None,
        attr_fn=lambda data: {"raw_phase": data.moon_phase} if data.moon_phase else {},
    ),
    WeatherSensorEntityDescription(
        key="moon_phase_date",
        translation_key="moon_phase_date",
        name="Next Moon Phase Date",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data, _: datetime.datetime.fromisoformat(data.moon_phase_date)
        if isinstance(data.moon_phase_date, str)
        else None,
    ),
]

