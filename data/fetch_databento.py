"""
Databento historical data downloader for MNQ + MES 1m OHLCV bars.

Setup:
  1. Sign up at https://databento.com (free account)
  2. Go to API Keys → copy your key
  3. pip install databento
  4. Set env var: DATABENTO_API_KEY=db-xxxx
     Or paste it in API_KEY below for a one-time run.
  5. Run: python data/fetch_databento.py

Cost check:
  The script prints the estimated cost BEFORE downloading.
  Confirm when prompted. A 2-year pull of MNQ+MES 1m is typically ~$5-20.

Output:
  data/mnq_1m.csv  (appended or overwritten — see OVERWRITE flag below)
  data/mes_1m.csv
"""
from __future__ import annotations

import csv
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Configuration ─────────────────────────────────────────────────────────────

API_KEY = os.environ.get("DATABENTO_API_KEY", "")  # or paste key here

# Date range — adjust as needed
START_DATE = "2023-01-01"   # start of history to download
END_DATE   = "2026-04-09"   # end date (today)

# Databento dataset + symbols
DATASET  = "GLBX.MDP3"      # CME Globex
SCHEMA   = "ohlcv-1m"       # 1-minute OHLCV bars
SYMBOLS  = {
    "NQ":  "NQ.c.0",        # continuous front-month NQ (full size, for backtesting)
    "ES":  "ES.c.0",        # continuous front-month ES (full size, for backtesting)
    # MNQ/MES used for live demo/live trading — download separately if needed
}
STYPE_IN = "continuous"     # tells Databento we're using .c.0 continuous symbols

# Output paths
DATA_DIR = Path(__file__).parent
OVERWRITE = True            # True = replace existing CSVs; False = append new bars only

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    try:
        import databento as db
    except ImportError:
        print("ERROR: databento package not installed.")
        print("Run: pip install databento")
        sys.exit(1)

    key = API_KEY or os.environ.get("DATABENTO_API_KEY", "")
    if not key:
        print("ERROR: DATABENTO_API_KEY not set.")
        print("Set env var or paste your key into API_KEY in this file.")
        sys.exit(1)

    client = db.Historical(key)

    for symbol_name, dbn_symbol in SYMBOLS.items():
        out_path = DATA_DIR / f"{symbol_name.lower()}_1m.csv"
        print(f"\n{'='*60}")
        print(f"Fetching {symbol_name} ({dbn_symbol})  {START_DATE} → {END_DATE}")

        # Cost check first — no charge until you confirm
        try:
            cost = client.metadata.get_cost(
                dataset=DATASET,
                symbols=[dbn_symbol],
                schema=SCHEMA,
                start=START_DATE,
                end=END_DATE,
                stype_in=STYPE_IN,
            )
            print(f"Estimated cost: ${cost:.4f} USD")
        except Exception as e:
            print(f"Could not fetch cost estimate: {e}")
            cost = None

        answer = input("Download? [y/N] ").strip().lower()
        if answer != "y":
            print("Skipped.")
            continue

        print("Downloading...")
        data = client.timeseries.get_range(
            dataset=DATASET,
            symbols=[dbn_symbol],
            schema=SCHEMA,
            start=START_DATE,
            end=END_DATE,
            stype_in=STYPE_IN,
        )

        df = data.to_df()
        print(f"  Got {len(df):,} bars")

        if df.empty:
            print("  No data returned. Check symbol/date range.")
            continue

        _save_csv(df, out_path, symbol_name)
        print(f"  Saved → {out_path}")


def _save_csv(df, out_path: Path, symbol: str) -> None:
    """Write DataFrame to CSV in the format expected by load_csv()."""
    import pandas as pd

    # Databento ohlcv-1m columns: open, high, low, close, volume
    # Index is the timestamp (UTC nanoseconds → datetime)
    df = df.copy()

    # Ensure the index is a datetime
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index, utc=True)
    elif df.index.tz is None:
        df.index = df.index.tz_localize("UTC")

    # Keep only trading hours if desired (comment out to keep full 24h)
    # Futures trade ~23h/day; all bars are valid for our pipeline
    rows = []
    for ts, row in df.iterrows():
        rows.append({
            "ts":     ts.strftime("%Y-%m-%dT%H:%M:%S"),
            "open":   row["open"],
            "high":   row["high"],
            "low":    row["low"],
            "close":  row["close"],
            "volume": int(row["volume"]),
            "symbol": symbol,
        })

    if not rows:
        return

    mode = "w" if OVERWRITE else "a"
    write_header = OVERWRITE or not out_path.exists()

    with open(out_path, mode, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["ts", "open", "high", "low", "close", "volume", "symbol"])
        if write_header:
            writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
