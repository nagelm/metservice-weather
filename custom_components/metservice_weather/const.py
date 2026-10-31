"""Support for MetService weather service."""

from __future__ import annotations

import re
from typing import Final


DOMAIN = "metservice_weather"
CONF_ATTRIBUTION = "Data provided by the MetService NZ weather service"
MANUFACTURER = "MetService"

CONF_AUTO_HIDE_SEASONAL = "auto_hide_seasonal"

FIELD_DESCRIPTION = "wxPhraseLong"
FIELD_HUMIDITY = "relativeHumidity"
FIELD_PRESSURE = "pressureAltimeter"
FIELD_TEMP = "temperature"
FIELD_WINDDIR = "windDirection"
FIELD_WINDGUST = "windGust"
FIELD_WINDSPEED = "windSpeed"


CONDITION_MAP: Final[dict[str, str]] = {
    "cloudy": "cloudy",
    "drizzle": "rainy",
    "few-showers": "rainy",
    "few-showers-night": "rainy",
    "fine": "sunny",
    "fog": "fog",
    "frost": "sunny",
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
REQUEST_TIMEOUT: Final = 10
PUBLIC_HEADERS: Final = {
    "Accept-Encoding": "gzip",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/111.0.0.0 Safari/537.36"
    ),
}
LOCATION_PATH_RE: Final = re.compile(
    r"/(?:towns-cities|rural)/regions/[a-z0-9-]+/locations/[a-z0-9-]+"
    r"|/rural/regions/[a-z0-9-]+"
)
API_METRIC: Final = "metric"
DEFAULT_LOCATION = "/towns-cities/regions/bay-of-plenty/locations/tauranga"

TEMPUNIT = "temperature"
LENGTHUNIT = "length"
SPEEDUNIT = "speed"
PRESSUREUNIT = "pressure"
