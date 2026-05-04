"""
Fair Value Gap (FVG) detection and mitigation tracking.

Pine-aligned rules (from IFVG Setup Detector v4, IFVG Ultimate+ v11, iFVG Final Build v22):

Bullish FVG : c0.high < c2.low  AND  c1.close > c0.high  (displacement close confirms gap)
Bearish FVG : c0.low  > c2.high AND  c1.close < c0.low   (displacement close confirms gap)

Where c0=oldest, c1=middle/displacement, c2=newest.

Wicks used for gap edges (not bodies).
CE (Consequent Encroachment) = midpoint of the zone.

Mitigation: body low crosses below FVG bottom (bull) or body high crosses above FVG top (bear).
  Pine: min(open,close) < fvg.bot  →  matches Python body_low / body_high

Expiry: FVGs that haven't been inverted within `inversion_window` bars are dropped.
  Pine default: i_invWindow = 15 bars.

Min size: optional filter — gaps smaller than min_size pts are ignored.
  Pine uses ATR(200) × 0.25. Callers should pass appropriate min_size per TF.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

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

    # Bar tracking for expiry
    bar_index: int = 0      # which bar (update call #) this FVG was created on

    # Leg tracking — which sweep leg "sponsored" this FVG
    leg_sweep_ts: datetime | None = None

    mitigated: bool = False
    mitigated_ts: datetime | None = None
    inverted: bool = False

    # bar_index is set at creation; first_touch_bar is set on the first interaction.
    first_touch_bar: int | None = None

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

    Parameters
    ----------
    timeframe        : minutes per bar (for reference)
    min_size         : minimum gap size in points (default 0 = no filter)
                       Pine uses ATR(200) × 0.25. Set per-TF in caller.
    inversion_window : drop FVGs that haven't been inverted within this many bars
                       Pine default: 15. Set 0 to disable expiry.
    """

    def __init__(
        self,
        timeframe: int,
        min_size: float = 0.0,
        inversion_window: int = 15,
    ):
        self.timeframe = timeframe
        self.min_size = min_size
        self.inversion_window = inversion_window

        self.active: list[FVG] = []       # unmitigated, unexpired FVGs
        self.mitigated: list[FVG] = []    # historical record (mitigated or expired)

        self._bar_count: int = 0          # increments each update() call

    def update(self, candles: list[Candle], leg_sweep_ts: datetime | None = None) -> list[FVG]:
        """
        Process the latest candles. Detects new FVGs and checks mitigation + expiry.
        Returns newly detected FVGs (if any).
        """
        self._bar_count += 1
        new_fvgs: list[FVG] = []

        if len(candles) >= 3:
            new = self._detect_at(candles, -1, leg_sweep_ts)
            if new:
                self.active.append(new)
                new_fvgs.append(new)

        current = candles[-1] if candles else None
        self._check_mitigation(current)
        if self.inversion_window > 0:
            self._expire_old()

        if current is not None:
            for fvg in self.active:
                if fvg.first_touch_bar is None:
                    if current.low <= fvg.top and current.high >= fvg.bottom:
                        fvg.first_touch_bar = self._bar_count

        return new_fvgs

    def _detect_at(self, candles: list[Candle], idx: int,
                   leg_sweep_ts: datetime | None) -> FVG | None:
        c0 = candles[idx - 2]   # oldest of the 3
        c1 = candles[idx - 1]   # middle / displacement candle
        c2 = candles[idx]       # newest of the 3

        # Bullish FVG: c0.high < c2.low gap, confirmed by c1 closing above c0.high
        if c0.high < c2.low and c1.close > c0.high:
            gap_size = c2.low - c0.high
            if gap_size >= self.min_size:
                return FVG(
                    id=_next_id(),
                    kind=FVGType.BULLISH,
                    timeframe=self.timeframe,
                    ts=c1.ts,
                    top=c2.low,
                    bottom=c0.high,
                    bar_index=self._bar_count,
                    leg_sweep_ts=leg_sweep_ts,
                )

        # Bearish FVG: c0.low > c2.high gap, confirmed by c1 closing below c0.low
        if c0.low > c2.high and c1.close < c0.low:
            gap_size = c0.low - c2.high
            if gap_size >= self.min_size:
                return FVG(
                    id=_next_id(),
                    kind=FVGType.BEARISH,
                    timeframe=self.timeframe,
                    ts=c1.ts,
                    top=c0.low,
                    bottom=c2.high,
                    bar_index=self._bar_count,
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

    def _expire_old(self) -> None:
        """Remove FVGs that have exceeded the inversion window without being inverted."""
        still_active = []
        for fvg in self.active:
            age = self._bar_count - fvg.bar_index
            if age > self.inversion_window:
                fvg.mitigated = True   # treat expired as mitigated for bookkeeping
                self.mitigated.append(fvg)
            else:
                still_active.append(fvg)
        self.active = still_active

    @staticmethod
    def _is_mitigated(fvg: FVG, candle: Candle) -> bool:
        """Mitigation = candle body closes beyond the far edge."""
        if fvg.kind == FVGType.BULLISH:
            return candle.body_low < fvg.bottom
        else:
            return candle.body_high > fvg.top

    def get_unmitigated(self, kind: FVGType | None = None) -> list[FVG]:
        if kind is None:
            return list(self.active)
        return [f for f in self.active if f.kind == kind]
