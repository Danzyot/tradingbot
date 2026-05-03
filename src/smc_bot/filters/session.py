from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo


KILLZONES: dict[str, tuple[time, time]] = {
    "asia": (time(20, 0), time(0, 0)),
    "london": (time(2, 0), time(5, 0)),
    "ny_am": (time(9, 30), time(11, 30)),
    "ny_pm": (time(13, 0), time(16, 0)),
}


class SessionFilter:
    def __init__(self, timezone: str = "America/New_York", killzones: dict[str, tuple[time, time]] | None = None):
        self._tz = ZoneInfo(timezone)
        self._killzones = killzones or KILLZONES

    def is_in_killzone(self, timestamp: datetime) -> bool:
        return self.get_active_killzone(timestamp) is not None

    def get_active_killzone(self, timestamp: datetime) -> str | None:
        ny_time = timestamp.astimezone(self._tz).time()

        for name, (start, end) in self._killzones.items():
            if start > end:
                if ny_time >= start or ny_time < end:
                    return name
            else:
                if start <= ny_time < end:
                    return name
        return None

    def is_trading_day(self, timestamp: datetime) -> bool:
        ny_dt = timestamp.astimezone(self._tz)
        return ny_dt.weekday() < 5
