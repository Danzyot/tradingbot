from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from smc_bot.data.candle import Candle
from smc_bot.detectors.fvg import FVGDetector, FVGDirection

NY = ZoneInfo("America/New_York")


def _candles(data, start=None):
    if start is None:
        start = datetime(2024, 1, 15, 9, 30, tzinfo=NY)
    return [
        Candle(timestamp=start + timedelta(minutes=i), open=o, high=h, low=l, close=c)
        for i, (o, h, l, c) in enumerate(data)
    ]


def test_bullish_fvg_detected():
    candles = _candles([
        (100, 101, 99, 100.5),    # high = 101
        (100.5, 104, 100, 103.5), # impulse up
        (103.5, 105, 102, 104.5), # low = 102 > 101 (candle 0 high) → bullish FVG
    ])

    det = FVGDetector(timeframe="1m")
    all_fvgs = []
    for c in candles:
        all_fvgs.extend(det.update(c))

    assert len(all_fvgs) == 1
    fvg = all_fvgs[0]
    assert fvg.direction == FVGDirection.BULLISH
    assert fvg.low == 101.0   # candle[0].high
    assert fvg.high == 102.0  # candle[2].low
    assert fvg.ce == 101.5


def test_bearish_fvg_detected():
    candles = _candles([
        (105, 106, 104, 104.5),  # low = 104
        (104.5, 105, 101, 101.5), # impulse down
        (101.5, 103, 100, 102),   # high = 103 < 104 (candle 0 low) → bearish FVG
    ])

    det = FVGDetector(timeframe="1m")
    all_fvgs = []
    for c in candles:
        all_fvgs.extend(det.update(c))

    assert len(all_fvgs) == 1
    fvg = all_fvgs[0]
    assert fvg.direction == FVGDirection.BEARISH
    assert fvg.high == 104.0  # candle[0].low
    assert fvg.low == 103.0   # candle[2].high


def test_no_fvg_when_no_gap():
    candles = _candles([
        (100, 102, 99, 101),
        (101, 103, 100.5, 102.5),
        (102.5, 103, 101.5, 102),  # low=101.5, candle[0].high=102. 101.5 < 102, no gap
    ])

    det = FVGDetector(timeframe="1m")
    all_fvgs = []
    for c in candles:
        all_fvgs.extend(det.update(c))

    assert len(all_fvgs) == 0


def test_fvg_mitigation():
    candles = _candles([
        (100, 101, 99, 100.5),
        (100.5, 104, 100, 103.5),
        (103.5, 105, 102, 104.5),  # bullish FVG: low=101, high=102, CE=101.5
        (104.5, 105, 101.5, 101.8), # retraces to CE (101.5) → mitigated
    ])

    det = FVGDetector(timeframe="1m")
    for c in candles:
        det.update(c)

    assert len(det.fvgs) == 1
    assert det.fvgs[0].mitigated is True
    assert len(det.unmitigated) == 0
