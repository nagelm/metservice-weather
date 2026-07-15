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
    _scan_forecasts,
    normalize_public_data,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def napier():
    current = json.loads((FIXTURES / "napier_public_current.json").read_text())
    daily = json.loads((FIXTURES / "napier_public_daily.json").read_text())
    return normalize_public_data(current, daily)


@pytest.fixture(scope="module")
def kumeu():
    current = json.loads((FIXTURES / "kumeu_public_current.json").read_text())
    daily = json.loads((FIXTURES / "kumeu_public_daily.json").read_text())
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


# ---------------------------------------------------------------------------
# _scan_forecasts — forecast entry scanning
# ---------------------------------------------------------------------------

def test_scan_forecasts_towns_shape_prefers_forecasts_entry():
    day = {"forecasts": [{"highTemp": 16}], "highTemp": 15}
    assert _scan_forecasts(day, "highTemp") == 16


def test_scan_forecasts_rural_shape_finds_second_entry():
    day = {
        "forecasts": [
            {"statement": "regional", "title": "Region"},
            {"highTemp": 17, "statement": None},
        ],
        "highTemp": 17,
    }
    assert _scan_forecasts(day, "highTemp") == 17
    assert _scan_forecasts(day, "statement") == "regional"


def test_scan_forecasts_day_level_only():
    day = {"highTemp": 12}
    assert _scan_forecasts(day, "highTemp") == 12


def test_scan_forecasts_none_in_forecasts_falls_through_to_day_level():
    day = {"forecasts": [{"highTemp": None}], "highTemp": 9}
    assert _scan_forecasts(day, "highTemp") == 9


def test_scan_forecasts_absent_everywhere_returns_none():
    assert _scan_forecasts({}, "highTemp") is None


def test_scan_forecasts_non_dict_day_returns_none():
    assert _scan_forecasts(None, "highTemp") is None
    assert _scan_forecasts(42, "highTemp") is None


def test_scan_forecasts_non_dict_forecast_entries_skipped():
    day = {"forecasts": ["junk", {"highTemp": 5}]}
    assert _scan_forecasts(day, "highTemp") == 5


# ---------------------------------------------------------------------------
# daily entry shape heuristics
# ---------------------------------------------------------------------------

def _daily_payload(days):
    return {"layout": {"primary": {"slots": {"main": {"modules": [{"days": days}]}}}}}


def test_daily_entry_towns_shape():
    day = {
        "date": "2024-06-15",
        "condition": "fine",
        "forecasts": [
            {"highTemp": 22, "lowTemp": 12, "statement": "Sunny day", "rainFall1": 30.0, "rainFall10": 5.0}
        ],
        "highTemp": 22,
        "lowTemp": 12,
        "statement": "Sunny day",
    }
    result = normalize_public_data({}, _daily_payload([day]))
    entry = result.daily_entries[0]
    assert entry.temp_high == 22.0 and isinstance(entry.temp_high, float)
    assert entry.temp_low == 12.0 and isinstance(entry.temp_low, float)
    assert entry.description == "Sunny day"
    assert entry.rain_prob_1mm == 30.0
    assert entry.rain_prob_10mm == 5.0


def test_daily_entry_rural_shape():
    day = {
        "date": "2024-06-15",
        "condition": "cloudy",
        "forecasts": [
            {"statement": "Regional cloudy", "title": "Region"},
            {"highTemp": 18, "lowTemp": 9, "rainFall1": 40.0, "rainFall10": 10.0, "statement": None},
        ],
        "highTemp": 18,
        "lowTemp": 9,
        "statement": "Regional cloudy",
    }
    result = normalize_public_data({}, _daily_payload([day]))
    entry = result.daily_entries[0]
    assert entry.temp_high == 18.0
    assert entry.temp_low == 9.0
    assert entry.description == "Regional cloudy"
    assert entry.rain_prob_1mm == 40.0
    assert entry.rain_prob_10mm == 10.0


def test_daily_entry_day_level_only():
    day = {"date": "2024-06-15", "condition": "fine", "highTemp": 20, "lowTemp": 10, "statement": "Fine day"}
    result = normalize_public_data({}, _daily_payload([day]))
    entry = result.daily_entries[0]
    assert entry.temp_high == 20.0
    assert entry.temp_low == 10.0
    assert entry.description == "Fine day"


def test_daily_entry_empty_day():
    result = normalize_public_data({}, _daily_payload([{}]))
    entry = result.daily_entries[0]
    assert entry.datetime is None
    assert entry.condition is None
    assert entry.temp_high is None
    assert entry.temp_low is None
    assert entry.description is None
    assert entry.rain_prob_1mm is None
    assert entry.rain_prob_10mm is None


def test_daily_entry_rain_fields_absent_is_none_not_zero():
    day = {"highTemp": 15, "lowTemp": 8, "statement": "no rain data"}
    result = normalize_public_data({}, _daily_payload([day]))
    entry = result.daily_entries[0]
    assert entry.rain_prob_1mm is None
    assert entry.rain_prob_10mm is None


def test_daily_entry_string_temps_coerced_to_float():
    day = {"forecasts": [{"highTemp": "16"}]}
    result = normalize_public_data({}, _daily_payload([day]))
    entry = result.daily_entries[0]
    assert entry.temp_high == 16.0
    assert isinstance(entry.temp_high, float)


# ---------------------------------------------------------------------------
# tomorrow derivation
# ---------------------------------------------------------------------------

def test_tomorrow_derived_from_day_index_1():
    days = [
        {"condition": "fine", "forecasts": [{"highTemp": 20, "lowTemp": 12, "statement": "Today fine"}]},
        {"condition": "cloudy", "forecasts": [{"highTemp": 17, "lowTemp": 10, "statement": "Tomorrow cloudy"}]},
    ]
    result = normalize_public_data({}, _daily_payload(days))
    assert result.tomorrow_condition == "cloudy"
    assert result.tomorrow_temp_high == 17.0 and isinstance(result.tomorrow_temp_high, float)
    assert result.tomorrow_temp_low == 10.0 and isinstance(result.tomorrow_temp_low, float)
    assert result.tomorrow_description == "Tomorrow cloudy"


def test_tomorrow_none_with_only_one_day():
    days = [{"condition": "fine", "forecasts": [{"highTemp": 20, "lowTemp": 12, "statement": "Today fine"}]}]
    result = normalize_public_data({}, _daily_payload(days))
    assert result.tomorrow_condition is None
    assert result.tomorrow_temp_high is None
    assert result.tomorrow_temp_low is None
    assert result.tomorrow_description is None


def test_tomorrow_none_with_empty_daily_dict():
    result = normalize_public_data({}, {})
    assert result.tomorrow_condition is None
    assert result.tomorrow_temp_high is None
    assert result.tomorrow_temp_low is None
    assert result.tomorrow_description is None


# ---------------------------------------------------------------------------
# today's high/low fallback
# ---------------------------------------------------------------------------

def _current_payload(obs=None, days=None):
    left = [{"observations": obs}] if obs is not None else []
    main = [{"days": days}] if days is not None else []
    return {"layout": {"primary": {"slots": {
        "left-major": {"modules": left},
        "main": {"modules": main},
    }}}}


def test_today_high_low_prefers_observations():
    obs = {"temperature": [{"high": 25.0, "low": 15.0, "current": 20.0}]}
    days = [{"highTemp": 30, "lowTemp": 10}]
    result = normalize_public_data(_current_payload(obs=obs, days=days), {})
    assert result.temp_today_high == 25.0
    assert result.temp_today_low == 15.0


def test_today_high_low_falls_back_to_day_level_when_no_observations():
    """The rural fix: no weather station, so fall back to day 0's forecast temps."""
    days = [{"highTemp": 18, "lowTemp": 8}]
    result = normalize_public_data(_current_payload(days=days), {})
    assert result.temp_today_high == 18.0
    assert result.temp_today_low == 8.0


def test_today_high_low_falls_back_to_forecasts_entry_rural_shape():
    days = [{"forecasts": [{"statement": "regional"}, {"highTemp": 16, "lowTemp": 6}]}]
    result = normalize_public_data(_current_payload(days=days), {})
    assert result.temp_today_high == 16.0
    assert result.temp_today_low == 6.0


def test_today_high_low_none_when_both_absent():
    result = normalize_public_data(_current_payload(), {})
    assert result.temp_today_high is None
    assert result.temp_today_low is None


# ---------------------------------------------------------------------------
# capability flags
# ---------------------------------------------------------------------------

def test_capability_flags_napier(napier):
    assert napier.has_observations is True
    assert napier.has_breakdown is True
    assert napier.is_rural is False


def test_capability_flags_kumeu(kumeu):
    assert kumeu.has_observations is False
    assert kumeu.has_breakdown is False
    assert kumeu.is_rural is True


def test_has_observations_false_when_module_value_is_none():
    current = {"layout": {"primary": {"slots": {"left-major": {"modules": [{"observations": None}]}}}}}
    result = normalize_public_data(current, {})
    assert result.has_observations is False


def test_has_observations_false_when_empty_dict():
    result = normalize_public_data(_current_payload(obs={}), {})
    assert result.has_observations is False


def test_has_observations_true_when_non_empty_dict():
    result = normalize_public_data(_current_payload(obs={"temperature": [{"current": 18}]}), {})
    assert result.has_observations is True


def test_is_rural_true():
    result = normalize_public_data(_current_payload(days=[{"isRural": "true"}]), {})
    assert result.is_rural is True


def test_is_rural_false_explicit():
    result = normalize_public_data(_current_payload(days=[{"isRural": "false"}]), {})
    assert result.is_rural is False


def test_is_rural_false_when_absent():
    result = normalize_public_data(_current_payload(days=[{}]), {})
    assert result.is_rural is False


# ---------------------------------------------------------------------------
# kumeu (rural) end-to-end contract
# ---------------------------------------------------------------------------

def test_kumeu_observation_fields_are_none(kumeu):
    assert kumeu.temperature is None
    assert kumeu.wind_speed is None
    assert kumeu.wind_gust is None
    assert kumeu.humidity is None
    assert kumeu.pressure is None
    assert kumeu.rainfall is None


def test_kumeu_today_high_low_are_floats(kumeu):
    assert isinstance(kumeu.temp_today_high, float)
    assert isinstance(kumeu.temp_today_low, float)


def test_kumeu_condition_and_forecast_text(kumeu):
    assert isinstance(kumeu.condition, str)
    assert isinstance(kumeu.forecast_text, str)
    assert len(kumeu.forecast_text) > 0


def test_kumeu_tomorrow_fields_present(kumeu):
    assert kumeu.tomorrow_condition is not None
    assert kumeu.tomorrow_temp_high is not None
    assert kumeu.tomorrow_temp_low is not None
    assert kumeu.tomorrow_description is not None


def test_kumeu_daily_entries_count(kumeu):
    assert 1 <= len(kumeu.daily_entries) <= 14


def test_kumeu_daily_entries_complete(kumeu):
    for i, d in enumerate(kumeu.daily_entries):
        assert d.condition is not None, f"day {i} missing condition"
        assert d.temp_high is not None, f"day {i} missing temp_high"
        assert d.temp_low is not None, f"day {i} missing temp_low"
        assert d.description is not None, f"day {i} missing description"
        assert d.rain_prob_1mm is not None, f"day {i} missing rain_prob_1mm"


def test_kumeu_hourly_entries_non_empty(kumeu):
    assert len(kumeu.hourly_entries) > 0


@pytest.mark.parametrize("location", ["napier", "kumeu"])
def test_rain_probability_exceedance_monotonic(location, napier, kumeu):
    data = napier if location == "napier" else kumeu
    for d in data.daily_entries:
        if d.rain_prob_1mm is not None and d.rain_prob_10mm is not None:
            assert d.rain_prob_1mm >= d.rain_prob_10mm
            assert 0 <= d.rain_prob_1mm <= 100
            assert 0 <= d.rain_prob_10mm <= 100


def test_napier_daily_entries_have_temp_high_and_description(napier):
    for i, d in enumerate(napier.daily_entries):
        assert d.temp_high is not None, f"day {i} missing temp_high"
        assert d.description is not None, f"day {i} missing description"


def test_napier_daily_entries_have_some_rain_probability(napier):
    """Towns pages publish rain probabilities from day ~2 onward, not day 0."""
    assert any(d.rain_prob_1mm is not None for d in napier.daily_entries)
