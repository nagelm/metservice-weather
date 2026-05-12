"""Config Flow to configure MetService NZ Integration."""
from __future__ import annotations
import asyncio
import logging
from http import HTTPStatus
import async_timeout
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_LOCATION, CONF_NAME, CONF_API_KEY
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

CONF_TIDE_REGION_URL = "tide_region_url"
CONF_TIDE_REGION = "tide_region"
CONF_TIDE_URL = "tide_url"
CONF_BOATING_REGION_URL = "boating_region_url"
CONF_BOATING_URL = "boating_url"
CONF_USE_MOBILE = "use_mobile"
CONF_API = "api"

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
        """Single page: location, name, marine regions, optional mobile API."""
        if user_input is None:
            # Fetch marine regions for the region selectors.  If the fetch
            # fails we still show the form — the dropdowns will just have
            # "None — skip" as their only option.
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
        api_key = user_input.get(CONF_API_KEY, "").strip()

        # Validate mobile API key when mobile is selected.
        if use_mobile:
            if not api_key:
                errors[CONF_API_KEY] = "api_key_required"
            else:
                try:
                    session = async_create_clientsession(self.hass)
                    with async_timeout.timeout(10):
                        response = await session.get(
                            "https://api.metservice.com/mobile/nz/weatherData/-43.123/172.123",
                            headers={**_MOBILE_HEADERS, "apiKey": api_key},
                        )
                    if response.status != HTTPStatus.OK:
                        errors[CONF_API_KEY] = "invalid_api_key"
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
            self.user_info[CONF_API_KEY] = api_key
        else:
            self.user_info.pop(CONF_API_KEY, None)

        # Resolve marine region selections.
        tide_label = user_input.get(CONF_TIDE_REGION, _SKIP)
        boating_label = user_input.get(CONF_BOATING_REGION_URL, _SKIP)

        if tide_label == _SKIP:
            self.user_info[CONF_TIDE_URL] = ""
            self.user_info.pop(CONF_TIDE_REGION_URL, None)
        else:
            region = next(
                (r for r in self.regions if r["heading"]["label"] == tide_label), None
            )
            self.user_info[CONF_TIDE_REGION_URL] = (
                region["heading"]["url"].lstrip("/") if region else None
            )

        if boating_label == _SKIP:
            self.user_info[CONF_BOATING_URL] = ""
            self.user_info.pop(CONF_BOATING_REGION_URL, None)
        else:
            region = next(
                (r for r in self.regions if r["heading"]["label"] == boating_label), None
            )
            self.user_info[CONF_BOATING_REGION_URL] = (
                region["heading"]["url"].lstrip("/") if region else None
            )

        # Set unique ID on first-time setup only.
        if not self._is_reconfiguring:
            uid = (
                f"{DOMAIN}-{user_input[CONF_NAME]}"
                if use_mobile
                else f"{DOMAIN}-{user_input[CONF_LOCATION]}"
            )
            await self.async_set_unique_id(uid)
            self._abort_if_unique_id_configured()

        # If either marine feature was selected, fetch their location lists.
        if tide_label != _SKIP or boating_label != _SKIP:
            return await self.async_step_locations()

        return self._finish_flow()

    def _build_setup_schema(self, submitted: dict | None = None) -> vol.Schema:
        """Build the setup form schema.

        ``submitted`` is passed on error re-display so the previously entered
        values are preserved as defaults rather than reverting to user_info.
        """
        values = submitted if submitted is not None else self.user_info

        # Derive the currently-selected region labels from stored URLs so the
        # selectors are pre-filled when reconfiguring.
        tide_default = _SKIP
        boating_default = _SKIP
        if submitted is None:
            current_tide_url = self.user_info.get(CONF_TIDE_REGION_URL, "")
            current_boating_url = self.user_info.get(CONF_BOATING_REGION_URL, "")
            for r in self.regions:
                url = r["heading"]["url"].lstrip("/")
                label = r["heading"]["label"]
                if url == current_tide_url:
                    tide_default = label
                if url == current_boating_url:
                    boating_default = label
        else:
            tide_default = submitted.get(CONF_TIDE_REGION, _SKIP)
            boating_default = submitted.get(CONF_BOATING_REGION_URL, _SKIP)

        region_opts = [{"value": _SKIP, "label": "None — skip"}] + [
            {"value": r["heading"]["label"], "label": r["heading"]["label"]}
            for r in self.regions
        ]

        return vol.Schema(
            {
                vol.Required(
                    CONF_LOCATION,
                    default=values.get(CONF_LOCATION, DEFAULT_LOCATION),
                ): SelectSelector(SelectSelectorConfig(options=LOCATIONS)),
                vol.Required(
                    CONF_NAME,
                    default=values.get(CONF_NAME, self.hass.config.location_name),
                ): str,
                vol.Required(
                    CONF_TIDE_REGION, default=tide_default
                ): SelectSelector(SelectSelectorConfig(options=region_opts)),
                vol.Required(
                    CONF_BOATING_REGION_URL, default=boating_default
                ): SelectSelector(SelectSelectorConfig(options=region_opts)),
                vol.Optional(
                    CONF_USE_MOBILE,
                    default=values.get(CONF_API, "public") == "mobile",
                ): BooleanSelector(),
                vol.Optional(
                    CONF_API_KEY,
                    default=values.get(CONF_API_KEY, ""),
                ): str,
            }
        )

    # ------------------------------------------------------------------ #
    # Step 2 of 2: locations (optional)                                    #
    # ------------------------------------------------------------------ #

    async def async_step_locations(self, user_input=None):
        """Fetch and display tide and/or boating location selectors."""
        if user_input is None:
            tide_region = self.user_info.get(CONF_TIDE_REGION_URL)
            boating_region = self.user_info.get(CONF_BOATING_REGION_URL)

            session = async_create_clientsession(self.hass)

            # Fetch the two location lists in parallel.
            fetch_tasks = []
            fetch_keys = []
            if tide_region:
                fetch_tasks.append(self._fetch_tide_locations(session, tide_region))
                fetch_keys.append("tide")
            if boating_region:
                fetch_tasks.append(self._fetch_boating_locations(session, boating_region))
                fetch_keys.append("boating")

            results = dict(
                zip(
                    fetch_keys,
                    await asyncio.gather(*fetch_tasks, return_exceptions=True),
                )
            )

            raw_tide = results.get("tide", [])
            raw_boating = results.get("boating", [])

            if isinstance(raw_tide, Exception):
                _LOGGER.error("Failed to fetch tide locations: %s", raw_tide)
                raw_tide = []
            if isinstance(raw_boating, Exception):
                _LOGGER.error("Failed to fetch boating locations: %s", raw_boating)
                raw_boating = []

            # If a fetch failed, clear that feature so the coordinator does
            # not try to use an invalid URL.
            if tide_region and not raw_tide:
                _LOGGER.warning("No tide locations returned — skipping tides")
                self.user_info[CONF_TIDE_URL] = ""
                self.user_info.pop(CONF_TIDE_REGION_URL, None)
            if boating_region and not raw_boating:
                _LOGGER.warning("No boating locations returned — skipping boating")
                self.user_info[CONF_BOATING_URL] = ""
                self.user_info.pop(CONF_BOATING_REGION_URL, None)

            self._tide_locations = raw_tide
            self._boating_locations = raw_boating
            self._tide_map = {
                str(i): m["label"]["text"]
                for i, m in enumerate(raw_tide)
                if isinstance(m.get("label"), dict) and m["label"].get("text")
            }
            self._boating_map = {
                str(i): m["label"]["text"]
                for i, m in enumerate(raw_boating)
                if isinstance(m.get("label"), dict) and m["label"].get("text")
            }

            schema = self._build_locations_schema()
            if not schema:
                # Both fetches failed or both were already skipped.
                return self._finish_flow()

            return self.async_show_form(
                step_id="locations", data_schema=vol.Schema(schema)
            )

        errors = {}

        if self._tide_map:
            url = self._resolve_tide_url(user_input[CONF_TIDE_URL])
            if not url:
                errors[CONF_TIDE_URL] = "tide_location_not_found"
            else:
                self.user_info[CONF_TIDE_URL] = (
                    f"https://www.metservice.com/publicData/webdata/{url.lstrip('/')}"
                )

        if self._boating_map:
            url = self._resolve_boating_url(user_input[CONF_BOATING_URL])
            if not url:
                errors[CONF_BOATING_URL] = "boating_location_not_found"
            else:
                self.user_info[CONF_BOATING_URL] = (
                    f"https://www.metservice.com/publicData/webdata/{url.lstrip('/')}"
                )

        if errors:
            return self.async_show_form(
                step_id="locations",
                data_schema=vol.Schema(self._build_locations_schema()),
                errors=errors,
            )

        return self._finish_flow()

    def _build_locations_schema(self) -> dict:
        schema = {}
        if self._tide_map:
            schema[vol.Required(CONF_TIDE_URL)] = SelectSelector(
                SelectSelectorConfig(
                    options=[
                        {"value": label, "label": label}
                        for label in self._tide_map.values()
                    ]
                )
            )
        if self._boating_map:
            schema[vol.Required(CONF_BOATING_URL)] = SelectSelector(
                SelectSelectorConfig(
                    options=[
                        {"value": label, "label": label}
                        for label in self._boating_map.values()
                    ]
                )
            )
        return schema

    # ------------------------------------------------------------------ #
    # Location fetch helpers                                               #
    # ------------------------------------------------------------------ #

    async def _fetch_tide_locations(self, session, region: str) -> list:
        url = f"https://www.metservice.com/publicData/webdata/{region}/tides"
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

    async def _fetch_boating_locations(self, session, region: str) -> list:
        region_slug = region.split("/")[-1]
        url = f"https://www.metservice.com/publicData/webdata/{region}/boating"
        with async_timeout.timeout(10):
            response = await session.get(url)
        data = await response.json(content_type=None)
        all_markers = (
            data.get("layout", {}).get("primary", {}).get("map", {}).get("markers", [])
        )
        prefix = f"/marine/regions/{region_slug}/boating/locations/"
        resolved = [
            m for m in all_markers if self._marker_url(m).startswith(prefix)
        ]
        return resolved if resolved else [
            m for m in all_markers
            if isinstance(m.get("label"), dict) and m["label"].get("text")
        ]

    # ------------------------------------------------------------------ #
    # URL resolution helpers                                               #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _marker_url(marker: dict) -> str:
        """Extract URL from a map marker's ``action.modules[0].link.url``."""
        try:
            return marker["action"]["modules"][0]["link"]["url"]
        except (KeyError, IndexError, TypeError):
            return ""

    def _resolve_tide_url(self, label: str) -> str | None:
        """Return the tides page path for the selected label."""
        for idx, loc_label in self._tide_map.items():
            if loc_label != label:
                continue
            marker = self._tide_locations[int(idx)]
            url = self._marker_url(marker)
            if url:
                return url
            action = marker.get("action")
            if isinstance(action, str) and action.startswith("/"):
                return action
            region = self.user_info.get(CONF_TIDE_REGION_URL, "")
            slug = label.lower().replace(" ", "-")
            fallback = f"/{region}/tides/locations/{slug}"
            _LOGGER.warning("Using constructed tide URL fallback: %s", fallback)
            return fallback
        return None

    def _resolve_boating_url(self, label: str) -> str | None:
        """Return the boating page path for the selected label."""
        for idx, loc_label in self._boating_map.items():
            if loc_label != label:
                continue
            marker = self._boating_locations[int(idx)]
            url = self._marker_url(marker)
            if url:
                return url
            region = self.user_info.get(CONF_BOATING_REGION_URL, "")
            slug = label.lower().replace(" ", "-")
            return f"/{region}/boating/locations/{slug}"
        return None
