# metservice-weather — Claude Code instructions

## Project
HACS custom integration for NZ weather data from MetService. Fork of `ciejer/metservice-weather`.
- **Domain:** `metservice_weather`
- **Version:** `0.9.18` (see `custom_components/metservice_weather/manifest.json`)
- **Repo:** `https://github.com/nagelm/metservice-weather`
- **HA min version:** 2024.2.0 (public API) / 2024.2.0 (mobile API)

## Dev environment

**Run tests (WSL venv):**
```
wsl bash scripts/test.sh                          # all tests, quiet
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
  coordinator.py                       — DataUpdateCoordinator; 20-min polling
                                         get_current_public(field) / get_forecast_daily_public(field, day)
                                         get_from_dict(data, keys) — depth-first key search
  const.py                             — SENSOR_MAP_PUBLIC / SENSOR_MAP_MOBILE (field → dotted path)
  sensor.py                            — 40+ CoordinatorEntity sensors; PARALLEL_UPDATES = 0
  weather.py                           — SingleCoordinatorWeatherEntity; PARALLEL_UPDATES = 0
  weather_current_conditions_sensors.py— sensor definitions (name, field key, unit, device class)
  config_flow.py                       — 2-step flow; public or mobile API; reconfigure support
tests/
  fixtures/napier_public_current.json  — captured public API fixture (post-expand, post-inject)
  fixtures/napier_public_daily.json    — captured 7-day forecast fixture
  test_config_flow.py                  — 9 config flow tests (all pass)
  test_coordinator_data.py             — 44 coordinator contract tests (all pass)
scripts/
  test.sh                              — pytest wrapper (WSL)
  lint.sh                              — ruff check + format (WSL)
  capture_fixtures.py                  — fetches real MetService data → tests/fixtures/
  get_cities.py                        — lists public API location paths (dev helper)
```

## Architecture — how data flows

1. **Coordinator fetch** (`get_public_weather` / `get_mobile_weather`)
   - Fetches main URL → expands nested `dataUrl` references recursively (`expand_data_urls`)
   - Fetches warnings, pollen (best-effort), 7-day daily forecast
   - Injects derived keys at root of `result_current`:
     `weather_warnings`, `pollen`, `tomorrow_condition/temp_high/temp_low/description`,
     `drying_morning`, `drying_afternoon`, `drying_next_good_day`
   - Returns `{"current": result_current, "daily": result_daily}`

2. **Sensor access** — `get_current_public(field)`:
   - Looks up `SENSOR_MAP_PUBLIC[field]` → dotted path string (e.g. `"observations.wind.0.averageSpeed"`)
   - Calls `get_from_dict(self.data["current"], keys)` — **depth-first search**, not exact path
   - DFS fragility is the core Silver problem: key collision in deep trees → wrong value

3. **SENSOR_MAP_PUBLIC** keys used by sensors and weather entity:
   `temperature`, `temperatureFeelsLike`, `relativeHumidity`, `pressureAltimeter`,
   `windSpeed`, `windGust`, `windDirection`, `wind_strength`, `rainfall`,
   `condition`, `wxPhraseLong`, `uvIndex`, `validTimeLocal`, `location_name`,
   `sunrise`, `sunset`, `moonrise`, `moonset`, `moon_phase`, `moon_phase_date`,
   `fire_danger`, `fire_season`, `pollen_levels`, `pollen_type`,
   `weather_warnings`, `tomorrow_*`, `drying_*`, `breakdown_*`,
   `hourly_temp`, `hourly_obs`, `hourly_skip`, `daily_*`

## Silver tier goal
Replace `get_from_dict` DFS lookups with a typed `MetServicePublicData` dataclass
normalised at fetch time. Coordinator stores the dataclass; sensors/weather read
typed attributes. Contract tests in `test_coordinator_data.py` must stay green
throughout the refactor.

IQS Silver requirements also include: `action-setup`, `test-before-configure`,
`test-before-setup`, `integration-owner`, `docs-*`, `reauthentication-flow`.

## Release workflow (CRITICAL)

1. Bump `manifest.json` version
2. Update `release_notes.md`
3. Commit + push
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
5. Upload zip to GitHub release asset; in HACS use **⋮ → Redownload** then restart HA.

## PowerShell git commit messages
Avoid here-strings for commit messages containing special characters. Use a variable:
```powershell
$msg = "subject`n`nbody`n`nCo-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
git commit -m $msg
```

## Production HA
- URL: `http://192.168.3.3:8123` — **never develop directly against it**
- Integration installed via HACS from the GitHub release zip

## Dev HA (WSL)
- Config dir: `C:\Users\mattn\projects\metservice-weather\config\`
- Launch: `preview_start("MetService Weather — HA Dev Instance")` (defined in `C:\Users\mattn\projects\ha\.claude\launch.json`)
- Credentials: `devadmin / MetsDev2026!`
- Integration loaded via PYTHONPATH — no install/zip needed, just restart HA after code changes
- If `index.html` render fix is lost after pip upgrade: `wsl python3 /mnt/c/Users/mattn/projects/metservice-weather/fix_index.py` then restart
