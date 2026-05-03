"""
CISD — Change In State of Delivery (ICT concept, Pine-aligned)

CoWork finding: In Pine scripts (IFVG Setup Detector v4, IFVG Ultimate+ v11),
CISD IS the FVG inversion candle — the bar whose body crosses the FVG boundary.
It is NOT "close above opposing candle open" (that was an approximation).

  Bullish CISD = bearish FVG inversion:
    max(open, close) > bear_fvg.top  →  body_high crosses above the FVG top
    Signals: delivery has shifted from bearish to bullish

  Bearish CISD = bullish FVG inversion:
    min(open, close) < bull_fvg.bottom  →  body_low crosses below the FVG bottom
    Signals: delivery has shifted from bullish to bearish

Used in Model 2 (ICT 2022): after CISD fires, wait for price to RETRACE back
to the FVG zone, then enter at the FVG consequent encroachment (CE).
Model 1 enters AT the CISD candle close (same bar) — Model 2 waits for retest.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Optional

from ..data.candle import Candle
from .fvg import FVG, FVGType
from .ifvg import TF_PRIORITY

if TYPE_CHECKING:
    from ..models.base import TradeDirection


class CISDDirection(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"


@dataclass
class CISDSignal:
    direction: CISDDirection
    ts: datetime
    trigger_candle: Candle      # the candle whose body crossed the FVG boundary
    source_fvg: FVG             # the FVG that was inverted (CISD reference array)
    breach_price: float         # the FVG boundary that was crossed


class CISDDetector:
    """Detects CISD by checking if the current candle body crosses an unmitigated
    FVG boundary from the sweep leg."""

    def detect(
        self,
        candle: Candle,
        leg_fvgs: dict[int, list[FVG]],
        direction: "TradeDirection",
    ) -> CISDSignal | None:
        """
        Check if `candle` creates a CISD against any FVG on the sweep leg.

        For a LONG setup (swept a low):
          - Leg FVGs are bearish (downward displacement formed the sweep)
          - CISD fires when body_high > bear_fvg.top

        For a SHORT setup (swept a high):
          - Leg FVGs are bullish (upward displacement formed the sweep)
          - CISD fires when body_low < bull_fvg.bottom

        Returns the CISD from the highest-priority timeframe (5m > 3m > 1m).
        """
        from .ifvg import TF_PRIORITY
        from ..models.base import TradeDirection

        if direction == TradeDirection.LONG:
            expected_fvg = FVGType.BEARISH
            for tf in TF_PRIORITY:
                for fvg in leg_fvgs.get(tf, []):
                    if fvg.kind != expected_fvg:
                        continue
                    if fvg.mitigated and fvg.mitigated_ts != candle.ts:
                        continue
                    if candle.body_high > fvg.top:
                        return CISDSignal(
                            direction=CISDDirection.BULLISH,
                            ts=candle.ts,
                            trigger_candle=candle,
                            source_fvg=fvg,
                            breach_price=fvg.top,
                        )
        else:
            expected_fvg = FVGType.BULLISH
            for tf in TF_PRIORITY:
                for fvg in leg_fvgs.get(tf, []):
                    if fvg.kind != expected_fvg:
                        continue
                    if fvg.mitigated and fvg.mitigated_ts != candle.ts:
                        continue
                    if candle.body_low < fvg.bottom:
                        return CISDSignal(
                            direction=CISDDirection.BEARISH,
                            ts=candle.ts,
                            trigger_candle=candle,
                            source_fvg=fvg,
                            breach_price=fvg.bottom,
                        )
        return None
