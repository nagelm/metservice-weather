# metservice-weather — Claude Code instructions

## Project
HACS custom integration for NZ weather data from MetService. Fork of `ciejer/metservice-weather`.
- **Domain:** `metservice_weather`
- **Version:** `2026.7.0` (see `custom_components/metservice_weather/manifest.json`)
- **Repo:** `https://github.com/nagelm/metservice-weather`
- **HA min version:** 2024.2.0

## Dev environment

**Run tests (WSL venv):**
```
wsl bash scripts/test.sh tests/                   # all tests
wsl bash scripts/test.sh tests/test_foo.py -v     # specific file, verbose
```

**Run lint:**
```
wsl bash scripts/lint.sh
```

**Capture fresh API fixtures:**
```
wsl bash -c "source /home/mattn/.venv/metservice-weather/bin/activate && cd /mnt/c/Users/mattn/projects/metservice-weather && python scripts/capture_fixtures.py"
```

**WSL venv path:** `/home/mattn/.venv/metservice-weather/`
**pytest requires WSL** — `pytest-homeassistant-custom-component` needs `fcntl` (Linux only).

## Key file map
```
custom_components/metservice_weather/
  __init__.py                          — entry setup/unload; MetServiceConfigEntry type alias;
                                         uses entry.runtime_data
  manifest.json                        — version bump here before each release
                                         sync_to_core.sh strips `version` automatically
  diagnostics.py                       — HA diagnostics panel support (backported from Core branch)
  coordinator.py                       — DataUpdateCoordinator[MetServicePublicData];
                                         20-min polling; always_update=False
                                         get_from_dict DFS still used for drying index extraction
  coordinator_types.py                 — MetServicePublicData dataclass + HourlyEntry + DailyEntry
                                         normalize_public_data(current, daily) → MetServicePublicData
                                         _scan_forecasts: field lookup across all forecasts[] entries
                                         + day level (towns AND rural page shapes)
                                         DailyEntry.rain_prob_1mm/10mm = rainFall1/rainFall10 exceedance
                                         probabilities (% chance of ≥1mm/≥10mm — NOT amounts)
                                         capability flags: has_observations/has_breakdown/is_rural
                                         tomorrow_* derived from daily_entries[1] (no injection)
  entity.py                            — MetServiceEntity(CoordinatorEntity) base class;
                                         shared DeviceInfo (identifiers, manufacturer, model, config_url)
  const.py                             — LOCATIONS list, CONDITION_MAP, unit constants, URLs
  sensor.py                            — 40+ WeatherSensor(MetServiceEntity, SensorEntity); PARALLEL_UPDATES = 0
                                         value_fn(coordinator.data, unit_system)
                                         entity creation gated per-description via exists_fn(coordinator);
                                         stale sensor registry entries removed at setup
  weather.py                           — MetServiceForecastPublic(MetServicePublic); PARALLEL_UPDATES = 0
                                         reads coordinator.data.* directly (typed)
                                         daily forecast: precipitation_probability from rain_prob_1mm
                                         (never precipitation — API has no daily amounts)
  weather_current_conditions_sensors.py— sensor definitions (translation_key, value_fn lambda, unit, device class,
                                         suggested_display_precision, exists_fn gate)
                                         gate ONLY structural absences (observations, breakdown, marine config);
                                         UV/fire/drying/pollen are SEASONAL — never gate them
  config_flow.py                       — 2-step flow (setup → locations); public API only; reconfigure support
tests/
  fixtures/napier_public_current.json  — captured towns-cities fixture (post-expand, post-inject)
  fixtures/napier_public_daily.json    — captured towns-cities 7-day forecast fixture
  fixtures/kumeu_public_current.json   — captured RURAL fixture: empty observations, no breakdown,
                                         regional+location forecasts entries, day-level temps
  fixtures/kumeu_public_daily.json     — captured rural 7-day forecast fixture
  test_config_flow.py                  — config flow tests
  test_coordinator_data.py             — coordinator contract tests (direct dataclass attr access)
  test_coordinator.py                  — coordinator fetch/error path tests
  test_sensor.py                       — sensor entity tests
  test_weather.py                      — weather entity tests
  test_init.py                         — setup/unload lifecycle tests
  test_normalizer.py                   — normalize_public_data unit tests
scripts/
  test.sh                              — pytest wrapper (WSL)
  lint.sh                              — ruff check + format (WSL)
  capture_fixtures.py                  — fetches real MetService data → tests/fixtures/
  get_cities.py                        — lists public API location paths (dev helper)
  sync_to_core.sh                      — syncs HACS → ha-core branch (rewrites imports,
                                         patches manifest, preserves Core-only files)
```

## Architecture — how data flows

1. **Coordinator fetch** (`get_public_weather`)
   - Fetches main URL → expands nested `dataUrl` references recursively (`expand_data_urls`)
   - Fetches warnings, pollen (best-effort), 7-day daily forecast
   - Calls `normalize_public_data(result_current, result_daily)` → returns `MetServicePublicData`
   - `self.data` is typed `MetServicePublicData`

2. **Sensor access** — `sensor.py` calls `value_fn(coordinator.data, unit_system)`
   - `value_fn` lambdas in `weather_current_conditions_sensors.py` read `data.temperature` etc.

3. **Weather entity** — reads `coordinator.data.*` directly:
   - `coordinator.data.temperature`, `.wind_speed`, `.hourly_entries`, `.daily_entries` etc.
   - `HourlyEntry` fields: `datetime`, `temperature`, `rainfall`, `wind_speed`, `wind_direction`
   - `DailyEntry` fields: `datetime`, `condition`, `temp_high`, `temp_low`, `description`, etc.

## IQS / Core submission status

### Code quality — all done
- ✅ `asyncio.timeout` everywhere (stdlib, no `async_timeout` package)
- ✅ Translation keys on all sensors + `entity.sensor` in `strings.json`/`en.json`
- ✅ `icons.json` present
- ✅ Mobile API path removed (private API key; not Core-appropriate)
- ✅ `async_migrate_entry` stub present
- ✅ Stable unique IDs (canonical location path slug)
- ✅ `async_get_clientsession` throughout
- ✅ `from __future__ import annotations` in all files
- ✅ 206 tests, 95.8% coverage, `--cov-fail-under=95`
- ✅ `MetServiceEntity` base class (`entity.py`) — shared DeviceInfo
- ✅ `suggested_display_precision` on all numeric sensors
- ✅ `diagnostics.py` — diagnostics panel support
- ✅ `MetServiceConfigEntry` type alias in `__init__.py`

### Core branch — `nagelm/core:add-metservice-nz-weather`
- Forked `home-assistant/core` → `nagelm/core`; branch created 2026-05-14
- `homeassistant/components/metservice_weather/` — all files synced from HACS repo
- `tests/components/metservice_weather/` — 206 tests, paths rewritten to `homeassistant.components.*`
- `quality_scale.yaml` — IQS Silver declared; brands/docs rules marked todo (see below)
- `CODEOWNERS` entry at correct alphabetical position
- **hassfest passes** (only known flag: `brands: todo` — deliberate, handled at PR time)
- Sync with: `bash scripts/sync_to_core.sh` (then commit + push in ha-core)

### Remaining Core submission steps (in order)

1. **Brands PR** → `home-assistant/brands`
   - Create `core/metservice_weather/` with `icon.png` (256×256 transparent PNG)
   - Optionally add `logo.png` and `icon@2x.png`
   - Fast review — typically merged within days
   - After merge: flip `brands: todo → done` in `quality_scale.yaml`, run sync

2. **HA documentation page** → `home-assistant/home-assistant.io`
   - File: `source/_integrations/metservice_weather.markdown`
   - Content based on README; must cover high-level description, installation, configuration,
     removal, supported functions, use cases, troubleshooting, known limitations
   - Submit alongside (or shortly before) the Core integration PR

3. **Update `quality_scale.yaml`** after brands merges and docs PR is submitted
   - `brands: done`, docs-* rules to `done`
   - Run `bash scripts/sync_to_core.sh` and commit to ha-core branch

4. **Open the Core integration PR** — `nagelm/core:add-metservice-nz-weather` → `home-assistant/core:dev`
   - PR description: summary, test plan, link brands PR (merged), link docs PR (pending)
   - Label: `new-integration`
   - Expected review cycle: 2–8 weeks

5. **Backport reviewer changes** to HACS repo as they come in; use `sync_to_core.sh` to re-sync

6. **Phase 4 (post-acceptance):** Extract `pymetservice-nz` PyPI library (Platinum-only, deferred)

## Versioning convention

Home Assistant–style calendar versioning: `YYYY.M.P` (year.month.patch, month
**not** zero-padded — same format as HA core, e.g. `2026.7.0`).

- First release in a calendar month: `YYYY.M.0`.
- Further releases in the same month bump the patch: `2026.7.1`, `2026.7.2`, …
- Year/month reflect the **release date**, not feature scope. There is no
  semantic major/minor signal — call out breaking changes prominently in
  `release_notes.md` instead.
- Tags stay `v`-prefixed: `v2026.7.0`.
- History: releases up to `v1.0.1` used SemVer. CalVer sorts above them
  (2026 > 1) so HACS upgrade paths are unaffected. `1.1.0` was never released;
  its changes ship as `2026.7.0`.

## Release workflow (CRITICAL)

1. Bump `manifest.json` version
2. Update `release_notes.md`
3. Commit + push + tag
4. Build zip using .NET ZipArchive — **NEVER `Compress-Archive`** (uses backslashes in paths → HA says "integration not found" on Linux):
```powershell
$zipPath = "C:\Users\mattn\projects\metservice-weather\metservice_weather.zip"
$sourceDir = "C:\Users\mattn\projects\metservice-weather\custom_components\metservice_weather"
Remove-Item $zipPath -Force -ErrorAction SilentlyContinue
Add-Type -Assembly System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::Open($zipPath, 'Create')
Get-ChildItem $sourceDir -Recurse -File | ForEach-Object {
    $rel = $_.FullName.Substring($sourceDir.Length + 1).Replace('\', '/')
    [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $_.FullName, $rel) | Out-Null
}
$zip.Dispose()
```
5. `gh release create vX.X.X --prerelease --repo nagelm/metservice-weather` — attach zip, invisible to HACS auto-update
6. Test on prod via HACS ⋮ → Redownload → select version
7. Promote: `gh release edit vX.X.X --prerelease=false --repo nagelm/metservice-weather`

## PowerShell git commit messages
Avoid here-strings for commit messages containing special characters. Use a variable:
```powershell
$msg = "subject`n`nbody`n`nCo-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
git commit -m $msg
```

## Production HA
- URL: `http://192.168.3.3:8123` — **never develop directly against it**
- Credentials: `HA_USERNAME` / `HA_PASSWORD` in `~/.claude/settings.json`
- Integration installed via HACS from the GitHub release zip
- Access logs via HA MCP tools (`mcp__Home_Assistant__ha_get_logs`)

## Dev HA (WSL)
Full startup procedure and tokens: **`dev_credentials.md`** (gitignored — never commit).

- Config dir: `C:\Users\mattn\projects\metservice-weather\config\`
- Integration loaded via PYTHONPATH — no install/zip needed, just restart HA after code changes
- If `index.html` render fix is lost after pip upgrade: `wsl python3 /mnt/c/Users/mattn/projects/ha/fix_index.py` then restart
