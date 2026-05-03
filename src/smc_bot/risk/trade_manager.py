from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from smc_bot.data.candle import Candle
from smc_bot.models.base import Signal, TradeDirection


class TradeState(Enum):
    OPEN = "open"
    TP1_HIT = "tp1_hit"
    CLOSED = "closed"


@dataclass
class ManagedTrade:
    signal: Signal
    contracts: int
    state: TradeState = TradeState.OPEN
    remaining_contracts: int = 0
    current_sl: float = 0.0
    entry_time: datetime | None = None
    tp1_time: datetime | None = None
    close_time: datetime | None = None
    exit_price: float | None = None
    pnl_r: float = 0.0

    def __post_init__(self):
        self.remaining_contracts = self.contracts
        self.current_sl = self.signal.stop_loss


class TradeManager:
    def __init__(self, tp1_close_pct: float = 50.0):
        self._tp1_close_pct = tp1_close_pct
        self._trades: list[ManagedTrade] = []

    @property
    def open_trades(self) -> list[ManagedTrade]:
        return [t for t in self._trades if t.state != TradeState.CLOSED]

    @property
    def closed_trades(self) -> list[ManagedTrade]:
        return [t for t in self._trades if t.state == TradeState.CLOSED]

    def open_trade(self, signal: Signal, contracts: int, timestamp: datetime) -> ManagedTrade:
        trade = ManagedTrade(
            signal=signal,
            contracts=contracts,
            entry_time=timestamp,
        )
        self._trades.append(trade)
        return trade

    def update(self, candle: Candle) -> list[ManagedTrade]:
        closed_trades: list[ManagedTrade] = []

        for trade in self.open_trades:
            result = self._check_trade(trade, candle)
            if result:
                closed_trades.append(trade)

        return closed_trades

    def _check_trade(self, trade: ManagedTrade, candle: Candle) -> bool:
        signal = trade.signal

        if signal.direction == TradeDirection.LONG:
            if candle.low <= trade.current_sl:
                self._close_trade(trade, trade.current_sl, candle.timestamp)
                return True

            if trade.state == TradeState.OPEN and candle.high >= signal.tp1:
                self._partial_close_tp1(trade, candle.timestamp)

            if trade.state == TradeState.TP1_HIT:
                if signal.tp2 and candle.high >= signal.tp2:
                    self._close_trade(trade, signal.tp2, candle.timestamp)
                    return True
        else:
            if candle.high >= trade.current_sl:
                self._close_trade(trade, trade.current_sl, candle.timestamp)
                return True

            if trade.state == TradeState.OPEN and candle.low <= signal.tp1:
                self._partial_close_tp1(trade, candle.timestamp)

            if trade.state == TradeState.TP1_HIT:
                if signal.tp2 and candle.low <= signal.tp2:
                    self._close_trade(trade, signal.tp2, candle.timestamp)
                    return True

        return False

    def _partial_close_tp1(self, trade: ManagedTrade, timestamp: datetime) -> None:
        close_amount = int(trade.contracts * self._tp1_close_pct / 100)
        trade.remaining_contracts = trade.contracts - close_amount
        trade.state = TradeState.TP1_HIT
        trade.tp1_time = timestamp
        trade.current_sl = trade.signal.entry_price

    def _close_trade(self, trade: ManagedTrade, price: float, timestamp: datetime) -> None:
        trade.state = TradeState.CLOSED
        trade.exit_price = price
        trade.close_time = timestamp
        trade.remaining_contracts = 0

        risk = trade.signal.risk
        if risk > 0:
            if trade.signal.direction == TradeDirection.LONG:
                trade.pnl_r = (price - trade.signal.entry_price) / risk
            else:
                trade.pnl_r = (trade.signal.entry_price - price) / risk
