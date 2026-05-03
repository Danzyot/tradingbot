from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from smc_bot.data.candle import Candle


def load_csv(
    path: Path,
    timestamp_col: str = "timestamp",
    date_format: str | None = None,
    tz: str = "America/New_York",
) -> list[Candle]:
    df = pd.read_csv(path)

    col_map = {}
    for col in df.columns:
        lower = col.lower().strip()
        if lower in ("timestamp", "date", "time", "datetime"):
            col_map["timestamp"] = col
        elif lower == "open":
            col_map["open"] = col
        elif lower == "high":
            col_map["high"] = col
        elif lower == "low":
            col_map["low"] = col
        elif lower == "close":
            col_map["close"] = col
        elif lower in ("volume", "vol"):
            col_map["volume"] = col

    if "timestamp" not in col_map:
        col_map["timestamp"] = timestamp_col

    ts_series = pd.to_datetime(df[col_map["timestamp"]], format=date_format)
    if ts_series.dt.tz is None:
        ts_series = ts_series.dt.tz_localize(tz)

    candles: list[Candle] = []
    for i in range(len(df)):
        candles.append(
            Candle(
                timestamp=ts_series.iloc[i].to_pydatetime(),
                open=float(df[col_map["open"]].iloc[i]),
                high=float(df[col_map["high"]].iloc[i]),
                low=float(df[col_map["low"]].iloc[i]),
                close=float(df[col_map["close"]].iloc[i]),
                volume=float(df[col_map.get("volume", col_map["close"])].iloc[i])
                if "volume" in col_map
                else 0.0,
            )
        )
    return candles


def load_parquet(path: Path, tz: str = "America/New_York") -> list[Candle]:
    df = pd.read_parquet(path)
    if "timestamp" in df.columns:
        ts_col = "timestamp"
    elif "datetime" in df.columns:
        ts_col = "datetime"
    else:
        ts_col = df.columns[0]

    ts_series = pd.to_datetime(df[ts_col])
    if ts_series.dt.tz is None:
        ts_series = ts_series.dt.tz_localize(tz)

    candles: list[Candle] = []
    for i in range(len(df)):
        candles.append(
            Candle(
                timestamp=ts_series.iloc[i].to_pydatetime(),
                open=float(df["open"].iloc[i]),
                high=float(df["high"].iloc[i]),
                low=float(df["low"].iloc[i]),
                close=float(df["close"].iloc[i]),
                volume=float(df["volume"].iloc[i]) if "volume" in df.columns else 0.0,
            )
        )
    return candles
