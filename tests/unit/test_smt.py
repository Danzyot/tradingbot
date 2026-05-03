from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from smc_bot.detectors.smt import SMTDetector, SMTDirection
from smc_bot.detectors.swing import SwingPoint, SwingType

NY = ZoneInfo("America/New_York")
BASE = datetime(2024, 1, 15, 9, 30, tzinfo=NY)


def test_bullish_smt_divergence():
    """NQ makes lower low, ES doesn't → bullish SMT, trade ES"""
    nq_swings = [
        SwingPoint(type=SwingType.LOW, price=100.0, timestamp=BASE, timeframe="1m", index=5),
        SwingPoint(type=SwingType.LOW, price=99.0, timestamp=BASE + timedelta(minutes=10), timeframe="1m", index=15),
    ]
    es_swings = [
        SwingPoint(type=SwingType.LOW, price=50.0, timestamp=BASE, timeframe="1m", index=5),
        SwingPoint(type=SwingType.LOW, price=50.5, timestamp=BASE + timedelta(minutes=10), timeframe="1m", index=15),
    ]

    det = SMTDetector(instrument_a="NQ", instrument_b="ES", window_candles=3)
    divs = det.update_swings(nq_swings, es_swings)

    bullish = [d for d in divs if d.direction == SMTDirection.BULLISH]
    assert len(bullish) >= 1
    assert bullish[0].trade_instrument == "ES"


def test_bearish_smt_divergence():
    """NQ makes higher high, ES doesn't → bearish SMT"""
    nq_swings = [
        SwingPoint(type=SwingType.HIGH, price=100.0, timestamp=BASE, timeframe="1m", index=5),
        SwingPoint(type=SwingType.HIGH, price=101.0, timestamp=BASE + timedelta(minutes=10), timeframe="1m", index=15),
    ]
    es_swings = [
        SwingPoint(type=SwingType.HIGH, price=50.0, timestamp=BASE, timeframe="1m", index=5),
        SwingPoint(type=SwingType.HIGH, price=49.5, timestamp=BASE + timedelta(minutes=10), timeframe="1m", index=15),
    ]

    det = SMTDetector(instrument_a="NQ", instrument_b="ES", window_candles=3)
    divs = det.update_swings(nq_swings, es_swings)

    bearish = [d for d in divs if d.direction == SMTDirection.BEARISH]
    assert len(bearish) >= 1


def test_no_divergence_when_both_make_lower_low():
    """Both make lower low → no SMT"""
    nq_swings = [
        SwingPoint(type=SwingType.LOW, price=100.0, timestamp=BASE, timeframe="1m", index=5),
        SwingPoint(type=SwingType.LOW, price=99.0, timestamp=BASE + timedelta(minutes=10), timeframe="1m", index=15),
    ]
    es_swings = [
        SwingPoint(type=SwingType.LOW, price=50.0, timestamp=BASE, timeframe="1m", index=5),
        SwingPoint(type=SwingType.LOW, price=49.0, timestamp=BASE + timedelta(minutes=10), timeframe="1m", index=15),
    ]

    det = SMTDetector(instrument_a="NQ", instrument_b="ES", window_candles=3)
    divs = det.update_swings(nq_swings, es_swings)

    bullish = [d for d in divs if d.direction == SMTDirection.BULLISH]
    assert len(bullish) == 0
