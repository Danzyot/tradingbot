"""
Liquidity sweep detection.

ICT directional rule — non-negotiable:
  HIGH levels (EQH, swing_high, session_high, PDH, ndog_high, fvg_high):
    → BEARISH sweep only (wick ABOVE, body closes BACK BELOW) → SHORT trade
    Rationale: buy stops accumulate above highs. Sweep takes them → institutions sell.

  LOW levels (EQL, swing_low, session_low, PDL, ndog_low, fvg_low):
    → BULLISH sweep only (wick BELOW, body closes BACK ABOVE) → LONG trade
    Rationale: sell stops accumulate below lows. Sweep takes them → institutions buy.

Running a bearish sweep on a LOW level (or bullish on HIGH) is NOT a valid ICT setup.
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

    # Level kinds that are HIGH levels — swept bearishly → SHORT
    _HIGH_KINDS = frozenset({
        "eqh", "swing_high", "pdh",
        "asia_high", "london_high", "ny_am_high", "ny_lunch_high", "ny_pm_high",
        "ndog_high", "nwog_high",
        "15m_fvg_high", "30m_fvg_high", "60m_fvg_high", "240m_fvg_high",
    })

    # Level kinds that are LOW levels — swept bullishly → LONG
    _LOW_KINDS = frozenset({
        "eql", "swing_low", "pdl",
        "asia_low", "london_low", "ny_am_low", "ny_lunch_low", "ny_pm_low",
        "ndog_low", "nwog_low",
        "15m_fvg_low", "30m_fvg_low", "60m_fvg_low", "240m_fvg_low",
    })

    def _level_direction(self, level: LiquidityLevel) -> SweepDirection | None:
        """
        Return the ONLY valid sweep direction for this level kind.
        HIGH levels can only be swept bearishly (wick above → short).
        LOW levels can only be swept bullishly (wick below → long).
        Returns None if the level kind is unrecognised (allow both — defensive fallback).
        """
        if level.kind in self._HIGH_KINDS:
            return SweepDirection.BEARISH
        if level.kind in self._LOW_KINDS:
            return SweepDirection.BULLISH
        # Unknown kind — check both directions but shouldn't happen with correct config
        return None

    def _check(self, c: Candle, level: LiquidityLevel) -> Sweep | None:
        valid_dir = self._level_direction(level)

        # Bullish sweep: wick below, body closes above → LONG
        if valid_dir in (SweepDirection.BULLISH, None):
            if (c.low < level.price and
                    c.body_low >= level.price):
                return Sweep(
                    ts=c.ts,
                    direction=SweepDirection.BULLISH,
                    level=level,
                    sweep_candle=c,
                )

        # Bearish sweep: wick above, body closes below → SHORT
        if valid_dir in (SweepDirection.BEARISH, None):
            if (c.high > level.price and
                    c.body_high <= level.price):
                return Sweep(
                    ts=c.ts,
                    direction=SweepDirection.BEARISH,
                    level=level,
                    sweep_candle=c,
                )

        return None
