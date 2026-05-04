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


# Priority order for timeframe selection (highest first, max 5m).
TF_PRIORITY = [5, 4, 3, 2, 1]

# Speed gate: inversion must fire within N bars (of the FVG's own TF) of first zone touch.
IFVG_MAX_CANDLES_AFTER_TOUCH = 4

# Max age gate: max_age_minutes = tf_minutes × IFVG_AGE_TF_MULT
#   1m → 8 min   3m → 24 min   5m → 40 min
IFVG_AGE_TF_MULT = 8


class IFVGDetector:
    """
    Monitors FVG trackers across multiple timeframes for a given sweep leg.
    Returns the highest-TF IFVG when ALL FVGs of that TF are inversed.

    Rule: if the leg has multiple FVGs at the same (highest) TF, ALL must be
    inversed before entry — the last inversion is the entry candle.
    """

    def __init__(self, fvg_trackers: dict[int, FVGTracker]):
        self.trackers = fvg_trackers

    def check(
        self,
        candle: Candle,
        sweep: Sweep,
        leg_fvgs: dict[int, list[FVG]],
    ) -> IFVG | None:
        """
        Check if the current candle creates an IFVG from the sweep leg's FVGs.

        Finds the highest TF that has FVGs of the expected kind on the leg.
        ALL FVGs of that TF must be inversed (close beyond far edge) as of this
        candle — the signal fires on the candle that inverses the last remaining one.
        Lower TFs are not checked if a higher TF has any pending FVGs.
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
            fvgs = [
                f for f in leg_fvgs.get(tf, [])
                if f.kind == expected_fvg_kind
            ]
            if not fvgs:
                continue

            # Speed gate: drop FVGs touched but not inverted within the window.
            tracker = self.trackers.get(tf)
            if tracker is not None:
                bar_now = tracker._bar_count
                fvgs = [
                    f for f in fvgs
                    if (
                        f.first_touch_bar is None or
                        (bar_now - f.first_touch_bar) <= IFVG_MAX_CANDLES_AFTER_TOUCH
                    )
                ]
            if not fvgs:
                continue

            # Age gate: TF-relative max age.
            max_age = tf * IFVG_AGE_TF_MULT
            fvgs = [
                f for f in fvgs
                if (candle.ts - f.ts).total_seconds() / 60 <= max_age
            ]
            if not fvgs:
                continue

            # Highest TF with FVGs — ALL must be inversed before entry fires.
            inversed_this_candle: list[FVG] = []
            all_clear = True

            for fvg in fvgs:
                if self._is_inversed(candle, fvg, ifvg_direction):
                    fvg.inverted = True
                    inversed_this_candle.append(fvg)
                elif fvg.inverted:
                    pass
                else:
                    all_clear = False
                    break

            if not all_clear:
                return None

            if not inversed_this_candle:
                return None

            return IFVG(
                source_fvg=inversed_this_candle[-1],
                direction=ifvg_direction,
                inversion_candle=candle,
                ts=candle.ts,
                timeframe=tf,
            )

        return None

    @staticmethod
    def _is_inversed(candle: Candle, fvg: FVG, direction: IFVGDirection) -> bool:
        """
        Full inversion: the candle must approach FROM WITHIN or on the near side of
        the FVG zone and close decisively through the far edge.

        Open check prevents triggering on continuation candles that already opened
        past the far edge (inversion happened on a prior bar — this would be a
        re-entry, not the inversion candle itself).
        """
        if direction == IFVGDirection.BULLISH:
            # Bearish FVG inverted: candle opens at/below fvg.top (within or below zone)
            # and closes above it (delivers through the far edge)
            return candle.open <= fvg.top and candle.close > fvg.top
        else:
            # Bullish FVG inverted: candle opens at/above fvg.bottom (within or above zone)
            # and closes below it (delivers through the far edge)
            return candle.open >= fvg.bottom and candle.close < fvg.bottom
