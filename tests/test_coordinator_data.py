"""Coordinator contract tests using captured MetService fixtures.

These tests load the captured Napier fixtures, inject them directly into a
coordinator instance (bypassing real network calls), then assert that each
sensor field on MetServicePublicData is of the expected type and within a
sane range.

Run from project root (WSL):
    pytest tests/test_coordinator_data.py -v
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from custom_components.metservice_weather.coordinator import WeatherUpdateCoordinator
from custom_components.metservice_weather.coordinator_types import (
    HourlyEntry,
    normalize_public_data,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def napier_data():
    """Load the Napier public fixtures once for the whole module."""
    current = json.loads((FIXTURES / "napier_public_current.json").read_text())
    daily = json.loads((FIXTURES / "napier_public_daily.json").read_text())
    return {"current": current, "daily": daily}


@pytest.fixture
def coord(napier_data):
    """Return a coordinator with normalised fixture data set, without touching HA framework."""
    c = object.__new__(WeatherUpdateCoordinator)
    c.data = normalize_public_data(napier_data["current"], napier_data["daily"])
    return c


@pytest.fixture(scope="module")
def kumeu_data():
    """Load the Kumeu (rural) public fixtures once for the whole module."""
    current = json.loads((FIXTURES / "kumeu_public_current.json").read_text())
    daily = json.loads((FIXTURES / "kumeu_public_daily.json").read_text())
    return {"current": current, "daily": daily}


@pytest.fixture
def rural_coord(kumeu_data):
    """Return a coordinator with normalised rural fixture data set, without touching HA framework."""
    c = object.__new__(WeatherUpdateCoordinator)
    c.data = normalize_public_data(kumeu_data["current"], kumeu_data["daily"])
    return c


# ---------------------------------------------------------------------------
# Current-conditions sensors
# ---------------------------------------------------------------------------


class TestCurrentConditions:
    """Contract tests for current-conditions fields from the Napier fixture."""

    def test_temperature_is_numeric(self, coord):
        """Temperature is numeric and within a plausible range."""
        val = coord.data.temperature
        assert isinstance(val, (int, float)), f"Expected numeric, got {val!r}"
        assert -20 <= val <= 50

    def test_feels_like_is_numeric(self, coord):
        """Feels-like temperature is numeric and within a plausible range."""
        val = coord.data.feels_like
        assert isinstance(val, (int, float)), f"Expected numeric, got {val!r}"
        assert -30 <= val <= 60

    def test_humidity_is_int_in_range(self, coord):
        """Humidity is an int between 0 and 100."""
        val = coord.data.humidity
        assert isinstance(val, int), f"Expected int, got {val!r}"
        assert 0 <= val <= 100

    def test_pressure_is_numeric(self, coord):
        """Pressure is numeric and within a plausible range."""
        val = coord.data.pressure
        assert isinstance(val, (int, float)), f"Expected numeric, got {val!r}"
        assert 870 <= val <= 1085

    def test_wind_speed_is_numeric(self, coord):
        """Wind speed is a non-negative number."""
        val = coord.data.wind_speed
        assert isinstance(val, (int, float)), f"Expected numeric, got {val!r}"
        assert val >= 0

    def test_wind_gust_is_numeric(self, coord):
        """Wind gust is a non-negative number."""
        val = coord.data.wind_gust
        assert isinstance(val, (int, float)), f"Expected numeric, got {val!r}"
        assert val >= 0

    def test_wind_direction_is_string(self, coord):
        """Wind direction is a non-empty string."""
        val = coord.data.wind_direction
        assert isinstance(val, str), f"Expected str, got {val!r}"
        assert len(val) >= 1

    def test_condition_is_string(self, coord):
        """Condition is a non-empty string."""
        val = coord.data.condition
        assert isinstance(val, str), f"Expected str, got {val!r}"
        assert len(val) > 0

    def test_rainfall_is_numeric(self, coord):
        """Rainfall is a non-negative number."""
        val = coord.data.rainfall
        assert isinstance(val, (int, float)), f"Expected numeric, got {val!r}"
        assert val >= 0

    def test_uv_index_is_string_or_none(self, coord):
        """UV index is a string or None."""
        val = coord.data.uv_index
        assert isinstance(val, str) or val is None

    def test_location_name_is_string(self, coord):
        """Location name is a non-empty string."""
        val = coord.data.location_name
        assert isinstance(val, str)
        assert len(val) > 0


# ---------------------------------------------------------------------------
# Sub-day breakdown
# ---------------------------------------------------------------------------


class TestBreakdown:
    """Contract tests for the sub-day breakdown fields."""

    @pytest.mark.parametrize(
        "attr",
        [
            "breakdown_morning",
            "breakdown_afternoon",
            "breakdown_evening",
            "breakdown_overnight",
        ],
    )
    def test_breakdown_condition_is_string(self, coord, attr):
        """Each breakdown period's condition is a string or None."""
        val = getattr(coord.data, attr)
        assert isinstance(val, str) or val is None


# ---------------------------------------------------------------------------
# Injected / derived fields
# ---------------------------------------------------------------------------


class TestInjectedFields:
    """Contract tests for fields injected or derived by the coordinator."""

    def test_weather_warnings_is_string(self, coord):
        """Weather warnings value is a string."""
        val = coord.data.weather_warnings
        assert isinstance(val, str)

    def test_tomorrow_condition_is_string(self, coord):
        """Tomorrow's condition is a string or None."""
        val = coord.data.tomorrow_condition
        assert isinstance(val, str) or val is None

    def test_tomorrow_temp_high_is_present(self, coord):
        """Tomorrow's high temperature is present."""
        val = coord.data.tomorrow_temp_high
        assert val is not None

    def test_tomorrow_temp_low_is_present(self, coord):
        """Tomorrow's low temperature is present."""
        val = coord.data.tomorrow_temp_low
        assert val is not None

    def test_tomorrow_description_is_string(self, coord):
        """Tomorrow's description is a string or None."""
        val = coord.data.tomorrow_description
        assert isinstance(val, str) or val is None

    def test_drying_morning_is_string(self, coord):
        """Morning drying index is a string or None."""
        val = coord.data.drying_morning
        assert isinstance(val, str) or val is None

    def test_drying_afternoon_is_string(self, coord):
        """Afternoon drying index is a string or None."""
        val = coord.data.drying_afternoon
        assert isinstance(val, str) or val is None

    def test_drying_next_good_day_is_string(self, coord):
        """Next good drying day is a string or None."""
        val = coord.data.drying_next_good_day
        assert isinstance(val, str) or val is None


# ---------------------------------------------------------------------------
# Pollen
# ---------------------------------------------------------------------------


class TestPollen:
    """Contract tests for pollen fields."""

    def test_pollen_level_is_string_or_none(self, coord):
        """Pollen level is a string or None."""
        val = coord.data.pollen_level
        assert isinstance(val, str) or val is None

    def test_pollen_type_is_string_or_none(self, coord):
        """Pollen type is a string or None."""
        val = coord.data.pollen_type
        assert isinstance(val, str) or val is None


# ---------------------------------------------------------------------------
# Sun / Moon
# ---------------------------------------------------------------------------


class TestSunMoon:
    """Contract tests for sun and moon fields."""

    def test_sunrise_is_string(self, coord):
        """Sunrise is a string or None."""
        val = coord.data.sunrise
        assert isinstance(val, str) or val is None

    def test_sunset_is_string(self, coord):
        """Sunset is a string or None."""
        val = coord.data.sunset
        assert isinstance(val, str) or val is None

    def test_moon_phase_is_string(self, coord):
        """Moon phase is a string or None."""
        val = coord.data.moon_phase
        assert isinstance(val, str) or val is None

    def test_moonrise_is_string(self, coord):
        """Moonrise is a string or None."""
        val = coord.data.moonrise
        assert isinstance(val, str) or val is None

    def test_moonset_is_string(self, coord):
        """Moonset is a string or None."""
        val = coord.data.moonset
        assert isinstance(val, str) or val is None


# ---------------------------------------------------------------------------
# Fire weather
# ---------------------------------------------------------------------------


class TestFireWeather:
    """Contract tests for fire weather fields."""

    def test_fire_danger_is_string_or_none(self, coord):
        """Fire danger is a string or None."""
        val = coord.data.fire_danger
        assert isinstance(val, str) or val is None

    def test_fire_season_is_string_or_none(self, coord):
        """Fire season is a string or None."""
        val = coord.data.fire_season
        assert isinstance(val, str) or val is None


# ---------------------------------------------------------------------------
# Hourly data
# ---------------------------------------------------------------------------


class TestHourlyData:
    """Contract tests for the hourly forecast fields."""

    def test_hourly_entries_is_list(self, coord):
        """Hourly entries is a non-empty list."""
        val = coord.data.hourly_entries
        assert isinstance(val, list)
        assert len(val) > 0

    def test_hourly_obs_is_positive_int(self, coord):
        """Hourly observation count is a positive int."""
        val = coord.data.hourly_obs
        assert isinstance(val, int)
        assert val > 0

    def test_hourly_skip_is_non_negative_int(self, coord):
        """Hourly skip offset is a non-negative int."""
        val = coord.data.hourly_skip
        assert isinstance(val, int)
        assert val >= 0

    def test_hourly_entry_has_required_keys(self, coord):
        """Current hourly entry has a datetime and a temperature or rainfall value."""
        entries = coord.data.hourly_entries
        skip = coord.data.hourly_skip
        entry = entries[skip]
        assert isinstance(entry, HourlyEntry)
        assert entry.datetime != ""
        assert entry.temperature is not None or entry.rainfall is not None


# ---------------------------------------------------------------------------
# Daily forecast
# ---------------------------------------------------------------------------


class TestDailyForecast:
    """Contract tests for the daily forecast fields."""

    def test_num_days_is_positive(self, coord):
        """Number of daily entries is between 1 and 14."""
        num_days = len(coord.data.daily_entries)
        assert isinstance(num_days, int)
        assert 1 <= num_days <= 14

    def test_day0_condition_is_string(self, coord):
        """Day 0 condition is a string or None."""
        val = coord.data.daily_entries[0].condition
        assert isinstance(val, str) or val is None

    def test_day0_temp_high_is_present(self, coord):
        """Day 0 high temperature is present."""
        val = coord.data.daily_entries[0].temp_high
        assert val is not None

    def test_day0_temp_low_is_present(self, coord):
        """Day 0 low temperature is present."""
        val = coord.data.daily_entries[0].temp_low
        assert val is not None

    def test_day0_datetime_is_string(self, coord):
        """Day 0 datetime is a string or None."""
        val = coord.data.daily_entries[0].datetime
        assert isinstance(val, str) or val is None

    def test_day0_description_is_string_or_none(self, coord):
        """Day 0 description is a string or None."""
        val = coord.data.daily_entries[0].description
        assert isinstance(val, str) or val is None

    def test_all_days_have_condition(self, coord):
        """Every daily entry has a condition set."""
        missing = [
            i for i, d in enumerate(coord.data.daily_entries) if d.condition is None
        ]
        assert not missing, f"Days missing condition: {missing}"

    def test_all_days_have_high_temp(self, coord):
        """Every daily entry has a high temperature set."""
        missing = [
            i for i, d in enumerate(coord.data.daily_entries) if d.temp_high is None
        ]
        assert not missing, f"Days missing temp_high: {missing}"


# ---------------------------------------------------------------------------
# Rural contract — Kumeu (no weather station, no breakdown, isRural)
# ---------------------------------------------------------------------------


class TestRuralContract:
    """Contract tests for the rural (no weather station) Kumeu fixture."""

    def test_temperature_is_none(self, rural_coord):
        """Rural location has no current temperature."""
        assert rural_coord.data.temperature is None

    def test_wind_speed_is_none(self, rural_coord):
        """Rural location has no current wind speed."""
        assert rural_coord.data.wind_speed is None

    def test_temp_today_high_is_float(self, rural_coord):
        """Rural location's today high temperature is a float."""
        assert isinstance(rural_coord.data.temp_today_high, float)

    def test_tomorrow_temp_high_is_present(self, rural_coord):
        """Rural location's tomorrow high temperature is present."""
        assert rural_coord.data.tomorrow_temp_high is not None

    def test_all_daily_entries_have_temp_high_and_description(self, rural_coord):
        """Every rural daily entry has a high temperature and description."""
        for i, d in enumerate(rural_coord.data.daily_entries):
            assert d.temp_high is not None, f"day {i} missing temp_high"
            assert d.description is not None, f"day {i} missing description"

    def test_is_rural_true(self, rural_coord):
        """Rural location's is_rural flag is True."""
        assert rural_coord.data.is_rural is True

    def test_has_observations_false(self, rural_coord):
        """Rural location's has_observations flag is False."""
        assert rural_coord.data.has_observations is False
