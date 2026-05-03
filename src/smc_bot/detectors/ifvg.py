from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from smc_bot.data.candle import Candle
from smc_bot.detectors.fvg import FVG, FVGDirection


class IFVGDirection(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"


@dataclass
class IFVG:
    direction: IFVGDirection
    high: float
    low: float
    timestamp: datetime
    inversion_timestamp: datetime
    timeframe: str
    source_fvg: FVG
    sweep_timestamp: datetime | None = None

    @property
    def ce(self) -> float:
        return (self.high + self.low) / 2


class IFVGDetector:
    def __init__(self, timeframe: str = "1m"):
        self._timeframe = timeframe
        self._tracked_fvgs: list[FVG] = []
        self._ifvgs: list[IFVG] = []

    @property
    def ifvgs(self) -> list[IFVG]:
        return self._ifvgs

    def track_fvg(self, fvg: FVG) -> None:
        if not fvg.mitigated:
            self._tracked_fvgs.append(fvg)

    def track_fvgs_from_sweep(self, fvgs: list[FVG], sweep_timestamp: datetime) -> None:
        for fvg in fvgs:
            if not fvg.mitigated:
                fvg_copy = FVG(
                    direction=fvg.direction,
                    high=fvg.high,
                    low=fvg.low,
                    timestamp=fvg.timestamp,
                    timeframe=fvg.timeframe,
                    index=fvg.index,
                )
                self._tracked_fvgs.append(fvg_copy)

    def update(self, candle: Candle, sweep_timestamp: datetime | None = None) -> list[IFVG]:
        new_ifvgs: list[IFVG] = []
        remaining: list[FVG] = []

        for fvg in self._tracked_fvgs:
            ifvg = self._check_inversion(fvg, candle, sweep_timestamp)
            if ifvg is not None:
                self._ifvgs.append(ifvg)
                new_ifvgs.append(ifvg)
            else:
                remaining.append(fvg)

        self._tracked_fvgs = remaining
        return new_ifvgs

    def _check_inversion(
        self, fvg: FVG, candle: Candle, sweep_timestamp: datetime | None
    ) -> IFVG | None:
        if fvg.direction == FVGDirection.BEARISH:
            if candle.body_high > fvg.high:
                return IFVG(
                    direction=IFVGDirection.BULLISH,
                    high=fvg.high,
                    low=fvg.low,
                    timestamp=fvg.timestamp,
                    inversion_timestamp=candle.timestamp,
                    timeframe=self._timeframe,
                    source_fvg=fvg,
                    sweep_timestamp=sweep_timestamp,
                )
        elif fvg.direction == FVGDirection.BULLISH:
            if candle.body_low < fvg.low:
                return IFVG(
                    direction=IFVGDirection.BEARISH,
                    high=fvg.high,
                    low=fvg.low,
                    timestamp=fvg.timestamp,
                    inversion_timestamp=candle.timestamp,
                    timeframe=self._timeframe,
                    source_fvg=fvg,
                    sweep_timestamp=sweep_timestamp,
                )
        return None


def select_highest_tf_ifvg(
    ifvgs: dict[str, list[IFVG]],
    preferred_order: list[str] | None = None,
) -> IFVG | None:
    if preferred_order is None:
        preferred_order = ["5m", "3m", "1m"]

    for tf in preferred_order:
        tf_ifvgs = ifvgs.get(tf, [])
        if tf_ifvgs:
            return tf_ifvgs[-1]
    return None
