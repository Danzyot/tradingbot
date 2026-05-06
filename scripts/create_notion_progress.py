"""
Creates/updates a Notion progress dashboard page for the SMC Trading Bot.
Run: python create_notion_progress.py
"""
import sys
sys.path.insert(0, 'src')

import os
import httpx

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

TOKEN = os.environ.get("NOTION_TOKEN", "")
if not TOKEN:
    print("ERROR: NOTION_TOKEN env var not set")
    sys.exit(1)

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": NOTION_VERSION,
}


def _text(content: str, bold: bool = False, color: str = "default") -> dict:
    t = {"type": "text", "text": {"content": content}}
    if bold or color != "default":
        t["annotations"] = {}
        if bold:
            t["annotations"]["bold"] = True
        if color != "default":
            t["annotations"]["color"] = color
    return t


def _heading(text: str, level: int = 2) -> dict:
    kind = f"heading_{level}"
    return {
        "object": "block",
        "type": kind,
        kind: {"rich_text": [_text(text, bold=True)]},
    }


def _para(text: str, bold: bool = False, color: str = "default") -> dict:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [_text(text, bold=bold, color=color)]},
    }


def _bullet(text: str, bold: bool = False) -> dict:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": [_text(text, bold=bold)]},
    }


def _divider() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}


def _callout(text: str, emoji: str = "📌") -> dict:
    return {
        "object": "block",
        "type": "callout",
        "callout": {
            "rich_text": [_text(text)],
            "icon": {"type": "emoji", "emoji": emoji},
            "color": "blue_background",
        },
    }


def _table_row(cells: list[str]) -> dict:
    return {
        "type": "table_row",
        "table_row": {
            "cells": [[_text(c)] for c in cells]
        },
    }


def _table(header: list[str], rows: list[list[str]]) -> dict:
    return {
        "object": "block",
        "type": "table",
        "table": {
            "table_width": len(header),
            "has_column_header": True,
            "has_row_header": False,
            "children": [_table_row(header)] + [_table_row(r) for r in rows],
        },
    }


def build_page_blocks() -> list[dict]:
    blocks = []

    # Header callout
    blocks.append(_callout(
        "SMC Trading Bot — NQ/ES Futures (MNQ/MES micro) | Zero-AI runtime | "
        "Python | Backtesting phase | GitHub: github.com/Danzyot/tradingbot",
        "🤖"
    ))

    # --- WHAT WE'RE BUILDING ---
    blocks.append(_heading("What We're Building", 2))
    blocks.append(_para(
        "A fully mechanical, deterministic day trading bot for NQ/ES futures using ICT/SMC "
        "concepts. No AI at runtime — pure rule-based Python logic. Current phase: "
        "historical backtest and signal validation.",
        bold=False
    ))
    blocks.append(_bullet("Entry model: Liquidity sweep → manipulation leg FVG → IFVG inversion → market entry"))
    blocks.append(_bullet("Instruments: MNQ/MES (micro contracts), data from NQ/ES full contracts"))
    blocks.append(_bullet("Data: Databento 1m OHLCV, 2023-01-02 to 2026-04-08 (~1.1M bars)"))
    blocks.append(_bullet("Journal: SQLite + Notion + Discord screenshot upload"))

    blocks.append(_divider())

    # --- STEP STATUS ---
    blocks.append(_heading("Master Plan — Step Status", 2))
    blocks.append(_table(
        ["Step", "Description", "Status"],
        [
            ["1", "Fix Bug A: FVG mitigation race (tracker.mitigated)", "✅ Done"],
            ["2", "Fix Bug B: inverted ≠ mitigated (fvg.inverted flag)", "✅ Done"],
            ["3", "Fix Bug C: remove body dominance from sweep candle", "✅ Done"],
            ["4", "Fix Bug D: wick check uses sweep_candle consistently", "✅ Done"],
            ["5", "Fixed 1R TP; DOL as runner reference only", "✅ Done"],
            ["6", "BE at first liquidity level between entry and TP1", "✅ Done"],
            ["7", "IFVG speed gate (4-bar first-touch window)", "✅ Done"],
            ["8", "IFVG open-in-zone check + DOL tier sorting", "✅ Done"],
            ["E", "EQH/EQL transitive grouping (sort-then-chain)", "✅ Done"],
            ["F", "EQH/EQL tolerance 0.25pt → 1.0pt", "✅ Done"],
            ["G", "LTF FVG min-size filter", "❌ Reverted — blocked valid manipulation legs"],
            ["H", "IFVG age gate: TF-relative (tf × 8 min)", "✅ Done"],
            ["I", "Displacement window: 20 → 30 bars", "✅ Done"],
            ["9", "HTF alignment gate (daily bias / premium-discount)", "⚠️ Disabled — 4H momentum version was backwards"],
        ]
    ))

    blocks.append(_divider())

    # --- CURRENT ARCHITECTURE ---
    blocks.append(_heading("Architecture", 2))
    blocks.append(_table(
        ["Module", "File", "What it does"],
        [
            ["Candle data", "data/candle.py + aggregator.py", "1m bars → multi-TF aggregation (3m/5m/15m/30m/1H/4H)"],
            ["FVG detector", "detectors/fvg.py", "Detects + tracks Fair Value Gaps, mitigation, inversion flag"],
            ["IFVG detector", "detectors/ifvg.py", "TF-priority IFVG inversion (5m > 3m > 1m), speed + age gates"],
            ["Sweep detector", "detectors/sweep.py", "Liquidity level sweeps, S/A/B tier, ATR-adaptive quality gates"],
            ["Liquidity levels", "detectors/liquidity.py", "EQH/EQL, PDH/PDL, session H/L, NWOG/NDOG, HTF FVG edges"],
            ["Swing detector", "detectors/swing.py", "Pivot points (left=20, right=5 for 1m manipulation legs)"],
            ["SMT detector", "detectors/smt.py", "NQ vs ES divergence at swing points"],
            ["Confluence engine", "models/confluence.py", "Orchestrates all detectors, emits Signal objects"],
            ["Backtest engine", "engine/backtest.py", "Full historical replay, 1m candle-by-candle"],
            ["Journal", "journal/logger.py + database.py", "SQLite trade logging, TP/SL/BE simulation"],
            ["Screenshots", "generate_screenshots.py", "mplfinance charts → Discord CDN → Notion"],
        ]
    ))

    blocks.append(_divider())

    # --- SIGNAL STATS ---
    blocks.append(_heading("Signal Statistics (post all fixes, as of 2026-05-04)", 2))
    blocks.append(_table(
        ["Period", "Signals", "W/L/BE", "Win Rate", "Net R", "Notes"],
        [
            ["Jan 2023 (full)", "11", "3W/5L/3BE", "27%", "-2R", "Volatile recovery month"],
            ["Q1 2023 (full)", "~18-19", "~6W/4L/9BE", "~33%", "+3R (pre-fix)", "Needs re-run with H/I fixes"],
            ["Jun 2023 2-week", "1", "0W/1L/0BE", "0%", "-1R", "Strong AI bull trend — few reversals"],
            ["Jun sweep-only", "23", "—", "—", "—", "23 sweeps → 1 IFVG (IFVG chain = bottleneck)"],
        ]
    ))

    blocks.append(_divider())

    # --- CURRENT INVESTIGATION ---
    blocks.append(_heading("Current Investigation / Open Issues", 2))
    blocks.append(_callout(
        "Signal frequency too low: 0.1–0.5 signals/day vs target 1–5/day. "
        "Root cause: in strong-trend markets (Jun 2023 AI bull), manipulation-leg FVGs "
        "are too small to pass the 2pt strong-close gate. 23 sweeps detected but only 1 IFVG.",
        "🔍"
    ))
    blocks.append(_bullet("HTF gate disabled — 4H momentum version was BACKWARDS (ICT shorts at PREMIUM, not discount)"))
    blocks.append(_bullet("Next: implement daily-bias gate (daily candle direction + premium/discount position)"))
    blocks.append(_bullet("Consider: lower strong-close threshold from 2pt to 1pt for smaller TF FVGs"))
    blocks.append(_bullet("Consider: reference smartmoneyconcepts pip package for cross-checking detector logic"))

    blocks.append(_divider())

    # --- KEY RULES ---
    blocks.append(_heading("Key Rules (never change without user approval)", 2))
    blocks.append(_bullet("Sweep: wick penetrates level + body closes BACK on original side (same candle)"))
    blocks.append(_bullet("IFVG LONG: bearish FVG on leg → body closes ABOVE fvg.top + open ≤ fvg.top"))
    blocks.append(_bullet("IFVG SHORT: bullish FVG on leg → body closes BELOW fvg.bottom + open ≥ fvg.bottom"))
    blocks.append(_bullet("SL: leg_extreme_candle wick ± 2pt buffer"))
    blocks.append(_bullet("TP1: always fixed 1R. DOL level = runner label only"))
    blocks.append(_bullet("BE: triggered at first liquidity level between entry and TP1"))
    blocks.append(_bullet("TF priority: 5m > 4m > 3m > 2m > 1m (highest TF IFVG wins)"))
    blocks.append(_bullet("Killzones: Asia 19-21 ET, London 02-05 ET, NY AM 08:30-11 ET, NY PM 13:30-16 ET"))

    blocks.append(_divider())

    # --- PYTHON LIBRARIES ---
    blocks.append(_heading("Useful Python Libraries Found", 2))
    blocks.append(_table(
        ["Library", "GitHub / PyPI", "What it has"],
        [
            ["smartmoneyconcepts", "pip install smartmoneyconcepts\njoshyattridge/smart-money-concepts",
             "FVG, order blocks, liquidity, swing H/L, BoS/ChoCh — OHLCV dataframe input"],
            ["SMC-Algo-Trading", "vlex05/SMC-Algo-Trading", "Bot framework using SMC concepts"],
            ["swch-bot", "kulaizki/swch-bot", "Liquidity sweep + ChoCh analysis"],
            ["Freqtrade", "freqtrade/freqtrade", "Crypto-focused backtesting, adaptable to futures"],
        ]
    ))
    blocks.append(_para(
        "Note: Our custom detectors are more precise than these libraries "
        "(ICT-specific rules, ATR-adaptive gates, transitive EQL clustering, etc.). "
        "smartmoneyconcepts is useful for cross-checking FVG/swing logic."
    ))

    blocks.append(_divider())

    # --- NEXT STEPS ---
    blocks.append(_heading("Next Steps", 2))
    blocks.append(_callout(
        "Priority: investigate why IFVG chain converts only 4% of sweeps. "
        "23 sweeps → 1 signal in Jun 2023. Check: is 2pt strong-close gate too strict for "
        "small-leg markets? Try 1pt threshold and re-run.",
        "🎯"
    ))
    blocks.append(_bullet("1. Re-run Jun 2023 with lower strong-close threshold (1pt vs 2pt) — see if signal count improves"))
    blocks.append(_bullet("2. Generate screenshots of existing trades (cp C:/tmp/bt_jun23.db data/journal.db && python generate_screenshots.py)"))
    blocks.append(_bullet("3. Implement daily-bias HTF gate (Step 9 correct version): daily candle direction + premium/discount"))
    blocks.append(_bullet("4. Run Q1 2023 full backtest with all current fixes to get updated baseline"))
    blocks.append(_bullet("5. Consider referencing smartmoneyconcepts library for FVG/swing cross-check"))

    blocks.append(_divider())
    blocks.append(_para("Last updated: 2026-05-04 | GitHub: github.com/Danzyot/tradingbot | Model: claude-sonnet-4-6"))

    return blocks


def create_progress_page() -> str:
    """Create a standalone Notion page in the workspace."""
    # First, find the database's parent page so we can create a sibling page
    db_id = os.environ.get("NOTION_DATABASE_ID", "33d537bf-3f5e-813b-b106-df8097f2d315")

    # Get database info to find its parent
    resp = httpx.get(f"{NOTION_API}/databases/{db_id}", headers=HEADERS)
    if resp.status_code != 200:
        print(f"Cannot fetch database info: {resp.status_code} {resp.text[:200]}")
        # Fall back: create page as child of the database's workspace
        parent = {"type": "database_id", "database_id": db_id}
        title = [{"type": "text", "text": {"content": "SMC Bot Progress Dashboard"}}]
        payload = {
            "parent": parent,
            "icon": {"type": "emoji", "emoji": "🤖"},
            "properties": {
                "Name": {"title": title},
            },
            "children": build_page_blocks(),
        }
        create_resp = httpx.post(f"{NOTION_API}/pages", headers=HEADERS, json=payload, timeout=30)
        if create_resp.status_code in (200, 201):
            page = create_resp.json()
            url = page.get("url", "")
            print(f"Created page (as DB entry): {url}")
            return url
        print(f"Failed: {create_resp.status_code} {create_resp.text[:400]}")
        return ""

    db_info = resp.json()
    parent_info = db_info.get("parent", {})
    print(f"Database parent: {parent_info}")

    # Create a new page with the database's parent as parent
    if parent_info.get("type") == "page_id":
        parent = {"type": "page_id", "page_id": parent_info["page_id"]}
    elif parent_info.get("type") == "workspace":
        parent = {"type": "workspace", "workspace": True}
    else:
        # Fall back: create as DB row (less ideal but works)
        parent = {"type": "database_id", "database_id": db_id}

    title = [{"type": "text", "text": {"content": "🤖 SMC Bot — Progress Dashboard"}}]

    if parent.get("type") == "database_id":
        # Database row needs properties
        payload = {
            "parent": parent,
            "icon": {"type": "emoji", "emoji": "🤖"},
            "properties": {"Name": {"title": title}},
            "children": build_page_blocks(),
        }
    else:
        payload = {
            "parent": parent,
            "icon": {"type": "emoji", "emoji": "🤖"},
            "properties": {"title": {"title": title}},
            "children": build_page_blocks(),
        }

    create_resp = httpx.post(f"{NOTION_API}/pages", headers=HEADERS, json=payload, timeout=30)
    if create_resp.status_code in (200, 201):
        page = create_resp.json()
        url = page.get("url", "")
        print(f"\n✅ Progress page created: {url}\n")
        return url

    print(f"Failed to create page: {create_resp.status_code}")
    print(create_resp.text[:600])
    return ""


if __name__ == "__main__":
    create_progress_page()
