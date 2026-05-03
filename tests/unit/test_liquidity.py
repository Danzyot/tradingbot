from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from smc_bot.detectors.liquidity import DOLTier, LiquidityDetector, LiquidityType
from smc_bot.detectors.swing import SwingPoint, SwingType

NY = ZoneInfo("America/New_York")
BASE = datetime(2024, 1, 15, 9, 30, tzinfo=NY)


def test_eqh_s_tier_detected():
    """Two highs at same price >3 candles apart → S tier"""
    swings = [
        SwingPoint(type=SwingType.HIGH, price=110.0, timestamp=BASE, timeframe="1m", index=5),
        SwingPoint(type=SwingType.HIGH, price=110.05, timestamp=BASE + timedelta(minutes=10), timeframe="1m", index=15),
    ]
    # diff = 0.05/110.025 * 100 = 0.045% < 0.1% tolerance
    # apart = 15 - 5 = 10 > 3 → S tier

    det = LiquidityDetector(tolerance_pct=0.1, min_candles_apart_s=3, min_candles_apart_a=1)
    levels = det.update_from_swings(swings)

    assert len(levels) == 1
    assert levels[0].type == LiquidityType.EQH
    assert levels[0].tier == DOLTier.S


def test_eql_a_tier_detected():
    """Two lows at same price 1-3 candles apart → A tier"""
    swings = [
        SwingPoint(type=SwingType.LOW, price=95.0, timestamp=BASE, timeframe="1m", index=5),
        SwingPoint(type=SwingType.LOW, price=95.05, timestamp=BASE + timedelta(minutes=2), timeframe="1m", index=7),
    ]
    # apart = 7 - 5 = 2, which is >= 1 but <= 3 → A tier

    det = LiquidityDetector(tolerance_pct=0.1, min_candles_apart_s=3, min_candles_apart_a=1)
    levels = det.update_from_swings(swings)

    assert len(levels) == 1
    assert levels[0].type == LiquidityType.EQL
    assert levels[0].tier == DOLTier.A


def test_no_eqh_when_prices_too_far_apart():
    """Prices differ by more than tolerance → no EQH"""
    swings = [
        SwingPoint(type=SwingType.HIGH, price=110.0, timestamp=BASE, timeframe="1m", index=5),
        SwingPoint(type=SwingType.HIGH, price=111.5, timestamp=BASE + timedelta(minutes=10), timeframe="1m", index=15),
    ]
    # diff = 1.5/110.75 * 100 = 1.35% > 0.1%

    det = LiquidityDetector(tolerance_pct=0.1)
    levels = det.update_from_swings(swings)

    assert len(levels) == 0
