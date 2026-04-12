"""
Killzone (session) filter.

Only allows entries during active trading sessions (ET, auto-adjusts EST/EDT).
Sessions (ICT killzones, confirmed from Pine Script IFVG Setup Detector + CoWork):
  Asia:      20:00-00:00 ET (crosses midnight — runs until midnight)
  London:    02:00-05:00 ET
  NY AM:     09:30-12:00 ET (opens at regular market open, not 08:30 pre-market)
  NY Lunch:  12:00-13:30 ET
  NY PM:     13:30-16:00 ET
"""
from __future__ import annotations
from datetime import datetime, time
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# (start, end) in ET
# Asia uses time(0, 0) as end to signal "runs until midnight" — handled by _in_session()
SESSIONS: dict[str, tuple[time, time]] = {
    "asia":      (time(20, 0),  time(0, 0)),   # 20:00 ET until midnight
    "london":    (time(2, 0),   time(5, 0)),
    "ny_am":     (time(9, 30),  time(12, 0)),   # regular market open, not 08:30
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


# HTF candle opens where manipulation commonly spikes (PO3 time aspect).
# Entering 1-5 min BEFORE these times destroys win rate — the HTF candle is about to
# open and will likely manipulate in one direction before distributing the other way.
_HTF_OPENS_ET: tuple[time, ...] = (
    time(9, 30),   # NY regular open — biggest PO3 source
    time(10, 0),   # 30-min candle boundary — frequent manipulation spike
    time(10, 30),  # another common 30m open
    time(15, 0),   # 30m boundary in NY PM
    time(15, 30),  # 30m boundary in NY PM
)
_HTF_OPEN_BLOCK_MINUTES = 5   # block entries this many minutes before each open


def near_htf_open(ts: datetime) -> bool:
    """
    Returns True if the timestamp is within _HTF_OPEN_BLOCK_MINUTES of a major
    HTF candle open. Entering here reduces win rate significantly because the
    next candle will likely manipulate (PO3 dynamic at these times).
    """
    et = ts.astimezone(ET)
    t = et.time()
    t_minutes = t.hour * 60 + t.minute
    for htf_open in _HTF_OPENS_ET:
        open_minutes = htf_open.hour * 60 + htf_open.minute
        if open_minutes - _HTF_OPEN_BLOCK_MINUTES <= t_minutes < open_minutes:
            return True
    return False
