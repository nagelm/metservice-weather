# Coordinator Dataclass Refactor Plan — metservice_weather

## Problem

`get_from_dict` is a depth-first search, not an exact-path traversal. Given the path
`["observations", "temperature", "0", "current"]`, it walks the entire JSON tree looking
for any `observations` key, then any `temperature` key inside that, etc. In a deeply nested
tree with repeated key names this silently returns the wrong value.

`SENSOR_MAP_PUBLIC` encodes the intended paths as dotted strings but the DFS implementation
doesn't honour them as exact paths.

## Goal

Replace the DFS lookup chain with:
1. An exact-path normalizer that runs once at fetch time
2. A typed `MetServicePublicData` dataclass that is stored as `coordinator.data`
3. Sensor `value_fn` lambdas that receive the whole dataclass and pick their own field

## Files changed by phase

| Phase | Files touched |
|-------|--------------|
| 1 | `coordinator_types.py` (new), `tests/test_normalizer.py` (new) |
| 2 | `coordinator.py` |
| 3 | `weather_current_conditions_sensors.py`, `sensor.py` |
| 4 | `weather.py` |
| 5 | `coordinator.py`, `const.py` (cleanup) |

---

## Phase 1 — Define dataclass + normalizer (no existing code touched)

### New file: `custom_components/metservice_weather/coordinator_types.py`

```python
"""Typed data models for the MetService coordinator."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


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


@dataclass
class HourlyEntry:
    datetime: str
    temperature: float | None
    rainfall: float | None
    wind_speed: float | None
    wind_direction: str | None


@dataclass
class DailyEntry:
    datetime: str | None
    condition: str | None
    temp_high: str | None
    temp_low: str | None
    description: str | None
    rainfall_low: float | None
    rainfall_high: float | None


@dataclass
class MetServicePublicData:
    # Current observations
    temperature: float | None
    feels_like: float | None
    temp_today_high: float | None
    temp_today_low: float | None
    humidity: int | None
    pressure: float | None
    pressure_trend: str | None
    wind_speed: float | None
    wind_gust: float | None
    wind_direction: str | None
    wind_strength: str | None
    rainfall: float | None
    condition: str | None
    forecast_text: str | None
    issued_at: str | None
    uv_index: str | None
    location_name: str | None

    # Sub-day breakdown
    breakdown_morning: str | None
    breakdown_afternoon: str | None
    breakdown_evening: str | None
    breakdown_overnight: str | None

    # Sun / moon
    sunrise: str | None
    sunset: str | None
    moonrise: str | None
    moonset: str | None
    moon_phase: str | None
    moon_phase_date: str | None

    # Fire weather
    fire_danger: str | None
    fire_season: str | None

    # Pollen (injected)
    pollen_level: str | None
    pollen_type: str | None

    # Derived / injected
    weather_warnings: str
    tomorrow_condition: str | None
    tomorrow_temp_high: str | None
    tomorrow_temp_low: str | None
    tomorrow_description: str | None
    drying_morning: str | None
    drying_afternoon: str | None
    drying_next_good_day: str | None

    # Hourly forecast
    hourly_entries: list[HourlyEntry]
    hourly_obs: int | None
    hourly_skip: int | None

    # Daily forecast
    daily_entries: list[DailyEntry]

    # Optional marine (None when not configured)
    tides: Any | None = None
    boating_forecast: str | None = None
    boating_status: str | None = None
    boating_table: Any | None = None
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

    Uses exact-path traversal (_get) — no DFS.
    All injected fields (weather_warnings, pollen, tomorrow_*, drying_*)
    are already present at the root of `current` when this is called.
    """
    # Hourly entries
    hourly_raw = _get(current, "graph", "columns") or []
    hourly_skip = _get(current, "graph", "series", "0", "count") or 0
    hourly_obs = _get(current, "graph", "series", "1", "count") or 0
    hourly_entries = [
        HourlyEntry(
            datetime=h.get("date", ""),
            temperature=_safe_float(h.get("temperature")),
            rainfall=_safe_float(h.get("rainfall")),
            wind_speed=_safe_float(_get(h, "wind", "speed")),
            wind_direction=_get(h, "wind", "direction"),
        )
        for h in hourly_raw
    ]

    # Daily entries (from 7-day JSON)
    raw_days = _get(daily, "layout", "primary", "slots", "main", "modules", "0", "days") or []
    daily_entries = [
        DailyEntry(
            datetime=_get(d, "date"),
            condition=_get(d, "condition"),
            temp_high=_get(d, "forecasts", "0", "highTemp"),
            temp_low=_get(d, "forecasts", "0", "lowTemp"),
            description=_get(d, "forecasts", "0", "statement"),
            rainfall_low=_safe_float(_get(d, "rainFall1")),
            rainfall_high=_safe_float(_get(d, "rainFall10")),
        )
        for d in raw_days
    ]

    return MetServicePublicData(
        # Observations
        temperature=_safe_float(_get(current, "observations", "temperature", "0", "current")),
        feels_like=_safe_float(_get(current, "observations", "temperature", "0", "feelsLike")),
        temp_today_high=_safe_float(_get(current, "observations", "temperature", "0", "high")),
        temp_today_low=_safe_float(_get(current, "observations", "temperature", "0", "low")),
        humidity=_safe_int(_get(current, "observations", "rain", "0", "relativeHumidity")),
        pressure=_safe_float(_get(current, "observations", "pressure", "0", "atSeaLevel")),
        pressure_trend=_get(current, "observations", "pressure", "0", "trend"),
        wind_speed=_safe_float(_get(current, "observations", "wind", "0", "averageSpeed")),
        wind_gust=_safe_float(_get(current, "observations", "wind", "0", "gustSpeed")),
        wind_direction=_get(current, "observations", "wind", "0", "direction"),
        wind_strength=_get(current, "observations", "wind", "0", "strength"),
        rainfall=_safe_float(_get(current, "observations", "rain", "rainfall")),
        # Forecast
        condition=_get(current, "days", "0", "condition"),
        forecast_text=_get(current, "days", "0", "forecasts", "0", "statement"),
        issued_at=_get(current, "days", "0", "issuedAt"),
        uv_index=_get(current, "uv", "sunProtection", "uvAlertLevel"),
        location_name=_get(current, "location", "label"),
        # Sub-day breakdown
        breakdown_morning=_get(current, "breakdown", "morning", "condition"),
        breakdown_afternoon=_get(current, "breakdown", "afternoon", "condition"),
        breakdown_evening=_get(current, "breakdown", "evening", "condition"),
        breakdown_overnight=_get(current, "breakdown", "overnight", "condition"),
        # Sun / moon
        sunrise=_get(current, "riseSet", "sunRise"),
        sunset=_get(current, "riseSet", "sunSet"),
        moonrise=_get(current, "riseSet", "moonRise"),
        moonset=_get(current, "riseSet", "moonSet"),
        moon_phase=_get(current, "moonPhases", "0", "phase"),
        moon_phase_date=_get(current, "moonPhases", "0", "dateISO"),
        # Fire weather
        fire_danger=_get(current, "fireWeatherData", "fireWeather", "danger", "forecast"),
        fire_season=_get(current, "fireWeatherData", "fireWeather", "season", "short"),
        # Pollen (injected at root)
        pollen_level=_get(current, "pollen", "pollenLevels", "level"),
        pollen_type=_get(current, "pollen", "pollenLevels", "type"),
        # Injected derived fields
        weather_warnings=current.get("weather_warnings", "No warnings"),
        tomorrow_condition=current.get("tomorrow_condition"),
        tomorrow_temp_high=current.get("tomorrow_temp_high"),
        tomorrow_temp_low=current.get("tomorrow_temp_low"),
        tomorrow_description=current.get("tomorrow_description"),
        drying_morning=current.get("drying_morning"),
        drying_afternoon=current.get("drying_afternoon"),
        drying_next_good_day=current.get("drying_next_good_day"),
        # Hourly
        hourly_entries=hourly_entries,
        hourly_obs=hourly_obs,
        hourly_skip=hourly_skip,
        # Daily
        daily_entries=daily_entries,
        # Marine — populated separately by coordinator when configured
        tides=current.get("tideImport"),
        boating_forecast=current.get("boating_forecast"),
        boating_status=current.get("boating_status"),
        boating_table=current.get("boating_table"),
        surf_conditions=current.get("surf_conditions"),
        surf_rating=current.get("surf_rating"),
        surf_wave_height=current.get("surf_wave_height"),
        surf_set_face=current.get("surf_set_face"),
        surf_swell_direction=current.get("surf_swell_direction"),
        surf_swell_height=current.get("surf_swell_height"),
        surf_wind_direction=current.get("surf_wind_direction"),
        surf_wind_speed=current.get("surf_wind_speed"),
        surf_wind_gust=current.get("surf_wind_gust"),
        surf_period=current.get("surf_period"),
    )


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
```

### New file: `tests/test_normalizer.py`

Tests the normalizer in isolation against the Napier fixtures. These tests are
independent of the coordinator — they verify the exact-path extraction logic.

```python
import json
from pathlib import Path
import pytest
from custom_components.metservice_weather.coordinator_types import (
    normalize_public_data, MetServicePublicData, HourlyEntry, DailyEntry
)

FIXTURES = Path(__file__).parent / "fixtures"

@pytest.fixture(scope="module")
def napier():
    current = json.loads((FIXTURES / "napier_public_current.json").read_text())
    daily = json.loads((FIXTURES / "napier_public_daily.json").read_text())
    return normalize_public_data(current, daily)

def test_returns_correct_type(napier):
    assert isinstance(napier, MetServicePublicData)

def test_temperature_is_float(napier):
    assert isinstance(napier.temperature, float)
    assert -20 <= napier.temperature <= 50

def test_humidity_is_int(napier):
    assert isinstance(napier.humidity, int)
    assert 0 <= napier.humidity <= 100

def test_wind_direction_is_string(napier):
    assert isinstance(napier.wind_direction, str)

def test_condition_is_string(napier):
    assert isinstance(napier.condition, str)

def test_weather_warnings_is_string(napier):
    assert isinstance(napier.weather_warnings, str)

def test_pollen_level_present(napier):
    assert napier.pollen_level is not None

def test_tomorrow_fields_present(napier):
    assert napier.tomorrow_condition is not None
    assert napier.tomorrow_temp_high is not None

def test_hourly_entries_is_list(napier):
    assert isinstance(napier.hourly_entries, list)
    assert len(napier.hourly_entries) > 0
    assert isinstance(napier.hourly_entries[0], HourlyEntry)

def test_daily_entries_is_list(napier):
    assert isinstance(napier.daily_entries, list)
    assert 1 <= len(napier.daily_entries) <= 14
    assert isinstance(napier.daily_entries[0], DailyEntry)

def test_all_daily_entries_have_condition(napier):
    missing = [i for i, d in enumerate(napier.daily_entries) if d.condition is None]
    assert not missing, f"Days missing condition: {missing}"

def test_all_daily_entries_have_temp_high(napier):
    missing = [i for i, d in enumerate(napier.daily_entries) if d.temp_high is None]
    assert not missing, f"Days missing temp_high: {missing}"

def test_sunrise_is_string(napier):
    assert isinstance(napier.sunrise, str)

def test_moon_phase_is_string(napier):
    assert isinstance(napier.moon_phase, str)
```

**Verify Phase 1:** `wsl bash scripts/test.sh tests/test_normalizer.py -v`
All 53 existing tests still pass (nothing changed yet).

---

## Phase 2 — Wire coordinator to return the dataclass

**File: `coordinator.py`**

### 2a. Import the new types
```python
from .coordinator_types import MetServicePublicData, normalize_public_data
```

### 2b. Change `get_public_weather` return value
At the end of `get_public_weather`, replace:
```python
return {
    RESULTS_CURRENT: result_current,
    RESULTS_FORECAST_DAILY: result_daily,
}
```
with:
```python
return normalize_public_data(result_current, result_daily)
```

### 2c. Add compatibility shims
Keep `get_current_public` and `get_forecast_daily_public` working so all existing
tests and callers continue to pass. Replace their bodies with shim implementations
that read from the dataclass:

```python
# Temporary shim — remove in Phase 5
_PUBLIC_FIELD_MAP: dict[str, str] = {
    "temperature": "temperature",
    "temperatureFeelsLike": "feels_like",
    "temperature_today_high": "temp_today_high",
    "temperature_today_low": "temp_today_low",
    "relativeHumidity": "humidity",
    "pressureAltimeter": "pressure",
    "pressureTendencyTrend": "pressure_trend",
    "windSpeed": "wind_speed",
    "windGust": "wind_gust",
    "windDirection": "wind_direction",
    "wind_strength": "wind_strength",
    "rainfall": "rainfall",
    "condition": "condition",
    "wxPhraseLong": "forecast_text",
    "validTimeLocal": "issued_at",
    "uvIndex": "uv_index",
    "location_name": "location_name",
    "breakdown_morning": "breakdown_morning",
    "breakdown_afternoon": "breakdown_afternoon",
    "breakdown_evening": "breakdown_evening",
    "breakdown_overnight": "breakdown_overnight",
    "sunrise": "sunrise",
    "sunset": "sunset",
    "moonrise": "moonrise",
    "moonset": "moonset",
    "moon_phase": "moon_phase",
    "moon_phase_date": "moon_phase_date",
    "fire_danger": "fire_danger",
    "fire_season": "fire_season",
    "pollen_levels": "pollen_level",
    "pollen_type": "pollen_type",
    "weather_warnings": "weather_warnings",
    "tomorrow_condition": "tomorrow_condition",
    "tomorrow_temp_high": "tomorrow_temp_high",
    "tomorrow_temp_low": "tomorrow_temp_low",
    "tomorrow_description": "tomorrow_description",
    "drying_index_morning": "drying_morning",
    "drying_index_afternoon": "drying_afternoon",
    "drying_next_good_day": "drying_next_good_day",
    "hourly_temp": "hourly_entries",
    "hourly_timestamp": "hourly_entries",
    "hourly_obs": "hourly_obs",
    "hourly_skip": "hourly_skip",
    "hourly_bkp_temp": "hourly_entries",
    "hourly_bkp_obs": "hourly_obs",
    "hourly_bkp_skip": "hourly_skip",
    "tides_high": "tides",
    "tides_low": "tides",
    "boating_forecast": "boating_forecast",
    "boating_status": "boating_status",
    "boating_table": "boating_table",
    "surf_conditions": "surf_conditions",
    "surf_rating": "surf_rating",
    "surf_wave_height": "surf_wave_height",
    "surf_set_face": "surf_set_face",
    "surf_swell_direction": "surf_swell_direction",
    "surf_swell_height": "surf_swell_height",
    "surf_wind_direction": "surf_wind_direction",
    "surf_wind_speed": "surf_wind_speed",
    "surf_wind_gust": "surf_wind_gust",
    "surf_period": "surf_period",
}

def get_current_public(self, field: str):
    """Shim — delegates to dataclass attribute. Remove in Phase 5."""
    try:
        attr = _PUBLIC_FIELD_MAP.get(field, field)
        return getattr(self.data, attr, None)
    except Exception as e:
        _LOGGER.error("Error retrieving public sensor '%s': %s", field, e)
        return None

def get_forecast_daily_public(self, field: str, day: int):
    """Shim — delegates to dataclass daily_entries. Remove in Phase 5."""
    try:
        if field == "":
            return len(self.data.daily_entries)
        entry = self.data.daily_entries[day]
        daily_attr_map = {
            "daily_condition": "condition",
            "daily_temp_high": "temp_high",
            "daily_temp_low": "temp_low",
            "daily_datetime": "datetime",
            "daily_description": "description",
            "daily_rainfall_low": "rainfall_low",
            "daily_rainfall_high": "rainfall_high",
            "daily_bkp_temp_high": "temp_high",
            "daily_bkp_temp_low": "temp_low",
            "daily_bkp_datetime": "datetime",
        }
        attr = daily_attr_map.get(field, field)
        return getattr(entry, attr, None)
    except Exception as e:
        _LOGGER.error("Error retrieving public forecast '%s' day %s: %s", field, day, e)
        return None
```

### 2d. Update existing contract tests
`test_coordinator_data.py` currently does `coord.data = {RESULTS_CURRENT: current, RESULTS_FORECAST_DAILY: daily}`.
Update the fixture to use the normalizer:
```python
from custom_components.metservice_weather.coordinator_types import normalize_public_data

@pytest.fixture
def coord(napier_data):
    c = object.__new__(WeatherUpdateCoordinator)
    c.data = normalize_public_data(napier_data["current"], napier_data["daily"])
    return c
```

**Verify Phase 2:** All 53 + normalizer tests pass. `wsl bash scripts/test.sh -v`

---

## Phase 3 — Update sensors to use the dataclass directly

This is the largest phase. The goal: sensors receive `MetServicePublicData` in their
`value_fn` rather than a pre-extracted raw value.

### 3a. Change `WeatherRequiredKeysMixin` in `weather_current_conditions_sensors.py`
```python
# Before
value_fn: Callable[[Any, str], StateType]

# After
value_fn: Callable[[MetServicePublicData, str], StateType]
```

### 3b. Update every sensor definition's `value_fn`
Each lambda currently receives the raw value. Change it to receive the dataclass.

Examples:
```python
# Before
WeatherSensorEntityDescription(
    key="temperature",
    value_fn=lambda data, _: _safe_float(data),
)

# After
WeatherSensorEntityDescription(
    key="temperature",
    value_fn=lambda d, _: _safe_float(d.temperature),
)
```

Full mapping (key → dataclass attribute for each sensor definition):

| Sensor key | `value_fn` accesses |
|---|---|
| `validTimeLocal` | `d.issued_at` |
| `wxPhraseLong` | `d.forecast_text` |
| `relativeHumidity` | `d.humidity` |
| `uvIndex` | `d.uv_index` |
| `windDirection` | `d.wind_direction` |
| `temperatureFeelsLike` | `d.feels_like` |
| `temperature` | `d.temperature` |
| `temperature_today_high` | `d.temp_today_high` |
| `temperature_today_low` | `d.temp_today_low` |
| `pressureAltimeter` | `d.pressure` |
| `pressureTendencyTrend` | `d.pressure_trend` |
| `windSpeed` | `d.wind_speed` |
| `windGust` | `d.wind_gust` |
| `wind_strength` | `d.wind_strength` |
| `rainfall` | `d.rainfall` |
| `condition` | `d.condition` |
| `sunrise` / `sunset` | `d.sunrise` / `d.sunset` |
| `moonrise` / `moonset` | `d.moonrise` / `d.moonset` |
| `moon_phase` | `d.moon_phase` |
| `moon_phase_date` | `d.moon_phase_date` |
| `fire_danger` / `fire_season` | `d.fire_danger` / `d.fire_season` |
| `pollen_levels` | `d.pollen_level` |
| `pollen_type` | `d.pollen_type` |
| `weather_warnings` | `d.weather_warnings` |
| `tomorrow_*` | `d.tomorrow_condition` etc. |
| `drying_index_morning` | `d.drying_morning` |
| `drying_index_afternoon` | `d.drying_afternoon` |
| `drying_next_good_day` | `d.drying_next_good_day` |
| `breakdown_*` | `d.breakdown_morning` etc. |
| `hourly_temp` / `hourly_timestamp` | `d.hourly_entries` |
| `tides_high` / `tides_low` | `d.tides` |
| `boating_*` | `d.boating_forecast` etc. |
| `surf_*` | `d.surf_conditions` etc. |

### 3c. Update `sensor.py`

`_sensor_data` becomes the whole dataclass (not a per-field value):

```python
def __init__(self, coordinator, description):
    ...
    self._sensor_data = coordinator.data  # whole dataclass, not per-field

@callback
def _handle_coordinator_update(self):
    self._sensor_data = self.coordinator.data
    self.async_write_ha_state()
```

**Verify Phase 3:** `wsl bash scripts/test.sh -v` — all tests pass.
Also verify in dev HA: restart → check all sensors have correct values.

---

## Phase 4 — Update `weather.py` to use the dataclass

Replace all `coordinator.get_current_public(field)` and `coordinator.get_forecast_daily_public(field, day)`
calls with direct dataclass attribute access:

```python
# Current conditions
coordinator.data.temperature
coordinator.data.wind_speed
coordinator.data.wind_direction
coordinator.data.humidity
coordinator.data.pressure
coordinator.data.condition

# Hourly forecast
entries = coordinator.data.hourly_entries
skip = coordinator.data.hourly_skip
obs = coordinator.data.hourly_obs
for entry in entries[skip : skip + obs]:
    ...

# Daily forecast
for entry in coordinator.data.daily_entries:
    day_condition = entry.condition
    temp_high = entry.temp_high
    ...
```

**Verify Phase 4:** All tests pass. Dev HA: forecast cards show correctly.

---

## Phase 5 — Delete dead code

Once Phases 3 and 4 are complete, remove:

- `get_current_public()` method from coordinator
- `get_forecast_daily_public()` method from coordinator
- `get_from_dict()` method from coordinator
- `_PUBLIC_FIELD_MAP` dict from coordinator
- `SENSOR_MAP_PUBLIC` from `const.py` (and its import in coordinator)
- `RESULTS_CURRENT`, `RESULTS_FORECAST_DAILY` from `const.py` (and imports)
- `hourly_bkp_*` shim entries (already dead code, confirmed by fixture tests)
- `daily_bkp_*` shim entries (same)

Run `wsl bash scripts/lint.sh` to catch any remaining unused imports.

**Verify Phase 5:** `wsl bash scripts/test.sh -v` — all tests pass with no import errors.

---

## Mobile API

`get_current_mobile` and `get_forecast_daily_mobile` are out of scope for this refactor.
The mobile path can follow the same pattern (`MetServiceMobileData` + `normalize_mobile_data`)
in a separate piece of work. For now, the mobile shims remain untouched.

---

## Verification checklist (end of refactor)

- [ ] `wsl bash scripts/test.sh -v` — all tests pass
- [ ] `wsl bash scripts/lint.sh` — no errors
- [ ] No `get_from_dict` calls remain: `grep -r "get_from_dict" custom_components/`
- [ ] No `SENSOR_MAP_PUBLIC` references remain: `grep -r "SENSOR_MAP_PUBLIC" custom_components/`
- [ ] No `RESULTS_CURRENT` references remain: `grep -r "RESULTS_CURRENT" custom_components/`
- [ ] Dev HA: restart → all 38 entities present with correct values
- [ ] Dev HA: wait 20 min → coordinator refreshes → entities still correct

## Risk notes

- **Phase 3 is the most error-prone** — ~40 sensor definitions to update. Do it
  methodically: update one sensor, run tests, repeat. The shims from Phase 2 mean
  any missed sensor silently falls back rather than crashing.
- **The `observations.rain.rainfall` path has no list index** (unlike `observations.rain.0.relativeHumidity`).
  The fixture confirmed this resolves correctly — `_get(current, "observations", "rain", "rainfall")`.
  Double-check this specifically in `test_normalizer.py`.
- **`hourly_bkp_*` keys** are used in `weather.py` as fallbacks. Once weather.py uses
  `coordinator.data.hourly_entries` directly (Phase 4), these fallback paths are gone.
  Confirm in dev HA that hourly forecast still works after Phase 4.
