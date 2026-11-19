"""The MetService NZ data coordinator."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from collections.abc import Awaitable, Callable
from typing import Any
from email.utils import parsedate_to_datetime
import logging
import re
import asyncio
import time

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
    BASE_URL,
    TEMPUNIT,
    LENGTHUNIT,
    SPEEDUNIT,
    PRESSUREUNIT,
)
from .coordinator_types import MetServicePublicData, normalize_public_data

_LOGGER = logging.getLogger(__name__)

MIN_TIME_BETWEEN_UPDATES = timedelta(minutes=20)

# Home Assistant's shared DNS resolver (c-ares) sometimes reports "Timeout while
# contacting DNS servers" for a working server, and after an EDNS cookie
# mismatch it can keep failing for about 2 minutes (home-assistant/core#145708).
# On a transient failure (a network error, or a 502, 503 or 504 from MetService)
# the coordinator keeps its last good data for up to STALE_DATA_LIMIT instead of
# going unavailable until the next 20-minute update. It polls again after
# RETRY_INTERVAL, which is past that window, or after a longer Retry-After the
# server sends, up to the normal interval.
RETRY_INTERVAL = timedelta(minutes=3)
STALE_DATA_LIMIT = timedelta(hours=1)
_TRANSIENT_ERRORS = (
    TimeoutError,
    aiohttp.ClientConnectionError,
    aiohttp.ClientPayloadError,
)
# Certificate and TLS failures do not clear up by waiting.
_PERMANENT_ERRORS = (aiohttp.ClientSSLError,)
# Gateway and availability errors from MetService's edge are usually brief.
_TRANSIENT_HTTP_STATUSES = frozenset({502, 503, 504})

_MARINE_REGION_SLUG_RE = re.compile(r"/marine/regions/([^/]+)/")


def _is_transient(cause: BaseException | None) -> bool:
    """Return whether a fetch failure is likely to clear up on its own."""
    if isinstance(cause, aiohttp.ClientResponseError):
        return cause.status in _TRANSIENT_HTTP_STATUSES
    return isinstance(cause, _TRANSIENT_ERRORS) and not isinstance(
        cause, _PERMANENT_ERRORS
    )


@dataclass
class WeatherUpdateCoordinatorConfig:
    """Class representing coordinator configuration."""

    api_url: str
    warnings_url: str
    unit_system: str
    location: str
    location_name: str
    tide_url: str
    boating_url: str
    surf_url: str
    update_interval = MIN_TIME_BETWEEN_UPDATES


def _retry_interval(cause: BaseException | None, normal: timedelta) -> timedelta:
    """Return the wait before the next poll after a transient failure.

    A Retry-After header on a 502, 503 or 504 is honoured, kept between
    RETRY_INTERVAL and the normal update interval.
    """
    if not isinstance(cause, aiohttp.ClientResponseError) or not cause.headers:
        return RETRY_INTERVAL
    value = (cause.headers.get("Retry-After") or "").strip()
    try:
        if value.isascii() and value.isdigit():
            seconds = min(int(value), normal.total_seconds())
        else:
            when = parsedate_to_datetime(value)
            if when.tzinfo is None:
                when = when.replace(tzinfo=UTC)
            seconds = (when - datetime.now(UTC)).total_seconds()
        wait = timedelta(seconds=seconds)
    except TypeError, ValueError, IndexError, OverflowError:
        return RETRY_INTERVAL
    return max(RETRY_INTERVAL, min(wait, normal))


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
        self.unit_system = config.unit_system
        self.location_device_id: str | None = None
        self._session = async_get_clientsession(hass)
        self._normal_update_interval = config.update_interval
        self._last_success: float | None = None
        self._outage_logged = False
        # Last good result of each section fetch (pollen, tides, boating, surf,
        # dataUrl modules), keyed by URL, with the monotonic time it was fetched.
        self._section_cache: dict[str, tuple[float, Any]] = {}
        # How many section values the update in progress has reused from the
        # cache. A parent dataUrl skips caching a payload with reused children,
        # and the next poll comes sooner while any section runs on reused data.
        self._sections_reused = 0
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

    @property
    def marine_region_slug(self) -> str:
        """Return the marine region slug (e.g. "kapiti-wellington"), or ""."""
        for url in (self._tide_url, self._boating_url, self._surf_url):
            if not url:
                continue
            match = _MARINE_REGION_SLUG_RE.search(url)
            if match:
                return match.group(1)
        return ""

    _PUBLIC_HEADERS: dict[str, str] = {
        "Accept-Encoding": "gzip",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/111.0.0.0 Safari/537.36"
        ),
    }

    async def _async_update_data(self) -> MetServicePublicData:
        """Fetch data from API, riding out a transient failure."""
        try:
            data = await self.get_public_weather()
        except UpdateFailed as err:
            if self._can_keep_last_data(err):
                return self._keep_last_data(err)
            self._outage_logged = False
            self.update_interval = self._normal_update_interval
            raise
        if self._outage_logged:
            _LOGGER.info("MetService data for %s recovered", self._location_name)
        self._outage_logged = False
        self._last_success = time.monotonic()
        # A section still running on reused data is retried sooner, the same as
        # a failed update. This stops once its last data is too old to reuse.
        self.update_interval = (
            RETRY_INTERVAL if self._sections_reused else self._normal_update_interval
        )
        return data

    def _can_keep_last_data(self, err: UpdateFailed) -> bool:
        """Return whether a failed update can fall back to the last good data."""
        if not _is_transient(err.__cause__):
            return False
        # Only while the entities are still available: once a failure has been
        # raised, old data must not come back as if an update had succeeded.
        if self._last_success is None or not self.last_update_success:
            return False
        age = time.monotonic() - self._last_success
        return age < STALE_DATA_LIMIT.total_seconds()

    def _keep_last_data(self, err: UpdateFailed) -> MetServicePublicData:
        """Keep the last good data and poll again sooner than usual."""
        interval = _retry_interval(err.__cause__, self._normal_update_interval)
        retry_minutes = round(interval.total_seconds() / 60)
        if not self._outage_logged:
            _LOGGER.warning(
                "%s; keeping the last MetService data for %s and trying again "
                "in %s minutes",
                err,
                self._location_name,
                retry_minutes,
            )
            self._outage_logged = True
        else:
            _LOGGER.debug(
                "%s; still keeping the last MetService data, trying again in %s "
                "minutes",
                err,
                retry_minutes,
            )
        self.update_interval = interval
        return self.data

    def _prune_sections(self) -> None:
        """Drop remembered section values too old to be reused."""
        cutoff = time.monotonic() - STALE_DATA_LIMIT.total_seconds()
        for key in [k for k, (at, _) in self._section_cache.items() if at < cutoff]:
            del self._section_cache[key]

    async def _fetch_section(
        self,
        name: str,
        url: str,
        empty: Any,
        parse: Callable[[Any], Awaitable[Any]],
        *,
        fetch_url: str | None = None,
        reuse: bool = True,
    ) -> Any:
        """Fetch one optional section of data, riding out a transient failure.

        The parsed value is remembered under url. When the fetch fails with a
        timeout, connection or payload error, or a 502, 503 or 504, the last
        value from within STALE_DATA_LIMIT is returned instead (a copy). Any
        other failure, or one with nothing recent to reuse, returns empty and
        records it, so a later failure can't bring back older data.
        """
        source = fetch_url or url
        level = logging.DEBUG if name == "pollen" else logging.WARNING
        try:
            async with asyncio.timeout(10):
                _LOGGER.debug("Fetching %s data from %s", name, source)
                response = await self._session.get(source, headers=self._PUBLIC_HEADERS)
                if response.status != 200:
                    reason = f"HTTP {response.status}"
                    transient = response.status in _TRANSIENT_HTTP_STATUSES
                    data = None
                else:
                    data = await response.json(content_type=None)
                    reason = "no data received" if data is None else ""
                    transient = False
            if not reason:
                reused_before = self._sections_reused
                value = await parse(data)
                # Don't remember a value built on reused nested data, so that
                # data can't outlive STALE_DATA_LIMIT inside its parent.
                if self._sections_reused == reused_before:
                    self._section_cache[url] = (time.monotonic(), value)
                return value
        except Exception as err:
            reason = repr(err)
            transient = _is_transient(err)

        entry = self._section_cache.get(url) if transient and reuse else None
        if entry is not None and (
            time.monotonic() - entry[0] < STALE_DATA_LIMIT.total_seconds()
        ):
            _LOGGER.log(
                level,
                "Error fetching %s data from %s (%s); keeping the last data",
                name,
                source,
                reason,
            )
            self._sections_reused += 1
            return copy.deepcopy(entry[1])
        _LOGGER.log(
            level,
            "Error fetching %s data from %s (%s); %s data unavailable",
            name,
            source,
            reason,
            name,
        )
        self._section_cache[url] = (time.monotonic(), empty)
        return copy.deepcopy(empty)

    async def get_public_weather(self):
        """Get weather data from public API."""
        self._prune_sections()
        self._sections_reused = 0
        headers = self._PUBLIC_HEADERS
        try:
            async with asyncio.timeout(10):
                url = f"{self._api_url}{self.location}"
                _LOGGER.debug("Fetching MetService public data from %s", url)
                response = await self._session.get(url, headers=headers)
                response.raise_for_status()
                result_current = await response.json(content_type=None)
                if result_current is None:
                    raise ValueError("No current weather data received.")
                self._check_errors(url, result_current)
            await self.expand_data_urls(result_current)
            async with asyncio.timeout(10):
                url = f"{self._warnings_url}/{result_current['location']['type']}/{result_current['location']['key']}"
                response = await self._session.get(url, headers=headers)
                response.raise_for_status()
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
                response.raise_for_status()
                result_daily = await response.json(content_type=None)
                if result_daily is None:
                    raise ValueError("No daily forecast data received.")
                self._check_errors(url, result_daily)
            await self.expand_data_urls(result_daily)
            result_current["weather_warnings"] = warnings_text
            result_current["warnings_list"] = structured
            result_current["pollen"] = await self.get_pollen_data()
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
                            drying_morning = text
                    if drying_afternoon is None and drying_morning is not None:
                        drying_afternoon = drying_morning
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

        async def parse(result_tides):
            self._check_errors(self._tide_url, result_tides)
            await self.expand_data_urls(result_tides)
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
                except KeyError, TypeError:
                    continue
            _LOGGER.warning(
                "Could not locate tideData in response — tides data will be unavailable"
            )
            return None

        return await self._fetch_section("tides", self._tide_url, None, parse)

    async def get_boating_data(self) -> dict:
        """Get boating/surf conditions. Returns empty dict if unavailable."""

        async def parse(data):
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

        return await self._fetch_section("boating", self._boating_url, {}, parse)

    async def get_surf_data(self) -> dict:
        """Get surf conditions for the configured location."""
        regional_url = re.sub(r"/locations/[^/]+$", "", self._surf_url.rstrip("/"))
        location_path = self._surf_url.split("publicData/webdata")[-1]

        async def parse(data):
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
                except KeyError, IndexError, TypeError:
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

        return await self._fetch_section(
            "surf", self._surf_url, {}, parse, fetch_url=regional_url
        )

    @staticmethod
    def _parse_pollen_html(html: str) -> dict:
        """Extract pollen level, plant types and status class from allergen HTML."""
        level = None
        plants = None
        status_class = None
        level_match = re.search(
            r'<span[^>]*class="status-([a-z-]+)"[^>]*>([^<]+)</span>', html
        )
        if level_match:
            status_class = level_match.group(1).strip()
            level = level_match.group(2).strip()
        plants_match = re.search(
            r"</span>(?:<br\s*/?>|</br>)(.*?)(?:<br\s*/?>|</br>|$)", html, re.IGNORECASE
        )
        if plants_match:
            plants = plants_match.group(1).strip()
        return {"level": level, "type": plants, "status_class": status_class}

    async def get_pollen_data(self) -> dict:
        """Fetch pollen/allergen data from MetService allergens endpoint."""
        empty = {"pollenLevels": {"level": None, "type": None}, "groups": []}

        async def parse(result):
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
            if not groups:
                return copy.deepcopy(empty)
            _LOGGER.debug("Pollen groups this cycle: %s", groups)
            return {"pollenLevels": groups[0], "groups": groups}

        return await self._fetch_section(
            "pollen",
            f"{self._api_url}{self._location}/airborne-allergens",
            empty,
            parse,
        )

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

    async def expand_data_urls(self, data, parent=None, key=None, _depth=0):
        """Recursively expand dataUrl entries in the data, replacing the entire object."""
        if _depth > 10:
            _LOGGER.warning("expand_data_urls: max recursion depth reached, stopping")
            return
        if isinstance(data, dict):
            if "dataUrl" in data:
                url = data["dataUrl"]
                full_url = f"{BASE_URL}{url}" if url.startswith("/") else url
                has_slot = parent is not None and key is not None

                async def expand(result):
                    holder = {"value": result}
                    await self.expand_data_urls(
                        result, parent=holder, key="value", _depth=_depth + 1
                    )
                    return holder["value"]

                value = await self._fetch_section(
                    "dataUrl", full_url, None, expand, reuse=has_slot
                )
                if has_slot:
                    parent[key] = value
            else:
                for k in list(data.keys()):
                    await self.expand_data_urls(
                        data[k], parent=data, key=k, _depth=_depth
                    )
        elif isinstance(data, list):
            for idx, item in enumerate(data):
                await self.expand_data_urls(item, parent=data, key=idx, _depth=_depth)
