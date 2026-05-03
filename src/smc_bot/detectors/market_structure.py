from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from smc_bot.detectors.swing import SwingPoint, SwingType


class Bias(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


@dataclass
class StructureBreak:
    bias: Bias
    price: float
    timestamp: datetime
    broken_swing: SwingPoint


class MarketStructureDetector:
    def __init__(self):
        self._bias: Bias = Bias.NEUTRAL
        self._breaks: list[StructureBreak] = []
        self._last_high: SwingPoint | None = None
        self._last_low: SwingPoint | None = None

    @property
    def bias(self) -> Bias:
        return self._bias

    @property
    def breaks(self) -> list[StructureBreak]:
        return self._breaks

    def update(self, swing: SwingPoint) -> StructureBreak | None:
        if swing.type == SwingType.HIGH:
            if self._last_high is not None and swing.price > self._last_high.price:
                if self._bias != Bias.BULLISH:
                    brk = StructureBreak(
                        bias=Bias.BULLISH,
                        price=swing.price,
                        timestamp=swing.timestamp,
                        broken_swing=self._last_high,
                    )
                    self._breaks.append(brk)
                    self._bias = Bias.BULLISH
                    self._last_high = swing
                    return brk
            self._last_high = swing

        elif swing.type == SwingType.LOW:
            if self._last_low is not None and swing.price < self._last_low.price:
                if self._bias != Bias.BEARISH:
                    brk = StructureBreak(
                        bias=Bias.BEARISH,
                        price=swing.price,
                        timestamp=swing.timestamp,
                        broken_swing=self._last_low,
                    )
                    self._breaks.append(brk)
                    self._bias = Bias.BEARISH
                    self._last_low = swing
                    return brk
            self._last_low = swing

        return None
