from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from smc_bot.data.candle import Candle
from smc_bot.detectors.liquidity import DOLTier, LiquidityLevel, LiquidityType
from smc_bot.detectors.sweep import SweepDetector, SweepDirection

NY = ZoneInfo("America/New_York")
BASE = datetime(2024, 1, 15, 9, 30, tzinfo=NY)


def test_bullish_sweep_wick_below_body_above():
    """Bullish sweep: wick goes below level, body stays above"""
    level = LiquidityLevel(
        price=100.0, type=LiquidityType.EQL, tier=DOLTier.S, timestamp=BASE
    )

    candle = Candle(
        timestamp=BASE + timedelta(minutes=5),
        open=101.0,
        high=102.0,
        low=99.5,    # wick below 100
        close=101.5, # body_low = min(101, 101.5) = 101 > 100
    )

    det = SweepDetector(cooldown_minutes=5)
    sweeps = det.update(candle, [level])

    assert len(sweeps) == 1
    assert sweeps[0].direction == SweepDirection.BULLISH
    assert level.swept is True


def test_bearish_sweep_wick_above_body_below():
    """Bearish sweep: wick goes above level, body stays below"""
    level = LiquidityLevel(
        price=110.0, type=LiquidityType.EQH, tier=DOLTier.A, timestamp=BASE
    )

    candle = Candle(
        timestamp=BASE + timedelta(minutes=5),
        open=109.0,
        high=110.5,  # wick above 110
        low=108.5,
        close=109.5, # body_high = max(109, 109.5) = 109.5 < 110
    )

    det = SweepDetector(cooldown_minutes=5)
    sweeps = det.update(candle, [level])

    assert len(sweeps) == 1
    assert sweeps[0].direction == SweepDirection.BEARISH


def test_no_sweep_when_body_closes_beyond():
    """Not a sweep if body closes beyond the level"""
    level = LiquidityLevel(
        price=100.0, type=LiquidityType.EQL, tier=DOLTier.S, timestamp=BASE
    )

    candle = Candle(
        timestamp=BASE + timedelta(minutes=5),
        open=101.0,
        high=102.0,
        low=99.5,
        close=99.8,  # body_low = min(101, 99.8) = 99.8 < 100 → not a sweep
    )

    det = SweepDetector(cooldown_minutes=5)
    sweeps = det.update(candle, [level])

    assert len(sweeps) == 0


def test_f_tier_ignored():
    """F-tier levels are never swept"""
    level = LiquidityLevel(
        price=100.0, type=LiquidityType.EQL, tier=DOLTier.F, timestamp=BASE
    )

    candle = Candle(
        timestamp=BASE + timedelta(minutes=5),
        open=101.0, high=102.0, low=99.5, close=101.5,
    )

    det = SweepDetector(cooldown_minutes=5)
    sweeps = det.update(candle, [level])

    assert len(sweeps) == 0


def test_cooldown_respected():
    """Second sweep within cooldown is ignored"""
    level1 = LiquidityLevel(price=100.0, type=LiquidityType.EQL, tier=DOLTier.S, timestamp=BASE)
    level2 = LiquidityLevel(price=99.0, type=LiquidityType.PDL, tier=DOLTier.B, timestamp=BASE)

    candle1 = Candle(timestamp=BASE + timedelta(minutes=5), open=101, high=102, low=99.5, close=101.5)
    candle2 = Candle(timestamp=BASE + timedelta(minutes=6), open=100, high=101, low=98.5, close=100.5)

    det = SweepDetector(cooldown_minutes=5)
    sweeps1 = det.update(candle1, [level1, level2])
    sweeps2 = det.update(candle2, [level2])

    assert len(sweeps1) == 1
    assert len(sweeps2) == 0  # within cooldown
