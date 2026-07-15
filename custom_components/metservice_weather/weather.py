"""Support for MetService weather service.

For more details about this platform, please refer to the documentation at
https://github.com/ciejer/metservice-weather.
"""

from __future__ import annotations

from .coordinator import WeatherUpdateCoordinator
from .entity import MetServiceEntity
from homeassistant.config_entries import ConfigEntry
from .const import (
    LENGTHUNIT,
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
    ATTR_FORECAST_PRECIPITATION_PROBABILITY,
    ATTR_FORECAST_TIME,
    ATTR_FORECAST_WIND_BEARING,
    ATTR_FORECAST_CONDITION,
    SingleCoordinatorWeatherEntity,
    WeatherEntityFeature,
    Forecast,
    DOMAIN as WEATHER_DOMAIN,
)


from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers import sun as sun_helper

from .helpers import format_timestamp

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[WeatherUpdateCoordinator],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add weather entity."""
    coordinator: WeatherUpdateCoordinator = entry.runtime_data
    async_add_entities([MetServiceForecastPublic(coordinator)])


class MetServicePublic(MetServiceEntity, SingleCoordinatorWeatherEntity):
    """Implementation of a MetService weather service."""

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

    _attr_supported_features = (
        WeatherEntityFeature.FORECAST_HOURLY | WeatherEntityFeature.FORECAST_DAILY
    )

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

        for entry in hourly_entries[hourly_skip : hourly_obs + hourly_skip]:
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
                        ATTR_FORECAST_TIME: format_timestamp(entry.datetime),
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
            entry = Forecast(
                {
                    ATTR_FORECAST_NATIVE_TEMP: day.temp_high,
                    ATTR_FORECAST_NATIVE_TEMP_LOW: day.temp_low,
                    ATTR_FORECAST_CONDITION: day_condition,
                    ATTR_FORECAST_TIME: forecast_time,
                }
            )
            # MetService publishes the % chance of ≥1 mm of rain
            # (an exceedance probability), not a rainfall amount, so it
            # maps to precipitation_probability — never to precipitation.
            if day.rain_prob_1mm is not None:
                entry[ATTR_FORECAST_PRECIPITATION_PROBABILITY] = round(
                    day.rain_prob_1mm
                )
            forecast.append(entry)
        return forecast
