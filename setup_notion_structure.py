"""
1. Remove duplicate image blocks from each trade Notion page (keep newest only).
2. Build navigation hierarchy inside the SMC Trade Journal parent page:
   Parent Page
   └── SMC Trade Journal (database — already exists)
   └── 2023
       └── January
           └── Week 1 (Jan 2–8)  ← summary + links to all trade pages
"""
import sqlite3, httpx, time
from pathlib import Path

import os
TOKEN        = os.environ.get("NOTION_TOKEN")
if not TOKEN:
    raise RuntimeError("Set the NOTION_TOKEN environment variable before running this script")
DB_ID        = "33d537bf-3f5e-813b-b106-df8097f2d315"
PARENT_PAGE  = "33d537bf-3f5e-8049-b1ea-dacdcbd74ac5"   # page that contains the DB
DB_PATH      = Path("data/journal.db")

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}


def notion_get(path: str) -> dict:
    r = httpx.get(f"https://api.notion.com/v1/{path}", headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()


def notion_post(path: str, body: dict) -> dict:
    r = httpx.post(f"https://api.notion.com/v1/{path}", headers=HEADERS, json=body, timeout=15)
    r.raise_for_status()
    return r.json()


def notion_patch(path: str, body: dict) -> dict:
    r = httpx.patch(f"https://api.notion.com/v1/{path}", headers=HEADERS, json=body, timeout=15)
    r.raise_for_status()
    return r.json()


def notion_delete(block_id: str) -> None:
    httpx.delete(f"https://api.notion.com/v1/blocks/{block_id}",
                 headers=HEADERS, timeout=15).raise_for_status()


def load_trades() -> list[dict]:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT id, ts, symbol, direction, model, session,
               entry_price, stop_loss, tp1, rr_ratio, score,
               outcome, exit_price, pnl_r, pnl_dollars,
               sweep_tier, sweep_direction, confluence_desc,
               smt_bonus, cisd_bonus, be_moved,
               notion_page_id, notes
        FROM trades
        ORDER BY ts
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Step 1: Remove duplicate image blocks ─────────────────────────────────────

def clean_duplicate_images(trades: list[dict]) -> None:
    print("\n=== Cleaning duplicate images ===")
    for t in trades:
        pid = t.get("notion_page_id")
        if not pid:
            continue
        try:
            data = notion_get(f"blocks/{pid}/children")
            image_blocks = [b for b in data.get("results", []) if b["type"] == "image"]
            # If more than one image, delete all but the last (newest)
            to_delete = image_blocks[:-1]
            for b in to_delete:
                notion_delete(b["id"])
                print(f"  Deleted old image from trade {t['id']}")
                time.sleep(0.3)
        except Exception as e:
            print(f"  Error on {t['id']}: {e}")


# ── Step 2: Create navigation pages ──────────────────────────────────────────

def create_page(parent_id: str, title: str, emoji: str = "📁") -> str:
    """Create a sub-page inside parent_id. Returns new page ID."""
    body = {
        "parent": {"type": "page_id", "page_id": parent_id},
        "icon": {"type": "emoji", "emoji": emoji},
        "properties": {
            "title": {"title": [{"type": "text", "text": {"content": title}}]}
        },
        "children": [],
    }
    result = notion_post("pages", body)
    return result["id"]


def add_blocks(page_id: str, blocks: list[dict]) -> None:
    notion_patch(f"blocks/{page_id}/children", {"children": blocks})


def rich_text(text: str, bold: bool = False, color: str = "default") -> dict:
    return {
        "type": "text",
        "text": {"content": text},
        "annotations": {"bold": bold, "color": color},
    }


def page_mention(page_id: str, text: str) -> dict:
    return {
        "type": "mention",
        "mention": {"type": "page", "page": {"id": page_id}},
        "plain_text": text,
    }


def outcome_color(outcome: str) -> str:
    return {"win": "green", "loss": "red", "be": "gray", "open": "default"}.get(outcome, "default")


def build_week_page(page_id: str, week_trades: list[dict]) -> None:
    """Populate a Week page with summary stats + one row per trade."""
    wins  = sum(1 for t in week_trades if t["outcome"] == "win")
    losses = sum(1 for t in week_trades if t["outcome"] == "loss")
    bes   = sum(1 for t in week_trades if t["outcome"] == "be")
    total_r    = sum(t.get("pnl_r") or 0 for t in week_trades)
    total_usd  = sum(t.get("pnl_dollars") or 0 for t in week_trades)
    wr = wins / len(week_trades) * 100 if week_trades else 0

    # Summary callout
    summary_text = (
        f"{len(week_trades)} trades  |  {wins}W / {losses}L / {bes}BE  |  "
        f"WR {wr:.0f}%  |  {total_r:+.2f}R  |  ${total_usd:+,.2f}"
    )

    blocks = [
        {
            "object": "block", "type": "callout",
            "callout": {
                "rich_text": [rich_text(summary_text, bold=True)],
                "icon": {"type": "emoji", "emoji": "📊"},
                "color": "blue_background",
            },
        },
        {"object": "block", "type": "divider", "divider": {}},
    ]

    # One bullet per trade linking to its Notion page
    for t in week_trades:
        pid = t.get("notion_page_id")
        if not pid:
            continue
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(t["ts"]).replace(tzinfo=timezone.utc)
        from zoneinfo import ZoneInfo
        dt_et = dt.astimezone(ZoneInfo("America/New_York"))
        ts = dt_et.strftime("%Y-%m-%d %H:%M ET")

        outcome = t.get("outcome", "?")
        pnl_r = t.get("pnl_r", 0) or 0
        direction = t.get("direction", "").upper()
        confluences = t.get("confluence_desc") or ""

        label = f"{ts} | {direction} | {outcome.upper()} {pnl_r:+.2f}R | {confluences}"

        blocks.append({
            "object": "block", "type": "bulleted_list_item",
            "bulleted_list_item": {
                "rich_text": [
                    page_mention(pid, label),
                ],
                "color": outcome_color(outcome),
            },
        })

    # Push in batches of 100 (Notion limit)
    for i in range(0, len(blocks), 100):
        add_blocks(page_id, blocks[i:i+100])
        time.sleep(0.5)


def build_navigation(trades: list[dict]) -> None:
    print("\n=== Building navigation structure ===")

    # Group trades by (year, month_label, week_label)
    from collections import defaultdict
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")

    grouped: dict[str, dict[str, dict[str, list]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )
    for t in trades:
        if not t.get("notion_page_id"):
            continue
        dt = datetime.fromisoformat(t["ts"]).replace(tzinfo=timezone.utc).astimezone(ET)
        year  = str(dt.year)
        month = dt.strftime("%B")       # "January"
        week  = f"Week {dt.isocalendar().week}"
        # Date range label for week
        grouped[year][month][week].append(t)

    # Get date range for each week
    def week_date_range(week_trades: list[dict]) -> str:
        from datetime import datetime, timezone
        dts = [
            datetime.fromisoformat(t["ts"]).replace(tzinfo=timezone.utc).astimezone(ET)
            for t in week_trades
        ]
        if not dts:
            return ""
        return f"{min(dts).strftime('%b %#d')}-{max(dts).strftime('%#d, %Y')}"

    for year, months in sorted(grouped.items()):
        print(f"\n  Creating year page: {year}")
        year_page = create_page(PARENT_PAGE, year, "📅")
        time.sleep(0.4)

        for month, weeks in sorted(months.items(),
                key=lambda x: datetime.strptime(x[0], "%B").month):
            month_label = f"{month} {year}"
            print(f"    Creating month page: {month_label}")
            month_page = create_page(year_page, month_label, "🗓️")
            time.sleep(0.4)

            for week_key, week_trades in sorted(weeks.items(),
                    key=lambda x: int(x[0].split()[-1])):
                date_range = week_date_range(week_trades)
                wins  = sum(1 for t in week_trades if t.get("outcome") == "win")
                losses = sum(1 for t in week_trades if t.get("outcome") == "loss")
                week_label = f"{week_key} ({date_range})  •  {wins}W/{losses}L"
                print(f"      Creating week page: {week_label} ({len(week_trades)} trades)")
                week_page = create_page(month_page, week_label, "📈")
                time.sleep(0.4)

                build_week_page(week_page, week_trades)
                time.sleep(0.5)

    print("\nNavigation structure created.")


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    trades = load_trades()
    print(f"Loaded {len(trades)} trades from DB")

    clean_duplicate_images(trades)
    build_navigation(trades)

    print("\nAll done.")
