# metservice-weather — Claude Code instructions

## Project
HACS custom integration for NZ weather data from MetService. Fork of `ciejer/metservice-weather`.
- **Domain:** `metservice_weather`
- **Version:** `1.0.0` (see `custom_components/metservice_weather/manifest.json`)
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
  __init__.py                          — entry setup/unload; uses entry.runtime_data
  manifest.json                        — version bump here before each release
                                         REMOVE `version` key before Core PR (HACS-only field)
  coordinator.py                       — DataUpdateCoordinator[MetServicePublicData];
                                         20-min polling; always_update=False
                                         get_from_dict DFS still used for drying index extraction
  coordinator_types.py                 — MetServicePublicData dataclass + HourlyEntry + DailyEntry
                                         normalize_public_data(current, daily) → MetServicePublicData
  entity.py                            — MetServiceEntity(CoordinatorEntity) base class;
                                         shared DeviceInfo (identifiers, manufacturer, model, config_url)
  const.py                             — LOCATIONS list, CONDITION_MAP, unit constants, URLs
  sensor.py                            — 40+ WeatherSensor(MetServiceEntity, SensorEntity); PARALLEL_UPDATES = 0
                                         value_fn(coordinator.data, unit_system)
  weather.py                           — MetServiceForecastPublic(MetServicePublic); PARALLEL_UPDATES = 0
                                         reads coordinator.data.* directly (typed)
  weather_current_conditions_sensors.py— sensor definitions (translation_key, value_fn lambda, unit, device class,
                                         suggested_display_precision)
  config_flow.py                       — 2-step flow (setup → locations); public API only; reconfigure support
tests/
  fixtures/napier_public_current.json  — captured public API fixture (post-expand, post-inject)
  fixtures/napier_public_daily.json    — captured 7-day forecast fixture
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

### Gold tier — all blockers resolved
- ✅ `manifest.json` — `requirements: []`, `integration_type: "service"`, `quality_scale: "gold"`
- ✅ `asyncio.timeout` everywhere (stdlib, no `async_timeout` package)
- ✅ Translation keys on all sensors + `entity.sensor` in `strings.json`/`en.json`
- ✅ `icons.json` present
- ✅ Mobile API path removed (private API key; not Core-appropriate)
- ✅ `async_migrate_entry` stub present
- ✅ Non-standard `Forecast` TypedDict keys removed
- ✅ Stable unique IDs (canonical location path slug)
- ✅ `async_get_clientsession` throughout
- ✅ `from __future__ import annotations` in all files
- ✅ 206 tests, 95.8% coverage, `--cov-fail-under=95`

### Phase 3 Platinum items — done
- ✅ Shared `MetServiceEntity` base class (`entity.py`)
- ✅ `model` + `configuration_url` in `DeviceInfo`
- ✅ `suggested_display_precision` on all numeric sensors
- ✅ `_update_listener` removed (no options flow)
- ✅ `tides`/`boating_table` typed as `list[dict[str, Any]]`

### Remaining before Core PR
- Remove `"version"` from `manifest.json` (one-line change, do this last — HACS needs it but Core CI rejects it)
- Phase 4: extract `pymetservice-nz` PyPI library (Platinum-only requirement, does not block Gold)

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
