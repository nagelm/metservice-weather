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
