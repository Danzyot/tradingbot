from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from smc_bot.data.candle import Candle
from smc_bot.detectors.nwog_ndog import NWOGNDOGDetector
from smc_bot.detectors.liquidity import LiquidityType

NY = ZoneInfo("America/New_York")


def test_ndog_detected():
    """Gap between 5pm close and 6pm open → NDOG"""
    det = NWOGNDOGDetector(timezone="America/New_York")

    # Friday 5pm candle (sets prev_close)
    fri_close = Candle(
        timestamp=datetime(2024, 1, 15, 17, 0, tzinfo=NY),
        open=100.0, high=101.0, low=99.5, close=100.5
    )
    det.update(fri_close)

    # Next day 6pm candle (creates NDOG)
    next_open = Candle(
        timestamp=datetime(2024, 1, 16, 18, 0, tzinfo=NY),
        open=101.5, high=102.0, low=101.0, close=101.8
    )
    levels = det.update(next_open)

    ndog_levels = [l for l in levels if l.type in (LiquidityType.NDOG_HIGH, LiquidityType.NDOG_LOW)]
    assert len(ndog_levels) == 2


def test_no_gap_on_first_candle():
    """First candle can't create a gap"""
    det = NWOGNDOGDetector()
    candle = Candle(
        timestamp=datetime(2024, 1, 15, 17, 0, tzinfo=NY),
        open=100.0, high=101.0, low=99.0, close=100.5
    )
    levels = det.update(candle)
    assert len(levels) == 0
