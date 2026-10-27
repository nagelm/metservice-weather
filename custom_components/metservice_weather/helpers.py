"""Shared utility helpers for MetService weather."""

from __future__ import annotations

from datetime import datetime

from homeassistant.util import dt as dt_util


def format_timestamp(timestamp_val: str) -> str:
    """Format an ISO timestamp string to UTC ISO format."""
    return (
        datetime.fromisoformat(timestamp_val)
        .astimezone(dt_util.get_time_zone("UTC"))
        .isoformat()
    )


def safe_float(value: object) -> float | None:
    """Convert value to float, returning None for non-numeric values."""
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return None


def safe_int(value: object) -> int | None:
    """Convert value to int, returning None for non-numeric values."""
    if value is None:
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return None
