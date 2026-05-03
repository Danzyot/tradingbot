from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open

    @property
    def body_high(self) -> float:
        return max(self.open, self.close)

    @property
    def body_low(self) -> float:
        return min(self.open, self.close)

    @property
    def body_size(self) -> float:
        return abs(self.close - self.open)

    @property
    def upper_wick(self) -> float:
        return self.high - self.body_high

    @property
    def lower_wick(self) -> float:
        return self.body_low - self.low

    @property
    def total_range(self) -> float:
        return self.high - self.low


class CandleBuffer:
    def __init__(self, maxlen: int = 500):
        self._candles: deque[Candle] = deque(maxlen=maxlen)

    def append(self, candle: Candle) -> None:
        self._candles.append(candle)

    def __len__(self) -> int:
        return len(self._candles)

    def __getitem__(self, idx: int | slice) -> Candle | list[Candle]:
        if isinstance(idx, slice):
            return list(self._candles)[idx]
        return self._candles[idx]

    @property
    def last(self) -> Candle | None:
        return self._candles[-1] if self._candles else None

    def get_last_n(self, n: int) -> list[Candle]:
        if n >= len(self._candles):
            return list(self._candles)
        return list(self._candles)[-n:]
