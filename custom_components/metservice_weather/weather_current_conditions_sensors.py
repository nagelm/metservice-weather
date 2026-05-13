"""Sensor platform for MetService weather."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast
from collections.abc import Callable
import datetime
from homeassistant.util import dt as dt_util

from .const import (
    FIELD_DESCRIPTION,
    FIELD_HUMIDITY,
    FIELD_PRESSURE,
    FIELD_TEMP,
    FIELD_WINDDIR,
    FIELD_WINDGUST,
    FIELD_WINDSPEED,
    ICON_THERMOMETER,
    ICON_WIND,
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


def _safe_float(data) -> float | None:
    """Convert data to float, returning None for non-numeric values like 'n/a'."""
    if data is None:
        return None
    try:
        return float(data)
    except (ValueError, TypeError):
        return None


def _safe_int(data) -> int | None:
    """Convert data to int, returning None for non-numeric values like 'n/a'."""
    if data is None:
        return None
    try:
        return int(data)
    except (ValueError, TypeError):
        return None


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

@dataclass
class WeatherRequiredKeysMixin:
    """Mixin for required keys."""

    value_fn: Callable[[dict[str, Any], str], StateType]


@dataclass
class WeatherSensorEntityDescription(SensorEntityDescription, WeatherRequiredKeysMixin):
    """Describes MetService Sensor entity."""

    attr_fn: Callable[[dict[str, Any]], dict[str, StateType]] = lambda _: {}
    unit_fn: Callable[[bool], str | None] = lambda _: None


current_condition_sensor_descriptions_public = [
    WeatherSensorEntityDescription(
        key="validTimeLocal",
        name="Forecast Description Updated Time",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:clock",
        value_fn=lambda data, _: datetime.datetime.fromisoformat(data.issued_at)
        if isinstance(data.issued_at, str)
        else None,
    ),
    WeatherSensorEntityDescription(
        key=FIELD_DESCRIPTION,
        name="Weather Description",
        icon="mdi:note-text",
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
        name="Relative Humidity",
        icon="mdi:water-percent",
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        unit_fn=lambda _: PERCENTAGE,
        value_fn=lambda data, _: _safe_int(data.humidity),
    ),
    WeatherSensorEntityDescription(
        key="uvIndex",
        name="UV Index",
        icon="mdi:sunglasses",
        value_fn=lambda data, _: cast(
            str, data.uv_index.replace("status-", "") if data.uv_index else None
        ),
    ),
    WeatherSensorEntityDescription(
        key=FIELD_WINDDIR,
        name="Wind Direction",
        icon=ICON_WIND,
        value_fn=lambda data, _: cast(str, data.wind_direction),
    ),
    WeatherSensorEntityDescription(
        key="temperatureFeelsLike",
        name="Temperature - Feels Like",
        icon=ICON_THERMOMETER,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.TEMPERATURE,
        unit_fn=lambda metric: UnitOfTemperature.CELSIUS
        if metric
        else UnitOfTemperature.FAHRENHEIT,
        value_fn=lambda data, _: _safe_float(data.feels_like),
    ),
    WeatherSensorEntityDescription(
        key=FIELD_TEMP,
        name="Temperature",
        icon=ICON_THERMOMETER,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.TEMPERATURE,
        unit_fn=lambda metric: UnitOfTemperature.CELSIUS
        if metric
        else UnitOfTemperature.FAHRENHEIT,
        value_fn=lambda data, _: _safe_float(data.temperature),
    ),
    WeatherSensorEntityDescription(
        key=FIELD_PRESSURE,
        name="Pressure",
        icon="mdi:gauge",
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.PRESSURE,
        unit_fn=lambda metric: UnitOfPressure.MBAR if metric else UnitOfPressure.INHG,
        value_fn=lambda data, _: _safe_float(data.pressure),
    ),
    WeatherSensorEntityDescription(
        key=FIELD_WINDGUST,
        name="Wind Gust",
        icon=ICON_WIND,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.WIND_SPEED,
        unit_fn=lambda metric: UnitOfSpeed.KILOMETERS_PER_HOUR
        if metric
        else UnitOfSpeed.MILES_PER_HOUR,
        value_fn=lambda data, _: _safe_float(data.wind_gust),
    ),
    WeatherSensorEntityDescription(
        key=FIELD_WINDSPEED,
        name="Wind Speed",
        icon=ICON_WIND,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.WIND_SPEED,
        unit_fn=lambda metric: UnitOfSpeed.KILOMETERS_PER_HOUR
        if metric
        else UnitOfSpeed.MILES_PER_HOUR,
        value_fn=lambda data, _: _safe_float(data.wind_speed),
    ),
    WeatherSensorEntityDescription(
        key="rainfall",
        name="Rainfall",
        icon="mdi:weather-rainy",
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.PRECIPITATION,
        unit_fn=lambda _: UnitOfPrecipitationDepth.MILLIMETERS,
        value_fn=lambda data, _: _safe_float(data.rainfall),
    ),
    WeatherSensorEntityDescription(
        key="pressureTendencyTrend",
        name="Pressure Tendency Trend",
        icon="mdi:gauge",
        value_fn=lambda data, _: cast(str, data.pressure_trend),
    ),
    WeatherSensorEntityDescription(
        key="pollen_levels",
        name="Pollen Levels",
        icon="mdi:flower",
        value_fn=lambda data, _: cast(str, data.pollen_level),
    ),
    WeatherSensorEntityDescription(
        key="pollen_type",
        name="Pollen Type",
        icon="mdi:flower",
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
        name="MetService Weather Warnings",
        icon="mdi:alert",
        value_fn=lambda data, _: (
            (data.weather_warnings[:252] + "...")
            if len(data.weather_warnings) > 255
            else data.weather_warnings
        ),
        attr_fn=lambda data: {"warnings": data.weather_warnings},
    ),
    WeatherSensorEntityDescription(
        key="fire_season",
        name="Fire Season",
        icon="mdi:fire",
        value_fn=lambda data, _: cast(str, data.fire_season),
    ),
    WeatherSensorEntityDescription(
        key="fire_danger",
        name="Fire Danger",
        icon="mdi:fire",
        value_fn=lambda data, _: cast(str, data.fire_danger),
    ),
    WeatherSensorEntityDescription(
        key="drying_index_morning",
        name="Clothes Drying Time - Morning",
        icon="mdi:tshirt-crew",
        value_fn=lambda data, _: cast(str, data.drying_morning) if data.drying_morning else None,
    ),
    WeatherSensorEntityDescription(
        key="drying_index_afternoon",
        name="Clothes Drying Time - Afternoon",
        icon="mdi:tshirt-crew",
        value_fn=lambda data, _: cast(str, data.drying_afternoon) if data.drying_afternoon else None,
    ),
    WeatherSensorEntityDescription(
        key="drying_next_good_day",
        name="Clothes Drying - Next Good Day",
        icon="mdi:calendar-check",
        value_fn=lambda data, _: cast(str, data.drying_next_good_day) if data.drying_next_good_day else None,
    ),
    WeatherSensorEntityDescription(
        key="tides_high",
        name="Next High Tide",
        icon="mdi:beach",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data, _: _next_tide_time(data.tides, "HIGH"),
    ),
    WeatherSensorEntityDescription(
        key="tides_low",
        name="Next Low Tide",
        icon="mdi:beach",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data, _: _next_tide_time(data.tides, "LOW"),
    ),
    WeatherSensorEntityDescription(
        key="boating_status",
        name="Boating Conditions",
        icon="mdi:sail-boat",
        value_fn=lambda data, _: cast(str, data.boating_status) if data.boating_status else None,
    ),
    WeatherSensorEntityDescription(
        key="boating_forecast",
        name="Boating Forecast",
        icon="mdi:sail-boat",
        value_fn=lambda data, _: (
            f"{data.boating_forecast[:252]}..."
            if isinstance(data.boating_forecast, str) and len(data.boating_forecast) > 255
            else (data.boating_forecast or None)
        ),
    ),
    # --- Surf (from regional surf page marker data) ---
    WeatherSensorEntityDescription(
        key="surf_conditions",
        name="Surf Conditions",
        icon="mdi:surfing",
        value_fn=lambda data, _: cast(str, data.surf_conditions) if data.surf_conditions else None,
    ),
    WeatherSensorEntityDescription(
        key="surf_rating",
        name="Surf Rating",
        icon="mdi:surfing",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data, _: _safe_int(data.surf_rating),
    ),
    WeatherSensorEntityDescription(
        key="surf_wave_height",
        name="Surf Wave Height",
        icon="mdi:waves",
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.DISTANCE,
        unit_fn=lambda _: "m",
        value_fn=lambda data, _: _safe_float(data.surf_wave_height),
    ),
    WeatherSensorEntityDescription(
        key="surf_set_face",
        name="Surf Set Face",
        icon="mdi:waves",
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.DISTANCE,
        unit_fn=lambda _: "m",
        value_fn=lambda data, _: _safe_float(data.surf_set_face),
    ),
    WeatherSensorEntityDescription(
        key="surf_swell_direction",
        name="Surf Swell Direction",
        icon="mdi:compass-rose",
        value_fn=lambda data, _: cast(str, data.surf_swell_direction) if data.surf_swell_direction else None,
    ),
    WeatherSensorEntityDescription(
        key="surf_swell_height",
        name="Surf Swell Height",
        icon="mdi:waves",
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.DISTANCE,
        unit_fn=lambda _: "m",
        value_fn=lambda data, _: _safe_float(data.surf_swell_height),
    ),
    WeatherSensorEntityDescription(
        key="surf_wind_direction",
        name="Surf Wind Direction",
        icon=ICON_WIND,
        value_fn=lambda data, _: cast(str, data.surf_wind_direction) if data.surf_wind_direction else None,
    ),
    WeatherSensorEntityDescription(
        key="surf_wind_speed",
        name="Surf Wind Speed",
        icon=ICON_WIND,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.WIND_SPEED,
        unit_fn=lambda _: "kn",
        value_fn=lambda data, _: _safe_int(data.surf_wind_speed),
    ),
    WeatherSensorEntityDescription(
        key="surf_wind_gust",
        name="Surf Wind Gust",
        icon=ICON_WIND,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.WIND_SPEED,
        unit_fn=lambda _: "kn",
        value_fn=lambda data, _: _safe_int(data.surf_wind_gust),
    ),
    WeatherSensorEntityDescription(
        key="surf_period",
        name="Surf Period",
        icon="mdi:timer-sand",
        state_class=SensorStateClass.MEASUREMENT,
        unit_fn=lambda _: "s",
        value_fn=lambda data, _: _safe_int(data.surf_period),
    ),
    # --- Wind and clothing (from currentConditions module) ---
    WeatherSensorEntityDescription(
        key="wind_strength",
        name="Wind Strength",
        icon=ICON_WIND,
        value_fn=lambda data, _: cast(str, data.wind_strength) if data.wind_strength else None,
    ),
    WeatherSensorEntityDescription(
        key="temperature_today_high",
        name="Today's High Temperature",
        icon=ICON_THERMOMETER,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.TEMPERATURE,
        unit_fn=lambda metric: UnitOfTemperature.CELSIUS if metric else UnitOfTemperature.FAHRENHEIT,
        value_fn=lambda data, _: _safe_float(data.temp_today_high),
    ),
    WeatherSensorEntityDescription(
        key="temperature_today_low",
        name="Today's Low Temperature",
        icon=ICON_THERMOMETER,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.TEMPERATURE,
        unit_fn=lambda metric: UnitOfTemperature.CELSIUS if metric else UnitOfTemperature.FAHRENHEIT,
        value_fn=lambda data, _: _safe_float(data.temp_today_low),
    ),
    # --- Tomorrow's forecast (injected from 7-day data) ---
    WeatherSensorEntityDescription(
        key="tomorrow_condition",
        name="Tomorrow — Condition",
        icon="mdi:weather-partly-cloudy",
        value_fn=lambda data, _: cast(str, data.tomorrow_condition) if data.tomorrow_condition else None,
    ),
    WeatherSensorEntityDescription(
        key="tomorrow_temp_high",
        name="Tomorrow — High Temperature",
        icon=ICON_THERMOMETER,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.TEMPERATURE,
        unit_fn=lambda metric: UnitOfTemperature.CELSIUS if metric else UnitOfTemperature.FAHRENHEIT,
        value_fn=lambda data, _: _safe_float(data.tomorrow_temp_high),
    ),
    WeatherSensorEntityDescription(
        key="tomorrow_temp_low",
        name="Tomorrow — Low Temperature",
        icon=ICON_THERMOMETER,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.TEMPERATURE,
        unit_fn=lambda metric: UnitOfTemperature.CELSIUS if metric else UnitOfTemperature.FAHRENHEIT,
        value_fn=lambda data, _: _safe_float(data.tomorrow_temp_low),
    ),
    WeatherSensorEntityDescription(
        key="tomorrow_description",
        name="Tomorrow — Description",
        icon="mdi:note-text",
        value_fn=lambda data, _: (
            f"{data.tomorrow_description[:252]}..."
            if isinstance(data.tomorrow_description, str) and len(data.tomorrow_description) > 255
            else (data.tomorrow_description or None)
        ),
    ),
    # --- Sub-day condition breakdown (from twoDayForecast module) ---
    WeatherSensorEntityDescription(
        key="breakdown_morning",
        name="Today — Morning Condition",
        icon="mdi:weather-partly-cloudy",
        value_fn=lambda data, _: cast(str, data.breakdown_morning) if data.breakdown_morning else None,
    ),
    WeatherSensorEntityDescription(
        key="breakdown_afternoon",
        name="Today — Afternoon Condition",
        icon="mdi:weather-sunny",
        value_fn=lambda data, _: cast(str, data.breakdown_afternoon) if data.breakdown_afternoon else None,
    ),
    WeatherSensorEntityDescription(
        key="breakdown_evening",
        name="Today — Evening Condition",
        icon="mdi:weather-sunset",
        value_fn=lambda data, _: cast(str, data.breakdown_evening) if data.breakdown_evening else None,
    ),
    WeatherSensorEntityDescription(
        key="breakdown_overnight",
        name="Today — Overnight Condition",
        icon="mdi:weather-night",
        value_fn=lambda data, _: cast(str, data.breakdown_overnight) if data.breakdown_overnight else None,
    ),
    # --- Sun and moon (from sunAndMoon module) ---
    WeatherSensorEntityDescription(
        key="sunrise",
        name="Sunrise",
        icon="mdi:weather-sunset-up",
        value_fn=lambda data, _: cast(str, data.sunrise) if data.sunrise else None,
    ),
    WeatherSensorEntityDescription(
        key="sunset",
        name="Sunset",
        icon="mdi:weather-sunset-down",
        value_fn=lambda data, _: cast(str, data.sunset) if data.sunset else None,
    ),
    WeatherSensorEntityDescription(
        key="moonrise",
        name="Moonrise",
        icon="mdi:weather-night",
        value_fn=lambda data, _: cast(str, data.moonrise) if data.moonrise else None,
    ),
    WeatherSensorEntityDescription(
        key="moonset",
        name="Moonset",
        icon="mdi:weather-night",
        value_fn=lambda data, _: cast(str, data.moonset) if data.moonset else None,
    ),
    WeatherSensorEntityDescription(
        key="moon_phase",
        name="Moon Phase",
        icon="mdi:moon-new",
        value_fn=lambda data, _: _MOON_PHASE_NAMES.get(cast(str, data.moon_phase), cast(str, data.moon_phase))
        if data.moon_phase
        else None,
        attr_fn=lambda data: {"raw_phase": data.moon_phase} if data.moon_phase else {},
    ),
    WeatherSensorEntityDescription(
        key="moon_phase_date",
        name="Next Moon Phase Date",
        icon="mdi:calendar-month",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data, _: datetime.datetime.fromisoformat(data.moon_phase_date)
        if isinstance(data.moon_phase_date, str)
        else None,
    ),
]

current_condition_sensor_descriptions_mobile = [
    WeatherSensorEntityDescription(
        key="validTimeLocal",
        name="Forecast Description Updated Time",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:clock",
        value_fn=lambda data, _: datetime.datetime.fromisoformat(data)
        if isinstance(data, str)
        else None,
    ),
    WeatherSensorEntityDescription(
        key=FIELD_DESCRIPTION,
        name="Weather Description",
        icon="mdi:note-text",
        value_fn=lambda data, _: (
            f"{data[:252]}..." if isinstance(data, str) and len(data) > 255 else (data if data else "No description")
        ),
        # Description can be very long, so truncate to 252 characters and append '...' if necessary
        attr_fn=lambda data: {"full_description": data} if isinstance(data, str) and data else {},
    ),
    WeatherSensorEntityDescription(
        key=FIELD_HUMIDITY,
        name="Relative Humidity",
        icon="mdi:water-percent",
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        unit_fn=lambda _: PERCENTAGE,
        value_fn=lambda data, _: _safe_int(data),
    ),
    WeatherSensorEntityDescription(  # UV index from main endpoint is UV Alert from mobile endpoint
        key="uvAlert",
        name="UV Alert",
        icon="mdi:sunglasses",
        value_fn=lambda data, _: cast(str, data),
    ),
    WeatherSensorEntityDescription(
        key=FIELD_WINDDIR,
        name="Wind Direction",
        icon=ICON_WIND,
        value_fn=lambda data, _: cast(str, data),
    ),
    WeatherSensorEntityDescription(
        key=FIELD_TEMP,
        name="Temperature",
        icon=ICON_THERMOMETER,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.TEMPERATURE,
        unit_fn=lambda metric: UnitOfTemperature.CELSIUS if metric else UnitOfTemperature.FAHRENHEIT,
        value_fn=lambda data, _: _safe_float(data),
    ),
    WeatherSensorEntityDescription(
        key=FIELD_PRESSURE,
        name="Pressure",
        icon="mdi:gauge",
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.PRESSURE,
        unit_fn=lambda metric: UnitOfPressure.MBAR if metric else UnitOfPressure.INHG,
        value_fn=lambda data, _: _safe_float(data),
    ),
    WeatherSensorEntityDescription(
        key=FIELD_WINDGUST,
        name="Wind Gust",
        icon=ICON_WIND,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.WIND_SPEED,
        unit_fn=lambda metric: UnitOfSpeed.KILOMETERS_PER_HOUR if metric else UnitOfSpeed.MILES_PER_HOUR,
        value_fn=lambda data, _: _safe_float(data),
    ),
    WeatherSensorEntityDescription(
        key=FIELD_WINDSPEED,
        name="Wind Speed",
        icon=ICON_WIND,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.WIND_SPEED,
        unit_fn=lambda metric: UnitOfSpeed.KILOMETERS_PER_HOUR if metric else UnitOfSpeed.MILES_PER_HOUR,
        value_fn=lambda data, _: _safe_float(data),
    ),
    WeatherSensorEntityDescription(
        key="pressureTendencyTrend",
        name="Pressure Tendency Trend",
        icon="mdi:gauge",
        value_fn=lambda data, _: cast(str, data),
    ),
    WeatherSensorEntityDescription(
        key="drying_index_morning",
        name="Clothes Drying Time - Morning",
        icon="mdi:tshirt-crew",
        value_fn=lambda data, _: cast(str, data.replace("Morning: ", "")) if data else None,
    ),
    WeatherSensorEntityDescription(
        key="drying_index_afternoon",
        name="Clothes Drying Time - Afternoon",
        icon="mdi:tshirt-crew",
        value_fn=lambda data, _: cast(str, data.replace("Afternoon: ", "")) if data else None,
    ),
    WeatherSensorEntityDescription(
        key="weather_warnings",
        name="MetService Weather Warnings",
        icon="mdi:alert",
        value_fn=lambda data, _: (data[:252] + '...') if data and len(data) > 255 else (data or "No warnings"),
        attr_fn=lambda data: {"warnings": data} if data else {},
    ),
    WeatherSensorEntityDescription(
        key="fire_season",
        name="Fire Season",
        icon="mdi:fire",
        value_fn=lambda data, _: cast(str, data),
    ),
    WeatherSensorEntityDescription(
        key="fire_danger",
        name="Fire Danger",
        icon="mdi:fire",
        value_fn=lambda data, _: cast(str, data),
    ),
    WeatherSensorEntityDescription(
        key="tides_high",
        name="Next High Tide",
        icon="mdi:beach",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data, _: _next_tide_time(data, "HIGH"),
    ),
    WeatherSensorEntityDescription(
        key="tides_low",
        name="Next Low Tide",
        icon="mdi:beach",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data, _: _next_tide_time(data, "LOW"),
    ),
]
