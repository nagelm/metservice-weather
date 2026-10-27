"""Shared utility helpers for MetService weather."""

from __future__ import annotations

import re
from datetime import datetime

from homeassistant.util import dt as dt_util

from .const import LOCATION_PATH_RE

_LOCATION_IN_ADDRESS_RE = re.compile(
    rf"(?:/publicdata/webdata)?({LOCATION_PATH_RE.pattern})(?:[/?#].*)?"
)
_ADDRESS_HOST_RE = re.compile(r"^(?:[a-z][a-z0-9+.-]*:)?//([^/?#]*)", re.I)
_METSERVICE_HOSTS = frozenset({"metservice.com", "www.metservice.com"})


def format_timestamp(timestamp_val: str) -> str:
    """Format an ISO timestamp string to UTC ISO format."""
    return (
        datetime.fromisoformat(timestamp_val)
        .astimezone(dt_util.get_time_zone("UTC"))
        .isoformat()
    )


def normalize_location_path(value: str) -> str | None:
    """Return the location path in a path or metservice.com address, or None.

    An address on any host other than metservice.com or www.metservice.com is
    rejected.
    """
    if len(value) > 512:
        return None
    address = value.strip()
    if host := _ADDRESS_HOST_RE.match(address):
        if host.group(1).lower() not in _METSERVICE_HOSTS:
            return None
        address = address[host.end() :]
    address = re.sub(r"^(?:www\.)?metservice\.com(?=[/?#]|$)", "", address, flags=re.I)
    path = "/" + address.lstrip("/").lower()
    match = _LOCATION_IN_ADDRESS_RE.fullmatch(path)
    return match.group(1) if match else None


def safe_float(value: object) -> float | None:
    """Convert value to float, returning None for non-numeric values."""
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except ValueError, TypeError:
        return None


def safe_int(value: object) -> int | None:
    """Convert value to int, returning None for non-numeric values."""
    if value is None:
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except ValueError, TypeError:
        return None
