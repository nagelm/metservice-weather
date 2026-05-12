"""Config Flow to configure MetService NZ Integration."""
from __future__ import annotations
import logging
from http import HTTPStatus
import async_timeout
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.const import CONF_LOCATION, CONF_NAME, CONF_API_KEY
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
)

from .const import (
    DOMAIN,
    DEFAULT_LOCATION,
    LOCATIONS,
)

CONF_REGION = "tide_region"
CONF_TIDE_REGION_URL = "tide_region_url"
CONF_TIDE_URL = "tide_url"
CONF_BOATING_REGION_URL = "boating_region_url"
CONF_BOATING_URL = "boating_url"

# Sentinel value used in region selectors so the user can skip optional steps
# without needing a separate boolean toggle.
_SKIP = "skip"

_LOGGER = logging.getLogger(__name__)

CONF_API = "api"


class WeatherFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a MetService config flow."""

    VERSION = 1

    # ------------------------------------------------------------------ #
    # Shared helpers                                                       #
    # ------------------------------------------------------------------ #

    @property
    def _is_reconfiguring(self) -> bool:
        """Return True when we are updating an existing entry."""
        return hasattr(self, "_reconfig_entry")

    def _finish_flow(self):
        """Create a new entry, or update the existing one when reconfiguring."""
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
        """Let the user choose between the mobile and public APIs."""
        if user_input is None:
            return await self._show_user_form()

        self.user_info = user_input
        if user_input[CONF_API] == "mobile":
            return await self.async_step_mobile()
        return await self.async_step_public()

    async def async_step_reconfigure(self, user_input=None):
        """Re-run the config flow so the user can update settings in place."""
        self._reconfig_entry = self._get_reconfigure_entry()
        # Seed user_info from the existing entry — every subsequent step
        # reads from and writes into this dict, so existing values are
        # preserved for any step the user does not change.
        self.user_info = dict(self._reconfig_entry.data)
        if self.user_info.get(CONF_API) == "mobile":
            return await self.async_step_mobile()
        return await self.async_step_public()

    # ------------------------------------------------------------------ #
    # Step: user (API type)                                                #
    # ------------------------------------------------------------------ #

    async def _show_user_form(self, errors=None):
        """Show the API-type selection form."""
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API, default="public"): SelectSelector(
                        SelectSelectorConfig(options=["public", "mobile"])
                    ),
                }
            ),
            errors=errors or {},
        )

    # ------------------------------------------------------------------ #
    # Step: public                                                         #
    # ------------------------------------------------------------------ #

    async def async_step_public(self, user_input=None):
        """Handle the public-API location/name step."""
        if user_input is None:
            return await self._show_public_form()

        errors = {}
        session = async_create_clientsession(self.hass)
        location = user_input[CONF_LOCATION]
        location_name = user_input[CONF_NAME]
        headers = {
            "Accept-Encoding": "gzip",
            "user-agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/111.0.0.0 Safari/537.36"
            ),
        }
        try:
            with async_timeout.timeout(10):
                url = f"https://www.metservice.com/publicData/webdata{location}"
                response = await session.get(url, headers=headers)
            if response.status != HTTPStatus.OK:
                _LOGGER.error(
                    "MetService config responded with HTTP error %s: %s",
                    response.status,
                    response.reason,
                )
                raise Exception
        except Exception:
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown_error"
            return await self._show_public_form(errors=errors)

        await response.json(content_type=None)

        if not self._is_reconfiguring:
            unique_id = str(f"{DOMAIN}-{location}")
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

        self.user_info[CONF_LOCATION] = location
        self.user_info[CONF_NAME] = location_name
        self.user_info[CONF_API] = "public"
        return await self.async_step_tide_region()

    async def _show_public_form(self, errors=None):
        """Show the public-API location/name form, pre-filled from user_info."""
        return self.async_show_form(
            step_id="public",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_LOCATION,
                        default=self.user_info.get(CONF_LOCATION, DEFAULT_LOCATION),
                    ): SelectSelector(SelectSelectorConfig(options=LOCATIONS)),
                    vol.Required(
                        CONF_NAME,
                        default=self.user_info.get(CONF_NAME, self.hass.config.location_name),
                    ): str,
                }
            ),
            errors=errors or {},
        )

    # ------------------------------------------------------------------ #
    # Step: mobile                                                         #
    # ------------------------------------------------------------------ #

    async def async_step_mobile(self, user_input=None):
        """Handle the mobile-API key/name step."""
        if user_input is None:
            return await self._show_mobile_form()

        errors = {}
        session = async_create_clientsession(self.hass)
        api_key = user_input[CONF_API_KEY]
        location_name = user_input[CONF_NAME]
        headers = {
            "Accept": "*/*",
            "User-Agent": (
                "MetServiceNZ/2.19.3 (com.metservice.iphoneapp; build:332; "
                "iOS 17.1.1) Alamofire/5.4.3"
            ),
            "Accept-Language": "en-CA;q=1.0",
            "Accept-Encoding": "br;q=1.0, gzip;q=0.9, deflate;q=0.8",
            "Connection": "keep-alive",
            "apiKey": api_key,
        }
        try:
            with async_timeout.timeout(10):
                url = "https://api.metservice.com/mobile/nz/weatherData/-43.123/172.123"
                response = await session.get(url, headers=headers)
            if response.status != HTTPStatus.OK:
                _LOGGER.error(
                    "MetService config responded with HTTP error %s: %s",
                    response.status,
                    response.reason,
                )
                raise Exception
        except Exception:
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown_error"
            return await self._show_mobile_form(errors=errors)

        await response.json(content_type=None)

        if not self._is_reconfiguring:
            unique_id = str(f"{DOMAIN}-{location_name}")
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

        self.user_info[CONF_API_KEY] = api_key
        self.user_info[CONF_NAME] = location_name
        self.user_info[CONF_API] = "mobile"
        return await self.async_step_tide_region()

    async def _show_mobile_form(self, errors=None):
        """Show the mobile-API key/name form, pre-filled from user_info."""
        return self.async_show_form(
            step_id="mobile",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_API_KEY,
                        default=self.user_info.get(CONF_API_KEY, ""),
                    ): str,
                    vol.Required(
                        CONF_NAME,
                        default=self.user_info.get(CONF_NAME, self.hass.config.location_name),
                    ): str,
                }
            ),
            errors=errors or {},
        )

    # ------------------------------------------------------------------ #
    # Shared schema builders                                               #
    # ------------------------------------------------------------------ #

    @callback
    def _async_generate_select_schema_region(
        self,
        options: list[dict],
        field_name: str,
        skip_label: str,
        default: str = _SKIP,
    ) -> vol.Schema:
        """Build a SelectSelector schema for a marine region list.

        The first option is always the skip sentinel so optional steps can be
        bypassed without a separate boolean toggle.  The ``default`` is set to
        the skip sentinel on first setup and to the currently-configured region
        label when reconfiguring.
        """
        select_opts = [{"value": _SKIP, "label": skip_label}] + [
            {"value": opt["heading"]["label"], "label": opt["heading"]["label"]}
            for opt in options
        ]
        return vol.Schema(
            {
                vol.Required(field_name, default=default): SelectSelector(
                    SelectSelectorConfig(options=select_opts)
                ),
            }
        )

    @callback
    def _async_generate_select_schema_location(
        self, options: list[dict], field_name: str
    ) -> vol.Schema:
        """Build a SelectSelector schema for a list of map markers.

        Each marker's label is a nested object ``{"text": "..."}``, not a plain
        string.  The display name is extracted from ``label.text`` so the
        SelectSelector receives plain strings.
        """
        self.locations_map = {
            str(index): opt["label"]["text"] for index, opt in enumerate(options)
        }
        select_opts = [
            {"value": label, "label": label} for label in self.locations_map.values()
        ]
        return vol.Schema(
            {
                vol.Required(field_name): SelectSelector(
                    SelectSelectorConfig(options=select_opts)
                ),
            }
        )

    # ------------------------------------------------------------------ #
    # URL helpers                                                          #
    # ------------------------------------------------------------------ #

    def get_tide_location_url_from_label(self, label):
        """Return the tides page URL for the selected tide location.

        Three strategies are tried in order:
        1. ``action.modules[0].link.url``  (resolved nested object)
        2. ``action`` as a plain URL string
        3. Slug constructed from the label + region URL (reliable fallback)
        """
        for index, location_label in self.locations_map.items():
            if location_label != label:
                continue
            marker = self.locations[int(index)]
            try:
                return marker["action"]["modules"][0]["link"]["url"]
            except (KeyError, IndexError, TypeError):
                pass
            action = marker.get("action")
            if isinstance(action, str) and action.startswith("/"):
                return action
            region = self.user_info.get(CONF_TIDE_REGION_URL, "")
            slug = label.lower().replace(" ", "-")
            constructed = f"/{region}/tides/locations/{slug}"
            _LOGGER.warning(
                "Could not extract tide URL from marker; using constructed fallback: %s",
                constructed,
            )
            return constructed
        return None

    @staticmethod
    def _get_marker_url(marker: dict, default: str) -> str:
        """Extract URL from a map marker's ``action.modules[0].link.url``."""
        try:
            return marker["action"]["modules"][0]["link"]["url"]
        except (KeyError, IndexError, TypeError):
            return default

    def _get_boating_url_from_label(self, label: str) -> str | None:
        """Return the boating page URL for the selected location."""
        for index, location_label in self.boating_locations_map.items():
            if location_label != label:
                continue
            marker = self.boating_locations[int(index)]
            url = self._get_marker_url(marker, "")
            if url:
                return url
            region = self.user_info.get(CONF_BOATING_REGION_URL, "")
            slug = label.lower().replace(" ", "-")
            return f"/{region}/boating/locations/{slug}"
        return None

    # ------------------------------------------------------------------ #
    # Step: tide_region                                                    #
    # ------------------------------------------------------------------ #

    async def async_step_tide_region(self, user_input=None):
        """Select a tide region, or skip tides entirely."""
        if user_input is None:
            try:
                session = async_create_clientsession(self.hass)
                with async_timeout.timeout(10):
                    response = await session.get(
                        "https://www.metservice.com/publicData/webdata/marine"
                    )
                regions_data = await response.json(content_type=None)
                self.regions = regions_data["layout"]["search"]["searchLocations"][0]["items"]
            except Exception:
                _LOGGER.exception("Failed to fetch marine regions for tides setup")
                return self.async_abort(reason="tides_unavailable")

            # When reconfiguring, pre-select the already-configured region.
            current_url = self.user_info.get(CONF_TIDE_REGION_URL, "")
            default = _SKIP
            if current_url:
                for item in self.regions:
                    if item["heading"]["url"].lstrip("/") == current_url:
                        default = item["heading"]["label"]
                        break

            return self.async_show_form(
                step_id="tide_region",
                data_schema=self._async_generate_select_schema_region(
                    self.regions, CONF_REGION, "None — skip tides", default=default
                ),
            )

        selected_label = user_input[CONF_REGION]
        if selected_label == _SKIP:
            self.user_info[CONF_TIDE_URL] = ""
            self.user_info.pop(CONF_TIDE_REGION_URL, None)
            return await self.async_step_boating_region()

        selected_region = next(
            (item for item in self.regions if item["heading"]["label"] == selected_label),
            None,
        )
        self.user_info[CONF_TIDE_REGION_URL] = (
            selected_region["heading"]["url"].lstrip("/") if selected_region else None
        )
        return await self.async_step_tide_location()

    # ------------------------------------------------------------------ #
    # Step: tide_location                                                  #
    # ------------------------------------------------------------------ #

    async def async_step_tide_location(self, user_input=None):
        """Select a specific tide location within the chosen region."""
        if user_input is None:
            region = self.user_info[CONF_TIDE_REGION_URL]
            url = f"https://www.metservice.com/publicData/webdata/{region}/tides"
            try:
                session = async_create_clientsession(self.hass)
                response = await session.get(url)
                locations_data = await response.json(content_type=None)
                if response.status != HTTPStatus.OK:
                    _LOGGER.error(
                        "Tides location fetch returned HTTP %s for %s", response.status, url
                    )
                    return self.async_abort(reason="tides_unavailable")
                map_modules = (
                    locations_data.get("layout", {})
                    .get("primary", {})
                    .get("map", {})
                    .get("modules", [])
                )
                self.locations = None
                for module in map_modules:
                    if "markers" in module:
                        self.locations = module["markers"]
                        break
                if not self.locations:
                    _LOGGER.error(
                        "Could not find tide location markers in response from %s", url
                    )
                    return self.async_abort(reason="tides_unavailable")
            except Exception:
                _LOGGER.exception("Failed to fetch tide locations from %s", url)
                return self.async_abort(reason="tides_unavailable")

            return self.async_show_form(
                step_id="tide_location",
                data_schema=self._async_generate_select_schema_location(
                    self.locations, CONF_TIDE_URL
                ),
            )

        selected_label = user_input[CONF_TIDE_URL]
        tide_url = self.get_tide_location_url_from_label(selected_label)
        if not tide_url:
            _LOGGER.error(
                "Could not find URL for selected tide location: %s", selected_label
            )
            return self.async_show_form(
                step_id="tide_location",
                data_schema=self._async_generate_select_schema_location(
                    self.locations, CONF_TIDE_URL
                ),
                errors={"base": "tide_location_not_found"},
            )

        tide_url = f"https://www.metservice.com/publicData/webdata/{tide_url.lstrip('/')}"
        self.user_info[CONF_TIDE_URL] = tide_url
        try:
            session = async_create_clientsession(self.hass)
            with async_timeout.timeout(10):
                headers = {
                    "Accept-Encoding": "gzip",
                    "user-agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/111.0.0.0 Safari/537.36"
                    ),
                }
                response = await session.get(tide_url, headers=headers)
            if response.status != HTTPStatus.OK:
                _LOGGER.error(
                    "Tide location validation returned HTTP %s: %s",
                    response.status,
                    response.reason,
                )
                return self.async_show_form(
                    step_id="tide_location",
                    data_schema=self._async_generate_select_schema_location(
                        self.locations, CONF_TIDE_URL
                    ),
                    errors={"base": "cannot_connect"},
                )
        except Exception:
            _LOGGER.exception("Unexpected exception validating tide location URL")
            return self.async_show_form(
                step_id="tide_location",
                data_schema=self._async_generate_select_schema_location(
                    self.locations, CONF_TIDE_URL
                ),
                errors={"base": "unknown_error"},
            )

        return await self.async_step_boating_region()

    # ------------------------------------------------------------------ #
    # Step: boating_region                                                 #
    # ------------------------------------------------------------------ #

    async def async_step_boating_region(self, user_input=None):
        """Select a boating region, or skip boating entirely."""
        if user_input is None:
            try:
                session = async_create_clientsession(self.hass)
                with async_timeout.timeout(10):
                    response = await session.get(
                        "https://www.metservice.com/publicData/webdata/marine"
                    )
                data = await response.json(content_type=None)
                self.boating_regions = data["layout"]["search"]["searchLocations"][0]["items"]
            except Exception:
                _LOGGER.exception("Failed to fetch marine regions for boating setup")
                return self.async_abort(reason="boating_unavailable")

            # When reconfiguring, pre-select the already-configured region.
            current_url = self.user_info.get(CONF_BOATING_REGION_URL, "")
            default = _SKIP
            if current_url:
                for item in self.boating_regions:
                    if item["heading"]["url"].lstrip("/") == current_url:
                        default = item["heading"]["label"]
                        break

            return self.async_show_form(
                step_id="boating_region",
                data_schema=self._async_generate_select_schema_region(
                    self.boating_regions,
                    CONF_BOATING_REGION_URL,
                    "None — skip boating",
                    default=default,
                ),
            )

        selected_label = user_input[CONF_BOATING_REGION_URL]
        if selected_label == _SKIP:
            self.user_info[CONF_BOATING_URL] = ""
            self.user_info.pop(CONF_BOATING_REGION_URL, None)
            return self._finish_flow()

        selected_region = next(
            (item for item in self.boating_regions if item["heading"]["label"] == selected_label),
            None,
        )
        self.user_info[CONF_BOATING_REGION_URL] = (
            selected_region["heading"]["url"].lstrip("/") if selected_region else None
        )
        return await self.async_step_boating_location()

    # ------------------------------------------------------------------ #
    # Step: boating_location                                               #
    # ------------------------------------------------------------------ #

    async def async_step_boating_location(self, user_input=None):
        """Select a specific boating location within the chosen region."""
        if user_input is None:
            region = self.user_info[CONF_BOATING_REGION_URL]
            region_slug = region.split("/")[-1]
            url = f"https://www.metservice.com/publicData/webdata/{region}/boating"
            try:
                session = async_create_clientsession(self.hass)
                with async_timeout.timeout(10):
                    response = await session.get(url)
                if response.status != 200:
                    _LOGGER.error(
                        "Boating location fetch returned HTTP %s for %s", response.status, url
                    )
                    return self.async_abort(reason="boating_unavailable")
                data = await response.json(content_type=None)
                all_markers = (
                    data.get("layout", {})
                    .get("primary", {})
                    .get("map", {})
                    .get("markers", [])
                )
                prefix = f"/marine/regions/{region_slug}/boating/locations/"
                # Prefer markers whose resolved URL starts with the expected prefix.
                # MetService often lazy-loads marker actions via dataUrl so the URL
                # may be empty; fall back to all labelled markers in that case and
                # rely on slug-based URL construction in _get_boating_url_from_label.
                resolved = [
                    m for m in all_markers if self._get_marker_url(m, "").startswith(prefix)
                ]
                self.boating_locations = resolved if resolved else [
                    m
                    for m in all_markers
                    if isinstance(m.get("label"), dict) and m["label"].get("text")
                ]
                if not self.boating_locations:
                    _LOGGER.error(
                        "No boating locations found for region %s", region_slug
                    )
                    return self.async_abort(reason="boating_unavailable")
            except Exception:
                _LOGGER.exception("Failed to fetch boating locations from %s", url)
                return self.async_abort(reason="boating_unavailable")

            self.boating_locations_map = {
                str(index): m["label"]["text"]
                for index, m in enumerate(self.boating_locations)
                if isinstance(m.get("label"), dict) and m["label"].get("text")
            }
            select_opts = [
                {"value": label, "label": label}
                for label in self.boating_locations_map.values()
            ]
            return self.async_show_form(
                step_id="boating_location",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_BOATING_URL): SelectSelector(
                            SelectSelectorConfig(options=select_opts)
                        ),
                    }
                ),
            )

        selected_label = user_input[CONF_BOATING_URL]
        boating_url = self._get_boating_url_from_label(selected_label)
        if not boating_url:
            _LOGGER.error(
                "Could not find URL for boating location: %s", selected_label
            )
            select_opts = [
                {"value": label, "label": label}
                for label in self.boating_locations_map.values()
            ]
            return self.async_show_form(
                step_id="boating_location",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_BOATING_URL): SelectSelector(
                            SelectSelectorConfig(options=select_opts)
                        ),
                    }
                ),
                errors={"base": "tide_location_not_found"},
            )

        full_url = f"https://www.metservice.com/publicData/webdata/{boating_url.lstrip('/')}"
        self.user_info[CONF_BOATING_URL] = full_url
        return self._finish_flow()
