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


# Priority order for timeframe selection (highest first).
# 5m is the absolute max for IFVG — never take 15m+ IFVG (trade lifecycle too long).
# All five LTF timeframes covered to find the highest available on the leg.
TF_PRIORITY = [5, 4, 3, 2, 1]


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
                continue   # no FVGs of this TF on the leg — try lower TF

            # This is the highest TF with FVGs. ALL must be inversed before entry.
            inversed_this_candle: list[FVG] = []
            all_clear = True

            for fvg in fvgs:
                if self._is_inversed(candle, fvg, ifvg_direction):
                    inversed_this_candle.append(fvg)
                elif fvg.mitigated and fvg.mitigated_ts != candle.ts:
                    pass   # pre-mitigated on a prior candle — counts as cleared
                else:
                    all_clear = False   # still active, not yet inversed
                    break

            if not all_clear:
                # Highest TF has pending FVGs — don't drop to lower TF, just wait
                return None

            if not inversed_this_candle:
                # All were pre-mitigated on prior candles, nothing to fire on now
                return None

            # Fire on the most recent FVG being inversed on this candle
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
