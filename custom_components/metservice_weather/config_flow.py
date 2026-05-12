"""Config Flow to configure MetService NZ Integration."""
from __future__ import annotations
import asyncio
import logging
from http import HTTPStatus
import async_timeout
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_LOCATION, CONF_NAME
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    SelectSelector,
    SelectSelectorConfig,
)

from .const import (
    DOMAIN,
    DEFAULT_LOCATION,
    LOCATIONS,
)

CONF_MARINE_REGION = "marine_region"
CONF_TIDE_URL = "tide_url"
CONF_BOATING_URL = "boating_url"
CONF_SURF_URL = "surf_url"
CONF_USE_MOBILE = "use_mobile"
CONF_MOBILE_API_KEY = "mobile_api_key"
CONF_API = "api"

# Legacy keys — kept for backward compatibility when reading old config entries
_LEGACY_TIDE_REGION_URL = "tide_region_url"
_LEGACY_BOATING_REGION = "boating_region"

_SKIP = "skip"

_LOGGER = logging.getLogger(__name__)

_MOBILE_HEADERS = {
    "Accept": "*/*",
    "User-Agent": (
        "MetServiceNZ/2.19.3 (com.metservice.iphoneapp; build:332; "
        "iOS 17.1.1) Alamofire/5.4.3"
    ),
    "Accept-Language": "en-CA;q=1.0",
    "Accept-Encoding": "br;q=1.0, gzip;q=0.9, deflate;q=0.8",
    "Connection": "keep-alive",
}

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
        return self.async_create_entry(title=self.user_info[CONF_NAME], data=self.user_info)

    # ------------------------------------------------------------------ #
    # Entry points                                                         #
    # ------------------------------------------------------------------ #

    async def async_step_user(self, user_input=None):
        """Initial entry point — seed empty user_info and go to setup."""
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
                session = async_create_clientsession(self.hass)
                with async_timeout.timeout(10):
                    response = await session.get(
                        "https://www.metservice.com/publicData/webdata/marine"
                    )
                data = await response.json(content_type=None)
                self.regions = data["layout"]["search"]["searchLocations"][0]["items"]
            except Exception:
                _LOGGER.exception("Failed to fetch marine regions — marine options unavailable")
                self.regions = []

            return self.async_show_form(
                step_id="setup",
                data_schema=self._build_setup_schema(),
            )

        errors = {}
        use_mobile = user_input.get(CONF_USE_MOBILE, False)
        api_key = user_input.get(CONF_MOBILE_API_KEY, "").strip()

        if use_mobile:
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
                    if response.status != HTTPStatus.OK:
                        errors[CONF_MOBILE_API_KEY] = "invalid_api_key"
                except Exception:
                    errors["base"] = "cannot_connect"

        if errors:
            return self.async_show_form(
                step_id="setup",
                data_schema=self._build_setup_schema(user_input),
                errors=errors,
            )

        # Persist core settings.
        self.user_info[CONF_LOCATION] = user_input[CONF_LOCATION]
        self.user_info[CONF_NAME] = user_input[CONF_NAME]
        self.user_info[CONF_API] = "mobile" if use_mobile else "public"
        if use_mobile:
            self.user_info[CONF_MOBILE_API_KEY] = api_key
        else:
            self.user_info.pop(CONF_MOBILE_API_KEY, None)

        # Set unique ID on first-time setup only.
        if not self._is_reconfiguring:
            uid = (
                f"{DOMAIN}-{user_input[CONF_NAME]}"
                if use_mobile
                else f"{DOMAIN}-{user_input[CONF_LOCATION]}"
            )
            await self.async_set_unique_id(uid)
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
                    self.user_info.get(_LEGACY_BOATING_REGION, "")
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
                vol.Optional(
                    CONF_USE_MOBILE,
                    default=values.get(CONF_API, "public") == "mobile",
                ): BooleanSelector(),
                vol.Optional(
                    CONF_MOBILE_API_KEY,
                    default=values.get(CONF_MOBILE_API_KEY, values.get("api_key", "")),
                ): str,
            }
        )

    # ------------------------------------------------------------------ #
    # Step 2 of 2: locations (shown only when a marine region is chosen)   #
    # ------------------------------------------------------------------ #

    async def async_step_locations(self, user_input=None):
        """Fetch and display tide, boating, and surf location selectors."""
        marine_region = self.user_info.get(CONF_MARINE_REGION, "")

        if user_input is None:
            session = async_create_clientsession(self.hass)

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
            url = self._resolve_url(tide_label, self._tide_map, self._tide_locations,
                                    marine_region, "tides")
            if not url:
                errors[CONF_TIDE_URL] = "tide_location_not_found"
            else:
                self.user_info[CONF_TIDE_URL] = f"{_BASE_URL}/{url.lstrip('/')}"

        # Boating
        boating_label = user_input.get(CONF_BOATING_URL, _SKIP)
        if boating_label == _SKIP:
            self.user_info[CONF_BOATING_URL] = ""
        elif self._boating_map:
            url = self._resolve_url(boating_label, self._boating_map, self._boating_locations,
                                    marine_region, "boating")
            if not url:
                errors[CONF_BOATING_URL] = "boating_location_not_found"
            else:
                self.user_info[CONF_BOATING_URL] = f"{_BASE_URL}/{url.lstrip('/')}"

        # Surf
        surf_label = user_input.get(CONF_SURF_URL, _SKIP)
        if surf_label == _SKIP:
            self.user_info[CONF_SURF_URL] = ""
        elif self._surf_map:
            url = self._resolve_url(surf_label, self._surf_map, self._surf_locations,
                                    marine_region, "surf")
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
                {"value": label, "label": label}
                for label in label_map.values()
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
            schema[vol.Required(CONF_TIDE_URL, default=_default(CONF_TIDE_URL, self._tide_map))] = (
                SelectSelector(SelectSelectorConfig(options=_opts(self._tide_map)))
            )
        if self._boating_map:
            schema[vol.Required(CONF_BOATING_URL, default=_default(CONF_BOATING_URL, self._boating_map))] = (
                SelectSelector(SelectSelectorConfig(options=_opts(self._boating_map)))
            )
        if self._surf_map:
            schema[vol.Required(CONF_SURF_URL, default=_default(CONF_SURF_URL, self._surf_map))] = (
                SelectSelector(SelectSelectorConfig(options=_opts(self._surf_map)))
            )
        return schema

    # ------------------------------------------------------------------ #
    # Location fetch helpers                                               #
    # ------------------------------------------------------------------ #

    async def _fetch_tide_locations(self, session, marine_region: str) -> list:
        url = f"{_BASE_URL}/{marine_region}/tides"
        with async_timeout.timeout(10):
            response = await session.get(url)
        data = await response.json(content_type=None)
        for module in (
            data.get("layout", {})
            .get("primary", {})
            .get("map", {})
            .get("modules", [])
        ):
            if "markers" in module:
                return module["markers"]
        return []

    async def _fetch_boating_locations(self, session, marine_region: str) -> list:
        region_slug = marine_region.split("/")[-1]
        url = f"{_BASE_URL}/{marine_region}/boating"
        with async_timeout.timeout(10):
            response = await session.get(url)
        data = await response.json(content_type=None)
        all_markers = (
            data.get("layout", {}).get("primary", {}).get("map", {}).get("markers", [])
        )
        prefix = f"/marine/regions/{region_slug}/boating/locations/"
        resolved = [m for m in all_markers if self._marker_url(m).startswith(prefix)]
        return resolved if resolved else [
            m for m in all_markers
            if isinstance(m.get("label"), dict) and m["label"].get("text")
        ]

    async def _fetch_surf_locations(self, session, marine_region: str) -> list:
        region_slug = marine_region.split("/")[-1]
        url = f"{_BASE_URL}/{marine_region}/surf"
        with async_timeout.timeout(10):
            response = await session.get(url)
        data = await response.json(content_type=None)
        all_markers = (
            data.get("layout", {}).get("primary", {}).get("map", {}).get("markers", [])
        )
        prefix = f"/marine/regions/{region_slug}/surf/locations/"
        resolved = [m for m in all_markers if self._marker_url(m).startswith(prefix)]
        return resolved if resolved else [
            m for m in all_markers
            if isinstance(m.get("label"), dict) and m["label"].get("text")
        ]

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
