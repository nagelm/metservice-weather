# MetService New Zealand Weather — Home Assistant Integration

Real-time and forecast weather data from [MetService NZ](https://www.metservice.com), delivered as Home Assistant entities.

> **This is a personal fork of [ciejer/metservice-weather](https://github.com/ciejer/metservice-weather).**
> Full credit to [@ciejer](https://github.com/ciejer) for building and maintaining the original integration.
> This fork applies a collection of fixes and quality improvements that have not yet landed upstream — see [release_notes.md](release_notes.md) for details.

---

## What you get

### Sensors
| Sensor | Notes |
|--------|-------|
| Temperature | Current observed temperature |
| Temperature — Feels Like | Apparent temperature |
| Relative Humidity | % |
| Pressure | hPa, with tendency trend sensor |
| Wind Speed / Gust / Direction | km/h |
| Rainfall | mm accumulated today |
| UV Index | Text level (Low / Moderate / High / etc.) |
| Weather Description | Plain-English forecast text |
| Pollen Levels / Type | When in season |
| Clothes Drying Time | Morning and afternoon estimates |
| Fire Season / Fire Danger | Regional fire status |
| MetService Weather Warnings | Active warnings text |
| Next High Tide / Next Low Tide | Requires tide configuration |
| Boating Conditions / Boating Forecast | Requires boating configuration |

### Weather entity
The integration creates a full HA weather entity with:
- Current condition (including `clear-night` when the sun is below the horizon)
- 48-hour hourly forecast with temperature, precipitation, wind speed and bearing
- 7-day daily forecast with high/low temperature, condition, plain-English description, and precipitation estimates

---

## Installation

### HACS (recommended)
1. [Install HACS](https://hacs.xyz/docs/setup/download) if you haven't already
2. Add this repository as a custom repository in HACS:
   **HACS → Integrations → ⋮ → Custom repositories**
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

#### Integration name
A label used as the prefix for all entities created by this integration (e.g. `Napier`). Defaults to your Home Assistant location name. You can set up multiple instances with different names if you want weather for more than one location.

#### Weather location
The MetService location used to fetch weather data. Choose the town or city closest to you. This is only used with the public API (the default).

#### Tide information region *(optional)*
Select the marine region that covers your area to enable tide sensors. The integration will then ask you to choose a specific tide station on the next screen. Choose **None — skip** if you don't need tides.

#### Boating conditions region *(optional)*
Select a marine region to enable boating and surf condition sensors. The integration will then ask you to choose a specific location on the next screen. Choose **None — skip** if you don't need this.

#### Override public web data with mobile API *(default: false)*
Enables an alternative data source that uses your Home Assistant GPS coordinates (latitude/longitude) rather than the fixed location selected above.

**You almost certainly do not need this.** The public API covers around 150 NZ towns and rural locations and provides more sensor data (rainfall, pollen, UV index, etc.).

Use the mobile API only if:
- Your exact location is not in the weather location list above, **and** the nearest listed location gives noticeably wrong data
- You want weather data to update based on your physical GPS position (e.g. you travel frequently)

Enabling this requires a **Mobile API key** — see below.

#### Mobile API key *(only required if mobile API override is enabled)*
A private API key used by the MetService mobile app. This key is not publicly available — you need to extract it by inspecting the network traffic from the MetService iOS or Android app.

See [this upstream issue](https://github.com/ciejer/metservice-weather/issues/12) for instructions on how to obtain it.

---

### Screen 2 — Marine locations *(only appears if a marine region was selected)*

#### Tide station
The specific tide gauge closest to you within your selected region.

#### Boating location
The specific boating area within your selected region.

Both lists are fetched live from MetService when this screen loads.

---

## Reconfiguring

To change any setting after initial setup:

1. Go to **Settings → Devices & Services**
2. Find the **MetService New Zealand Weather** card
3. Click the **⋮** menu → **Reconfigure**

The setup screen opens with all your current values pre-filled. You can change location, marine region, or toggle the mobile API without deleting and re-adding the integration.

> **Note:** Switching between public and mobile API requires deleting and re-adding the integration, because entity unique IDs are tied to the API type.

---

## Multiple locations

You can add the integration more than once with different locations. Each instance gets its own set of entities prefixed with the integration name you choose.

---

## Disclaimer

Weather data is updated every 20 minutes. Always check the MetService website directly in time-critical or safety-of-life situations. This integration should never be relied upon for emergency decisions.

---

## Credits

- [@ciejer](https://github.com/ciejer) — original integration author
- [jaydeethree](https://github.com/jaydeethree/Home-Assistant-weatherdotcom) and [alexander0042](https://github.com/alexander0042/pirate-weather-ha) — structural reference
- [natekspencer](https://github.com/natekspencer/hacs-vivint) — installation / config structure
