## v2026.7.1

### Sensor behaviour hardening

Every sensor's real-world behaviour was reviewed against recorded history; this release fixes what that review surfaced.

#### New Pollen sensor (old sensors deprecated, not removed)

MetService's allergen page serves several concurrent status blocks — e.g. mid-July: `Imminent` (wattle, pine — season approaching) alongside `Low` (cypress, hazelnut — currently in the air). The old sensors flattened this to whichever block came first, mixing a *forecast notice* into what looked like an exposure level.

The new `sensor.<device>_pollen`:

- **State** = the current exposure level: `none` / `low` / `moderate` / `high`, keyed to MetService's own severity taxonomy (never `Imminent` — that's an outlook, not a level)
- **`low_allergens`** / **`moderate_allergens`** / **`high_allergens`** attributes list what's in the air at each level (comma-separated strings, so they render on tile cards via `state_content`; empty levels are omitted)
- **`imminent_allergens`** attribute lists species whose season is about to start

`sensor.<device>_pollen_levels` and `sensor.<device>_pollen_type` are **deprecated but keep working** — existing installs keep them; new installs get them disabled and hidden. An automation watching `imminent_allergens` is the new way to get a "pollen season starting" alert.

#### New Weather Warning Level sensor (severity enum)

A new `warning_level` sensor is an enum keyed to severity; the existing Weather Warnings sensor is deprecated but keeps working (its state is the headline text — the old truncation bug stays fixed):

- **State**: `none` / `watch` / `warning` / `orange` / `red` — the most severe active warning's level, so numeric-style "at least orange" automation conditions work.
- **Attributes**: `headline` (most severe warning's name, e.g. `Strong Wind Warning - Orange (+1 more)`) and `count` — flat values that render everywhere, per HA's attribute guidance.
- **Warning details** — a companion sensor, disabled by default (enable it on the device page): state is the active warning count and its `active_warnings` attribute carries the full structured list (`name`, `text`, `threat_period`, no truncation) for notification automations. The list is deliberately excluded from the recorder, so enabling it costs no database growth.
- Existing automations on the old sensor keep working; when migrating, `state != "No warnings"` becomes `state != "none"` on the new sensor.

#### New UV Risk sensor (5-level enum; UV Index deprecated)

The new `uv_risk` sensor's state is `low` / `moderate` / `high` / `very_high` / `extreme` (NIWA's alert scale — a closed vocabulary, so ad-hoc wording changes can't break automations). New attributes: `status_class`, `advice` (the sun-protection message), `protection_window_start` / `protection_window_end` (populated in season), and `has_alert`. Off-season the sensor reads `unknown` as before.

#### New closed-vocabulary enum sensors (old text sensors deprecated)

New sensors: Pressure tendency (`rising`/`falling`/`stable`), Wind strength (`calm`→`storm`), Fire season (FENZ `open`/`restricted`/`prohibited` — the descriptive text moved to attributes), Fire danger (`low`→`extreme`, keyed to NIWA's own index), and Moon phase (all eight octants, `new_moon`→`waning_crescent`, derived from MetService's next principal-phase event — which rides along as `next_phase` + `next_phase_at` attributes) — enum sensors with translated states and validated vocabularies alongside the original text sensors, which are deprecated but unchanged. The old Next Moon Phase Date sensor is deprecated with the rest (its timestamp now lives in `next_phase_at`). Any unexpected upstream value logs one warning and reads `unknown` instead of breaking.

#### New sunrise/sunset/moonrise/moonset timestamp sensors

New `*_time` sensors carry real timestamps usable in automation triggers and templates (with the `7:42am`-style text as a `display` attribute). The original string sensors are deprecated but unchanged.

#### Added: opt-in forecast rain sensors

Three new sensors, disabled by default (enable on the device page): **Rain next 8 hours** (mm), **Rain next 24 hours** (mm), and **Next rain expected**. These replace the `weather.get_forecasts` template dance for the most common rain automations.

Next rain expected searches the full forecast, not just the hourly series: the first rainy hour when one is in reach (`precision: hour`), otherwise the first daily-forecast day MetService draws with a precipitation icon (`precision: day`, timestamped midday). When the entire 7-day horizon is dry the state is unknown **with `outlook: no_rain_expected` and a `forecast_horizon` attribute** — an explicit "no rain through <date>" claim, distinguishable from missing data (which carries no attributes).

#### Added: option to auto-disable sensors with no upstream data

A new setup/reconfigure toggle ("Automatically disable sensors while MetService publishes no data", default off) disables and hides seasonal sensors (UV, fire danger, clothes drying) while MetService pauses the product, instead of removing them. Their history and settings are kept, and they're re-enabled automatically — no restart — when data resumes; turning the toggle back off restores everything in one restart too. Leave it off to keep today's behaviour (sensors stay visible and read `unknown` off-season).

Installs that already had the option turned on under its earlier remove-outright behaviour will have their seasonal sensors' registry rows re-created — born disabled and hidden — the first time they update.

#### Zero breaking changes: deprecation instead of removal

Every sensor whose format changed is **forked, not broken**: your existing sensors keep their exact previous behaviour, and the new enum/timestamp versions arrive as separate entities (enabled for everyone; the deprecated originals are hidden and disabled only for fresh installs). On upgrade, each deprecated sensor is checked against a thorough usage scan — automations, scripts, scenes, groups, **dashboards**, helper chains (derivative/utility meter/statistics/…), voice-assistant exposure, and HomeKit:

- **In use somewhere** → the sensor is *hidden* but keeps working and recording — everything referencing it is unaffected, and a repair names exactly where it's used.
- **Nothing uses it** → the sensor is *disabled* (reversible in one toggle on the device page; its history is kept).

Your choices always win: sensors you've manually hidden, un-hidden, enabled, or disabled are never touched again, and nothing is ever auto-re-enabled. A one-time notice summarizes what was disabled or hidden. Removal of the deprecated set is planned for version 2026.9.0.

#### Added: Repairs guidance (Settings → Repairs)

Repair issues now appear **only when your setup shows evidence of needing them**, and clear themselves once fixed:

- A deprecated sensor still in use → migration notice naming where it's used (automation, dashboard, helper, …) and the replacement.
- An entity removed on upgrade that your automations still referenced → removal notice with a suggested replacement.
- A config entry still on the mobile API removed in v1.0.0 (or an unknown location) → reconfigure guidance.
- Automations/scripts still reading the `forecast_hourly`/`forecast_daily` weather attributes removed after v0.9.x → pointer to `weather.get_forecasts` and the new rain sensors.

#### Changed: the weather device is named after the selected location

The town/rural device now carries the **MetService location's own label** (e.g. choosing Porirua names the device "Porirua"), instead of the free-text name typed at setup — that name remains the config entry's title in the integrations list. If you renamed the device yourself, your name still wins; clear the custom name (pencil icon on the device page) to adopt the location label. Entity IDs, unique IDs, and history are unchanged for existing installs.

#### Added: marine data gets its own device

Tide, boating, and surf sensors now group under a separate device named after your selected marine region (e.g. "Kapiti and Wellington"), linked via the town device. Entity IDs and history are unchanged - Home Assistant re-homes the entities automatically. Because these sensors move to their own device, their displayed friendly name changes too (e.g. "Auckland Next high tide" becomes "Auckland East Coast Next high tide"). entity_id, unique_id, and recorded history are unaffected — but update any notification template, dashboard label, or voice-assistant phrase that used the old friendly name.

#### Added: tide detail attributes and Tide direction sensor

Next high/low tide sensors now carry a `height_m` attribute — the predicted height of the tide the sensor is counting down to. A new **Tide direction** sensor (marine device, disabled by default) reads `rising` / `falling` from the next upcoming event and carries the full-day `tide_table` attribute (`type`, `time`, `height` per entry); the table is excluded from the recorder, so enabling it costs no database growth.

#### Added: daily rainfall totals for today and tomorrow

The daily forecast now carries a real precipitation amount (mm) for today and tomorrow, aggregated from the hourly data: actual recorded rainfall for elapsed hours plus the forecast for the remainder of the day (matching MetService's own "total rainfall for today" figure). Later days keep the chance-of-rain percentage. Totals only appear when a day has near-complete hourly coverage, and each cycle cross-checks the sum against MetService's stated total in debug logging.

#### Changed: sensor names follow Home Assistant naming guidelines

All sensor display names now use HA's official sentence-case, measurement-first style (e.g. "Wind Speed" → "Wind speed", "Today's High Temperature" → "High temperature today", "Tomorrow — Condition" → "Condition tomorrow", "Temperature - Feels Like" → "Temperature feel", "MetService Weather Warnings" → "Warnings"). One rename is a correction, not just style: "Rainfall" → **"Rain last hour"** — the station value is a trailing-hour figure that rises and falls with the rain (verified against recorded history), not the daily total the old name implied. Entity IDs, unique IDs, and recorded history are unchanged for existing installs — only the displayed friendly name changes (update any dashboard label, notification template, or voice phrase that used the old wording). Fresh installs additionally mint cleaner entity IDs from the new names. UI-renamed entities are unaffected (your custom name wins). Deprecated sensors keep their old names.

#### Fixed / hardened

- **Rural weather entities now show current temperature and wind**: locations without a weather station (most rural pages) previously had no `temperature`, `wind_speed`, or `wind_bearing` on the weather entity at all. These now fall back to the forecast for the current hour — the same stand-in MetService's own site uses. Stations that briefly drop an observation get the same fallback instead of a blank. Humidity and pressure have no hourly forecast source and remain unavailable without a station.
- **Stale duplicate weather entities are cleaned up on upgrade**: installs dating back to the old entity-ID collision (e.g. a leftover `weather.<name>_<name>_forecast` stuck permanently `unavailable`) had that orphan restored on every restart. The weather platform now prunes stale registry entries at setup, as the sensor platform already did.
- **Unknown condition tokens can no longer break the weather card**: unmapped MetService condition tokens (e.g. unseen night variants) now fall back to their day equivalent, or report as unknown with a logged warning — previously they passed through as invalid Home Assistant conditions.
- **Moon phase date no longer flip-flops**: MetService recomputes the phase time per request with second-level jitter (observed: the same event served 19 s apart), causing spurious state changes. Timestamps are now rounded to 5 minutes, so the sensor changes only when the actual phase event advances.
- **Diagnostic logging for observation dropouts**: when a station value (temperature, wind, …) goes missing for a polling cycle, debug logging now records the raw upstream payload — distinguishing MetService outages from ingestion problems. Enable with `logger: logs: custom_components.metservice_weather: debug`.
- A warning payload missing a field no longer aborts the whole data update.

#### Documentation

- README now explains seasonal products: UV and fire danger are stripped server-side off-season (`unknown` in winter is expected); pollen runs year-round and reads `Imminent` pre-season with the upcoming allergens.

---

## v2026.7.0

### Rural locations fixed, correct rain probabilities — and a new version scheme

> **Versioning change:** this integration now uses Home Assistant–style calendar versioning (`YYYY.M.patch`), so v1.0.1 is followed by v2026.7.0. Upgrades through HACS are unaffected.

Fixes [#2](https://github.com/nagelm/metservice-weather/issues/2) and [#3](https://github.com/nagelm/metservice-weather/issues/3); delivers the rural-town half of [#4](https://github.com/nagelm/metservice-weather/issues/4).

#### Rain "amounts" were actually probabilities (#3)

MetService's daily `rainFall1`/`rainFall10` fields are **exceedance probabilities** — the % chance of at least 1 mm / 10 mm of rain that day — not rainfall amounts. Earlier releases reported them as `precipitation` in mm (so "95% chance of ≥1 mm" showed as 95 mm of rain, and "low" always looked bigger than "high").

- The daily forecast now exposes `precipitation_probability` (the ≥1 mm probability, matching the "chance of rain" shown on metservice.com) and no longer reports a daily precipitation amount — the public API doesn't publish one.
- The `precipitation_low_mm` / `precipitation_high_mm` attributes from v0.9.x are gone. If you templated against them, switch to `precipitation_probability`.
- Hourly forecast precipitation is unchanged — that is real mm data.

#### Rural locations now fully work (#2, #4)

~80 of the selectable locations are MetService *rural* pages, which have a different data shape (no weather station, temps and rain probabilities nested differently, regional + local forecast text). Previously these locations showed `Unknown` for many sensors and, since v1.0.0, missing daily temps. Now:

- Daily forecast: high/low temps, condition, chance of rain, and the regional multi-day text descriptions all populate.
- Today's / Tomorrow's high & low temperature sensors work (today's falls back to the day-0 forecast — the same value MetService shows — when there is no station).
- Sensors a location can never provide (wind/temperature/pressure/humidity observations, morning/afternoon/evening/overnight breakdowns) are no longer created as permanently-unknown entities, and stale ones are cleaned from the entity registry on upgrade.
- Seasonal sensors (UV, fire danger, clothes drying, pollen) are still created everywhere and read `unknown` off-season — that's MetService pausing the product, not a bug.

#### Internals

- Forecast parsing now scans every `forecasts[]` entry plus the day level, covering towns-cities and rural page shapes with one rule.
- `tomorrow_*` values are derived from the normalised 7-day data instead of a separate injection path.
- Weather entity no longer errors during startup if the first data refresh hasn't completed (all properties now handle missing coordinator data).
- New rural (Kumeu) API fixtures; test suite extended to cover every page-shape heuristic (towns/rural/day-level-only/missing-module cases). 259 tests, 95% coverage, now enforced in CI alongside lint, formatting, hassfest and HACS validation.

---

## v1.0.1

> **Note:** v1.0.0 was tagged before Phase 3 code changes were committed; v1.0.1 ensures the release zip matches the documented changes.

### Mobile API removed — public API only; IQS Gold compliance

**v0.9.19 is the last release with mobile API support.**

The mobile API relied on a private key that is not supported for third-party use, and has been removed. The MetService mobile API relies on a private API key extracted from the iOS app — it is not publicly distributed and is not supported for third-party use.

If you rely on GPS-based location tracking or a location not in the ~150 supported towns, stay on [v0.9.19](https://github.com/nagelm/metservice-weather/releases/tag/v0.9.19) — it remains fully functional.

#### Breaking changes
- **Mobile API removed.** Config entries using the mobile API path must be deleted and re-added using the public API after upgrading.
- **Reauth flow removed** — was only needed for mobile API key expiry.

#### IQS Gold compliance
All Home Assistant Integration Quality Scale Gold-tier requirements are now met:
- `asyncio.timeout` throughout (stdlib, no third-party package)
- Translation keys on all 40+ sensors; `entity.sensor` section in `strings.json`
- `icons.json` present
- Stable unique IDs from canonical location path slug
- `async_get_clientsession` throughout (no session leaks)
- `async_migrate_entry` stub

#### Code quality (Phase 3)
- Shared `MetServiceEntity` base class with `model` and `configuration_url` in `DeviceInfo`
- `suggested_display_precision` on all numeric sensors
- `tides` and `boating_table` typed as `list[dict[str, Any]]`
- Dead `_update_listener` reload mechanism removed

#### Test suite
- 206 tests, 95.8% coverage (`--cov-fail-under=95`)

---

## v0.9.19

### Internal refactor: typed dataclass, Silver IQS compliance, bug fixes

#### Coordinator data model
- **Typed `MetServicePublicData` dataclass** replaces the raw `{"current": ..., "daily": ...}` dict returned by `get_public_weather`. All public API fields are normalised at fetch time into typed attributes (`temperature`, `wind_speed`, `humidity`, `daily_entries`, `hourly_entries`, etc.). Sensors and the weather entity read directly from typed attributes — no more depth-first key search across the raw API tree.
- **`always_update=False`** added to `DataUpdateCoordinator` — HA now skips entity state writes when the data hasn't changed (dataclass `__eq__` comparison), reducing unnecessary recorder writes on every 20-minute poll.

#### Bug fixes
- **Fix hourly wind speed always `None`** — the hourly forecast graph uses `wind.speed`, not `wind.averageSpeed` (that key is only in the current observations section). All 48 hourly forecast entries now carry a wind speed value.
- **Auth failure now triggers reauth flow** — mobile API HTTP 401/403 responses previously became generic `UpdateFailed` (entities unavailable but no reauth prompt). Now raises `ConfigEntryAuthFailed` to trigger the reauth notification.
- **Demote fetch logs from INFO to DEBUG** — `"Fetching MetService public/mobile data…"` and `"Fetching pollen data…"` were logging at INFO on every 20-minute poll cycle, producing noise in production logs. All are now DEBUG.

#### IQS Silver compliance
- **`integration-owner`** — added `.github/CODEOWNERS` (`@ciejer @nagelm`).
- **`config-entry-unloading`** — added `tests/test_init.py` with 5 lifecycle tests covering setup and unload for both public and mobile API paths.
- **`test-coverage`** — coverage enforcement raised to 95% (`--cov-fail-under=95` in `pyproject.toml`). Current coverage: 97%.
- **Reauthentication flow** — `async_step_reauth` / `async_step_reauth_confirm` in config flow handles expired/rejected mobile API keys; public API entries abort with `not_applicable`.

#### Test suite
- 250 tests, 97% coverage (up from 53 tests / no enforcement at v0.9.18).

---

## v0.9.18

### IQS Bronze compliance — code quality and test coverage

- **`runtime-data` refactor** — replaced `hass.data[DOMAIN]` with `entry.runtime_data` across `__init__.py`, `sensor.py`, and `weather.py`; this is the current HA best practice for storing coordinator references and avoids using the global data store for per-entry state
- **`PARALLEL_UPDATES = 0`** — added to `sensor.py` and `weather.py`; disables HA's default per-entity semaphore since updates are already serialised through the `DataUpdateCoordinator`
- **Fix `WeatherSensor.available`** — removed the incorrect custom `available` property that returned `True` even after a failed coordinator update (when stale data existed); `CoordinatorEntity`'s built-in `available` property correctly reflects `last_update_success`
- **Config flow test suite** — 9 test cases covering: public API setup, marine region selection, mobile API with valid/invalid/missing key, network timeout, duplicate location prevention, marine fetch failure, and reconfigure flow; uses `pytest-homeassistant-custom-component` with no real network calls
- **README rewritten** — repositioned as a standalone fork with full sensor inventory (including surf, sun/moon, sub-day, and drying index sensors previously absent from the docs), a Removal section, and a Contributing section

---

## v0.9.17

### Fix config flow translations not loading after HACS install

- **Add `strings.json`** — HA uses `strings.json` at the component root as the canonical source for English config flow translations. Without it, HA does not load the `config_flow` translation category for custom integrations, so field labels and help text from `translations/en.json` were silently ignored. The setup form showed raw field keys or stale cached labels instead of the intended human-readable labels. `strings.json` contains the same content as `translations/en.json` and is kept in sync going forward.

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

## v0.9.16

### UI label and help text improvements

- **"Integration name" → "Device name"** — the name field on the setup screen is now labelled "Device name" to better reflect that it prefixes all HA entity names and appears on the device card
- **Help text for Device name** — explains that the name appears on all entities (e.g. "Auckland Temperature") and that adding multiple instances with different names/locations is how you get weather for more than one place
- **Help text for Marine Region** — explains that the field is optional, covers tide times, boating conditions, and surf sensors, and that the next screen lets you pick specific stations for each
- **Help text for each location selector** — each of Tide station, Boating location, and Surf location now has a description explaining what sensors it enables and that "None — skip" omits those sensors entirely
- **"marine_region" → "Marine Region"** — display label corrected

---

## v0.9.15

### Config flow redesign — single marine region, three independent location selectors

- **Single marine region** — the setup screen now has one "Marine region" dropdown (with "None — skip marine data") that replaces the previous separate tide-region and boating-region selectors; the chosen region is shared across all three marine services
- **Three independent location selectors on page 2** — after selecting a region, a second screen shows Tide location, Boating location, and Surf location, each with a "None — skip" option; sensors are only registered for services where a location was chosen
- **Backward compatible** — existing config entries continue to work; the coordinator reads legacy `tide_region_url` / `boating_region` keys as a fallback so old entries need not be reconfigured

### Surf sensors (new, public API)

When a surf location is configured, 10 new sensors are registered:
- **Surf Conditions** — "Good", "Medium", or "Bad"
- **Surf Rating** — 1–10 numeric quality score
- **Surf Wave Height** — metres
- **Surf Set Face** — face height in metres
- **Surf Swell Direction** — cardinal direction (e.g. "SW")
- **Surf Swell Height** — metres
- **Surf Wind Direction** — cardinal direction
- **Surf Wind Speed / Gust** — knots
- **Surf Period** — wave period in seconds

Data is fetched live from the MetService regional surf page on each coordinator update cycle. All surf sensors are excluded from entity registration when no surf location is configured.

---

## v0.9.14

- **Normalise drying index sensors so all three always carry a value** — surveyed all MetService location patterns and found three distinct real-world states: good day (morning and afternoon both have hours), mixed day (morning has hours, afternoon shows "Wet"), and wet all day (morning shows bare "Wet all day" with no prefix, afternoon entry is replaced by "Next good day: Thursday"). The coordinator now handles all three: `Clothes Drying Time - Afternoon` mirrors morning's "Wet all day" on a complete washout instead of going unavailable; `Clothes Drying - Next Good Day` shows "Today" whenever either morning or afternoon is usable, and a day name only on a full washout.

---

## v0.9.13

- **Fix drying index sensor labels when conditions are poor** — MetService omits the "Afternoon:" line and substitutes "Next good day: Thursday" when drying conditions are bad all day. The coordinator now parses drying state entries by their text prefix rather than array position, so `Clothes Drying Time - Morning` and `Clothes Drying Time - Afternoon` always show the correct data.
- **Add `Clothes Drying - Next Good Day` sensor** — new sensor (public API) exposing the next viable drying day when today's conditions are poor; shows `None` when today is already a good drying day.

---

## v0.9.12

- **Remove Clothing Layers and Clothing Windproof Layers sensors** — `Clothing Layers` produced unreliable data (the `layers` key in the API collides with other uses of that word in the page JSON, causing the wrong value to be returned); `Clothing Windproof Layers` was marginal value. Both removed.

---

## v0.9.11

### Feature additions

- **Tomorrow's forecast** — four new sensors (public API): `Tomorrow — Condition`, `Tomorrow — High Temperature`, `Tomorrow — Low Temperature`, `Tomorrow — Description`; data is extracted from the 7-day forecast at update time and injected into the coordinator so the existing sensor infrastructure can access it cleanly

### Bug fixes / quality

- **Auto-disable tide and boating sensors** — tide sensors (`Next High Tide`, `Next Low Tide`) and boating sensors (`Boating Conditions`, `Boating Forecast`) are now excluded from entity registration entirely when no tide/boating location is configured; previously they were always registered and showed as `unavailable`, cluttering the entity list

---

## v0.9.10 — New sensors

### Feature additions

- **Wind Strength** — new `Wind Strength` sensor (public API) exposing MetService's Beaufort-scale text description ("Light winds", "Fresh", "Near gale", etc.) from the current conditions module; was fetched but never surfaced

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

