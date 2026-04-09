"""
CISD — Change In State of Delivery (ICT concept)

More sensitive than CHoCH. Based on candle BODY opens/closes, ignores wicks.

Bullish CISD: a candle body closes ABOVE the open of the most recent prior bearish candle.
  → Signals transition from bearish to bullish delivery.

Bearish CISD: a candle body closes BELOW the open of the most recent prior bullish candle.
  → Signals transition from bullish to bearish delivery.

Used as optional confirmation after a liquidity sweep.
Also used as required trigger in Model 2 (ICT 2022).
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

from ..data.candle import Candle


class CISDDirection(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"


@dataclass
class CISDSignal:
    direction: CISDDirection
    ts: datetime
    trigger_candle: Candle          # the candle whose body caused the CISD
    reference_candle: Candle        # the prior opposing candle whose open was breached
    breach_price: float             # the open price that was breached


class CISDDetector:
    """
    Scans recent candles for a CISD event.

    Bullish CISD: current candle body_high > most recent bearish candle's open
    Bearish CISD: current candle body_low  < most recent bullish candle's open
    """

    def detect(self, candles: list[Candle]) -> CISDSignal | None:
        """
        Check the most recent closed candle for a CISD against prior candles.
        Returns a CISDSignal if found, else None.
        """
        if len(candles) < 2:
            return None

        current = candles[-1]

        # Search backwards for the most recent opposing candle
        bullish_cisd = self._check_bullish(current, candles[:-1])
        bearish_cisd = self._check_bearish(current, candles[:-1])

        # Return whichever fired (prefer bearish if both, which shouldn't happen)
        return bullish_cisd or bearish_cisd

    def _check_bullish(self, current: Candle, prior: list[Candle]) -> CISDSignal | None:
        """Body closes above the open of the most recent bearish candle."""
        for c in reversed(prior):
            if c.bearish:
                if current.body_high > c.open:
                    return CISDSignal(
                        direction=CISDDirection.BULLISH,
                        ts=current.ts,
                        trigger_candle=current,
                        reference_candle=c,
                        breach_price=c.open,
                    )
                break  # only check the most recent bearish candle
        return None

    def _check_bearish(self, current: Candle, prior: list[Candle]) -> CISDSignal | None:
        """Body closes below the open of the most recent bullish candle."""
        for c in reversed(prior):
            if c.bullish:
                if current.body_low < c.open:
                    return CISDSignal(
                        direction=CISDDirection.BEARISH,
                        ts=current.ts,
                        trigger_candle=current,
                        reference_candle=c,
                        breach_price=c.open,
                    )
                break  # only check the most recent bullish candle
        return None
