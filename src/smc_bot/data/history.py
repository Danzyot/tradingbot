"""Load 1m CSV candles (Databento format) into list[Candle]."""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .candle import Candle


def load_csv(path: str | Path, timeframe: int = 1, symbol: Optional[str] = None) -> list[Candle]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"CSV not found: {path}")

    candles: list[Candle] = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts_str = row["ts"].strip()
            # Handle both "2025-01-01T12:00:00" and "2025-01-01T12:00:00+00:00"
            if ts_str.endswith("Z"):
                ts_str = ts_str[:-1] + "+00:00"
            try:
                ts = datetime.fromisoformat(ts_str)
            except ValueError:
                ts = datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%S")

            # Ensure timezone-aware UTC
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)

            candles.append(
                Candle(
                    ts=ts,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                    timeframe=timeframe,
                )
            )

    candles.sort(key=lambda c: c.ts)
    return candles


def load_pair(
    mnq_path: str | Path,
    mes_path: str | Path,
) -> tuple[list[Candle], list[Candle]]:
    """Load MNQ and MES candles together, returning (mnq_candles, mes_candles)."""
    mnq = load_csv(mnq_path, timeframe=1, symbol="MNQ")
    mes = load_csv(mes_path, timeframe=1, symbol="MES")
    return mnq, mes
