from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from smc_bot.data.candle import Candle
from smc_bot.detectors.liquidity import DOLTier, LiquidityLevel, LiquidityType


@dataclass
class Gap:
    high: float
    low: float
    type: str
    timestamp: datetime

    @property
    def ce(self) -> float:
        return (self.high + self.low) / 2


class NWOGNDOGDetector:
    def __init__(self, timezone: str = "America/New_York"):
        self._tz = ZoneInfo(timezone)
        self._gaps: list[Gap] = []
        self._prev_close: float | None = None
        self._prev_close_time: datetime | None = None
        self._friday_close: float | None = None
        self._current_date = None

    @property
    def gaps(self) -> list[Gap]:
        return self._gaps

    def update(self, candle: Candle) -> list[LiquidityLevel]:
        new_levels: list[LiquidityLevel] = []
        ny_time = candle.timestamp.astimezone(self._tz)
        candle_date = ny_time.date()
        candle_time = ny_time.time()

        close_time = time(17, 0)
        open_time = time(18, 0)

        if candle_time >= close_time and (
            self._prev_close_time is None
            or candle.timestamp > self._prev_close_time
        ):
            if self._current_date != candle_date or self._prev_close is None:
                if self._prev_close is not None and candle_time >= open_time:
                    gap_high = max(self._prev_close, candle.open)
                    gap_low = min(self._prev_close, candle.open)

                    if gap_high != gap_low:
                        weekday = ny_time.weekday()
                        if weekday == 0 and self._friday_close is not None:
                            gap_high = max(self._friday_close, candle.open)
                            gap_low = min(self._friday_close, candle.open)
                            gap = Gap(
                                high=gap_high,
                                low=gap_low,
                                type="NWOG",
                                timestamp=candle.timestamp,
                            )
                            self._gaps.append(gap)
                            new_levels.extend(self._gap_to_levels(gap, is_weekly=True, ts=candle.timestamp))
                        else:
                            gap = Gap(
                                high=gap_high,
                                low=gap_low,
                                type="NDOG",
                                timestamp=candle.timestamp,
                            )
                            self._gaps.append(gap)
                            new_levels.extend(self._gap_to_levels(gap, is_weekly=False, ts=candle.timestamp))

                if ny_time.weekday() == 4:
                    self._friday_close = candle.close

                self._prev_close = candle.close
                self._prev_close_time = candle.timestamp
                self._current_date = candle_date

        return new_levels

    def _gap_to_levels(
        self, gap: Gap, is_weekly: bool, ts: datetime
    ) -> list[LiquidityLevel]:
        if is_weekly:
            high_type = LiquidityType.NWOG_HIGH
            low_type = LiquidityType.NWOG_LOW
        else:
            high_type = LiquidityType.NDOG_HIGH
            low_type = LiquidityType.NDOG_LOW

        return [
            LiquidityLevel(price=gap.high, type=high_type, tier=DOLTier.B, timestamp=ts),
            LiquidityLevel(price=gap.low, type=low_type, tier=DOLTier.B, timestamp=ts),
        ]
