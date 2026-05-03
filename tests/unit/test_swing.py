from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from smc_bot.data.candle import Candle
from smc_bot.detectors.swing import SwingDetector, SwingType

NY = ZoneInfo("America/New_York")


def _candles(data, start=None):
    if start is None:
        start = datetime(2024, 1, 15, 9, 30, tzinfo=NY)
    return [
        Candle(timestamp=start + timedelta(minutes=i), open=o, high=h, low=l, close=c)
        for i, (o, h, l, c) in enumerate(data)
    ]


def test_swing_high_detected():
    candles = _candles([
        (100, 101, 99.5, 100.5),
        (100.5, 101.5, 100, 101),
        (101, 102, 100.5, 101.5),
        (101.5, 102.5, 101, 102),
        (102, 103, 101.5, 102.5),
        (102.5, 106, 102, 105),  # pivot high = 106
        (105, 105.5, 104, 104.5),
        (104.5, 105, 103.5, 104),
    ])

    det = SwingDetector(left=5, right=2, timeframe="1m")
    all_swings = []
    for c in candles:
        all_swings.extend(det.update(c))

    highs = [s for s in all_swings if s.type == SwingType.HIGH]
    assert len(highs) == 1
    assert highs[0].price == 106.0


def test_swing_low_detected():
    candles = _candles([
        (106, 107, 105, 105.5),
        (105.5, 106, 104.5, 105),
        (105, 105.5, 104, 104.5),
        (104.5, 105, 103.5, 104),
        (104, 104.5, 103, 103.5),
        (103.5, 104, 97, 97.5),  # pivot low = 97
        (97.5, 98.5, 97.5, 98),
        (98, 99, 97.5, 98.5),
    ])

    det = SwingDetector(left=5, right=2, timeframe="1m")
    all_swings = []
    for c in candles:
        all_swings.extend(det.update(c))

    lows = [s for s in all_swings if s.type == SwingType.LOW]
    assert len(lows) == 1
    assert lows[0].price == 97.0


def test_no_swing_with_insufficient_candles():
    candles = _candles([
        (100, 101, 99, 100.5),
        (100.5, 102, 100, 101.5),
    ])

    det = SwingDetector(left=5, right=2, timeframe="1m")
    all_swings = []
    for c in candles:
        all_swings.extend(det.update(c))

    assert len(all_swings) == 0


def test_htf_swing_parameters():
    candles = _candles([
        (100, 101, 99, 100.5),
        (100.5, 102, 100, 101.5),
        (101.5, 103, 101, 102.5),
        (102.5, 108, 102, 107),  # pivot high at index 3
        (107, 107.5, 106, 106.5),
    ])

    det = SwingDetector(left=3, right=1, timeframe="15m")
    all_swings = []
    for c in candles:
        all_swings.extend(det.update(c))

    highs = [s for s in all_swings if s.type == SwingType.HIGH]
    assert len(highs) == 1
    assert highs[0].price == 108.0
