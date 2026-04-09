"""
Historical backtest engine.

Replays 1m candles through the full SMC pipeline:
  - MultiTFAggregator builds 3m/5m/15m/30m/1H/4H candles
  - LiquidityDetector builds levels
  - ConfluenceEngine detects setups and signals
  - TradeJournal records and simulates outcomes

Usage:
    python -m smc_bot.engine.backtest --mnq data/mnq_1m.csv --mes data/mes_1m.csv
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

from ..data.candle import CandleBuffer
from ..data.aggregator import MultiTFAggregator
from ..data.history import load_csv, load_pair
from ..detectors.fvg import FVGTracker
from ..detectors.swing import SwingDetector
from ..detectors.smt import SMTDetector
from ..detectors.liquidity import (
    detect_eqhl, detect_session_levels, detect_pdhl,
    detect_ndog, fvg_as_liquidity,
)
from ..filters.session import SESSIONS
from ..models.confluence import ConfluenceEngine
from ..journal.logger import TradeJournal
from ..journal.reporter import print_summary

# Timeframes to track (minutes)
TFS = [1, 3, 5, 15, 30, 60, 240]

# Swing lookback settings
LTF_SWING_LEFT = 5
LTF_SWING_RIGHT = 2
HTF_SWING_LEFT = 3
HTF_SWING_RIGHT = 2

# Minimum FVG size (points) for a gap to count as a liquidity level.
# Too-small FVGs flood the level list with noise — only significant imbalances matter.
MIN_FVG_SIZE: dict[int, float] = {15: 5.0, 30: 8.0, 60: 10.0, 240: 15.0}

# Cap on how many unmitigated FVGs per TF are used as sweep targets.
# Keep only the most recent ones — older ones are less relevant to current price action.
MAX_FVG_LEVELS_PER_TF = 3


def run_backtest(
    mnq_csv: Path,
    mes_csv: Optional[Path] = None,
    db_path: Optional[Path] = None,
    setup_expiry_min: int = 60,
    min_rr: float = 1.0,
    max_concurrent_trades: int = 1,
    be_trigger_r: float = 1.0,   # move SL to entry when price moves this many R in favor
    starting_balance: float = 50_000.0,   # simulated account size
    risk_pct: float = 0.005,              # risk per trade as fraction (0.5% = 0.005)
    date_from: Optional[str] = None,      # "YYYY-MM-DD" — filter candles from this date
    date_to: Optional[str] = None,        # "YYYY-MM-DD" — filter candles up to this date
    clear_db: bool = True,
    verbose: bool = True,
) -> None:
    """
    Run the full backtest.

    Args:
        mnq_csv:          Path to MNQ 1m CSV.
        mes_csv:          Path to MES 1m CSV (optional, for SMT).
        db_path:          SQLite journal path. Defaults to data/journal.db.
        setup_expiry_min: How long setups stay active.
        min_rr:           Minimum R:R to emit signal.
        verbose:          Print progress.
    """
    if db_path is None:
        db_path = mnq_csv.parent / "journal.db"

    # ── Load data ─────────────────────────────────────────────────────────────
    from datetime import timezone
    mnq_candles = load_csv(mnq_csv, timeframe=1)
    mes_candles = load_csv(mes_csv, timeframe=1) if mes_csv and mes_csv.exists() else []

    # Apply date range filter
    if date_from:
        from datetime import datetime
        dt_from = datetime.fromisoformat(date_from).replace(tzinfo=timezone.utc)
        mnq_candles = [c for c in mnq_candles if c.ts >= dt_from]
        mes_candles = [c for c in mes_candles if c.ts >= dt_from]
    if date_to:
        from datetime import datetime
        dt_to = datetime.fromisoformat(date_to).replace(tzinfo=timezone.utc)
        mnq_candles = [c for c in mnq_candles if c.ts <= dt_to]
        mes_candles = [c for c in mes_candles if c.ts <= dt_to]

    if verbose:
        date_range = ""
        if mnq_candles:
            date_range = f" ({mnq_candles[0].ts.strftime('%Y-%m-%d')} to {mnq_candles[-1].ts.strftime('%Y-%m-%d')})"
        print(f"Loaded {len(mnq_candles)} NQ bars, {len(mes_candles)} ES bars{date_range}")

    # Index MES candles by timestamp for fast lookup
    mes_by_ts = {c.ts: c for c in mes_candles}

    # ── Infrastructure ────────────────────────────────────────────────────────
    fvg_trackers = {tf: FVGTracker(timeframe=tf) for tf in TFS}
    swing_ltf  = SwingDetector(left=LTF_SWING_LEFT,  right=LTF_SWING_RIGHT)
    swing_15m  = SwingDetector(left=3, right=2)   # for 15m EQH/EQL (significant levels)
    swing_ltf_es = SwingDetector(left=LTF_SWING_LEFT, right=LTF_SWING_RIGHT)  # ES SMT
    smt = SMTDetector("NQ", "ES") if mes_candles else None

    aggregator = MultiTFAggregator(timeframes=TFS)

    engine = ConfluenceEngine(
        fvg_trackers=fvg_trackers,
        swing_detector=swing_ltf,
        smt_detector=smt,
        setup_expiry_minutes=setup_expiry_min,
        min_rr=min_rr,
    )

    journal = TradeJournal(db_path, starting_balance=starting_balance, risk_pct=risk_pct)
    if clear_db:
        journal.db.clear()

    # ── Candle buffers per TF for swing detection ─────────────────────────────
    tf_buffers: dict[int, list] = {tf: [] for tf in TFS}

    # ── Main replay loop ──────────────────────────────────────────────────────
    total_signals = 0
    for i, candle in enumerate(mnq_candles):
        # 1. Push through aggregator — builds all HTF candles
        aggregator.push(candle)
        candles_by_tf = {tf: aggregator.get(tf).as_list() for tf in TFS}

        # Update FVG trackers with latest candles
        for tf, candles in candles_by_tf.items():
            if candles:
                fvg_trackers[tf].update(candles)

        # 2. Build significant liquidity levels
        ltf_candles  = candles_by_tf.get(1,  [])
        candles_15m  = candles_by_tf.get(15, [])

        levels = []

        # EQH/EQL from 15m swing points only (significant, not 1m noise)
        swings_15m = swing_15m.detect(candles_15m) if len(candles_15m) >= 10 else []
        levels.extend(detect_eqhl(swings_15m))

        if len(ltf_candles) >= 60:
            # All session H/L (most recent occurrence of each)
            for sess_name, (sess_start, sess_end) in SESSIONS.items():
                levels.extend(detect_session_levels(ltf_candles, sess_name, sess_start, sess_end))

            # PDH / PDL
            levels.extend(detect_pdhl(ltf_candles, candle.ts.date()))

            # NDOG — gap between previous day close and current day open
            from zoneinfo import ZoneInfo
            ET = ZoneInfo("America/New_York")
            today_et = candle.ts.astimezone(ET).date()
            today_candles = [c for c in ltf_candles if c.ts.astimezone(ET).date() == today_et]
            prev_candles  = [c for c in ltf_candles if c.ts.astimezone(ET).date() < today_et]
            if today_candles and prev_candles:
                prev_close   = prev_candles[-1].close
                today_open   = today_candles[0].open
                levels.extend(detect_ndog(prev_close, today_open, today_candles[0].ts))

        # 15m, 30m, 1H, 4H unmitigated FVGs as liquidity levels.
        # LTF (1m/3m/5m) FVG edges are NOT valid sweep targets.
        # Filters: minimum gap size per TF + cap to most recent N per TF.
        for tf in [15, 30, 60, 240]:
            min_size = MIN_FVG_SIZE.get(tf, 5.0)
            candidates = [
                fvg for fvg in fvg_trackers[tf].active
                if not fvg.mitigated and fvg.size >= min_size
            ]
            # Most recent unmitigated FVGs are most relevant — cap to MAX_FVG_LEVELS_PER_TF
            for fvg in sorted(candidates, key=lambda f: f.ts, reverse=True)[:MAX_FVG_LEVELS_PER_TF]:
                levels.extend(fvg_as_liquidity(fvg.top, fvg.bottom, fvg.ts, tf=tf))

        engine.set_liquidity_levels(levels)

        # 3. Build swing points for SMT (use 1m for both instruments)
        swings_nq = swing_ltf.detect(ltf_candles) if len(ltf_candles) >= 10 else []
        swings_mes = None
        if mes_candles:
            mes_buf = [c for c in mes_candles if c.ts <= candle.ts]
            swings_mes = swing_ltf_es.detect(mes_buf[-200:]) if len(mes_buf) >= 10 else []

        # 4. Run confluence engine
        signals = engine.update(
            candle=candle,
            candles_by_tf=candles_by_tf,
            swings_nq=swings_nq,
            swings_es=swings_mes,
        )

        # 5. Record signals — one trade at a time
        for signal in signals:
            if len(journal._open) >= max_concurrent_trades:
                break   # already at capacity; discard remaining signals this candle
            trade_id = journal.record_signal(signal)
            total_signals += 1
            if verbose:
                print(
                    f"  SIGNAL [{signal.ts.strftime('%H:%M')}] "
                    f"{signal.direction.value.upper()} {signal.symbol} "
                    f"@ {signal.entry_price:.2f} | "
                    f"SL {signal.stop_loss:.2f} | TP1 {signal.tp1:.2f} | "
                    f"R:R {signal.rr_ratio:.1f} | model={signal.model.value} | "
                    f"score={signal.score}"
                )

        # 6. Check open trade outcomes (TP/SL/BE) against this candle
        journal.check_outcomes(candle.close, candle.ts, be_trigger_r=be_trigger_r)

        if verbose and i % 50 == 0:
            print(f"  [{i+1}/{len(mnq_candles)}] {candle.ts.strftime('%Y-%m-%d %H:%M')} close={candle.close}")

    # 7. Close any remaining open trades at last price
    if mnq_candles:
        last = mnq_candles[-1]
        journal.close_all_open(last.close, last.ts)

    if verbose:
        print(f"\nBacktest complete. {total_signals} signals generated.")
        print()
        print_summary(db_path, starting_balance=starting_balance)


def main():
    parser = argparse.ArgumentParser(description="SMC Bot Backtest")
    parser.add_argument("--mnq", type=Path, default=Path("data/mnq_1m.csv"))
    parser.add_argument("--mes", type=Path, default=Path("data/mes_1m.csv"))
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--min-rr", type=float, default=1.0)
    parser.add_argument("--expiry", type=int, default=60)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    run_backtest(
        mnq_csv=args.mnq,
        mes_csv=args.mes,
        db_path=args.db,
        setup_expiry_min=args.expiry,
        min_rr=args.min_rr,
        verbose=not args.quiet,
    )


if __name__ == "__main__":
    main()
