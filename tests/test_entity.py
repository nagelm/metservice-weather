"""Tests for MetServiceEntity's device grouping (location device vs marine device)."""

from __future__ import annotations

from custom_components.metservice_weather.const import DOMAIN
from custom_components.metservice_weather.coordinator import (
    WeatherUpdateCoordinator,
    WeatherUpdateCoordinatorConfig,
)
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
        unit_system_api="m",
        unit_system="metric",
        location="/towns-cities/regions/hawkes-bay/locations/napier",
        location_name="Napier",
        tide_url=tide_url,
        boating_url=boating_url,
        surf_url=surf_url,
    )
    return WeatherUpdateCoordinator(hass, config)


# ---------------------------------------------------------------------------
# Test: _marine_device_name derivation
# ---------------------------------------------------------------------------


def test_marine_device_name_known_slug_matches_metservice_label():
    """A known MetService region slug maps to its real editorial label."""
    assert _marine_device_name("kapiti-wellington", "Napier") == "Kapiti and Wellington"


def test_marine_device_name_known_slug_not_derivable_mechanically():
    """Some real labels don't come from a mechanical hyphen->title-case.

    That's why a lookup table (not string munging) is used for MetService's
    known regions.
    """
    assert _marine_device_name("east-auckland", "Napier") == "Auckland East Coast"
    assert _marine_device_name("christchurch", "Napier") == "Canterbury"
    assert _marine_device_name("west-coast-north", "Napier") == "Buller and Westland"


def test_marine_device_name_unknown_slug_generic_derivation():
    """An unrecognised slug falls back to a generic derivation.

    A future MetService region not in the lookup table gets a hyphen/
    underscore -> title-case derivation instead.
    """
    assert _marine_device_name("future-region", "Napier") == "Future Region"
    assert _marine_device_name("solo", "Napier") == "Solo"


def test_marine_device_name_empty_slug_falls_back_to_location_name():
    """An empty/missing slug falls back to f'{location_name} Marine'."""
    assert _marine_device_name("", "Napier") == "Napier Marine"


# ---------------------------------------------------------------------------
# Test: MetServiceEntity DeviceInfo branching
# ---------------------------------------------------------------------------


async def test_location_device_is_the_default(hass):
    """The default device="location" builds the original town/rural device.

    Unchanged from before marine devices existed.
    """
    coord = _make_coordinator(hass)
    ent = MetServiceEntity(coord)
    info = ent.device_info
    assert info["identifiers"] == {(DOMAIN, coord.location)}
    assert info["name"] == "Napier"
    assert info.get("via_device") is None


async def test_marine_device_has_distinct_identifier_and_via_device(hass):
    """device="marine" builds a separate, linked device.

    Linked under the location device via via_device, with a name that
    reflects the marine region.
    """
    coord = _make_coordinator(
        hass,
        tide_url=(
            "https://www.metservice.com/publicData/webdata/marine/regions/"
            "kapiti-wellington/tides/locations/wellington"
        ),
    )
    ent = MetServiceEntity(coord, device="marine")
    info = ent.device_info
    assert info["identifiers"] == {(DOMAIN, f"{coord.location}_marine")}
    assert info["identifiers"] != {(DOMAIN, coord.location)}
    assert info["via_device"] == (DOMAIN, coord.location)
    assert info["name"] == "Kapiti and Wellington"


async def test_marine_device_falls_back_to_location_name_when_no_marine_url(hass):
    """No tide/boating/surf URL configured falls back to a location-based name.

    Falls back to f'{location_name} Marine' rather than an empty/broken
    label.
    """
    coord = _make_coordinator(hass)
    ent = MetServiceEntity(coord, device="marine")
    assert ent.device_info["name"] == "Napier Marine"


async def test_marine_and_location_devices_share_manufacturer_and_model(hass):
    """Both devices use the same manufacturer/model/configuration_url style.

    Matches the pre-existing location device's style.
    """
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


# ---------------------------------------------------------------------------
# Test: marine device move changes the composed friendly name
# (release_notes.md "Added: marine data gets its own device")
# ---------------------------------------------------------------------------


async def test_marine_sensor_composed_friendly_name_changes_from_location_device(hass):
    """A marine-flagged sensor's composed friendly name reflects the marine device.

    release_notes.md documents that moving tide/boating/surf sensors to
    their own marine device changes the displayed friendly name, e.g.
    "Napier Next High Tide" becomes "Kapiti and Wellington ... Next High
    Tide" — with has_entity_name composition, HA builds the shown name as
    f"{device_name} {entity_name}". This asserts that composition directly
    off device_info["name"] and the entity's own name, and contrasts it
    against what the same entity's composed name would have been under the
    original location device.
    """
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
    assert entity_name == "Next High Tide"

    composed = f"{device_name} {entity_name}"
    assert composed == "Kapiti and Wellington Next High Tide"

    # Contrast with the old composition under the pre-move location device
    # (the release-notes "Napier Next High Tide" example).
    old_device_name = MetServiceEntity(coord).device_info["name"]
    assert old_device_name == "Napier"
    assert f"{old_device_name} {entity_name}" == "Napier Next High Tide"
    assert composed != f"{old_device_name} {entity_name}"
