"""
Trade journal — SQLite backend.

Schema:
  trades      – one row per signal fired
  setups      – one row per setup created (even if no entry)

All datetimes stored as ISO UTC strings.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Generator, Optional

DEFAULT_DB = Path(__file__).parent.parent.parent.parent / "data" / "journal.db"


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(db_path: Path = DEFAULT_DB) -> None:
    """Create tables if they don't exist."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(db_path) as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS trades (
            id              TEXT PRIMARY KEY,
            ts              TEXT NOT NULL,
            symbol          TEXT NOT NULL,
            direction       TEXT NOT NULL,   -- 'long' | 'short'
            model           TEXT NOT NULL,   -- 'ifvg' | 'ict2022'
            session         TEXT NOT NULL,

            entry_price     REAL NOT NULL,
            stop_loss       REAL NOT NULL,
            tp1             REAL NOT NULL,
            tp2             REAL NOT NULL,
            rr_ratio        REAL NOT NULL,
            score           INTEGER NOT NULL,

            -- account sizing
            risk_dollars    REAL NOT NULL DEFAULT 0,  -- dollar risk on this trade (balance * risk_pct)
            balance_before  REAL,                     -- account balance before entry

            -- outcome fields (filled after trade closes)
            outcome         TEXT,            -- 'win' | 'loss' | 'be'
            exit_price      REAL,
            exit_ts         TEXT,
            pnl_r           REAL,            -- P&L in R-multiples
            pnl_dollars     REAL,            -- P&L in dollars
            be_moved        INTEGER NOT NULL DEFAULT 0,  -- 1 if SL was moved to BE

            -- confirmation flags
            smt_bonus       INTEGER NOT NULL DEFAULT 0,
            cisd_bonus      INTEGER NOT NULL DEFAULT 0,

            -- setup context
            setup_id        TEXT NOT NULL,
            sweep_ts        TEXT NOT NULL,
            sweep_price     REAL NOT NULL,
            sweep_tier      TEXT NOT NULL,
            sweep_direction TEXT NOT NULL,

            -- Entry context
            entry_tf        INTEGER NOT NULL DEFAULT 1,  -- IFVG timeframe (1/3/5)
            confluence_desc TEXT,            -- human-readable confluence summary

            -- FVG/IFVG zone for chart drawing
            fvg_top         REAL,
            fvg_bottom      REAL,
            fvg_ts          TEXT,
            fvg_kind        TEXT,            -- 'bullish' or 'bearish'

            -- Sweep wick tip for $ marker
            sweep_wick      REAL,

            -- SMT drawing coords (orange line between diverging swings)
            smt_ts_a        TEXT,
            smt_price_a     REAL,
            smt_ts_b        TEXT,
            smt_price_b     REAL,

            -- Notion sync
            notion_page_id  TEXT,            -- set after syncing to Notion

            notes           TEXT
        );

        CREATE TABLE IF NOT EXISTS setups (
            id              TEXT PRIMARY KEY,
            created_ts      TEXT NOT NULL,
            expires_ts      TEXT NOT NULL,
            direction       TEXT NOT NULL,
            sweep_ts        TEXT NOT NULL,
            sweep_price     REAL NOT NULL,
            sweep_tier      TEXT NOT NULL,
            fired           INTEGER NOT NULL DEFAULT 0,  -- 1 if signal emitted
            expired         INTEGER NOT NULL DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS trades_ts ON trades(ts);
        CREATE INDEX IF NOT EXISTS trades_symbol ON trades(symbol);
        CREATE INDEX IF NOT EXISTS setups_created ON setups(created_ts);
        """)


@contextmanager
def get_conn(db_path: Path = DEFAULT_DB) -> Generator[sqlite3.Connection, None, None]:
    conn = _connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


class JournalDB:
    def __init__(self, db_path: Path = DEFAULT_DB):
        self.db_path = db_path
        init_db(db_path)

    def insert_trade(self, trade: dict[str, object]) -> None:
        with get_conn(self.db_path) as conn:
            conn.execute("""
                INSERT OR IGNORE INTO trades
                    (id, ts, symbol, direction, model, session,
                     entry_price, stop_loss, tp1, tp2, rr_ratio, score,
                     smt_bonus, cisd_bonus,
                     setup_id, sweep_ts, sweep_price, sweep_tier, sweep_direction,
                     entry_tf, confluence_desc,
                     fvg_top, fvg_bottom, fvg_ts, fvg_kind,
                     sweep_wick,
                     smt_ts_a, smt_price_a, smt_ts_b, smt_price_b,
                     risk_dollars, balance_before,
                     notes)
                VALUES
                    (:id, :ts, :symbol, :direction, :model, :session,
                     :entry_price, :stop_loss, :tp1, :tp2, :rr_ratio, :score,
                     :smt_bonus, :cisd_bonus,
                     :setup_id, :sweep_ts, :sweep_price, :sweep_tier, :sweep_direction,
                     :entry_tf, :confluence_desc,
                     :fvg_top, :fvg_bottom, :fvg_ts, :fvg_kind,
                     :sweep_wick,
                     :smt_ts_a, :smt_price_a, :smt_ts_b, :smt_price_b,
                     :risk_dollars, :balance_before,
                     :notes)
            """, {k: v for k, v in trade.items() if not k.startswith("_")})

    def update_outcome(
        self,
        trade_id: str,
        outcome: str,
        exit_price: float,
        exit_ts: datetime,
        pnl_r: float,
        pnl_dollars: float = 0.0,
        be_moved: bool = False,
        notes: Optional[str] = None,
    ) -> None:
        with get_conn(self.db_path) as conn:
            conn.execute("""
                UPDATE trades
                SET outcome=?, exit_price=?, exit_ts=?, pnl_r=?, pnl_dollars=?,
                    be_moved=?, notes=COALESCE(?,notes)
                WHERE id=?
            """, (outcome, exit_price, exit_ts.isoformat(), pnl_r, pnl_dollars,
                  int(be_moved), notes, trade_id))

    def set_notion_page_id(self, trade_id: str, page_id: str) -> None:
        with get_conn(self.db_path) as conn:
            conn.execute(
                "UPDATE trades SET notion_page_id=? WHERE id=?", (page_id, trade_id)
            )

    def unsynced_trades(self) -> list[sqlite3.Row]:
        """Return closed trades not yet synced to Notion."""
        with get_conn(self.db_path) as conn:
            return conn.execute(
                "SELECT * FROM trades WHERE outcome IS NOT NULL AND notion_page_id IS NULL"
            ).fetchall()

    def insert_setup(self, setup: dict[str, object]) -> None:
        with get_conn(self.db_path) as conn:
            conn.execute("""
                INSERT OR IGNORE INTO setups
                    (id, created_ts, expires_ts, direction,
                     sweep_ts, sweep_price, sweep_tier)
                VALUES
                    (:id, :created_ts, :expires_ts, :direction,
                     :sweep_ts, :sweep_price, :sweep_tier)
            """, setup)

    def mark_setup_fired(self, setup_id: str) -> None:
        with get_conn(self.db_path) as conn:
            conn.execute("UPDATE setups SET fired=1 WHERE id=?", (setup_id,))

    def mark_setup_expired(self, setup_id: str) -> None:
        with get_conn(self.db_path) as conn:
            conn.execute("UPDATE setups SET expired=1 WHERE id=?", (setup_id,))

    def clear(self) -> None:
        """Delete all trades and setups — use before each fresh backtest run."""
        with get_conn(self.db_path) as conn:
            conn.execute("DELETE FROM trades")
            conn.execute("DELETE FROM setups")

    def all_trades(self) -> list[sqlite3.Row]:
        with get_conn(self.db_path) as conn:
            return conn.execute("SELECT * FROM trades ORDER BY ts").fetchall()

    def open_trades(self) -> list[sqlite3.Row]:
        with get_conn(self.db_path) as conn:
            return conn.execute(
                "SELECT * FROM trades WHERE outcome IS NULL ORDER BY ts"
            ).fetchall()
