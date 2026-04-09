"""
Trade screenshot workflow.

This module is executed interactively by Claude using TradingView MCP tools.
Python side: reads trades needing screenshots, uploads to Discord, updates DB + Notion.
MCP side (Claude): scrolls chart, draws levels, captures screenshot, clears drawings.

Full flow per trade:
  1. Claude calls chart_scroll_to_date(trade_ts)
  2. Claude calls chart_set_timeframe("5")
  3. Claude calls draw_shape x3 (entry/SL/TP1 horizontal lines)
  4. Claude calls capture_screenshot(filename=trade_id, region="chart")
  5. Claude calls draw_clear()
  6. Python: upload PNG to Discord → get CDN URL
  7. Python: update DB with discord_url
  8. Python: update Notion page with image block
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

SCREENSHOTS_DIR = Path(__file__).parent.parent.parent.parent / "data" / "screenshots"


# ── DB helpers ────────────────────────────────────────────────────────────────

def get_pending_screenshots(db_path: Path) -> list[dict]:
    """Return closed trades that don't have a screenshot (imgur_url) yet."""
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT id, ts, symbol, direction, model, session,
               entry_price, stop_loss, tp1, tp2,
               outcome, exit_price, pnl_r,
               sweep_tier, sweep_direction, sweep_ts, sweep_price,
               smt_bonus, cisd_bonus, be_moved,
               entry_tf, confluence_desc,
               fvg_top, fvg_bottom, fvg_ts, fvg_kind,
               sweep_wick, smt_ts_a, smt_price_a, smt_ts_b, smt_price_b,
               notion_page_id, notes
        FROM trades
        WHERE outcome IS NOT NULL
          AND (notes IS NULL OR (notes NOT LIKE '%imgur:%' AND notes NOT LIKE '%discord:%'))
        ORDER BY ts
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_screenshot_uploaded(db_path: Path, trade_id: str, url: str, prefix: str = "discord") -> None:
    """Store the screenshot URL in the trade's notes field."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        UPDATE trades
        SET notes = COALESCE(notes || ' | ', '') || ?
        WHERE id = ?
    """, (f"{prefix}:{url}", trade_id))
    conn.commit()
    conn.close()


# ── Chart setup params ────────────────────────────────────────────────────────

def chart_setup_params(trade: dict) -> dict:
    """
    Returns all params Claude needs to set up the TradingView chart for this trade.
    """
    ts_str = trade["ts"]
    try:
        dt = datetime.fromisoformat(ts_str)
    except ValueError:
        dt = datetime.strptime(ts_str[:19], "%Y-%m-%dT%H:%M:%S")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    unix_ts = int(dt.timestamp())

    entry_tf = trade.get("entry_tf") or 5  # minutes per candle
    # Show ~40 candles on each side of the entry
    half_window = 40 * entry_tf * 60  # seconds

    # FVG zone unix timestamps for rectangle drawing
    fvg_ts_unix = None
    if trade.get("fvg_ts"):
        try:
            fvg_dt = datetime.fromisoformat(trade["fvg_ts"][:19])
            if fvg_dt.tzinfo is None:
                fvg_dt = fvg_dt.replace(tzinfo=timezone.utc)
            fvg_ts_unix = int(fvg_dt.timestamp())
        except Exception:
            pass

    sweep_ts_unix = None
    if trade.get("sweep_ts"):
        try:
            sweep_dt = datetime.fromisoformat(trade["sweep_ts"][:19])
            if sweep_dt.tzinfo is None:
                sweep_dt = sweep_dt.replace(tzinfo=timezone.utc)
            sweep_ts_unix = int(sweep_dt.timestamp())
        except Exception:
            pass

    return {
        "trade_id": trade["id"],
        "entry_ts": unix_ts,
        "range_from": unix_ts - half_window,
        "range_to": unix_ts + half_window,
        "entry_tf": entry_tf,
        "timeframe": str(entry_tf),
        "symbol": trade["symbol"],
        "entry": trade["entry_price"],
        "sl": trade["stop_loss"],
        "tp1": trade["tp1"],
        "exit_price": trade.get("exit_price"),
        "outcome": trade.get("outcome"),
        "filename": screenshot_filename(trade),
        "notion_page_id": trade.get("notion_page_id"),
        "confluence_desc": trade.get("confluence_desc") or "",
        "smt_bonus": bool(trade.get("smt_bonus")),
        # FVG zone
        "fvg_top": trade.get("fvg_top"),
        "fvg_bottom": trade.get("fvg_bottom"),
        "fvg_ts": fvg_ts_unix,
        # Sweep
        "sweep_ts": sweep_ts_unix,
        "sweep_price": trade.get("sweep_price"),
    }


def screenshot_filename(trade: dict) -> str:
    ts = trade["ts"][:16].replace("T", "_").replace(":", "")
    return f"{ts}_{trade['symbol']}_{trade['direction']}_{trade['id']}"


def print_trade_summary(trade: dict) -> None:
    print(f"\n{'='*50}")
    print(f"Trade {trade['id']} | {trade['ts'][:16]}")
    print(f"  {trade['direction'].upper()} {trade['symbol']} | {trade['model']}")
    print(f"  Entry: {trade['entry_price']}  SL: {trade['stop_loss']}  TP1: {trade['tp1']}")
    print(f"  Outcome: {trade['outcome']}  PnL: {trade.get('pnl_r', '?')}R")
    flags = []
    if trade.get("smt_bonus"):  flags.append("SMT")
    if trade.get("cisd_bonus"): flags.append("CISD")
    if trade.get("be_moved"):   flags.append("BE")
    if flags: print(f"  Bonus confluences: {', '.join(flags)}")
    print(f"  Sweep: {trade['sweep_tier']} tier {trade['sweep_direction']}")


# ── Full screenshot + upload + Notion update ──────────────────────────────────

def process_screenshot(
    trade: dict,
    screenshot_path: Path,
    db_path: Path,
    discord_webhook_url: Optional[str] = None,
    notion_token: Optional[str] = None,
    notion_database_id: Optional[str] = None,
) -> Optional[str]:
    """
    After Claude has saved the screenshot file:
    1. Upload to Discord webhook → get CDN URL
    2. Mark in DB
    3. Add image block to Notion page (if page exists)

    Returns the Discord CDN URL, or None on failure.
    """
    from .discord_client import DiscordClient
    direction = trade.get("direction", "").upper()
    symbol = trade.get("symbol", "")
    outcome = (trade.get("outcome") or "open").upper()
    pnl = trade.get("pnl_r")
    pnl_str = f"{pnl:+.2f}R" if pnl is not None else ""
    caption = f"{trade['ts'][:16]} | {direction} {symbol} | {outcome} {pnl_str}"

    discord = DiscordClient(webhook_url=discord_webhook_url)

    try:
        url = discord.upload_file(screenshot_path, caption=caption)
        print(f"  Uploaded: {url}")
    except Exception as e:
        print(f"  Discord upload failed: {e}")
        return None

    mark_screenshot_uploaded(db_path, trade["id"], url, prefix="discord")

    # Add image block to Notion page
    notion_page_id = trade.get("notion_page_id")
    if notion_page_id and notion_token:
        try:
            _add_image_to_notion_page(notion_page_id, url, trade, notion_token)
            print(f"  Image added to Notion page {notion_page_id}")
        except Exception as e:
            print(f"  Notion image block failed: {e}")

    return url


def _add_image_to_notion_page(page_id: str, image_url: str, trade: dict, token: str) -> None:
    """Append an image block + caption to an existing Notion page."""
    import httpx

    direction = trade.get("direction", "").upper()
    symbol = trade.get("symbol", "")
    outcome = (trade.get("outcome") or "open").upper()
    pnl = trade.get("pnl_r")
    pnl_str = f"{pnl:+.2f}R" if pnl is not None else ""
    caption = f"{trade['ts'][:16]} | {direction} {symbol} | {outcome} {pnl_str}"

    blocks = [
        {
            "object": "block",
            "type": "image",
            "image": {
                "type": "external",
                "external": {"url": image_url},
                "caption": [{"type": "text", "text": {"content": caption}}],
            },
        }
    ]

    httpx.patch(
        f"https://api.notion.com/v1/blocks/{page_id}/children",
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        },
        json={"children": blocks},
        timeout=15,
    ).raise_for_status()
