"""Shared test fixtures for metservice_weather tests."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from custom_components.metservice_weather.coordinator import (
    WeatherUpdateCoordinator,
    WeatherUpdateCoordinatorConfig,
)
from custom_components.metservice_weather.coordinator_types import MetServicePublicData

MOCK_MARINE_RESPONSE = {
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


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations defined in the tests directory."""
    yield


MOCK_LOCATIONS = [
    {"label": "Napier", "value": "/towns-cities/regions/hawkes-bay/locations/napier"},
    {
        "label": "Whangārei",
        "value": "/towns-cities/regions/northland/locations/whangarei",
    },
]


@pytest.fixture(autouse=True)
def mock_location_index():
    """Serve a fixed location index to the config flow."""
    with patch(
        "custom_components.metservice_weather.config_flow.async_fetch_locations",
        AsyncMock(return_value=MOCK_LOCATIONS),
    ) as mock:
        yield mock


@pytest.fixture
def mock_coordinator_refresh():
    """Patch coordinator first refresh to avoid real network calls during setup."""
    with patch(
        "custom_components.metservice_weather.coordinator.WeatherUpdateCoordinator.async_config_entry_first_refresh",
        return_value=None,
    ):
        yield


@pytest.fixture
def mock_marine_session(mock_coordinator_refresh):
    """Mock aiohttp session returning marine regions; also patches coordinator refresh."""
    marine_resp = AsyncMock()
    marine_resp.json = AsyncMock(return_value=MOCK_MARINE_RESPONSE)
    marine_resp.status = 200

    session_mock = MagicMock()
    session_mock.get = AsyncMock(return_value=marine_resp)
    session_mock.__aenter__ = AsyncMock(return_value=session_mock)
    session_mock.__aexit__ = AsyncMock(return_value=None)

    with patch(
        "custom_components.metservice_weather.config_flow.async_get_clientsession",
        return_value=session_mock,
    ):
        yield session_mock, marine_resp


NAPIER_LOCATION = "/towns-cities/regions/hawkes-bay/locations/napier"


def make_coordinator(
    hass, *, tide_url="", boating_url="", surf_url="", with_data=True
) -> WeatherUpdateCoordinator:
    """Build a Napier coordinator without network access.

    with_data seeds an empty MetServicePublicData, as most entity tests need.
    """
    config = WeatherUpdateCoordinatorConfig(
        api_url="https://www.metservice.com/publicData/webdata",
        warnings_url="https://www.metservice.com/publicData/webdata/warnings-service",
        unit_system="metric",
        location=NAPIER_LOCATION,
        location_name="Napier",
        tide_url=tide_url,
        boating_url=boating_url,
        surf_url=surf_url,
    )
    coord = WeatherUpdateCoordinator(hass, config, None)
    if with_data:
        coord.data = MetServicePublicData()
    return coord
