"""
Killzone (session) filter.

Only allows entries during active trading sessions (ET, auto-adjusts EST/EDT).
Sessions:
  Asia:     20:00-00:00 ET (8pm to midnight)
  London:   02:00-05:00 ET
  NY AM:    09:30-11:00 ET
  NY PM:    13:00-16:00 ET
"""
from __future__ import annotations
from datetime import datetime, time
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# (start, end) in ET — end of time(0,0) means "until midnight" (special case)
SESSIONS: dict[str, tuple[time, time]] = {
    "asia":   (time(20, 0),  time(0, 0)),   # 8pm to midnight ET
    "london": (time(2, 0),   time(5, 0)),
    "ny_am":  (time(9, 30),  time(11, 0)),
    "ny_pm":  (time(13, 0),  time(16, 0)),
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
