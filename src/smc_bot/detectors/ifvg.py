"""
IFVG (Inversion Fair Value Gap) detection.

An IFVG is a previously unmitigated FVG from the manipulation/sweep leg
that gets "inversed" — a candle body closes BEYOND the FVG.

For a LONG setup:
  - The manipulation leg swept a low (bearish move down to the sweep)
  - FVGs on that leg are BEARISH FVGs
  - When a candle body closes ABOVE the bearish FVG → bullish IFVG → ENTRY

For a SHORT setup:
  - The manipulation leg swept a high (bullish move up to the sweep)
  - FVGs on that leg are BULLISH FVGs
  - When a candle body closes BELOW the bullish FVG → bearish IFVG → ENTRY

Priority rule: Use the HIGHEST timeframe IFVG between 1m–5m.
  (5m > 3m > 1m)

Entry: Market order on the candle that creates the IFVG (body-close beyond FVG).
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

from ..data.candle import Candle
from .fvg import FVG, FVGType, FVGTracker
from .sweep import Sweep, SweepDirection


class IFVGDirection(Enum):
    BULLISH = "bullish"   # entry for long
    BEARISH = "bearish"   # entry for short


@dataclass
class IFVG:
    source_fvg: FVG           # the FVG that got inversed
    direction: IFVGDirection
    inversion_candle: Candle  # the candle whose body-close created the IFVG
    ts: datetime
    timeframe: int

    @property
    def entry_price(self) -> float:
        """Entry = close of inversion candle (market order on close)."""
        return self.inversion_candle.close

    @property
    def zone_top(self) -> float:
        return self.source_fvg.top

    @property
    def zone_bottom(self) -> float:
        return self.source_fvg.bottom


# Priority order for timeframe selection (highest first)
TF_PRIORITY = [5, 3, 1]


class IFVGDetector:
    """
    Monitors FVG trackers across multiple timeframes for a given sweep leg.
    Returns the highest-TF IFVG when one forms.
    """

    def __init__(self, fvg_trackers: dict[int, FVGTracker]):
        """
        fvg_trackers: {timeframe_minutes: FVGTracker}
        Only timeframes in TF_PRIORITY (1, 3, 5) are checked for IFVG entries.
        """
        self.trackers = fvg_trackers

    def check(
        self,
        candle: Candle,
        sweep: Sweep,
        leg_fvgs: dict[int, list[FVG]],   # FVGs from the sweep leg, keyed by TF
    ) -> IFVG | None:
        """
        Check if the current candle creates an IFVG from the sweep leg's FVGs.
        Returns the highest-TF IFVG if found, else None.
        """
        expected_fvg_kind = (
            FVGType.BEARISH if sweep.direction == SweepDirection.BULLISH
            else FVGType.BULLISH
        )
        ifvg_direction = (
            IFVGDirection.BULLISH if sweep.direction == SweepDirection.BULLISH
            else IFVGDirection.BEARISH
        )

        for tf in TF_PRIORITY:
            fvgs = leg_fvgs.get(tf, [])
            for fvg in fvgs:
                if fvg.kind != expected_fvg_kind:
                    continue
                if fvg.mitigated:
                    continue
                if self._is_inversed(candle, fvg, ifvg_direction):
                    return IFVG(
                        source_fvg=fvg,
                        direction=ifvg_direction,
                        inversion_candle=candle,
                        ts=candle.ts,
                        timeframe=tf,
                    )

        return None

    @staticmethod
    def _is_inversed(candle: Candle, fvg: FVG, direction: IFVGDirection) -> bool:
        """
        BULLISH inversion: candle CLOSE is above the bearish FVG's top.
        BEARISH inversion: candle CLOSE is below the bullish FVG's bottom.

        CoWork fix: use close, not body_high/body_low.
        body_high = max(open, close) — a bearish candle that opens above fvg.top
        fires body_high > fvg.top even though price closed BELOW and is going down.
        Using close ensures the candle actually closed beyond the FVG on that bar.
        """
        if direction == IFVGDirection.BULLISH:
            return candle.close > fvg.top
        else:
            return candle.close < fvg.bottom
