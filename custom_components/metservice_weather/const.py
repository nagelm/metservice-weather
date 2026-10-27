"""Support for MetService weather service.

For more details about this platform, please refer to the documentation at
https://github.com/nagelm/metservice-weather.
"""

from __future__ import annotations

import re
from typing import Final


DOMAIN = "metservice_weather"
CONF_ATTRIBUTION = "Data provided by the MetService NZ weather service"
MANUFACTURER = "MetService"

# Onboarding option: when enabled, seasonal sensors (UV, fire danger, clothes
# drying) that MetService is not currently publishing are disabled and
# hidden instead of staying in an always-unknown state — keeping their
# history and settings — and re-enabled automatically, no restart required,
# once data resumes. Default off — see weather_current_conditions_sensors.py's
# `seasonal` field and sensor.py's async_setup_entry gating. Storage key name
# (auto_hide_seasonal) is unchanged from when the option removed sensors
# outright, for backward compatibility with entries created before that
# behaviour changed to disable+hide.
CONF_AUTO_HIDE_SEASONAL = "auto_hide_seasonal"

FIELD_DESCRIPTION = "wxPhraseLong"
FIELD_HUMIDITY = "relativeHumidity"
FIELD_PRESSURE = "pressureAltimeter"
FIELD_TEMP = "temperature"
FIELD_WINDDIR = "windDirection"
FIELD_WINDGUST = "windGust"
FIELD_WINDSPEED = "windSpeed"


CONDITION_MAP: Final[dict[str, str]] = {
    # Every newly detected entry should be added to this list, mapping to homeassistant's supported values from below.
    # These initial entries are as found on https://about.metservice.com/our-company/learning-centre/weather-icons-explained/
    "cloudy": "cloudy",
    "drizzle": "rainy",
    "few-showers": "rainy",
    "few-showers-night": "rainy",
    "fine": "sunny",
    "fog": "fog",
    "frost": "clear-night",
    "hail": "hail",
    "mostly-cloudy": "cloudy",
    "partly-cloudy": "partlycloudy",
    "partly-cloudy-night": "partlycloudy",
    "rain": "pouring",
    "showers": "rainy",
    "snow": "snowy",
    "thunder": "lightning",
    "wind-rain": "pouring",
    "rain-wind": "pouring",
    "windy": "windy",
}

BASE_URL = "https://www.metservice.com"
PUBLIC_URL = f"{BASE_URL}/publicData/webdata"
PUBLIC_WARNINGS_URL = f"{PUBLIC_URL}/warnings-service"
LOCATIONS_INDEX_URL = f"{PUBLIC_URL}/towns-cities"
MARINE_INDEX_URL = f"{PUBLIC_URL}/marine"
LOCATION_PATH_RE: Final = re.compile(
    r"^/(?:towns-cities|rural)/regions/[^/]+/locations/[^/]+$"
)
API_METRIC: Final = "metric"
API_URL_METRIC: Final = "m"
DEFAULT_LOCATION = "/towns-cities/regions/bay-of-plenty/locations/tauranga"

TEMPUNIT = "temperature"
LENGTHUNIT = "length"
SPEEDUNIT = "speed"
PRESSUREUNIT = "pressure"
