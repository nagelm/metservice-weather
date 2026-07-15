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

_UNMAPPED_LOGGED: set[str] = set()


def _map_condition(raw: str | None) -> str | None:
    """Map a MetService condition token to an HA condition, or None if unknown.

    Night variants fall back to their day token ("showers-night" → "showers");
    a night variant of a sunny condition maps to clear-night. Unknown tokens
    are logged once per runtime and reported as None rather than passed
    through as an invalid HA condition.
    """
    if raw is None:
        return None
    if raw in CONDITION_MAP:
        return CONDITION_MAP[raw]
    base = raw.removesuffix("-night")
    if base != raw and base in CONDITION_MAP:
        mapped = CONDITION_MAP[base]
        return "clear-night" if mapped == "sunny" else mapped
    if raw not in _UNMAPPED_LOGGED:
        _UNMAPPED_LOGGED.add(raw)
        _LOGGER.warning(
            "Unknown MetService condition %r — please report at "
            "https://github.com/nagelm/metservice-weather/issues",
            raw,
        )
    return None


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
    def native_temperature(self) -> float | None:
        """Return the platform temperature in native units (i.e. not converted)."""
        data = self.coordinator.data
        return data.temperature if data else None

    @property
    def native_temperature_unit(self) -> str:
        """Return the native unit of measurement for temperature."""
        return self.coordinator.units_of_measurement[TEMPUNIT]

    @property
    def native_pressure(self) -> float | None:
        """Return the pressure in native units."""
        data = self.coordinator.data
        return data.pressure if data else None

    @property
    def native_pressure_unit(self) -> str:
        """Return the native unit of measurement for pressure."""
        return self.coordinator.units_of_measurement[PRESSUREUNIT]

    @property
    def humidity(self) -> int | None:
        """Return the relative humidity in native units."""
        data = self.coordinator.data
        return data.humidity if data else None

    @property
    def native_wind_speed(self) -> float | None:
        """Return the wind speed in native units."""
        data = self.coordinator.data
        return data.wind_speed if data else None

    @property
    def native_wind_speed_unit(self) -> str:
        """Return the native unit of measurement for wind speed."""
        return self.coordinator.units_of_measurement[SPEEDUNIT]

    @property
    def wind_bearing(self) -> str | None:
        """Return the wind bearing."""
        data = self.coordinator.data
        return data.wind_direction if data else None

    @property
    def native_precipitation_unit(self) -> str:
        """Return the native unit of measurement for accumulated precipitation."""
        return self.coordinator.units_of_measurement[LENGTHUNIT]

    @property
    def condition(self) -> str | None:
        """Return the current condition."""
        data = self.coordinator.data
        if data is None:
            return None
        raw = data.condition
        mapped = _map_condition(raw)
        if mapped is None:
            return None
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
        if data is None:
            return forecast
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
        data = self.coordinator.data
        if data is None:
            return forecast
        for day in data.daily_entries:
            day_condition = _map_condition(day.condition)
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
            # Unlike the daily chance-of-rain above (a probability),
            # rain_total_mm is a genuine amount aggregated from the hourly
            # forecast, so it belongs in native_precipitation, not
            # precipitation_probability.
            if day.rain_total_mm is not None:
                entry[ATTR_FORECAST_NATIVE_PRECIPITATION] = day.rain_total_mm
            forecast.append(entry)
        return forecast
