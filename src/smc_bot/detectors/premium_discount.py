from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Zone(Enum):
    PREMIUM = "premium"
    DISCOUNT = "discount"
    EQUILIBRIUM = "equilibrium"


@dataclass
class DealingRange:
    swing_high: float
    swing_low: float

    @property
    def range_size(self) -> float:
        return self.swing_high - self.swing_low

    @property
    def equilibrium(self) -> float:
        return (self.swing_high + self.swing_low) / 2

    @property
    def ote_high(self) -> float:
        return self.swing_low + self.range_size * 0.79

    @property
    def ote_low(self) -> float:
        return self.swing_low + self.range_size * 0.618

    def get_zone(self, price: float) -> Zone:
        eq = self.equilibrium
        if price > eq:
            return Zone.PREMIUM
        elif price < eq:
            return Zone.DISCOUNT
        return Zone.EQUILIBRIUM

    def is_in_ote(self, price: float) -> bool:
        return self.ote_low <= price <= self.ote_high

    def fib_level(self, price: float) -> float:
        if self.range_size == 0:
            return 0.5
        return (price - self.swing_low) / self.range_size
