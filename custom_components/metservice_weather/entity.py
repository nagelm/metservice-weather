"""Base entity for MetService weather integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import WeatherUpdateCoordinator

# MetService marine region slug -> official display label, captured from
# https://www.metservice.com/publicData/webdata/marine's
# layout.search.searchLocations[0].items[*].heading (checked 2026-07-17).
# These editorial names frequently don't match a mechanical hyphen -> title
# case of the slug (e.g. "east-auckland" -> "Auckland East Coast",
# "christchurch" -> "Canterbury", "west-coast-north" -> "Buller and
# Westland"), so an exact lookup table is used for MetService's current,
# finite set of marine regions. A slug MetService adds in future falls back
# to a generic derivation in _marine_device_name below.
_MARINE_REGION_NAMES: dict[str, str] = {
    "northland": "Northland",
    "great-barrier": "Great Barrier",
    "piha": "Piha",
    "coromandel": "Coromandel",
    "east-auckland": "Auckland East Coast",
    "west-auckland": "Auckland West Coast",
    "raglan": "Raglan",
    "bay-of-plenty": "Bay of Plenty",
    "rotorua-taupo": "Rotorua and Taupo",
    "gisborne-mahia": "Gisborne Mahia",
    "taranaki": "Taranaki",
    "whanganui-manawatu": "Manawatu-Whanganui",
    "hawke-bay-wairarapa": "Hawke Bay and Wairarapa",
    "kapiti-wellington": "Kapiti and Wellington",
    "nelson": "Nelson",
    "west-coast-north": "Buller and Westland",
    "kaikoura": "Kaikoura",
    "christchurch": "Canterbury",
    "west-coast-south": "Fiordland",
    "dunedin": "Otago",
    "southland": "Southland",
    "chatham-islands": "Chatham Islands",
}


def _marine_device_name(region_slug: str, location_name: str) -> str:
    """Derive the marine device's display name.

    ``region_slug`` is the coordinator's parsed marine region slug (e.g.
    "kapiti-wellington", from ``WeatherUpdateCoordinator.marine_region_slug``).
    A known slug maps to MetService's own region label, e.g.
    "kapiti-wellington" -> "Kapiti and Wellington" (verbatim MetService label,
    per user decision - sensor names already say tide/surf/boating). Unrecognised
    slug (a marine region MetService adds after this table was captured)
    falls back to a generic hyphen/underscore -> title-case derivation.
    A missing/empty slug falls back to f"{location_name} Marine".
    """
    if not region_slug:
        return f"{location_name} Marine"
    label = _MARINE_REGION_NAMES.get(region_slug)
    if label is None:
        words = region_slug.replace("-", " ").replace("_", " ").split()
        label = " ".join(word.capitalize() for word in words) if words else None
    return label if label else f"{location_name} Marine"


class MetServiceEntity(CoordinatorEntity[WeatherUpdateCoordinator]):
    """Base class providing shared DeviceInfo for all MetService entities."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: WeatherUpdateCoordinator, device: str = "location"
    ) -> None:
        """Attach the appropriate MetService device info to the entity.

        ``device`` selects which device registry entry this entity belongs
        under: "location" (default) is the town/rural page device that
        every entity used before marine support existed; "marine" is a
        separate device describing the selected marine region (tides,
        boating, surf — these describe the region, not the town) and is
        linked under the location device via via_device.
        """
        super().__init__(coordinator)
        if device == "marine":
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, f"{coordinator.location}_marine")},
                name=_marine_device_name(
                    coordinator.marine_region_slug, coordinator.location_name
                ),
                manufacturer=MANUFACTURER,
                model="MetService Public API",
                configuration_url="https://www.metservice.com",
                via_device=(DOMAIN, coordinator.location),
            )
        else:
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, coordinator.location)},
                name=coordinator.location_name,
                manufacturer=MANUFACTURER,
                model="MetService Public API",
                configuration_url="https://www.metservice.com",
            )
