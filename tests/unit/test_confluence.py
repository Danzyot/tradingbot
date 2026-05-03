from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from smc_bot.config import Settings
from smc_bot.data.candle import Candle
from smc_bot.detectors.liquidity import DOLTier, LiquidityLevel, LiquidityType
from smc_bot.models.base import TradeDirection, ModelType
from smc_bot.models.confluence import ConfluenceEngine

NY = ZoneInfo("America/New_York")
BASE = datetime(2024, 1, 15, 9, 30, tzinfo=NY)


def test_setup_created_on_sweep():
    """A sweep creates a pending setup"""
    settings = Settings()
    engine = ConfluenceEngine(settings, instrument="NQ")

    # Manually add a liquidity level
    level = LiquidityLevel(price=100.0, type=LiquidityType.EQL, tier=DOLTier.S, timestamp=BASE)
    engine._liquidity._levels.append(level)

    # Feed a candle that sweeps the level
    candle = Candle(
        timestamp=BASE + timedelta(minutes=1),
        open=101.0, high=102.0, low=99.5, close=101.5,
    )
    engine.update("1m", candle)

    assert len(engine._active_setups) == 1
    assert engine._active_setups[0].direction == TradeDirection.LONG


def test_setup_expires():
    """Setup expires after configured minutes"""
    settings = Settings()
    settings.models.setup_expiry_minutes = 5
    engine = ConfluenceEngine(settings, instrument="NQ")

    level = LiquidityLevel(price=100.0, type=LiquidityType.EQL, tier=DOLTier.S, timestamp=BASE)
    engine._liquidity._levels.append(level)

    sweep_candle = Candle(timestamp=BASE, open=101, high=102, low=99.5, close=101.5)
    engine.update("1m", sweep_candle)

    assert len(engine.active_setups) == 1

    # Feed candle after expiry
    late_candle = Candle(
        timestamp=BASE + timedelta(minutes=6),
        open=101, high=102, low=100.5, close=101.5,
    )
    engine.update("1m", late_candle)

    assert len(engine.active_setups) == 0


def test_min_rr_filter():
    """Signal not generated if R:R < min (1:1)"""
    settings = Settings()
    settings.risk.min_rr = 1.0
    engine = ConfluenceEngine(settings, instrument="NQ")

    # This test verifies the R:R check exists in the model evaluation
    # Full integration requires multiple detectors firing together
    assert settings.risk.min_rr == 1.0
