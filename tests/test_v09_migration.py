"""Upgrade path from v0.9.x (including ciejer/metservice-weather v0.9).

Each test rebuilds the registry rows v0.9 left behind and checks what a
first setup on the current code does with them.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import slugify
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.metservice_weather import _async_migrate_legacy_unique_ids
from custom_components.metservice_weather.const import DOMAIN
from custom_components.metservice_weather.coordinator import WeatherUpdateCoordinator
from custom_components.metservice_weather.coordinator_types import (
    normalize_public_data,
)
from tests.test_deprecation import _FakeAutomationEntity, _FakeEntityComponent

FIXTURES = Path(__file__).parent / "fixtures"
NAPIER = "/towns-cities/regions/hawkes-bay/locations/napier"
HASTINGS = "/towns-cities/regions/hawkes-bay/locations/hastings"
OTAKI = "/rural/regions/kapiti-horowhenua/locations/otaki"

AUTOMATIONS_PATCH = (
    "custom_components.metservice_weather.deprecation.automations_with_entity"
)
SCRIPTS_PATCH = "custom_components.metservice_weather.deprecation.scripts_with_entity"

# ciejer v0.9 current_condition_sensor_descriptions_public: key -> name
V09_PUBLIC = {
    "validTimeLocal": "Forecast Description Updated Time",
    "wxPhraseLong": "Weather Description",
    "relativeHumidity": "Relative Humidity",
    "uvIndex": "UV Index",
    "windDirection": "Wind Direction",
    "temperatureFeelsLike": "Temperature - Feels Like",
    "temperature": "Temperature",
    "pressureAltimeter": "Pressure",
    "windGust": "Wind Gust",
    "windSpeed": "Wind Speed",
    "pressureTendencyTrend": "Pressure Tendency Trend",
    "pollen_levels": "Pollen Levels",
    "pollen_type": "Pollen Type",
    "weather_warnings": "MetService Weather Warnings",
    "fire_season": "Fire Season",
    "fire_danger": "Fire Danger",
    "drying_index_morning": "Clothes Drying Time - Morning",
    "drying_index_afternoon": "Clothes Drying Time - Afternoon",
    "tides_high": "Next High Tide",
    "tides_low": "Next Low Tide",
}
# ciejer v0.9 current_condition_sensor_descriptions_mobile keys
V09_MOBILE = {
    "validTimeLocal": "Forecast Description Updated Time",
    "wxPhraseLong": "Weather Description",
    "relativeHumidity": "Relative Humidity",
    "uvAlert": "UV Alert",
    "windDirection": "Wind Direction",
    "temperature": "Temperature",
    "pressureAltimeter": "Pressure",
    "windGust": "Wind Gust",
    "windSpeed": "Wind Speed",
    "pressureTendencyTrend": "Pressure Tendency Trend",
    "drying_index_morning": "Clothes Drying Time - Morning",
    "drying_index_afternoon": "Clothes Drying Time - Afternoon",
    "weather_warnings": "MetService Weather Warnings",
    "fire_season": "Fire Season",
    "fire_danger": "Fire Danger",
    "tides_high": "Next High Tide",
    "tides_low": "Next Low Tide",
}
RETIRED = {
    "uvIndex",
    "pressureTendencyTrend",
    "pollen_levels",
    "pollen_type",
    "weather_warnings",
    "fire_season",
    "fire_danger",
    "uvAlert",
}
TIDES = {"tides_high", "tides_low"}


def _napier_data():
    return normalize_public_data(
        json.loads((FIXTURES / "napier_public_current.json").read_text("utf-8")),
        json.loads((FIXTURES / "napier_public_daily.json").read_text("utf-8")),
    )


def _v09_public_data(name, location, tide_url=""):
    data = {
        "api": "public",
        "enable_tides": bool(tide_url),
        "location": location,
        "name": name,
    }
    if tide_url:
        data["tide_region_url"] = "/marine/regions/hawke-bay-wairarapa"
        data["tide_url"] = tide_url
    return data


def _seed_v09(hass, entry, name, device_identifier, keys=V09_PUBLIC):
    """Recreate the registry rows ciejer v0.9 leaves behind for one entry."""
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, device_identifier)},
        name=name,
        manufacturer="MetService",
    )
    ent_reg = er.async_get(hass)
    rows = {}
    for key, v09_name in keys.items():
        rows[key] = ent_reg.async_get_or_create(
            "sensor",
            DOMAIN,
            f"{name},{key}".lower(),
            config_entry=entry,
            device_id=device.id,
            suggested_object_id=slugify(f"{name}_{v09_name}"),
            has_entity_name=True,
            original_name=v09_name,
        )
    rows["weather"] = ent_reg.async_get_or_create(
        "weather",
        DOMAIN,
        f"{name},weather".lower(),
        config_entry=entry,
        device_id=device.id,
        suggested_object_id=slugify(name),
        has_entity_name=True,
        original_name=f"{name} Forecast",
    )
    return device, rows


async def _setup(hass, entry, data):
    async def _first_refresh(coordinator):
        coordinator.data = data

    with patch.object(
        WeatherUpdateCoordinator,
        "async_config_entry_first_refresh",
        autospec=True,
        side_effect=_first_refresh,
    ):
        ok = await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return ok


def _make_v09_entry(data, unique_id):
    return MockConfigEntry(
        domain=DOMAIN, data=data, unique_id=unique_id, title=data["name"], version=1
    )


async def test_v09_full_public_entry(hass):
    """A full v0.9 install keeps every surviving entity, with customisations; retired sensors get the repair naming their replacement."""
    entry = _make_v09_entry(_v09_public_data("Home", NAPIER), f"{DOMAIN}-{NAPIER}")
    entry.add_to_hass(hass)
    device, rows = _seed_v09(hass, entry, "Home", NAPIER)
    ent_reg = er.async_get(hass)
    v09_ids = {key: row.entity_id for key, row in rows.items()}
    assert v09_ids["temperature"] == "sensor.home_temperature"
    assert v09_ids["weather"] == "weather.home"

    ent_reg.async_update_entity(v09_ids["temperature"], name="My temp", icon="mdi:x")

    referenced = {
        v09_ids["uvIndex"]: ["automation.uv_alert"],
        v09_ids["weather_warnings"]: ["automation.warn"],
        v09_ids["temperature"]: ["automation.heat"],
    }
    hass.config.components.add("automation")
    hass.config.components.add("script")
    with (
        patch(AUTOMATIONS_PATCH, side_effect=lambda h, eid: referenced.get(eid, [])),
        patch(SCRIPTS_PATCH, return_value=[]),
    ):
        assert await _setup(hass, entry, _napier_data())

    survivors = set(V09_PUBLIC) - RETIRED - TIDES
    for key in survivors:
        row = ent_reg.async_get(v09_ids[key])
        assert row is not None, key
        assert row.unique_id == f"{NAPIER}_{key}".lower(), key
        assert row.previous_unique_id == f"home,{key}".lower()
        assert hass.states.get(v09_ids[key]) is not None, key
    for key in (RETIRED | TIDES) & set(V09_PUBLIC):
        assert ent_reg.async_get(v09_ids[key]) is None, key
    w = ent_reg.async_get(v09_ids["weather"])
    assert w is not None and w.unique_id == f"{NAPIER}_weather"
    assert hass.states.get("weather.home") is not None

    temp = ent_reg.async_get(v09_ids["temperature"])
    assert temp.name == "My temp" and temp.icon == "mdi:x"
    assert temp.device_id == device.id
    dev = dr.async_get(hass).async_get(device.id)
    assert dev.name == "Napier"

    for r in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        assert not r.entity_id.endswith("_2"), r.entity_id

    issues = {
        iid: issue
        for (dom, iid), issue in ir.async_get(hass).issues.items()
        if dom == DOMAIN
    }
    uv = issues[f"removed_entity_{entry.entry_id}_{slugify(v09_ids['uvIndex'])}"]
    assert uv.translation_placeholders["replacement"] == "UV index"
    warn = issues[
        f"removed_entity_{entry.entry_id}_{slugify(v09_ids['weather_warnings'])}"
    ]
    assert warn.translation_placeholders["replacement"].startswith("Warnings")
    # temperature is kept, so no removed_entity issue for it
    assert (
        f"removed_entity_{entry.entry_id}_{slugify(v09_ids['temperature'])}"
        not in issues
    )


async def test_v09_tides_survive(hass):
    """v0.9 tide sensors keep their entity IDs and move to the marine device."""
    tide_url = (
        "https://www.metservice.com/publicData/webdata/"
        "/marine/regions/hawke-bay-wairarapa/tides/locations/napier"
    )
    entry = _make_v09_entry(
        _v09_public_data("Home", NAPIER, tide_url), f"{DOMAIN}-{NAPIER}"
    )
    entry.add_to_hass(hass)
    device, rows = _seed_v09(hass, entry, "Home", NAPIER)
    ent_reg = er.async_get(hass)
    hass.config.components.add("automation")
    with patch(AUTOMATIONS_PATCH, return_value=[]):
        assert await _setup(hass, entry, _napier_data())
    for key in TIDES:
        row = ent_reg.async_get(rows[key].entity_id)
        assert row is not None, key
        assert row.unique_id == f"{NAPIER}_{key}".lower()
        assert row.device_id != device.id


@pytest.mark.parametrize(
    "name",
    [
        "Smith's Place, Ōtaki (Home)",
        "İSTANBUL",
        "ΣΟΦΟΣ",
        "  spaced  ",
        "a,b,c",
        "HOME",
    ],
)
async def test_v09_odd_names_rekey(hass, name):
    """Typed names with commas, quotes, non-ASCII letters, padding or capitals all re-key."""
    entry = _make_v09_entry(_v09_public_data(name, OTAKI), f"{DOMAIN}-{OTAKI}")
    entry.add_to_hass(hass)
    _device, rows = _seed_v09(hass, entry, name, OTAKI)
    await _async_migrate_legacy_unique_ids(hass, entry)
    ent_reg = er.async_get(hass)
    for key, row in rows.items():
        new = ent_reg.async_get(row.entity_id)
        assert new.unique_id == f"{OTAKI}_{key}".lower(), (name, key, new.unique_id)


async def test_v09_two_entries_same_name(hass):
    """Two entries with the same typed name each set up, and the v0.9 rows stay with the entry that owns them."""
    a = _make_v09_entry(_v09_public_data("Home", NAPIER), f"{DOMAIN}-{NAPIER}")
    b = _make_v09_entry(_v09_public_data("Home", HASTINGS), f"{DOMAIN}-{HASTINGS}")
    a.add_to_hass(hass)
    b.add_to_hass(hass)
    # v0.9: only one entry's rows got registered (the other collided); here B owns them
    _device, rows = _seed_v09(hass, b, "Home", HASTINGS)
    base = _napier_data()
    by_loc = {
        NAPIER: base,
        HASTINGS: dataclasses.replace(base, location_name="Hastings"),
    }

    async def _first_refresh(coordinator):
        coordinator.data = by_loc[coordinator.location]

    hass.config.components.add("automation")
    with (
        patch(AUTOMATIONS_PATCH, return_value=[]),
        patch.object(
            WeatherUpdateCoordinator,
            "async_config_entry_first_refresh",
            autospec=True,
            side_effect=_first_refresh,
        ),
    ):
        # sets up the whole domain, i.e. both entries
        assert await hass.config_entries.async_setup(a.entry_id)
        await hass.async_block_till_done()
    assert a.state is ConfigEntryState.LOADED and b.state is ConfigEntryState.LOADED
    ent_reg = er.async_get(hass)
    row = ent_reg.async_get(rows["temperature"].entity_id)
    assert row.unique_id == f"{HASTINGS}_temperature"
    assert row.config_entry_id == b.entry_id
    a_uids = {
        r.unique_id for r in er.async_entries_for_config_entry(ent_reg, a.entry_id)
    }
    assert f"{NAPIER}_temperature" in a_uids


def _mobile_data(name):
    return {"api": "mobile", "enable_tides": False, "api_key": "k", "name": name}


@pytest.mark.parametrize("new_name", ["Home", "Napier home"])
async def test_v09_mobile_entry_then_reconfigure(hass, new_name):
    """A mobile-API entry keeps its rows until Reconfigure, which re-keys them whether or not the name changes."""
    entry = _make_v09_entry(_mobile_data("Home"), f"{DOMAIN}-Home")
    entry.add_to_hass(hass)
    _device, rows = _seed_v09(hass, entry, "Home", "Home", keys=V09_MOBILE)
    ent_reg = er.async_get(hass)
    hass.config.components.add("automation")
    with patch(AUTOMATIONS_PATCH, return_value=[]):
        await _setup(hass, entry, _napier_data())
    assert all(ent_reg.async_get(r.entity_id) for r in rows.values())

    # What Reconfigure writes (config_flow.async_step_setup + _finish_flow)
    hass.config_entries.async_update_entry(
        entry,
        data={
            **entry.data,
            "location": NAPIER,
            "name": new_name,
            "api": "public",
            "auto_hide_seasonal": False,
            "marine_region": "",
            "tide_url": "",
            "boating_url": "",
            "surf_url": "",
        },
    )
    with patch(AUTOMATIONS_PATCH, return_value=[]):
        if entry.state is ConfigEntryState.SETUP_ERROR:
            await hass.config_entries.async_unload(entry.entry_id)
        assert await _setup(hass, entry, _napier_data())
    kept = ent_reg.async_get(rows["temperature"].entity_id)
    assert kept is not None
    assert kept.unique_id == f"{NAPIER}_temperature"


async def test_v09_already_crossed_has_both(hass):
    """Someone who crossed v1.0 earlier keeps the current row; the duplicate old one is cleaned up and the rest re-key."""
    entry = _make_v09_entry(_v09_public_data("Home", NAPIER), f"{DOMAIN}-{NAPIER}")
    entry.add_to_hass(hass)
    _device, rows = _seed_v09(hass, entry, "Home", NAPIER)
    ent_reg = er.async_get(hass)
    new = ent_reg.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{NAPIER}_temperature",
        config_entry=entry,
        suggested_object_id="napier_temperature",
    )
    hass.config.components.add("automation")
    with patch(AUTOMATIONS_PATCH, return_value=[]):
        assert await _setup(hass, entry, _napier_data())
    assert ent_reg.async_get(new.entity_id) is not None
    assert ent_reg.async_get(rows["temperature"].entity_id) is None
    # the other keys of the old install are re-keyed
    assert ent_reg.async_get(rows["windSpeed"].entity_id).unique_id == (
        f"{NAPIER}_windspeed"
    )


async def test_v09_forecast_attribute_repair_on_kept_weather(hass):
    """The removed-forecast-attributes repair finds automations using the kept v0.9 weather entity."""
    entry = _make_v09_entry(_v09_public_data("Home", NAPIER), f"{DOMAIN}-{NAPIER}")
    entry.add_to_hass(hass)
    _seed_v09(hass, entry, "Home", NAPIER)
    hass.config.components.add("automation")
    hass.data["automation"] = _FakeEntityComponent(
        {
            "automation.rain": _FakeAutomationEntity(
                {
                    "trigger": [{"platform": "state", "entity_id": "weather.home"}],
                    "action": [
                        {
                            "service": "notify.notify",
                            "data": {
                                "message": "{{ state_attr('weather.home','forecast_hourly') }}"
                            },
                        }
                    ],
                }
            )
        }
    )
    with patch(
        AUTOMATIONS_PATCH,
        side_effect=lambda h, eid: ["automation.rain"] if eid == "weather.home" else [],
    ):
        assert await _setup(hass, entry, _napier_data())
    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, f"forecast_attributes_{entry.entry_id}"
    )
    assert issue is not None
