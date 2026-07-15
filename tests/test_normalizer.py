"""Tests for coordinator_types: _get, normalizer, and dataclass structure."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from custom_components.metservice_weather.coordinator_types import (
    DailyEntry,
    HourlyEntry,
    MetServicePublicData,
    _get,
    _round_iso_to_minutes,
    _safe_float,
    _safe_int,
    _scan_forecasts,
    normalize_public_data,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def napier():
    """Build normalized MetServicePublicData from the Napier (towns-cities) fixtures."""
    current = json.loads((FIXTURES / "napier_public_current.json").read_text())
    daily = json.loads((FIXTURES / "napier_public_daily.json").read_text())
    return normalize_public_data(current, daily)


@pytest.fixture(scope="module")
def kumeu():
    """Build normalized MetServicePublicData from the Kumeu (rural) fixtures."""
    current = json.loads((FIXTURES / "kumeu_public_current.json").read_text())
    daily = json.loads((FIXTURES / "kumeu_public_daily.json").read_text())
    return normalize_public_data(current, daily)


# ---------------------------------------------------------------------------
# _get — exact-path traversal
# ---------------------------------------------------------------------------


def test_get_simple_dict():
    """_get returns the value at a simple single-key path."""
    assert _get({"a": 1}, "a") == 1


def test_get_nested():
    """_get traverses nested dict keys."""
    assert _get({"a": {"b": 42}}, "a", "b") == 42


def test_get_list_index():
    """_get indexes into a list using a string index."""
    assert _get(["x", "y", "z"], "1") == "y"


def test_get_mixed():
    """_get traverses a mix of dict keys and list indices."""
    data = {"items": [{"val": 10}, {"val": 20}]}
    assert _get(data, "items", "1", "val") == 20


def test_get_missing_key_returns_none():
    """_get returns None for a missing dict key."""
    assert _get({"a": 1}, "b") is None


def test_get_out_of_range_returns_none():
    """_get returns None for a list index out of range."""
    assert _get([1, 2], "5") is None


def test_get_none_data_returns_none():
    """_get returns None when data is None."""
    assert _get(None, "a") is None


def test_get_non_dict_non_list_returns_none():
    """_get returns None when data is neither a dict nor a list."""
    assert _get(42, "a") is None


def test_get_empty_path_returns_data():
    """_get with an empty path returns the data unchanged."""
    data = {"x": 1}
    assert _get(data) == data


def test_get_does_not_search_depth_first():
    """_get matches only the exact path, not a depth-first search."""
    # DFS would find "val" anywhere in the tree; exact-path must not.
    data = {"level1": {"other": {"val": 999}}, "val": 42}
    assert _get(data, "val") == 42  # top-level hit only
    assert _get(data, "level1", "val") is None  # "val" not a direct child of level1


# ---------------------------------------------------------------------------
# _safe_float / _safe_int
# ---------------------------------------------------------------------------


def test_safe_float_numeric():
    """_safe_float converts numeric strings and numbers to float."""
    assert _safe_float("18.5") == 18.5
    assert _safe_float(18) == 18.0


def test_safe_float_invalid():
    """_safe_float returns None for None or non-numeric strings."""
    assert _safe_float(None) is None
    assert _safe_float("n/a") is None


def test_safe_int_numeric():
    """_safe_int converts numeric strings and floats to int."""
    assert _safe_int("5") == 5
    assert _safe_int(5.9) == 5


def test_safe_int_invalid():
    """_safe_int returns None for None or non-numeric strings."""
    assert _safe_int(None) is None
    assert _safe_int("bad") is None


# ---------------------------------------------------------------------------
# normalize_public_data — against Napier fixture
# ---------------------------------------------------------------------------


def test_returns_correct_type(napier):
    """normalize_public_data returns a MetServicePublicData instance."""
    assert isinstance(napier, MetServicePublicData)


def test_temperature_is_float(napier):
    """Normalized temperature is a float within a plausible range."""
    assert isinstance(napier.temperature, float)
    assert -20 <= napier.temperature <= 50


def test_humidity_is_int(napier):
    """Normalized humidity is an int within 0-100."""
    assert isinstance(napier.humidity, int)
    assert 0 <= napier.humidity <= 100


def test_wind_direction_is_string(napier):
    """Normalized wind_direction is a string."""
    assert isinstance(napier.wind_direction, str)


def test_condition_is_string(napier):
    """Normalized condition is a string."""
    assert isinstance(napier.condition, str)


def test_weather_warnings_is_string(napier):
    """Normalized weather_warnings is a string."""
    assert isinstance(napier.weather_warnings, str)


def test_pollen_level_present(napier):
    """Normalized pollen_level is populated from the Napier fixture."""
    assert napier.pollen_level is not None


def test_tomorrow_fields_present(napier):
    """Normalized tomorrow_condition and tomorrow_temp_high are populated."""
    assert napier.tomorrow_condition is not None
    assert napier.tomorrow_temp_high is not None


def test_hourly_entries_is_list(napier):
    """Normalized hourly_entries is a non-empty list of HourlyEntry."""
    assert isinstance(napier.hourly_entries, list)
    assert len(napier.hourly_entries) > 0
    assert isinstance(napier.hourly_entries[0], HourlyEntry)


def test_daily_entries_is_list(napier):
    """Normalized daily_entries is a list of 1-14 DailyEntry items."""
    assert isinstance(napier.daily_entries, list)
    assert 1 <= len(napier.daily_entries) <= 14
    assert isinstance(napier.daily_entries[0], DailyEntry)


def test_all_daily_entries_have_condition(napier):
    """Every normalized daily entry has a condition."""
    missing = [i for i, d in enumerate(napier.daily_entries) if d.condition is None]
    assert not missing, f"Days missing condition: {missing}"


def test_all_daily_entries_have_temp_high(napier):
    """Every normalized daily entry has a temp_high."""
    missing = [i for i, d in enumerate(napier.daily_entries) if d.temp_high is None]
    assert not missing, f"Days missing temp_high: {missing}"


def test_sunrise_is_string(napier):
    """Normalized sunrise is a string."""
    assert isinstance(napier.sunrise, str)


def test_moon_phase_is_string(napier):
    """Normalized moon_phase is a string."""
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
    """Tides are extracted from the tideImport key on the current payload."""
    tides = [{"type": "HIGH", "time": "06:30", "height": 1.8}]
    current = {
        "weather_warnings": "No warnings",
        "tideImport": tides,
    }
    result = normalize_public_data(current, {})
    assert result.tides == tides


def test_boating_extracted_from_boating_data():
    """Boating status and forecast text are extracted from boating_data."""
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
    """Surf conditions and rating are extracted from surf_data."""
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
    assert result.warnings_list == []


def test_warnings_list_passes_through_when_injected():
    """warnings_list is extracted from the injected 'warnings_list' key on current."""
    structured = [
        {
            "name": "Strong Wind Watch",
            "text": "Keep an eye out",
            "threat_period": "Today",
        }
    ]
    current = {"weather_warnings": "Strong Wind Watch", "warnings_list": structured}
    result = normalize_public_data(current, {})
    assert result.warnings_list == structured


# ---------------------------------------------------------------------------
# _scan_forecasts — forecast entry scanning
# ---------------------------------------------------------------------------


def test_scan_forecasts_towns_shape_prefers_forecasts_entry():
    """_scan_forecasts prefers the value from the forecasts entry over the day level."""
    day = {"forecasts": [{"highTemp": 16}], "highTemp": 15}
    assert _scan_forecasts(day, "highTemp") == 16


def test_scan_forecasts_rural_shape_finds_second_entry():
    """_scan_forecasts finds the field in the second forecasts entry for the rural shape."""
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
    """_scan_forecasts falls back to the day level when forecasts is absent."""
    day = {"highTemp": 12}
    assert _scan_forecasts(day, "highTemp") == 12


def test_scan_forecasts_none_in_forecasts_falls_through_to_day_level():
    """_scan_forecasts falls back to the day level when forecasts entries are None."""
    day = {"forecasts": [{"highTemp": None}], "highTemp": 9}
    assert _scan_forecasts(day, "highTemp") == 9


def test_scan_forecasts_absent_everywhere_returns_none():
    """_scan_forecasts returns None when the field is absent everywhere."""
    assert _scan_forecasts({}, "highTemp") is None


def test_scan_forecasts_non_dict_day_returns_none():
    """_scan_forecasts returns None when day is not a dict."""
    assert _scan_forecasts(None, "highTemp") is None
    assert _scan_forecasts(42, "highTemp") is None


def test_scan_forecasts_non_dict_forecast_entries_skipped():
    """_scan_forecasts skips non-dict entries in the forecasts list."""
    day = {"forecasts": ["junk", {"highTemp": 5}]}
    assert _scan_forecasts(day, "highTemp") == 5


# ---------------------------------------------------------------------------
# daily entry shape heuristics
# ---------------------------------------------------------------------------


def _daily_payload(days):
    return {"layout": {"primary": {"slots": {"main": {"modules": [{"days": days}]}}}}}


def test_daily_entry_towns_shape():
    """Towns-shape daily entry populates temps, description, and rain probabilities from the forecasts entry."""
    day = {
        "date": "2024-06-15",
        "condition": "fine",
        "forecasts": [
            {
                "highTemp": 22,
                "lowTemp": 12,
                "statement": "Sunny day",
                "rainFall1": 30.0,
                "rainFall10": 5.0,
            }
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
    """Rural daily entries populate temps from the location forecasts entry."""
    day = {
        "date": "2024-06-15",
        "condition": "cloudy",
        "forecasts": [
            {"statement": "Regional cloudy", "title": "Region"},
            {
                "highTemp": 18,
                "lowTemp": 9,
                "rainFall1": 40.0,
                "rainFall10": 10.0,
                "statement": None,
            },
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
    """Daily entry falls back to day-level temps and statement when forecasts is absent."""
    day = {
        "date": "2024-06-15",
        "condition": "fine",
        "highTemp": 20,
        "lowTemp": 10,
        "statement": "Fine day",
    }
    result = normalize_public_data({}, _daily_payload([day]))
    entry = result.daily_entries[0]
    assert entry.temp_high == 20.0
    assert entry.temp_low == 10.0
    assert entry.description == "Fine day"


def test_daily_entry_empty_day():
    """An empty day dict normalizes to a DailyEntry with all fields None."""
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
    """Absent rain fields normalize to None rather than zero."""
    day = {"highTemp": 15, "lowTemp": 8, "statement": "no rain data"}
    result = normalize_public_data({}, _daily_payload([day]))
    entry = result.daily_entries[0]
    assert entry.rain_prob_1mm is None
    assert entry.rain_prob_10mm is None


def test_daily_entry_string_temps_coerced_to_float():
    """String temperature values are coerced to float."""
    day = {"forecasts": [{"highTemp": "16"}]}
    result = normalize_public_data({}, _daily_payload([day]))
    entry = result.daily_entries[0]
    assert entry.temp_high == 16.0
    assert isinstance(entry.temp_high, float)


# ---------------------------------------------------------------------------
# tomorrow derivation
# ---------------------------------------------------------------------------


def test_tomorrow_derived_from_day_index_1():
    """Tomorrow fields are derived from daily_entries index 1."""
    days = [
        {
            "condition": "fine",
            "forecasts": [{"highTemp": 20, "lowTemp": 12, "statement": "Today fine"}],
        },
        {
            "condition": "cloudy",
            "forecasts": [
                {"highTemp": 17, "lowTemp": 10, "statement": "Tomorrow cloudy"}
            ],
        },
    ]
    result = normalize_public_data({}, _daily_payload(days))
    assert result.tomorrow_condition == "cloudy"
    assert result.tomorrow_temp_high == 17.0 and isinstance(
        result.tomorrow_temp_high, float
    )
    assert result.tomorrow_temp_low == 10.0 and isinstance(
        result.tomorrow_temp_low, float
    )
    assert result.tomorrow_description == "Tomorrow cloudy"


def test_tomorrow_none_with_only_one_day():
    """Tomorrow fields are None when only one day of forecast data is present."""
    days = [
        {
            "condition": "fine",
            "forecasts": [{"highTemp": 20, "lowTemp": 12, "statement": "Today fine"}],
        }
    ]
    result = normalize_public_data({}, _daily_payload(days))
    assert result.tomorrow_condition is None
    assert result.tomorrow_temp_high is None
    assert result.tomorrow_temp_low is None
    assert result.tomorrow_description is None


def test_tomorrow_none_with_empty_daily_dict():
    """Tomorrow fields are None when the daily payload is empty."""
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
    return {
        "layout": {
            "primary": {
                "slots": {
                    "left-major": {"modules": left},
                    "main": {"modules": main},
                }
            }
        }
    }


def test_today_high_low_prefers_observations():
    """Today's high/low prefer the observations block over day-level forecast temps."""
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
    """Today's high/low fall back to the second forecasts entry for the rural shape."""
    days = [{"forecasts": [{"statement": "regional"}, {"highTemp": 16, "lowTemp": 6}]}]
    result = normalize_public_data(_current_payload(days=days), {})
    assert result.temp_today_high == 16.0
    assert result.temp_today_low == 6.0


def test_today_high_low_none_when_both_absent():
    """Today's high/low are None when observations and day-level data are both absent."""
    result = normalize_public_data(_current_payload(), {})
    assert result.temp_today_high is None
    assert result.temp_today_low is None


# ---------------------------------------------------------------------------
# capability flags
# ---------------------------------------------------------------------------


def test_capability_flags_napier(napier):
    """Napier fixture reports observations, breakdown, and non-rural capability flags."""
    assert napier.has_observations is True
    assert napier.has_breakdown is True
    assert napier.is_rural is False


def test_capability_flags_kumeu(kumeu):
    """Kumeu fixture reports no observations, no breakdown, and rural capability flags."""
    assert kumeu.has_observations is False
    assert kumeu.has_breakdown is False
    assert kumeu.is_rural is True


def test_has_observations_false_when_module_value_is_none():
    """has_observations is False when the observations module value is None."""
    current = {
        "layout": {
            "primary": {"slots": {"left-major": {"modules": [{"observations": None}]}}}
        }
    }
    result = normalize_public_data(current, {})
    assert result.has_observations is False


def test_has_observations_false_when_empty_dict():
    """has_observations is False when observations is an empty dict."""
    result = normalize_public_data(_current_payload(obs={}), {})
    assert result.has_observations is False


def test_has_observations_true_when_non_empty_dict():
    """has_observations is True when observations is a non-empty dict."""
    result = normalize_public_data(
        _current_payload(obs={"temperature": [{"current": 18}]}), {}
    )
    assert result.has_observations is True


def test_is_rural_true():
    """is_rural is True when the day's isRural flag is the string 'true'."""
    result = normalize_public_data(_current_payload(days=[{"isRural": "true"}]), {})
    assert result.is_rural is True


def test_is_rural_false_explicit():
    """is_rural is False when the day's isRural flag is the string 'false'."""
    result = normalize_public_data(_current_payload(days=[{"isRural": "false"}]), {})
    assert result.is_rural is False


def test_is_rural_false_when_absent():
    """is_rural defaults to False when isRural is absent."""
    result = normalize_public_data(_current_payload(days=[{}]), {})
    assert result.is_rural is False


# ---------------------------------------------------------------------------
# kumeu (rural) end-to-end contract
# ---------------------------------------------------------------------------


def test_kumeu_observation_fields_are_none(kumeu):
    """Kumeu (rural) observation fields normalize to None."""
    assert kumeu.temperature is None
    assert kumeu.wind_speed is None
    assert kumeu.wind_gust is None
    assert kumeu.humidity is None
    assert kumeu.pressure is None
    assert kumeu.rainfall is None


def test_kumeu_today_high_low_are_floats(kumeu):
    """Kumeu's today high/low temps are floats."""
    assert isinstance(kumeu.temp_today_high, float)
    assert isinstance(kumeu.temp_today_low, float)


def test_kumeu_condition_and_forecast_text(kumeu):
    """Kumeu's condition and forecast_text are non-empty strings."""
    assert isinstance(kumeu.condition, str)
    assert isinstance(kumeu.forecast_text, str)
    assert len(kumeu.forecast_text) > 0


def test_kumeu_tomorrow_fields_present(kumeu):
    """Kumeu's tomorrow fields are all populated."""
    assert kumeu.tomorrow_condition is not None
    assert kumeu.tomorrow_temp_high is not None
    assert kumeu.tomorrow_temp_low is not None
    assert kumeu.tomorrow_description is not None


def test_kumeu_daily_entries_count(kumeu):
    """Kumeu's daily_entries count is within the expected 1-14 range."""
    assert 1 <= len(kumeu.daily_entries) <= 14


def test_kumeu_daily_entries_complete(kumeu):
    """Every Kumeu daily entry has condition, temps, description, and rain probability."""
    for i, d in enumerate(kumeu.daily_entries):
        assert d.condition is not None, f"day {i} missing condition"
        assert d.temp_high is not None, f"day {i} missing temp_high"
        assert d.temp_low is not None, f"day {i} missing temp_low"
        assert d.description is not None, f"day {i} missing description"
        assert d.rain_prob_1mm is not None, f"day {i} missing rain_prob_1mm"


def test_kumeu_hourly_entries_non_empty(kumeu):
    """Kumeu's hourly_entries is non-empty."""
    assert len(kumeu.hourly_entries) > 0


@pytest.mark.parametrize("location", ["napier", "kumeu"])
def test_rain_probability_exceedance_monotonic(location, napier, kumeu):
    """Rain probability exceedance is monotonic: the 1mm chance is never below the 10mm chance."""
    data = napier if location == "napier" else kumeu
    for d in data.daily_entries:
        if d.rain_prob_1mm is not None and d.rain_prob_10mm is not None:
            assert d.rain_prob_1mm >= d.rain_prob_10mm
            assert 0 <= d.rain_prob_1mm <= 100
            assert 0 <= d.rain_prob_10mm <= 100


def test_napier_daily_entries_have_temp_high_and_description(napier):
    """Every Napier daily entry has temp_high and description."""
    for i, d in enumerate(napier.daily_entries):
        assert d.temp_high is not None, f"day {i} missing temp_high"
        assert d.description is not None, f"day {i} missing description"


def test_napier_daily_entries_have_some_rain_probability(napier):
    """Towns pages publish rain probabilities from day ~2 onward, not day 0."""
    assert any(d.rain_prob_1mm is not None for d in napier.daily_entries)


# ---------------------------------------------------------------------------
# Debug logging for transient observation nulls
# ---------------------------------------------------------------------------

_TYPES_LOGGER = "custom_components.metservice_weather.coordinator_types"


def test_debug_log_fires_when_observations_present_but_field_parses_none(caplog):
    """A debug record lists fields that stayed None despite a present observations block."""
    obs = {"temperature": [{"current": None}], "wind": [{"averageSpeed": 12}]}
    with caplog.at_level(logging.DEBUG, logger=_TYPES_LOGGER):
        normalize_public_data(_current_payload(obs=obs), {})
    matches = [r for r in caplog.records if "parsed to None" in r.getMessage()]
    assert len(matches) == 1
    assert "temperature" in matches[0].getMessage()


def test_debug_log_absent_when_observations_fully_populated(caplog):
    """No debug record fires when every tracked observation field parses successfully."""
    obs = {
        "temperature": [{"current": 18.0, "feelsLike": 17.0}],
        "rain": [{"relativeHumidity": 55, "rainfall": 0.0}],
        "pressure": [{"atSeaLevel": 1013.0}],
        "wind": [{"averageSpeed": 10.0, "gustSpeed": 15.0, "direction": "NW"}],
    }
    with caplog.at_level(logging.DEBUG, logger=_TYPES_LOGGER):
        normalize_public_data(_current_payload(obs=obs), {})
    matches = [r for r in caplog.records if "parsed to None" in r.getMessage()]
    assert matches == []


def test_debug_log_fires_when_observations_empty_on_non_rural_location(caplog):
    """A debug record fires when the observations module is empty on a non-rural page."""
    with caplog.at_level(logging.DEBUG, logger=_TYPES_LOGGER):
        normalize_public_data(_current_payload(days=[{}]), {})
    matches = [r for r in caplog.records if "empty/absent" in r.getMessage()]
    assert len(matches) == 1


def test_debug_log_absent_for_kumeu_rural_fixture(caplog):
    """No 'empty/absent' debug record fires for a rural location — absence is structural there."""
    current = json.loads((FIXTURES / "kumeu_public_current.json").read_text())
    daily = json.loads((FIXTURES / "kumeu_public_daily.json").read_text())
    with caplog.at_level(logging.DEBUG, logger=_TYPES_LOGGER):
        normalize_public_data(current, daily)
    matches = [r for r in caplog.records if "empty/absent" in r.getMessage()]
    assert matches == []


# ---------------------------------------------------------------------------
# _round_iso_to_minutes — moon-phase timestamp jitter suppression
# ---------------------------------------------------------------------------


def test_round_iso_collapses_second_level_jitter():
    """Two prod-observed jittered timestamps of one event round to the same value."""
    a = _round_iso_to_minutes("2026-07-07T19:15:27+00:00")
    b = _round_iso_to_minutes("2026-07-07T19:15:46+00:00")
    assert a == b == "2026-07-07T19:15:00+00:00"


def test_round_iso_collapses_minute_boundary_jitter():
    """Jitter that crosses a minute boundary (prod-observed) still collapses."""
    a = _round_iso_to_minutes("2026-07-14T10:00:19+00:00")
    b = _round_iso_to_minutes("2026-07-14T10:01:14+00:00")
    assert a == b == "2026-07-14T10:00:00+00:00"


def test_round_iso_rounds_up_to_nearest_step():
    """A timestamp past the midpoint rounds up to the next 5-minute mark."""
    assert _round_iso_to_minutes("2026-07-07T19:13:40+00:00") == (
        "2026-07-07T19:15:00+00:00"
    )


def test_round_iso_preserves_timezone_offset():
    """NZ-offset timestamps keep their offset after rounding."""
    assert _round_iso_to_minutes("2026-07-21T22:55:48+12:00") == (
        "2026-07-21T22:55:00+12:00"
    )


def test_round_iso_passthrough_on_garbage():
    """Non-ISO strings and non-strings pass through unchanged."""
    assert _round_iso_to_minutes("not-a-date") == "not-a-date"
    assert _round_iso_to_minutes(None) is None
    assert _round_iso_to_minutes(42) == 42


def test_moon_phase_date_rounded_in_normalize(napier):
    """The napier fixture's moon phase date normalizes to a 5-minute boundary."""
    from datetime import datetime as _dt

    assert napier.moon_phase_date is not None
    parsed = _dt.fromisoformat(napier.moon_phase_date)
    assert parsed.second == 0 and parsed.microsecond == 0
    assert parsed.minute % 5 == 0


def test_moon_phase_raw_jitter_logged_at_debug(caplog):
    """A jittery raw dateISO is debug-logged with its rounded value."""
    current = {
        "layout": {
            "secondary": {
                "slots": {
                    "major": {
                        "modules": [
                            {
                                "riseSet": {},
                                "moonPhases": [
                                    {
                                        "phase": "FULL",
                                        "dateISO": "2026-07-07T19:15:27+00:00",
                                    }
                                ],
                            }
                        ]
                    }
                }
            }
        }
    }
    with caplog.at_level(
        logging.DEBUG, logger="custom_components.metservice_weather.coordinator_types"
    ):
        result = normalize_public_data(current, {})
    assert result.moon_phase_date == "2026-07-07T19:15:00+00:00"
    assert any("rounded to" in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------------------
# Pollen groups — multiple concurrent status blocks
# ---------------------------------------------------------------------------


def test_pollen_groups_pass_through():
    """Injected pollen groups land on pollen_groups; headline stays level/type."""
    current = {
        "pollen": {
            "pollenLevels": {"level": "Imminent", "type": "Wattle, alder"},
            "groups": [
                {"level": "Imminent", "type": "Wattle, alder"},
                {"level": "Low", "type": "Cypress, hazelnut"},
            ],
        }
    }
    result = normalize_public_data(current, {})
    assert result.pollen_level == "Imminent"
    assert len(result.pollen_groups) == 2
    assert result.pollen_groups[1]["level"] == "Low"


def test_pollen_groups_default_empty():
    """pollen_groups defaults to an empty list when no pollen data is injected."""
    result = normalize_public_data({}, {})
    assert result.pollen_groups == []
