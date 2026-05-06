# SMC Trading Bot

A fully mechanical, rule-based day trading bot for NQ/ES futures (MNQ/MES micro contracts) built on ICT/Smart Money Concepts (SMC). Zero AI at runtime — all logic is deterministic Python.

Current phase: **historical backtest and signal validation**. Live execution is a future phase.

## What It Does

Detects and backtests a specific ICT entry model on 1-minute futures data:

1. **Liquidity sweep** — a candle wick penetrates a key level (EQH/EQL, PDH/PDL, session H/L, etc.) and the body closes back on the original side
2. **FVG on the manipulation leg** — a Fair Value Gap forms in the candles leading to the sweep
3. **IFVG inversion** — a later candle body closes through the FVG far edge (5m > 3m > 1m priority)
4. **Entry** at the IFVG inversion candle close; SL at the leg extreme wick; TP1 at 1R

## Project Structure

```
src/smc_bot/          Core bot logic (detectors, engine, journal, models)
config/settings.yaml  Risk and session parameters
data/                 CSV price data (gitignored — download via data/fetch_databento.py)
scripts/              Utility scripts (Notion sync, chart generation, legs scan)
run_backtest.py       Main backtest entry point
```

## Running the Backtest

```bash
# Install dependencies
pip install -e .

# Download historical data (requires Databento API key)
pip install databento
DATABENTO_API_KEY=db-xxxx python data/fetch_databento.py

# Run backtest (edit date_from/date_to in run_backtest.py first)
python run_backtest.py
```

## Configuration

Edit `run_backtest.py` to set the date range and parameters:

```python
run_backtest(
    mnq_csv=Path("data/nq_1m.csv"),   # NQ 1m data for backtesting
    mes_csv=Path("data/es_1m.csv"),   # ES 1m data for SMT divergence
    date_from="2023-01-02",           # start of validation window
    date_to="2023-01-08",             # end of validation window (keep short)
    starting_balance=50_000.0,        # simulated account size
    risk_pct=0.005,                   # 0.5% risk per trade
    min_rr=1.0,                       # minimum reward:risk to take a trade
    db_path=Path("C:/tmp/bt_jan23.db"),
    clear_db=True,
)
```

Risk and session parameters are documented in `config/settings.yaml`.

## Environment Variables

```
DATABENTO_API_KEY     Databento API key (for data download)
DISCORD_WEBHOOK_URL   Discord webhook for screenshot uploads
NOTION_TOKEN          Notion integration token (for trade journal)
NOTION_DATABASE_ID    Notion database ID (default: 33d537bf-3f5e-813b-b106-df8097f2d315)
```

## Utility Scripts

All run from the repo root:

```bash
python scripts/setup_notion.py              # sync journal DB trades to Notion
python scripts/setup_notion_structure.py   # build Year/Month/Week nav in Notion
python scripts/generate_screenshots.py     # generate + upload trade charts to Discord
python scripts/generate_leg_screenshots.py # per-sweep manipulation leg charts
python scripts/run_legs_scan.py            # scan sweeps → data/legs_scan.json
python scripts/visualize_legs.py           # per-day leg visualization charts
python scripts/create_notion_progress.py   # create/update Notion progress dashboard
```

## Data

Historical data comes from [Databento](https://databento.com) (GLBX.MDP3, ohlcv-1m schema):
- `data/nq_1m.csv` — NQ continuous front month, 2023-01-02 to 2026-04-08
- `data/es_1m.csv` — ES continuous front month, same range

CSV files are gitignored (63–66 MB each). Download via `data/fetch_databento.py`.

## GitHub

https://github.com/Danzyot/tradingbot
