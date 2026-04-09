"""
Swing high/low pivot detection.

A swing high = highest high in a window of (left + right) candles.
A swing low  = lowest  low  in a window of (left + right) candles.

The pivot is confirmed only after `right` bars have closed past it,
so the last `right` candles are always unconfirmed.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from ..data.candle import Candle


class SwingType(Enum):
    HIGH = "high"
    LOW = "low"


@dataclass(slots=True)
class SwingPoint:
    ts: datetime
    price: float
    kind: SwingType
    timeframe: int
    candle_index: int   # index in the buffer at time of detection
    is_strong: bool = False   # True if it caused a BOS later


class SwingDetector:
    """
    Detects confirmed swing highs and lows from a candle list.

    Parameters
    ----------
    left  : bars to the left that must be lower/higher
    right : bars to the right that must be lower/higher (confirmation delay)
    """

    def __init__(self, left: int = 5, right: int = 2):
        self.left = left
        self.right = right

    def detect(self, candles: list[Candle]) -> list[SwingPoint]:
        """
        Run on a full candle list. Returns all confirmed pivots.
        The last `right` candles cannot be confirmed yet.
        """
        pivots: list[SwingPoint] = []
        n = len(candles)
        if n < self.left + self.right + 1:
            return pivots

        for i in range(self.left, n - self.right):
            c = candles[i]
            window_left  = candles[i - self.left : i]
            window_right = candles[i + 1 : i + self.right + 1]

            # Swing High
            if (all(c.high >= x.high for x in window_left) and
                    all(c.high >= x.high for x in window_right)):
                pivots.append(SwingPoint(
                    ts=c.ts, price=c.high,
                    kind=SwingType.HIGH,
                    timeframe=c.timeframe,
                    candle_index=i,
                ))

            # Swing Low
            if (all(c.low <= x.low for x in window_left) and
                    all(c.low <= x.low for x in window_right)):
                pivots.append(SwingPoint(
                    ts=c.ts, price=c.low,
                    kind=SwingType.LOW,
                    timeframe=c.timeframe,
                    candle_index=i,
                ))

        return pivots

    def latest(self, candles: list[Candle], kind: SwingType) -> SwingPoint | None:
        """Return the most recent confirmed pivot of the given kind."""
        pivots = [p for p in self.detect(candles) if p.kind == kind]
        return pivots[-1] if pivots else None
