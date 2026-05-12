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
)
from homeassistant.helpers.typing import StateType


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
    WeatherSensorEntityDescription(
        key="uvIndex",
        name="UV Index",
        icon="mdi:sunglasses",
        value_fn=lambda data, _: cast(str, data.replace("status-", "") if data else None),
    ),
    WeatherSensorEntityDescription(
        key=FIELD_WINDDIR,
        name="Wind Direction",
        icon=ICON_WIND,
        value_fn=lambda data, _: cast(str, data),
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
        value_fn=lambda data, _: _safe_float(data),
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
        unit_fn=lambda metric: UnitOfSpeed.KILOMETERS_PER_HOUR
        if metric
        else UnitOfSpeed.MILES_PER_HOUR,
        value_fn=lambda data, _: _safe_float(data),
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
        value_fn=lambda data, _: _safe_float(data),
    ),
    WeatherSensorEntityDescription(
        key="pressureTendencyTrend",
        name="Pressure Tendency Trend",
        icon="mdi:gauge",
        value_fn=lambda data, _: cast(str, data),
    ),
    WeatherSensorEntityDescription(
        key="pollen_levels",
        name="Pollen Levels",
        icon="mdi:flower",
        value_fn=lambda data, _: cast(str, data),
    ),
    WeatherSensorEntityDescription(
        key="pollen_type",
        name="Pollen Type",
        icon="mdi:flower",
        value_fn=lambda data, _: cast(
            str, ". ".join(i.capitalize() for i in data.lstrip(" ")[0:254].split(". "))
        )
        if data else None,
        # Pollen Type can be very long, so truncate to 254 characters; and capitalise each sentence
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
