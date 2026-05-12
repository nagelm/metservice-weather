> **This is a personal fork of [ciejer/metservice-weather](https://github.com/ciejer/metservice-weather), which is the original and primary work. Full credit to [@ciejer](https://github.com/ciejer) for building and maintaining this integration. This fork applies a collection of open issues, PRs, and quality improvements that have not yet landed upstream.**

---

## What's included from upstream (ciejer/metservice-weather)

All upstream changes through the point of forking are included, covering the full development history of the integration:

- **Mobile API support** — parallel mobile and public API implementations with separate config flows
- **Tides integration** — configurable tide location selection via a multi-step config flow with region and location pickers
- **Hourly and daily forecasts** — full `WeatherEntityFeature.FORECAST_HOURLY` and `FORECAST_DAILY` support
- **Weather warnings and fire danger** — live warnings fetched from the MetService warnings service and surfaced as sensors
- **Pollen, drying index, UV, pressure trend** — extended sensor set well beyond the core weather fields
- **Dynamic `dataUrl` expansion** — recursive fetching of MetService's lazily-loaded nested API structure
- **Rural/regional location support** — backup data paths for locations that structure API responses differently
- **Device grouping** — all entities grouped under a single HA device ([#109](https://github.com/ciejer/metservice-weather/pull/109))
- **Reduced logging verbosity** — debug-level logging for non-critical paths ([#95](https://github.com/ciejer/metservice-weather/pull/95))
- **HACS compatibility** — zip-based release workflow, country code, hacsfest validation

---

## Changes in this fork (nagelm/metservice-weather)

### Fixes for open upstream issues and PRs

- **Fix entity ID collisions breaking HA 2026.2+** — removed `generate_entity_id()` calls that produced invalid entity IDs; entities now rely solely on `unique_id` as intended by HA. Resolves [#157](https://github.com/ciejer/metservice-weather/issues/157)

- **Fix `clear-night` condition never appearing** — when the current condition maps to `sunny` but the sun is below the horizon, the weather entity now correctly returns `clear-night`. Resolves [#152](https://github.com/ciejer/metservice-weather/issues/152)

- **Fix tides config flow crashing on setup** — the marine region fetch had no error handling or timeout; a failed response caused an unhandled exception. The region URL also had a leading `/` that created double-slash URLs. Fixed with proper try/except, `async_timeout`, and `lstrip('/')`. Resolves [#113](https://github.com/ciejer/metservice-weather/issues/113)

- **Fix pollen data after MetService API restructure** — MetService moved pollen from a structured JSON field to an HTML content block at a new `/airborne-allergens` endpoint. Pollen is now fetched from the correct endpoint and parsed with regex. Resolves [#132](https://github.com/ciejer/metservice-weather/issues/132)

- **Add forecast descriptions to daily forecast entries** — each day in the daily forecast now includes a `description` field containing the plain-English forecast text, surfaced via the weather entity and as a dedicated sensor. Resolves [#96](https://github.com/ciejer/metservice-weather/issues/96)

- **Fix hourly forecast condition icon logic** — the `windy` icon was silently overwritten by `partlycloudy` because the icon selection chain used `if/if` instead of `if/elif`. Wind conditions are now correctly preserved. Resolves [#149](https://github.com/ciejer/metservice-weather/issues/149)

### Additional bug fixes

- Fix mobile API: `native_pressure` and `humidity` on the weather entity were reading from the public API data path — always returning `None` for mobile API users
- Fix tide sensor `IndexError` crash when all tides for the current day have already passed
- Fix humidity sensor returning `0` for valid `0%` humidity readings due to `cast(int, data) or 0` falsy short-circuit
- Fix mobile drying index sensor crashing with `AttributeError` when data is `None` (e.g. in winter when no drying index is published)
- Fix mobile hourly forecast off-by-one: `range(len-1)` was silently dropping the last forecast hour
- Fix hourly and daily forecasts crashing for rural/regional locations due to missing backup sensor map keys (`hourly_bkp_obs`, `hourly_bkp_skip`, `hourly_bkp_temp`, `daily_bkp_datetime`)
- Fix `expand_data_urls` sub-requests sending no `User-Agent` header, which MetService may reject
- Fix `expand_data_urls` calls running inside `async_timeout` blocks — sub-requests each have their own timeout so the outer 10s limit was causing spurious failures when MetService returns many nested data URLs
- Fix tide region fetch in config flow having no timeout (could hang the config flow indefinitely)
- Fix `DEFAULT_LOCATION` not matching the SelectSelector value format (no location was pre-selected in the public API setup form)
- Add recursion depth limit (10) to `expand_data_urls` to guard against malformed or circular API responses
- Add `None` guard to hourly forecast so missing data returns an empty list cleanly rather than crashing
- Fix `expand_data_urls` recursion depth counter incorrectly incrementing on every dict/list traversal step rather than only on dataUrl expansion hops — caused hundreds of false-positive warnings per update cycle and log throttling in HA 2026.5
- Fix weather warnings sensor showing `unknown` state instead of "No warnings" when no active warnings — empty `warnings_text` string was falsy and bypassed the sensor value function
- Fix numeric sensors crashing with `ValueError` when MetService returns `"n/a"` for a field — `cast(float, data)` is a no-op at runtime, passing `"n/a"` straight through to HA's sensor platform which then raises `ValueError` and breaks the entire update loop; replaced all numeric `cast(float/int, data)` calls with `_safe_float`/`_safe_int` helpers that return `None` for non-numeric values. Resolves [#136](https://github.com/ciejer/metservice-weather/issues/136)
- Fix zero-value sensors (e.g. 0°C temperature, 0% humidity) showing as `unknown` — `if not self._sensor_data:` in `sensor.py` treated the integer `0` as falsy and short-circuited to `None` before calling `value_fn`; changed to `if self._sensor_data is None:`. Resolves [#108](https://github.com/ciejer/metservice-weather/issues/108)
- Fix `"wind-rain"` condition mapped to `"exceptional"` (a tornado-level HA state) instead of `"pouring"`; add `"rain-wind"` as an alias for the same. Resolves [#107](https://github.com/ciejer/metservice-weather/issues/107)
- Fix tide location config flow: `label` field in MetService marker objects is `{"text": "..."}` not a plain string — `SelectSelector` options were receiving dict objects causing 400 errors on every submission; extract `opt["label"]["text"]` for valid string values
- Fix tide location URL extraction: MetService marker `action` data is lazy-loaded via `dataUrl` which the config flow never resolves, so `action.modules[0].link.url` always fails; replaced with a 3-strategy fallback (nested path → plain string action → construct from label slug + region URL); slug construction is reliable for all known MetService stations

## v1.0.2

- **Remove Clothing Layers and Clothing Windproof Layers sensors** — `Clothing Layers` produced unreliable data (the `layers` key in the API collides with other uses of that word in the page JSON, causing the wrong value to be returned); `Clothing Windproof Layers` was marginal value. Both removed.

---

## v1.0.1

### Feature additions

- **Tomorrow's forecast** — four new sensors (public API): `Tomorrow — Condition`, `Tomorrow — High Temperature`, `Tomorrow — Low Temperature`, `Tomorrow — Description`; data is extracted from the 7-day forecast at update time and injected into the coordinator so the existing sensor infrastructure can access it cleanly

### Bug fixes / quality

- **Auto-disable tide and boating sensors** — tide sensors (`Next High Tide`, `Next Low Tide`) and boating sensors (`Boating Conditions`, `Boating Forecast`) are now excluded from entity registration entirely when no tide/boating location is configured; previously they were always registered and showed as `unavailable`, cluttering the entity list

---

## v1.0.0 — New sensors

### Feature additions

- **Wind Strength** — new `Wind Strength` sensor (public API) exposing MetService's Beaufort-scale text description ("Light winds", "Fresh", "Near gale", etc.) from the current conditions module; was fetched but never surfaced

- **Clothing Layers / Windproof Layers** — two new sensors (public API) exposing MetService's clothing recommendation from the current conditions module: number of layers to wear today and whether windproof layers are needed

- **Today's High / Low Temperature** — two new sensors (public API) exposing the observed or forecast high and low temperature for the current day from the current conditions module

- **Sub-day condition breakdown** — four new sensors (public API) from the two-day forecast module: `Today — Morning Condition`, `Today — Afternoon Condition`, `Today — Evening Condition`, `Today — Overnight Condition`; useful for "will it rain this afternoon?" without parsing the hourly forecast

- **Sunrise / Sunset** — two new sensors (public API) from the sun-and-moon module giving today's sunrise and sunset times as local time strings (e.g. "7:06am", "5:11pm")

- **Moonrise / Moonset** — two new sensors (public API) from the sun-and-moon module giving today's moonrise and moonset times

- **Moon Phase / Next Moon Phase Date** — two new sensors (public API) from the sun-and-moon module: the name of the next upcoming moon phase ("New Moon", "First Quarter", "Full Moon", "Last Quarter") and its date as a proper HA timestamp; useful in automations

All new sensors use data already fetched and expanded by the coordinator's existing `expand_data_urls` pass — no additional network requests.

---

### Config flow improvements (v0.9.9)

- **Renamed `api_key` → `mobile_api_key`** — the stored config entry key for the mobile API key is now `mobile_api_key`; backward compatibility retained (old entries with `api_key` continue to work)
- **Renamed `boating_region_url` → `boating_region`** — internal field name cleaned up; backward compatibility retained via fallback read
- **Name field moved to top of setup screen** — integration name is now the first field, matching the natural top-to-bottom reading order
- **`use_mobile` label made more descriptive** — now reads "Override public web data with mobile API (default: false)" to make the default and intent explicit
- **README rewritten** — full documentation of every configuration option, sensors table, reconfigure instructions, and a clear explanation of when (and when not) to use the mobile API override

### Config flow improvements (v0.9.8)

- **Single setup screen** — the entire configuration now fits in at most two screens: one main screen (location, name, tide region, boating region, optional mobile API toggle + key) and one optional marine locations screen (only shown if a tide or boating region was selected); previous versions required up to six separate screens
- **Marine location fetch parallelised** — tide and boating location lists are fetched simultaneously so the second screen appears immediately
- **Legacy mobile API** — moved from a top-level choice to an opt-in checkbox at the bottom of the main setup screen with descriptive help text explaining when it is and is not useful; public API remains the default
- **Field help text** — all fields now have descriptions rendered below them in the HA UI via the translations file, including a clear explanation of the mobile API use case and where to obtain the API key
- **Reconfigure pre-fills all fields** — the main setup screen pre-fills location, name, region selectors, and the mobile toggle from the existing entry; the locations screen always shows fresh options fetched from MetService

### Config flow improvements (v0.9.7)

- **Remove enable_tides / enable_boating toggles** — the two boolean toggle fields on the initial setup screen are gone; tides and boating are now optional steps that always appear in the flow with "None — skip tides / boating" as the first option, defaulting to skipped; no separate toggle needed and no ambiguity about what will happen
- **Reconfigure support** — a "Reconfigure" button now appears on the integration card; clicking it re-runs the full flow (location/name pre-filled, tide/boating region pre-selected to match the current configuration) and updates the entry in place without requiring delete + re-add; changing from public ↔ mobile API still requires delete + re-add since entity unique IDs are API-type-specific
- **Backwards compatibility** — existing entries continue to work unchanged; the coordinator now drives tide/boating fetching from URL presence rather than the old boolean flags, which gives identical runtime behaviour for all existing entries

### Feature additions (v0.9.6)

- **Rainfall sensor** — new `Rainfall` sensor for public API users, reading from `observations.rain.rainfall` (resolves [#74](https://github.com/ciejer/metservice-weather/issues/74))
- **Daily forecast precipitation** — `ATTR_FORECAST_PRECIPITATION` now populated in daily forecast entries from `rainFall1` (low estimate); additional `precipitation_low_mm` and `precipitation_high_mm` attributes for days 3–7 where MetService provides range estimates
- **Boating/surf conditions** — optional boating integration added to the config flow; adds `Boating Conditions` and `Boating Forecast` sensors for public API users (resolves [#70](https://github.com/ciejer/metservice-weather/issues/70), [#126](https://github.com/ciejer/metservice-weather/issues/126)); the config flow guides through region and location selection using the same marker/slug approach as tides; marker URL lazy-loading is handled with a slug-construction fallback so all MetService boating stations are selectable

### Code quality improvements

- Remove three duplicate copies of `get_from_dict` — sensor data fetching now calls coordinator methods directly, eliminating ~80 lines of repeated code
- Change `units_of_measurement` from a fragile integer-indexed tuple to a named dict keyed by string constants
- Consolidate shared public API headers into a single `_PUBLIC_HEADERS` class constant (was duplicated across three methods)
- Refactor `__init__.py` to eliminate near-identical public/mobile setup blocks
- Replace hardcoded `AUCKLAND_TIMEZONE` with `dt_util.utcnow()` for tide time comparisons, removing a NZ-specific assumption
- Fix weather warnings truncation to be consistent with description sensor (both now max 255 chars)
- Remove dead `RESULTS_FORECAST_HOURLY` constant
- Remove all commented-out sensor descriptions
- Fix all f-string logger calls to use `%s` formatting (avoids string evaluation when the log level would filter the message)
- Clean up stale debug log comments and unreachable code throughout

