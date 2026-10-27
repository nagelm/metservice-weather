"""Tests for MetService diagnostics."""

from unittest.mock import MagicMock

from custom_components.metservice_weather.diagnostics import (
    async_get_config_entry_diagnostics,
)

LOCATION = "/towns-cities/regions/hawkes-bay/locations/napier"


async def test_diagnostics_redact_legacy_api_keys(hass):
    """Legacy v0.9 API keys never appear in diagnostics."""
    entry = MagicMock()
    entry.data = {"location": LOCATION, "api_key": "a", "mobile_api_key": "b"}
    entry.runtime_data.data = None

    result = await async_get_config_entry_diagnostics(hass, entry)

    data = result["config_entry_data"]
    assert data["api_key"] == "**REDACTED**"
    assert data["mobile_api_key"] == "**REDACTED**"
    assert data["location"] == LOCATION
    assert result["coordinator_data"] is None
