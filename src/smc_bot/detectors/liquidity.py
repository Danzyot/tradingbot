from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from enum import Enum
from zoneinfo import ZoneInfo

from smc_bot.data.candle import Candle
from smc_bot.detectors.swing import SwingPoint, SwingType


class DOLTier(Enum):
    S = "S"
    A = "A"
    B = "B"
    C = "C"
    F = "F"


class LiquidityType(Enum):
    EQH = "eqh"
    EQL = "eql"
    PDH = "pdh"
    PDL = "pdl"
    SESSION_HIGH = "session_high"
    SESSION_LOW = "session_low"
    NWOG_HIGH = "nwog_high"
    NWOG_LOW = "nwog_low"
    NDOG_HIGH = "ndog_high"
    NDOG_LOW = "ndog_low"
    UNMITIGATED_FVG = "unmitigated_fvg"
    WEAK_HIGH = "weak_high"
    WEAK_LOW = "weak_low"


@dataclass
class LiquidityLevel:
    price: float
    type: LiquidityType
    tier: DOLTier
    timestamp: datetime
    swept: bool = False
    sweep_timestamp: datetime | None = None


class LiquidityDetector:
    def __init__(
        self,
        tolerance_pct: float = 0.1,
        min_candles_apart_s: int = 3,
        min_candles_apart_a: int = 1,
        timezone: str = "America/New_York",
    ):
        self._tolerance_pct = tolerance_pct
        self._min_candles_s = min_candles_apart_s
        self._min_candles_a = min_candles_apart_a
        self._tz = ZoneInfo(timezone)
        self._levels: list[LiquidityLevel] = []
        self._daily_high: float | None = None
        self._daily_low: float | None = None
        self._prev_daily_high: float | None = None
        self._prev_daily_low: float | None = None
        self._session_highs: dict[str, float] = {}
        self._session_lows: dict[str, float] = {}
        self._current_date: datetime | None = None

    @property
    def levels(self) -> list[LiquidityLevel]:
        return self._levels

    @property
    def unswept(self) -> list[LiquidityLevel]:
        return [lv for lv in self._levels if not lv.swept]

    def update_from_swings(self, swings: list[SwingPoint]) -> list[LiquidityLevel]:
        new_levels: list[LiquidityLevel] = []

        highs = [s for s in swings if s.type == SwingType.HIGH]
        lows = [s for s in swings if s.type == SwingType.LOW]

        new_levels.extend(self._detect_equal_levels(highs, LiquidityType.EQH))
        new_levels.extend(self._detect_equal_levels(lows, LiquidityType.EQL))

        for level in new_levels:
            if not self._level_exists(level):
                self._levels.append(level)

        return new_levels

    def update_daily(self, candle: Candle) -> list[LiquidityLevel]:
        new_levels: list[LiquidityLevel] = []
        candle_date = candle.timestamp.astimezone(self._tz).date()

        if self._current_date is None:
            self._current_date = candle_date
            self._daily_high = candle.high
            self._daily_low = candle.low
            return new_levels

        if candle_date != self._current_date:
            self._prev_daily_high = self._daily_high
            self._prev_daily_low = self._daily_low

            if self._prev_daily_high is not None:
                pdh = LiquidityLevel(
                    price=self._prev_daily_high,
                    type=LiquidityType.PDH,
                    tier=DOLTier.B,
                    timestamp=candle.timestamp,
                )
                self._levels.append(pdh)
                new_levels.append(pdh)

            if self._prev_daily_low is not None:
                pdl = LiquidityLevel(
                    price=self._prev_daily_low,
                    type=LiquidityType.PDL,
                    tier=DOLTier.B,
                    timestamp=candle.timestamp,
                )
                self._levels.append(pdl)
                new_levels.append(pdl)

            self._current_date = candle_date
            self._daily_high = candle.high
            self._daily_low = candle.low
            self._session_highs.clear()
            self._session_lows.clear()
        else:
            if candle.high > (self._daily_high or 0):
                self._daily_high = candle.high
            if candle.low < (self._daily_low or float("inf")):
                self._daily_low = candle.low

        return new_levels

    def add_session_level(
        self, price: float, liq_type: LiquidityType, timestamp: datetime
    ) -> None:
        level = LiquidityLevel(
            price=price, type=liq_type, tier=DOLTier.B, timestamp=timestamp
        )
        if not self._level_exists(level):
            self._levels.append(level)

    def add_gap_level(
        self, price: float, liq_type: LiquidityType, timestamp: datetime
    ) -> None:
        level = LiquidityLevel(
            price=price, type=liq_type, tier=DOLTier.B, timestamp=timestamp
        )
        if not self._level_exists(level):
            self._levels.append(level)

    def mark_swept(self, level: LiquidityLevel, timestamp: datetime) -> None:
        level.swept = True
        level.sweep_timestamp = timestamp

    def _detect_equal_levels(
        self, points: list[SwingPoint], liq_type: LiquidityType
    ) -> list[LiquidityLevel]:
        levels: list[LiquidityLevel] = []
        if len(points) < 2:
            return levels

        for i in range(len(points) - 1):
            for j in range(i + 1, len(points)):
                p1, p2 = points[i], points[j]
                avg = (p1.price + p2.price) / 2
                diff_pct = abs(p1.price - p2.price) / avg * 100

                if diff_pct <= self._tolerance_pct:
                    candles_apart = abs(p2.index - p1.index)
                    if candles_apart > self._min_candles_s:
                        tier = DOLTier.S
                    elif candles_apart >= self._min_candles_a:
                        tier = DOLTier.A
                    else:
                        continue

                    level = LiquidityLevel(
                        price=avg,
                        type=liq_type,
                        tier=tier,
                        timestamp=p2.timestamp,
                    )
                    levels.append(level)

        return levels

    def _level_exists(self, new_level: LiquidityLevel) -> bool:
        for existing in self._levels:
            if existing.type == new_level.type:
                avg = (existing.price + new_level.price) / 2
                if avg == 0:
                    continue
                diff_pct = abs(existing.price - new_level.price) / avg * 100
                if diff_pct <= self._tolerance_pct:
                    return True
        return False
