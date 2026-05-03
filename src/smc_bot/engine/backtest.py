from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from smc_bot.config import Settings, load_settings
from smc_bot.data.aggregator import MultiTFAggregator
from smc_bot.data.candle import Candle
from smc_bot.data.history import load_csv
from smc_bot.journal.database import JournalDB
from smc_bot.journal.logger import log_signal, setup_logging
from smc_bot.models.base import Signal, TradeDirection
from smc_bot.models.confluence import ConfluenceEngine


@dataclass
class BacktestTrade:
    signal: Signal
    signal_id: int
    entry_candle_idx: int
    exit_candle_idx: int | None = None
    exit_price: float | None = None
    pnl_r: float | None = None
    outcome: str | None = None


class BacktestEngine:
    def __init__(
        self,
        settings: Settings | None = None,
        instrument: str = "NQ",
        db_path: str = "backtest_journal.db",
    ):
        self._settings = settings or load_settings()
        self._instrument = instrument
        self._aggregator = MultiTFAggregator(
            timeframes=self._settings.fvg.timeframes
        )
        self._engine = ConfluenceEngine(self._settings, instrument=instrument)
        self._db = JournalDB(db_path)
        self._trades: list[BacktestTrade] = []
        self._open_trades: list[BacktestTrade] = []
        self._candle_idx = 0

    @property
    def trades(self) -> list[BacktestTrade]:
        return self._trades

    @property
    def signals(self) -> list[Signal]:
        return self._engine.signals

    @property
    def db(self) -> JournalDB:
        return self._db

    def run(self, candles_1m: list[Candle]) -> list[BacktestTrade]:
        setup_logging()
        logger.info(f"Starting backtest: {len(candles_1m)} candles, instrument={self._instrument}")

        for candle in candles_1m:
            self._process_candle(candle)
            self._candle_idx += 1

        self._aggregator.flush()

        for trade in self._open_trades:
            trade.exit_price = candles_1m[-1].close if candles_1m else None
            trade.exit_candle_idx = self._candle_idx - 1
            trade.outcome = "open_at_end"
            if trade.exit_price and trade.signal.risk > 0:
                if trade.signal.direction == TradeDirection.LONG:
                    trade.pnl_r = (trade.exit_price - trade.signal.entry_price) / trade.signal.risk
                else:
                    trade.pnl_r = (trade.signal.entry_price - trade.exit_price) / trade.signal.risk

        self._trades.extend(self._open_trades)
        self._open_trades.clear()

        logger.info(
            f"Backtest complete: {len(self._engine.signals)} signals, "
            f"{len(self._trades)} trades"
        )
        return self._trades

    def _process_candle(self, candle: Candle) -> None:
        completed = self._aggregator.feed(candle)

        for tf, tf_candle in completed.items():
            if tf_candle is not None:
                new_signals = self._engine.update(tf, tf_candle)
                for signal in new_signals:
                    log_signal(signal)
                    signal_id = self._db.record_signal(signal)
                    trade = BacktestTrade(
                        signal=signal,
                        signal_id=signal_id,
                        entry_candle_idx=self._candle_idx,
                    )
                    self._open_trades.append(trade)

        self._manage_open_trades(candle)

    def _manage_open_trades(self, candle: Candle) -> None:
        closed: list[BacktestTrade] = []

        for trade in self._open_trades:
            signal = trade.signal

            if signal.direction == TradeDirection.LONG:
                if candle.low <= signal.stop_loss:
                    trade.exit_price = signal.stop_loss
                    trade.pnl_r = -1.0
                    trade.outcome = "loss"
                    trade.exit_candle_idx = self._candle_idx
                    closed.append(trade)
                elif candle.high >= signal.tp1:
                    trade.exit_price = signal.tp1
                    trade.pnl_r = signal.rr_ratio
                    trade.outcome = "win"
                    trade.exit_candle_idx = self._candle_idx
                    closed.append(trade)
            else:
                if candle.high >= signal.stop_loss:
                    trade.exit_price = signal.stop_loss
                    trade.pnl_r = -1.0
                    trade.outcome = "loss"
                    trade.exit_candle_idx = self._candle_idx
                    closed.append(trade)
                elif candle.low <= signal.tp1:
                    trade.exit_price = signal.tp1
                    trade.pnl_r = signal.rr_ratio
                    trade.outcome = "win"
                    trade.exit_candle_idx = self._candle_idx
                    closed.append(trade)

        for trade in closed:
            self._open_trades.remove(trade)
            self._trades.append(trade)
            self._db.record_trade(
                signal_id=trade.signal_id,
                signal=trade.signal,
                exit_price=trade.exit_price,
                close_timestamp=candle.timestamp if trade.exit_price else None,
                pnl_r=trade.pnl_r,
                outcome=trade.outcome,
            )


def run_backtest_from_csv(
    csv_path: str | Path,
    settings_path: str | Path | None = None,
    instrument: str = "NQ",
    db_path: str = "backtest_journal.db",
) -> BacktestEngine:
    settings = load_settings(Path(settings_path)) if settings_path else load_settings()
    candles = load_csv(Path(csv_path))

    engine = BacktestEngine(settings=settings, instrument=instrument, db_path=db_path)
    engine.run(candles)
    return engine
