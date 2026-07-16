"""Config Flow to configure MetService NZ Integration."""

from __future__ import annotations
import asyncio
import logging
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_LOCATION, CONF_NAME
from homeassistant.data_entry_flow import section
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
)

from .const import (
    DOMAIN,
    DEFAULT_LOCATION,
    LOCATIONS,
    CONF_AUTO_HIDE_SEASONAL,
)

CONF_MARINE_REGION = "marine_region"
CONF_TIDE_URL = "tide_url"
CONF_BOATING_URL = "boating_url"
CONF_SURF_URL = "surf_url"
CONF_API = "api"

# Key of the collapsed "Advanced" section on the setup form. The toggle
# nested under it arrives in user_input[SECTION_ADVANCED_OPTIONS], but is
# stored flat in entry.data — see _build_setup_schema and async_step_setup.
SECTION_ADVANCED_OPTIONS = "advanced_options"

# Legacy keys — kept for backward compatibility when reading old config entries
_LEGACY_TIDE_REGION_URL = "tide_region_url"
_LEGACY_BOATING_REGION = "boating_region"

_SKIP = "skip"

_LOGGER = logging.getLogger(__name__)

_BASE_URL = "https://www.metservice.com/publicData/webdata"


class WeatherFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a MetService config flow."""

    VERSION = 1

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    @property
    def _is_reconfiguring(self) -> bool:
        return hasattr(self, "_reconfig_entry")

    def _finish_flow(self):
        """Create a new entry or update the existing one when reconfiguring."""
        if self._is_reconfiguring:
            return self.async_update_reload_and_abort(
                self._reconfig_entry,
                data=self.user_info,
            )
        return self.async_create_entry(
            title=self.user_info[CONF_NAME], data=self.user_info
        )

    # ------------------------------------------------------------------ #
    # Entry points                                                         #
    # ------------------------------------------------------------------ #

    async def async_step_user(self, user_input=None):
        """Handle initial entry — seed empty user_info and go to setup."""
        self.user_info = {}
        return await self.async_step_setup()

    async def async_step_reconfigure(self, user_input=None):
        """Re-entry point — seed user_info from the existing entry."""
        self._reconfig_entry = self._get_reconfigure_entry()
        self.user_info = dict(self._reconfig_entry.data)
        return await self.async_step_setup()

    # ------------------------------------------------------------------ #
    # Step 1 of 2: setup                                                   #
    # ------------------------------------------------------------------ #

    async def async_step_setup(self, user_input=None):
        """Page 1: location, name, one optional marine region, mobile API."""
        if user_input is None:
            try:
                session = async_get_clientsession(self.hass)
                async with asyncio.timeout(10):
                    response = await session.get(
                        "https://www.metservice.com/publicData/webdata/marine"
                    )
                data = await response.json(content_type=None)
                self.regions = data["layout"]["search"]["searchLocations"][0]["items"]
            except Exception:
                _LOGGER.exception(
                    "Failed to fetch marine regions — marine options unavailable"
                )
                self.regions = []

            return self.async_show_form(
                step_id="setup",
                data_schema=self._build_setup_schema(),
            )

        # Persist core settings.
        self.user_info[CONF_LOCATION] = user_input[CONF_LOCATION]
        self.user_info[CONF_NAME] = user_input[CONF_NAME]
        self.user_info[CONF_API] = "public"
        # The toggle is nested under the "Advanced" section in the submitted
        # form data, but entry.data keeps it as a flat key — sensor.py reads
        # it flat and there is no migration.
        advanced_options = user_input.get(SECTION_ADVANCED_OPTIONS, {})
        self.user_info[CONF_AUTO_HIDE_SEASONAL] = advanced_options.get(
            CONF_AUTO_HIDE_SEASONAL, False
        )

        # Set unique ID on first-time setup only.
        if not self._is_reconfiguring:
            await self.async_set_unique_id(f"{DOMAIN}-{user_input[CONF_LOCATION]}")
            self._abort_if_unique_id_configured()

        # Resolve the marine region selection.
        marine_label = user_input.get(CONF_MARINE_REGION, _SKIP)
        if marine_label == _SKIP:
            # No marine region chosen — clear all marine URLs and finish.
            self.user_info[CONF_MARINE_REGION] = ""
            self.user_info[CONF_TIDE_URL] = ""
            self.user_info[CONF_BOATING_URL] = ""
            self.user_info[CONF_SURF_URL] = ""
            # Remove any stale legacy keys.
            self.user_info.pop(_LEGACY_TIDE_REGION_URL, None)
            self.user_info.pop(_LEGACY_BOATING_REGION, None)
            return self._finish_flow()

        region = next(
            (r for r in self.regions if r["heading"]["label"] == marine_label), None
        )
        marine_region_url = region["heading"]["url"].lstrip("/") if region else ""
        self.user_info[CONF_MARINE_REGION] = marine_region_url
        # Remove stale legacy keys so old and new formats don't coexist.
        self.user_info.pop(_LEGACY_TIDE_REGION_URL, None)
        self.user_info.pop(_LEGACY_BOATING_REGION, None)

        return await self.async_step_locations()

    def _build_setup_schema(self, submitted: dict | None = None) -> vol.Schema:
        """Build the setup form schema."""
        values = submitted if submitted is not None else self.user_info

        # Derive the currently-selected marine region label for pre-fill on
        # reconfigure.  Handles both the new single-region key and legacy
        # separate-region keys so old entries open correctly.
        marine_default = _SKIP
        if submitted is None:
            current_region = self.user_info.get(CONF_MARINE_REGION, "")
            if not current_region:
                # Fall back to either legacy key so old entries pre-fill.
                current_region = self.user_info.get(
                    _LEGACY_TIDE_REGION_URL,
                    self.user_info.get(_LEGACY_BOATING_REGION, ""),
                )
            for r in self.regions:
                if r["heading"]["url"].lstrip("/") == current_region:
                    marine_default = r["heading"]["label"]
                    break
        else:
            marine_default = submitted.get(CONF_MARINE_REGION, _SKIP)

        region_opts = [{"value": _SKIP, "label": "None — skip marine data"}] + [
            {"value": r["heading"]["label"], "label": r["heading"]["label"]}
            for r in self.regions
        ]

        return vol.Schema(
            {
                vol.Required(
                    CONF_NAME,
                    default=values.get(CONF_NAME, self.hass.config.location_name),
                ): str,
                vol.Required(
                    CONF_LOCATION,
                    default=values.get(CONF_LOCATION, DEFAULT_LOCATION),
                ): SelectSelector(SelectSelectorConfig(options=LOCATIONS)),
                vol.Required(
                    CONF_MARINE_REGION, default=marine_default
                ): SelectSelector(SelectSelectorConfig(options=region_opts)),
                vol.Required(SECTION_ADVANCED_OPTIONS): section(
                    vol.Schema(
                        {
                            vol.Optional(
                                CONF_AUTO_HIDE_SEASONAL,
                                default=values.get(CONF_AUTO_HIDE_SEASONAL, False),
                            ): bool,
                        }
                    ),
                    # Collapsed by default on fresh setup (no stored value —
                    # values.get(...) is False, so `not False` is True). On
                    # reconfigure, open the section when the toggle is
                    # currently enabled so the user sees their non-default
                    # choice.
                    {"collapsed": not values.get(CONF_AUTO_HIDE_SEASONAL, False)},
                ),
            }
        )

    # ------------------------------------------------------------------ #
    # Step 2 of 2: locations (shown only when a marine region is chosen)   #
    # ------------------------------------------------------------------ #

    async def async_step_locations(self, user_input=None):
        """Fetch and display tide, boating, and surf location selectors."""
        marine_region = self.user_info.get(CONF_MARINE_REGION, "")

        if user_input is None:
            session = async_get_clientsession(self.hass)

            results = dict(
                zip(
                    ["tide", "boating", "surf"],
                    await asyncio.gather(
                        self._fetch_tide_locations(session, marine_region),
                        self._fetch_boating_locations(session, marine_region),
                        self._fetch_surf_locations(session, marine_region),
                        return_exceptions=True,
                    ),
                )
            )

            for key in ("tide", "boating", "surf"):
                if isinstance(results[key], Exception):
                    _LOGGER.error("Failed to fetch %s locations: %s", key, results[key])
                    results[key] = []

            self._tide_locations = results["tide"]
            self._boating_locations = results["boating"]
            self._surf_locations = results["surf"]

            self._tide_map = self._build_label_map(self._tide_locations)
            self._boating_map = self._build_label_map(self._boating_locations)
            self._surf_map = self._build_label_map(self._surf_locations)

            return self.async_show_form(
                step_id="locations",
                data_schema=vol.Schema(self._build_locations_schema()),
            )

        errors = {}

        # Tide
        tide_label = user_input.get(CONF_TIDE_URL, _SKIP)
        if tide_label == _SKIP:
            self.user_info[CONF_TIDE_URL] = ""
        elif self._tide_map:
            url = self._resolve_url(
                tide_label, self._tide_map, self._tide_locations, marine_region, "tides"
            )
            if not url:
                errors[CONF_TIDE_URL] = "tide_location_not_found"
            else:
                self.user_info[CONF_TIDE_URL] = f"{_BASE_URL}/{url.lstrip('/')}"

        # Boating
        boating_label = user_input.get(CONF_BOATING_URL, _SKIP)
        if boating_label == _SKIP:
            self.user_info[CONF_BOATING_URL] = ""
        elif self._boating_map:
            url = self._resolve_url(
                boating_label,
                self._boating_map,
                self._boating_locations,
                marine_region,
                "boating",
            )
            if not url:
                errors[CONF_BOATING_URL] = "boating_location_not_found"
            else:
                self.user_info[CONF_BOATING_URL] = f"{_BASE_URL}/{url.lstrip('/')}"

        # Surf
        surf_label = user_input.get(CONF_SURF_URL, _SKIP)
        if surf_label == _SKIP:
            self.user_info[CONF_SURF_URL] = ""
        elif self._surf_map:
            url = self._resolve_url(
                surf_label, self._surf_map, self._surf_locations, marine_region, "surf"
            )
            if not url:
                errors[CONF_SURF_URL] = "surf_location_not_found"
            else:
                self.user_info[CONF_SURF_URL] = f"{_BASE_URL}/{url.lstrip('/')}"

        if errors:
            return self.async_show_form(
                step_id="locations",
                data_schema=vol.Schema(self._build_locations_schema()),
                errors=errors,
            )

        return self._finish_flow()

    def _build_label_map(self, markers: list) -> dict:
        """Build an index→label map from a markers list."""
        return {
            str(i): m["label"]["text"]
            for i, m in enumerate(markers)
            if isinstance(m.get("label"), dict) and m["label"].get("text")
        }

    def _build_locations_schema(self) -> dict:
        """Build the locations form schema with skip options for all three."""
        skip_opt = [{"value": _SKIP, "label": "None — skip"}]

        def _opts(label_map: dict) -> list:
            return skip_opt + [
                {"value": label, "label": label} for label in label_map.values()
            ]

        def _default(conf_key: str, label_map: dict) -> str:
            """Pre-fill from the existing config entry URL, if present."""
            stored_url = self.user_info.get(conf_key, "")
            if not stored_url:
                return _SKIP
            for label in label_map.values():
                if label.lower().replace(" ", "-") in stored_url.lower():
                    return label
            return _SKIP

        schema = {}
        if self._tide_map:
            schema[
                vol.Required(
                    CONF_TIDE_URL, default=_default(CONF_TIDE_URL, self._tide_map)
                )
            ] = SelectSelector(SelectSelectorConfig(options=_opts(self._tide_map)))
        if self._boating_map:
            schema[
                vol.Required(
                    CONF_BOATING_URL,
                    default=_default(CONF_BOATING_URL, self._boating_map),
                )
            ] = SelectSelector(SelectSelectorConfig(options=_opts(self._boating_map)))
        if self._surf_map:
            schema[
                vol.Required(
                    CONF_SURF_URL, default=_default(CONF_SURF_URL, self._surf_map)
                )
            ] = SelectSelector(SelectSelectorConfig(options=_opts(self._surf_map)))
        return schema

    # ------------------------------------------------------------------ #
    # Location fetch helpers                                               #
    # ------------------------------------------------------------------ #

    async def _fetch_tide_locations(self, session, marine_region: str) -> list:
        url = f"{_BASE_URL}/{marine_region}/tides"
        async with asyncio.timeout(10):
            response = await session.get(url)
        data = await response.json(content_type=None)
        for module in (
            data.get("layout", {}).get("primary", {}).get("map", {}).get("modules", [])
        ):
            if "markers" in module:
                return module["markers"]
        return []

    async def _fetch_boating_locations(self, session, marine_region: str) -> list:
        region_slug = marine_region.split("/")[-1]
        url = f"{_BASE_URL}/{marine_region}/boating"
        async with asyncio.timeout(10):
            response = await session.get(url)
        data = await response.json(content_type=None)
        all_markers = (
            data.get("layout", {}).get("primary", {}).get("map", {}).get("markers", [])
        )
        prefix = f"/marine/regions/{region_slug}/boating/locations/"
        resolved = [m for m in all_markers if self._marker_url(m).startswith(prefix)]
        return (
            resolved
            if resolved
            else [
                m
                for m in all_markers
                if isinstance(m.get("label"), dict) and m["label"].get("text")
            ]
        )

    async def _fetch_surf_locations(self, session, marine_region: str) -> list:
        region_slug = marine_region.split("/")[-1]
        url = f"{_BASE_URL}/{marine_region}/surf"
        async with asyncio.timeout(10):
            response = await session.get(url)
        data = await response.json(content_type=None)
        all_markers = (
            data.get("layout", {}).get("primary", {}).get("map", {}).get("markers", [])
        )
        prefix = f"/marine/regions/{region_slug}/surf/locations/"
        resolved = [m for m in all_markers if self._marker_url(m).startswith(prefix)]
        return (
            resolved
            if resolved
            else [
                m
                for m in all_markers
                if isinstance(m.get("label"), dict) and m["label"].get("text")
            ]
        )

    # ------------------------------------------------------------------ #
    # URL resolution helpers                                               #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _marker_url(marker: dict) -> str:
        """Extract URL from a map marker's action.modules[0].link.url."""
        try:
            return marker["action"]["modules"][0]["link"]["url"]
        except (KeyError, IndexError, TypeError):
            return ""

    def _resolve_url(
        self,
        label: str,
        label_map: dict,
        locations: list,
        marine_region: str,
        service: str,
    ) -> str | None:
        """Return the location page path for the selected label."""
        for idx, loc_label in label_map.items():
            if loc_label != label:
                continue
            marker = locations[int(idx)]
            url = self._marker_url(marker)
            if url:
                return url
            action = marker.get("action")
            if isinstance(action, str) and action.startswith("/"):
                return action
            slug = label.lower().replace(" ", "-")
            fallback = f"/{marine_region}/{service}/locations/{slug}"
            _LOGGER.warning("Using constructed %s URL fallback: %s", service, fallback)
            return fallback
        return None
