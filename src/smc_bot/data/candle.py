from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from collections import deque


@dataclass(slots=True)
class Candle:
    ts: datetime      # bar open timestamp (UTC)
    open: float
    high: float
    low: float
    close: float
    volume: float
    timeframe: int    # minutes

    @property
    def bullish(self) -> bool:
        return self.close >= self.open

    @property
    def bearish(self) -> bool:
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


class CandleBuffer:
    """Fixed-size ring buffer for a single timeframe."""

    def __init__(self, timeframe: int, maxlen: int = 2000):
        self.timeframe = timeframe
        self._buf: deque[Candle] = deque(maxlen=maxlen)

    def push(self, candle: Candle) -> None:
        self._buf.append(candle)

    def __len__(self) -> int:
        return len(self._buf)

    def __getitem__(self, idx: int) -> Candle:
        return self._buf[idx]

    def latest(self, n: int = 1) -> list[Candle]:
        """Return last N candles, newest last."""
        return list(self._buf)[-n:]

    def as_list(self) -> list[Candle]:
        return list(self._buf)
