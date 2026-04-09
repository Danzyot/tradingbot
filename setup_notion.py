import sys, os
sys.path.insert(0, 'src')

from pathlib import Path
from smc_bot.journal.notion_client import NotionJournal, sync_to_notion

NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID", "33d537bf-3f5e-813b-b106-df8097f2d315")

if not NOTION_TOKEN:
    raise RuntimeError("Set the NOTION_TOKEN environment variable before running this script")

n = NotionJournal(token=NOTION_TOKEN, database_id=NOTION_DATABASE_ID)

# Sync all unsynced trades from the journal DB to Notion
db_path = Path('data/journal.db')
if db_path.exists():
    synced = sync_to_notion(db_path, n)
    print(f"Synced {synced} trades to Notion")
else:
    print("No journal.db found — run the backtest first, then re-run this script")
