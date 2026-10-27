"""Typed data models for the MetService coordinator."""

from __future__ import annotations

import contextlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from homeassistant.util import dt as dt_util

from .const import CONDITION_MAP

_LOGGER = logging.getLogger(__name__)

_PRECIPITATION_HA_CONDITIONS = {
    "rainy",
    "pouring",
    "hail",
    "snowy",
    "snowy-rainy",
    "lightning",
    "lightning-rainy",
}


def _round_iso_to_minutes(iso: Any, resolution_minutes: int = 5) -> Any:
    """Round an ISO timestamp string to the nearest N minutes."""
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
    """Exact-path traversal — no depth-first search."""
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


_CLOCK_TIME_RE = re.compile(r"\d{1,2}:\d{2}\s*[AaPp][Mm]")


def _parse_clock_time(clock: str | None, reference: datetime | None) -> str | None:
    """Combine a bare MetService clock string with reference's date and tz."""
    if not clock or reference is None:
        return None
    compact = re.sub(r"\s+", "", clock)
    try:
        parsed_time = datetime.strptime(compact, "%I:%M%p").time()
    except ValueError:
        return None
    return reference.replace(
        hour=parsed_time.hour,
        minute=parsed_time.minute,
        second=0,
        microsecond=0,
    ).isoformat()


def _extract_clock_token(text: Any) -> str | None:
    """Pull the first bare "H:MMam/pm" token out of a longer string."""
    if not isinstance(text, str):
        return None
    match = _CLOCK_TIME_RE.search(text)
    return match.group(0) if match else None


def _find_module(modules: list, key: str) -> dict:
    """Return the first module dict that contains `key`, or {}."""
    for m in modules:
        if isinstance(m, dict) and key in m:
            return m
    return {}


def _scan_forecasts(day: Any, key: str) -> Any:
    """Return the first non-None `key` from forecasts entries, else the day level."""
    if not isinstance(day, dict):
        return None
    for f in day.get("forecasts") or []:
        if isinstance(f, dict) and f.get(key) is not None:
            return f[key]
    return day.get(key)


_MOON_PHASE_PRINCIPAL_MAP: dict[str, str] = {
    "NEW": "new_moon",
    "FIRST": "first_quarter",
    "FULL": "full_moon",
    "LAST": "last_quarter",
}
_MOON_PHASE_INTERMEDIATE_MAP: dict[str, str] = {
    "FIRST": "waxing_crescent",
    "FULL": "waxing_gibbous",
    "LAST": "waning_gibbous",
    "NEW": "waning_crescent",
}


def _moon_phase_current(moon_phases: Any, reference: datetime | None) -> str | None:
    """Derive the current-moon-phase ENUM state from MetService's moonPhases list."""
    if not moon_phases or reference is None:
        return None
    next_event = moon_phases[0]
    if not isinstance(next_event, dict):
        return None
    phase_token = next_event.get("phase")
    date_iso = next_event.get("dateISO")
    if not isinstance(date_iso, str):
        return None
    try:
        event_date = datetime.fromisoformat(date_iso).date()
    except ValueError:
        return None
    if event_date == reference.date():
        return _MOON_PHASE_PRINCIPAL_MAP.get(phase_token)
    return _MOON_PHASE_INTERMEDIATE_MAP.get(phase_token)


_POLLEN_CLASS_TO_STATE = {"good": "low", "medium": "moderate", "bad": "high"}
_POLLEN_STATE_RANK = {"low": 1, "moderate": 2, "high": 3}
_UNKNOWN_POLLEN_CLASSES_LOGGED: set[str] = set()
_POLLEN_LABEL_DRIFT_LOGGED: set[str] = set()


def _next_rain_from_daily(
    daily_entries: list[DailyEntry],
    now: datetime,
    last_hourly: datetime | None,
) -> str | None:
    """First future day whose condition MetService itself draws as precipitation."""
    for day in daily_entries:
        if CONDITION_MAP.get(day.condition or "") not in _PRECIPITATION_HA_CONDITIONS:
            continue
        if not day.datetime:
            continue
        try:
            day_dt = datetime.fromisoformat(day.datetime)
        except (ValueError, TypeError):
            continue
        if day_dt.date() < now.date():
            continue
        if last_hourly is not None and day_dt.date() < last_hourly.date():
            continue
        return day.datetime
    return None


def _derive_pollen(
    groups: list[dict[str, str | None]],
) -> tuple[str | None, dict[str, list[str]], list[str]]:
    """Derive the one-sensor pollen model from raw MetService status groups."""
    if not groups:
        return None, {}, []

    active: dict[str, list[str]] = {}
    imminent: list[str] = []

    for group in groups:
        cls = group.get("status_class")
        allergens = [
            t.strip() for t in (group.get("type") or "").split(",") if t.strip()
        ]
        if cls == "medium-good":
            imminent.extend(allergens)
        elif cls in _POLLEN_CLASS_TO_STATE:
            state = _POLLEN_CLASS_TO_STATE[cls]
            active.setdefault(state, []).extend(allergens)
            label = (group.get("level") or "").strip()
            if (
                label
                and label.lower() != state
                and label not in _POLLEN_LABEL_DRIFT_LOGGED
            ):
                _POLLEN_LABEL_DRIFT_LOGGED.add(label)
                _LOGGER.warning(
                    "MetService pollen label %r doesn't match its status class "
                    "%r — please report at "
                    "https://github.com/nagelm/metservice-weather/issues",
                    label,
                    cls,
                )
        elif cls == "none" or cls is None:
            continue
        elif cls not in _UNKNOWN_POLLEN_CLASSES_LOGGED:
            _UNKNOWN_POLLEN_CLASSES_LOGGED.add(cls)
            _LOGGER.warning(
                "Unknown MetService pollen status class %r — please report at "
                "https://github.com/nagelm/metservice-weather/issues",
                cls,
            )

    if not active:
        return "none", active, imminent

    best_state = max(active, key=lambda s: _POLLEN_STATE_RANK[s])
    return best_state, active, imminent


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
    """Single daily forecast entry."""

    datetime: str | None = None
    condition: str | None = None
    temp_high: float | None = None
    temp_low: float | None = None
    description: str | None = None
    rain_prob_1mm: float | None = None
    rain_prob_10mm: float | None = None
    rain_total_mm: float | None = None


@dataclass
class MetServicePublicData:
    """Normalised snapshot of public API data for one polling cycle."""

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

    uv_status_class: str | None = None
    uv_alert_level: str | None = None
    uv_message: str | None = None
    uv_has_alert: bool | None = None
    uv_window_start_raw: str | None = None
    uv_window_end_raw: str | None = None
    uv_window_start_at: str | None = None
    uv_window_end_at: str | None = None

    breakdown_morning: str | None = None
    breakdown_afternoon: str | None = None
    breakdown_evening: str | None = None
    breakdown_overnight: str | None = None

    sunrise: str | None = None
    sunset: str | None = None
    moonrise: str | None = None
    moonset: str | None = None
    moon_phase: str | None = None
    moon_phase_date: str | None = None
    moon_phase_current: str | None = None
    sunrise_at: str | None = None
    sunset_at: str | None = None
    moonrise_at: str | None = None
    moonset_at: str | None = None

    fire_danger: str | None = None
    fire_season: str | None = None
    fire_season_status: str | None = None
    fire_season_short: str | None = None
    fire_season_text: str | None = None
    fire_danger_index: int | None = None
    fire_danger_text: str | None = None
    fire_danger_forecast: str | None = None

    pollen_level: str | None = None
    pollen_type: str | None = None
    pollen_groups: list[dict[str, str | None]] = field(default_factory=list)

    pollen_state: str | None = None  # none | low | moderate | high
    pollen_active: dict[str, list[str]] = field(default_factory=dict)
    pollen_imminent: list[str] = field(default_factory=list)

    weather_warnings: str = "No warnings"
    warnings_list: list[dict[str, str]] = field(default_factory=list)
    tomorrow_condition: str | None = None
    tomorrow_temp_high: float | None = None
    tomorrow_temp_low: float | None = None
    tomorrow_description: str | None = None
    drying_morning: str | None = None
    drying_afternoon: str | None = None
    drying_next_good_day: str | None = None

    has_observations: bool = False
    has_breakdown: bool = False
    is_rural: bool = False

    hourly_entries: list[HourlyEntry] = field(default_factory=list)
    hourly_obs: int | None = None
    hourly_skip: int | None = None

    rain_next_8h_mm: float | None = None
    rain_next_24h_mm: float | None = None
    next_rain_at: str | None = None
    next_rain_precision: str | None = None  # "hour" | "day"
    rain_forecast_horizon: str | None = None  # last daily-forecast day searched

    daily_entries: list[DailyEntry] = field(default_factory=list)

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


def normalize_public_data(
    current: dict, daily: dict, now: datetime | None = None
) -> MetServicePublicData:
    """Build a MetServicePublicData from raw coordinator dicts."""
    now = now or dt_util.now()

    left_major = (
        _get(current, "layout", "primary", "slots", "left-major", "modules") or []
    )
    obs = _find_module(left_major, "observations").get("observations") or {}

    main_mods = _get(current, "layout", "primary", "slots", "main", "modules") or []
    days = _find_module(main_mods, "days").get("days") or []
    day0 = days[0] if days and isinstance(days[0], dict) else {}
    breakdown0 = day0.get("breakdown") or {}

    graph_module = _find_module(main_mods, "graph")
    graph = graph_module.get("graph", {})
    graph_series = graph.get("series") or []
    hourly_skip = graph_series[0].get("count", 0) if graph_series else 0
    hourly_obs_count = graph_series[1].get("count", 0) if len(graph_series) > 1 else 0

    left_minor = (
        _get(current, "layout", "primary", "slots", "left-minor", "modules") or []
    )
    uv = _find_module(left_minor, "uv").get("uv", {})

    secondary = _get(current, "layout", "secondary", "slots", "major", "modules") or []
    rise_mod = _find_module(secondary, "riseSet")
    rise_set = rise_mod.get("riseSet", {})
    moon_phases = rise_mod.get("moonPhases", [])

    issued_at_raw = day0.get("issuedAt")
    try:
        issued_at_reference = (
            datetime.fromisoformat(issued_at_raw) if issued_at_raw else None
        )
    except (ValueError, TypeError):
        issued_at_reference = None

    sunrise_at = _parse_clock_time(rise_set.get("sunRise"), issued_at_reference)
    sunset_at = _parse_clock_time(rise_set.get("sunSet"), issued_at_reference)
    moonrise_at = _parse_clock_time(rise_set.get("moonRise"), issued_at_reference)
    moonset_at = _parse_clock_time(rise_set.get("moonSet"), issued_at_reference)

    uv_status_raw = _get(uv, "sunProtection", "status")
    uv_status_class = (
        uv_status_raw.removeprefix("status-")
        if isinstance(uv_status_raw, str)
        else None
    )
    uv_alert_level = _get(uv, "sunProtection", "uvAlertLevel")
    uv_message_raw = _get(uv, "sunProtection", "uvMessage")
    uv_message = (
        ". ".join(str(item) for item in uv_message_raw)
        if isinstance(uv_message_raw, list) and uv_message_raw
        else None
    )
    uv_has_alert_raw = _get(uv, "sunProtection", "uvHasAlert")
    uv_has_alert = uv_has_alert_raw if isinstance(uv_has_alert_raw, bool) else None
    uv_start_time_raw = _get(uv, "sunProtection", "uvStartTime")
    uv_end_time_raw = _get(uv, "sunProtection", "uvEndTime")
    uv_window_start_raw = (
        uv_start_time_raw
        if isinstance(uv_start_time_raw, str) and "undefined" not in uv_start_time_raw
        else None
    )
    uv_window_end_raw = (
        uv_end_time_raw
        if isinstance(uv_end_time_raw, str) and "undefined" not in uv_end_time_raw
        else None
    )
    uv_window_start_at = _parse_clock_time(
        _extract_clock_token(uv_start_time_raw), issued_at_reference
    )
    uv_window_end_at = _parse_clock_time(
        _extract_clock_token(uv_end_time_raw), issued_at_reference
    )

    day1 = days[1] if len(days) > 1 and isinstance(days[1], dict) else {}
    fire_season_status_raw = _get(
        day0, "fireWeatherData", "fireWeather", "season", "status"
    )
    fire_season_status = (
        fire_season_status_raw.lower()
        if isinstance(fire_season_status_raw, str)
        else None
    )
    fire_season_short = _get(day0, "fireWeatherData", "fireWeather", "season", "short")
    fire_season_text = _get(day0, "fireWeatherData", "fireWeather", "season", "text")
    fire_danger_index = _safe_int(
        _get(day0, "fireWeatherData", "fireWeather", "danger", "dailyObservationIndex")
    )
    fire_danger_text = _get(day0, "fireWeatherData", "fireWeather", "danger", "text")
    fire_danger_forecast = _get(
        day1, "fireWeatherData", "fireWeather", "danger", "forecast"
    )

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

    observed_hourly = hourly_entries[:hourly_skip]
    forecast_hourly = hourly_entries[hourly_skip : hourly_skip + hourly_obs_count]
    hour_mm: dict[Any, float | None] = {}
    for slice_entries in (forecast_hourly, observed_hourly):
        for h in slice_entries:
            if not h.datetime:
                continue
            try:
                parsed = datetime.fromisoformat(h.datetime)
            except ValueError:
                continue
            hour_mm[parsed] = h.rainfall

    rain_sums: dict[Any, float] = {}
    rain_counts: dict[Any, int] = {}
    for parsed, rainfall in hour_mm.items():
        day_key = parsed.date()
        rain_sums[day_key] = rain_sums.get(day_key, 0.0) + (rainfall or 0)
        rain_counts[day_key] = rain_counts.get(day_key, 0) + 1

    for entry in daily_entries:
        if not entry.datetime:
            continue
        try:
            entry_date = datetime.fromisoformat(entry.datetime).date()
        except ValueError:
            continue
        if rain_counts.get(entry_date, 0) >= 20:
            entry.rain_total_mm = round(rain_sums[entry_date], 1)

    with contextlib.suppress(Exception):
        notes = graph_module.get("notes") or []
        note_text = " ".join(n.get("text", "") for n in notes if isinstance(n, dict))
        match = re.search(
            r"Total rainfall forecast for today:\s*([0-9.]+)\s*mm", note_text
        )
        if match and daily_entries and daily_entries[0].rain_total_mm is not None:
            ours = daily_entries[0].rain_total_mm
            theirs = float(match.group(1))
            if abs(ours - theirs) > 1.5:
                _LOGGER.debug(
                    "Daily rainfall aggregation cross-check: summed %.1f mm vs "
                    "MetService note %.1f mm",
                    ours,
                    theirs,
                )

    now_floor = now.replace(minute=0, second=0, microsecond=0)
    future_hourly: list[tuple[datetime, HourlyEntry]] = []
    for h in forecast_hourly:
        if not h.datetime:
            continue
        try:
            parsed = datetime.fromisoformat(h.datetime)
            if parsed < now_floor:
                continue
        except (ValueError, TypeError):
            continue
        future_hourly.append((parsed, h))
    future_hourly.sort(key=lambda pair: pair[0])

    rain_next_8h_mm = (
        round(sum((h.rainfall or 0) for _, h in future_hourly[:8]), 1)
        if len(future_hourly) >= 8
        else None
    )
    rain_next_24h_mm = (
        round(sum((h.rainfall or 0) for _, h in future_hourly[:24]), 1)
        if len(future_hourly) >= 24
        else None
    )
    next_rain_at = next(
        (
            h.datetime
            for _, h in future_hourly
            if h.rainfall is not None and h.rainfall > 0
        ),
        None,
    )
    next_rain_precision = "hour" if next_rain_at is not None else None

    if next_rain_at is None:
        last_hourly = future_hourly[-1][0] if future_hourly else None
        next_rain_at = _next_rain_from_daily(daily_entries, now, last_hourly)
        if next_rain_at is not None:
            next_rain_precision = "day"

    rain_forecast_horizon = (
        (daily_entries[-1].datetime or None) if daily_entries else None
    )

    tomorrow = daily_entries[1] if len(daily_entries) > 1 else None

    boating = current.get("boating_data") or {}
    surf = current.get("surf_data") or {}

    temp_today_high = _safe_float(_get(obs, "temperature", "0", "high"))
    if temp_today_high is None:
        temp_today_high = _safe_float(_scan_forecasts(day0, "highTemp"))
    temp_today_low = _safe_float(_get(obs, "temperature", "0", "low"))
    if temp_today_low is None:
        temp_today_low = _safe_float(_scan_forecasts(day0, "lowTemp"))

    is_rural = str(day0.get("isRural", "")).lower() == "true"

    pollen_groups = current.get("pollen", {}).get("groups") or []
    pollen_state, pollen_active, pollen_imminent = _derive_pollen(pollen_groups)

    raw_phase_date = _get(moon_phases, "0", "dateISO")
    moon_phase_date = _round_iso_to_minutes(raw_phase_date)
    if moon_phase_date != raw_phase_date:
        _LOGGER.debug(
            "Moon phase dateISO %s rounded to %s", raw_phase_date, moon_phase_date
        )
    moon_phase_current = _moon_phase_current(moon_phases, issued_at_reference)

    data = MetServicePublicData(
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
        condition=day0.get("condition"),
        forecast_text=_scan_forecasts(day0, "statement"),
        issued_at=day0.get("issuedAt"),
        uv_index=_get(uv, "sunProtection", "uvAlertLevel"),
        location_name=_get(current, "location", "label"),
        uv_status_class=uv_status_class,
        uv_alert_level=uv_alert_level,
        uv_message=uv_message,
        uv_has_alert=uv_has_alert,
        uv_window_start_raw=uv_window_start_raw,
        uv_window_end_raw=uv_window_end_raw,
        uv_window_start_at=uv_window_start_at,
        uv_window_end_at=uv_window_end_at,
        breakdown_morning=_get(breakdown0, "morning", "condition"),
        breakdown_afternoon=_get(breakdown0, "afternoon", "condition"),
        breakdown_evening=_get(breakdown0, "evening", "condition"),
        breakdown_overnight=_get(breakdown0, "overnight", "condition"),
        sunrise=rise_set.get("sunRise"),
        sunset=rise_set.get("sunSet"),
        moonrise=rise_set.get("moonRise"),
        moonset=rise_set.get("moonSet"),
        moon_phase=_get(moon_phases, "0", "phase"),
        moon_phase_date=moon_phase_date,
        moon_phase_current=moon_phase_current,
        sunrise_at=sunrise_at,
        sunset_at=sunset_at,
        moonrise_at=moonrise_at,
        moonset_at=moonset_at,
        fire_danger=_get(
            day0, "fireWeatherData", "fireWeather", "danger", "dailyObservation"
        ),
        fire_season=_get(day0, "fireWeatherData", "fireWeather", "season", "short"),
        fire_season_status=fire_season_status,
        fire_season_short=fire_season_short,
        fire_season_text=fire_season_text,
        fire_danger_index=fire_danger_index,
        fire_danger_text=fire_danger_text,
        fire_danger_forecast=fire_danger_forecast,
        pollen_level=_get(current, "pollen", "pollenLevels", "level"),
        pollen_type=_get(current, "pollen", "pollenLevels", "type"),
        pollen_groups=pollen_groups,
        pollen_state=pollen_state,
        pollen_active=pollen_active,
        pollen_imminent=pollen_imminent,
        weather_warnings=current.get("weather_warnings", "No warnings"),
        warnings_list=current.get("warnings_list") or [],
        tomorrow_condition=tomorrow.condition if tomorrow else None,
        tomorrow_temp_high=tomorrow.temp_high if tomorrow else None,
        tomorrow_temp_low=tomorrow.temp_low if tomorrow else None,
        tomorrow_description=tomorrow.description if tomorrow else None,
        drying_morning=current.get("drying_morning"),
        drying_afternoon=current.get("drying_afternoon"),
        drying_next_good_day=current.get("drying_next_good_day"),
        has_observations=bool(obs),
        has_breakdown=bool(breakdown0),
        is_rural=is_rural,
        hourly_entries=hourly_entries,
        hourly_obs=hourly_obs_count,
        hourly_skip=hourly_skip,
        rain_next_8h_mm=rain_next_8h_mm,
        rain_next_24h_mm=rain_next_24h_mm,
        next_rain_at=next_rain_at,
        next_rain_precision=next_rain_precision,
        rain_forecast_horizon=rain_forecast_horizon,
        daily_entries=daily_entries,
        tides=current.get("tideImport"),
        boating_forecast=boating.get("boating_forecast"),
        boating_status=boating.get("boating_status"),
        boating_table=boating.get("boating_table"),
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
