"""Tests for async_setup_entry and async_unload_entry in __init__.py."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.metservice_weather import (
    _async_migrate_legacy_unique_ids,
    async_migrate_entry,
)
from custom_components.metservice_weather.const import DOMAIN
from custom_components.metservice_weather.coordinator import WeatherUpdateCoordinator
from custom_components.metservice_weather.coordinator_types import (
    normalize_public_data,
)


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


async def test_setup_links_marine_device_under_location_device(hass):
    """Setup registers the location device and links the marine one to it by id."""
    marine_base = "https://www.metservice.com/publicData/webdata/marine/regions"
    entry = _make_entry(
        {
            **_PUBLIC_ENTRY_DATA,
            "marine_region": "marine/regions/kapiti-wellington",
            "tide_url": f"{marine_base}/kapiti-wellington/tides/locations/wellington",
            "boating_url": f"{marine_base}/kapiti-wellington/boating/locations/wellington",
            "surf_url": f"{marine_base}/kapiti-wellington/surf/locations/lyall-bay",
        }
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.metservice_weather.WeatherUpdateCoordinator.async_config_entry_first_refresh",
        new_callable=AsyncMock,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id) is True
        await hass.async_block_till_done()

    coordinator = entry.runtime_data
    dev_reg = dr.async_get(hass)

    location_device = dev_reg.async_get_device_by_identifier(
        (DOMAIN, coordinator.location), entry.entry_id
    )
    assert location_device is not None
    assert location_device.id == coordinator.location_device_id
    assert location_device.name == "Napier"

    marine_device = dev_reg.async_get_device_by_identifier(
        (DOMAIN, f"{coordinator.location}_marine"), entry.entry_id
    )
    assert marine_device is not None
    assert marine_device.id != location_device.id
    assert marine_device.via_device_id == location_device.id


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
    assert entry.runtime_data.config_entry is entry


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


async def test_bare_slug_location_entry_creates_legacy_entry_issue(hass):
    """A pre-v1.0 bare-slug location gets a legacy_entry issue."""
    entry = _make_entry({**_PUBLIC_ENTRY_DATA, "location": "dargaville"})
    entry.add_to_hass(hass)

    with patch(
        "custom_components.metservice_weather.WeatherUpdateCoordinator.async_config_entry_first_refresh",
        new_callable=AsyncMock,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert ir.async_get(hass).async_get_issue(DOMAIN, _legacy_issue_id(entry))


@pytest.mark.parametrize(
    "location",
    ["/towns-cities/regions/auckland/locations/makarau", "/rural/regions/nelson"],
)
async def test_location_path_raises_no_legacy_entry_issue(hass, location):
    """Public location paths, including Golden Bay's region page, are not flagged."""
    entry = _make_entry({**_PUBLIC_ENTRY_DATA, "location": location})
    entry.add_to_hass(hass)

    with patch(
        "custom_components.metservice_weather.WeatherUpdateCoordinator.async_config_entry_first_refresh",
        new_callable=AsyncMock,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert ir.async_get(hass).async_get_issue(DOMAIN, _legacy_issue_id(entry)) is None


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


_NEW_PREFIX = f"{_PUBLIC_ENTRY_DATA['location']}_"
_FIXTURES = Path(__file__).parent / "fixtures"


def _napier_data():
    return normalize_public_data(
        json.loads((_FIXTURES / "napier_public_current.json").read_text()),
        json.loads((_FIXTURES / "napier_public_daily.json").read_text()),
    )


async def test_v09_entities_keep_their_entity_ids_through_setup(hass):
    """Entities registered by v0.9 ("<name>,<key>") survive setup on their old entity IDs, re-keyed in place."""
    entry = _make_entry({**_PUBLIC_ENTRY_DATA, "name": "Home"})
    entry.add_to_hass(hass)
    ent_reg = er.async_get(hass)
    temp = ent_reg.async_get_or_create(
        "sensor",
        DOMAIN,
        "home,temperature",
        config_entry=entry,
        suggested_object_id="home_temperature",
    )
    weather = ent_reg.async_get_or_create(
        "weather",
        DOMAIN,
        "home,weather",
        config_entry=entry,
        suggested_object_id="home",
    )
    data = _napier_data()

    async def _first_refresh(coordinator):
        coordinator.data = data

    with patch.object(
        WeatherUpdateCoordinator,
        "async_config_entry_first_refresh",
        autospec=True,
        side_effect=_first_refresh,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert ent_reg.async_get(temp.entity_id).unique_id == f"{_NEW_PREFIX}temperature"
    assert ent_reg.async_get(weather.entity_id).unique_id == f"{_NEW_PREFIX}weather"
    assert hass.states.get(temp.entity_id) is not None
    assert hass.states.get(weather.entity_id) is not None
    assert hass.states.get("sensor.napier_temperature") is None


async def test_v09_unique_ids_are_rekeyed(hass):
    """Sensor and weather entries in the v0.9 format move to "<location>_<key>"; others are untouched."""
    entry = _make_entry({**_PUBLIC_ENTRY_DATA, "name": "Home"})
    entry.add_to_hass(hass)
    ent_reg = er.async_get(hass)
    temp = ent_reg.async_get_or_create(
        "sensor", DOMAIN, "home,temperature", config_entry=entry
    )
    weather = ent_reg.async_get_or_create(
        "weather", DOMAIN, "home,weather", config_entry=entry
    )
    current = ent_reg.async_get_or_create(
        "sensor", DOMAIN, f"{_NEW_PREFIX}humidity", config_entry=entry
    )

    await _async_migrate_legacy_unique_ids(hass, entry)

    assert ent_reg.async_get(temp.entity_id).unique_id == f"{_NEW_PREFIX}temperature"
    assert ent_reg.async_get(weather.entity_id).unique_id == f"{_NEW_PREFIX}weather"
    assert ent_reg.async_get(current.entity_id).unique_id == f"{_NEW_PREFIX}humidity"


async def test_v09_unique_id_left_alone_when_target_already_registered(hass):
    """Someone who already crossed v1.0.0 has both entries; the old one is not re-keyed onto the new one."""
    entry = _make_entry({**_PUBLIC_ENTRY_DATA, "name": "Home"})
    entry.add_to_hass(hass)
    ent_reg = er.async_get(hass)
    old = ent_reg.async_get_or_create(
        "sensor", DOMAIN, "home,temperature", config_entry=entry
    )
    new = ent_reg.async_get_or_create(
        "sensor", DOMAIN, f"{_NEW_PREFIX}temperature", config_entry=entry
    )

    await _async_migrate_legacy_unique_ids(hass, entry)

    assert ent_reg.async_get(old.entity_id).unique_id == "home,temperature"
    assert ent_reg.async_get(new.entity_id).unique_id == f"{_NEW_PREFIX}temperature"


async def test_v09_migration_skips_unknown_location_entries(hass):
    """An entry without a current public location (e.g. mobile API) is not re-keyed."""
    entry = _make_entry(
        {**_PUBLIC_ENTRY_DATA, "name": "Home", "location": "/mobile/old/path"}
    )
    entry.add_to_hass(hass)
    ent_reg = er.async_get(hass)
    old = ent_reg.async_get_or_create(
        "sensor", DOMAIN, "home,temperature", config_entry=entry
    )

    await _async_migrate_legacy_unique_ids(hass, entry)

    assert ent_reg.async_get(old.entity_id).unique_id == "home,temperature"


async def test_v09_migration_exception_does_not_block_setup(hass):
    """A failure inside the unique_id migration is swallowed and never blocks setup."""
    entry = _make_entry(_PUBLIC_ENTRY_DATA)
    entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.metservice_weather.er.async_migrate_entries",
            side_effect=RuntimeError("boom"),
        ),
        patch(
            "custom_components.metservice_weather.WeatherUpdateCoordinator.async_config_entry_first_refresh",
            new_callable=AsyncMock,
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED


async def test_migration_1_1_to_1_2_drops_legacy_keys(hass):
    """The one-time migration removes keys v0.9 entries stored and bumps the minor version."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        minor_version=1,
        data={
            **_PUBLIC_ENTRY_DATA,
            "api_key": "a",
            "mobile_api_key": "b",
            "enable_tides": False,
            "tide_region_url": "x",
            "boating_region": "y",
        },
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry)

    assert entry.minor_version == 2
    assert dict(entry.data) == _PUBLIC_ENTRY_DATA


async def test_migration_rekeys_v09_rows_once(hass):
    """The v0.9 re-key runs in the migration; a migrated entry isn't re-keyed at setup."""
    entry = MockConfigEntry(
        domain=DOMAIN, version=1, minor_version=1, data=_PUBLIC_ENTRY_DATA
    )
    entry.add_to_hass(hass)
    ent_reg = er.async_get(hass)
    row = ent_reg.async_get_or_create(
        "sensor", DOMAIN, "Napier,temperature", config_entry=entry
    )

    assert await async_migrate_entry(hass, entry)

    assert (
        ent_reg.async_get(row.entity_id).unique_id
        == f"{_PUBLIC_ENTRY_DATA['location']}_temperature"
    )
    assert entry.minor_version == 2


async def test_migration_leaves_mobile_entry_without_location_at_1_1(hass):
    """A v0.9 mobile entry has no location path yet, so it waits for Reconfigure."""
    data = {"name": "Home", "api": "mobile", "api_key": "k"}
    entry = MockConfigEntry(domain=DOMAIN, version=1, minor_version=1, data=data)
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry)

    assert entry.minor_version == 1
    assert dict(entry.data) == data


async def test_migration_refuses_newer_major_version(hass):
    """An entry written by a newer major version is refused."""
    entry = MockConfigEntry(
        domain=DOMAIN, version=2, minor_version=1, data=_PUBLIC_ENTRY_DATA
    )
    entry.add_to_hass(hass)

    assert not await async_migrate_entry(hass, entry)


async def test_setup_migrates_an_old_entry_before_loading(hass):
    """Setting up a 1.1 entry runs the migration and loads it at 1.2."""
    entry = MockConfigEntry(
        domain=DOMAIN, version=1, minor_version=1, data=_PUBLIC_ENTRY_DATA
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.metservice_weather.WeatherUpdateCoordinator.async_config_entry_first_refresh",
        new_callable=AsyncMock,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.minor_version == 2


async def test_setup_removes_devices_left_without_entities(hass):
    """A device from an old location or turned-off marine data, with no entities left, is removed."""
    entry = _make_entry(_PUBLIC_ENTRY_DATA)
    entry.add_to_hass(hass)
    dev_reg = dr.async_get(hass)
    old_location = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "/towns-cities/regions/auckland/locations/makarau")},
        name="Makarau",
    )
    old_marine = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, f"{_PUBLIC_ENTRY_DATA['location']}_marine")},
        name="Hawke's Bay",
    )

    with patch(
        "custom_components.metservice_weather.WeatherUpdateCoordinator.async_config_entry_first_refresh",
        new_callable=AsyncMock,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert dev_reg.async_get(old_location.id) is None
    assert dev_reg.async_get(old_marine.id) is None
    location_device = dev_reg.async_get_device_by_identifier(
        (DOMAIN, entry.runtime_data.location), entry.entry_id
    )
    assert location_device is not None


async def test_setup_keeps_a_device_whose_entities_are_disabled(hass):
    """A device whose only entities are disabled still has entities, so it stays."""
    entry = _make_entry(_PUBLIC_ENTRY_DATA)
    entry.add_to_hass(hass)
    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "/towns-cities/regions/auckland/locations/makarau")},
        name="Makarau",
    )
    ent_reg.async_get_or_create(
        "sensor",
        "other_domain",
        "kept",
        device_id=device.id,
        disabled_by=er.RegistryEntryDisabler.USER,
    )

    with patch(
        "custom_components.metservice_weather.WeatherUpdateCoordinator.async_config_entry_first_refresh",
        new_callable=AsyncMock,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert dev_reg.async_get(device.id) is not None
