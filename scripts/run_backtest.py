#!/usr/bin/env python3
"""Run a backtest on historical 1m candle data."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from smc_bot.config import load_settings
from smc_bot.engine.backtest import BacktestEngine
from smc_bot.data.history import load_csv
from smc_bot.journal.reporter import generate_report, print_report


def main():
    parser = argparse.ArgumentParser(description="SMC/ICT Backtest Runner")
    parser.add_argument("csv_path", help="Path to 1m candle CSV file")
    parser.add_argument("--instrument", default="NQ", help="Instrument (NQ, ES, MNQ, MES)")
    parser.add_argument("--settings", default=None, help="Path to settings.yaml")
    parser.add_argument("--db", default="backtest_journal.db", help="Journal DB path")
    parser.add_argument("--start-date", default=None, help="Filter: start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", default=None, help="Filter: end date (YYYY-MM-DD)")
    args = parser.parse_args()

    settings_path = Path(args.settings) if args.settings else None
    settings = load_settings(settings_path)

    print(f"Loading candles from {args.csv_path}...")
    candles = load_csv(Path(args.csv_path))
    print(f"Loaded {len(candles)} candles")

    if args.start_date:
        candles = [c for c in candles if c.timestamp.strftime("%Y-%m-%d") >= args.start_date]
    if args.end_date:
        candles = [c for c in candles if c.timestamp.strftime("%Y-%m-%d") <= args.end_date]

    print(f"Running backtest on {len(candles)} candles ({args.instrument})...")
    engine = BacktestEngine(settings=settings, instrument=args.instrument, db_path=args.db)
    trades = engine.run(candles)

    print(f"\nBacktest complete!")
    print(f"Signals generated: {len(engine.signals)}")
    print(f"Trades taken: {len(trades)}")

    if trades:
        wins = sum(1 for t in trades if t.outcome == "win")
        losses = sum(1 for t in trades if t.outcome == "loss")
        total_r = sum(t.pnl_r or 0 for t in trades)
        print(f"Wins: {wins} | Losses: {losses} | Total P&L: {total_r:+.2f}R")

        if candles:
            start = candles[0].timestamp.strftime("%Y-%m-%d")
            end = candles[-1].timestamp.strftime("%Y-%m-%d")
            report = generate_report(engine.db, start, end)
            print("\n" + print_report(report))


if __name__ == "__main__":
    main()
