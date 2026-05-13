"""Shared test fixtures for metservice_weather tests."""
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

MOCK_MARINE_RESPONSE = {
    "layout": {
        "search": {
            "searchLocations": [{"items": [
                {"heading": {"label": "Northland", "url": "/marine/regions/northland"}}
            ]}]
        }
    }
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations defined in the tests directory."""
    yield


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
        "custom_components.metservice_weather.config_flow.async_create_clientsession",
        return_value=session_mock,
    ):
        yield session_mock, marine_resp
