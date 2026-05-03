from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class TradeDirection(Enum):
    LONG = "long"
    SHORT = "short"


class SetupState(Enum):
    PENDING = "pending"
    TRIGGERED = "triggered"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ModelType(Enum):
    IFVG = "model1_ifvg"
    ICT2022 = "model2_ict2022"


@dataclass
class Signal:
    direction: TradeDirection
    model: ModelType
    entry_price: float
    stop_loss: float
    tp1: float
    tp2: float | None
    timestamp: datetime
    instrument: str
    killzone: str
    score: int = 0
    confluences: dict[str, Any] = field(default_factory=dict)

    @property
    def risk(self) -> float:
        return abs(self.entry_price - self.stop_loss)

    @property
    def reward_tp1(self) -> float:
        return abs(self.tp1 - self.entry_price)

    @property
    def rr_ratio(self) -> float:
        if self.risk == 0:
            return 0
        return self.reward_tp1 / self.risk


@dataclass
class Setup:
    direction: TradeDirection
    sweep_price: float
    sweep_timestamp: datetime
    expiry: datetime
    state: SetupState = SetupState.PENDING
    model: ModelType | None = None
    signal: Signal | None = None
    confluences: dict[str, Any] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        return self.state == SetupState.EXPIRED

    @property
    def is_active(self) -> bool:
        return self.state == SetupState.PENDING

    def expire(self) -> None:
        self.state = SetupState.EXPIRED

    def trigger(self, signal: Signal) -> None:
        self.state = SetupState.TRIGGERED
        self.signal = signal
        self.model = signal.model
