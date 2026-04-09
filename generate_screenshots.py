"""
Generate trade screenshots from nq_1m.csv data using mplfinance.
Each screenshot shows:
  - Candlestick chart centered on the trade (80 candles on each side at entry_tf)
  - IFVG zone: gray rectangle from fvg_ts to entry_ts
  - Sweep wick marker: $ text at sweep_wick price
  - Entry: green dashed horizontal line
  - SL: red dashed horizontal line
  - TP1: blue dashed horizontal line
  - Title: trade details + outcome

Then uploads to Discord and links in Notion.
"""
import sys, os
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, "src")

import sqlite3
import pandas as pd
import mplfinance as mpf
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")  # set NOTION_TOKEN in your environment
DB_PATH = Path("data/journal.db")
NQ_CSV = Path("data/nq_1m.csv")
SCREENSHOTS_DIR = Path("data/screenshots")
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

CANDLES_EACH_SIDE = 35   # bars to show on each side of entry — tight view on the setup


def load_trades() -> list[dict]:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT id, ts, symbol, direction, model, session,
               entry_price, stop_loss, tp1, tp2,
               outcome, exit_price, pnl_r, pnl_dollars,
               sweep_tier, sweep_direction, sweep_ts, sweep_price,
               smt_bonus, cisd_bonus, be_moved,
               entry_tf, confluence_desc,
               fvg_top, fvg_bottom, fvg_ts, fvg_kind,
               sweep_wick, smt_ts_a, smt_price_a, smt_ts_b, smt_price_b,
               notion_page_id, notes
        FROM trades
        WHERE outcome IS NOT NULL
          AND (notes IS NULL OR (notes NOT LIKE '%discord:%'))
        ORDER BY ts
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_done(trade_id: str, url: str) -> None:
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(
        "UPDATE trades SET notes = COALESCE(notes || ' | ', '') || ? WHERE id = ?",
        (f"discord:{url}", trade_id),
    )
    conn.commit()
    conn.close()


def add_to_notion(page_id: str, image_url: str, trade: dict) -> None:
    import httpx
    direction = trade.get("direction", "").upper()
    symbol = trade.get("symbol", "")
    outcome = (trade.get("outcome") or "open").upper()
    pnl = trade.get("pnl_r")
    pnl_str = f"{pnl:+.2f}R" if pnl is not None else ""
    caption = f"{trade['ts'][:16]} | {direction} {symbol} | {outcome} {pnl_str}"

    blocks = [{
        "object": "block", "type": "image",
        "image": {
            "type": "external", "external": {"url": image_url},
            "caption": [{"type": "text", "text": {"content": caption}}],
        },
    }]
    httpx.patch(
        f"https://api.notion.com/v1/blocks/{page_id}/children",
        headers={"Authorization": f"Bearer {NOTION_TOKEN}", "Notion-Version": "2022-06-28",
                 "Content-Type": "application/json"},
        json={"children": blocks}, timeout=15,
    ).raise_for_status()


def upload_to_discord(path: Path, caption: str) -> str:
    import httpx
    image_bytes = path.read_bytes()
    resp = httpx.post(
        DISCORD_WEBHOOK_URL,
        data={"content": caption},
        files={"file": (path.name, image_bytes, "image/png")},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["attachments"][0]["url"]


def parse_ts(ts_str: str) -> datetime:
    if not ts_str:
        return None
    try:
        dt = datetime.fromisoformat(ts_str)
    except ValueError:
        dt = datetime.strptime(ts_str[:19], "%Y-%m-%dT%H:%M:%S")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def generate_chart(trade: dict, df_1m: pd.DataFrame) -> Path:
    """Generate a candlestick screenshot for one trade. Returns path to PNG."""
    entry_tf = int(trade.get("entry_tf") or 5)
    entry_dt = parse_ts(trade["ts"])
    fvg_dt = parse_ts(trade.get("fvg_ts"))
    sweep_dt = parse_ts(trade.get("sweep_ts"))

    # Resample 1m data to entry_tf, convert index to ET for display
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
    df = df_1m.copy()
    df.index = df.index.tz_convert(ET)
    df_tf = df.resample(f"{entry_tf}min", label="left", closed="left").agg({
        "Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"
    }).dropna()

    # Convert entry/fvg/sweep timestamps to ET for index lookups
    entry_dt_et = entry_dt.astimezone(ET)
    fvg_dt = fvg_dt.astimezone(ET) if fvg_dt else None
    sweep_dt = sweep_dt.astimezone(ET) if sweep_dt else None

    # Find the entry bar
    entry_bar = df_tf.index.asof(entry_dt_et)
    if entry_bar is pd.NaT:
        # Fallback: nearest bar
        idx = df_tf.index.searchsorted(entry_dt_et)
        entry_bar = df_tf.index[max(0, min(idx, len(df_tf) - 1))]

    entry_pos = df_tf.index.get_loc(entry_bar)

    # Always include the sweep candle in view (go back further if needed)
    left_bars = CANDLES_EACH_SIDE
    if sweep_dt:
        sweep_bar = df_tf.index.asof(sweep_dt)
        if sweep_bar is not pd.NaT:
            sweep_pos = df_tf.index.get_loc(sweep_bar)
            left_bars = max(CANDLES_EACH_SIDE, entry_pos - sweep_pos + 10)

    start_pos = max(0, entry_pos - left_bars)
    end_pos = min(len(df_tf), entry_pos + 20)   # show 20 bars after entry for outcome
    df_window = df_tf.iloc[start_pos:end_pos]

    if df_window.empty:
        print(f"  No data for trade {trade['id']} at {entry_dt}")
        return None

    # ── Plot ──────────────────────────────────────────────────────────────────
    fig, axes = mpf.plot(
        df_window,
        type="candle",
        style="nightclouds",
        returnfig=True,
        figsize=(14, 7),
        ylabel="Price",
        tight_layout=True,
    )
    ax = axes[0]

    entry = trade["entry_price"]
    sl = trade["stop_loss"]
    tp1 = trade["tp1"]
    direction = trade["direction"]
    outcome = trade.get("outcome", "open")
    pnl_r = trade.get("pnl_r", 0) or 0

    # Horizontal lines: entry (green), SL (red), TP1 (blue)
    ax.axhline(entry, color="#00cc44", linewidth=1.5, linestyle="--", label=f"Entry {entry:.2f}")
    ax.axhline(sl,    color="#ff4444", linewidth=1.5, linestyle="--", label=f"SL {sl:.2f}")
    ax.axhline(tp1,   color="#4488ff", linewidth=1.5, linestyle="--", label=f"TP1 {tp1:.2f}")

    # IFVG zone: gray rectangle between fvg_ts and entry_ts
    fvg_top = trade.get("fvg_top")
    fvg_bottom = trade.get("fvg_bottom")
    if fvg_top and fvg_bottom and fvg_dt:
        fvg_ts_idx = df_window.index.searchsorted(fvg_dt)
        entry_ts_idx = df_window.index.searchsorted(entry_dt_et)
        if fvg_ts_idx < len(df_window) and entry_ts_idx <= len(df_window):
            x_start = max(0, fvg_ts_idx - 0.5)
            x_end = min(len(df_window) - 1, entry_ts_idx + 0.5)
            ax.axhspan(fvg_bottom, fvg_top, alpha=0.25, color="gray",
                       xmin=x_start / len(df_window), xmax=x_end / len(df_window))
            ax.text(x_start + (x_end - x_start) / 2, (fvg_top + fvg_bottom) / 2,
                    "IFVG", ha="center", va="center", fontsize=7, color="white", alpha=0.8)

    # Sweep wick marker
    sweep_wick = trade.get("sweep_wick")
    if sweep_wick and sweep_dt:
        sw_idx = df_window.index.searchsorted(sweep_dt)
        if sw_idx < len(df_window):
            ax.annotate("$", xy=(sw_idx, sweep_wick),
                        fontsize=11, color="gold", fontweight="bold",
                        ha="center", va="center")

    # SMT line (orange)
    smt_ts_a = parse_ts(trade.get("smt_ts_a"))
    smt_ts_b = parse_ts(trade.get("smt_ts_b"))
    if smt_ts_a: smt_ts_a = smt_ts_a.astimezone(ET)
    if smt_ts_b: smt_ts_b = smt_ts_b.astimezone(ET)
    smt_pa = trade.get("smt_price_a")
    smt_pb = trade.get("smt_price_b")
    if smt_ts_a and smt_ts_b and smt_pa and smt_pb:
        idx_a = df_window.index.searchsorted(smt_ts_a)
        idx_b = df_window.index.searchsorted(smt_ts_b)
        if idx_a < len(df_window) and idx_b < len(df_window):
            ax.plot([idx_a, idx_b], [smt_pa, smt_pb], color="orange",
                    linewidth=2, label="SMT")

    # Title
    ts_et = entry_dt.astimezone(__import__("zoneinfo").ZoneInfo("America/New_York"))
    outcome_str = f"{outcome.upper()} {pnl_r:+.2f}R"
    color_map = {"win": "#00cc44", "loss": "#ff4444", "be": "#aaaaaa", "open": "#888888"}
    confluences = trade.get("confluence_desc") or ""
    title = (
        f"{ts_et.strftime('%Y-%m-%d %H:%M ET')} | "
        f"{direction.upper()} {trade.get('symbol', 'NQ')} | "
        f"{outcome_str}  |  {confluences}"
    )
    ax.set_title(title, fontsize=9, color=color_map.get(outcome, "white"), pad=6)

    # Legend
    handles = [
        mpatches.Patch(color="#00cc44", label=f"Entry {entry:.2f}"),
        mpatches.Patch(color="#ff4444", label=f"SL {sl:.2f}"),
        mpatches.Patch(color="#4488ff", label=f"TP1 {tp1:.2f}"),
    ]
    if fvg_top:
        handles.append(mpatches.Patch(color="gray", alpha=0.5, label="IFVG"))
    ax.legend(handles=handles, loc="upper left", fontsize=8)

    # Save
    ts_str = trade["ts"][:16].replace("T", "_").replace(":", "")
    filename = f"{ts_str}_{trade.get('symbol','NQ')}_{direction}_{trade['id']}.png"
    out_path = SCREENSHOTS_DIR / filename
    fig.savefig(out_path, dpi=120, bbox_inches="tight", facecolor="#131722")
    plt.close(fig)
    return out_path


def main():
    print("Loading NQ 1m data...")
    df_1m = pd.read_csv(NQ_CSV, parse_dates=["ts"], index_col="ts")
    df_1m.index = pd.DatetimeIndex(df_1m.index).tz_localize("UTC") if df_1m.index.tzinfo is None else df_1m.index
    df_1m.columns = [c.capitalize() for c in df_1m.columns]
    # Ensure we have OHLCV columns
    required = {"Open", "High", "Low", "Close"}
    if not required.issubset(set(df_1m.columns)):
        # Try lowercase
        df_1m.columns = [c.title() for c in df_1m.columns]
    if "Volume" not in df_1m.columns:
        df_1m["Volume"] = 0

    trades = load_trades()
    print(f"{len(trades)} trades need screenshots")

    for i, trade in enumerate(trades, 1):
        print(f"\n[{i}/{len(trades)}] {trade['id']} {trade['ts'][:16]} {trade['direction'].upper()} {trade.get('outcome','?')}")
        try:
            path = generate_chart(trade, df_1m)
            if not path:
                continue

            if not DISCORD_WEBHOOK_URL:
                print(f"  Saved: {path} (no Discord webhook — skipping upload)")
                continue

            direction = trade.get("direction", "").upper()
            symbol = trade.get("symbol", "")
            outcome = (trade.get("outcome") or "open").upper()
            pnl = trade.get("pnl_r")
            pnl_str = f"{pnl:+.2f}R" if pnl is not None else ""
            caption = f"{trade['ts'][:16]} | {direction} {symbol} | {outcome} {pnl_str} | {trade.get('confluence_desc','')}"

            url = upload_to_discord(path, caption)
            print(f"  Uploaded: {url[:80]}...")
            mark_done(trade["id"], url)

            notion_page_id = trade.get("notion_page_id")
            if notion_page_id and NOTION_TOKEN:
                add_to_notion(notion_page_id, url, trade)
                print(f"  Added to Notion page")

        except Exception as e:
            print(f"  ERROR: {e}")
            import traceback; traceback.print_exc()

    print(f"\nDone. Screenshots saved to {SCREENSHOTS_DIR}")


if __name__ == "__main__":
    main()
