# MetService New Zealand Weather

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)

Real-time and forecast weather data from [MetService NZ](https://www.metservice.com) for Home Assistant. New Zealand's only purpose-built weather integration, using the same data source as the MetService website and app.

> **This integration is a fork of [ciejer/metservice-weather](https://github.com/ciejer/metservice-weather)**, built on the foundational work of [@ciejer](https://github.com/ciejer). This fork has since diverged significantly — see [What's changed since the fork](#whats-changed-since-the-fork).

---

## What's changed since the fork

This fork was started to resolve issues blocking daily use and to bring the integration toward [Home Assistant Integration Quality Scale](https://developers.home-assistant.io/docs/integration_quality_scale_index) compliance. Key changes over the original:

- **Public API only** — the integration now uses MetService's public web data API exclusively. No API key or account required.
- **Typed data model** — a `MetServicePublicData` dataclass replaces the raw dict. All sensors read typed attributes; no more string-key lookups at runtime.
- **40+ sensors** — full sensor coverage including sub-day breakdown, drying index, moon phase, fire danger, pollen, and all marine sensors (tides, boating, surf).
- **Marine data** — optional tide station, boating conditions, and surf sensors, each independently configurable.
- **Config flow redesigned** — two-step setup with live-fetched marine station lists; reconfigure support; duplicate location prevention.
- **Forecast caching** — hourly and daily forecasts are cached and invalidated only on coordinator update, avoiding redundant API calls.
- **IQS Gold compliance** — translation keys, `icons.json`, stable unique IDs, `asyncio.timeout` throughout, 206 tests at 95%+ coverage. Working toward Core inclusion.
- **Bug fixes** — hourly wind speed, `clear-night` condition when sun is below horizon, coordinator `always_update=False`, `async_get_clientsession` (no session leaks), and more.

---

## Mobile API — removed in v1.0.0

> **v0.9.19 is the last release with mobile API support.**

Earlier versions of this integration included an option to use the MetService mobile app API, which enabled GPS-based location data not available from the public web API. That feature has been removed in v1.0.0.

**Why it was removed:** The mobile API relies on a private API key extracted from the MetService iOS app. This key is not publicly distributed, not officially supported for third-party use, and incompatible with the requirements for inclusion in Home Assistant Core. Retaining it would permanently block this integration from being accepted into the Core repository.

**If you rely on the mobile API** — for GPS-based location tracking or a location not in the list of ~150 supported towns — stay on [v0.9.19](https://github.com/nagelm/metservice-weather/releases/tag/v0.9.19). It remains fully functional for that purpose and will continue to be available via HACS.

---

## What you get

### Sensors

**Current conditions**

| Sensor | Notes |
|--------|-------|
| Temperature | Current observed temperature |
| Temperature — Feels Like | Apparent temperature |
| Today's High / Low | Observed or forecast high and low for today |
| Relative Humidity | % |
| Pressure | hPa |
| Pressure Trend | Enum: `rising` / `falling` / `stable` |
| Wind Speed | km/h |
| Wind Gust | km/h |
| Wind Direction | Cardinal (e.g. SW) |
| Wind Strength | Enum: `calm` → `storm` (MetService's Beaufort-style scale) |
| Rainfall | mm accumulated today |
| UV Index | Enum: `low` / `moderate` / `high` / `very_high` / `extreme`; advice + protection window as attributes |
| Weather Description | Plain-English forecast text |

**Sub-day forecast**

| Sensor | Notes |
|--------|-------|
| Today — Morning Condition | |
| Today — Afternoon Condition | |
| Today — Evening Condition | |
| Today — Overnight Condition | |
| Tomorrow — Condition | |
| Tomorrow — High Temperature | |
| Tomorrow — Low Temperature | |
| Tomorrow — Description | |
| Rain — Next 8 Hours | mm from the hourly forecast; **disabled by default** |
| Rain — Next 24 Hours | mm from the hourly forecast; **disabled by default** |
| Next Rain Expected | Timestamp of the first forecast hour with rain; **disabled by default** |

**Seasonal / environmental**

| Sensor | Notes |
|--------|-------|
| Pollen | Always (see seasonal notes) |
| Clothes Drying Time — Morning | Time window for drying |
| Clothes Drying Time — Afternoon | Time window for drying |
| Clothes Drying — Next Good Day | Day name when today is a washout |
| Fire Season | Enum: `open` / `restricted` / `prohibited` (FENZ) |
| Fire Danger | Enum: `low` → `extreme` (NIWA index) |
| Weather Warnings | Severity enum: `none` / `watch` / `warning` / `orange` / `red`; headline + structured list as attributes |

**Sunrise / sunset / moon**

| Sensor | Notes |
|--------|-------|
| Sunrise / Sunset | Timestamps (old `7:42am`-style text kept as `display` attribute) |
| Moonrise / Moonset | Timestamps (`display` attribute as above) |
| Moon Phase | Enum: `new` / `first_quarter` / `full` / `last_quarter` — the next principal phase event |
| Next Moon Phase Date | HA timestamp for automations |

**Marine *(optional — requires configuration)***

| Sensor | Requires |
|--------|---------|
| Next High Tide (+ height and day table attributes) | Tide station configured |
| Next Low Tide (+ height and day table attributes) | Tide station configured |
| Boating Conditions | Boating location configured |
| Boating Forecast | Boating location configured |
| Surf Conditions | Surf location configured |
| Surf Rating | Surf location configured |
| Surf Wave Height | Surf location configured |
| Surf Set Face | Surf location configured |
| Surf Swell Direction | Surf location configured |
| Surf Swell Height | Surf location configured |
| Surf Wind Direction | Surf location configured |
| Surf Wind Speed / Gust | Surf location configured |
| Surf Period | Surf location configured |

### Seasonal sensors — `unknown` off-season is normal

Some MetService products pause for part of the year. The API keeps the data
structures in place but empties the payload server-side, so the matching sensors
correctly read `unknown` until the product resumes — that's MetService pausing,
not a bug:

| Sensor | Behaviour |
|---|---|
| UV Index | Suspended over winter — the API replaces the sun-protection data with an explicit end-of-season stub |
| Fire Danger / Fire Season | Published only while a fire season is declared (varies by district); off-season the API sends no fire data |

Two related products that do **not** go unknown, but change character with the
seasons:

| Sensor | Behaviour |
|---|---|
| Pollen | Runs year-round. State is the current exposure level (`none`/`low`/`moderate`/`high`, from MetService's own severity taxonomy); allergens about to start their season appear in the `imminent_allergens` attribute, active allergens per level in the `active_allergens` attribute |
| Clothes Drying | Year-round for towns/cities; rural locations may not carry it |

Sensors a **location can never provide** (e.g. wind/temperature observations for
rural locations without a weather station) are not created at all, rather than
sitting permanently unknown.

### Weather entity

A full Home Assistant weather entity with:

- Current condition (correctly returns `clear-night` when the sun is below the horizon)
- 48-hour hourly forecast — temperature, precipitation, wind speed and bearing
- 7-day daily forecast — high/low temperature, condition, plain-English description, chance of rain (MetService's probability of at least 1 mm falling that day), and — for today and tomorrow — the expected rainfall amount in mm, aggregated from the hourly data (actual recorded rainfall for elapsed hours plus the forecast for the rest of the day)

**Where to find the chance of rain:** Home Assistant no longer exposes forecasts
as entity attributes — forecast fields are only visible via the
`weather.get_forecasts` action, template sensors built on it, or forecast cards
(the built-in weather card's daily tiles don't render probability; custom cards
like clock-weather-card do). Also note an upstream limitation: **towns-cities
locations only publish the chance of rain from roughly day 3 onward** — MetService
covers the nearer days with hourly rainfall amounts instead. This integration
relays those in the hourly forecast and also sums them into daily rainfall
totals for today and tomorrow, so every day of the daily forecast carries rain
information except day 2, which upstream covers in neither form. Rural
locations publish the probability for all seven days.

---

## Requirements

- Home Assistant 2024.2 or later
- HACS (for the recommended installation method)
- A New Zealand location — MetService only covers NZ

---

## Installation

### HACS (recommended)

1. [Install HACS](https://hacs.xyz/docs/setup/download) if you haven't already
2. Add this repository as a custom repository in HACS:\
   **HACS → Integrations → ⋮ → Custom repositories**\
   URL: `https://github.com/nagelm/metservice-weather` — Category: Integration
3. Search for **MetService New Zealand Weather** and install it
4. Restart Home Assistant

### Manual

Copy the `custom_components/metservice_weather` folder into your Home Assistant `config/custom_components/` directory, then restart Home Assistant.

---

## Configuration

Go to **Settings → Devices & Services → Add Integration** and search for **MetService New Zealand Weather**.

Setup takes at most two screens.

### Screen 1 — Setup

#### Device name
A label used as the prefix for all entities created by this integration (e.g. `Napier`). Defaults to your Home Assistant location name. You can set up multiple instances with different names to get weather for more than one location — each instance creates its own independent set of entities.

#### Weather location
The MetService location used to fetch weather data. Choose the town or city closest to you. Around 150 NZ towns and rural locations are available.

#### Automatically remove sensors while MetService publishes no data *(optional)*
Off by default. When enabled, seasonal sensors (UV, fire danger, clothes drying) are removed while
MetService pauses the product server-side, and return automatically when data resumes. When disabled,
they stay and read `unknown` off-season.

#### Marine Region *(optional)*
Select the marine region that covers your area to enable tide, boating, and surf sensors. The integration will then ask you to choose specific stations on the next screen. Choose **None — skip marine data** if you don't need any marine sensors.

### Screen 2 — Marine locations *(only shown if a marine region was selected)*

Choose a specific station for each marine service you want. Each selector includes a **None — skip** option — you can enable tides without enabling boating, or surf without tides.

| Field | Sensors enabled |
|-------|----------------|
| Tide station | Next High Tide, Next Low Tide |
| Boating location | Boating Conditions, Boating Forecast |
| Surf location | 10 surf sensors (conditions, rating, swell, wind, period) |

Both lists are fetched live from MetService when this screen loads.

---

## Reconfiguring

To change any setting after initial setup:

1. Go to **Settings → Devices & Services**
2. Find the **MetService New Zealand Weather** card
3. Click **⋮ → Reconfigure**

The setup screen opens with all your current values pre-filled. You can change location or marine stations without deleting and re-adding the integration.

---

## Multiple locations

You can add the integration more than once with different device names and locations. Each instance is fully independent with its own set of entities.

---

## Removal

1. Go to **Settings → Devices & Services**
2. Find the **MetService New Zealand Weather** card
3. Click **⋮ → Delete**
4. Confirm the deletion — this removes all entities and the config entry

If you installed via HACS and want to remove the integration files too:
1. Go to **HACS → Integrations**
2. Find **MetService New Zealand Weather**
3. Click **⋮ → Remove**
4. Restart Home Assistant

---

## Contributing

Issues and pull requests are welcome. If you've found a bug or have an improvement in mind, please open an issue first so we can discuss it before you invest time in a PR.

For bugs: include your HA version, integration version, and the relevant section of your Home Assistant log (`Settings → System → Logs`).

---

## Disclaimer

Weather data is updated every 20 minutes. Always check the MetService website directly in time-critical or safety-of-life situations. This integration should never be relied upon for emergency decisions.

---

## Credits

- [@ciejer](https://github.com/ciejer) — original integration author and maintainer of [ciejer/metservice-weather](https://github.com/ciejer/metservice-weather)
- [jaydeethree](https://github.com/jaydeethree/Home-Assistant-weatherdotcom) and [alexander0042](https://github.com/alexander0042/pirate-weather-ha) — structural reference
- [natekspencer](https://github.com/natekspencer/hacs-vivint) — installation / config structure
