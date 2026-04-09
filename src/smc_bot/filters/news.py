"""
High-impact news filter.

Blocks entries 30 minutes before and 15 minutes after red-folder USD events.
Fetches from ForexFactory or a local fallback JSON.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import json
import httpx

ET = ZoneInfo("America/New_York")
_CACHE: list["NewsEvent"] = []
_CACHE_DATE: datetime | None = None


@dataclass
class NewsEvent:
    ts: datetime        # event time (UTC)
    title: str
    impact: str         # "High", "Medium", "Low"
    currency: str


def is_blocked(ts: datetime, pre_min: int = 30, post_min: int = 15) -> bool:
    """Return True if `ts` falls within a news blackout window."""
    events = _get_events()
    for ev in events:
        if ev.impact != "High" or ev.currency != "USD":
            continue
        window_start = ev.ts - timedelta(minutes=pre_min)
        window_end   = ev.ts + timedelta(minutes=post_min)
        if window_start <= ts <= window_end:
            return True
    return False


def _get_events() -> list[NewsEvent]:
    global _CACHE, _CACHE_DATE
    now = datetime.utcnow()
    # Refresh cache once per day
    if _CACHE_DATE and (now - _CACHE_DATE).total_seconds() < 86400:
        return _CACHE
    try:
        _CACHE = _fetch_forexfactory()
        _CACHE_DATE = now
    except Exception:
        # If fetch fails, use existing cache or empty list
        pass
    return _CACHE


def _fetch_forexfactory() -> list[NewsEvent]:
    """
    Fetch this week's calendar from ForexFactory JSON endpoint.
    Falls back to empty list on failure.
    """
    try:
        resp = httpx.get(
            "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
            timeout=10,
        )
        resp.raise_for_status()
        raw = resp.json()
        events = []
        for item in raw:
            try:
                ts_str = item.get("date", "") + " " + item.get("time", "12:00am")
                ts = datetime.strptime(ts_str.strip(), "%Y-%m-%dT%H:%M:%S%z")
                events.append(NewsEvent(
                    ts=ts,
                    title=item.get("title", ""),
                    impact=item.get("impact", "Low"),
                    currency=item.get("country", ""),
                ))
            except Exception:
                continue
        return events
    except Exception:
        return []


def load_from_file(path: str) -> None:
    """Load events from a local JSON file (backup/offline mode)."""
    global _CACHE, _CACHE_DATE
    with open(path) as f:
        raw = json.load(f)
    _CACHE = [
        NewsEvent(
            ts=datetime.fromisoformat(e["ts"]),
            title=e["title"],
            impact=e["impact"],
            currency=e["currency"],
        )
        for e in raw
    ]
    _CACHE_DATE = datetime.utcnow()
