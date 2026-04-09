"""
Fair Value Gap (FVG) detection and mitigation tracking.

Bullish FVG : candle[i-2].high < candle[i].low   → gap zone = (candle[i-2].high, candle[i].low)
Bearish FVG : candle[i-2].low  > candle[i].high  → gap zone = (candle[i].high,   candle[i-2].low)

CE (Consequent Encroachment) = midpoint of the zone.

Mitigation: a candle body closes BEYOND the far edge of the FVG.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from ..data.candle import Candle


class FVGType(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"


@dataclass
class FVG:
    id: int
    kind: FVGType
    timeframe: int
    ts: datetime            # timestamp of the middle (trigger) candle

    # Zone boundaries
    top: float              # upper edge
    bottom: float           # lower edge

    # Leg tracking — which sweep leg "sponsored" this FVG
    leg_sweep_ts: Optional[datetime] = None

    mitigated: bool = False
    mitigated_ts: Optional[datetime] = None

    @property
    def ce(self) -> float:
        return (self.top + self.bottom) / 2

    @property
    def size(self) -> float:
        return self.top - self.bottom


_fvg_counter = 0


def _next_id() -> int:
    global _fvg_counter
    _fvg_counter += 1
    return _fvg_counter


class FVGTracker:
    """
    Detects and tracks FVGs across a stream of candles.
    Call `update(candles)` after each new closed candle.
    """

    def __init__(self, timeframe: int):
        self.timeframe = timeframe
        self.active: list[FVG] = []       # unmitigated FVGs
        self.mitigated: list[FVG] = []    # historical record

    def update(self, candles: list[Candle], leg_sweep_ts: datetime | None = None) -> list[FVG]:
        """
        Process the latest candles. Detects new FVGs and checks mitigation.
        Returns newly detected FVGs (if any).
        """
        new_fvgs: list[FVG] = []

        if len(candles) >= 3:
            new = self._detect_at(candles, -1, leg_sweep_ts)
            if new:
                self.active.append(new)
                new_fvgs.append(new)

        self._check_mitigation(candles[-1] if candles else None)
        return new_fvgs

    def _detect_at(self, candles: list[Candle], idx: int,
                   leg_sweep_ts: datetime | None) -> FVG | None:
        c0 = candles[idx - 2]   # oldest of the 3
        c2 = candles[idx]       # newest of the 3

        # Bullish FVG
        if c0.high < c2.low:
            return FVG(
                id=_next_id(),
                kind=FVGType.BULLISH,
                timeframe=self.timeframe,
                ts=candles[idx - 1].ts,
                top=c2.low,
                bottom=c0.high,
                leg_sweep_ts=leg_sweep_ts,
            )

        # Bearish FVG
        if c0.low > c2.high:
            return FVG(
                id=_next_id(),
                kind=FVGType.BEARISH,
                timeframe=self.timeframe,
                ts=candles[idx - 1].ts,
                top=c0.low,
                bottom=c2.high,
                leg_sweep_ts=leg_sweep_ts,
            )

        return None

    def _check_mitigation(self, candle: Candle | None) -> None:
        if candle is None:
            return
        still_active = []
        for fvg in self.active:
            if self._is_mitigated(fvg, candle):
                fvg.mitigated = True
                fvg.mitigated_ts = candle.ts
                self.mitigated.append(fvg)
            else:
                still_active.append(fvg)
        self.active = still_active

    @staticmethod
    def _is_mitigated(fvg: FVG, candle: Candle) -> bool:
        """Mitigation = candle BODY closes beyond the far edge."""
        if fvg.kind == FVGType.BULLISH:
            # Mitigated when body closes below the bottom of the bullish FVG
            return candle.body_low < fvg.bottom
        else:
            # Mitigated when body closes above the top of the bearish FVG
            return candle.body_high > fvg.top

    def get_unmitigated(self, kind: FVGType | None = None) -> list[FVG]:
        if kind is None:
            return list(self.active)
        return [f for f in self.active if f.kind == kind]
