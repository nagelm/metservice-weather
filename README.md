# MetService New Zealand Weather

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)

Real-time and forecast weather data from [MetService NZ](https://www.metservice.com) for Home Assistant. New Zealand's only purpose-built weather integration, using the same data source as the MetService website and app.

> **This integration is a fork of [ciejer/metservice-weather](https://github.com/ciejer/metservice-weather)**, built on the foundational work of [@ciejer](https://github.com/ciejer). This fork has diverged significantly — resolving over 20 open upstream issues, adding new sensors, redesigning the config flow, and working toward Home Assistant Integration Quality Scale compliance. Both versions are available via HACS; install whichever suits your needs.

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
| Pressure Trend | Rising / Falling / Steady |
| Wind Speed | km/h |
| Wind Gust | km/h |
| Wind Direction | Cardinal (e.g. SW) |
| Wind Strength | Beaufort-scale description (e.g. "Fresh", "Near gale") |
| Rainfall | mm accumulated today |
| UV Index | Low / Moderate / High / Very High / Extreme |
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

**Seasonal / environmental**

| Sensor | Notes |
|--------|-------|
| Pollen Level | When in season |
| Pollen Type | When in season |
| Clothes Drying Time — Morning | Time window for drying |
| Clothes Drying Time — Afternoon | Time window for drying |
| Clothes Drying — Next Good Day | Day name when today is a washout |
| Fire Season | Active / Inactive |
| Fire Danger | Fire danger level |
| Weather Warnings | Active warning text; "No warnings" when clear |

**Sunrise / sunset / moon**

| Sensor | Notes |
|--------|-------|
| Sunrise / Sunset | Today's times as local strings |
| Moonrise / Moonset | Today's times as local strings |
| Moon Phase | Next upcoming phase name |
| Next Moon Phase Date | HA timestamp for automations |

**Marine *(optional — requires configuration)***

| Sensor | Requires |
|--------|---------|
| Next High Tide | Tide station configured |
| Next Low Tide | Tide station configured |
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

### Weather entity

A full Home Assistant weather entity with:

- Current condition (correctly returns `clear-night` when the sun is below the horizon)
- 48-hour hourly forecast — temperature, precipitation, wind speed and bearing
- 7-day daily forecast — high/low temperature, condition, plain-English description, and precipitation range estimates

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

#### Marine Region *(optional)*
Select the marine region that covers your area to enable tide, boating, and surf sensors. The integration will then ask you to choose specific stations on the next screen. Choose **None — skip marine data** if you don't need any marine sensors.

---

> **Mobile API removed in v1.0.0** — The mobile API override (and its private API key requirement) has been removed as part of the path toward Home Assistant Core submission. If you rely on GPS-based location tracking or a location not in the list above, stay on [v0.9.19](https://github.com/nagelm/metservice-weather/releases/tag/v0.9.19) — it remains fully functional for that purpose.

---

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

The setup screen opens with all your current values pre-filled. You can change location, marine region, or toggle the mobile API without deleting and re-adding the integration.

> **Note:** Changing between public and mobile API requires deleting and re-adding the integration, as entity unique IDs are tied to the API type.

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

- [@ciejer](https://github.com/ciejer) — original integration author and maintainer
- [jaydeethree](https://github.com/jaydeethree/Home-Assistant-weatherdotcom) and [alexander0042](https://github.com/alexander0042/pirate-weather-ha) — structural reference
- [natekspencer](https://github.com/natekspencer/hacs-vivint) — installation / config structure
