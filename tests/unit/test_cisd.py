from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from smc_bot.data.candle import Candle
from smc_bot.detectors.cisd import CISDDetector, CISDDirection

NY = ZoneInfo("America/New_York")
BASE = datetime(2024, 1, 15, 9, 30, tzinfo=NY)


def test_bullish_cisd():
    """Body closes above open of prior bearish candle"""
    candles = [
        Candle(timestamp=BASE, open=105.0, high=106.0, low=103.0, close=103.5),  # bearish: open=105
        Candle(timestamp=BASE + timedelta(minutes=1), open=103.5, high=106.0, low=103.0, close=105.5),  # body_high=105.5 > 105
    ]

    det = CISDDetector(timeframe="1m")
    all_cisds = []
    for c in candles:
        all_cisds.extend(det.update(c))

    bullish = [c for c in all_cisds if c.direction == CISDDirection.BULLISH]
    assert len(bullish) == 1
    assert bullish[0].broken_candle_open == 105.0


def test_bearish_cisd():
    """Body closes below open of prior bullish candle"""
    candles = [
        Candle(timestamp=BASE, open=100.0, high=103.0, low=99.5, close=102.5),  # bullish: open=100
        Candle(timestamp=BASE + timedelta(minutes=1), open=102.5, high=103.0, low=99.0, close=99.5),  # body_low=99.5 < 100
    ]

    det = CISDDetector(timeframe="1m")
    all_cisds = []
    for c in candles:
        all_cisds.extend(det.update(c))

    bearish = [c for c in all_cisds if c.direction == CISDDirection.BEARISH]
    assert len(bearish) == 1
    assert bearish[0].broken_candle_open == 100.0


def test_no_cisd_wick_only():
    """Wick through open doesn't count"""
    candles = [
        Candle(timestamp=BASE, open=105.0, high=106.0, low=103.0, close=103.5),  # bearish
        Candle(timestamp=BASE + timedelta(minutes=1), open=103.5, high=105.5, low=103.0, close=104.5),
        # body_high = max(103.5, 104.5) = 104.5 < 105.0 → no CISD
    ]

    det = CISDDetector(timeframe="1m")
    all_cisds = []
    for c in candles:
        all_cisds.extend(det.update(c))

    bullish = [c for c in all_cisds if c.direction == CISDDirection.BULLISH]
    assert len(bullish) == 0
