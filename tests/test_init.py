"""Tests for async_setup_entry and async_unload_entry in __init__.py."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.metservice_weather.const import DOMAIN


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_PUBLIC_ENTRY_DATA = {
    "name": "Napier",
    "location": "/towns-cities/regions/hawkes-bay/locations/napier",
    "api": "public",
    "marine_region": "",
    "tide_url": "",
    "boating_url": "",
    "surf_url": "",
    "latitude": "-39.49",
    "longitude": "176.91",
}

_MOBILE_ENTRY_DATA = {
    "name": "Auckland",
    "location": "Auckland",
    "api": "mobile",
    "mobile_api_key": "test-key",
    "marine_region": "",
    "tide_url": "",
    "boating_url": "",
    "surf_url": "",
    "latitude": "-36.84",
    "longitude": "174.76",
}


def _make_entry(data: dict) -> MockConfigEntry:
    return MockConfigEntry(domain=DOMAIN, data=data)


# ---------------------------------------------------------------------------
# Test: async_setup_entry and async_unload_entry (public API)
# ---------------------------------------------------------------------------

async def test_setup_and_unload_public(hass):
    """Entry sets up correctly and unloads cleanly for the public API path."""
    entry = _make_entry(_PUBLIC_ENTRY_DATA)
    entry.add_to_hass(hass)

    with patch(
        "custom_components.metservice_weather.WeatherUpdateCoordinator.async_config_entry_first_refresh",
        new_callable=AsyncMock,
    ):
        result = await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert result is True
    assert entry.state is ConfigEntryState.LOADED

    unload_result = await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert unload_result is True
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_and_unload_mobile(hass):
    """Entry sets up correctly and unloads cleanly for the mobile API path."""
    entry = _make_entry(_MOBILE_ENTRY_DATA)
    entry.add_to_hass(hass)

    with patch(
        "custom_components.metservice_weather.WeatherUpdateCoordinator.async_config_entry_first_refresh",
        new_callable=AsyncMock,
    ):
        result = await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert result is True
    assert entry.state is ConfigEntryState.LOADED

    unload_result = await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert unload_result is True
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_unload_returns_true_when_platforms_unload(hass):
    """async_unload_entry returns True when all platforms unload successfully."""
    from custom_components.metservice_weather import async_unload_entry

    entry = _make_entry(_PUBLIC_ENTRY_DATA)
    entry.add_to_hass(hass)

    with patch(
        "custom_components.metservice_weather.WeatherUpdateCoordinator.async_config_entry_first_refresh",
        new_callable=AsyncMock,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    result = await async_unload_entry(hass, entry)
    assert result is True


async def test_setup_first_refresh_failure_raises(hass):
    """If first refresh fails, async_setup_entry raises ConfigEntryNotReady."""
    from homeassistant.exceptions import ConfigEntryNotReady

    entry = _make_entry(_PUBLIC_ENTRY_DATA)
    entry.add_to_hass(hass)

    with patch(
        "custom_components.metservice_weather.WeatherUpdateCoordinator.async_config_entry_first_refresh",
        side_effect=ConfigEntryNotReady("connection failed"),
    ):
        result = await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert result is False
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_runtime_data_set_after_setup(hass):
    """Coordinator is accessible via entry.runtime_data after setup."""
    from custom_components.metservice_weather.coordinator import WeatherUpdateCoordinator

    entry = _make_entry(_PUBLIC_ENTRY_DATA)
    entry.add_to_hass(hass)

    with patch(
        "custom_components.metservice_weather.WeatherUpdateCoordinator.async_config_entry_first_refresh",
        new_callable=AsyncMock,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert isinstance(entry.runtime_data, WeatherUpdateCoordinator)
