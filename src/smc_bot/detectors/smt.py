"""
SMT (Smart Money Technique) Divergence — NQ vs ES.

Pine-aligned rules (from IFVG Setup Detector v4):
- Pivot params: left=4, right=4 (Normal sensitivity)
- Temporal proximity: BOTH instruments' pivots must have formed within
  `proximity_bars` bars of each other (Pine: same bar or within pivot window).
  Python uses timestamp proximity since bars are 1m.
- Price comparison: wick highs/lows (not close)
- Direction: `(NQ_delta × ES_delta) < 0` → divergence (equivalent to Python's current logic)

Bullish SMT: one instrument makes a lower low, the other does NOT.
  → Trade the one showing relative strength (the one that held higher).

Bearish SMT: one instrument makes a higher high, the other does NOT.
  → Trade the one showing relative weakness (the one that failed to make a higher high).

SMT is an OPTIONAL secondary confirmation (not required for entry).
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
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

    Parameters
    ----------
    symbol_a, symbol_b : instrument names (NQ, ES)
    proximity_bars     : max bar gap allowed between the two diverging pivots.
                         Pine requires both pivots to update on the same bar or
                         within the same pivot window (left=4, right=4 → ~4 bars).
                         Using 4 bars * 1 min = 4 minutes as the window.
    bar_duration_sec   : seconds per bar (default 60 = 1m bars)
    """

    def __init__(
        self,
        symbol_a: str = "NQ",
        symbol_b: str = "ES",
        proximity_bars: int = 4,
        bar_duration_sec: int = 60,
    ):
        self.symbol_a = symbol_a
        self.symbol_b = symbol_b
        # Max time delta between the two diverging pivots
        self._max_gap = timedelta(seconds=proximity_bars * bar_duration_sec)

    def check_bullish(
        self,
        swings_a: list[SwingPoint],
        swings_b: list[SwingPoint],
        ts: datetime,
    ) -> SMTSignal | None:
        """
        Bullish SMT: A makes lower low, B does NOT (or vice versa).
        Compares the two most recent swing lows — ONLY if they formed within
        proximity_bars of each other (Pine temporal proximity requirement).
        """
        lows_a = [p for p in swings_a if p.kind == SwingType.LOW]
        lows_b = [p for p in swings_b if p.kind == SwingType.LOW]

        if len(lows_a) < 2 or len(lows_b) < 2:
            return None

        curr_a = lows_a[-1]
        curr_b = lows_b[-1]

        # Temporal proximity: both most-recent pivots must be close in time
        if abs(curr_a.ts - curr_b.ts) > self._max_gap:
            return None

        prev_a, prev_b = lows_a[-2].price, lows_b[-2].price
        a_made_lower = curr_a.price < prev_a
        b_made_lower = curr_b.price < prev_b

        if a_made_lower and not b_made_lower:
            return SMTSignal(
                direction=SMTDirection.BULLISH, ts=ts,
                symbol_a=self.symbol_a, symbol_b=self.symbol_b,
                trade_symbol=self.symbol_b,
                low_a=curr_a.price, low_b=curr_b.price,
                ts_a=curr_a.ts, ts_b=curr_b.ts,
            )
        if b_made_lower and not a_made_lower:
            return SMTSignal(
                direction=SMTDirection.BULLISH, ts=ts,
                symbol_a=self.symbol_a, symbol_b=self.symbol_b,
                trade_symbol=self.symbol_a,
                low_a=curr_a.price, low_b=curr_b.price,
                ts_a=curr_a.ts, ts_b=curr_b.ts,
            )
        return None

    def check_bearish(
        self,
        swings_a: list[SwingPoint],
        swings_b: list[SwingPoint],
        ts: datetime,
    ) -> SMTSignal | None:
        """
        Bearish SMT: A makes higher high, B does NOT (or vice versa).
        """
        highs_a = [p for p in swings_a if p.kind == SwingType.HIGH]
        highs_b = [p for p in swings_b if p.kind == SwingType.HIGH]

        if len(highs_a) < 2 or len(highs_b) < 2:
            return None

        curr_a = highs_a[-1]
        curr_b = highs_b[-1]

        # Temporal proximity check
        if abs(curr_a.ts - curr_b.ts) > self._max_gap:
            return None

        prev_a, prev_b = highs_a[-2].price, highs_b[-2].price
        a_made_higher = curr_a.price > prev_a
        b_made_higher = curr_b.price > prev_b

        if a_made_higher and not b_made_higher:
            return SMTSignal(
                direction=SMTDirection.BEARISH, ts=ts,
                symbol_a=self.symbol_a, symbol_b=self.symbol_b,
                trade_symbol=self.symbol_b,
                high_a=curr_a.price, high_b=curr_b.price,
                ts_a=curr_a.ts, ts_b=curr_b.ts,
            )
        if b_made_higher and not a_made_higher:
            return SMTSignal(
                direction=SMTDirection.BEARISH, ts=ts,
                symbol_a=self.symbol_a, symbol_b=self.symbol_b,
                trade_symbol=self.symbol_a,
                high_a=curr_a.price, high_b=curr_b.price,
                ts_a=curr_a.ts, ts_b=curr_b.ts,
            )
        return None
