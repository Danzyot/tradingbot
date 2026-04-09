"""
Liquidity sweep detection.

A valid sweep:
- BULLISH sweep (bearish→bullish reversal): wick goes BELOW a liquidity level,
  but the candle BODY closes ABOVE the level.
- BEARISH sweep (bullish→bearish reversal): wick goes ABOVE a liquidity level,
  but the candle BODY closes BELOW the level.

Only S/A/B tier liquidity levels count as valid sweep targets.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

from ..data.candle import Candle


class SweepDirection(Enum):
    BULLISH = "bullish"   # swept a low → potential long
    BEARISH = "bearish"   # swept a high → potential short


class LiqTier(Enum):
    S = "S"
    A = "A"
    B = "B"
    C = "C"
    F = "F"   # ignored


@dataclass
class LiquidityLevel:
    price: float
    tier: LiqTier
    kind: str           # "swing_high", "swing_low", "eqh", "eql", "pdh", "pdl",
                        # "session_high", "session_low", "nwog_high", "nwog_low",
                        # "ndog_high", "ndog_low", "fvg_high", "fvg_low"
    ts: datetime        # when the level was formed
    swept: bool = False
    swept_ts: Optional[datetime] = None


@dataclass
class Sweep:
    ts: datetime
    direction: SweepDirection
    level: LiquidityLevel
    sweep_candle: Candle
    # The manipulation leg = candles from sweep_ts backward until prior structure
    leg_start_ts: Optional[datetime] = None


class SweepDetector:
    """
    Given a list of liquidity levels and a new candle, detect valid sweeps.
    """

    VALID_TIERS = {LiqTier.S, LiqTier.A, LiqTier.B}

    def detect(self, candle: Candle, levels: list[LiquidityLevel]) -> list[Sweep]:
        sweeps: list[Sweep] = []
        for level in levels:
            if level.tier not in self.VALID_TIERS:
                continue
            if level.swept:
                continue

            sweep = self._check(candle, level)
            if sweep:
                level.swept = True
                level.swept_ts = candle.ts
                sweeps.append(sweep)

        return sweeps

    def _check(self, c: Candle, level: LiquidityLevel) -> Sweep | None:
        # Bullish sweep: wick below, body closes above
        if (c.low < level.price and           # wick penetrates
                c.body_low >= level.price):    # body stays above (or exactly at)
            return Sweep(
                ts=c.ts,
                direction=SweepDirection.BULLISH,
                level=level,
                sweep_candle=c,
            )

        # Bearish sweep: wick above, body closes below
        if (c.high > level.price and          # wick penetrates
                c.body_high <= level.price):   # body stays below (or exactly at)
            return Sweep(
                ts=c.ts,
                direction=SweepDirection.BEARISH,
                level=level,
                sweep_candle=c,
            )

        return None
