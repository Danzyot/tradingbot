"""
SMT (Smart Money Technique) Divergence — NQ vs ES.

Bullish SMT: one instrument makes a lower low, the other does NOT.
  → Trade the one showing relative strength (the one that held higher).

Bearish SMT: one instrument makes a higher high, the other does NOT.
  → Trade the one showing relative weakness (the one that failed to make a higher high).

SMT is an OPTIONAL secondary confirmation (not required for entry).
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

from .swing import SwingPoint, SwingType


class SMTDirection(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"


@dataclass
class SMTSignal:
    direction: SMTDirection
    ts: datetime
    symbol_a: str           # e.g. "NQ"
    symbol_b: str           # e.g. "ES"
    trade_symbol: str       # which one to trade (relative strength)
    low_a: Optional[float] = None
    low_b: Optional[float] = None
    high_a: Optional[float] = None
    high_b: Optional[float] = None
    # Swing timestamps for chart drawing (orange line between diverging wicks)
    ts_a: Optional[datetime] = None   # timestamp of symbol_a swing
    ts_b: Optional[datetime] = None   # timestamp of symbol_b swing


class SMTDetector:
    """
    Compare the most recent swing lows (for bullish) or highs (for bearish)
    between two correlated instruments.
    """

    def __init__(self, symbol_a: str = "NQ", symbol_b: str = "ES"):
        self.symbol_a = symbol_a
        self.symbol_b = symbol_b

    def check_bullish(
        self,
        swings_a: list[SwingPoint],   # lows for symbol A
        swings_b: list[SwingPoint],   # lows for symbol B
        ts: datetime,
    ) -> SMTSignal | None:
        """
        Bullish SMT: A makes lower low, B does NOT (or vice versa).
        Compares the two most recent swing lows.
        """
        lows_a = [p for p in swings_a if p.kind == SwingType.LOW]
        lows_b = [p for p in swings_b if p.kind == SwingType.LOW]

        if len(lows_a) < 2 or len(lows_b) < 2:
            return None

        # Current vs previous low
        prev_a, curr_a = lows_a[-2].price, lows_a[-1].price
        prev_b, curr_b = lows_b[-2].price, lows_b[-1].price

        a_made_lower = curr_a < prev_a
        b_made_lower = curr_b < prev_b

        if a_made_lower and not b_made_lower:
            return SMTSignal(
                direction=SMTDirection.BULLISH, ts=ts,
                symbol_a=self.symbol_a, symbol_b=self.symbol_b,
                trade_symbol=self.symbol_b,
                low_a=curr_a, low_b=curr_b,
                ts_a=lows_a[-1].ts, ts_b=lows_b[-1].ts,
            )
        if b_made_lower and not a_made_lower:
            return SMTSignal(
                direction=SMTDirection.BULLISH, ts=ts,
                symbol_a=self.symbol_a, symbol_b=self.symbol_b,
                trade_symbol=self.symbol_a,
                low_a=curr_a, low_b=curr_b,
                ts_a=lows_a[-1].ts, ts_b=lows_b[-1].ts,
            )
        return None

    def check_bearish(
        self,
        swings_a: list[SwingPoint],   # highs for symbol A
        swings_b: list[SwingPoint],   # highs for symbol B
        ts: datetime,
    ) -> SMTSignal | None:
        """
        Bearish SMT: A makes higher high, B does NOT (or vice versa).
        """
        highs_a = [p for p in swings_a if p.kind == SwingType.HIGH]
        highs_b = [p for p in swings_b if p.kind == SwingType.HIGH]

        if len(highs_a) < 2 or len(highs_b) < 2:
            return None

        prev_a, curr_a = highs_a[-2].price, highs_a[-1].price
        prev_b, curr_b = highs_b[-2].price, highs_b[-1].price

        a_made_higher = curr_a > prev_a
        b_made_higher = curr_b > prev_b

        if a_made_higher and not b_made_higher:
            return SMTSignal(
                direction=SMTDirection.BEARISH, ts=ts,
                symbol_a=self.symbol_a, symbol_b=self.symbol_b,
                trade_symbol=self.symbol_b,
                high_a=curr_a, high_b=curr_b,
                ts_a=highs_a[-1].ts, ts_b=highs_b[-1].ts,
            )
        if b_made_higher and not a_made_higher:
            return SMTSignal(
                direction=SMTDirection.BEARISH, ts=ts,
                symbol_a=self.symbol_a, symbol_b=self.symbol_b,
                trade_symbol=self.symbol_a,
                high_a=curr_a, high_b=curr_b,
                ts_a=highs_a[-1].ts, ts_b=highs_b[-1].ts,
            )
        return None
