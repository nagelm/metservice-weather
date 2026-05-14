"""Support for MetService weather service.

For more details about this platform, please refer to the documentation at
https://github.com/ciejer/metservice-weather.
"""
from __future__ import annotations

from .coordinator import WeatherUpdateCoordinator
from homeassistant.config_entries import ConfigEntry
from .const import (
    DOMAIN,
    FIELD_CONDITIONS,
    FIELD_HUMIDITY,
    FIELD_PRESSURE,
    FIELD_TEMP,
    FIELD_WINDDIR,
    FIELD_WINDSPEED,
    LENGTHUNIT,
    MANUFACTURER,
    PRESSUREUNIT,
    SPEEDUNIT,
    TEMPUNIT,
    CONDITION_MAP,
)

import logging
from datetime import datetime

from homeassistant.components.weather import (
    ATTR_FORECAST_NATIVE_PRECIPITATION,
    ATTR_FORECAST_NATIVE_TEMP,
    ATTR_FORECAST_NATIVE_TEMP_LOW,
    ATTR_FORECAST_NATIVE_WIND_SPEED,
    ATTR_FORECAST_TIME,
    ATTR_FORECAST_WIND_BEARING,
    ATTR_FORECAST_CONDITION,
    SingleCoordinatorWeatherEntity,
    WeatherEntityFeature,
    Forecast,
    DOMAIN as WEATHER_DOMAIN,
)

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers import sun as sun_helper

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


from .helpers import format_timestamp, safe_float


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry[WeatherUpdateCoordinator], async_add_entities: AddEntitiesCallback
) -> None:
    """Add weather entity."""
    coordinator: WeatherUpdateCoordinator = entry.runtime_data
    if entry.data["api"] == "mobile":
        async_add_entities(
            [
                MetServiceForecastMobile(coordinator),
            ]
        )
    else:
        async_add_entities(
            [
                MetServiceForecastPublic(coordinator),
            ]
        )


class MetServiceMobile(SingleCoordinatorWeatherEntity):
    """Implementation of a MetService weather service."""

    def __init__(self, coordinator: WeatherUpdateCoordinator) -> None:
        """Set up MetService device info."""
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.location)},
            name=coordinator.location_name,
            manufacturer=MANUFACTURER,
        )

    @property
    def native_temperature(self) -> float:
        """Return the platform temperature in native units (i.e. not converted)."""
        return self.coordinator.get_current_mobile(FIELD_TEMP)

    @property
    def native_temperature_unit(self) -> str:
        """Return the native unit of measurement for temperature."""
        return self.coordinator.units_of_measurement[TEMPUNIT]

    @property
    def native_pressure(self) -> float:
        """Return the pressure in native units."""
        return self.coordinator.get_current_mobile(FIELD_PRESSURE)

    @property
    def native_pressure_unit(self) -> str:
        """Return the native unit of measurement for pressure."""
        return self.coordinator.units_of_measurement[PRESSUREUNIT]

    @property
    def humidity(self) -> float:
        """Return the relative humidity in native units."""
        return self.coordinator.get_current_mobile(FIELD_HUMIDITY)

    @property
    def native_wind_speed(self) -> float:
        """Return the wind speed in native units."""
        return self.coordinator.get_current_mobile(FIELD_WINDSPEED)

    @property
    def native_wind_speed_unit(self) -> str:
        """Return the native unit of measurement for wind speed."""
        return self.coordinator.units_of_measurement[SPEEDUNIT]

    @property
    def wind_bearing(self) -> str:
        """Return the wind bearing."""
        return self.coordinator.get_current_mobile(FIELD_WINDDIR)

    @property
    def native_precipitation_unit(self) -> str:
        """Return the native unit of measurement for accumulated precipitation."""
        return self.coordinator.units_of_measurement[LENGTHUNIT]

    @property
    def condition(self) -> str:
        """Return the current condition."""
        raw = self.coordinator.get_current_mobile(FIELD_CONDITIONS)
        mapped = CONDITION_MAP.get(raw, raw)
        if mapped == "sunny" and not sun_helper.is_up(self.hass):
            return "clear-night"
        return mapped


class MetServiceForecastMobile(MetServiceMobile):
    """Implementation of a MetService weather forecast."""

    _attr_has_entity_name = True
    _attr_supported_features = WeatherEntityFeature.FORECAST_HOURLY | WeatherEntityFeature.FORECAST_DAILY

    def __init__(self, coordinator: WeatherUpdateCoordinator):
        """Initialize the forecast sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.location}_{WEATHER_DOMAIN}".lower()
        self._attr_name = "Forecast"
        self._forecast_hourly_cache: list[Forecast] | None = None
        self._forecast_daily_cache: list[Forecast] | None = None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Invalidate forecast caches and notify active subscribers."""
        self._forecast_hourly_cache = None
        self._forecast_daily_cache = None
        super()._handle_coordinator_update()

    async def async_forecast_hourly(self) -> list[Forecast] | None:
        """Return hourly forecast."""
        if self._forecast_hourly_cache is None:
            self._forecast_hourly_cache = self.forecast_hourly
        return self._forecast_hourly_cache

    async def async_forecast_daily(self) -> list[Forecast] | None:
        """Return daily forecast."""
        if self._forecast_daily_cache is None:
            self._forecast_daily_cache = self.forecast_daily
        return self._forecast_daily_cache

    @property
    def forecast_hourly(self) -> list[Forecast]:
        """Return the hourly forecast in native units."""

        forecast = []
        hourly_readings = self.coordinator.get_current_mobile("hourly_base")
        if not hourly_readings:
            return forecast
        for hour in range(len(hourly_readings)):
            this_hour = hourly_readings[hour]

            rain_fall = safe_float(this_hour.get("rainFall"))
            wind_speed = safe_float(this_hour.get("windSpeed"))
            wind_dir = this_hour.get("windDir")
            is_daytime = 7 < datetime.fromisoformat(this_hour["dateISO"]).hour < 19

            if rain_fall is not None and rain_fall > 0:
                if rain_fall > 6:
                    icon = "pouring"
                else:
                    icon = "rainy"
            elif wind_speed is not None and wind_speed > 40:
                icon = "windy"
            elif is_daytime:
                icon = "partlycloudy"
            else:
                icon = "clear-night"

            forecast.append(
                Forecast(
                    {
                        ATTR_FORECAST_NATIVE_TEMP: safe_float(this_hour.get("temperature")),
                        ATTR_FORECAST_TIME: format_timestamp(
                            this_hour["dateISO"]
                        ),
                        ATTR_FORECAST_NATIVE_PRECIPITATION: rain_fall,
                        ATTR_FORECAST_NATIVE_WIND_SPEED: wind_speed,
                        ATTR_FORECAST_WIND_BEARING: wind_dir,
                        ATTR_FORECAST_CONDITION: icon,
                    }
                )
            )
        return forecast

    @property
    def forecast_daily(self) -> list[Forecast]:
        """Return the daily forecast in native units."""

        forecast = []
        num_days = self.coordinator.get_forecast_daily_mobile("", 0)

        for day in range(0, num_days):
            day_condition = self.coordinator.get_forecast_daily_mobile("daily_condition", day)
            if day_condition in CONDITION_MAP:
                day_condition = CONDITION_MAP[day_condition]
            day_description = self.coordinator.get_forecast_daily_mobile("daily_description", day)
            forecast.append(
                Forecast(
                    {
                        ATTR_FORECAST_NATIVE_TEMP: self.coordinator.get_forecast_daily_mobile(
                            "daily_temp_high", day
                        ),
                        ATTR_FORECAST_NATIVE_TEMP_LOW: self.coordinator.get_forecast_daily_mobile(
                            "daily_temp_low", day
                        ),
                        ATTR_FORECAST_CONDITION: day_condition,
                        ATTR_FORECAST_TIME: self.coordinator.get_forecast_daily_mobile("daily_datetime", day),
                    }
                )
            )
        return forecast

class MetServicePublic(SingleCoordinatorWeatherEntity):
    """Implementation of a MetService weather service."""

    def __init__(self, coordinator: WeatherUpdateCoordinator) -> None:
        """Set up MetService device info."""
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.location)},
            name=coordinator.location_name,
            manufacturer=MANUFACTURER,
        )

    @property
    def native_temperature(self) -> float:
        """Return the platform temperature in native units (i.e. not converted)."""
        return self.coordinator.data.temperature

    @property
    def native_temperature_unit(self) -> str:
        """Return the native unit of measurement for temperature."""
        return self.coordinator.units_of_measurement[TEMPUNIT]

    @property
    def native_pressure(self) -> float:
        """Return the pressure in native units."""
        return self.coordinator.data.pressure

    @property
    def native_pressure_unit(self) -> str:
        """Return the native unit of measurement for pressure."""
        return self.coordinator.units_of_measurement[PRESSUREUNIT]

    @property
    def humidity(self) -> int | None:
        """Return the relative humidity in native units."""
        return self.coordinator.data.humidity

    @property
    def native_wind_speed(self) -> float:
        """Return the wind speed in native units."""
        return self.coordinator.data.wind_speed

    @property
    def native_wind_speed_unit(self) -> str:
        """Return the native unit of measurement for wind speed."""
        return self.coordinator.units_of_measurement[SPEEDUNIT]

    @property
    def wind_bearing(self) -> str:
        """Return the wind bearing."""
        return self.coordinator.data.wind_direction

    @property
    def native_precipitation_unit(self) -> str:
        """Return the native unit of measurement for accumulated precipitation."""
        return self.coordinator.units_of_measurement[LENGTHUNIT]

    @property
    def condition(self) -> str:
        """Return the current condition."""
        raw = self.coordinator.data.condition
        mapped = CONDITION_MAP.get(raw, raw)
        if mapped == "sunny" and not sun_helper.is_up(self.hass):
            return "clear-night"
        return mapped


class MetServiceForecastPublic(MetServicePublic):
    """Implementation of a MetService weather forecast."""

    _attr_has_entity_name = True
    _attr_supported_features = WeatherEntityFeature.FORECAST_HOURLY | WeatherEntityFeature.FORECAST_DAILY

    def __init__(self, coordinator: WeatherUpdateCoordinator):
        """Initialize the forecast sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.location}_{WEATHER_DOMAIN}".lower()
        self._attr_name = "Forecast"
        self._forecast_hourly_cache: list[Forecast] | None = None
        self._forecast_daily_cache: list[Forecast] | None = None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Invalidate forecast caches and notify active subscribers."""
        self._forecast_hourly_cache = None
        self._forecast_daily_cache = None
        super()._handle_coordinator_update()

    async def async_forecast_hourly(self) -> list[Forecast] | None:
        """Return hourly forecast."""
        if self._forecast_hourly_cache is None:
            self._forecast_hourly_cache = self.forecast_hourly
        return self._forecast_hourly_cache

    async def async_forecast_daily(self) -> list[Forecast] | None:
        """Return daily forecast."""
        if self._forecast_daily_cache is None:
            self._forecast_daily_cache = self.forecast_daily
        return self._forecast_daily_cache

    @property
    def forecast_hourly(self) -> list[Forecast]:
        """Return the hourly forecast in native units."""

        forecast = []
        data = self.coordinator.data
        hourly_entries = data.hourly_entries
        hourly_obs = data.hourly_obs
        hourly_skip = data.hourly_skip

        if not hourly_entries or hourly_obs is None or hourly_skip is None:
            return forecast

        for entry in hourly_entries[hourly_skip:hourly_obs + hourly_skip]:
            rainfall = entry.rainfall
            wind_speed = entry.wind_speed
            wind_dir = entry.wind_direction
            is_daytime = 7 < datetime.fromisoformat(entry.datetime).hour < 19

            if rainfall is not None and rainfall > 0:
                if rainfall > 6:
                    icon = "pouring"
                else:
                    icon = "rainy"
            elif wind_speed is not None and wind_speed > 40:
                icon = "windy"
            elif is_daytime:
                icon = "partlycloudy"
            else:
                icon = "clear-night"

            forecast.append(
                Forecast(
                    {
                        ATTR_FORECAST_NATIVE_TEMP: entry.temperature,
                        ATTR_FORECAST_TIME: format_timestamp(
                            entry.datetime
                        ),
                        ATTR_FORECAST_NATIVE_PRECIPITATION: rainfall,
                        ATTR_FORECAST_NATIVE_WIND_SPEED: wind_speed,
                        ATTR_FORECAST_WIND_BEARING: wind_dir,
                        ATTR_FORECAST_CONDITION: icon,
                    }
                )
            )
        return forecast

    @property
    def forecast_daily(self) -> list[Forecast]:
        """Return the daily forecast in native units."""

        forecast = []
        for day in self.coordinator.data.daily_entries:
            day_condition = day.condition
            if day_condition in CONDITION_MAP:
                day_condition = CONDITION_MAP[day_condition]
            try:
                forecast_time = format_timestamp(day.datetime) if day.datetime else None
            except (ValueError, AttributeError):
                forecast_time = day.datetime
            forecast.append(
                Forecast(
                    {
                        ATTR_FORECAST_NATIVE_TEMP: day.temp_high,
                        ATTR_FORECAST_NATIVE_TEMP_LOW: day.temp_low,
                        ATTR_FORECAST_CONDITION: day_condition,
                        ATTR_FORECAST_TIME: forecast_time,
                        ATTR_FORECAST_NATIVE_PRECIPITATION: day.rainfall_low,
                    }
                )
            )
        return forecast

