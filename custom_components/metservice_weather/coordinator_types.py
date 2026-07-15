"""Typed data models for the MetService coordinator."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

_LOGGER = logging.getLogger(__name__)


def _round_iso_to_minutes(iso: Any, resolution_minutes: int = 5) -> Any:
    """Round an ISO timestamp string to the nearest N minutes.

    MetService recomputes astronomical times per request with second-level
    jitter (observed: the same moon phase served as 19:15:27, then 19:15:46).
    Rounding at normalize time keeps the snapshot stable across polls so
    state only changes when the underlying event actually does. Values that
    aren't parseable ISO strings pass through unchanged.
    """
    if not isinstance(iso, str):
        return iso
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    step = timedelta(minutes=resolution_minutes)
    anchor = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    rounded = round((dt - anchor) / step) * step
    return (anchor + rounded).isoformat()


def _get(data: Any, *path: str) -> Any:
    """Exact-path traversal — no depth-first search.

    Numeric path parts are treated as list indices.
    """
    for part in path:
        if data is None:
            return None
        if isinstance(data, list):
            try:
                data = data[int(part)]
            except (IndexError, ValueError):
                return None
        elif isinstance(data, dict):
            data = data.get(part)
        else:
            return None
    return data


def _safe_float(val: Any) -> float | None:
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _safe_int(val: Any) -> int | None:
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _find_module(modules: list, key: str) -> dict:
    """Return the first module dict that contains `key`, or {}."""
    for m in modules:
        if isinstance(m, dict) and key in m:
            return m
    return {}


def _scan_forecasts(day: Any, key: str) -> Any:
    """Return the first non-None `key` from forecasts entries, else the day level.

    MetService publishes daily forecasts in several shapes:
    - towns-cities: one forecasts entry carrying temps, rain probabilities
      and the statement (temps duplicated at day level)
    - rural: a regional-text entry (statement only) plus a location entry
      carrying temps and rain probabilities (statement null); temps and
      statement also appear at day level
    Scanning every entry and then the day level covers all of them.
    """
    if not isinstance(day, dict):
        return None
    for f in day.get("forecasts") or []:
        if isinstance(f, dict) and f.get(key) is not None:
            return f[key]
    return day.get(key)


@dataclass
class HourlyEntry:
    """Single hourly forecast entry."""

    datetime: str = ""
    temperature: float | None = None
    rainfall: float | None = None
    wind_speed: float | None = None
    wind_direction: str | None = None


@dataclass
class DailyEntry:
    """Single daily forecast entry.

    rain_prob_1mm / rain_prob_10mm are MetService's rainfall exceedance
    probabilities (rainFall1 / rainFall10): the % chance of at least
    1 mm / 10 mm of rain that day. They are probabilities, NOT amounts —
    the public API does not publish daily rainfall amounts.
    """

    datetime: str | None = None
    condition: str | None = None
    temp_high: float | None = None
    temp_low: float | None = None
    description: str | None = None
    rain_prob_1mm: float | None = None
    rain_prob_10mm: float | None = None


@dataclass
class MetServicePublicData:
    """Normalised snapshot of public API data for one polling cycle."""

    # Current observations
    temperature: float | None = None
    feels_like: float | None = None
    temp_today_high: float | None = None
    temp_today_low: float | None = None
    humidity: int | None = None
    pressure: float | None = None
    pressure_trend: str | None = None
    wind_speed: float | None = None
    wind_gust: float | None = None
    wind_direction: str | None = None
    wind_strength: str | None = None
    rainfall: float | None = None
    condition: str | None = None
    forecast_text: str | None = None
    issued_at: str | None = None
    uv_index: str | None = None
    location_name: str | None = None

    # Sub-day breakdown
    breakdown_morning: str | None = None
    breakdown_afternoon: str | None = None
    breakdown_evening: str | None = None
    breakdown_overnight: str | None = None

    # Sun / moon
    sunrise: str | None = None
    sunset: str | None = None
    moonrise: str | None = None
    moonset: str | None = None
    moon_phase: str | None = None
    moon_phase_date: str | None = None

    # Fire weather
    fire_danger: str | None = None
    fire_season: str | None = None

    # Pollen (injected)
    pollen_level: str | None = None
    pollen_type: str | None = None

    # Derived / injected
    weather_warnings: str = "No warnings"
    warnings_list: list[dict[str, str]] = field(default_factory=list)
    tomorrow_condition: str | None = None
    tomorrow_temp_high: float | None = None
    tomorrow_temp_low: float | None = None
    tomorrow_description: str | None = None
    drying_morning: str | None = None
    drying_afternoon: str | None = None
    drying_next_good_day: str | None = None

    # Capability flags — structural presence of optional page sections.
    # Used to decide which sensor entities to create for a location.
    # Only sections whose absence is permanent for a location belong here;
    # seasonal products (UV, fire, drying, pollen) must stay ungated.
    has_observations: bool = False
    has_breakdown: bool = False
    is_rural: bool = False

    # Hourly forecast
    hourly_entries: list[HourlyEntry] = field(default_factory=list)
    hourly_obs: int | None = None
    hourly_skip: int | None = None

    # Daily forecast
    daily_entries: list[DailyEntry] = field(default_factory=list)

    # Optional marine (None / empty when not configured)
    tides: list[dict[str, Any]] | None = None
    boating_forecast: str | None = None
    boating_status: str | None = None
    boating_table: list[dict[str, Any]] | None = None
    surf_conditions: str | None = None
    surf_rating: str | None = None
    surf_wave_height: str | None = None
    surf_set_face: str | None = None
    surf_swell_direction: str | None = None
    surf_swell_height: str | None = None
    surf_wind_direction: str | None = None
    surf_wind_speed: str | None = None
    surf_wind_gust: str | None = None
    surf_period: str | None = None


def normalize_public_data(current: dict, daily: dict) -> MetServicePublicData:
    """Build a MetServicePublicData from raw coordinator dicts.

    Uses exact-path traversal (_get) and explicit section extraction —
    no DFS.  All injected fields (weather_warnings, pollen, drying_*)
    are already present at the root of `current` when this is called;
    tomorrow_* fields are derived here from the 7-day data.
    """
    # ------------------------------------------------------------------
    # Extract key sections from the nested layout structure
    # ------------------------------------------------------------------

    # Observations: layout.primary.slots.left-major.modules → module with "observations"
    # Rural locations have no weather station: the currentConditions module
    # expands to {} (or observations: null), so obs ends up empty.
    left_major = (
        _get(current, "layout", "primary", "slots", "left-major", "modules") or []
    )
    obs = _find_module(left_major, "observations").get("observations") or {}

    # Days / breakdown / fire: layout.primary.slots.main.modules → module with "days"
    main_mods = _get(current, "layout", "primary", "slots", "main", "modules") or []
    days = _find_module(main_mods, "days").get("days") or []
    day0 = days[0] if days and isinstance(days[0], dict) else {}
    breakdown0 = day0.get("breakdown") or {}

    # Hourly graph: layout.primary.slots.main.modules → module with "graph"
    graph = _find_module(main_mods, "graph").get("graph", {})
    graph_series = graph.get("series") or []
    hourly_skip = graph_series[0].get("count", 0) if graph_series else 0
    hourly_obs_count = graph_series[1].get("count", 0) if len(graph_series) > 1 else 0

    # UV: layout.primary.slots.left-minor.modules → module with "uv"
    left_minor = (
        _get(current, "layout", "primary", "slots", "left-minor", "modules") or []
    )
    uv = _find_module(left_minor, "uv").get("uv", {})

    # Sunrise / moon: layout.secondary.slots.major.modules → module with "riseSet"
    secondary = _get(current, "layout", "secondary", "slots", "major", "modules") or []
    rise_mod = _find_module(secondary, "riseSet")
    rise_set = rise_mod.get("riseSet", {})
    moon_phases = rise_mod.get("moonPhases", [])

    # ------------------------------------------------------------------
    # Hourly entries
    # ------------------------------------------------------------------
    hourly_raw = graph.get("columns") or []
    hourly_entries = [
        HourlyEntry(
            datetime=h.get("date", ""),
            temperature=_safe_float(h.get("temperature")),
            rainfall=_safe_float(h.get("rainfall")),
            wind_speed=_safe_float(_get(h, "wind", "speed")),
            wind_direction=_get(h, "wind", "direction"),
        )
        for h in hourly_raw
        if isinstance(h, dict)
    ]

    # ------------------------------------------------------------------
    # Daily entries (from 7-day JSON)
    # ------------------------------------------------------------------
    raw_days = (
        _get(daily, "layout", "primary", "slots", "main", "modules", "0", "days") or []
    )
    daily_entries = [
        DailyEntry(
            datetime=_get(d, "date"),
            condition=_get(d, "condition"),
            temp_high=_safe_float(_scan_forecasts(d, "highTemp")),
            temp_low=_safe_float(_scan_forecasts(d, "lowTemp")),
            description=_scan_forecasts(d, "statement"),
            rain_prob_1mm=_safe_float(_scan_forecasts(d, "rainFall1")),
            rain_prob_10mm=_safe_float(_scan_forecasts(d, "rainFall10")),
        )
        for d in raw_days
        if isinstance(d, dict)
    ]

    # Tomorrow's forecast is day index 1 of the 7-day data.
    tomorrow = daily_entries[1] if len(daily_entries) > 1 else None

    # ------------------------------------------------------------------
    # Marine — boating and surf stored nested under their own keys
    # ------------------------------------------------------------------
    boating = current.get("boating_data") or {}
    surf = current.get("surf_data") or {}

    # ------------------------------------------------------------------
    # Today's high/low — the current-conditions widget shows day 0's
    # forecast temps, so falling back to the forecast when there is no
    # weather station (rural locations) yields the same quantity.
    # ------------------------------------------------------------------
    temp_today_high = _safe_float(_get(obs, "temperature", "0", "high"))
    if temp_today_high is None:
        temp_today_high = _safe_float(_scan_forecasts(day0, "highTemp"))
    temp_today_low = _safe_float(_get(obs, "temperature", "0", "low"))
    if temp_today_low is None:
        temp_today_low = _safe_float(_scan_forecasts(day0, "lowTemp"))

    is_rural = str(day0.get("isRural", "")).lower() == "true"

    # ------------------------------------------------------------------
    # Moon phase date — MetService recomputes this per backend refresh with
    # second-level jitter; round to 5 minutes so state only changes when
    # the phase event actually advances. Log the raw value so prod debug
    # logs record the jitter series for upstream characterisation.
    # ------------------------------------------------------------------
    raw_phase_date = _get(moon_phases, "0", "dateISO")
    moon_phase_date = _round_iso_to_minutes(raw_phase_date)
    if moon_phase_date != raw_phase_date:
        _LOGGER.debug(
            "Moon phase dateISO %s rounded to %s", raw_phase_date, moon_phase_date
        )

    # ------------------------------------------------------------------
    # Assemble dataclass
    # ------------------------------------------------------------------
    data = MetServicePublicData(
        # Observations
        temperature=_safe_float(_get(obs, "temperature", "0", "current")),
        feels_like=_safe_float(_get(obs, "temperature", "0", "feelsLike")),
        temp_today_high=temp_today_high,
        temp_today_low=temp_today_low,
        humidity=_safe_int(_get(obs, "rain", "0", "relativeHumidity")),
        pressure=_safe_float(_get(obs, "pressure", "0", "atSeaLevel")),
        pressure_trend=_get(obs, "pressure", "0", "trend"),
        wind_speed=_safe_float(_get(obs, "wind", "0", "averageSpeed")),
        wind_gust=_safe_float(_get(obs, "wind", "0", "gustSpeed")),
        wind_direction=_get(obs, "wind", "0", "direction"),
        wind_strength=_get(obs, "wind", "0", "strength"),
        rainfall=_safe_float(_get(obs, "rain", "0", "rainfall")),
        # Today's forecast (day 0)
        condition=day0.get("condition"),
        forecast_text=_scan_forecasts(day0, "statement"),
        issued_at=day0.get("issuedAt"),
        uv_index=_get(uv, "sunProtection", "uvAlertLevel"),
        location_name=_get(current, "location", "label"),
        # Sub-day breakdown
        breakdown_morning=_get(breakdown0, "morning", "condition"),
        breakdown_afternoon=_get(breakdown0, "afternoon", "condition"),
        breakdown_evening=_get(breakdown0, "evening", "condition"),
        breakdown_overnight=_get(breakdown0, "overnight", "condition"),
        # Sun / moon
        sunrise=rise_set.get("sunRise"),
        sunset=rise_set.get("sunSet"),
        moonrise=rise_set.get("moonRise"),
        moonset=rise_set.get("moonSet"),
        moon_phase=_get(moon_phases, "0", "phase"),
        moon_phase_date=moon_phase_date,
        # Fire weather (from day 0's fireWeatherData)
        fire_danger=_get(
            day0, "fireWeatherData", "fireWeather", "danger", "dailyObservation"
        ),
        fire_season=_get(day0, "fireWeatherData", "fireWeather", "season", "short"),
        # Pollen (injected at root as {"pollenLevels": {...}})
        pollen_level=_get(current, "pollen", "pollenLevels", "level"),
        pollen_type=_get(current, "pollen", "pollenLevels", "type"),
        # Injected derived fields
        weather_warnings=current.get("weather_warnings", "No warnings"),
        warnings_list=current.get("warnings_list") or [],
        tomorrow_condition=tomorrow.condition if tomorrow else None,
        tomorrow_temp_high=tomorrow.temp_high if tomorrow else None,
        tomorrow_temp_low=tomorrow.temp_low if tomorrow else None,
        tomorrow_description=tomorrow.description if tomorrow else None,
        drying_morning=current.get("drying_morning"),
        drying_afternoon=current.get("drying_afternoon"),
        drying_next_good_day=current.get("drying_next_good_day"),
        # Capability flags
        has_observations=bool(obs),
        has_breakdown=bool(breakdown0),
        is_rural=is_rural,
        # Hourly
        hourly_entries=hourly_entries,
        hourly_obs=hourly_obs_count,
        hourly_skip=hourly_skip,
        # Daily
        daily_entries=daily_entries,
        # Tides (injected at root as a list)
        tides=current.get("tideImport"),
        # Boating (injected under "boating_data" key)
        boating_forecast=boating.get("boating_forecast"),
        boating_status=boating.get("boating_status"),
        boating_table=boating.get("boating_table"),
        # Surf (injected under "surf_data" key)
        surf_conditions=surf.get("surf_conditions"),
        surf_rating=surf.get("surf_rating"),
        surf_wave_height=surf.get("surf_wave_height"),
        surf_set_face=surf.get("surf_set_face"),
        surf_swell_direction=surf.get("surf_swell_direction"),
        surf_swell_height=surf.get("surf_swell_height"),
        surf_wind_direction=surf.get("surf_wind_direction"),
        surf_wind_speed=surf.get("surf_wind_speed"),
        surf_wind_gust=surf.get("surf_wind_gust"),
        surf_period=surf.get("surf_period"),
    )
    if obs:
        missing = [
            f
            for f in (
                "temperature",
                "feels_like",
                "humidity",
                "pressure",
                "wind_speed",
                "wind_gust",
                "wind_direction",
                "rainfall",
            )
            if getattr(data, f) is None
        ]
        if missing:
            _LOGGER.debug(
                "Observations block present but %s parsed to None — raw block: %.800s",
                missing,
                json.dumps(obs, default=str),
            )
    elif not is_rural:
        _LOGGER.debug(
            "Observations block empty/absent this cycle on a non-rural location; "
            "left-major module keys: %s",
            [sorted(m) if isinstance(m, dict) else str(type(m)) for m in left_major],
        )
    return data
