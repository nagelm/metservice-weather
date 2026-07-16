"""Tests for async_setup_entry and async_unload_entry in __init__.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import issue_registry as ir
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
    from custom_components.metservice_weather.coordinator import (
        WeatherUpdateCoordinator,
    )

    entry = _make_entry(_PUBLIC_ENTRY_DATA)
    entry.add_to_hass(hass)

    with patch(
        "custom_components.metservice_weather.WeatherUpdateCoordinator.async_config_entry_first_refresh",
        new_callable=AsyncMock,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert isinstance(entry.runtime_data, WeatherUpdateCoordinator)


# ---------------------------------------------------------------------------
# Test: _check_legacy_entry (detector 2 — legacy mobile-API / unknown-location entry)
# ---------------------------------------------------------------------------


def _legacy_issue_id(entry: MockConfigEntry) -> str:
    return f"legacy_entry_{entry.entry_id}"


async def test_mobile_api_entry_creates_legacy_entry_issue(hass):
    """An entry still using the removed mobile API gets an ERROR-severity, non-fixable legacy_entry issue."""
    entry = _make_entry({**_PUBLIC_ENTRY_DATA, "api": "mobile"})
    entry.add_to_hass(hass)

    with patch(
        "custom_components.metservice_weather.WeatherUpdateCoordinator.async_config_entry_first_refresh",
        new_callable=AsyncMock,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    issue = ir.async_get(hass).async_get_issue(DOMAIN, _legacy_issue_id(entry))
    assert issue is not None
    assert issue.severity == ir.IssueSeverity.ERROR
    assert issue.is_fixable is False
    assert "mobile" in issue.translation_placeholders["reason"]


async def test_unknown_location_entry_creates_legacy_entry_issue(hass):
    """An entry whose location no longer matches a current public location value gets a legacy_entry issue."""
    entry = _make_entry(
        {**_PUBLIC_ENTRY_DATA, "location": "/mobile/some/old/location/path"}
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.metservice_weather.WeatherUpdateCoordinator.async_config_entry_first_refresh",
        new_callable=AsyncMock,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    issue = ir.async_get(hass).async_get_issue(DOMAIN, _legacy_issue_id(entry))
    assert issue is not None
    assert issue.severity == ir.IssueSeverity.ERROR
    assert "unrecognised location" in issue.translation_placeholders["reason"]


async def test_self_corrected_user_valid_entry_stays_silent_and_clears_pre_existing_issue(
    hass,
):
    """A valid public-API entry never gets a legacy_entry issue, and a stale one from before reconfiguring is cleared."""
    entry = _make_entry(_PUBLIC_ENTRY_DATA)
    entry.add_to_hass(hass)

    issue_id = _legacy_issue_id(entry)
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key="legacy_entry",
    )
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None

    with patch(
        "custom_components.metservice_weather.WeatherUpdateCoordinator.async_config_entry_first_refresh",
        new_callable=AsyncMock,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_legacy_entry_check_exception_does_not_block_setup(hass):
    """A failure inside the legacy-entry check is swallowed and never blocks the rest of setup."""
    entry = _make_entry(_PUBLIC_ENTRY_DATA)
    entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.metservice_weather.ir.async_delete_issue",
            side_effect=RuntimeError("boom"),
        ),
        patch(
            "custom_components.metservice_weather.WeatherUpdateCoordinator.async_config_entry_first_refresh",
            new_callable=AsyncMock,
        ),
    ):
        result = await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert result is True
    assert entry.state is ConfigEntryState.LOADED
