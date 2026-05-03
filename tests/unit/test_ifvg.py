from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from smc_bot.data.candle import Candle
from smc_bot.detectors.fvg import FVG, FVGDirection
from smc_bot.detectors.ifvg import IFVGDetector, IFVGDirection, select_highest_tf_ifvg

NY = ZoneInfo("America/New_York")
BASE = datetime(2024, 1, 15, 9, 30, tzinfo=NY)


def test_bearish_fvg_inverts_to_bullish_ifvg():
    """Bearish FVG body-closed-above → becomes bullish IFVG"""
    bearish_fvg = FVG(
        direction=FVGDirection.BEARISH,
        high=105.0,
        low=103.0,
        timestamp=BASE,
        timeframe="5m",
        index=5,
    )

    det = IFVGDetector(timeframe="5m")
    det.track_fvg(bearish_fvg)

    inversion_candle = Candle(
        timestamp=BASE + timedelta(minutes=10),
        open=104.0,
        high=106.0,
        low=103.5,
        close=105.5,  # body_high = 105.5 > 105.0 (FVG high)
    )

    ifvgs = det.update(inversion_candle)
    assert len(ifvgs) == 1
    assert ifvgs[0].direction == IFVGDirection.BULLISH
    assert ifvgs[0].high == 105.0
    assert ifvgs[0].low == 103.0


def test_bullish_fvg_inverts_to_bearish_ifvg():
    """Bullish FVG body-closed-below → becomes bearish IFVG"""
    bullish_fvg = FVG(
        direction=FVGDirection.BULLISH,
        high=102.0,
        low=100.0,
        timestamp=BASE,
        timeframe="3m",
        index=3,
    )

    det = IFVGDetector(timeframe="3m")
    det.track_fvg(bullish_fvg)

    inversion_candle = Candle(
        timestamp=BASE + timedelta(minutes=6),
        open=101.0,
        high=101.5,
        low=99.0,
        close=99.5,  # body_low = 99.5 < 100.0 (FVG low)
    )

    ifvgs = det.update(inversion_candle)
    assert len(ifvgs) == 1
    assert ifvgs[0].direction == IFVGDirection.BEARISH


def test_no_inversion_without_body_close_through():
    """Wick through FVG doesn't count — only body close"""
    bearish_fvg = FVG(
        direction=FVGDirection.BEARISH,
        high=105.0,
        low=103.0,
        timestamp=BASE,
        timeframe="5m",
        index=5,
    )

    det = IFVGDetector(timeframe="5m")
    det.track_fvg(bearish_fvg)

    wick_only_candle = Candle(
        timestamp=BASE + timedelta(minutes=10),
        open=104.0,
        high=106.0,  # wick above FVG high
        low=103.5,
        close=104.5,  # body_high = max(104, 104.5) = 104.5 < 105.0
    )

    ifvgs = det.update(wick_only_candle)
    assert len(ifvgs) == 0


def test_select_highest_tf_ifvg():
    """5m preferred over 3m preferred over 1m"""
    from smc_bot.detectors.ifvg import IFVG

    fvg_5m = FVG(direction=FVGDirection.BEARISH, high=105, low=103, timestamp=BASE, timeframe="5m", index=1)
    fvg_1m = FVG(direction=FVGDirection.BEARISH, high=104, low=102, timestamp=BASE, timeframe="1m", index=2)

    ifvg_5m = IFVG(direction=IFVGDirection.BULLISH, high=105, low=103,
                   timestamp=BASE, inversion_timestamp=BASE + timedelta(minutes=5),
                   timeframe="5m", source_fvg=fvg_5m)
    ifvg_1m = IFVG(direction=IFVGDirection.BULLISH, high=104, low=102,
                   timestamp=BASE, inversion_timestamp=BASE + timedelta(minutes=5),
                   timeframe="1m", source_fvg=fvg_1m)

    result = select_highest_tf_ifvg({"5m": [ifvg_5m], "1m": [ifvg_1m]})
    assert result == ifvg_5m

    result_no_5m = select_highest_tf_ifvg({"1m": [ifvg_1m]})
    assert result_no_5m == ifvg_1m
