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
    assert (
        _marine_device_name("kapiti-wellington", "Napier")
        == "Kapiti and Wellington Marine"
    )


def test_marine_device_name_known_slug_not_derivable_mechanically():
    """Some real labels don't come from a mechanical hyphen->title-case.

    That's why a lookup table (not string munging) is used for MetService's
    known regions.
    """
    assert (
        _marine_device_name("east-auckland", "Napier") == "Auckland East Coast Marine"
    )
    assert _marine_device_name("christchurch", "Napier") == "Canterbury Marine"
    assert (
        _marine_device_name("west-coast-north", "Napier")
        == "Buller and Westland Marine"
    )


def test_marine_device_name_unknown_slug_generic_derivation():
    """An unrecognised slug falls back to a generic derivation.

    A future MetService region not in the lookup table gets a hyphen/
    underscore -> title-case derivation instead.
    """
    assert _marine_device_name("future-region", "Napier") == "Future Region Marine"
    assert _marine_device_name("solo", "Napier") == "Solo Marine"


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
    assert info["name"] == "Kapiti and Wellington Marine"


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
