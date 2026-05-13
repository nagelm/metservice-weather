"""Tests for coordinator_types: _get, normalizer, and dataclass structure."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from custom_components.metservice_weather.coordinator_types import (
    DailyEntry,
    HourlyEntry,
    MetServicePublicData,
    _get,
    _safe_float,
    _safe_int,
    normalize_public_data,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def napier():
    current = json.loads((FIXTURES / "napier_public_current.json").read_text())
    daily = json.loads((FIXTURES / "napier_public_daily.json").read_text())
    return normalize_public_data(current, daily)


# ---------------------------------------------------------------------------
# _get — exact-path traversal
# ---------------------------------------------------------------------------

def test_get_simple_dict():
    assert _get({"a": 1}, "a") == 1


def test_get_nested():
    assert _get({"a": {"b": 42}}, "a", "b") == 42


def test_get_list_index():
    assert _get(["x", "y", "z"], "1") == "y"


def test_get_mixed():
    data = {"items": [{"val": 10}, {"val": 20}]}
    assert _get(data, "items", "1", "val") == 20


def test_get_missing_key_returns_none():
    assert _get({"a": 1}, "b") is None


def test_get_out_of_range_returns_none():
    assert _get([1, 2], "5") is None


def test_get_none_data_returns_none():
    assert _get(None, "a") is None


def test_get_non_dict_non_list_returns_none():
    assert _get(42, "a") is None


def test_get_empty_path_returns_data():
    data = {"x": 1}
    assert _get(data) == data


def test_get_does_not_search_depth_first():
    # DFS would find "val" anywhere in the tree; exact-path must not.
    data = {"level1": {"other": {"val": 999}}, "val": 42}
    assert _get(data, "val") == 42          # top-level hit only
    assert _get(data, "level1", "val") is None  # "val" not a direct child of level1


# ---------------------------------------------------------------------------
# _safe_float / _safe_int
# ---------------------------------------------------------------------------

def test_safe_float_numeric():
    assert _safe_float("18.5") == 18.5
    assert _safe_float(18) == 18.0


def test_safe_float_invalid():
    assert _safe_float(None) is None
    assert _safe_float("n/a") is None


def test_safe_int_numeric():
    assert _safe_int("5") == 5
    assert _safe_int(5.9) == 5


def test_safe_int_invalid():
    assert _safe_int(None) is None
    assert _safe_int("bad") is None


# ---------------------------------------------------------------------------
# normalize_public_data — against Napier fixture
# ---------------------------------------------------------------------------

def test_returns_correct_type(napier):
    assert isinstance(napier, MetServicePublicData)


def test_temperature_is_float(napier):
    assert isinstance(napier.temperature, float)
    assert -20 <= napier.temperature <= 50


def test_humidity_is_int(napier):
    assert isinstance(napier.humidity, int)
    assert 0 <= napier.humidity <= 100


def test_wind_direction_is_string(napier):
    assert isinstance(napier.wind_direction, str)


def test_condition_is_string(napier):
    assert isinstance(napier.condition, str)


def test_weather_warnings_is_string(napier):
    assert isinstance(napier.weather_warnings, str)


def test_pollen_level_present(napier):
    assert napier.pollen_level is not None


def test_tomorrow_fields_present(napier):
    assert napier.tomorrow_condition is not None
    assert napier.tomorrow_temp_high is not None


def test_hourly_entries_is_list(napier):
    assert isinstance(napier.hourly_entries, list)
    assert len(napier.hourly_entries) > 0
    assert isinstance(napier.hourly_entries[0], HourlyEntry)


def test_daily_entries_is_list(napier):
    assert isinstance(napier.daily_entries, list)
    assert 1 <= len(napier.daily_entries) <= 14
    assert isinstance(napier.daily_entries[0], DailyEntry)


def test_all_daily_entries_have_condition(napier):
    missing = [i for i, d in enumerate(napier.daily_entries) if d.condition is None]
    assert not missing, f"Days missing condition: {missing}"


def test_all_daily_entries_have_temp_high(napier):
    missing = [i for i, d in enumerate(napier.daily_entries) if d.temp_high is None]
    assert not missing, f"Days missing temp_high: {missing}"


def test_sunrise_is_string(napier):
    assert isinstance(napier.sunrise, str)


def test_moon_phase_is_string(napier):
    assert isinstance(napier.moon_phase, str)


# ---------------------------------------------------------------------------
# normalize_public_data — marine field extraction
# ---------------------------------------------------------------------------

def test_marine_fields_none_when_absent():
    """With no marine data injected, all marine fields are None."""
    result = normalize_public_data(
        {"weather_warnings": "No warnings", "hourly_entries": [], "daily_entries": []},
        {},
    )
    assert result.tides is None
    assert result.boating_forecast is None
    assert result.surf_conditions is None


def test_tides_extracted_from_tide_import():
    tides = [{"type": "HIGH", "time": "06:30", "height": 1.8}]
    current = {
        "weather_warnings": "No warnings",
        "tideImport": tides,
    }
    result = normalize_public_data(current, {})
    assert result.tides == tides


def test_boating_extracted_from_boating_data():
    current = {
        "weather_warnings": "No warnings",
        "boating_data": {
            "boating_status": "Good",
            "boating_forecast": "Calm seas",
            "boating_table": [],
        },
    }
    result = normalize_public_data(current, {})
    assert result.boating_status == "Good"
    assert result.boating_forecast == "Calm seas"


def test_surf_extracted_from_surf_data():
    current = {
        "weather_warnings": "No warnings",
        "surf_data": {
            "surf_conditions": "Fair",
            "surf_rating": 3,
            "surf_wave_height": 1.2,
        },
    }
    result = normalize_public_data(current, {})
    assert result.surf_conditions == "Fair"
    assert result.surf_rating == 3


# ---------------------------------------------------------------------------
# normalize_public_data — edge cases
# ---------------------------------------------------------------------------

def test_empty_dicts_returns_defaults():
    """normalize_public_data must not raise on completely empty input."""
    result = normalize_public_data({}, {})
    assert result.temperature is None
    assert result.daily_entries == []
    assert result.hourly_entries == []
    assert result.weather_warnings == "No warnings"
