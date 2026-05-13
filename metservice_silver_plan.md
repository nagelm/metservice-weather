# Silver IQS Plan — metservice_weather

> **Bronze is complete (v0.9.18):** runtime-data, parallel-updates, entity-unavailable, config flow tests (9), coordinator contract tests (44), README with Removal section.

---

## Already Compliant — No Action Needed

| Rule | Reason |
|------|--------|
| `action-exceptions` | No custom service actions; rule N/A |
| `config-entry-unloading` | `async_unload_entry` fully implemented |
| `integration-owner` | `manifest.json` codeowners: `@ciejer @nagelm` |
| `parallel-updates` | `PARALLEL_UPDATES = 0` in `sensor.py` and `weather.py` ✓ |
| `entity-unavailable` | Custom `available` override removed; `CoordinatorEntity` handles it ✓ |

---

## Changes Required

### 1. `log-when-unavailable` — Remove duplicate logs before `UpdateFailed`
**File:** `custom_components/metservice_weather/coordinator.py`

`DataUpdateCoordinator` logs automatically on first failure and on recovery. Any `_LOGGER.error(...)` immediately before `raise UpdateFailed(...)` creates duplicate spam.

Audit `coordinator.py`: remove error-level logs that precede `raise UpdateFailed`. Keep `_LOGGER.debug` for diagnostics.

---

### 2. `reauthentication-flow` — Add reauth for mobile API
**Files:** `config_flow.py`, `coordinator.py`, `strings.json`, `translations/en.json`

#### coordinator.py
Raise `ConfigEntryAuthFailed` instead of `UpdateFailed` on HTTP 401/403 from mobile API:
```python
from homeassistant.exceptions import ConfigEntryAuthFailed

if response.status in (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN):
    raise ConfigEntryAuthFailed("Mobile API key rejected")
```

#### config_flow.py
Add `async_step_reauth` and `async_step_reauth_confirm` to `WeatherFlowHandler`:
```python
async def async_step_reauth(self, entry_data: dict) -> FlowResult:
    self._reauth_entry = self._get_reauth_entry()
    if self._reauth_entry.data.get(CONF_API) != "mobile":
        return self.async_abort(reason="not_applicable")
    return await self.async_step_reauth_confirm()

async def async_step_reauth_confirm(self, user_input=None):
    errors = {}
    if user_input is not None:
        api_key = user_input.get(CONF_MOBILE_API_KEY, "").strip()
        if not api_key:
            errors[CONF_MOBILE_API_KEY] = "api_key_required"
        else:
            try:
                session = async_create_clientsession(self.hass)
                with async_timeout.timeout(10):
                    response = await session.get(
                        "https://api.metservice.com/mobile/nz/weatherData/-43.123/172.123",
                        headers={**_MOBILE_HEADERS, "apiKey": api_key},
                    )
                if response.status == HTTPStatus.OK:
                    return self.async_update_reload_and_abort(
                        self._reauth_entry,
                        data={**self._reauth_entry.data, CONF_MOBILE_API_KEY: api_key},
                    )
                errors[CONF_MOBILE_API_KEY] = "invalid_api_key"
            except Exception:
                errors["base"] = "cannot_connect"

    return self.async_show_form(
        step_id="reauth_confirm",
        data_schema=vol.Schema({vol.Required(CONF_MOBILE_API_KEY): str}),
        errors=errors,
    )
```

#### strings.json / translations/en.json
Add under `config.step`:
```json
"reauth_confirm": {
  "title": "Re-authenticate MetService",
  "description": "Your MetService mobile API key has been rejected. Enter a new key.",
  "data": { "mobile_api_key": "Mobile API key" }
}
```
Add under `config.abort`:
```json
"not_applicable": "Reauthentication is only available for mobile API entries."
```

---

### 3. `test-coverage` — Achieve >95% coverage
**New/extended test files**

Build on the existing 53 tests. Add:

#### tests/test_coordinator.py
Mock `aiohttp` — no real network calls:
- Successful public API fetch → `data` populated
- Successful mobile API fetch → `data` populated
- Network timeout → `UpdateFailed` raised
- HTTP 401 from mobile → `ConfigEntryAuthFailed` raised
- Malformed JSON → `UpdateFailed` or graceful None
- Tide/boating/surf URLs: with and without configuration

#### tests/test_sensor.py
Using coordinator with fixture data pre-loaded:
- All public API sensors created
- All mobile API sensors created
- `native_value` returns correct value via accessor
- `native_value` returns `None` when data is None
- `extra_state_attributes` returns correct dict
- `available` is `False` when `coordinator.last_update_success` is False

#### tests/test_weather.py
- Weather entity created for public and mobile API
- `condition` maps correctly from CONDITION_MAP
- `async_forecast_hourly` returns `Forecast` list with required keys
- `async_forecast_daily` returns `Forecast` list with required keys
- Entity unavailable when coordinator fails

#### tests/test_config_flow.py (extend existing 9 cases)
- Reauth: valid new key → entry updated and reloaded
- Reauth: empty key → `api_key_required`
- Reauth: invalid key → `invalid_api_key`
- Reauth: network error → `cannot_connect`
- Reauth: public API entry → aborts `not_applicable`

Run: `wsl bash scripts/test.sh --cov=custom_components/metservice_weather --cov-fail-under=95`

---

### 4. `docs-configuration-parameters` and `docs-installation-parameters`
**File:** `README.md`

Extend existing README sections:

**Setup fields** (shown during config flow):
- Device name — entity prefix, recommend using location name
- Weather location — ~170 NZ locations, what if yours isn't listed
- Marine region — optional, what it unlocks (tide/boating/surf sensors)
- Mobile API override + key — when to use it, how to get the key

**Marine configuration fields** (second step):
- Tide station, boating location, surf spot — all optional and independent

---

## Verification

1. `wsl bash scripts/test.sh --cov=custom_components/metservice_weather --cov-fail-under=95` passes
2. Force 401 from mobile API in dev HA → reauth notification appears → new key accepted → integration resumes
3. Network disconnect in dev HA → entities go unavailable → reconnect → recover; exactly one error log + one recovery log
4. `grep -r "_LOGGER.error" custom_components/metservice_weather/coordinator.py` shows no errors immediately before `raise UpdateFailed`

---

## Effort Estimate

| Item | Effort |
|------|--------|
| Remove duplicate pre-`UpdateFailed` logs | 30 min |
| `ConfigEntryAuthFailed` on 401/403 | 30 min |
| Reauthentication flow (code + strings) | ~2 hours |
| Full test suite to >95% coverage | ~8–12 hours |
| README config/installation parameter docs | 1 hour |

**Recommended order:**
1. Remove duplicate logs
2. `ConfigEntryAuthFailed` in coordinator
3. Reauth flow + strings
4. Tests (config flow reauth → coordinator → sensor → weather)
5. README docs
