from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from smc_bot.models.base import Signal, TradeDirection, ModelType


class JournalDB:
    def __init__(self, db_path: Path | str = "journal.db"):
        self._db_path = str(db_path)
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    def _init_db(self) -> None:
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                instrument TEXT NOT NULL,
                direction TEXT NOT NULL,
                model TEXT NOT NULL,
                entry_price REAL NOT NULL,
                stop_loss REAL NOT NULL,
                tp1 REAL NOT NULL,
                tp2 REAL,
                rr_ratio REAL NOT NULL,
                score INTEGER NOT NULL,
                killzone TEXT NOT NULL,
                confluences TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id INTEGER REFERENCES signals(id),
                open_timestamp TEXT NOT NULL,
                close_timestamp TEXT,
                instrument TEXT NOT NULL,
                direction TEXT NOT NULL,
                model TEXT NOT NULL,
                entry_price REAL NOT NULL,
                exit_price REAL,
                stop_loss REAL NOT NULL,
                tp1 REAL NOT NULL,
                tp2 REAL,
                pnl_r REAL,
                outcome TEXT,
                killzone TEXT NOT NULL,
                notes TEXT
            );

            CREATE TABLE IF NOT EXISTS daily_summary (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL UNIQUE,
                total_signals INTEGER DEFAULT 0,
                total_trades INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                breakeven INTEGER DEFAULT 0,
                total_pnl_r REAL DEFAULT 0.0,
                model1_signals INTEGER DEFAULT 0,
                model2_signals INTEGER DEFAULT 0,
                best_trade_r REAL DEFAULT 0.0,
                worst_trade_r REAL DEFAULT 0.0
            );
        """)
        self._conn.commit()

    def record_signal(self, signal: Signal) -> int:
        cursor = self._conn.execute(
            """INSERT INTO signals (timestamp, instrument, direction, model,
               entry_price, stop_loss, tp1, tp2, rr_ratio, score, killzone, confluences)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                signal.timestamp.isoformat(),
                signal.instrument,
                signal.direction.value,
                signal.model.value,
                signal.entry_price,
                signal.stop_loss,
                signal.tp1,
                signal.tp2,
                signal.rr_ratio,
                signal.score,
                signal.killzone,
                json.dumps(signal.confluences),
            ),
        )
        self._conn.commit()
        return cursor.lastrowid

    def record_trade(
        self,
        signal_id: int,
        signal: Signal,
        exit_price: float | None = None,
        close_timestamp: datetime | None = None,
        pnl_r: float | None = None,
        outcome: str | None = None,
        notes: str | None = None,
    ) -> int:
        cursor = self._conn.execute(
            """INSERT INTO trades (signal_id, open_timestamp, close_timestamp,
               instrument, direction, model, entry_price, exit_price, stop_loss,
               tp1, tp2, pnl_r, outcome, killzone, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                signal_id,
                signal.timestamp.isoformat(),
                close_timestamp.isoformat() if close_timestamp else None,
                signal.instrument,
                signal.direction.value,
                signal.model.value,
                signal.entry_price,
                exit_price,
                signal.stop_loss,
                signal.tp1,
                signal.tp2,
                pnl_r,
                outcome,
                signal.killzone,
                notes,
            ),
        )
        self._conn.commit()
        return cursor.lastrowid

    def get_signals_for_date(self, date: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM signals WHERE timestamp LIKE ?", (f"{date}%",)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_trades_for_date(self, date: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM trades WHERE open_timestamp LIKE ?", (f"{date}%",)
        ).fetchall()
        return [dict(r) for r in rows]

    def update_daily_summary(self, date: str) -> None:
        signals = self.get_signals_for_date(date)
        trades = self.get_trades_for_date(date)

        wins = sum(1 for t in trades if t.get("outcome") == "win")
        losses = sum(1 for t in trades if t.get("outcome") == "loss")
        breakeven = sum(1 for t in trades if t.get("outcome") == "breakeven")
        total_pnl = sum(t.get("pnl_r", 0) or 0 for t in trades)
        model1 = sum(1 for s in signals if s["model"] == ModelType.IFVG.value)
        model2 = sum(1 for s in signals if s["model"] == ModelType.ICT2022.value)

        pnls = [t.get("pnl_r", 0) or 0 for t in trades]
        best = max(pnls) if pnls else 0
        worst = min(pnls) if pnls else 0

        self._conn.execute(
            """INSERT OR REPLACE INTO daily_summary
               (date, total_signals, total_trades, wins, losses, breakeven,
                total_pnl_r, model1_signals, model2_signals, best_trade_r, worst_trade_r)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (date, len(signals), len(trades), wins, losses, breakeven,
             total_pnl, model1, model2, best, worst),
        )
        self._conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
