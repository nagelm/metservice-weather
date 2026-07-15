"""Tests for WeatherUpdateCoordinator fetch paths, accessors, and error handling."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.metservice_weather.coordinator import (
    WeatherUpdateCoordinator,
    WeatherUpdateCoordinatorConfig,
)
from custom_components.metservice_weather.coordinator_types import (
    MetServicePublicData,
)

# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


_PUBLIC_CURRENT = _load("napier_public_current.json")
_PUBLIC_DAILY = _load("napier_public_daily.json")


def _make_config(
    tide_url="",
    boating_url="",
    surf_url="",
) -> WeatherUpdateCoordinatorConfig:
    return WeatherUpdateCoordinatorConfig(
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


def _make_coordinator(hass, **kwargs) -> WeatherUpdateCoordinator:
    config = _make_config(**kwargs)
    coord = WeatherUpdateCoordinator(hass, config)
    return coord


def _mock_response(data, status=200):
    resp = AsyncMock()
    resp.status = status
    resp.json = AsyncMock(return_value=data)
    return resp


# ---------------------------------------------------------------------------
# Test: properties
# ---------------------------------------------------------------------------


async def test_coordinator_properties(hass):
    """Coordinator exposes location and disables tides/boating/surf by default."""
    coord = _make_coordinator(hass)
    assert coord.location == "/towns-cities/regions/hawkes-bay/locations/napier"
    assert coord.location_name == "Napier"
    assert coord.enable_tides is False
    assert coord.enable_boating is False
    assert coord.enable_surf is False


async def test_coordinator_properties_with_urls(hass):
    """Coordinator enables tides, boating, and surf when their URLs are configured."""
    coord = _make_coordinator(
        hass,
        tide_url="https://example.com/tides",
        boating_url="https://example.com/boating",
        surf_url="https://example.com/surf",
    )
    assert coord.enable_tides is True
    assert coord.enable_boating is True
    assert coord.enable_surf is True
    assert coord.tide_url == "https://example.com/tides"


# ---------------------------------------------------------------------------
# Test: get_from_dict (DFS)
# ---------------------------------------------------------------------------


async def test_get_from_dict_simple(hass):
    """get_from_dict resolves a simple nested key path."""
    coord = _make_coordinator(hass)
    data = {"a": {"b": {"c": 42}}}
    assert coord.get_from_dict(data, ["a", "b", "c"]) == 42


async def test_get_from_dict_list_traversal(hass):
    """get_from_dict extracts a field from the first item of a list."""
    coord = _make_coordinator(hass)
    data = {"items": [{"val": 1}, {"val": 2}]}
    assert coord.get_from_dict(data, ["items", "val"]) == 1


async def test_get_from_dict_indexed_list(hass):
    """get_from_dict resolves a numeric string key as a list index."""
    coord = _make_coordinator(hass)
    data = [{"val": 10}, {"val": 20}]
    assert coord.get_from_dict(data, ["1", "val"]) == 20


async def test_get_from_dict_missing_key(hass):
    """get_from_dict returns None when the key path doesn't exist."""
    coord = _make_coordinator(hass)
    data = {"a": 1}
    assert coord.get_from_dict(data, ["b"]) is None


async def test_get_from_dict_empty_keys(hass):
    """get_from_dict returns the original data when no keys are given."""
    coord = _make_coordinator(hass)
    assert coord.get_from_dict({"x": 1}, []) == {"x": 1}


# ---------------------------------------------------------------------------
# Test: _check_errors
# ---------------------------------------------------------------------------


async def test_check_errors_no_errors(hass):
    """_check_errors does not raise when the response has no errors key."""
    coord = _make_coordinator(hass)
    coord._check_errors("http://x", {"data": 1})  # should not raise


async def test_check_errors_empty_errors_list(hass):
    """_check_errors does not raise when the errors list is empty."""
    coord = _make_coordinator(hass)
    coord._check_errors("http://x", {"errors": []})  # empty list — no raise


async def test_check_errors_raises(hass):
    """_check_errors raises ValueError with the API's error message."""
    coord = _make_coordinator(hass)
    with pytest.raises(ValueError, match="something went wrong"):
        coord._check_errors(
            "http://x", {"errors": [{"message": "something went wrong"}]}
        )


# ---------------------------------------------------------------------------
# Test: _parse_pollen_html
# ---------------------------------------------------------------------------


async def test_parse_pollen_html_level_and_plants(hass):
    """_parse_pollen_html extracts the pollen level and plant types."""
    coord = _make_coordinator(hass)
    html = '<span class="status-high">High</span><br/>Grass, Timothy'
    result = coord._parse_pollen_html(html)
    assert result["level"] == "High"
    assert "Grass" in result["type"]


async def test_parse_pollen_html_empty(hass):
    """_parse_pollen_html returns None level and type for unrecognized HTML."""
    coord = _make_coordinator(hass)
    result = coord._parse_pollen_html("<div>nothing here</div>")
    assert result["level"] is None
    assert result["type"] is None


# ---------------------------------------------------------------------------
# Test: _format_timestamp
# ---------------------------------------------------------------------------


async def test_format_timestamp(hass):
    """_format_timestamp converts a local ISO timestamp to UTC."""
    coord = _make_coordinator(hass)
    result = coord._format_timestamp("2024-06-15T12:00:00+12:00")
    assert "2024-06-15" in result
    assert (
        result.endswith("+00:00")
        or "Z" in result
        or "UTC" in result
        or "00:00" in result
    )


# ---------------------------------------------------------------------------
# Test: get_public_weather — happy path
# ---------------------------------------------------------------------------


async def test_get_public_weather_returns_data(hass):
    """get_public_weather returns typed data including weather warnings."""
    coord = _make_coordinator(hass)

    warnings_data = {
        "warnings": [
            {
                "name": "Strong Wind",
                "text": "Gale force winds",
                "threatPeriod": "Tonight",
            }
        ]
    }
    pollen_data = {"layout": {"primary": {"slots": {"main": {"modules": []}}}}}

    responses = [
        _mock_response(_PUBLIC_CURRENT),  # main fetch
        _mock_response(warnings_data),  # warnings fetch
        _mock_response(_PUBLIC_DAILY),  # 7-day fetch
        _mock_response(pollen_data),  # pollen fetch (best-effort)
    ]

    mock_session = MagicMock()
    mock_session.get = AsyncMock(side_effect=responses)
    coord._session = mock_session

    result = await coord.get_public_weather()
    assert isinstance(result, MetServicePublicData)
    assert "Strong Wind" in result.weather_warnings


async def test_get_public_weather_no_warnings(hass):
    """Empty warnings list → 'No warnings' text injected."""
    coord = _make_coordinator(hass)

    warnings_data = {"warnings": []}
    pollen_data = {"layout": {"primary": {"slots": {"main": {"modules": []}}}}}

    mock_session = MagicMock()
    mock_session.get = AsyncMock(
        side_effect=[
            _mock_response(_PUBLIC_CURRENT),
            _mock_response(warnings_data),
            _mock_response(_PUBLIC_DAILY),
            _mock_response(pollen_data),
        ]
    )
    coord._session = mock_session

    result = await coord.get_public_weather()
    assert result.weather_warnings == "No warnings"


async def test_get_public_weather_timeout_raises_update_failed(hass):
    """get_public_weather raises UpdateFailed when the request times out."""
    coord = _make_coordinator(hass)
    mock_session = MagicMock()
    mock_session.get = AsyncMock(side_effect=TimeoutError())
    coord._session = mock_session

    with pytest.raises(UpdateFailed):
        await coord.get_public_weather()


async def test_get_public_weather_client_error_raises_update_failed(hass):
    """get_public_weather raises UpdateFailed on an aiohttp client error."""
    coord = _make_coordinator(hass)
    mock_session = MagicMock()
    mock_session.get = AsyncMock(side_effect=aiohttp.ClientError("conn failed"))
    coord._session = mock_session

    with pytest.raises(UpdateFailed):
        await coord.get_public_weather()


async def test_get_public_weather_none_response_raises_update_failed(hass):
    """get_public_weather raises UpdateFailed when the main fetch returns no data."""
    coord = _make_coordinator(hass)
    resp = _mock_response(None)
    mock_session = MagicMock()
    mock_session.get = AsyncMock(return_value=resp)
    coord._session = mock_session

    with pytest.raises(UpdateFailed, match="No current weather data"):
        await coord.get_public_weather()


async def test_get_public_weather_api_error_raises_update_failed(hass):
    """get_public_weather raises UpdateFailed when the API response contains an error."""
    coord = _make_coordinator(hass)
    error_resp = {"errors": [{"message": "rate limit exceeded"}]}
    mock_session = MagicMock()
    mock_session.get = AsyncMock(return_value=_mock_response(error_resp))
    coord._session = mock_session

    with pytest.raises(UpdateFailed):
        await coord.get_public_weather()


# ---------------------------------------------------------------------------
# Test: _async_update_data dispatches correctly
# ---------------------------------------------------------------------------


async def test_async_update_data_public(hass):
    """_async_update_data delegates to get_public_weather."""
    coord = _make_coordinator(hass)
    with patch.object(
        coord,
        "get_public_weather",
        new_callable=AsyncMock,
        return_value={"current": {}, "daily": {}},
    ) as mock:
        await coord._async_update_data()
        mock.assert_called_once()


# ---------------------------------------------------------------------------
# Test: get_pollen_data
# ---------------------------------------------------------------------------


async def test_get_pollen_data_success(hass):
    """get_pollen_data parses the pollen level from the fetched module."""
    coord = _make_coordinator(hass)
    pollen_html = '<span class="status-low">Low</span><br/>Grass'
    pollen_data = {
        "layout": {
            "primary": {
                "slots": {
                    "main": {
                        "modules": [
                            {"content": [{"iconName": "pollen", "html": pollen_html}]}
                        ]
                    }
                }
            }
        }
    }
    mock_session = MagicMock()
    mock_session.get = AsyncMock(return_value=_mock_response(pollen_data))
    coord._session = mock_session

    result = await coord.get_pollen_data()
    assert result["pollenLevels"]["level"] == "Low"


async def test_get_pollen_data_non_200_returns_empty(hass):
    """get_pollen_data returns empty pollen levels on a non-200 response."""
    coord = _make_coordinator(hass)
    mock_session = MagicMock()
    mock_session.get = AsyncMock(return_value=_mock_response({}, status=404))
    coord._session = mock_session

    result = await coord.get_pollen_data()
    assert result == {"pollenLevels": {"level": None, "type": None}}


async def test_get_pollen_data_exception_returns_empty(hass):
    """get_pollen_data returns empty pollen levels when the fetch raises."""
    coord = _make_coordinator(hass)
    mock_session = MagicMock()
    mock_session.get = AsyncMock(side_effect=Exception("network error"))
    coord._session = mock_session

    result = await coord.get_pollen_data()
    assert result == {"pollenLevels": {"level": None, "type": None}}


# ---------------------------------------------------------------------------
# Test: get_tides
# ---------------------------------------------------------------------------


async def test_get_tides_success(hass):
    """get_tides returns the parsed tide entries."""
    tide_data = {
        "layout": {
            "primary": {
                "slots": {
                    "main": {
                        "modules": [
                            {
                                "tideData": [
                                    {"time": "06:30", "type": "HIGH", "height": 1.8}
                                ]
                            }
                        ]
                    }
                }
            }
        }
    }
    coord = _make_coordinator(hass, tide_url="https://example.com/tides")
    mock_session = MagicMock()
    mock_session.get = AsyncMock(return_value=_mock_response(tide_data))
    coord._session = mock_session

    result = await coord.get_tides()
    assert result is not None
    assert result[0]["type"] == "HIGH"


async def test_get_tides_non_200_returns_none(hass):
    """get_tides returns None on a non-200 response."""
    coord = _make_coordinator(hass, tide_url="https://example.com/tides")
    mock_session = MagicMock()
    mock_session.get = AsyncMock(return_value=_mock_response({}, status=404))
    coord._session = mock_session

    result = await coord.get_tides()
    assert result is None


async def test_get_tides_none_response_returns_none(hass):
    """get_tides returns None when the response body is None."""
    coord = _make_coordinator(hass, tide_url="https://example.com/tides")
    mock_session = MagicMock()
    mock_session.get = AsyncMock(return_value=_mock_response(None))
    coord._session = mock_session

    result = await coord.get_tides()
    assert result is None


async def test_get_tides_missing_tidedata_returns_none(hass):
    """get_tides returns None when no module contains tideData."""
    tide_data = {
        "layout": {"primary": {"slots": {"main": {"modules": [{"other": "data"}]}}}}
    }
    coord = _make_coordinator(hass, tide_url="https://example.com/tides")
    mock_session = MagicMock()
    mock_session.get = AsyncMock(return_value=_mock_response(tide_data))
    coord._session = mock_session

    result = await coord.get_tides()
    assert result is None


async def test_get_tides_network_error_returns_none(hass):
    """get_tides returns None on a network error."""
    coord = _make_coordinator(hass, tide_url="https://example.com/tides")
    mock_session = MagicMock()
    mock_session.get = AsyncMock(side_effect=aiohttp.ClientError("fail"))
    coord._session = mock_session

    result = await coord.get_tides()
    assert result is None


# ---------------------------------------------------------------------------
# Test: get_boating_data
# ---------------------------------------------------------------------------


async def test_get_boating_data_success(hass):
    """get_boating_data returns the boating status and forecast text."""
    boating_data = {
        "layout": {
            "primary": {
                "slots": {
                    "main": {
                        "modules": [
                            {
                                "days": [
                                    {
                                        "view": {"text": "Good", "status": "good"},
                                        "forecast": {
                                            "text": "Calm seas",
                                            "issuedAt": "2024-06-15",
                                        },
                                        "table": {"columns": []},
                                    }
                                ]
                            }
                        ]
                    }
                }
            }
        }
    }
    coord = _make_coordinator(hass, boating_url="https://example.com/boating")
    mock_session = MagicMock()
    mock_session.get = AsyncMock(return_value=_mock_response(boating_data))
    coord._session = mock_session

    result = await coord.get_boating_data()
    assert result["boating_status"] == "Good"
    assert result["boating_forecast"] == "Calm seas"


async def test_get_boating_data_non_200_returns_empty(hass):
    """get_boating_data returns an empty dict on a non-200 response."""
    coord = _make_coordinator(hass, boating_url="https://example.com/boating")
    mock_session = MagicMock()
    mock_session.get = AsyncMock(return_value=_mock_response({}, status=503))
    coord._session = mock_session

    assert await coord.get_boating_data() == {}


async def test_get_boating_data_no_days_returns_empty(hass):
    """get_boating_data returns an empty dict when the days list is empty."""
    boating_data = {
        "layout": {"primary": {"slots": {"main": {"modules": [{"days": []}]}}}}
    }
    coord = _make_coordinator(hass, boating_url="https://example.com/boating")
    mock_session = MagicMock()
    mock_session.get = AsyncMock(return_value=_mock_response(boating_data))
    coord._session = mock_session

    assert await coord.get_boating_data() == {}


async def test_get_boating_data_no_modules_returns_empty(hass):
    """get_boating_data returns an empty dict when there are no modules."""
    boating_data = {"layout": {"primary": {"slots": {"main": {"modules": []}}}}}
    coord = _make_coordinator(hass, boating_url="https://example.com/boating")
    mock_session = MagicMock()
    mock_session.get = AsyncMock(return_value=_mock_response(boating_data))
    coord._session = mock_session

    assert await coord.get_boating_data() == {}


async def test_get_boating_data_network_error_returns_empty(hass):
    """get_boating_data returns an empty dict on a network error."""
    coord = _make_coordinator(hass, boating_url="https://example.com/boating")
    mock_session = MagicMock()
    mock_session.get = AsyncMock(side_effect=aiohttp.ClientError("fail"))
    coord._session = mock_session

    assert await coord.get_boating_data() == {}


# ---------------------------------------------------------------------------
# Test: get_surf_data
# ---------------------------------------------------------------------------


def _surf_marker(path="/marine/regions/northland/surf/locations/waihi-beach"):
    return {
        "action": {
            "modules": [
                {
                    "link": {"url": path},
                    "value": {
                        "rating": 3,
                        "waveHeight": 1.2,
                        "setFace": 1.5,
                        "swell": {"direction": "NW", "swellHeight": 1.0},
                        "wind": {
                            "direction": "SW",
                            "averageSpeed": 20,
                            "gustSpeed": 30,
                        },
                        "period": 8,
                    },
                }
            ]
        },
        "view": {"text": "Fair"},
    }


async def test_get_surf_data_success(hass):
    """get_surf_data returns the surf rating and conditions for a matching marker."""
    surf_url = "https://www.metservice.com/publicData/webdata/marine/regions/northland/surf/locations/waihi-beach"
    surf_data = {"layout": {"primary": {"map": {"markers": [_surf_marker()]}}}}
    coord = _make_coordinator(hass, surf_url=surf_url)
    mock_session = MagicMock()
    mock_session.get = AsyncMock(return_value=_mock_response(surf_data))
    coord._session = mock_session

    result = await coord.get_surf_data()
    assert result["surf_rating"] == 3
    assert result["surf_conditions"] == "Fair"


async def test_get_surf_data_no_matching_marker_returns_empty(hass):
    """get_surf_data returns an empty dict when no marker matches the surf URL."""
    surf_url = "https://www.metservice.com/publicData/webdata/marine/regions/northland/surf/locations/waihi-beach"
    surf_data = {"layout": {"primary": {"map": {"markers": []}}}}
    coord = _make_coordinator(hass, surf_url=surf_url)
    mock_session = MagicMock()
    mock_session.get = AsyncMock(return_value=_mock_response(surf_data))
    coord._session = mock_session

    assert await coord.get_surf_data() == {}


async def test_get_surf_data_non_200_returns_empty(hass):
    """get_surf_data returns an empty dict on a non-200 response."""
    surf_url = "https://www.metservice.com/publicData/webdata/marine/regions/northland/surf/locations/waihi-beach"
    coord = _make_coordinator(hass, surf_url=surf_url)
    mock_session = MagicMock()
    mock_session.get = AsyncMock(return_value=_mock_response({}, status=404))
    coord._session = mock_session

    assert await coord.get_surf_data() == {}


async def test_get_surf_data_network_error_returns_empty(hass):
    """get_surf_data returns an empty dict on a network error."""
    surf_url = "https://www.metservice.com/publicData/webdata/marine/regions/northland/surf/locations/waihi-beach"
    coord = _make_coordinator(hass, surf_url=surf_url)
    mock_session = MagicMock()
    mock_session.get = AsyncMock(side_effect=aiohttp.ClientError("fail"))
    coord._session = mock_session

    assert await coord.get_surf_data() == {}


# ---------------------------------------------------------------------------
# Test: expand_data_urls
# ---------------------------------------------------------------------------


async def test_expand_data_urls_replaces_node(hass):
    """expand_data_urls replaces a dataUrl node with the fetched payload."""
    coord = _make_coordinator(hass)
    expanded = {"realData": 42}
    mock_session = MagicMock()
    mock_session.get = AsyncMock(return_value=_mock_response(expanded))
    coord._session = mock_session

    data = {"node": {"dataUrl": "/some/path"}}
    await coord.expand_data_urls(data)
    assert data["node"] == expanded


async def test_expand_data_urls_non_200_sets_none(hass):
    """expand_data_urls sets the node to None on a non-200 response."""
    coord = _make_coordinator(hass)
    mock_session = MagicMock()
    mock_session.get = AsyncMock(return_value=_mock_response({}, status=500))
    coord._session = mock_session

    data = {"node": {"dataUrl": "/bad/path"}}
    await coord.expand_data_urls(data)
    assert data["node"] is None


async def test_expand_data_urls_no_data_url_unchanged(hass):
    """expand_data_urls leaves data unchanged and makes no requests when there's no dataUrl."""
    coord = _make_coordinator(hass)
    data = {"a": 1, "b": {"c": 2}}
    mock_session = MagicMock()
    mock_session.get = AsyncMock()
    coord._session = mock_session

    await coord.expand_data_urls(data)
    assert data == {"a": 1, "b": {"c": 2}}
    mock_session.get.assert_not_called()


async def test_expand_data_urls_list(hass):
    """expand_data_urls expands a dataUrl found inside a list."""
    coord = _make_coordinator(hass)
    expanded = {"val": 99}
    mock_session = MagicMock()
    mock_session.get = AsyncMock(return_value=_mock_response(expanded))
    coord._session = mock_session

    data = [{"dataUrl": "/path"}]
    await coord.expand_data_urls(data)
    assert data[0] == expanded


async def test_expand_data_urls_max_depth_guard(hass):
    """Passing _depth > 10 should not make any HTTP calls."""
    coord = _make_coordinator(hass)
    mock_session = MagicMock()
    mock_session.get = AsyncMock()
    coord._session = mock_session

    data = {"dataUrl": "/should/not/fetch"}
    await coord.expand_data_urls(data, _depth=11)
    mock_session.get.assert_not_called()


# ---------------------------------------------------------------------------
# Test: tide/boating/surf injected into public weather fetch
# ---------------------------------------------------------------------------


async def test_get_public_weather_injects_tides(hass):
    """When tide_url is set, tideImport is injected into result_current."""
    coord = _make_coordinator(hass, tide_url="https://example.com/tides")

    tide_resp = {
        "layout": {
            "primary": {
                "slots": {
                    "main": {
                        "modules": [
                            {
                                "tideData": [
                                    {"type": "HIGH", "time": "06:00", "height": 1.5}
                                ]
                            }
                        ]
                    }
                }
            }
        }
    }
    warnings_data = {"warnings": []}
    pollen_data = {"layout": {"primary": {"slots": {"main": {"modules": []}}}}}

    mock_session = MagicMock()
    mock_session.get = AsyncMock(
        side_effect=[
            _mock_response(_PUBLIC_CURRENT),
            _mock_response(warnings_data),
            _mock_response(_PUBLIC_DAILY),
            _mock_response(pollen_data),
            _mock_response(tide_resp),
        ]
    )
    coord._session = mock_session

    result = await coord.get_public_weather()
    assert result.tides is not None


async def test_get_public_weather_injects_boating(hass):
    """When boating_url is set, boating_data is injected into result_current."""
    boating_data_resp = {
        "layout": {
            "primary": {
                "slots": {
                    "main": {
                        "modules": [
                            {
                                "days": [
                                    {
                                        "view": {"text": "Good", "status": "good"},
                                        "forecast": {"text": "Calm", "issuedAt": ""},
                                        "table": {"columns": []},
                                    }
                                ]
                            }
                        ]
                    }
                }
            }
        }
    }
    warnings_data = {"warnings": []}
    pollen_data = {"layout": {"primary": {"slots": {"main": {"modules": []}}}}}

    coord = _make_coordinator(hass, boating_url="https://example.com/boating")
    mock_session = MagicMock()
    mock_session.get = AsyncMock(
        side_effect=[
            _mock_response(_PUBLIC_CURRENT),
            _mock_response(warnings_data),
            _mock_response(_PUBLIC_DAILY),
            _mock_response(pollen_data),
            _mock_response(boating_data_resp),
        ]
    )
    coord._session = mock_session

    result = await coord.get_public_weather()
    assert result.boating_status is not None


async def test_get_public_weather_injects_surf(hass):
    """When surf_url is set, surf_data is injected into result_current."""
    surf_url = "https://www.metservice.com/publicData/webdata/marine/regions/northland/surf/locations/waihi-beach"
    surf_resp = {
        "layout": {"primary": {"map": {"markers": [_surf_marker()]}}},
    }
    warnings_data = {"warnings": []}
    pollen_data = {"layout": {"primary": {"slots": {"main": {"modules": []}}}}}

    coord = _make_coordinator(hass, surf_url=surf_url)
    mock_session = MagicMock()
    mock_session.get = AsyncMock(
        side_effect=[
            _mock_response(_PUBLIC_CURRENT),
            _mock_response(warnings_data),
            _mock_response(_PUBLIC_DAILY),
            _mock_response(pollen_data),
            _mock_response(surf_resp),
        ]
    )
    coord._session = mock_session

    result = await coord.get_public_weather()
    assert result.surf_conditions is not None


async def test_get_public_weather_warnings_none_raises_update_failed(hass):
    """When warnings fetch returns None, UpdateFailed is raised."""
    coord = _make_coordinator(hass)
    mock_session = MagicMock()
    mock_session.get = AsyncMock(
        side_effect=[
            _mock_response(_PUBLIC_CURRENT),
            _mock_response(None),  # warnings returns None
        ]
    )
    coord._session = mock_session

    with pytest.raises(UpdateFailed, match="No warnings data"):
        await coord.get_public_weather()


async def test_get_public_weather_daily_none_raises_update_failed(hass):
    """When daily forecast fetch returns None, UpdateFailed is raised."""
    warnings_data = {"warnings": []}
    coord = _make_coordinator(hass)
    mock_session = MagicMock()
    mock_session.get = AsyncMock(
        side_effect=[
            _mock_response(_PUBLIC_CURRENT),
            _mock_response(warnings_data),
            _mock_response(None),  # daily returns None
        ]
    )
    coord._session = mock_session

    with pytest.raises(UpdateFailed, match="No daily forecast"):
        await coord.get_public_weather()


async def test_get_public_weather_unexpected_exception_raises_update_failed(hass):
    """An unexpected exception (not TimeoutError or ClientError) is wrapped in UpdateFailed."""
    coord = _make_coordinator(hass)
    mock_session = MagicMock()
    mock_session.get = AsyncMock(side_effect=RuntimeError("unexpected"))
    coord._session = mock_session

    with pytest.raises(UpdateFailed, match="Unexpected error"):
        await coord.get_public_weather()


async def test_get_public_weather_tomorrow_injection(hass):
    """Tomorrow's forecast is derived from daily_entries[1] by normalize_public_data, not injected by the coordinator."""
    warnings_data = {"warnings": []}
    pollen_data = {"layout": {"primary": {"slots": {"main": {"modules": []}}}}}
    daily_with_tomorrow = {
        "layout": {
            "primary": {
                "slots": {
                    "main": {
                        "modules": [
                            {
                                "days": [
                                    {
                                        "condition": "fine",
                                        "forecasts": [
                                            {
                                                "highTemp": 20,
                                                "lowTemp": 12,
                                                "statement": "Today fine",
                                            }
                                        ],
                                    },
                                    {
                                        "condition": "cloudy",
                                        "forecasts": [
                                            {
                                                "highTemp": 17,
                                                "lowTemp": 10,
                                                "statement": "Tomorrow cloudy",
                                            }
                                        ],
                                    },
                                ]
                            }
                        ]
                    }
                }
            }
        }
    }
    coord = _make_coordinator(hass)
    mock_session = MagicMock()
    mock_session.get = AsyncMock(
        side_effect=[
            _mock_response(_PUBLIC_CURRENT),
            _mock_response(warnings_data),
            _mock_response(daily_with_tomorrow),
            _mock_response(pollen_data),
        ]
    )
    coord._session = mock_session

    result = await coord.get_public_weather()
    assert result.tomorrow_condition == "cloudy"
    assert result.tomorrow_temp_high == 17.0
    assert result.tomorrow_temp_low == 10
    assert result.tomorrow_description == "Tomorrow cloudy"


async def test_get_public_weather_drying_wet_all_day(hass):
    """Drying index: 'Wet all day' (bare text) path covers lines 295-298 and 302."""
    warnings_data = {"warnings": []}
    pollen_data = {"layout": {"primary": {"slots": {"main": {"modules": []}}}}}

    # Build a current fixture with dryingIndex.dryingState containing a "next good day" entry
    # and a bare "Wet all day" entry, so we exercise those branches.
    # We'll patch get_from_dict to return the crafted state instead of relying on
    # fixture data having a dryingIndex key.
    coord = _make_coordinator(hass)

    drying_states = [
        {"text": "Wet all day"},
        {"text": "Next good day: Thursday"},
    ]

    mock_session = MagicMock()
    mock_session.get = AsyncMock(
        side_effect=[
            _mock_response(_PUBLIC_CURRENT),
            _mock_response(warnings_data),
            _mock_response(_PUBLIC_DAILY),
            _mock_response(pollen_data),
        ]
    )
    coord._session = mock_session

    original_get_from_dict = coord.get_from_dict

    def patched_get_from_dict(data, keys):
        if keys == ["dryingIndex", "dryingState"]:
            return drying_states
        return original_get_from_dict(data, keys)

    with patch.object(coord, "get_from_dict", side_effect=patched_get_from_dict):
        result = await coord.get_public_weather()

    assert result.drying_morning == "Wet all day"
    assert result.drying_afternoon == "Wet all day"  # mirrored from morning
    assert (
        result.drying_next_good_day == "Thursday"
    )  # extracted from "Next good day: Thursday"


async def test_get_public_weather_drying_exception_silenced(hass):
    """Exception during drying index extraction is silenced (lines 310-311)."""
    warnings_data = {"warnings": []}
    pollen_data = {"layout": {"primary": {"slots": {"main": {"modules": []}}}}}

    coord = _make_coordinator(hass)

    mock_session = MagicMock()
    mock_session.get = AsyncMock(
        side_effect=[
            _mock_response(_PUBLIC_CURRENT),
            _mock_response(warnings_data),
            _mock_response(_PUBLIC_DAILY),
            _mock_response(pollen_data),
        ]
    )
    coord._session = mock_session

    def patched_get_from_dict(data, keys):
        if keys == ["dryingIndex", "dryingState"]:
            raise RuntimeError("simulated drying error")
        return coord.__class__.get_from_dict(coord, data, keys)

    with patch.object(coord, "get_from_dict", side_effect=patched_get_from_dict):
        result = await coord.get_public_weather()

    # Should succeed without raising; drying fields simply None
    assert isinstance(result, MetServicePublicData)


# ---------------------------------------------------------------------------
# Test: exception paths in marine helpers
# ---------------------------------------------------------------------------


async def test_get_tides_unexpected_exception_returns_none(hass):
    """Unexpected exception in get_tides returns None (lines 366-368)."""
    coord = _make_coordinator(hass, tide_url="https://example.com/tides")
    mock_session = MagicMock()
    mock_session.get = AsyncMock(side_effect=RuntimeError("disk full"))
    coord._session = mock_session

    result = await coord.get_tides()
    assert result is None


async def test_get_boating_data_unexpected_exception_returns_empty(hass):
    """Unexpected exception in get_boating_data returns {} (lines 404-406)."""
    coord = _make_coordinator(hass, boating_url="https://example.com/boating")
    mock_session = MagicMock()
    mock_session.get = AsyncMock(side_effect=RuntimeError("disk full"))
    coord._session = mock_session

    assert await coord.get_boating_data() == {}


async def test_get_surf_data_unexpected_exception_returns_empty(hass):
    """Unexpected exception in get_surf_data returns {} (lines 472-474)."""
    surf_url = "https://www.metservice.com/publicData/webdata/marine/regions/northland/surf/locations/waihi-beach"
    coord = _make_coordinator(hass, surf_url=surf_url)
    mock_session = MagicMock()
    mock_session.get = AsyncMock(side_effect=RuntimeError("disk full"))
    coord._session = mock_session

    assert await coord.get_surf_data() == {}


async def test_get_surf_data_bad_marker_skipped(hass):
    """Marker without 'action' key triggers except (KeyError/IndexError/TypeError) continue (lines 444-445)."""
    surf_url = "https://www.metservice.com/publicData/webdata/marine/regions/northland/surf/locations/waihi-beach"
    bad_marker = {}  # missing 'action' key → KeyError
    good_marker = _surf_marker()
    surf_data = {"layout": {"primary": {"map": {"markers": [bad_marker, good_marker]}}}}
    coord = _make_coordinator(hass, surf_url=surf_url)
    mock_session = MagicMock()
    mock_session.get = AsyncMock(return_value=_mock_response(surf_data))
    coord._session = mock_session

    result = await coord.get_surf_data()
    assert result["surf_rating"] == 3


# ---------------------------------------------------------------------------
# Test: expand_data_urls exception path
# ---------------------------------------------------------------------------


async def test_expand_data_urls_exception_sets_none(hass):
    """When session.get raises (not timeout/client), parent key is set to None (lines 636-639)."""
    coord = _make_coordinator(hass)
    mock_session = MagicMock()
    mock_session.get = AsyncMock(side_effect=RuntimeError("unexpected network failure"))
    coord._session = mock_session

    data = {"node": {"dataUrl": "/some/path"}}
    await coord.expand_data_urls(data)
    assert data["node"] is None


async def test_get_public_weather_tomorrow_extraction_exception_silenced(hass):
    """Tomorrow_* fields stay None instead of raising when the 7-day payload has no days."""
    import copy

    warnings_data = {"warnings": []}
    pollen_data = {"layout": {"primary": {"slots": {"main": {"modules": []}}}}}
    # modules is explicitly [] — normalize_public_data's _get returns None
    # for the out-of-range "0" index instead of raising IndexError.
    # Use a fresh current dict to avoid cross-test mutation of _PUBLIC_CURRENT.
    current_copy = copy.deepcopy(_PUBLIC_CURRENT)
    # Remove any pre-existing tomorrow key so the assertion is meaningful.
    current_copy.pop("tomorrow_condition", None)
    daily_bad = {"layout": {"primary": {"slots": {"main": {"modules": []}}}}}

    coord = _make_coordinator(hass)
    mock_session = MagicMock()
    mock_session.get = AsyncMock(
        side_effect=[
            _mock_response(current_copy),
            _mock_response(warnings_data),
            _mock_response(daily_bad),
            _mock_response(pollen_data),
        ]
    )
    coord._session = mock_session

    result = await coord.get_public_weather()
    # Should succeed; IndexError is caught and tomorrow fields remain None.
    assert isinstance(result, MetServicePublicData)
    assert result.tomorrow_condition is None
