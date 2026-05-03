from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from smc_bot.data.candle import Candle


class FVGDirection(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"


@dataclass
class FVG:
    direction: FVGDirection
    high: float
    low: float
    timestamp: datetime
    timeframe: str
    index: int
    mitigated: bool = False
    mitigation_timestamp: datetime | None = None

    @property
    def ce(self) -> float:
        return (self.high + self.low) / 2

    @property
    def size(self) -> float:
        return self.high - self.low


class FVGDetector:
    def __init__(self, timeframe: str = "1m"):
        self._timeframe = timeframe
        self._candles: list[Candle] = []
        self._fvgs: list[FVG] = []

    @property
    def fvgs(self) -> list[FVG]:
        return self._fvgs

    @property
    def unmitigated(self) -> list[FVG]:
        return [f for f in self._fvgs if not f.mitigated]

    def update(self, candle: Candle) -> list[FVG]:
        self._candles.append(candle)
        new_fvgs: list[FVG] = []

        if len(self._candles) < 3:
            return new_fvgs

        c0 = self._candles[-3]
        c1 = self._candles[-2]
        c2 = self._candles[-1]

        if c0.high < c2.low:
            fvg = FVG(
                direction=FVGDirection.BULLISH,
                high=c2.low,
                low=c0.high,
                timestamp=c1.timestamp,
                timeframe=self._timeframe,
                index=len(self._candles) - 2,
            )
            self._fvgs.append(fvg)
            new_fvgs.append(fvg)

        if c0.low > c2.high:
            fvg = FVG(
                direction=FVGDirection.BEARISH,
                high=c0.low,
                low=c2.high,
                timestamp=c1.timestamp,
                timeframe=self._timeframe,
                index=len(self._candles) - 2,
            )
            self._fvgs.append(fvg)
            new_fvgs.append(fvg)

        self._check_mitigation(candle)
        return new_fvgs

    def _check_mitigation(self, candle: Candle) -> None:
        for fvg in self._fvgs:
            if fvg.mitigated:
                continue
            if fvg.direction == FVGDirection.BULLISH:
                if candle.low <= fvg.ce:
                    fvg.mitigated = True
                    fvg.mitigation_timestamp = candle.timestamp
            else:
                if candle.high >= fvg.ce:
                    fvg.mitigated = True
                    fvg.mitigation_timestamp = candle.timestamp
