"""Tests for the metservice_weather config flow."""
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from custom_components.metservice_weather.const import DOMAIN, DEFAULT_LOCATION
from custom_components.metservice_weather.config_flow import (
    CONF_MARINE_REGION,
    CONF_TIDE_URL,
    CONF_BOATING_URL,
    CONF_SURF_URL,
    CONF_USE_MOBILE,
    CONF_MOBILE_API_KEY,
    WeatherFlowHandler,
)
from homeassistant.const import CONF_NAME, CONF_LOCATION


# ---------------------------------------------------------------------------
# Test 1 — public API, no marine region
# ---------------------------------------------------------------------------

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
            CONF_USE_MOBILE: False,
            CONF_MOBILE_API_KEY: "",
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Napier"


# ---------------------------------------------------------------------------
# Test 2 — public API with marine region (proceeds to locations step)
# ---------------------------------------------------------------------------

async def test_public_with_marine_region(hass, mock_coordinator_refresh):
    """Selecting a marine region shows the locations step; skipping all creates entry."""
    empty_markers_resp = AsyncMock()
    empty_markers_resp.json = AsyncMock(return_value={
        "layout": {"primary": {"map": {"modules": [], "markers": []}}}
    })
    empty_markers_resp.status = 200

    marine_resp = AsyncMock()
    marine_resp.json = AsyncMock(return_value={
        "layout": {
            "search": {
                "searchLocations": [{"items": [
                    {"heading": {"label": "Northland", "url": "/marine/regions/northland"}}
                ]}]
            }
        }
    })
    marine_resp.status = 200

    session_mock = MagicMock()
    # First call: marine fetch; subsequent calls: tide/boating/surf location fetches
    session_mock.get = AsyncMock(side_effect=[
        marine_resp,
        empty_markers_resp,
        empty_markers_resp,
        empty_markers_resp,
    ])

    with patch(
        "custom_components.metservice_weather.config_flow.async_create_clientsession",
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
                CONF_USE_MOBILE: False,
                CONF_MOBILE_API_KEY: "",
            },
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "locations"

        # No tide/boating/surf options shown (empty markers), so submit empty
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {},
        )
        assert result["type"] == FlowResultType.CREATE_ENTRY


# ---------------------------------------------------------------------------
# Test 3 — mobile API with valid key
# ---------------------------------------------------------------------------

async def test_mobile_valid_key(hass, mock_coordinator_refresh):
    """Mobile API with a valid key creates entry."""
    marine_resp = AsyncMock()
    marine_resp.json = AsyncMock(return_value={
        "layout": {"search": {"searchLocations": [{"items": []}]}}
    })
    marine_resp.status = 200

    key_valid_resp = AsyncMock()
    key_valid_resp.status = 200

    session_mock = MagicMock()
    session_mock.get = AsyncMock(side_effect=[marine_resp, key_valid_resp])

    with patch(
        "custom_components.metservice_weather.config_flow.async_create_clientsession",
        return_value=session_mock,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] == FlowResultType.FORM

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_NAME: "Auckland",
                CONF_LOCATION: "/towns-cities/regions/auckland/locations/auckland",
                CONF_MARINE_REGION: "skip",
                CONF_USE_MOBILE: True,
                CONF_MOBILE_API_KEY: "validkey123",
            },
        )
        assert result["type"] == FlowResultType.CREATE_ENTRY


# ---------------------------------------------------------------------------
# Test 4 — mobile API, no key supplied
# ---------------------------------------------------------------------------

async def test_mobile_no_key(hass, mock_marine_session):
    """Mobile API with empty key shows error on the form."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Test",
            CONF_LOCATION: DEFAULT_LOCATION,
            CONF_MARINE_REGION: "skip",
            CONF_USE_MOBILE: True,
            CONF_MOBILE_API_KEY: "",
        },
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {CONF_MOBILE_API_KEY: "api_key_required"}


# ---------------------------------------------------------------------------
# Test 5 — mobile API, invalid key (401 response)
# ---------------------------------------------------------------------------

async def test_mobile_invalid_key(hass, mock_coordinator_refresh):
    """Mobile API with a bad key shows invalid_api_key error."""
    marine_resp = AsyncMock()
    marine_resp.json = AsyncMock(return_value={
        "layout": {"search": {"searchLocations": [{"items": []}]}}
    })
    marine_resp.status = 200

    bad_key_resp = AsyncMock()
    bad_key_resp.status = 401

    session_mock = MagicMock()
    session_mock.get = AsyncMock(side_effect=[marine_resp, bad_key_resp])

    with patch(
        "custom_components.metservice_weather.config_flow.async_create_clientsession",
        return_value=session_mock,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] == FlowResultType.FORM

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_NAME: "Test",
                CONF_LOCATION: DEFAULT_LOCATION,
                CONF_MARINE_REGION: "skip",
                CONF_USE_MOBILE: True,
                CONF_MOBILE_API_KEY: "badkey",
            },
        )
        assert result["type"] == FlowResultType.FORM
        assert result["errors"] == {CONF_MOBILE_API_KEY: "invalid_api_key"}


# ---------------------------------------------------------------------------
# Test 6 — mobile API, timeout during key validation
# ---------------------------------------------------------------------------

async def test_mobile_timeout(hass, mock_coordinator_refresh):
    """Timeout during key validation shows cannot_connect error."""
    marine_resp = AsyncMock()
    marine_resp.json = AsyncMock(return_value={
        "layout": {"search": {"searchLocations": [{"items": []}]}}
    })
    marine_resp.status = 200

    session_mock = MagicMock()
    session_mock.get = AsyncMock(side_effect=[marine_resp, TimeoutError()])

    with patch(
        "custom_components.metservice_weather.config_flow.async_create_clientsession",
        return_value=session_mock,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] == FlowResultType.FORM

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_NAME: "Test",
                CONF_LOCATION: DEFAULT_LOCATION,
                CONF_MARINE_REGION: "skip",
                CONF_USE_MOBILE: True,
                CONF_MOBILE_API_KEY: "somekey",
            },
        )
        assert result["type"] == FlowResultType.FORM
        assert result["errors"] == {"base": "cannot_connect"}


# ---------------------------------------------------------------------------
# Test 7 — duplicate location aborts
# ---------------------------------------------------------------------------

async def test_duplicate_location_aborts(hass, mock_marine_session):
    """Second setup with same location unique_id aborts."""
    # First entry
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Napier",
            CONF_LOCATION: "/towns-cities/regions/hawkes-bay/locations/napier",
            CONF_MARINE_REGION: "skip",
            CONF_USE_MOBILE: False,
            CONF_MOBILE_API_KEY: "",
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY

    # Second entry with same location
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
            CONF_USE_MOBILE: False,
            CONF_MOBILE_API_KEY: "",
        },
    )
    assert result2["type"] == FlowResultType.ABORT
    assert result2["reason"] == "already_configured"


# ---------------------------------------------------------------------------
# Test 8 — marine fetch fails gracefully
# ---------------------------------------------------------------------------

async def test_marine_fetch_fails_gracefully(hass, mock_coordinator_refresh):
    """If marine fetch raises an exception, the form still shows with no crash."""
    session_mock = MagicMock()
    session_mock.get = AsyncMock(side_effect=Exception("network error"))

    with patch(
        "custom_components.metservice_weather.config_flow.async_create_clientsession",
        return_value=session_mock,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "setup"


# ---------------------------------------------------------------------------
# Test 9 — reconfigure
# ---------------------------------------------------------------------------

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
            CONF_USE_MOBILE: False,
            CONF_MOBILE_API_KEY: "",
        },
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert existing_entry.data[CONF_NAME] == "Napier Updated"


# ---------------------------------------------------------------------------
# Test 10 — reauth: public API entry is not applicable
# ---------------------------------------------------------------------------

async def test_reauth_public_not_applicable(hass, mock_coordinator_refresh):
    """Reauth on a public API entry aborts with not_applicable."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
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
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=entry.data,
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "not_applicable"


# ---------------------------------------------------------------------------
# Test 11 — reauth: mobile API, empty key shows error
# ---------------------------------------------------------------------------

async def test_reauth_mobile_empty_key(hass, mock_coordinator_refresh):
    """Reauth confirm with empty key shows api_key_required error."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"{DOMAIN}-Mobile",
        data={
            CONF_NAME: "Mobile",
            CONF_LOCATION: "/towns-cities/regions/auckland/locations/auckland",
            "api": "mobile",
            CONF_MOBILE_API_KEY: "oldkey",
            "marine_region": "",
            "tide_url": "",
            "boating_url": "",
            "surf_url": "",
        },
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=entry.data,
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_MOBILE_API_KEY: ""},
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {CONF_MOBILE_API_KEY: "api_key_required"}


# ---------------------------------------------------------------------------
# Test 12 — reauth: mobile API, invalid key (401)
# ---------------------------------------------------------------------------

async def test_reauth_mobile_invalid_key(hass, mock_coordinator_refresh):
    """Reauth confirm with a rejected key shows invalid_api_key error."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"{DOMAIN}-Mobile2",
        data={
            CONF_NAME: "Mobile2",
            CONF_LOCATION: "/towns-cities/regions/auckland/locations/auckland",
            "api": "mobile",
            CONF_MOBILE_API_KEY: "oldkey",
            "marine_region": "",
            "tide_url": "",
            "boating_url": "",
            "surf_url": "",
        },
    )
    entry.add_to_hass(hass)

    bad_key_resp = AsyncMock()
    bad_key_resp.status = 401

    session_mock = MagicMock()
    session_mock.get = AsyncMock(return_value=bad_key_resp)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=entry.data,
    )
    assert result["type"] == FlowResultType.FORM

    with patch(
        "custom_components.metservice_weather.config_flow.async_create_clientsession",
        return_value=session_mock,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_MOBILE_API_KEY: "badkey"},
        )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {CONF_MOBILE_API_KEY: "invalid_api_key"}


# ---------------------------------------------------------------------------
# Test 13 — reauth: mobile API, valid key accepted
# ---------------------------------------------------------------------------

async def test_reauth_mobile_valid_key(hass, mock_coordinator_refresh):
    """Reauth confirm with a valid key updates the entry and reloads."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"{DOMAIN}-Mobile3",
        data={
            CONF_NAME: "Mobile3",
            CONF_LOCATION: "/towns-cities/regions/auckland/locations/auckland",
            "api": "mobile",
            CONF_MOBILE_API_KEY: "oldkey",
            "marine_region": "",
            "tide_url": "",
            "boating_url": "",
            "surf_url": "",
        },
    )
    entry.add_to_hass(hass)

    ok_resp = AsyncMock()
    ok_resp.status = 200

    session_mock = MagicMock()
    session_mock.get = AsyncMock(return_value=ok_resp)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=entry.data,
    )
    assert result["type"] == FlowResultType.FORM

    with patch(
        "custom_components.metservice_weather.config_flow.async_create_clientsession",
        return_value=session_mock,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_MOBILE_API_KEY: "newvalidkey"},
        )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_MOBILE_API_KEY] == "newvalidkey"


# ---------------------------------------------------------------------------
# Test 14 — reauth: network error during key validation
# ---------------------------------------------------------------------------

async def test_reauth_mobile_cannot_connect(hass, mock_coordinator_refresh):
    """Reauth confirm with a network error shows cannot_connect error."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"{DOMAIN}-Mobile4",
        data={
            CONF_NAME: "Mobile4",
            CONF_LOCATION: "/towns-cities/regions/auckland/locations/auckland",
            "api": "mobile",
            CONF_MOBILE_API_KEY: "oldkey",
            "marine_region": "",
            "tide_url": "",
            "boating_url": "",
            "surf_url": "",
        },
    )
    entry.add_to_hass(hass)

    session_mock = MagicMock()
    session_mock.get = AsyncMock(side_effect=Exception("network error"))

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=entry.data,
    )
    assert result["type"] == FlowResultType.FORM

    with patch(
        "custom_components.metservice_weather.config_flow.async_create_clientsession",
        return_value=session_mock,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_MOBILE_API_KEY: "somekey"},
        )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


# ---------------------------------------------------------------------------
# Test 15 — location fetch exception is swallowed, step still shows
# ---------------------------------------------------------------------------

async def test_locations_fetch_exception_graceful(hass, mock_coordinator_refresh):
    """If one of tide/boating/surf fetches raises, the locations form still shows."""
    marine_resp = AsyncMock()
    marine_resp.json = AsyncMock(return_value={
        "layout": {
            "search": {
                "searchLocations": [{"items": [
                    {"heading": {"label": "Northland", "url": "/marine/regions/northland"}}
                ]}]
            }
        }
    })
    marine_resp.status = 200

    ok_resp = AsyncMock()
    ok_resp.json = AsyncMock(return_value={
        "layout": {"primary": {"map": {"modules": [], "markers": []}}}
    })
    ok_resp.status = 200

    session_mock = MagicMock()
    # Marine fetch succeeds; tide raises; boating and surf succeed
    session_mock.get = AsyncMock(side_effect=[
        marine_resp,
        Exception("tide fetch failed"),
        ok_resp,
        ok_resp,
    ])

    with patch(
        "custom_components.metservice_weather.config_flow.async_create_clientsession",
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
                CONF_USE_MOBILE: False,
                CONF_MOBILE_API_KEY: "",
            },
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "locations"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {}
        )
        assert result["type"] == FlowResultType.CREATE_ENTRY


# ---------------------------------------------------------------------------
# Test 16 — _marker_url returns empty string on malformed marker
# ---------------------------------------------------------------------------

def test_marker_url_malformed():
    """_marker_url returns '' when the marker dict is missing expected keys."""
    assert WeatherFlowHandler._marker_url({}) == ""
    assert WeatherFlowHandler._marker_url({"action": {}}) == ""
    assert WeatherFlowHandler._marker_url({"action": {"modules": []}}) == ""
    assert WeatherFlowHandler._marker_url(None) == ""  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Test 17 — _resolve_url uses action string path when marker URL is empty
# ---------------------------------------------------------------------------

def test_resolve_url_action_string_path(hass):
    """_resolve_url returns the action string when _marker_url returns empty."""
    flow = WeatherFlowHandler()
    flow.hass = hass

    marker = {"label": {"text": "Mangawhai"}, "action": "/marine/regions/northland/tides/locations/mangawhai"}
    label_map = {"0": "Mangawhai"}
    locations = [marker]

    result = flow._resolve_url("Mangawhai", label_map, locations, "marine/regions/northland", "tides")
    assert result == "/marine/regions/northland/tides/locations/mangawhai"


# ---------------------------------------------------------------------------
# Test 18 — _resolve_url falls back to slug-constructed URL
# ---------------------------------------------------------------------------

def test_resolve_url_fallback_slug(hass):
    """_resolve_url constructs a fallback URL when neither URL nor action is usable."""
    flow = WeatherFlowHandler()
    flow.hass = hass

    marker = {"label": {"text": "Big Beach"}, "action": "not a path"}
    label_map = {"0": "Big Beach"}
    locations = [marker]

    result = flow._resolve_url("Big Beach", label_map, locations, "marine/regions/northland", "surf")
    assert result == "/marine/regions/northland/surf/locations/big-beach"


# ---------------------------------------------------------------------------
# Test 19 — reconfigure pre-fills existing marine region label
# ---------------------------------------------------------------------------

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
    marine_resp.json = AsyncMock(return_value={
        "layout": {
            "search": {
                "searchLocations": [{"items": [
                    {"heading": {"label": "Northland", "url": "/marine/regions/northland"}}
                ]}]
            }
        }
    })
    marine_resp.status = 200

    session_mock = MagicMock()
    session_mock.get = AsyncMock(return_value=marine_resp)

    with patch(
        "custom_components.metservice_weather.config_flow.async_create_clientsession",
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
        # The schema default for marine region should be pre-filled
        schema = result["data_schema"].schema
        for key in schema:
            if hasattr(key, "schema") and "marine_region" in str(key.schema):
                assert key.default() == "Northland"
                break
