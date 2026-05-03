from __future__ import annotations

from datetime import datetime, timedelta

from smc_bot.data.candle import Candle, CandleBuffer

TIMEFRAME_MINUTES: dict[str, int] = {
    "1m": 1,
    "3m": 3,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1H": 60,
    "4H": 240,
}


def _align_timestamp(ts: datetime, minutes: int) -> datetime:
    epoch = datetime(ts.year, ts.month, ts.day, tzinfo=ts.tzinfo)
    total_minutes = (ts - epoch).total_seconds() / 60
    aligned_minutes = int(total_minutes // minutes) * minutes
    return epoch + timedelta(minutes=aligned_minutes)


class MultiTFAggregator:
    def __init__(self, timeframes: list[str] | None = None, buffer_size: int = 500):
        if timeframes is None:
            timeframes = list(TIMEFRAME_MINUTES.keys())
        self._timeframes = timeframes
        self._buffers: dict[str, CandleBuffer] = {
            tf: CandleBuffer(maxlen=buffer_size) for tf in timeframes
        }
        self._building: dict[str, Candle | None] = {tf: None for tf in timeframes}

    @property
    def timeframes(self) -> list[str]:
        return self._timeframes

    def get_buffer(self, timeframe: str) -> CandleBuffer:
        return self._buffers[timeframe]

    def feed(self, candle: Candle) -> dict[str, Candle | None]:
        completed: dict[str, Candle | None] = {}
        for tf in self._timeframes:
            minutes = TIMEFRAME_MINUTES[tf]
            if minutes == 1:
                self._buffers[tf].append(candle)
                completed[tf] = candle
                continue

            aligned = _align_timestamp(candle.timestamp, minutes)
            building = self._building[tf]

            if building is None or _align_timestamp(building.timestamp, minutes) != aligned:
                if building is not None:
                    self._buffers[tf].append(building)
                    completed[tf] = building
                else:
                    completed[tf] = None
                self._building[tf] = Candle(
                    timestamp=aligned,
                    open=candle.open,
                    high=candle.high,
                    low=candle.low,
                    close=candle.close,
                    volume=candle.volume,
                )
            else:
                building.high = max(building.high, candle.high)
                building.low = min(building.low, candle.low)
                building.close = candle.close
                building.volume += candle.volume
                completed[tf] = None

        return completed

    def flush(self) -> dict[str, Candle | None]:
        completed: dict[str, Candle | None] = {}
        for tf in self._timeframes:
            building = self._building[tf]
            if building is not None:
                self._buffers[tf].append(building)
                completed[tf] = building
                self._building[tf] = None
            else:
                completed[tf] = None
        return completed
