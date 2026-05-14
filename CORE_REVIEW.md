# metservice_weather — HA Core Submission Review

**Date:** 2026-05-14
**Version reviewed:** v0.9.19
**Verdict:** Not ready — requires significant work before opening a Core PR.
**Gold tier:** Achievable without an external library. External library is Platinum-only.

---

## Summary

The integration is well-built for a HACS custom component. The coordinator structure, test coverage (260 tests, 97%), error handling, and dataclass refactor are all solid. The gap to Core (Gold tier) is primarily translation infrastructure, icon declarations, manifest completeness, and a handful of correctness bugs — not fundamental design problems. The external library requirement is Platinum-only and does not block Gold.

---

## Tier A — Core PR blockers

### A1 · No external PyPI library *(Platinum only — does NOT block Gold)*
All HTTP I/O lives inside the integration. Platinum requires a separately installable package (e.g. `pymetservice-nz`). Every network call in `coordinator.py` and `config_flow.py` must move there. No workaround at Platinum.

### A2 · `manifest.json` missing required fields *(blocks Gold)*
`requirements` (must be `[]`), `integration_type` (`"service"`), and `quality_scale` are all absent. CI fails immediately. Also: `version` key must be **removed** for Core (HACS-only field).

### A3 · `async_timeout` package used everywhere *(blocks Gold)*
Core requires `asyncio.timeout` (stdlib, Python 3.11+). Every `import async_timeout` and usage in `coordinator.py` and `config_flow.py` must be replaced.

### A4 · `with async_timeout.timeout()` is a runtime bug *(blocks Gold)*
In `config_flow.py` (6 occurrences), timeout is applied via sync `with` on an async CM — it silently does nothing. Timeouts are not enforced in the config flow. Fix: `async with asyncio.timeout(...)`.

### A5 · No `translation_key` on any sensor; no `entity` section in `strings.json` *(blocks Gold)*
Gold requires translatable entity names. All 40+ sensor descriptions use hardcoded English `name` strings. Each description needs a `translation_key`; `strings.json` and `en.json` need an `entity.sensor` section.

### A6 · `icons.json` absent *(blocks Gold)*
Gold requires icon declarations in `icons.json`. All icon specs are currently inline Python (`icon=` fields in `weather_current_conditions_sensors.py`).

### A7 · Mobile API path is not Core-quality *(blocks Gold)*
Dict-based DFS (`get_from_dict`), `SENSOR_MAP_MOBILE` string keys, `dict[str, Any]` coordinator data — cannot pass strict-typing review. Options: full dataclass migration (high effort) or remove mobile path from Core PR scope.

### A8 · No `async_migrate_entry` *(blocks Gold)*
`VERSION = 1` is declared in config flow but no migration function exists. Core requires a migration path. At minimum a stub that handles `VERSION == 1` is needed.

### A9 · Non-standard keys in `Forecast` TypedDict *(blocks Gold)*
`"description"`, `"precipitation_low_mm"`, `"precipitation_high_mm"` in daily forecast entries fail Core's TypedDict validation. Extra data must go in `extra_state_attributes` or a separate service.

### A10 · Unique IDs derived from mutable display name *(blocks Gold)*
`f"{coordinator.location_name},{...}"` uses `entry.data[CONF_NAME]` (user-editable). Renaming the entry or reconfiguring orphans all entities. Must use a stable immutable identifier (e.g. canonical location path slug).

---

## Tier B — Flagged in first-pass review

| # | Issue | File | Effort |
|---|-------|------|--------|
| B1 | `abort.reconfigure_successful` missing from `strings.json` — success screen shows raw key | `strings.json`, `en.json` | Trivial |
| B2 | `from __future__ import annotations` missing | `__init__.py`, `weather.py`, `const.py` | Trivial |
| B3 | `async_create_clientsession` leaks a session per config flow; use `async_get_clientsession` | `config_flow.py` | Low |
| B4/B5 | `WeatherSensor.__init__` calls `get_current_mobile()` at init time — stale/`None` on mobile path; init `_sensor_data = None` instead | `sensor.py` | Low |
| B6 | `WeatherSensorEntityDescription` not `frozen=True, kw_only=True` | `weather_current_conditions_sensors.py` | Low |
| B7 | Daily forecast `ATTR_FORECAST_TIME` not passed through `_format_timestamp` — local time vs UTC inconsistency with hourly | `weather.py` | Low |
| B8 | `self.coordinator._format_timestamp(...)` called from entity — private coordinator method accessed outside coordinator | `weather.py` | Low |
| B9 | `safe_float` duplicated: defined in `weather.py` and `_safe_float` in `weather_current_conditions_sensors.py` | both files | Low |
| B10 | `if(entry.data["api"] == "mobile"):` — unnecessary parentheses | `weather.py:65` | Trivial |
| B11 | `@ciejer` listed as codeowner — original fork author; Core requires active maintainers (respond within 30 days) | `.github/CODEOWNERS` | Low |

---

## Tier C — Nice-to-haves (not blockers)

- Extract a shared `MetServiceEntity` base class (avoid duplicate `DeviceInfo` in `sensor.py` and `weather.py`)
- Add `model` and `configuration_url` to `DeviceInfo`
- Add `suggested_display_precision` to numeric sensor descriptions
- Remove the `_update_listener` reload mechanism (no options flow exists; fires on every config update)
- Split `DataUpdateCoordinator[MetServicePublicData | dict[str, Any]]` into two separate typed coordinators
- Implement `_async_setup` for one-time initialisation instead of inline on every poll
- Type `tides: Any | None` and `boating_table: Any | None` concretely in `MetServicePublicData`
- `Forecast({...})` dict constructor → keyword-argument form `Forecast(datetime=..., ...)`
- Daily forecast `ATTR_FORECAST_TIME` UTC normalisation (related to B7)

---

## Phased remediation plan

### Phase 1 — Gold tier + all Tier B fixes
*Achieves IQS Gold. No external library needed.*

1. **manifest.json**: add `requirements: []`, `integration_type: "service"`, `quality_scale: "gold"`; remove `version`
2. **asyncio.timeout**: replace all `async_timeout` imports and usages in `coordinator.py` and `config_flow.py`; fix sync `with` → `async with` in config_flow.py (6 occurrences)
3. **Translation keys**: add `translation_key` to every `WeatherSensorEntityDescription`; add `entity.sensor` section to `strings.json` + `en.json`
4. **icons.json**: create with all entity icon declarations; remove `icon=` from Python descriptions
5. **async_migrate_entry**: add stub function handling `VERSION == 1`
6. **Forecast cleanup**: remove `"description"`, `"precipitation_low_mm"`, `"precipitation_high_mm"` from `Forecast` dicts; expose via `extra_state_attributes` on the weather entity
7. **Stable unique IDs**: derive from canonical location path slug, not display name
8. **strings.json**: add `abort.reconfigure_successful`; remove dead `unknown_error` key
9. **`from __future__ import annotations`**: add to `__init__.py`, `weather.py`, `const.py`
10. **`async_get_clientsession`**: replace `async_create_clientsession` in `config_flow.py`
11. **Sensor mobile init**: change `WeatherSensor.__init__` to `self._sensor_data = None`
12. **Frozen description dataclass**: add `frozen=True, kw_only=True` to `WeatherSensorEntityDescription`
13. **Daily forecast UTC**: pass daily `ATTR_FORECAST_TIME` through `_format_timestamp`
14. **`_format_timestamp` extraction**: move to a utility module; update all callers
15. **`safe_float` dedup**: consolidate into one implementation in the utility module
16. **Syntax fix**: `if(entry.data` → `if entry.data` in `weather.py:65`
17. **CODEOWNERS**: remove or confirm `@ciejer`; ensure only active maintainers listed

### Phase 2 — Mobile path decision
*Unblocks Core PR submission.*

- **Option A (recommended):** Remove mobile path from Core PR scope. Keep on a HACS-only branch. Add a clear comment in `config_flow.py` and `coordinator.py` marking mobile as HACS-only. Removes `get_from_dict`, `SENSOR_MAP_MOBILE`, `get_current_mobile`, `get_forecast_daily_mobile`, `MetServiceMobile`, `MetServiceForecastMobile` from the Core submission.
- **Option B:** Migrate mobile path to a `MetServiceMobileData` dataclass at parity with the public path (significant effort — weeks).

### Phase 3 — Low-to-medium effort Platinum changes *(no external library)*

1. Shared `MetServiceEntity` base class (dedup `DeviceInfo`)
2. `model` and `configuration_url` in `DeviceInfo`
3. `suggested_display_precision` on all numeric sensors
4. Remove `_update_listener` reload mechanism
5. Split coordinator into two separate typed coordinators (one per API path)
6. Add `_async_setup` for one-time location verification
7. Type `tides`, `boating_table`, and mobile coordinator data concretely
8. `Forecast` keyword-argument construction

### Phase 4 — External library + high-effort Platinum

1. Create `pymetservice-nz` (or equivalent) PyPI package
2. Move all HTTP logic from `coordinator.py` into the library
3. Move all HTTP logic from `config_flow.py` into the library
4. Pin the library in `manifest.json` `requirements`
5. Migrate mobile path to library (if not removed in Phase 2)
6. Set `quality_scale: "platinum"` in manifest

---

## Key file locations

| File | Role |
|------|------|
| `custom_components/metservice_weather/manifest.json` | Version, requirements, integration_type, quality_scale |
| `custom_components/metservice_weather/coordinator.py` | DataUpdateCoordinator, HTTP fetch, async_timeout |
| `custom_components/metservice_weather/coordinator_types.py` | MetServicePublicData dataclass, normalize_public_data |
| `custom_components/metservice_weather/config_flow.py` | Config flow, reconfigure, reauth, async_timeout bug |
| `custom_components/metservice_weather/sensor.py` | 40+ CoordinatorEntity sensors, WeatherSensorEntityDescription |
| `custom_components/metservice_weather/weather.py` | Weather entity, forecast caching, Forecast TypedDict |
| `custom_components/metservice_weather/weather_current_conditions_sensors.py` | Sensor descriptions, value_fn lambdas, icons |
| `custom_components/metservice_weather/strings.json` | Config flow strings, error keys, translations |
| `custom_components/metservice_weather/translations/en.json` | English locale (mirrors strings.json, needs entity.sensor section) |
| `.github/CODEOWNERS` | Codeowner declarations |
