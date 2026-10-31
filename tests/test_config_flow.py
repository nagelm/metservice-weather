"""Tests for the metservice_weather config flow."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from custom_components.metservice_weather.const import (
    DOMAIN,
    CONF_AUTO_HIDE_SEASONAL,
)
from custom_components.metservice_weather.helpers import normalize_location_path
from tests.conftest import MOCK_MARINE_RESPONSE
from custom_components.metservice_weather.config_flow import (
    CONF_CUSTOM_LOCATION,
    CONF_MARINE_REGION,
    SECTION_ADVANCED_OPTIONS,
    WeatherFlowHandler,
    async_fetch_locations,
)
from homeassistant.const import CONF_NAME, CONF_LOCATION


async def test_public_no_marine(hass, mock_marine_session):
    """User flow with public API and marine skipped creates entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "setup"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Napier",
            CONF_LOCATION: "/towns-cities/regions/hawkes-bay/locations/napier",
            CONF_MARINE_REGION: "skip",
            SECTION_ADVANCED_OPTIONS: {},
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Napier"


async def test_public_with_marine_region(hass, mock_coordinator_refresh):
    """Selecting a marine region shows the locations step; skipping all creates entry."""
    empty_markers_resp = AsyncMock()
    empty_markers_resp.json = AsyncMock(
        return_value={"layout": {"primary": {"map": {"modules": [], "markers": []}}}}
    )
    empty_markers_resp.status = 200

    marine_resp = AsyncMock()
    marine_resp.json = AsyncMock(
        return_value={
            "layout": {
                "search": {
                    "searchLocations": [
                        {
                            "items": [
                                {
                                    "heading": {
                                        "label": "Northland",
                                        "url": "/marine/regions/northland",
                                    }
                                }
                            ]
                        }
                    ]
                }
            }
        }
    )
    marine_resp.status = 200

    session_mock = MagicMock()
    session_mock.get = AsyncMock(
        side_effect=[
            marine_resp,
            empty_markers_resp,
            empty_markers_resp,
            empty_markers_resp,
        ]
    )

    with patch(
        "custom_components.metservice_weather.config_flow.async_get_clientsession",
        return_value=session_mock,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "setup"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_NAME: "Northland",
                CONF_LOCATION: "/towns-cities/regions/northland/locations/whangarei",
                CONF_MARINE_REGION: "Northland",
                SECTION_ADVANCED_OPTIONS: {},
            },
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "locations"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {},
        )
        assert result["type"] == FlowResultType.CREATE_ENTRY


async def test_duplicate_location_aborts(hass, mock_marine_session):
    """Second setup with same location unique_id aborts."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Napier",
            CONF_LOCATION: "/towns-cities/regions/hawkes-bay/locations/napier",
            CONF_MARINE_REGION: "skip",
            SECTION_ADVANCED_OPTIONS: {},
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY

    result2 = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result2["type"] == FlowResultType.FORM

    result2 = await hass.config_entries.flow.async_configure(
        result2["flow_id"],
        {
            CONF_NAME: "Napier Duplicate",
            CONF_LOCATION: "/towns-cities/regions/hawkes-bay/locations/napier",
            CONF_MARINE_REGION: "skip",
            SECTION_ADVANCED_OPTIONS: {},
        },
    )
    assert result2["type"] == FlowResultType.ABORT
    assert result2["reason"] == "already_configured"


async def test_marine_fetch_fails_gracefully(hass, mock_coordinator_refresh):
    """If marine fetch raises an exception, the form still shows with no crash."""
    session_mock = MagicMock()
    session_mock.get = AsyncMock(side_effect=Exception("network error"))

    with patch(
        "custom_components.metservice_weather.config_flow.async_get_clientsession",
        return_value=session_mock,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "setup"


async def test_reconfigure(hass, mock_marine_session):
    """Reconfigure flow pre-fills existing entry data and updates on submit."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    existing_entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"{DOMAIN}-/towns-cities/regions/hawkes-bay/locations/napier",
        data={
            CONF_NAME: "Napier",
            CONF_LOCATION: "/towns-cities/regions/hawkes-bay/locations/napier",
            "api": "public",
            "marine_region": "",
            "tide_url": "",
            "boating_url": "",
            "surf_url": "",
        },
    )
    existing_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": existing_entry.entry_id,
        },
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "setup"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Napier Updated",
            CONF_LOCATION: "/towns-cities/regions/hawkes-bay/locations/napier",
            CONF_MARINE_REGION: "skip",
            SECTION_ADVANCED_OPTIONS: {},
        },
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert existing_entry.data[CONF_NAME] == "Napier Updated"

    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(existing_entry.entry_id)
    await hass.async_block_till_done()


async def test_locations_fetch_exception_graceful(hass, mock_coordinator_refresh):
    """If one of tide/boating/surf fetches raises, the locations form still shows."""
    marine_resp = AsyncMock()
    marine_resp.json = AsyncMock(
        return_value={
            "layout": {
                "search": {
                    "searchLocations": [
                        {
                            "items": [
                                {
                                    "heading": {
                                        "label": "Northland",
                                        "url": "/marine/regions/northland",
                                    }
                                }
                            ]
                        }
                    ]
                }
            }
        }
    )
    marine_resp.status = 200

    ok_resp = AsyncMock()
    ok_resp.json = AsyncMock(
        return_value={"layout": {"primary": {"map": {"modules": [], "markers": []}}}}
    )
    ok_resp.status = 200

    session_mock = MagicMock()
    session_mock.get = AsyncMock(
        side_effect=[
            marine_resp,
            Exception("tide fetch failed"),
            ok_resp,
            ok_resp,
        ]
    )

    with patch(
        "custom_components.metservice_weather.config_flow.async_get_clientsession",
        return_value=session_mock,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_NAME: "Northland",
                CONF_LOCATION: "/towns-cities/regions/northland/locations/whangarei",
                CONF_MARINE_REGION: "Northland",
                SECTION_ADVANCED_OPTIONS: {},
            },
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "locations"

        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        assert result["type"] == FlowResultType.CREATE_ENTRY


def test_marker_url_malformed():
    """_marker_url returns '' when the marker dict is missing expected keys."""
    assert WeatherFlowHandler._marker_url({}) == ""
    assert WeatherFlowHandler._marker_url({"action": {}}) == ""
    assert WeatherFlowHandler._marker_url({"action": {"modules": []}}) == ""
    assert WeatherFlowHandler._marker_url(None) == ""  # type: ignore[arg-type]


def test_resolve_url_action_string_path(hass):
    """_resolve_url returns the action string when _marker_url returns empty."""
    flow = WeatherFlowHandler()
    flow.hass = hass

    marker = {
        "label": {"text": "Mangawhai"},
        "action": "/marine/regions/northland/tides/locations/mangawhai",
    }
    label_map = {"0": "Mangawhai"}
    locations = [marker]

    result = flow._resolve_url(
        "Mangawhai", label_map, locations, "marine/regions/northland", "tides"
    )
    assert result == "/marine/regions/northland/tides/locations/mangawhai"


def test_resolve_url_fallback_slug(hass):
    """_resolve_url constructs a fallback URL when neither URL nor action is usable."""
    flow = WeatherFlowHandler()
    flow.hass = hass

    marker = {"label": {"text": "Big Beach"}, "action": "not a path"}
    label_map = {"0": "Big Beach"}
    locations = [marker]

    result = flow._resolve_url(
        "Big Beach", label_map, locations, "marine/regions/northland", "surf"
    )
    assert result == "/marine/regions/northland/surf/locations/big-beach"


async def test_reconfigure_prefills_marine_region(hass, mock_coordinator_refresh):
    """Reconfigure of an entry with a marine_region pre-fills the region label."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    existing_entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"{DOMAIN}-/towns-cities/regions/northland/locations/whangarei",
        data={
            CONF_NAME: "Whangarei",
            CONF_LOCATION: "/towns-cities/regions/northland/locations/whangarei",
            "api": "public",
            "marine_region": "marine/regions/northland",
            "tide_url": "",
            "boating_url": "",
            "surf_url": "",
        },
    )
    existing_entry.add_to_hass(hass)

    marine_resp = AsyncMock()
    marine_resp.json = AsyncMock(
        return_value={
            "layout": {
                "search": {
                    "searchLocations": [
                        {
                            "items": [
                                {
                                    "heading": {
                                        "label": "Northland",
                                        "url": "/marine/regions/northland",
                                    }
                                }
                            ]
                        }
                    ]
                }
            }
        }
    )
    marine_resp.status = 200

    session_mock = MagicMock()
    session_mock.get = AsyncMock(return_value=marine_resp)

    with patch(
        "custom_components.metservice_weather.config_flow.async_get_clientsession",
        return_value=session_mock,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_RECONFIGURE,
                "entry_id": existing_entry.entry_id,
            },
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "setup"
        schema = result["data_schema"].schema
        for key in schema:
            if hasattr(key, "schema") and "marine_region" in str(key.schema):
                assert key.default() == "Northland"
                break


async def test_setup_form_includes_auto_hide_seasonal_field(hass, mock_marine_session):
    """The setup form's Advanced section includes auto_hide_seasonal, defaulting False, collapsed."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "setup"

    schema = result["data_schema"].schema
    section_matches = [key for key in schema if key.schema == SECTION_ADVANCED_OPTIONS]
    assert len(section_matches) == 1
    section = schema[section_matches[0]]
    assert section.options["collapsed"] is True

    inner_schema = section.schema.schema
    matches = [key for key in inner_schema if key.schema == CONF_AUTO_HIDE_SEASONAL]
    assert len(matches) == 1
    assert matches[0].default() is False


async def test_auto_hide_seasonal_true_persists_in_entry_data(
    hass, mock_marine_session
):
    """Submitting the setup form with a nested auto_hide_seasonal=True stores it flat on the entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Napier",
            CONF_LOCATION: "/towns-cities/regions/hawkes-bay/locations/napier",
            CONF_MARINE_REGION: "skip",
            SECTION_ADVANCED_OPTIONS: {CONF_AUTO_HIDE_SEASONAL: True},
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["result"].data[CONF_AUTO_HIDE_SEASONAL] is True


async def test_auto_hide_seasonal_false_persists_in_entry_data(
    hass, mock_marine_session
):
    """Submitting the setup form with a nested auto_hide_seasonal=False stores it flat on the entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Napier",
            CONF_LOCATION: "/towns-cities/regions/hawkes-bay/locations/napier",
            CONF_MARINE_REGION: "skip",
            SECTION_ADVANCED_OPTIONS: {CONF_AUTO_HIDE_SEASONAL: False},
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["result"].data[CONF_AUTO_HIDE_SEASONAL] is False


async def test_auto_hide_seasonal_empty_section_defaults_false(
    hass, mock_marine_session
):
    """Submitting the setup form with an empty Advanced section defaults auto_hide_seasonal to False."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Napier",
            CONF_LOCATION: "/towns-cities/regions/hawkes-bay/locations/napier",
            CONF_MARINE_REGION: "skip",
            SECTION_ADVANCED_OPTIONS: {},
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["result"].data[CONF_AUTO_HIDE_SEASONAL] is False


async def test_reconfigure_prefills_auto_hide_seasonal(hass, mock_marine_session):
    """Reconfigure of an entry with auto_hide_seasonal=True pre-fills the toggle and opens the section."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    existing_entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"{DOMAIN}-/towns-cities/regions/hawkes-bay/locations/napier",
        data={
            CONF_NAME: "Napier",
            CONF_LOCATION: "/towns-cities/regions/hawkes-bay/locations/napier",
            "api": "public",
            "marine_region": "",
            "tide_url": "",
            "boating_url": "",
            "surf_url": "",
            CONF_AUTO_HIDE_SEASONAL: True,
        },
    )
    existing_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": existing_entry.entry_id,
        },
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "setup"

    schema = result["data_schema"].schema
    section_matches = [key for key in schema if key.schema == SECTION_ADVANCED_OPTIONS]
    assert len(section_matches) == 1
    section = schema[section_matches[0]]
    assert section.options["collapsed"] is False

    inner_schema = section.schema.schema
    matches = [key for key in inner_schema if key.schema == CONF_AUTO_HIDE_SEASONAL]
    assert len(matches) == 1
    assert matches[0].default() is True


async def test_reconfigure_collapses_advanced_section_when_disabled(
    hass, mock_marine_session
):
    """Reconfigure of an entry with auto_hide_seasonal=False renders the Advanced section collapsed."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    existing_entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"{DOMAIN}-/towns-cities/regions/hawkes-bay/locations/napier",
        data={
            CONF_NAME: "Napier",
            CONF_LOCATION: "/towns-cities/regions/hawkes-bay/locations/napier",
            "api": "public",
            "marine_region": "",
            "tide_url": "",
            "boating_url": "",
            "surf_url": "",
            CONF_AUTO_HIDE_SEASONAL: False,
        },
    )
    existing_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": existing_entry.entry_id,
        },
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "setup"

    schema = result["data_schema"].schema
    section_matches = [key for key in schema if key.schema == SECTION_ADVANCED_OPTIONS]
    assert len(section_matches) == 1
    section = schema[section_matches[0]]
    assert section.options["collapsed"] is True

    inner_schema = section.schema.schema
    matches = [key for key in inner_schema if key.schema == CONF_AUTO_HIDE_SEASONAL]
    assert len(matches) == 1
    assert matches[0].default() is False


@pytest.mark.parametrize(
    ("custom", "expected"),
    [
        (
            "https://www.metservice.com/towns-cities/regions/auckland/locations/makarau/",
            "/towns-cities/regions/auckland/locations/makarau",
        ),
        (
            "https://www.metservice.com/publicData/webdata/towns-cities/regions/auckland/locations/makarau",
            "/towns-cities/regions/auckland/locations/makarau",
        ),
        (
            "https://www.metservice.com/towns-cities/regions/auckland/locations/makarau/7-days",
            "/towns-cities/regions/auckland/locations/makarau",
        ),
        ("makarau", None),
    ],
)
async def test_custom_location_overrides_list(
    hass, mock_marine_session, custom, expected
):
    """A valid custom location is used instead of the list; anything else is rejected."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Makarau",
            CONF_LOCATION: "/towns-cities/regions/hawkes-bay/locations/napier",
            CONF_MARINE_REGION: "skip",
            SECTION_ADVANCED_OPTIONS: {CONF_CUSTOM_LOCATION: custom},
        },
    )
    if expected:
        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["data"][CONF_LOCATION] == expected
    else:
        assert result["errors"] == {"base": "invalid_location"}


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("https://evil.example/towns-cities/regions/auckland/locations/makarau", None),
        ("//evil.example/towns-cities/regions/auckland/locations/makarau", None),
        (
            "https://user@www.metservice.com/towns-cities/regions/auckland/locations/makarau",
            None,
        ),
        (
            "https://www.metservice.com:8443/towns-cities/regions/auckland/locations/makarau",
            None,
        ),
        (
            "https://metservice.com/towns-cities/regions/auckland/locations/makarau",
            "/towns-cities/regions/auckland/locations/makarau",
        ),
        (
            "https://www.metservice.com/publicData/webdata/towns-cities/regions/auckland/locations/makarau",
            "/towns-cities/regions/auckland/locations/makarau",
        ),
        (
            "Https://WWW.MetService.com/towns-cities/regions/auckland/locations/makarau",
            "/towns-cities/regions/auckland/locations/makarau",
        ),
        (
            "www.metservice.com/towns-cities/regions/auckland/locations/makarau",
            "/towns-cities/regions/auckland/locations/makarau",
        ),
        ("metservice.com.evil.example/towns-cities/regions/x/locations/y", None),
        ("/towns-cities/regions/auckland/locations/../../../etc/passwd", None),
        ("/towns-cities/regions/auckland/locations/makarau%2F..%2Fx", None),
        ("/towns-cities/regions/auckland/locations/makarau@evil.example", None),
        ("/towns-cities/regions/auckland/locations/makarau\x00", None),
        ("/towns-cities/regions/auckland/locations/" + "a" * 600, None),
    ],
)
def test_normalize_location_path_rejects_hostile_input(typed, expected):
    """Only a MetService location path survives; other hosts and odd characters are rejected."""
    assert normalize_location_path(typed) == expected


async def test_custom_location_without_a_page_is_rejected(hass, mock_marine_session):
    """A well-formed custom location MetService has no page for is not saved."""
    _, response = mock_marine_session
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    response.status = 404
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Nowhere",
            CONF_LOCATION: "/towns-cities/regions/hawkes-bay/locations/napier",
            CONF_MARINE_REGION: "skip",
            SECTION_ADVANCED_OPTIONS: {
                CONF_CUSTOM_LOCATION: "/towns-cities/regions/auckland/locations/nowhere"
            },
        },
    )
    assert result["errors"] == {"base": "location_not_found"}


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_custom_location_server_error_reports_cannot_connect(
    hass, mock_marine_session, status
):
    """A 5xx or 429 from MetService means it couldn't answer, not that the place doesn't exist."""
    _, response = mock_marine_session
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    response.status = status
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Nowhere",
            CONF_LOCATION: "/towns-cities/regions/hawkes-bay/locations/napier",
            CONF_MARINE_REGION: "skip",
            SECTION_ADVANCED_OPTIONS: {
                CONF_CUSTOM_LOCATION: "/towns-cities/regions/auckland/locations/nowhere"
            },
        },
    )
    assert result["errors"] == {"base": "cannot_connect"}


async def _start_setup(hass):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def test_custom_location_unreachable_reports_cannot_connect(
    hass, mock_marine_session
):
    """A failed page check reports cannot_connect, not a bad address."""
    session, _ = mock_marine_session
    result = await _start_setup(hass)
    session.get = AsyncMock(side_effect=TimeoutError)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Makarau",
            CONF_MARINE_REGION: "skip",
            SECTION_ADVANCED_OPTIONS: {
                CONF_CUSTOM_LOCATION: "/towns-cities/regions/auckland/locations/makarau"
            },
        },
    )
    assert result["errors"] == {"base": "cannot_connect"}


async def test_listed_custom_location_skips_page_check(hass, mock_marine_session):
    """A custom address for a town already in the list is saved without another fetch."""
    session, _ = mock_marine_session
    result = await _start_setup(hass)
    calls = session.get.call_count
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Napier",
            CONF_MARINE_REGION: "skip",
            SECTION_ADVANCED_OPTIONS: {
                CONF_CUSTOM_LOCATION: "https://www.metservice.com/towns-cities/regions/hawkes-bay/locations/napier"
            },
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert session.get.call_count == calls


async def test_no_location_errors_and_keeps_dropdown_empty(hass, mock_marine_session):
    """With neither a list pick nor a custom location the form re-shows without a default."""
    result = await _start_setup(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Nowhere",
            CONF_MARINE_REGION: "skip",
            SECTION_ADVANCED_OPTIONS: {},
        },
    )
    assert result["errors"] == {"base": "invalid_location"}
    key = next(k for k in result["data_schema"].schema if k == CONF_LOCATION)
    assert key.default is vol.UNDEFINED


async def test_reconfigure_with_both_locations_cleared_errors(
    hass, mock_marine_session
):
    """Clearing the Weather location on Reconfigure, with no custom location, is an error."""
    entry = _custom_entry(
        hass, "/towns-cities/regions/hawkes-bay/locations/napier", "Napier"
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )
    key = next(k for k in result["data_schema"].schema if k == CONF_LOCATION)
    assert key.default is vol.UNDEFINED
    assert key.description == {"suggested_value": entry.data[CONF_LOCATION]}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_NAME: "Napier", CONF_MARINE_REGION: "skip", SECTION_ADVANCED_OPTIONS: {}},
    )
    assert result["errors"] == {"base": "invalid_location"}


def _custom_entry(hass, location, name="Makarau"):
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"{DOMAIN}-{location}",
        data={
            CONF_NAME: name,
            CONF_LOCATION: location,
            "api": "public",
            "marine_region": "",
            "tide_url": "",
            "boating_url": "",
            "surf_url": "",
        },
    )
    entry.add_to_hass(hass)
    return entry


async def test_reconfigure_list_pick_replaces_prefilled_custom(
    hass, mock_marine_session
):
    """Picking a town while the pre-filled custom location is untouched moves the entry to that town."""
    custom = "/towns-cities/regions/auckland/locations/makarau"
    napier = "/towns-cities/regions/hawkes-bay/locations/napier"
    entry = _custom_entry(hass, custom)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Makarau",
            CONF_LOCATION: napier,
            CONF_MARINE_REGION: "skip",
            SECTION_ADVANCED_OPTIONS: {CONF_CUSTOM_LOCATION: custom},
        },
    )
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_LOCATION] == napier
    assert entry.unique_id == f"{DOMAIN}-{napier}"


async def test_reconfigure_onto_another_entrys_location_aborts(
    hass, mock_marine_session
):
    """Reconfigure can't move an entry onto a location another entry already uses."""
    custom = "/towns-cities/regions/auckland/locations/makarau"
    _custom_entry(hass, custom)
    napier = _custom_entry(
        hass, "/towns-cities/regions/hawkes-bay/locations/napier", "Napier"
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": napier.entry_id,
        },
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Napier",
            CONF_MARINE_REGION: "skip",
            SECTION_ADVANCED_OPTIONS: {CONF_CUSTOM_LOCATION: custom},
        },
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure_custom_location_opens_advanced(hass, mock_marine_session):
    """An entry on an unlisted location reopens with Advanced expanded and the path filled in."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    custom = "/towns-cities/regions/auckland/locations/makarau"
    existing_entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"{DOMAIN}-{custom}",
        data={
            CONF_NAME: "Makarau",
            CONF_LOCATION: custom,
            "api": "public",
            "marine_region": "",
            "tide_url": "",
            "boating_url": "",
            "surf_url": "",
        },
    )
    existing_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": existing_entry.entry_id,
        },
    )
    schema = result["data_schema"].schema
    section = next(v for k, v in schema.items() if k == SECTION_ADVANCED_OPTIONS)
    assert section.options["collapsed"] is False
    field = next(k for k in section.schema.schema if k == CONF_CUSTOM_LOCATION)
    assert field.description == {"suggested_value": custom}


async def test_setup_form_offers_fetched_locations(hass, mock_marine_session):
    """The location selector lists the fetched index."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    for key, selector in result["data_schema"].schema.items():
        if key == CONF_LOCATION:
            config = selector.config
            assert [o["label"] for o in config["options"]] == ["Napier", "Whangārei"]
            break
    else:
        raise AssertionError("location field missing")


async def test_setup_aborts_without_location_list(
    hass, mock_marine_session, mock_location_index
):
    """The flow aborts with cannot_connect when the location list can't be fetched."""
    mock_location_index.return_value = []
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


async def test_fetch_locations_parses_index():
    """Every valid child of every region becomes an option, in MetService's order."""
    response = AsyncMock()
    response.json = AsyncMock(
        return_value={
            "layout": {
                "search": {
                    "searchLocations": [
                        {
                            "items": [
                                {
                                    "children": [
                                        {
                                            "label": "Kaikohe",
                                            "url": "/rural/regions/northland/locations/kaikohe",
                                        },
                                        {
                                            "label": "Kaitaia",
                                            "url": "/towns-cities/regions/northland/locations/kaitaia",
                                        },
                                        {"label": "No URL"},
                                        {"label": "Search", "url": "/search?q=x"},
                                    ]
                                },
                                {"heading": {"label": "Empty"}},
                            ]
                        },
                        {
                            "items": [
                                {
                                    "children": [
                                        {
                                            "label": "Te Anau",
                                            "url": "/rural/regions/southland/locations/te-anau",
                                        }
                                    ]
                                }
                            ]
                        },
                    ]
                }
            }
        }
    )
    session = MagicMock()
    session.get = AsyncMock(return_value=response)
    assert await async_fetch_locations(session) == [
        {"value": "/rural/regions/northland/locations/kaikohe", "label": "Kaikohe"},
        {
            "value": "/towns-cities/regions/northland/locations/kaitaia",
            "label": "Kaitaia",
        },
        {"value": "/rural/regions/southland/locations/te-anau", "label": "Te Anau"},
    ]


async def test_fetch_locations_failure_returns_empty():
    """A failed index fetch returns an empty list."""
    session = MagicMock()
    session.get = AsyncMock(side_effect=Exception("network error"))
    assert await async_fetch_locations(session) == []


_NORTHLAND_TIDE_URL = (
    "https://www.metservice.com/publicData/webdata"
    "/marine/regions/northland/tides/locations/whangarei"
)


def _northland_marine_entry():
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"{DOMAIN}-/towns-cities/regions/northland/locations/whangarei",
        data={
            CONF_NAME: "Whangarei",
            CONF_LOCATION: "/towns-cities/regions/northland/locations/whangarei",
            "api": "public",
            "marine_region": "marine/regions/northland",
            "tide_url": _NORTHLAND_TIDE_URL,
            "boating_url": "",
            "surf_url": "",
        },
    )
    return entry


async def test_reconfigure_keeps_marine_settings_when_marine_index_fails(
    hass, mock_coordinator_refresh
):
    """With the marine index down, only "skip" is offered, so the stored marine settings stay."""
    entry = _northland_marine_entry()
    entry.add_to_hass(hass)

    session_mock = MagicMock()
    session_mock.get = AsyncMock(side_effect=Exception("marine index down"))
    with patch(
        "custom_components.metservice_weather.config_flow.async_get_clientsession",
        return_value=session_mock,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_RECONFIGURE,
                "entry_id": entry.entry_id,
            },
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_NAME: "Whangarei",
                CONF_LOCATION: "/towns-cities/regions/northland/locations/whangarei",
                CONF_MARINE_REGION: "skip",
                SECTION_ADVANCED_OPTIONS: {},
            },
        )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data["marine_region"] == "marine/regions/northland"
    assert entry.data["tide_url"] == _NORTHLAND_TIDE_URL


async def test_reconfigure_keeps_station_when_its_list_fails(
    hass, mock_coordinator_refresh
):
    """A tide list that fails to load leaves the stored tide station alone in the same region."""
    entry = _northland_marine_entry()
    entry.add_to_hass(hass)

    marine_resp = AsyncMock()
    marine_resp.json = AsyncMock(return_value=MOCK_MARINE_RESPONSE)
    marine_resp.status = 200
    empty_resp = AsyncMock()
    empty_resp.json = AsyncMock(
        return_value={"layout": {"primary": {"map": {"modules": [], "markers": []}}}}
    )
    empty_resp.status = 200

    session_mock = MagicMock()
    session_mock.get = AsyncMock(
        side_effect=[marine_resp, Exception("tide list down"), empty_resp, empty_resp]
    )
    with patch(
        "custom_components.metservice_weather.config_flow.async_get_clientsession",
        return_value=session_mock,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_RECONFIGURE,
                "entry_id": entry.entry_id,
            },
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_NAME: "Whangarei",
                CONF_LOCATION: "/towns-cities/regions/northland/locations/whangarei",
                CONF_MARINE_REGION: "Northland",
                SECTION_ADVANCED_OPTIONS: {},
            },
        )
        assert result["step_id"] == "locations"
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data["tide_url"] == _NORTHLAND_TIDE_URL


async def test_duplicate_location_aborts_after_migrating_an_old_entry(
    hass, mock_marine_session
):
    """A location held by an entry migrated from 1.1 still can't be added twice."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from custom_components.metservice_weather import async_migrate_entry

    location = "/towns-cities/regions/hawkes-bay/locations/napier"
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        minor_version=1,
        unique_id=f"{DOMAIN}-{location}",
        data={"name": "Napier", "location": location, "api": "public", "api_key": "a"},
    )
    entry.add_to_hass(hass)
    assert await async_migrate_entry(hass, entry)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Napier Duplicate",
            CONF_LOCATION: location,
            CONF_MARINE_REGION: "skip",
            SECTION_ADVANCED_OPTIONS: {},
        },
    )

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"
