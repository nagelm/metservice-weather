#!/usr/bin/env python3
"""Capture MetService API fixtures for coordinator contract tests.

Fetches real data for Napier (public API) and saves post-expansion,
post-injection coordinator data as JSON fixtures in tests/fixtures/.

Run from the project root:
    python scripts/capture_fixtures.py

Requires: aiohttp, async_timeout (both present in the project venv).
"""
import asyncio
import json
import re
from pathlib import Path

import aiohttp
import async_timeout

BASE_URL = "https://www.metservice.com"
PUBLIC_URL = f"{BASE_URL}/publicData/webdata"
WARNINGS_URL = f"{BASE_URL}/publicData/webdata/warnings-service"
LOCATION = "/towns-cities/regions/hawkes-bay/locations/napier"

HEADERS = {
    "Accept-Encoding": "gzip",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/111.0.0.0 Safari/537.36"
    ),
}


async def expand_data_urls(session, data, parent=None, key=None, _depth=0):
    """Mirror the coordinator's expand_data_urls for fixture capture."""
    if _depth > 10:
        return
    if isinstance(data, dict):
        if "dataUrl" in data:
            url = data["dataUrl"]
            full_url = f"{BASE_URL}{url}" if url.startswith("/") else url
            try:
                async with async_timeout.timeout(15):
                    resp = await session.get(full_url, headers=HEADERS)
                    if resp.status != 200:
                        print(f"  [skip] {full_url} → HTTP {resp.status}")
                        if parent is not None and key is not None:
                            parent[key] = None
                        return
                    result = await resp.json(content_type=None)
                if parent is not None and key is not None:
                    parent[key] = result
                await expand_data_urls(session, result, parent=parent, key=key, _depth=_depth + 1)
            except Exception as exc:
                print(f"  [error] {full_url}: {exc}")
                if parent is not None and key is not None:
                    parent[key] = None
        else:
            for k in list(data.keys()):
                await expand_data_urls(session, data[k], parent=data, key=k, _depth=_depth)
    elif isinstance(data, list):
        for idx, item in enumerate(data):
            await expand_data_urls(session, item, parent=data, key=idx, _depth=_depth)


def inject_derived_fields(result_current, result_daily):
    """Apply the same post-fetch injections the coordinator does."""
    # Tomorrow's forecast from 7-day data
    try:
        all_days = (
            result_daily.get("layout", {})
            .get("primary", {})
            .get("slots", {})
            .get("main", {})
            .get("modules", [{}])[0]
            .get("days", [])
        )
        if len(all_days) > 1:
            tmrw = all_days[1]
            tf = (tmrw.get("forecasts") or [{}])[0]
            result_current["tomorrow_condition"] = tmrw.get("condition")
            result_current["tomorrow_temp_high"] = tf.get("highTemp")
            result_current["tomorrow_temp_low"] = tf.get("lowTemp")
            result_current["tomorrow_description"] = tf.get("statement")
    except Exception as exc:
        print(f"  [warn] tomorrow injection failed: {exc}")

    # Drying index parsing
    try:
        drying_states = None
        # Walk result_current looking for dryingState (simplified get_from_dict)
        def find_key(data, target, _d=0):
            if _d > 15:
                return None
            if isinstance(data, dict):
                if target in data:
                    return data[target]
                for v in data.values():
                    r = find_key(v, target, _d + 1)
                    if r is not None:
                        return r
            elif isinstance(data, list):
                for item in data:
                    r = find_key(item, target, _d + 1)
                    if r is not None:
                        return r
            return None

        drying_states = find_key(result_current, "dryingState")
        if isinstance(drying_states, list):
            drying_morning = drying_afternoon = drying_next_good_day = None
            for entry in drying_states:
                text = entry.get("text", "") if isinstance(entry, dict) else ""
                if text.startswith("Morning:"):
                    drying_morning = text.removeprefix("Morning:").strip()
                elif text.startswith("Afternoon:"):
                    drying_afternoon = text.removeprefix("Afternoon:").strip()
                elif text.lower().startswith("next good day"):
                    drying_next_good_day = text.split(":", 1)[-1].strip() if ":" in text else text
                elif text:
                    drying_morning = text
            if drying_afternoon is None and drying_morning is not None:
                drying_afternoon = drying_morning
            if drying_next_good_day is None:
                drying_next_good_day = "Today"
            result_current["drying_morning"] = drying_morning
            result_current["drying_afternoon"] = drying_afternoon
            result_current["drying_next_good_day"] = drying_next_good_day
    except Exception as exc:
        print(f"  [warn] drying injection failed: {exc}")


async def main():
    fixtures_dir = Path(__file__).parent.parent / "tests" / "fixtures"
    fixtures_dir.mkdir(parents=True, exist_ok=True)

    connector = aiohttp.TCPConnector(limit=10)
    async with aiohttp.ClientSession(connector=connector) as session:

        # 1. Current conditions
        url = f"{PUBLIC_URL}{LOCATION}"
        print(f"Fetching {url}")
        async with async_timeout.timeout(15):
            resp = await session.get(url, headers=HEADERS)
            resp.raise_for_status()
            result_current = await resp.json(content_type=None)

        print("Expanding dataUrls in result_current ...")
        await expand_data_urls(session, result_current)

        # 2. Warnings
        loc_type = result_current["location"]["type"]
        loc_key = result_current["location"]["key"]
        warn_url = f"{WARNINGS_URL}/{loc_type}/{loc_key}"
        print(f"Fetching warnings {warn_url}")
        async with async_timeout.timeout(15):
            resp = await session.get(warn_url, headers=HEADERS)
            result_warnings = await resp.json(content_type=None)
        await expand_data_urls(session, result_warnings)

        warnings_list = [
            f"{w['name']}, {w['text']}, {w['threatPeriod']}"
            for w in result_warnings.get("warnings", [])
        ]
        result_current["weather_warnings"] = (
            "\n".join(warnings_list) if warnings_list else "No warnings"
        )

        # 3. Pollen (best-effort)
        pollen_url = f"{PUBLIC_URL}{LOCATION}/airborne-allergens"
        print(f"Fetching pollen {pollen_url}")
        try:
            async with async_timeout.timeout(10):
                resp = await session.get(pollen_url, headers=HEADERS)
                if resp.status == 200:
                    result_pollen = await resp.json(content_type=None)
                    modules = (
                        result_pollen.get("layout", {})
                        .get("primary", {})
                        .get("slots", {})
                        .get("main", {})
                        .get("modules", [])
                    )
                    pollen_data = {"pollenLevels": {"level": None, "type": None}}
                    for module in modules:
                        for item in module.get("content", []):
                            if item.get("iconName") == "pollen" and "html" in item:
                                html = item["html"]
                                level_m = re.search(r'<span[^>]*class="status-[^"]*"[^>]*>([^<]+)</span>', html)
                                plants_m = re.search(r'</span>(?:<br\s*/?>|</br>)(.*?)(?:<br\s*/?>|</br>|$)', html, re.IGNORECASE)
                                pollen_data = {"pollenLevels": {
                                    "level": level_m.group(1).strip() if level_m else None,
                                    "type": plants_m.group(1).strip() if plants_m else None,
                                }}
                    result_current["pollen"] = pollen_data
        except Exception as exc:
            print(f"  [warn] pollen fetch failed: {exc}")
            result_current["pollen"] = {"pollenLevels": {"level": None, "type": None}}

        # 4. Daily forecast
        daily_url = f"{PUBLIC_URL}{LOCATION}/7-days"
        print(f"Fetching {daily_url}")
        async with async_timeout.timeout(15):
            resp = await session.get(daily_url, headers=HEADERS)
            resp.raise_for_status()
            result_daily = await resp.json(content_type=None)
        print("Expanding dataUrls in result_daily ...")
        await expand_data_urls(session, result_daily)

        # 5. Inject derived fields
        print("Injecting derived fields ...")
        inject_derived_fields(result_current, result_daily)

    # Save
    current_path = fixtures_dir / "napier_public_current.json"
    daily_path = fixtures_dir / "napier_public_daily.json"

    with open(current_path, "w", encoding="utf-8") as f:
        json.dump(result_current, f, indent=2, default=str)
    size_kb = current_path.stat().st_size / 1024
    print(f"\nSaved {current_path} ({size_kb:.0f} KB)")

    with open(daily_path, "w", encoding="utf-8") as f:
        json.dump(result_daily, f, indent=2, default=str)
    size_kb = daily_path.stat().st_size / 1024
    print(f"Saved {daily_path} ({size_kb:.0f} KB)")

    print("\nDone. Review fixture sizes before committing.")


if __name__ == "__main__":
    asyncio.run(main())
