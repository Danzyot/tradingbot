from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from smc_bot.detectors.swing import SwingPoint, SwingType


class SMTDirection(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"


@dataclass
class SMTDivergence:
    direction: SMTDirection
    timestamp: datetime
    instrument_a_price: float
    instrument_b_price: float
    instrument_a: str
    instrument_b: str
    trade_instrument: str


class SMTDetector:
    def __init__(
        self,
        instrument_a: str = "NQ",
        instrument_b: str = "ES",
        window_candles: int = 3,
    ):
        self._instrument_a = instrument_a
        self._instrument_b = instrument_b
        self._window = window_candles
        self._swings_a: list[SwingPoint] = []
        self._swings_b: list[SwingPoint] = []
        self._divergences: list[SMTDivergence] = []

    @property
    def divergences(self) -> list[SMTDivergence]:
        return self._divergences

    @property
    def last_divergence(self) -> SMTDivergence | None:
        return self._divergences[-1] if self._divergences else None

    def update_swings(
        self, swings_a: list[SwingPoint], swings_b: list[SwingPoint]
    ) -> list[SMTDivergence]:
        self._swings_a = swings_a
        self._swings_b = swings_b
        return self._detect()

    def add_swing_a(self, swing: SwingPoint) -> list[SMTDivergence]:
        self._swings_a.append(swing)
        return self._detect_latest()

    def add_swing_b(self, swing: SwingPoint) -> list[SMTDivergence]:
        self._swings_b.append(swing)
        return self._detect_latest()

    def _detect_latest(self) -> list[SMTDivergence]:
        if not self._swings_a or not self._swings_b:
            return []

        new_divergences: list[SMTDivergence] = []

        lows_a = [s for s in self._swings_a if s.type == SwingType.LOW]
        lows_b = [s for s in self._swings_b if s.type == SwingType.LOW]
        highs_a = [s for s in self._swings_a if s.type == SwingType.HIGH]
        highs_b = [s for s in self._swings_b if s.type == SwingType.HIGH]

        if len(lows_a) >= 2 and lows_b:
            div = self._check_bullish(lows_a[-2], lows_a[-1], lows_b)
            if div:
                new_divergences.append(div)

        if len(lows_b) >= 2 and lows_a:
            div = self._check_bullish_reverse(lows_b[-2], lows_b[-1], lows_a)
            if div:
                new_divergences.append(div)

        if len(highs_a) >= 2 and highs_b:
            div = self._check_bearish(highs_a[-2], highs_a[-1], highs_b)
            if div:
                new_divergences.append(div)

        if len(highs_b) >= 2 and highs_a:
            div = self._check_bearish_reverse(highs_b[-2], highs_b[-1], highs_a)
            if div:
                new_divergences.append(div)

        self._divergences.extend(new_divergences)
        return new_divergences

    def _detect(self) -> list[SMTDivergence]:
        self._divergences.clear()
        return self._detect_latest()

    def _check_bullish(
        self, prev_a: SwingPoint, curr_a: SwingPoint, lows_b: list[SwingPoint]
    ) -> SMTDivergence | None:
        if curr_a.price >= prev_a.price:
            return None

        matching_b = self._find_matching(curr_a, lows_b)
        if matching_b is None:
            return None

        prev_matching_b = self._find_matching(prev_a, lows_b)
        if prev_matching_b is None:
            return None

        if matching_b.price >= prev_matching_b.price:
            return SMTDivergence(
                direction=SMTDirection.BULLISH,
                timestamp=curr_a.timestamp,
                instrument_a_price=curr_a.price,
                instrument_b_price=matching_b.price,
                instrument_a=self._instrument_a,
                instrument_b=self._instrument_b,
                trade_instrument=self._instrument_b,
            )
        return None

    def _check_bullish_reverse(
        self, prev_b: SwingPoint, curr_b: SwingPoint, lows_a: list[SwingPoint]
    ) -> SMTDivergence | None:
        if curr_b.price >= prev_b.price:
            return None

        matching_a = self._find_matching(curr_b, lows_a)
        if matching_a is None:
            return None

        prev_matching_a = self._find_matching(prev_b, lows_a)
        if prev_matching_a is None:
            return None

        if matching_a.price >= prev_matching_a.price:
            return SMTDivergence(
                direction=SMTDirection.BULLISH,
                timestamp=curr_b.timestamp,
                instrument_a_price=matching_a.price,
                instrument_b_price=curr_b.price,
                instrument_a=self._instrument_a,
                instrument_b=self._instrument_b,
                trade_instrument=self._instrument_a,
            )
        return None

    def _check_bearish(
        self, prev_a: SwingPoint, curr_a: SwingPoint, highs_b: list[SwingPoint]
    ) -> SMTDivergence | None:
        if curr_a.price <= prev_a.price:
            return None

        matching_b = self._find_matching(curr_a, highs_b)
        if matching_b is None:
            return None

        prev_matching_b = self._find_matching(prev_a, highs_b)
        if prev_matching_b is None:
            return None

        if matching_b.price <= prev_matching_b.price:
            return SMTDivergence(
                direction=SMTDirection.BEARISH,
                timestamp=curr_a.timestamp,
                instrument_a_price=curr_a.price,
                instrument_b_price=matching_b.price,
                instrument_a=self._instrument_a,
                instrument_b=self._instrument_b,
                trade_instrument=self._instrument_b,
            )
        return None

    def _check_bearish_reverse(
        self, prev_b: SwingPoint, curr_b: SwingPoint, highs_a: list[SwingPoint]
    ) -> SMTDivergence | None:
        if curr_b.price <= prev_b.price:
            return None

        matching_a = self._find_matching(curr_b, highs_a)
        if matching_a is None:
            return None

        prev_matching_a = self._find_matching(prev_b, highs_a)
        if prev_matching_a is None:
            return None

        if matching_a.price <= prev_matching_a.price:
            return SMTDivergence(
                direction=SMTDirection.BEARISH,
                timestamp=curr_b.timestamp,
                instrument_a_price=matching_a.price,
                instrument_b_price=curr_b.price,
                instrument_a=self._instrument_a,
                instrument_b=self._instrument_b,
                trade_instrument=self._instrument_a,
            )
        return None

    def _find_matching(
        self, target: SwingPoint, candidates: list[SwingPoint]
    ) -> SwingPoint | None:
        best = None
        best_dist = float("inf")
        for c in candidates:
            dist = abs(c.index - target.index)
            if dist <= self._window and dist < best_dist:
                best = c
                best_dist = dist
        return best
