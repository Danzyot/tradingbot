from __future__ import annotations

from datetime import datetime, timedelta
from dataclasses import dataclass, field

from smc_bot.config import RiskConfig


@dataclass
class RiskState:
    daily_pnl_pct: float = 0.0
    weekly_pnl_pct: float = 0.0
    trades_today: int = 0
    open_trades: int = 0
    consecutive_losses: int = 0
    last_loss_time: datetime | None = None
    halted: bool = False
    halt_reason: str = ""


class RiskManager:
    def __init__(self, config: RiskConfig):
        self._config = config
        self._state = RiskState()

    @property
    def state(self) -> RiskState:
        return self._state

    def can_trade(self, timestamp: datetime) -> tuple[bool, str]:
        if self._state.halted:
            return False, f"Halted: {self._state.halt_reason}"

        if self._state.daily_pnl_pct <= self._config.daily_halt_pct:
            self._state.halted = True
            self._state.halt_reason = "Daily loss limit hit"
            return False, self._state.halt_reason

        if self._state.weekly_pnl_pct <= self._config.weekly_halt_pct:
            self._state.halted = True
            self._state.halt_reason = "Weekly loss limit hit"
            return False, self._state.halt_reason

        if self._state.trades_today >= self._config.max_trades_per_day:
            return False, "Max trades per day reached"

        if self._state.open_trades >= self._config.max_concurrent_trades:
            return False, "Max concurrent trades reached"

        if self._state.consecutive_losses >= self._config.consecutive_loss_pause:
            if self._state.last_loss_time:
                pause_end = self._state.last_loss_time + timedelta(
                    minutes=self._config.pause_duration_minutes
                )
                if timestamp < pause_end:
                    return False, f"Pause after {self._config.consecutive_loss_pause} consecutive losses"
                self._state.consecutive_losses = 0

        return True, ""

    def record_trade_open(self) -> None:
        self._state.trades_today += 1
        self._state.open_trades += 1

    def record_trade_close(self, pnl_pct: float, timestamp: datetime) -> None:
        self._state.open_trades = max(0, self._state.open_trades - 1)
        self._state.daily_pnl_pct += pnl_pct
        self._state.weekly_pnl_pct += pnl_pct

        if pnl_pct < 0:
            self._state.consecutive_losses += 1
            self._state.last_loss_time = timestamp
        else:
            self._state.consecutive_losses = 0

    def reset_daily(self) -> None:
        self._state.daily_pnl_pct = 0.0
        self._state.trades_today = 0
        self._state.consecutive_losses = 0
        if self._state.halt_reason == "Daily loss limit hit":
            self._state.halted = False
            self._state.halt_reason = ""

    def reset_weekly(self) -> None:
        self._state.weekly_pnl_pct = 0.0
        self._state.halted = False
        self._state.halt_reason = ""
