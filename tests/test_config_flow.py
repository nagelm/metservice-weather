"""Tests for the metservice_weather config flow."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from custom_components.metservice_weather.const import (
    DOMAIN,
    CONF_AUTO_HIDE_SEASONAL,
)
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
    """Reconfigure of an entry with auto_hide_seasonal=True pre-fills the toggle; the section stays collapsed."""
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
    assert section.options["collapsed"] is True

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
