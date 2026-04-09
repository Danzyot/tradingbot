"""
Notion trade journal integration.

Posts each closed trade as a page in a Notion database.
Each trade gets its own row with all confluences, entry/exit details, and outcome.

Setup:
  1. Go to https://www.notion.so/my-integrations → New integration → copy the token
  2. Create a Notion database (see create_database() or create one manually)
  3. Share the database with your integration (click Share → Invite → select integration)
  4. Set env vars:
       NOTION_TOKEN=secret_xxx
       NOTION_DATABASE_ID=your-database-id (from the database URL)
  5. Or pass them directly to NotionJournal()

Database properties (auto-created by create_database()):
  Name            title   Trade ID + symbol + direction
  Date            date    Entry timestamp
  Symbol          select  MNQ / MES
  Direction       select  Long / Short
  Model           select  IFVG / ICT2022
  Session         select  london / ny_am / ny_pm / asia
  Entry           number
  Stop Loss       number
  TP1             number
  TP2             number
  R:R             number
  Score           number  (2 base + bonuses)
  SMT             checkbox
  CISD            checkbox
  BE Moved        checkbox
  Sweep Tier      select  S / A / B
  Sweep Direction select  bullish / bearish
  Outcome         select  Win / Loss / BE / Open
  PnL R           number  P&L in R-multiples
  Exit Price      number
  Notes           rich_text
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

import httpx


NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


class NotionJournal:
    def __init__(
        self,
        token: Optional[str] = None,
        database_id: Optional[str] = None,
    ):
        self.token = token or os.environ.get("NOTION_TOKEN", "")
        self.database_id = database_id or os.environ.get("NOTION_DATABASE_ID", "")
        if not self.token:
            raise ValueError("NOTION_TOKEN not set. Pass token= or set env var.")
        # database_id is optional at construction — only required for post_trade/update
        self._headers = {
            "Authorization": f"Bearer {self.token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }

    # ── Public API ────────────────────────────────────────────────────────────

    def post_trade(self, trade: dict) -> str:
        """
        Create a new page in the Notion database for this trade.
        `trade` is a sqlite3.Row or dict with all trade columns.
        Returns the Notion page ID.
        """
        props = self._build_properties(trade)

        # If an Imgur URL is already in notes, embed as image block on the page
        children = []
        imgur_url = _extract_screenshot_url(trade.get("notes", "") or "")
        if imgur_url:
            children.append({
                "object": "block",
                "type": "image",
                "image": {
                    "type": "external",
                    "external": {"url": imgur_url},
                },
            })

        body = {
            "parent": {"database_id": self.database_id},
            "properties": props,
        }
        if children:
            body["children"] = children

        resp = httpx.post(
            f"{NOTION_API}/pages",
            headers=self._headers,
            json=body,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()["id"]

    def update_trade_outcome(self, page_id: str, trade: dict) -> None:
        """Update outcome fields on an existing Notion page."""
        props = self._outcome_properties(trade)
        httpx.patch(
            f"{NOTION_API}/pages/{page_id}",
            headers=self._headers,
            json={"properties": props},
            timeout=15,
        ).raise_for_status()

    def patch_database_properties(self, properties: dict) -> None:
        """Add new properties to an existing Notion database (non-destructive)."""
        httpx.patch(
            f"{NOTION_API}/databases/{self.database_id}",
            headers=self._headers,
            json={"properties": properties},
            timeout=15,
        ).raise_for_status()

    def create_database(self, parent_page_id: str, title: str = "SMC Trade Journal") -> str:
        """
        Programmatically create the trade journal database inside a Notion page.
        Returns the new database ID.

        Args:
            parent_page_id: The Notion page ID to create the database under.
                            Get it from the page URL: notion.so/Page-Title-<ID>
        """
        body = {
            "parent": {"type": "page_id", "page_id": parent_page_id},
            "title": [{"type": "text", "text": {"content": title}}],
            "properties": self._database_schema(),
        }
        resp = httpx.post(
            f"{NOTION_API}/databases",
            headers=self._headers,
            json=body,
            timeout=15,
        )
        resp.raise_for_status()
        db_id = resp.json()["id"]
        print(f"Database created! ID: {db_id}")
        print(f"Set NOTION_DATABASE_ID={db_id}")
        return db_id

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _build_properties(self, t: dict) -> dict:
        """Build all Notion page properties from a trade dict."""
        direction = (t["direction"] or "").capitalize()
        symbol = (t["symbol"] or "NQ").upper()
        name = f"{t['ts'][:16]} {symbol} {direction}"

        # Date grouping fields derived from timestamp
        try:
            ts_dt = datetime.fromisoformat(t["ts"][:19])
        except Exception:
            ts_dt = datetime.utcnow()
        year_str  = str(ts_dt.year)
        month_str = ts_dt.strftime("%Y-%m %b")        # e.g. "2026-01 Jan"
        week_str  = f"{ts_dt.year}-W{ts_dt.isocalendar()[1]:02d}"  # e.g. "2026-W14"

        props = {
            "Name": _title(name),
            "Date": _date(t["ts"]),
            "Symbol": _select(symbol),
            "Direction": _select(direction),
            "Model": _select((t["model"] or "").upper()),
            "Session": _select(t.get("session") or ""),
            "Entry": _number(t["entry_price"]),
            "Stop Loss": _number(t["stop_loss"]),
            "TP1": _number(t["tp1"]),
            "TP2": _number(t.get("tp2")),
            "R:R": _number(t["rr_ratio"]),
            "Score": _number(t["score"]),
            "SMT": _checkbox(bool(t.get("smt_bonus"))),
            "CISD": _checkbox(bool(t.get("cisd_bonus"))),
            "BE Moved": _checkbox(bool(t.get("be_moved"))),
            "Sweep Tier": _select((t.get("sweep_tier") or "").upper()),
            "Sweep Direction": _select((t.get("sweep_direction") or "").capitalize()),
            "Outcome": _select(_outcome_label(t.get("outcome"))),
            "Entry TF": _select(f"{t.get('entry_tf', 1)}m" if t.get("entry_tf") else ""),
            "Year":     _select(year_str),
            "Month":    _select(month_str),
            "Week":     _select(week_str),
        }

        if t.get("confluence_desc"):
            props["Confluences"] = _rich_text(str(t["confluence_desc"]))

        # Outcome fields (may be None if trade is still open)
        if t.get("pnl_r") is not None:
            props["PnL R"] = _number(t["pnl_r"])
        if t.get("exit_price") is not None:
            props["Exit Price"] = _number(t["exit_price"])
        if t.get("notes"):
            props["Notes"] = _rich_text(str(t["notes"]))

        return props

    def _outcome_properties(self, t: dict) -> dict:
        props = {
            "Outcome": _select(_outcome_label(t.get("outcome"))),
            "BE Moved": _checkbox(bool(t.get("be_moved"))),
        }
        if t.get("pnl_r") is not None:
            props["PnL R"] = _number(t["pnl_r"])
        if t.get("exit_price") is not None:
            props["Exit Price"] = _number(t["exit_price"])
        return props

    def _database_schema(self) -> dict:
        return {
            "Name":            {"title": {}},
            "Date":            {"date": {}},
            "Symbol":          {"select": {"options": [{"name": "MNQ"}, {"name": "MES"}]}},
            "Direction":       {"select": {"options": [{"name": "Long"}, {"name": "Short"}]}},
            "Model":           {"select": {"options": [{"name": "IFVG"}, {"name": "ICT2022"}]}},
            "Session":         {"select": {"options": [
                {"name": "london"}, {"name": "ny_am"}, {"name": "ny_pm"}, {"name": "asia"}
            ]}},
            "Entry":           {"number": {"format": "number"}},
            "Stop Loss":       {"number": {"format": "number"}},
            "TP1":             {"number": {"format": "number"}},
            "TP2":             {"number": {"format": "number"}},
            "R:R":             {"number": {"format": "number"}},
            "Score":           {"number": {"format": "number"}},
            "SMT":             {"checkbox": {}},
            "CISD":            {"checkbox": {}},
            "BE Moved":        {"checkbox": {}},
            "Sweep Tier":      {"select": {"options": [
                {"name": "S"}, {"name": "A"}, {"name": "B"}
            ]}},
            "Sweep Direction": {"select": {"options": [
                {"name": "Bullish"}, {"name": "Bearish"}
            ]}},
            "Outcome":         {"select": {"options": [
                {"name": "Win", "color": "green"},
                {"name": "Loss", "color": "red"},
                {"name": "BE", "color": "yellow"},
                {"name": "Open", "color": "blue"},
            ]}},
            "PnL R":           {"number": {"format": "number"}},
            "Exit Price":      {"number": {"format": "number"}},
            "Entry TF":        {"select": {"options": [
                {"name": "1m"}, {"name": "3m"}, {"name": "5m"}
            ]}},
            "Confluences":     {"rich_text": {}},
            "Year":            {"select": {}},
            "Month":           {"select": {}},
            "Week":            {"select": {}},
            "Notes":           {"rich_text": {}},
        }


# ── Sync function ─────────────────────────────────────────────────────────────

def sync_to_notion(db_path, notion: NotionJournal) -> int:
    """
    Push all unsynced closed trades from SQLite to Notion.
    Returns number of trades synced.
    """
    from .database import JournalDB
    jdb = JournalDB(db_path)
    unsynced = jdb.unsynced_trades()
    count = 0
    for trade in unsynced:
        trade_dict = dict(trade)
        try:
            page_id = notion.post_trade(trade_dict)
            jdb.set_notion_page_id(trade_dict["id"], page_id)
            count += 1
        except Exception as e:
            print(f"  Failed to sync trade {trade_dict['id']}: {e}")
    return count


# ── Property builders ─────────────────────────────────────────────────────────

def _title(text: str) -> dict:
    return {"title": [{"text": {"content": str(text)}}]}

def _date(ts_str: str) -> dict:
    # Notion expects ISO 8601; strip microseconds if present
    return {"date": {"start": ts_str[:19]}}

def _select(name: str) -> dict:
    return {"select": {"name": str(name)}} if name else {"select": None}

def _number(val) -> dict:
    return {"number": float(val) if val is not None else None}

def _checkbox(val: bool) -> dict:
    return {"checkbox": bool(val)}

def _rich_text(text: str) -> dict:
    return {"rich_text": [{"text": {"content": str(text)}}]}

def _outcome_label(outcome: Optional[str]) -> str:
    mapping = {"win": "Win", "loss": "Loss", "be": "BE", None: "Open"}
    return mapping.get(outcome, "Open")

def _extract_screenshot_url(notes: str) -> Optional[str]:
    """Extract screenshot URL (discord: or imgur: prefix) from notes field."""
    for part in notes.split("|"):
        part = part.strip()
        for prefix in ("discord:", "imgur:"):
            if part.startswith(prefix):
                return part[len(prefix):].strip()
    return None
