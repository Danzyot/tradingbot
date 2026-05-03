from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from smc_bot.data.candle import Candle
from smc_bot.detectors.liquidity import DOLTier, LiquidityLevel, LiquidityType


class SweepDirection(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"


@dataclass
class Sweep:
    direction: SweepDirection
    level: LiquidityLevel
    price: float
    timestamp: datetime
    candle: Candle
    tier: DOLTier

    @property
    def is_valid_tier(self) -> bool:
        return self.tier in (DOLTier.S, DOLTier.A, DOLTier.B)


class SweepDetector:
    def __init__(self, cooldown_minutes: int = 5):
        self._cooldown = timedelta(minutes=cooldown_minutes)
        self._sweeps: list[Sweep] = []
        self._last_sweep_time: datetime | None = None

    @property
    def sweeps(self) -> list[Sweep]:
        return self._sweeps

    @property
    def last_sweep(self) -> Sweep | None:
        return self._sweeps[-1] if self._sweeps else None

    def update(self, candle: Candle, levels: list[LiquidityLevel]) -> list[Sweep]:
        new_sweeps: list[Sweep] = []

        if self._last_sweep_time and (candle.timestamp - self._last_sweep_time) < self._cooldown:
            return new_sweeps

        for level in levels:
            if level.swept:
                continue
            if level.tier == DOLTier.F:
                continue

            sweep = self._check_sweep(candle, level)
            if sweep is not None and sweep.is_valid_tier:
                new_sweeps.append(sweep)
                level.swept = True
                level.sweep_timestamp = candle.timestamp
                self._last_sweep_time = candle.timestamp

        self._sweeps.extend(new_sweeps)
        return new_sweeps

    def _check_sweep(self, candle: Candle, level: LiquidityLevel) -> Sweep | None:
        if level.type in (
            LiquidityType.EQL,
            LiquidityType.PDL,
            LiquidityType.SESSION_LOW,
            LiquidityType.NWOG_LOW,
            LiquidityType.NDOG_LOW,
            LiquidityType.WEAK_LOW,
        ):
            if candle.low < level.price and candle.body_low > level.price:
                return Sweep(
                    direction=SweepDirection.BULLISH,
                    level=level,
                    price=candle.low,
                    timestamp=candle.timestamp,
                    candle=candle,
                    tier=level.tier,
                )

        if level.type in (
            LiquidityType.EQH,
            LiquidityType.PDH,
            LiquidityType.SESSION_HIGH,
            LiquidityType.NWOG_HIGH,
            LiquidityType.NDOG_HIGH,
            LiquidityType.WEAK_HIGH,
            LiquidityType.UNMITIGATED_FVG,
        ):
            if candle.high > level.price and candle.body_high < level.price:
                return Sweep(
                    direction=SweepDirection.BEARISH,
                    level=level,
                    price=candle.high,
                    timestamp=candle.timestamp,
                    candle=candle,
                    tier=level.tier,
                )

        return None
