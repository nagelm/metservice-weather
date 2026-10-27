"""Tests for MetServiceEntity's device grouping (location device vs marine device)."""

from __future__ import annotations

from custom_components.metservice_weather.const import DOMAIN
from custom_components.metservice_weather.coordinator import (
    WeatherUpdateCoordinator,
    WeatherUpdateCoordinatorConfig,
)
from custom_components.metservice_weather.coordinator_types import MetServicePublicData
from custom_components.metservice_weather.entity import (
    MetServiceEntity,
    _marine_device_name,
)
from custom_components.metservice_weather.sensor import WeatherSensor
from custom_components.metservice_weather.weather_current_conditions_sensors import (
    current_condition_sensor_descriptions_public,
)


def _make_coordinator(
    hass, tide_url="", boating_url="", surf_url=""
) -> WeatherUpdateCoordinator:
    config = WeatherUpdateCoordinatorConfig(
        api_url="https://www.metservice.com/publicData/webdata",
        warnings_url="https://www.metservice.com/publicData/webdata/warnings-service",
        unit_system="metric",
        location="/towns-cities/regions/hawkes-bay/locations/napier",
        location_name="Napier",
        tide_url=tide_url,
        boating_url=boating_url,
        surf_url=surf_url,
    )
    return WeatherUpdateCoordinator(hass, config)


async def test_location_device_prefers_api_label(hass):
    """The town device is named after the API's verbatim location label."""
    coord = _make_coordinator(hass)
    coord.data = MetServicePublicData(location_name="Porirua")
    ent = MetServiceEntity(coord)
    assert ent.device_info["name"] == "Porirua"


async def test_location_device_falls_back_to_locations_table(hass):
    """Without data, the bundled LOCATIONS table names the device."""
    coord = _make_coordinator(hass)
    coord.data = None
    ent = MetServiceEntity(coord)
    assert ent.device_info["name"] == "Napier"


async def test_location_device_falls_back_to_entry_name_for_unknown_path(hass):
    """Unknown location path with no data: the typed entry name is the last resort."""
    config = WeatherUpdateCoordinatorConfig(
        api_url="https://www.metservice.com/publicData/webdata",
        warnings_url="https://www.metservice.com/publicData/webdata/warnings-service",
        unit_system="metric",
        location="/towns-cities/regions/nowhere/locations/atlantis",
        location_name="My Custom Name",
        tide_url="",
        boating_url="",
        surf_url="",
    )
    coord = WeatherUpdateCoordinator(hass, config)
    coord.data = None
    ent = MetServiceEntity(coord)
    assert ent.device_info["name"] == "My Custom Name"


async def test_marine_fallback_uses_resolved_location_label(hass):
    """The '<location> Marine' fallback uses the resolved label, not the entry name."""
    coord = _make_coordinator(hass)
    coord.data = MetServicePublicData(location_name="Porirua")
    ent = MetServiceEntity(coord, device="marine")
    assert ent.device_info["name"] == "Porirua Marine"


def test_marine_device_name_known_slug_matches_metservice_label():
    """A known MetService region slug maps to its real editorial label."""
    assert _marine_device_name("kapiti-wellington", "Napier") == "Kapiti and Wellington"


def test_marine_device_name_known_slug_not_derivable_mechanically():
    """Some real labels don't come from a mechanical hyphen->title-case."""
    assert _marine_device_name("east-auckland", "Napier") == "Auckland East Coast"
    assert _marine_device_name("christchurch", "Napier") == "Canterbury"
    assert _marine_device_name("west-coast-north", "Napier") == "Buller and Westland"


def test_marine_device_name_unknown_slug_generic_derivation():
    """An unrecognised slug falls back to a generic derivation."""
    assert _marine_device_name("future-region", "Napier") == "Future Region"
    assert _marine_device_name("solo", "Napier") == "Solo"


def test_marine_device_name_empty_slug_falls_back_to_location_name():
    """An empty/missing slug falls back to f'{location_name} Marine'."""
    assert _marine_device_name("", "Napier") == "Napier Marine"


async def test_location_device_is_the_default(hass):
    """The default device="location" builds the original town/rural device."""
    coord = _make_coordinator(hass)
    ent = MetServiceEntity(coord)
    info = ent.device_info
    assert info["identifiers"] == {(DOMAIN, coord.location)}
    assert info["name"] == "Napier"
    assert info.get("via_device") is None
    assert info.get("via_device_id") is None


async def test_marine_device_has_distinct_identifier_and_via_device(hass):
    """device="marine" builds a separate, linked device."""
    coord = _make_coordinator(
        hass,
        tide_url=(
            "https://www.metservice.com/publicData/webdata/marine/regions/"
            "kapiti-wellington/tides/locations/wellington"
        ),
    )
    coord.location_device_id = "parent-device-id"
    ent = MetServiceEntity(coord, device="marine")
    info = ent.device_info
    assert info["identifiers"] == {(DOMAIN, f"{coord.location}_marine")}
    assert info["identifiers"] != {(DOMAIN, coord.location)}
    assert info["via_device_id"] == "parent-device-id"
    assert "via_device" not in info
    assert info["name"] == "Kapiti and Wellington"


async def test_marine_device_omits_via_device_id_when_parent_unregistered(hass):
    """No cached parent id means the key is omitted, not written as None."""
    coord = _make_coordinator(
        hass,
        tide_url=(
            "https://www.metservice.com/publicData/webdata/marine/regions/"
            "kapiti-wellington/tides/locations/wellington"
        ),
    )
    assert coord.location_device_id is None
    info = MetServiceEntity(coord, device="marine").device_info
    assert "via_device_id" not in info
    assert "via_device" not in info


async def test_marine_device_falls_back_to_location_name_when_no_marine_url(hass):
    """No tide/boating/surf URL configured falls back to a location-based name."""
    coord = _make_coordinator(hass)
    ent = MetServiceEntity(coord, device="marine")
    assert ent.device_info["name"] == "Napier Marine"


async def test_marine_and_location_devices_share_manufacturer_and_model(hass):
    """Both devices use the same manufacturer/model/configuration_url style."""
    coord = _make_coordinator(
        hass,
        tide_url=(
            "https://www.metservice.com/publicData/webdata/marine/regions/"
            "kapiti-wellington/tides/locations/wellington"
        ),
    )
    location_info = MetServiceEntity(coord).device_info
    marine_info = MetServiceEntity(coord, device="marine").device_info
    assert location_info["manufacturer"] == marine_info["manufacturer"]
    assert location_info["model"] == marine_info["model"]
    assert location_info["configuration_url"] == marine_info["configuration_url"]


async def test_marine_sensor_composed_friendly_name_changes_from_location_device(hass):
    """A marine-flagged sensor's composed friendly name reflects the marine device."""
    coord = _make_coordinator(
        hass,
        tide_url=(
            "https://www.metservice.com/publicData/webdata/marine/regions/"
            "kapiti-wellington/tides/locations/wellington"
        ),
    )
    desc = next(
        d for d in current_condition_sensor_descriptions_public if d.key == "tides_high"
    )
    assert desc.device == "marine"

    sensor = WeatherSensor(coord, desc)
    assert sensor.has_entity_name is True

    device_name = sensor.device_info["name"]
    entity_name = sensor.entity_description.name
    assert device_name == "Kapiti and Wellington"
    assert entity_name == "Next high tide"

    composed = f"{device_name} {entity_name}"
    assert composed == "Kapiti and Wellington Next high tide"

    old_device_name = MetServiceEntity(coord).device_info["name"]
    assert old_device_name == "Napier"
    assert f"{old_device_name} {entity_name}" == "Napier Next high tide"
    assert composed != f"{old_device_name} {entity_name}"
