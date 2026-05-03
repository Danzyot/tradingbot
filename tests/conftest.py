from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from smc_bot.data.candle import Candle


NY = ZoneInfo("America/New_York")


def make_candle(
    open: float,
    high: float,
    low: float,
    close: float,
    timestamp: datetime | None = None,
    volume: float = 100.0,
) -> Candle:
    if timestamp is None:
        timestamp = datetime(2024, 1, 15, 9, 30, tzinfo=NY)
    return Candle(
        timestamp=timestamp,
        open=open,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def make_candle_sequence(
    data: list[tuple[float, float, float, float]],
    start: datetime | None = None,
    interval_minutes: int = 1,
) -> list[Candle]:
    if start is None:
        start = datetime(2024, 1, 15, 9, 30, tzinfo=NY)

    candles = []
    for i, (o, h, l, c) in enumerate(data):
        ts = start + timedelta(minutes=i * interval_minutes)
        candles.append(Candle(timestamp=ts, open=o, high=h, low=l, close=c, volume=100.0))
    return candles


@pytest.fixture
def ny_tz():
    return NY


@pytest.fixture
def base_timestamp():
    return datetime(2024, 1, 15, 9, 30, tzinfo=NY)


@pytest.fixture
def bullish_fvg_candles(base_timestamp):
    """3 candles that form a bullish FVG: candle[0].high < candle[2].low"""
    return make_candle_sequence(
        [
            (100.0, 101.0, 99.0, 100.5),   # candle 0: high = 101
            (100.5, 103.0, 100.0, 102.5),   # candle 1: impulse
            (102.5, 104.0, 101.5, 103.5),   # candle 2: low = 101.5 > 101 (candle 0 high)
        ],
        start=base_timestamp,
    )


@pytest.fixture
def bearish_fvg_candles(base_timestamp):
    """3 candles that form a bearish FVG: candle[0].low > candle[2].high"""
    return make_candle_sequence(
        [
            (103.0, 104.0, 102.0, 103.5),   # candle 0: low = 102
            (103.5, 103.5, 100.0, 100.5),   # candle 1: impulse down
            (100.5, 101.5, 99.0, 100.0),    # candle 2: high = 101.5 < 102 (candle 0 low)
        ],
        start=base_timestamp,
    )


@pytest.fixture
def swing_high_candles(base_timestamp):
    """Sequence with a clear swing high at index 5 (left=5, right=2)"""
    return make_candle_sequence(
        [
            (100.0, 101.0, 99.5, 100.5),
            (100.5, 101.5, 100.0, 101.0),
            (101.0, 102.0, 100.5, 101.5),
            (101.5, 102.5, 101.0, 102.0),
            (102.0, 103.0, 101.5, 102.5),
            (102.5, 105.0, 102.0, 104.0),  # swing high at 105.0
            (104.0, 104.5, 103.0, 103.5),
            (103.5, 104.0, 102.5, 103.0),  # confirmed after right=2
        ],
        start=base_timestamp,
    )


@pytest.fixture
def swing_low_candles(base_timestamp):
    """Sequence with a clear swing low at index 5 (left=5, right=2)"""
    return make_candle_sequence(
        [
            (105.0, 105.5, 104.0, 104.5),
            (104.5, 105.0, 103.5, 104.0),
            (104.0, 104.5, 103.0, 103.5),
            (103.5, 104.0, 102.5, 103.0),
            (103.0, 103.5, 102.0, 102.5),
            (102.5, 103.0, 99.0, 99.5),   # swing low at 99.0
            (99.5, 100.5, 99.5, 100.0),
            (100.0, 101.0, 99.5, 100.5),  # confirmed
        ],
        start=base_timestamp,
    )
