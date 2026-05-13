"""Coordinator contract tests using captured MetService fixtures.

These tests load the captured Napier fixtures, inject them directly into a
coordinator instance (bypassing real network calls), then assert that each
sensor accessor returns a value of the expected type and within a sane range.

They are "contract" tests in the sense that they pin the *observable interface*
of the coordinator — any Silver-tier refactor that changes how data is stored
internally must still satisfy these assertions.

Run from project root (WSL):
    pytest tests/test_coordinator_data.py -v
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from custom_components.metservice_weather.coordinator import WeatherUpdateCoordinator
from custom_components.metservice_weather.const import (
    RESULTS_CURRENT,
    RESULTS_FORECAST_DAILY,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def napier_data():
    """Load the Napier public fixtures once for the whole module."""
    current = json.loads((FIXTURES / "napier_public_current.json").read_text())
    daily = json.loads((FIXTURES / "napier_public_daily.json").read_text())
    return {RESULTS_CURRENT: current, RESULTS_FORECAST_DAILY: daily}


@pytest.fixture
def coord(napier_data):
    """Return a coordinator with fixture data set, without touching HA framework."""
    c = object.__new__(WeatherUpdateCoordinator)
    c.data = napier_data
    return c


# ---------------------------------------------------------------------------
# Current-conditions sensors
# ---------------------------------------------------------------------------


class TestCurrentConditions:
    def test_temperature_is_numeric(self, coord):
        val = coord.get_current_public("temperature")
        assert isinstance(val, (int, float)), f"Expected numeric, got {val!r}"
        assert -20 <= val <= 50

    def test_feels_like_is_numeric(self, coord):
        val = coord.get_current_public("temperatureFeelsLike")
        assert isinstance(val, (int, float)), f"Expected numeric, got {val!r}"
        assert -30 <= val <= 60

    def test_humidity_is_int_in_range(self, coord):
        val = coord.get_current_public("relativeHumidity")
        assert isinstance(val, int), f"Expected int, got {val!r}"
        assert 0 <= val <= 100

    def test_pressure_is_numeric(self, coord):
        val = coord.get_current_public("pressureAltimeter")
        assert isinstance(val, (int, float)), f"Expected numeric, got {val!r}"
        assert 870 <= val <= 1085

    def test_wind_speed_is_numeric(self, coord):
        val = coord.get_current_public("windSpeed")
        assert isinstance(val, (int, float)), f"Expected numeric, got {val!r}"
        assert val >= 0

    def test_wind_gust_is_numeric(self, coord):
        val = coord.get_current_public("windGust")
        assert isinstance(val, (int, float)), f"Expected numeric, got {val!r}"
        assert val >= 0

    def test_wind_direction_is_string(self, coord):
        val = coord.get_current_public("windDirection")
        assert isinstance(val, str), f"Expected str, got {val!r}"
        assert len(val) >= 1

    def test_condition_is_string(self, coord):
        val = coord.get_current_public("condition")
        assert isinstance(val, str), f"Expected str, got {val!r}"
        assert len(val) > 0

    def test_rainfall_is_numeric(self, coord):
        val = coord.get_current_public("rainfall")
        assert isinstance(val, (int, float)), f"Expected numeric, got {val!r}"
        assert val >= 0

    def test_uv_index_is_string(self, coord):
        val = coord.get_current_public("uvIndex")
        assert isinstance(val, str) or val is None
        if val is not None:
            assert val in {"Low", "Moderate", "High", "Very High", "Extreme", ""}

    def test_location_name_is_string(self, coord):
        val = coord.get_current_public("location_name")
        assert isinstance(val, str)
        assert len(val) > 0


# ---------------------------------------------------------------------------
# Sub-day breakdown
# ---------------------------------------------------------------------------


class TestBreakdown:
    @pytest.mark.parametrize("period", ["morning", "afternoon", "evening", "overnight"])
    def test_breakdown_condition_is_string(self, coord, period):
        val = coord.get_current_public(f"breakdown_{period}")
        assert isinstance(val, str) or val is None


# ---------------------------------------------------------------------------
# Injected / derived fields
# ---------------------------------------------------------------------------


class TestInjectedFields:
    def test_weather_warnings_is_string(self, coord):
        val = coord.get_current_public("weather_warnings")
        assert isinstance(val, str)

    def test_tomorrow_condition_is_string(self, coord):
        val = coord.get_current_public("tomorrow_condition")
        assert isinstance(val, str) or val is None

    def test_tomorrow_temp_high_is_present(self, coord):
        val = coord.get_current_public("tomorrow_temp_high")
        assert val is not None

    def test_tomorrow_temp_low_is_present(self, coord):
        val = coord.get_current_public("tomorrow_temp_low")
        assert val is not None

    def test_tomorrow_description_is_string(self, coord):
        val = coord.get_current_public("tomorrow_description")
        assert isinstance(val, str) or val is None

    def test_drying_morning_is_string(self, coord):
        val = coord.get_current_public("drying_index_morning")
        assert isinstance(val, str) or val is None

    def test_drying_afternoon_is_string(self, coord):
        val = coord.get_current_public("drying_index_afternoon")
        assert isinstance(val, str) or val is None

    def test_drying_next_good_day_is_string(self, coord):
        val = coord.get_current_public("drying_next_good_day")
        assert isinstance(val, str) or val is None


# ---------------------------------------------------------------------------
# Pollen
# ---------------------------------------------------------------------------


class TestPollen:
    def test_pollen_level_is_string_or_none(self, coord):
        val = coord.get_current_public("pollen_levels")
        assert isinstance(val, str) or val is None

    def test_pollen_type_is_string_or_none(self, coord):
        val = coord.get_current_public("pollen_type")
        assert isinstance(val, str) or val is None


# ---------------------------------------------------------------------------
# Sun / Moon
# ---------------------------------------------------------------------------


class TestSunMoon:
    def test_sunrise_is_string(self, coord):
        val = coord.get_current_public("sunrise")
        assert isinstance(val, str) or val is None

    def test_sunset_is_string(self, coord):
        val = coord.get_current_public("sunset")
        assert isinstance(val, str) or val is None

    def test_moon_phase_is_string(self, coord):
        val = coord.get_current_public("moon_phase")
        assert isinstance(val, str) or val is None

    def test_moonrise_is_string(self, coord):
        val = coord.get_current_public("moonrise")
        assert isinstance(val, str) or val is None

    def test_moonset_is_string(self, coord):
        val = coord.get_current_public("moonset")
        assert isinstance(val, str) or val is None


# ---------------------------------------------------------------------------
# Fire weather
# ---------------------------------------------------------------------------


class TestFireWeather:
    def test_fire_danger_is_string_or_none(self, coord):
        val = coord.get_current_public("fire_danger")
        assert isinstance(val, str) or val is None

    def test_fire_season_is_string_or_none(self, coord):
        val = coord.get_current_public("fire_season")
        assert isinstance(val, str) or val is None


# ---------------------------------------------------------------------------
# Hourly data
# ---------------------------------------------------------------------------


class TestHourlyData:
    def test_hourly_temp_is_list(self, coord):
        val = coord.get_current_public("hourly_temp")
        assert isinstance(val, list)
        assert len(val) > 0

    def test_hourly_obs_is_positive_int(self, coord):
        val = coord.get_current_public("hourly_obs")
        assert isinstance(val, int)
        assert val > 0

    def test_hourly_skip_is_non_negative_int(self, coord):
        val = coord.get_current_public("hourly_skip")
        assert isinstance(val, int)
        assert val >= 0

    def test_hourly_entry_has_required_keys(self, coord):
        readings = coord.get_current_public("hourly_temp")
        skip = coord.get_current_public("hourly_skip")
        obs = coord.get_current_public("hourly_obs")
        # Sample the first visible hour
        entry = readings[skip]
        assert "date" in entry
        assert "wind" in entry
        assert "temperature" in entry or "rainfall" in entry


# ---------------------------------------------------------------------------
# Daily forecast
# ---------------------------------------------------------------------------


class TestDailyForecast:
    def test_num_days_is_positive(self, coord):
        num_days = coord.get_forecast_daily_public("", 0)
        assert isinstance(num_days, int)
        assert 1 <= num_days <= 14

    def test_day0_condition_is_string(self, coord):
        val = coord.get_forecast_daily_public("daily_condition", 0)
        assert isinstance(val, str) or val is None

    def test_day0_temp_high_is_present(self, coord):
        val = coord.get_forecast_daily_public("daily_temp_high", 0)
        assert val is not None

    def test_day0_temp_low_is_present(self, coord):
        val = coord.get_forecast_daily_public("daily_temp_low", 0)
        assert val is not None

    def test_day0_datetime_is_string(self, coord):
        val = coord.get_forecast_daily_public("daily_datetime", 0)
        assert isinstance(val, str) or val is None

    def test_day0_description_is_string_or_none(self, coord):
        val = coord.get_forecast_daily_public("daily_description", 0)
        assert isinstance(val, str) or val is None

    def test_all_days_have_condition(self, coord):
        num_days = coord.get_forecast_daily_public("", 0)
        missing = []
        for day in range(num_days):
            val = coord.get_forecast_daily_public("daily_condition", day)
            if val is None:
                missing.append(day)
        assert not missing, f"Days missing condition: {missing}"

    def test_all_days_have_high_temp(self, coord):
        num_days = coord.get_forecast_daily_public("", 0)
        missing = []
        for day in range(num_days):
            val = coord.get_forecast_daily_public("daily_temp_high", day)
            if val is None:
                missing.append(day)
        assert not missing, f"Days missing temp_high: {missing}"
