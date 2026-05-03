from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from smc_bot.data.candle import Candle


class SwingType(Enum):
    HIGH = "high"
    LOW = "low"


class SwingStrength(Enum):
    STRONG = "strong"
    WEAK = "weak"


@dataclass(slots=True)
class SwingPoint:
    type: SwingType
    price: float
    timestamp: datetime
    timeframe: str
    index: int
    strength: SwingStrength = SwingStrength.WEAK

    def __hash__(self) -> int:
        return hash((self.type, self.price, self.timestamp, self.timeframe))


class SwingDetector:
    def __init__(self, left: int = 5, right: int = 2, timeframe: str = "1m"):
        self._left = left
        self._right = right
        self._timeframe = timeframe
        self._candles: list[Candle] = []
        self._swings: list[SwingPoint] = []
        self._index = 0

    @property
    def swings(self) -> list[SwingPoint]:
        return self._swings

    @property
    def swing_highs(self) -> list[SwingPoint]:
        return [s for s in self._swings if s.type == SwingType.HIGH]

    @property
    def swing_lows(self) -> list[SwingPoint]:
        return [s for s in self._swings if s.type == SwingType.LOW]

    def update(self, candle: Candle) -> list[SwingPoint]:
        self._candles.append(candle)
        self._index += 1
        new_swings: list[SwingPoint] = []

        if len(self._candles) < self._left + self._right + 1:
            return new_swings

        pivot_idx = len(self._candles) - 1 - self._right
        pivot = self._candles[pivot_idx]

        if self._is_swing_high(pivot_idx):
            sp = SwingPoint(
                type=SwingType.HIGH,
                price=pivot.high,
                timestamp=pivot.timestamp,
                timeframe=self._timeframe,
                index=pivot_idx,
            )
            self._swings.append(sp)
            new_swings.append(sp)
            self._update_strength()

        if self._is_swing_low(pivot_idx):
            sp = SwingPoint(
                type=SwingType.LOW,
                price=pivot.low,
                timestamp=pivot.timestamp,
                timeframe=self._timeframe,
                index=pivot_idx,
            )
            self._swings.append(sp)
            new_swings.append(sp)
            self._update_strength()

        return new_swings

    def _is_swing_high(self, idx: int) -> bool:
        pivot_high = self._candles[idx].high
        for i in range(idx - self._left, idx):
            if self._candles[i].high > pivot_high:
                return False
        for i in range(idx + 1, idx + self._right + 1):
            if self._candles[i].high > pivot_high:
                return False
        return True

    def _is_swing_low(self, idx: int) -> bool:
        pivot_low = self._candles[idx].low
        for i in range(idx - self._left, idx):
            if self._candles[i].low < pivot_low:
                return False
        for i in range(idx + 1, idx + self._right + 1):
            if self._candles[i].low < pivot_low:
                return False
        return True

    def _update_strength(self) -> None:
        highs = [s for s in self._swings if s.type == SwingType.HIGH]
        lows = [s for s in self._swings if s.type == SwingType.LOW]

        for i in range(len(highs) - 1):
            if len(highs) > i + 1 and highs[i + 1].price > highs[i].price:
                highs[i].strength = SwingStrength.STRONG

        for i in range(len(lows) - 1):
            if len(lows) > i + 1 and lows[i + 1].price < lows[i].price:
                lows[i].strength = SwingStrength.STRONG
