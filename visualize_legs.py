"""
Generate per-day candlestick charts showing swing highs/lows and manipulation legs.
Reads the JSON produced by run_legs_scan.py.

Each chart (5m candles, one per trading day with quality sweeps) shows:
  - Swing highs ▲ and swing lows ▼ as text markers (5m, left=5 right=2)
  - Swept liquidity level as a dashed horizontal line
  - Full manipulation leg as a shaded zone (leg_start_ts → sweep_ts)
  - Leg extreme as a gold × marker (where SL would be placed)
  - NO entry / SL / TP / IFVG markers — pure structure visualization

Usage:
    python visualize_legs.py
    python visualize_legs.py --json data/legs_scan.json --from 2023-01-02 --to 2023-01-10
    python visualize_legs.py --upload          # also post to Discord webhook
"""
import sys, json, argparse, os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import mplfinance as mpf
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

sys.path.insert(0, "src")

NQ_CSV    = Path("data/nq_1m.csv")
LEGS_JSON = Path("data/legs_scan.json")
OUT_DIR   = Path("data/screenshots/legs")
ET        = ZoneInfo("America/New_York")

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")


def parse_ts(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def load_ohlcv(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path, parse_dates=["ts"], index_col="ts")
    df.index = pd.DatetimeIndex(df.index)
    if df.index.tzinfo is None:
        df.index = df.index.tz_localize("UTC")
    df.columns = [c.capitalize() for c in df.columns]
    if "Volume" not in df.columns:
        df["Volume"] = 0
    return df


def generate_day_chart(
    day_str: str,
    sweeps: list[dict],
    swings: list[dict],
    df_1m: pd.DataFrame,
    out_dir: Path,
) -> "Path | None":
    day_dt    = datetime.strptime(day_str, "%Y-%m-%d").replace(tzinfo=ET)
    day_start = day_dt.replace(hour=0,  minute=0,  second=0).astimezone(timezone.utc)
    day_end   = day_dt.replace(hour=23, minute=59, second=59).astimezone(timezone.utc)

    df_day = df_1m.loc[day_start:day_end]
    if df_day.empty:
        return None

    # Resample to 5m for the chart
    df_5m = df_day.resample("5min", label="left", closed="left").agg({
        "Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"
    }).dropna()
    if len(df_5m) < 10:
        return None

    df_5m.index = df_5m.index.tz_convert(ET)
    n = len(df_5m)

    def ts_to_x(ts: datetime) -> int:
        ts_et = ts.astimezone(ET)
        idx = df_5m.index.searchsorted(ts_et)
        return int(min(idx, n - 1))

    fig, axes = mpf.plot(
        df_5m,
        type="candle",
        style="nightclouds",
        returnfig=True,
        figsize=(18, 7),
        ylabel="Price",
        tight_layout=True,
    )
    ax = axes[0]

    # ── Swing markers ─────────────────────────────────────────────────────────
    day_swings = [s for s in swings if day_start <= parse_ts(s["ts"]) <= day_end]
    price_range = df_5m["High"].max() - df_5m["Low"].min()
    offset = max(price_range * 0.004, 3.0)   # 0.4% of range, min 3pt

    for s in day_swings:
        x = ts_to_x(parse_ts(s["ts"]))
        p = s["price"]
        if s["kind"] == "high":
            ax.annotate("▲", xy=(x, p + offset), fontsize=8,
                        ha="center", va="bottom", color="#00ee66", fontweight="bold")
        else:
            ax.annotate("▼", xy=(x, p - offset), fontsize=8,
                        ha="center", va="top", color="#ff5555", fontweight="bold")

    # ── Sweep legs ────────────────────────────────────────────────────────────
    day_sweeps = [s for s in sweeps if day_start <= parse_ts(s["sweep_ts"]) <= day_end]

    for sw in day_sweeps:
        sweep_x  = ts_to_x(parse_ts(sw["sweep_ts"]))
        leg_start_x = (
            ts_to_x(parse_ts(sw["leg_start_ts"]))
            if sw.get("leg_start_ts")
            else max(0, sweep_x - 24)
        )
        level_price = sw["level_price"]
        direction   = sw["direction"]
        color = "#3399ff" if direction == "bullish" else "#ff7700"

        # Swept level: dashed line
        ax.axhline(level_price, color=color, linewidth=0.9, linestyle="--", alpha=0.7)
        ax.text(
            min(sweep_x + 1, n - 1), level_price,
            f" {sw['level_kind']}({sw['level_tier']})",
            fontsize=6.5, color=color, va="center",
        )

        # Leg zone: shaded area between leg_start and sweep
        left_x  = min(leg_start_x, sweep_x)
        right_x = max(leg_start_x, sweep_x)
        if right_x > left_x:
            ax.axvspan(left_x - 0.5, right_x + 0.5, alpha=0.10, color=color)

        # Leg extreme: gold × at actual price
        if sw.get("leg_extreme_ts") and sw.get("leg_extreme_price") is not None:
            ext_x = ts_to_x(parse_ts(sw["leg_extreme_ts"]))
            ax.annotate(
                "×", xy=(ext_x, sw["leg_extreme_price"]),
                fontsize=13, color="gold", ha="center", va="center", fontweight="bold",
            )

    # ── Title + legend ────────────────────────────────────────────────────────
    ax.set_title(
        f"{day_str}  |  {len(day_sweeps)} quality sweeps  |  {len(day_swings)} 5m swings",
        fontsize=10, pad=6,
    )
    handles = [
        mpatches.Patch(color="#00ee66", label="Swing high ▲ (5m)"),
        mpatches.Patch(color="#ff5555", label="Swing low ▼ (5m)"),
        mpatches.Patch(color="#3399ff", alpha=0.4, label="Bullish sweep leg"),
        mpatches.Patch(color="#ff7700", alpha=0.4, label="Bearish sweep leg"),
        mpatches.Patch(color="gold",    label="Leg extreme × (SL anchor)"),
    ]
    ax.legend(handles=handles, loc="upper left", fontsize=7.5)

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{day_str}_legs.png"
    fig.savefig(out_path, dpi=130, bbox_inches="tight", facecolor="#131722")
    plt.close(fig)
    return out_path


def upload_to_discord(path: Path, caption: str) -> str:
    import httpx
    resp = httpx.post(
        DISCORD_WEBHOOK_URL,
        data={"content": caption},
        files={"file": (path.name, path.read_bytes(), "image/png")},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["attachments"][0]["url"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json",   type=Path, default=LEGS_JSON)
    parser.add_argument("--from",   dest="date_from", default=None)
    parser.add_argument("--to",     dest="date_to",   default=None)
    parser.add_argument("--upload", action="store_true", help="Upload charts to Discord")
    args = parser.parse_args()

    data   = json.loads(args.json.read_text())
    sweeps = data["sweeps"]
    swings = data["swings"]
    print(f"Loaded {len(sweeps)} sweeps, {len(swings)} swings from {args.json}")

    df_1m = load_ohlcv(NQ_CSV)

    # Collect days that have quality sweeps
    days: set[str] = set()
    for sw in sweeps:
        day_et = parse_ts(sw["sweep_ts"]).astimezone(ET).date().isoformat()
        days.add(day_et)

    days = sorted(days)
    if args.date_from:
        days = [d for d in days if d >= args.date_from]
    if args.date_to:
        days = [d for d in days if d <= args.date_to]

    print(f"Generating charts for {len(days)} days...")
    generated: list[Path] = []
    for day in days:
        path = generate_day_chart(day, sweeps, swings, df_1m, OUT_DIR)
        if path:
            print(f"  OK {path.name}")
            generated.append(path)
        else:
            print(f"  --{day}: no chart data")

    if args.upload and DISCORD_WEBHOOK_URL and generated:
        print(f"\nUploading {len(generated)} charts to Discord...")
        for path in generated:
            try:
                url = upload_to_discord(path, f"Legs visualization: {path.stem}")
                print(f"  ^{url[:80]}...")
            except Exception as e:
                print(f"  ERR{path.name}: {e}")

    print(f"\nDone. {len(generated)} charts -> {OUT_DIR}")


if __name__ == "__main__":
    main()
