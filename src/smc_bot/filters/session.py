"""
Killzone (session) filter.

Only allows entries during active trading sessions (ET, auto-adjusts EST/EDT).
Sessions (ICT killzones, confirmed from CLAUDE.md + CoWork TFO observation):
  Asia:      19:00-21:00 ET
  London:    02:00-05:00 ET
  NY AM:     08:30-11:00 ET
  NY Lunch:  12:00-13:30 ET  (CoWork confirmed TFO shows this as 5th session)
  NY PM:     13:30-16:00 ET
"""
from __future__ import annotations
from datetime import datetime, time
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# (start, end) in ET
SESSIONS: dict[str, tuple[time, time]] = {
    "asia":      (time(19, 0),  time(21, 0)),
    "london":    (time(2, 0),   time(5, 0)),
    "ny_am":     (time(8, 30),  time(11, 0)),
    "ny_lunch":  (time(12, 0),  time(13, 30)),
    "ny_pm":     (time(13, 30), time(16, 0)),
}


def _in_session(t: time, start: time, end: time) -> bool:
    """Check if time t falls within [start, end). Handles midnight boundary."""
    if end == time(0, 0):          # "until midnight" — runs until 23:59:59
        return t >= start
    return start <= t < end


def active_session(ts: datetime) -> str | None:
    """Return the name of the active session at `ts` (ET), or None if outside all sessions."""
    et = ts.astimezone(ET)
    t = et.time()
    for name, (start, end) in SESSIONS.items():
        if _in_session(t, start, end):
            return name
    return None


def in_killzone(ts: datetime) -> bool:
    return active_session(ts) is not None
