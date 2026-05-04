"""
Generate per-sweep screenshots showing:
  - 5m candlestick chart (60 bars, centered on sweep)
  - Manipulation leg: all candles in the leg highlighted with a colored background zone
  - Swing highs ▲ / swing lows ▼ as triangle markers
  - Swept liquidity level: dashed horizontal line with label
  - Leg extreme: bold horizontal line (where SL would anchor)
  - NO entry / SL / TP / IFVG markers — pure structure

Reads data/legs_scan.json produced by run_legs_scan.py.
Uploads to Discord webhook if DISCORD_WEBHOOK_URL is set.

Usage:
    python generate_leg_screenshots.py
    python generate_leg_screenshots.py --from 2023-01-02 --to 2023-01-07
"""
import sys, json, os, argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import mplfinance as mpf
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.lines as mlines

sys.path.insert(0, "src")

NQ_CSV    = Path("data/nq_1m.csv")
LEGS_JSON = Path("data/legs_scan.json")
OUT_DIR   = Path("data/screenshots/legs_per_sweep")
ET        = ZoneInfo("America/New_York")

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
BARS_BEFORE = 40   # 5m bars before sweep to show
BARS_AFTER  = 20   # 5m bars after sweep to show


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


def generate_sweep_chart(
    sw: dict,
    swings: list[dict],
    df_1m: pd.DataFrame,
    out_dir: Path,
) -> "Path | None":
    sweep_ts   = parse_ts(sw["sweep_ts"])
    direction  = sw["direction"]
    level_p    = sw["level_price"]
    level_kind = sw["level_kind"]
    level_tier = sw["level_tier"]

    leg_start_ts = parse_ts(sw["leg_start_ts"]) if sw.get("leg_start_ts") else sweep_ts - timedelta(minutes=60)
    leg_ext_ts   = parse_ts(sw["leg_extreme_ts"]) if sw.get("leg_extreme_ts") else None
    leg_ext_p    = sw.get("leg_extreme_price")

    # Window: from leg_start - 10 min to sweep + 30 min
    window_start = (leg_start_ts - timedelta(minutes=10)).astimezone(timezone.utc)
    window_end   = (sweep_ts     + timedelta(minutes=30)).astimezone(timezone.utc)

    df_win = df_1m.loc[window_start:window_end]
    if df_win.empty or len(df_win) < 5:
        return None

    # Resample to 3m
    df_3m = df_win.resample("3min", label="left", closed="left").agg({
        "Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"
    }).dropna()
    if len(df_3m) < 5:
        return None

    df_3m.index = df_3m.index.tz_convert(ET)
    n = len(df_3m)

    def ts_to_x(ts: datetime) -> int:
        ts_et = ts.astimezone(ET)
        idx = df_3m.index.searchsorted(ts_et)
        return int(min(idx, n - 1))

    fig, axes = mpf.plot(
        df_3m,
        type="candle",
        style="nightclouds",
        returnfig=True,
        figsize=(14, 6),
        ylabel="Price",
        tight_layout=True,
    )
    ax = axes[0]

    color = "#2288ff" if direction == "bullish" else "#ff6600"

    # ── Manipulation leg: shaded background zone ──────────────────────────────
    leg_x0 = ts_to_x(leg_start_ts)
    leg_x1 = ts_to_x(sweep_ts)
    if leg_x1 > leg_x0:
        ax.axvspan(leg_x0 - 0.5, leg_x1 + 0.5, alpha=0.22, color=color, zorder=1)

    # ── Swept level: dashed horizontal line ───────────────────────────────────
    ax.axhline(level_p, color=color, linewidth=1.2, linestyle="--", alpha=0.85, zorder=2)
    ax.text(
        min(leg_x1 + 1, n - 1), level_p,
        f"  {level_kind} ({level_tier}) @ {level_p:.2f}",
        fontsize=7.5, color=color, va="center", zorder=3,
    )

    # ── Leg extreme: bold horizontal line at the wick tip ─────────────────────
    if leg_ext_p is not None:
        ext_color = "#ffcc00"
        ax.axhline(leg_ext_p, color=ext_color, linewidth=1.5, linestyle="-.", alpha=0.9, zorder=2)
        ax.text(
            max(0, leg_x0 - 1), leg_ext_p,
            f" leg extreme {leg_ext_p:.2f}  ",
            fontsize=7, color=ext_color, va="center", ha="right", zorder=3,
        )
        if leg_ext_ts:
            ext_x = ts_to_x(leg_ext_ts)
            ax.annotate(
                "X", xy=(ext_x, leg_ext_p),
                fontsize=11, color=ext_color, ha="center", va="center",
                fontweight="bold", zorder=4,
            )

    # ── Swing markers from the same day ───────────────────────────────────────
    day_start = sweep_ts.astimezone(timezone.utc).replace(hour=0, minute=0, second=0)
    day_end   = day_start + timedelta(days=1)
    day_swings = [s for s in swings if day_start <= parse_ts(s["ts"]) <= day_end]

    price_range = df_3m["High"].max() - df_3m["Low"].min()
    offset = max(price_range * 0.005, 4.0)

    for s in day_swings:
        x = ts_to_x(parse_ts(s["ts"]))
        if x < 0 or x >= n:
            continue
        p = s["price"]
        if s["kind"] == "high":
            ax.annotate("▲", xy=(x, p + offset), fontsize=9,
                        ha="center", va="bottom", color="#00ee66", fontweight="bold", zorder=4)
        else:
            ax.annotate("▼", xy=(x, p - offset), fontsize=9,
                        ha="center", va="top", color="#ff5555", fontweight="bold", zorder=4)

    # ── Sweep candle marker ───────────────────────────────────────────────────
    sweep_x = ts_to_x(sweep_ts)
    ax.axvline(sweep_x, color=color, linewidth=1.5, alpha=0.6, linestyle=":", zorder=3)
    ax.text(sweep_x, ax.get_ylim()[1], "SWEEP", rotation=90,
            fontsize=7, color=color, ha="right", va="top", alpha=0.9, zorder=4)

    # ── Title + legend ────────────────────────────────────────────────────────
    sweep_et = sweep_ts.astimezone(ET)
    dir_label = "BULLISH" if direction == "bullish" else "BEARISH"
    ax.set_title(
        f"{sweep_et.strftime('%Y-%m-%d %H:%M ET')}  |  {dir_label} sweep of {level_kind} ({level_tier})",
        fontsize=10, pad=6,
    )

    handles = [
        mpatches.Patch(color=color,     alpha=0.4, label="Manipulation leg"),
        mlines.Line2D([], [], color=color, linestyle="--", label=f"Swept level @ {level_p:.2f}"),
        mlines.Line2D([], [], color="#ffcc00", linestyle="-.", label=f"Leg extreme @ {leg_ext_p:.2f}" if leg_ext_p else "Leg extreme"),
        mpatches.Patch(color="#00ee66", label="Swing high ▲"),
        mpatches.Patch(color="#ff5555", label="Swing low ▼"),
    ]
    ax.legend(handles=handles, loc="upper left", fontsize=7.5)

    # ── Save ──────────────────────────────────────────────────────────────────
    out_dir.mkdir(parents=True, exist_ok=True)
    ts_str = sweep_ts.strftime("%Y%m%d_%H%M")
    fname  = f"{ts_str}_{direction[:4]}_{level_kind}_{level_tier}.png"
    out_path = out_dir / fname
    fig.savefig(out_path, dpi=120, bbox_inches="tight", facecolor="#131722")
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
    parser.add_argument("--no-upload", action="store_true", help="Skip Discord upload")
    args = parser.parse_args()

    data   = json.loads(args.json.read_text())
    sweeps = data["sweeps"]
    swings = data["swings"]
    print(f"Loaded {len(sweeps)} sweeps, {len(swings)} swings")

    if args.date_from:
        sweeps = [s for s in sweeps if s["sweep_ts"][:10] >= args.date_from]
    if args.date_to:
        sweeps = [s for s in sweeps if s["sweep_ts"][:10] <= args.date_to]
    print(f"Generating charts for {len(sweeps)} sweeps...")

    df_1m = load_ohlcv(NQ_CSV)
    upload = bool(DISCORD_WEBHOOK_URL) and not args.no_upload

    for i, sw in enumerate(sweeps, 1):
        sweep_et = parse_ts(sw["sweep_ts"]).astimezone(ET)
        label = f"{sweep_et.strftime('%m-%d %H:%M')} {sw['direction'].upper()} {sw['level_kind']}({sw['level_tier']})"
        path = generate_sweep_chart(sw, swings, df_1m, OUT_DIR)
        if not path:
            print(f"  [{i}/{len(sweeps)}] {label} -- no data, skipped")
            continue

        if upload:
            try:
                url = upload_to_discord(path, f"[{i}/{len(sweeps)}] {label}")
                print(f"  [{i}/{len(sweeps)}] {label}  -> {url[:70]}...")
            except Exception as e:
                print(f"  [{i}/{len(sweeps)}] {label}  ERR: {e}")
        else:
            print(f"  [{i}/{len(sweeps)}] {label}  saved: {path.name}")

    print(f"\nDone. {len(sweeps)} charts -> {OUT_DIR}")


if __name__ == "__main__":
    main()
