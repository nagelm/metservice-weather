"""The MetService NZ data coordinator."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging
import re
import asyncio

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.const import (
    UnitOfPressure,
    UnitOfTemperature,
    UnitOfLength,
    UnitOfSpeed,
)

from .const import (
    TEMPUNIT,
    LENGTHUNIT,
    SPEEDUNIT,
    PRESSUREUNIT,
)
from .coordinator_types import MetServicePublicData, normalize_public_data
from .helpers import format_timestamp

_LOGGER = logging.getLogger(__name__)

MIN_TIME_BETWEEN_UPDATES = timedelta(minutes=20)


@dataclass
class WeatherUpdateCoordinatorConfig:
    """Class representing coordinator configuration."""

    api_url: str
    warnings_url: str
    unit_system_api: str
    unit_system: str
    location: str
    location_name: str
    tide_url: str
    boating_url: str
    surf_url: str
    update_interval = MIN_TIME_BETWEEN_UPDATES


class WeatherUpdateCoordinator(DataUpdateCoordinator[MetServicePublicData]):
    """The MetService update coordinator."""

    def __init__(
        self, hass: HomeAssistant, config: WeatherUpdateCoordinatorConfig
    ) -> None:
        """Initialize."""
        self._api_url = config.api_url
        self._warnings_url = config.warnings_url
        self._location = config.location
        self._location_name = config.location_name
        self._tide_url = config.tide_url
        self._boating_url = config.boating_url
        self._surf_url = config.surf_url
        self._unit_system_api = config.unit_system_api
        self._base_url = "https://www.metservice.com"
        self.unit_system = config.unit_system
        self._session = async_get_clientsession(hass)
        self.units_of_measurement = {
            TEMPUNIT: UnitOfTemperature.CELSIUS,
            LENGTHUNIT: UnitOfLength.MILLIMETERS,
            SPEEDUNIT: UnitOfSpeed.KILOMETERS_PER_HOUR,
            PRESSUREUNIT: UnitOfPressure.MBAR,
        }

        super().__init__(
            hass,
            _LOGGER,
            name="WeatherUpdateCoordinator",
            update_interval=config.update_interval,
            always_update=False,
        )

    @property
    def location(self):
        """Return the location used for data."""
        return self._location

    @property
    def location_name(self):
        """Return the entity name prefix."""
        return self._location_name

    @property
    def enable_tides(self) -> bool:
        """Return whether tides data is configured."""
        return bool(self._tide_url)

    @property
    def enable_boating(self) -> bool:
        """Return whether boating data is configured."""
        return bool(self._boating_url)

    @property
    def enable_surf(self) -> bool:
        """Return whether surf data is configured."""
        return bool(self._surf_url)

    @property
    def tide_url(self) -> str:
        """Return the tide URL."""
        return self._tide_url

    # Shared headers for public API and supplementary fetches
    _PUBLIC_HEADERS: dict[str, str] = {
        "Accept-Encoding": "gzip",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/111.0.0.0 Safari/537.36"
        ),
    }

    async def _async_update_data(self) -> MetServicePublicData:
        """Fetch data from API."""
        return await self.get_public_weather()

    async def get_public_weather(self):
        """Get weather data from public API."""
        headers = self._PUBLIC_HEADERS
        try:
            async with asyncio.timeout(10):
                url = f"{self._api_url}{self.location}"
                _LOGGER.debug("Fetching MetService public data from %s", url)
                response = await self._session.get(url, headers=headers)
                result_current = await response.json(content_type=None)
                if result_current is None:
                    raise ValueError("No current weather data received.")
                self._check_errors(url, result_current)
            await self.expand_data_urls(result_current)
            async with asyncio.timeout(10):
                url = f"{self._warnings_url}/{result_current['location']['type']}/{result_current['location']['key']}"
                response = await self._session.get(url, headers=headers)
                result_warnings = await response.json(content_type=None)
                if result_warnings is None:
                    raise ValueError("No warnings data received.")
                self._check_errors(url, result_warnings)
            await self.expand_data_urls(result_warnings)
            structured = [
                {
                    "name": warning.get("name") or "Warning",
                    "text": warning.get("text") or "",
                    "threat_period": warning.get("threatPeriod") or "",
                }
                for warning in result_warnings.get("warnings", [])
            ]
            warnings_list = [
                f"{w['name']}, {w['text']}, {w['threat_period']}" for w in structured
            ]
            warnings_text = "\n".join(warnings_list) if warnings_list else "No warnings"
            async with asyncio.timeout(10):
                url = f"{self._api_url}{self.location}/7-days"
                response = await self._session.get(url, headers=headers)
                result_daily = await response.json(content_type=None)
                if result_daily is None:
                    raise ValueError("No daily forecast data received.")
                self._check_errors(url, result_daily)
            await self.expand_data_urls(result_daily)
            result_current["weather_warnings"] = warnings_text
            result_current["warnings_list"] = structured
            result_current["pollen"] = await self.get_pollen_data()
            # tomorrow_* fields are derived inside normalize_public_data
            # from the 7-day data — no injection needed here.
            # Inject drying index fields by text prefix, then normalise so
            # that all three sensors always carry a useful value:
            #
            # MetService has three real-world patterns:
            #   Good day:    ["Morning: X hrs",  "Afternoon: Y hrs"]
            #   Mixed day:   ["Morning: X hrs",  "Afternoon: Wet"]
            #   Wet all day: ["Wet all day",      "Next good day: <day>"]
            #
            # After parsing:
            #   drying_morning    — hours, "Wet", or "Wet all day"
            #   drying_afternoon  — hours, "Wet", or "Wet all day" (copied from
            #                       morning when MetService omits the afternoon entry)
            #   drying_next_good_day — "Today" when either period is usable,
            #                          day name ("Thursday") on a complete washout
            try:
                drying_states = self.get_from_dict(
                    result_current, ["dryingIndex", "dryingState"]
                )
                if isinstance(drying_states, list):
                    drying_morning = None
                    drying_afternoon = None
                    drying_next_good_day = None
                    for entry in drying_states:
                        text = entry.get("text", "") if isinstance(entry, dict) else ""
                        if text.startswith("Morning:"):
                            drying_morning = text.removeprefix("Morning:").strip()
                        elif text.startswith("Afternoon:"):
                            drying_afternoon = text.removeprefix("Afternoon:").strip()
                        elif text.lower().startswith("next good day"):
                            drying_next_good_day = (
                                text.split(":", 1)[-1].strip() if ":" in text else text
                            )
                        elif text:
                            # No recognised prefix — MetService uses bare "Wet all day"
                            # for the morning slot on a complete washout.
                            drying_morning = text
                    # When MetService omits the afternoon (wet-all-day case),
                    # mirror the morning value so the sensor is never empty.
                    if drying_afternoon is None and drying_morning is not None:
                        drying_afternoon = drying_morning
                    # When there is no "next good day" entry, today itself is
                    # a usable drying day.
                    if drying_next_good_day is None:
                        drying_next_good_day = "Today"
                    result_current["drying_morning"] = drying_morning
                    result_current["drying_afternoon"] = drying_afternoon
                    result_current["drying_next_good_day"] = drying_next_good_day
            except Exception as _e:
                _LOGGER.debug("Could not extract drying index states: %s", _e)
            if self._tide_url:
                result_current["tideImport"] = await self.get_tides()
            if self._boating_url:
                result_current["boating_data"] = await self.get_boating_data()
            if self._surf_url:
                result_current["surf_data"] = await self.get_surf_data()
            return normalize_public_data(result_current, result_daily)

        except ValueError as err:
            raise UpdateFailed(f"Data validation error: {err}") from err
        except (TimeoutError, aiohttp.ClientError) as err:
            raise UpdateFailed(f"Error fetching MetService data: {err}") from err
        except Exception as err:
            raise UpdateFailed(f"Unexpected error: {err}") from err

    async def get_tides(self):
        """Get tides data. Returns None if unavailable rather than raising."""
        try:
            async with asyncio.timeout(10):
                url = self._tide_url
                _LOGGER.info("Fetching tides data from %s", url)
                response = await self._session.get(url, headers=self._PUBLIC_HEADERS)
                if response.status != 200:
                    _LOGGER.warning(
                        "Tides endpoint returned HTTP %s — tides data will be unavailable",
                        response.status,
                    )
                    return None
                result_tides = await response.json(content_type=None)
                if result_tides is None:
                    _LOGGER.warning("No tides data received")
                    return None
                self._check_errors(url, result_tides)
            await self.expand_data_urls(result_tides)
            # Try multiple known path variants for the tideData key
            for path in [
                ["layout", "primary", "slots", "main", "modules"],
                ["layout", "primary", "slots", "left-major", "modules"],
            ]:
                try:
                    modules = result_tides
                    for key in path:
                        modules = modules[key]
                    for module in modules:
                        if "tideData" in module:
                            return module["tideData"]
                except (KeyError, TypeError):
                    continue
            _LOGGER.warning(
                "Could not locate tideData in response — tides data will be unavailable"
            )
            return None

        except (TimeoutError, aiohttp.ClientError) as err:
            _LOGGER.warning(
                "Error fetching tides data: %s — tides will be unavailable", repr(err)
            )
            return None
        except Exception as err:
            _LOGGER.warning(
                "Unexpected error fetching tides data: %s — tides will be unavailable",
                repr(err),
            )
            return None

    async def get_boating_data(self) -> dict:
        """Get boating/surf conditions. Returns empty dict if unavailable."""
        try:
            async with asyncio.timeout(10):
                url = self._boating_url
                _LOGGER.info("Fetching boating data from %s", url)
                response = await self._session.get(url, headers=self._PUBLIC_HEADERS)
                if response.status != 200:
                    _LOGGER.warning(
                        "Boating endpoint returned HTTP %s — boating data unavailable",
                        response.status,
                    )
                    return {}
                data = await response.json(content_type=None)
            modules = (
                data.get("layout", {})
                .get("primary", {})
                .get("slots", {})
                .get("main", {})
                .get("modules", [])
            )
            if not modules:
                return {}
            days = modules[0].get("days", [])
            if not days:
                return {}
            today = days[0]
            return {
                "boating_status": today.get("view", {}).get("text", ""),
                "boating_status_raw": today.get("view", {}).get("status", ""),
                "boating_forecast": today.get("forecast", {}).get("text", ""),
                "boating_issued_at": today.get("forecast", {}).get("issuedAt", ""),
                "boating_table": today.get("table", {}).get("columns", []),
            }
        except (TimeoutError, aiohttp.ClientError) as err:
            _LOGGER.warning(
                "Error fetching boating data: %s — boating will be unavailable",
                repr(err),
            )
            return {}
        except Exception as err:
            _LOGGER.warning(
                "Unexpected error fetching boating data: %s — boating will be unavailable",
                repr(err),
            )
            return {}

    async def get_surf_data(self) -> dict:
        """Get surf conditions for the configured location.

        The coordinator stores the location-specific surf URL (e.g.
        ``…/surf/locations/waihi-beach``).  To get live data we fetch the
        regional surf page (strip ``/locations/…``) and find the matching
        marker, which carries current conditions directly in its ``value``
        block.  This avoids relying on location-specific pages that return
        HTTP 400 for some stations.
        """
        try:
            # Derive regional surf URL from the stored location URL.
            regional_url = re.sub(r"/locations/[^/]+$", "", self._surf_url.rstrip("/"))
            location_path = self._surf_url.split("publicData/webdata")[-1]

            _LOGGER.info("Fetching surf data from %s", regional_url)
            async with asyncio.timeout(10):
                response = await self._session.get(
                    regional_url, headers=self._PUBLIC_HEADERS
                )
                if response.status != 200:
                    _LOGGER.warning(
                        "Surf endpoint returned HTTP %s — surf data unavailable",
                        response.status,
                    )
                    return {}
                data = await response.json(content_type=None)

            # Find the marker whose link URL matches our stored location path.
            all_markers = (
                data.get("layout", {})
                .get("primary", {})
                .get("map", {})
                .get("markers", [])
            )
            marker = None
            for m in all_markers:
                try:
                    if m["action"]["modules"][0]["link"]["url"] == location_path:
                        marker = m
                        break
                except (KeyError, IndexError, TypeError):
                    continue

            if not marker:
                _LOGGER.warning(
                    "Could not find surf marker for %s — surf data unavailable",
                    location_path,
                )
                return {}

            value = marker.get("action", {}).get("modules", [{}])[0].get("value", {})
            swell = value.get("swell", {})
            wind = value.get("wind", {})
            view = marker.get("view", {})

            return {
                "surf_conditions": view.get("text", ""),
                "surf_rating": value.get("rating"),
                "surf_wave_height": value.get("waveHeight"),
                "surf_set_face": value.get("setFace"),
                "surf_swell_direction": swell.get("direction"),
                "surf_swell_height": swell.get("swellHeight"),
                "surf_wind_direction": wind.get("direction"),
                "surf_wind_speed": wind.get("averageSpeed"),
                "surf_wind_gust": wind.get("gustSpeed"),
                "surf_period": value.get("period"),
            }

        except (TimeoutError, aiohttp.ClientError) as err:
            _LOGGER.warning(
                "Error fetching surf data: %s — surf will be unavailable", repr(err)
            )
            return {}
        except Exception as err:
            _LOGGER.warning(
                "Unexpected error fetching surf data: %s — surf will be unavailable",
                repr(err),
            )
            return {}

    @staticmethod
    def _parse_pollen_html(html: str) -> dict:
        """Extract pollen level, plant types and status class from allergen HTML.

        status_class is MetService's site-wide severity taxonomy (good/medium/
        bad = exposure ramp; medium-good = blue informational, used for the
        pre-season "Imminent" notice; none = no data). It is the machine-
        orderable signal; the level text is the display label.
        """
        level = None
        plants = None
        status_class = None
        # Match <span class="status-...">Level</span>
        level_match = re.search(
            r'<span[^>]*class="status-([a-z-]+)"[^>]*>([^<]+)</span>', html
        )
        if level_match:
            status_class = level_match.group(1).strip()
            level = level_match.group(2).strip()
        # Plant types appear after the closing </span> tag
        plants_match = re.search(
            r"</span>(?:<br\s*/?>|</br>)(.*?)(?:<br\s*/?>|</br>|$)", html, re.IGNORECASE
        )
        if plants_match:
            plants = plants_match.group(1).strip()
        return {"level": level, "type": plants, "status_class": status_class}

    async def get_pollen_data(self) -> dict:
        """Fetch pollen/allergen data from MetService allergens endpoint.

        The page can carry several concurrent pollen status blocks (e.g. a
        pre-season "Imminent" for trees alongside a "Low" for currently
        active allergens). The first block stays the headline value; all
        blocks are returned under "groups".
        """
        empty = {"pollenLevels": {"level": None, "type": None}, "groups": []}
        try:
            async with asyncio.timeout(10):
                url = f"{self._api_url}{self._location}/airborne-allergens"
                _LOGGER.debug("Fetching pollen data from %s", url)
                response = await self._session.get(url, headers=self._PUBLIC_HEADERS)
                if response.status != 200:
                    _LOGGER.debug(
                        "Pollen endpoint returned HTTP %s — pollen data unavailable",
                        response.status,
                    )
                    return empty
                result = await response.json(content_type=None)
            # Search all modules for pollen iconWithText content blocks
            modules = (
                result.get("layout", {})
                .get("primary", {})
                .get("slots", {})
                .get("main", {})
                .get("modules", [])
            )
            groups = [
                self._parse_pollen_html(item["html"])
                for module in modules
                for item in module.get("content", [])
                if item.get("iconName") == "pollen" and "html" in item
            ]
            if groups:
                _LOGGER.debug("Pollen groups this cycle: %s", groups)
                return {"pollenLevels": groups[0], "groups": groups}
        except Exception as err:
            _LOGGER.debug("Could not fetch pollen data: %s", repr(err))
        return empty

    def _check_errors(self, url: str, response: dict):
        """Check for errors in the API response."""
        if "errors" not in response:
            return
        if errors := response["errors"]:
            error_messages = "; ".join([e["message"] for e in errors])
            raise ValueError(f"Error from {url}: {error_messages}")

    def get_from_dict(self, data_dict, map_list):
        """Recursively look for a given key path within a dictionary."""
        if not map_list:
            return data_dict
        if isinstance(data_dict, list):
            for idx, item in enumerate(data_dict):
                if map_list[0].isdigit() and idx == int(map_list[0]):
                    result = self.get_from_dict(item, map_list[1:])
                    if result is not None:
                        return result
                else:
                    result = self.get_from_dict(item, map_list)
                    if result is not None:
                        return result
        elif isinstance(data_dict, dict):
            for key, value in data_dict.items():
                if key == map_list[0]:
                    result = self.get_from_dict(value, map_list[1:])
                    if result is not None:
                        return result
                else:
                    result = self.get_from_dict(value, map_list)
                    if result is not None:
                        return result
        return None

    @staticmethod
    def _format_timestamp(timestamp_val: str) -> str:
        """Format timestamp to ISO format in UTC."""
        return format_timestamp(timestamp_val)

    async def expand_data_urls(self, data, parent=None, key=None, _depth=0):
        """Recursively expand dataUrl entries in the data, replacing the entire object.

        _depth counts only dataUrl expansion hops, not structural traversal steps,
        so the recursion guard fires on genuinely circular/runaway URL chains rather
        than on deeply nested but normal JSON objects.
        """
        if _depth > 10:
            _LOGGER.warning("expand_data_urls: max recursion depth reached, stopping")
            return
        if isinstance(data, dict):
            if "dataUrl" in data:
                url = data["dataUrl"]
                full_url = f"{self._base_url}{url}" if url.startswith("/") else url
                try:
                    async with asyncio.timeout(10):
                        response = await self._session.get(
                            full_url, headers=self._PUBLIC_HEADERS
                        )
                        if response.status != 200:
                            _LOGGER.warning(
                                "Error fetching %s: HTTP %s", full_url, response.status
                            )
                            if parent is not None and key is not None:
                                parent[key] = None
                            return
                        result = await response.json(content_type=None)
                    if parent is not None and key is not None:
                        parent[key] = result
                    # Increment depth only when following a dataUrl hop, not during
                    # structural traversal, so the guard catches URL expansion cycles.
                    await self.expand_data_urls(
                        result, parent=parent, key=key, _depth=_depth + 1
                    )
                except Exception as e:
                    _LOGGER.warning("Error fetching dataUrl %s: %s", full_url, e)
                    if parent is not None and key is not None:
                        parent[key] = None
            else:
                for k in list(data.keys()):
                    # Pass _depth unchanged — traversing dict keys is not a URL hop.
                    await self.expand_data_urls(
                        data[k], parent=data, key=k, _depth=_depth
                    )
        elif isinstance(data, list):
            for idx, item in enumerate(data):
                # Pass _depth unchanged — traversing list items is not a URL hop.
                await self.expand_data_urls(item, parent=data, key=idx, _depth=_depth)
