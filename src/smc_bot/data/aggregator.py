"""Aggregate 1-minute candles into higher timeframes."""
from __future__ import annotations
from datetime import datetime, timezone
from .candle import Candle, CandleBuffer


class MultiTFAggregator:
    """
    Feed 1m candles in; get buffers for all requested timeframes.
    Timeframes must be multiples of 1m.
    """

    def __init__(self, timeframes: list[int]):
        assert 1 in timeframes, "Must include 1m base timeframe"
        self.timeframes = sorted(timeframes)
        self.buffers: dict[int, CandleBuffer] = {
            tf: CandleBuffer(tf) for tf in timeframes
        }
        self._partials: dict[int, Candle | None] = {tf: None for tf in timeframes if tf > 1}

    def push(self, candle_1m: Candle) -> None:
        """Process a closed 1m candle. Updates all TF buffers."""
        assert candle_1m.timeframe == 1
        self.buffers[1].push(candle_1m)

        for tf in self.timeframes:
            if tf == 1:
                continue
            self._update_tf(tf, candle_1m)

    def _update_tf(self, tf: int, c1m: Candle) -> None:
        bar_start = self._bar_start(c1m.ts, tf)
        partial = self._partials[tf]

        if partial is None or partial.ts != bar_start:
            # New bar started — flush old partial
            if partial is not None:
                self.buffers[tf].push(partial)
            self._partials[tf] = Candle(
                ts=bar_start,
                open=c1m.open,
                high=c1m.high,
                low=c1m.low,
                close=c1m.close,
                volume=c1m.volume,
                timeframe=tf,
            )
        else:
            # Extend existing partial
            partial.high = max(partial.high, c1m.high)
            partial.low = min(partial.low, c1m.low)
            partial.close = c1m.close
            partial.volume += c1m.volume

    @staticmethod
    def _bar_start(ts: datetime, tf_minutes: int) -> datetime:
        minutes = ts.hour * 60 + ts.minute
        aligned = (minutes // tf_minutes) * tf_minutes
        return ts.replace(hour=aligned // 60, minute=aligned % 60, second=0, microsecond=0)

    def get(self, tf: int) -> CandleBuffer:
        return self.buffers[tf]
