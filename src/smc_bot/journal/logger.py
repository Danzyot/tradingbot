"""
Journal logger — converts Signal/Setup objects to DB rows and manages trade lifecycle.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..models.base import Signal, Setup, TradeDirection
from .database import JournalDB, DEFAULT_DB


class TradeJournal:
    """
    Records signals as trades and tracks their outcome.

    In backtest mode, outcomes are simulated by checking subsequent candles
    against TP1 / SL levels.

    BE (breakeven) logic:
      When price moves `be_trigger_r` R in favor, the SL in _open is updated
      to entry (breakeven). From that point, hitting the SL = BE outcome.
    """

    def __init__(
        self,
        db_path: Path = DEFAULT_DB,
        starting_balance: float = 50_000.0,
        risk_pct: float = 0.005,   # 0.5% risk per trade
    ):
        self.db = JournalDB(db_path)
        self.balance = starting_balance
        self.starting_balance = starting_balance
        self.risk_pct = risk_pct
        # _open: trade_id → trade_dict (mutable — SL updates for BE)
        self._open: dict[str, dict] = {}
        # balance history: list of (trade_id, balance_after)
        self.balance_history: list[tuple[str, float]] = []

    # ── Signal recording ──────────────────────────────────────────────────────

    def record_signal(self, signal: Signal) -> str:
        """Log a signal as a new trade. Returns the trade ID."""
        trade_id = str(uuid.uuid4())[:8]
        risk_dollars = round(self.balance * self.risk_pct, 2)
        row = {
            "id": trade_id,
            "ts": signal.ts.isoformat(),
            "symbol": signal.symbol,
            "direction": signal.direction.value,
            "model": signal.model.value,
            "session": signal.session,
            "entry_price": signal.entry_price,
            "stop_loss": signal.stop_loss,   # may be updated to BE later
            "tp1": signal.tp1,
            "tp2": signal.tp2,
            "rr_ratio": signal.rr_ratio,
            "score": signal.score,
            "smt_bonus": int(signal.smt_bonus),
            "cisd_bonus": int(signal.cisd_bonus),
            "setup_id": signal.setup.id,
            "sweep_ts": signal.setup.sweep.ts.isoformat(),
            "sweep_price": signal.setup.sweep.level.price,
            "sweep_tier": signal.setup.sweep.level.tier.value,
            "sweep_direction": signal.setup.sweep.direction.value,
            "entry_tf": signal.entry_tf,
            "confluence_desc": signal.confluence_desc or None,
            "fvg_top": signal.fvg_top,
            "fvg_bottom": signal.fvg_bottom,
            "fvg_ts": signal.fvg_ts.isoformat() if signal.fvg_ts else None,
            "fvg_kind": signal.fvg_kind,
            "sweep_wick": signal.sweep_wick,
            "smt_ts_a": signal.smt_ts_a.isoformat() if signal.smt_ts_a else None,
            "smt_price_a": signal.smt_price_a,
            "smt_ts_b": signal.smt_ts_b.isoformat() if signal.smt_ts_b else None,
            "smt_price_b": signal.smt_price_b,
            "risk_dollars": risk_dollars,
            "balance_before": round(self.balance, 2),
            "notes": None,
            # Internal tracking
            "_original_sl": signal.stop_loss,
            "_be_moved": False,
        }
        self.db.insert_trade(row)
        self.db.mark_setup_fired(signal.setup.id)
        self._open[trade_id] = row
        return trade_id

    def record_setup(self, setup: Setup) -> None:
        """Log a newly created setup (before entry fires)."""
        self.db.insert_setup({
            "id": setup.id,
            "created_ts": setup.created_ts.isoformat(),
            "expires_ts": setup.expires_ts.isoformat(),
            "direction": setup.direction.value,
            "sweep_ts": setup.sweep.ts.isoformat(),
            "sweep_price": setup.sweep.level.price,
            "sweep_tier": setup.sweep.level.tier.value,
        })

    def record_setup_expired(self, setup: Setup) -> None:
        self.db.mark_setup_expired(setup.id)

    # ── Outcome simulation ────────────────────────────────────────────────────

    def check_outcomes(
        self,
        candle_close: float,
        candle_ts: datetime,
        be_trigger_r: float = 1.0,
    ) -> None:
        """
        For each open trade, check if TP1, SL, or BE was hit on this candle.
        Uses close price as fill assumption (conservative — real fills use high/low).

        Args:
            candle_close:  Closing price of the current candle.
            candle_ts:     Timestamp of the candle.
            be_trigger_r:  Move SL to entry when price moves this many R in favor.
                           Set to 0 to disable BE entirely.
        """
        for trade_id, trade in list(self._open.items()):
            direction = trade["direction"]
            entry = trade["entry_price"]
            sl = trade["stop_loss"]
            tp1 = trade["tp1"]
            original_sl = trade["_original_sl"]
            be_moved = trade["_be_moved"]

            risk = abs(entry - original_sl)
            if risk == 0:
                continue

            # BE logic: if price has moved be_trigger_r * risk in our favor,
            # slide SL to entry (only once)
            if be_trigger_r > 0 and not be_moved:
                be_price = (
                    entry + be_trigger_r * risk if direction == "long"
                    else entry - be_trigger_r * risk
                )
                if (direction == "long" and candle_close >= be_price) or \
                   (direction == "short" and candle_close <= be_price):
                    trade["stop_loss"] = entry
                    trade["_be_moved"] = True
                    sl = entry  # use updated SL for this candle's check

            # Check exit conditions
            if direction == "long":
                hit_tp = candle_close >= tp1
                hit_sl = candle_close <= sl
            else:
                hit_tp = candle_close <= tp1
                hit_sl = candle_close >= sl

            risk_dollars = trade.get("risk_dollars", 0.0)

            if hit_tp:
                reward = abs(tp1 - entry)
                pnl_r = round(reward / risk, 2)
                pnl_dollars = round(pnl_r * risk_dollars, 2)
                self.db.update_outcome(trade_id, "win", tp1, candle_ts, pnl_r,
                                       pnl_dollars=pnl_dollars, be_moved=be_moved)
                self.balance += pnl_dollars
                self.balance_history.append((trade_id, round(self.balance, 2)))
                del self._open[trade_id]
            elif hit_sl:
                if sl == entry:
                    self.db.update_outcome(trade_id, "be", entry, candle_ts, 0.0,
                                           pnl_dollars=0.0, be_moved=True)
                    self.balance_history.append((trade_id, round(self.balance, 2)))
                else:
                    pnl_dollars = -risk_dollars
                    self.db.update_outcome(trade_id, "loss", sl, candle_ts, -1.0,
                                           pnl_dollars=pnl_dollars, be_moved=be_moved)
                    self.balance += pnl_dollars
                    self.balance_history.append((trade_id, round(self.balance, 2)))
                del self._open[trade_id]

    def close_all_open(self, final_price: float, final_ts: datetime) -> None:
        """Force-close all open trades at end of backtest (at market)."""
        for trade_id, trade in list(self._open.items()):
            entry = trade["entry_price"]
            original_sl = trade["_original_sl"]
            risk = abs(entry - original_sl)
            risk_dollars = trade.get("risk_dollars", 0.0)
            if trade["direction"] == "long":
                pnl_r = (final_price - entry) / risk if risk > 0 else 0
            else:
                pnl_r = (entry - final_price) / risk if risk > 0 else 0
            pnl_r = round(pnl_r, 2)
            pnl_dollars = round(pnl_r * risk_dollars, 2)
            outcome = "win" if pnl_r > 0.0 else ("be" if abs(pnl_r) < 0.01 else "loss")
            self.db.update_outcome(trade_id, outcome, final_price, final_ts,
                                   pnl_r, pnl_dollars=pnl_dollars)
            self.balance += pnl_dollars
            self.balance_history.append((trade_id, round(self.balance, 2)))
        self._open.clear()
