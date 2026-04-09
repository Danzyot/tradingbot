# SMC Trading Bot — Claude Context

This file is the source of truth for Claude Code. Read this at the start of every session.

---

## Project Goal

A fully automated, mechanical day trading bot for NQ/ES futures (MNQ/MES micro contracts).
- **Zero AI at runtime** — all logic is deterministic Python rules
- **No live executions yet** — current phase is historical backtest + journal mode
- Live executions come later after everything is validated
- OpenClaw AI handles orchestration/live loop alongside Claude Code

---

## Repository

- GitHub: https://github.com/Danzyot/tradingbot
- Local: `C:\Users\yotda\tradingbot\`
- Python: `python` (not `python3`) — Python 3.14.3 on Windows
- Run anything from repo root: `cd C:\Users\yotda\tradingbot`

---

## Architecture

```
src/smc_bot/
  data/
    candle.py         Candle dataclass (slots), CandleBuffer (deque ring buffer)
    aggregator.py     MultiTFAggregator — builds 3m/5m/15m/30m/1H/4H from 1m base
    history.py        CSV loader → list[Candle], load_csv() / load_pair()

  detectors/
    fvg.py            FVG detection + FVGTracker (mitigation via body close beyond far edge)
    ifvg.py           IFVG inversion detector, TF_PRIORITY = [5, 3, 1]
    sweep.py          LiquidityLevel, Sweep, SweepDetector — body must close back inside
    cisd.py           CISDDetector — body-based (not wick), checks most recent opposing candle
    smt.py            SMTDetector — NQ vs ES swing divergence; stores ts_a/ts_b for drawing
    swing.py          SwingDetector(left, right) — pivot detection with confirmation delay
    liquidity.py      detect_eqhl, detect_session_levels, detect_pdhl, detect_ndog/nwog

  filters/
    session.py        in_killzone(), active_session() — ET timezone, 4 sessions
    news.py           is_blocked() — fetches ForexFactory, blocks 30min pre / 15min post USD High

  models/
    base.py           Setup, Signal, TradeDirection, ModelType dataclasses
                      Signal now carries: entry_tf, confluence_desc, fvg_top/bottom/ts/kind,
                      sweep_wick, smt_ts_a/price_a/ts_b/price_b
    confluence.py     ConfluenceEngine — main orchestrator, call update() per 1m candle
                      Builds confluence_desc string, populates all drawing coords on Signal

  engine/
    backtest.py       run_backtest() — full historical replay pipeline
                      Params: date_from/date_to (YYYY-MM-DD), starting_balance, risk_pct

  journal/
    database.py       JournalDB — SQLite backend, trades + setups tables
    logger.py         TradeJournal — records signals, simulates TP/SL/BE outcomes
                      Tracks running account balance; risk_dollars = balance * risk_pct per trade
    reporter.py       print_summary() — prints stats + account balance/drawdown from DB
    notion_client.py  NotionJournal — posts trades to Notion database
    discord_client.py DiscordClient — uploads screenshots via webhook, returns CDN URL
    screenshot.py     Screenshot workflow helpers; chart_setup_params() returns all drawing data
    imgur_client.py   ImgurClient — kept for reference, Discord is preferred

data/
  nq_1m.csv           1,144,591 bars NQ 1m (2023-01-02 to 2026-04-08, from Databento)
  es_1m.csv           Same date range, ES 1m
  mnq_1m.csv          309 bars MNQ 1m (2026-04-08 only, original sample)
  mes_1m.csv          300 bars MES 1m (same)
  fetch_databento.py  Downloads NQ/ES 1m history from Databento (GLBX.MDP3, ohlcv-1m)
  save_data.py        Regenerates original 309-bar CSVs from embedded data
  journal.db          SQLite journal (auto-created, gitignored)
```

---

## Entry Model (CONFIRMED — do not change without user input)

### Mandatory sequence:
1. **Liquidity sweep**: wick penetrates level; candle BODY closes back on original side (NOT beyond level)
2. **FVG on manipulation leg**: forms before/during the sweep
3. **IFVG inversion**: a later candle body closes beyond the FVG far edge
   - LONG: bearish FVG → body closes ABOVE `fvg.top`
   - SHORT: bullish FVG → body closes BELOW `fvg.bottom`
4. **Entry**: market order at IFVG inversion candle close
5. **SL**: below sweep low (long) / above sweep high (short)

### IFVG timeframe priority: 5m > 3m > 1m (highest TF wins)

### Model 1 (primary): sweep → IFVG → entry
### Model 2 (ICT 2022, secondary): sweep → CISD → FVG retest at CE → entry
- Model 1 has priority; if it fires, Model 2 skips the same setup

---

## Liquidity Tiers

| Tier | Description |
|------|-------------|
| S    | Perfect EQH/EQL, 3+ candles apart |
| A    | EQH/EQL 1-3 candles apart; unmitigated HTF FVGs |
| B    | Session H/L, NWOG/NDOG, PDH/PDL, H/L inside FVG |
| C    | Order blocks (NOT YET IMPLEMENTED) |
| F    | Ignored traps |

Bot only sweeps S/A/B tiers.

Liquidity level kinds: `eqh`, `eql`, `pdh`, `pdl`, `session_high`, `session_low`,
`swing_high`, `swing_low`, `fvg_high`, `fvg_low`, `nwog_high`, `nwog_low`, `ndog_high`, `ndog_low`

---

## Sessions / Killzones (ET — auto-adjusts EST/EDT)

| Session | ET Time |
|---------|---------|
| Asia    | 19:00–21:00 |
| London  | 02:00–05:00 |
| NY AM   | 08:30–11:00 |
| NY PM   | 13:30–16:00 |

---

## Key Detector Rules

**CISD (Change In State of Delivery):**
- Bullish: `current.body_high > most_recent_bearish_candle.open`
- Bearish: `current.body_low < most_recent_bullish_candle.open`
- Body only, NOT wicks. Checks ONLY the most recent opposing candle.

**FVG mitigation:**
- Bullish FVG mitigated when: `body_low < fvg.bottom`
- Bearish FVG mitigated when: `body_high > fvg.top`

**SMT:**
- Bullish: NQ makes lower low, ES doesn't → trade ES (stronger)
- Bearish: NQ makes higher high, ES doesn't → trade ES (weaker)
- SMTSignal stores ts_a/ts_b (swing timestamps) for orange line drawing on screenshots

**Sweep:**
- Bullish: `c.low < level.price AND c.body_low >= level.price`
- Bearish: `c.high > level.price AND c.body_high <= level.price`

---

## Backtest Configuration

```python
run_backtest(
    mnq_csv=Path("data/nq_1m.csv"),    # full NQ for backtesting
    mes_csv=Path("data/es_1m.csv"),    # full ES for SMT
    setup_expiry_min=60,
    min_rr=1.0,
    max_concurrent_trades=1,
    be_trigger_r=1.0,
    starting_balance=50_000.0,         # simulated $50k account
    risk_pct=0.005,                    # 0.5% risk per trade = $250 at start
    date_from="2023-01-02",            # YYYY-MM-DD filter — change per validation week
    date_to="2023-01-08",
)
```

Run command: `python run_backtest.py` from repo root.

**Validation workflow:**
- Test 1 week at a time (date_from / date_to)
- Sync to Notion: `python setup_notion.py`
- Claude captures screenshots for each trade (TradingView MCP)
- Manually review each trade in Notion
- Expand date range once model confirmed correct

---

## Account Simulation

- Starting balance: $50,000
- Risk per trade: 0.5% of current balance (dynamic — recalculates each trade)
- Stored per trade: `risk_dollars`, `balance_before`, `pnl_dollars`
- Reporter shows: final balance, net P&L $, max drawdown %, balance per trade

---

## Trade Journal (SQLite + Notion + Discord)

### SQLite — `data/journal.db`
Tables: `trades`, `setups`

Key trade columns:
- Core: id, ts, symbol, direction, model, session, entry_price, stop_loss, tp1, tp2, rr_ratio, score
- Outcomes: outcome, exit_price, exit_ts, pnl_r, pnl_dollars, be_moved
- Confluences: smt_bonus, cisd_bonus, sweep_tier, sweep_direction
- Entry context: entry_tf, confluence_desc
- Account: risk_dollars, balance_before
- Drawing coords: fvg_top, fvg_bottom, fvg_ts, fvg_kind, sweep_wick, smt_ts_a, smt_price_a, smt_ts_b, smt_price_b
- Sync: notion_page_id, notes (stores discord:URL)

### Screenshot Workflow (Discord → Notion)

Flow per trade:
1. Python: `get_pending_screenshots(db_path)` → list of trades needing screenshots
2. Python: `chart_setup_params(trade)` → all drawing params (timeframe, range, coords)
3. Claude: `chart_set_timeframe(entry_tf)` + `chart_set_visible_range(range_from, range_to)`
4. Claude draws on chart:
   - **IFVG zone**: gray rectangle from fvg_ts to entry_ts, between fvg_bottom and fvg_top
   - **FVG zone** (if level was FVG type): green (bullish) or red (bearish) rectangle — TODO: store HTF FVG level zone coords
   - **Sweep $**: text shape at sweep_wick price with "$" label
   - **SMT line**: orange trend_line from (smt_ts_a, smt_price_a) to (smt_ts_b, smt_price_b) — only if smt_bonus
   - **Entry**: green horizontal_line
   - **SL**: red horizontal_line
   - **TP1**: blue horizontal_line
5. Claude: `capture_screenshot(filename, region="chart")`
6. Python: `process_screenshot(trade, path, db_path, discord_webhook_url, notion_token)`
   → uploads to Discord CDN → marks DB → adds image block to Notion page

### Screenshot workflow (actual — replaces TradingView MCP approach)
Run `python generate_screenshots.py` — generates candlestick charts from nq_1m.csv data (mplfinance),
uploads to Discord, embeds in Notion. Reads DISCORD_WEBHOOK_URL from Windows user env.
Shows: entry/SL/TP1 lines, IFVG gray zone, $ sweep marker, SMT orange line, trade title.

Known TradingView MCP issues:
- `draw_clear` fails with "getChartApi is not defined" — remove drawings manually with `draw_remove_one`
- `chart_scroll_to_date` fails with "evaluate is not defined"
- `chart_set_visible_range` ignores timestamps — stays at current time
- `scrollTimeTo` (JS) does not navigate to historical dates 3+ years back
- TradingView Desktop cannot navigate to Jan 2023 via any MCP method — use generate_screenshots.py instead

### Credentials (set as env vars)
```
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/1491711154085429358/...
NOTION_TOKEN=ntn_...  (your Notion integration token — get from notion.so/my-integrations)
NOTION_DATABASE_ID=33d537bf-3f5e-813b-b106-df8097f2d315
DATABENTO_API_KEY=db-...  (regenerate — was exposed in chat)
```

`setup_notion.py` has hardcoded token + DB ID as fallback.

### Notion Database Properties
Name, Date, Symbol, Direction, Model, Session, Entry, Stop Loss, TP1, TP2, R:R, Score,
SMT (checkbox), CISD (checkbox), BE Moved (checkbox), Sweep Tier, Sweep Direction,
Outcome (Win/Loss/BE/Open), PnL R, Exit Price, Entry TF, Confluences,
Year, Month, Week, Notes

Notion database ID: `33d537bf-3f5e-813b-b106-df8097f2d315`

---

## Historical Data

Source: **Databento** (GLBX.MDP3, ohlcv-1m schema)
- `data/nq_1m.csv` — NQ continuous (NQ.c.0), 2023-01-02 to 2026-04-08, 1,144,591 bars
- `data/es_1m.csv` — ES continuous (ES.c.0), same range
- Download script: `python data/fetch_databento.py`
- NQ/ES = full contracts for backtesting; MNQ/MES = micro contracts for live demo/live trading

---

## TradingView MCP

- CDP port: 9222
- Launch: `Start-Process 'C:\Program Files\WindowsApps\TradingView.Desktop_3.0.0.7652_x64__n534cwy3xpjzj\TradingView.exe' -ArgumentList '--remote-debugging-port=9222'`
- NQ symbol: `CME_MINI:NQM2026` (or current front month)
- MNQ symbol: `CME_MINI:MNQM2026`
- MES symbol: `CME_MINI:MESM2026`
- Indicators loaded: BoS/ChoCh (Nephew_Sam_), FVG/iFVG (Nephew_Sam_), Equal Highs and Lows, NWOG/NDOG+Event Horizon, ICT Killzones & Pivots [TFO]
- Read indicator output via: `data_get_pine_boxes`, `data_get_pine_lines`, `data_get_pine_labels`

---

## Current State — Where We Left Off (last updated 2026-04-10)

### What was built this session:
- **SL fixed**: now uses sweep candle wick (candle.low - 2.0 for longs, candle.high + 2.0 for shorts), not just level price - 2.0
- **120-min cooldown** on re-sweeping the same price level (`_swept_levels` dict in ConfluenceEngine)
- **EQH/EQL tightened**: 0.05% tolerance, 3+ touches = S-tier, 2 touches + candle gap ≥5 = A-tier, else skip
- **HTF FVG liquidity levels**: 15m, 30m, 1H, 4H unmitigated FVG edges as sweep targets; LTF excluded
- **FVG size filter** (`MIN_FVG_SIZE` in backtest.py): 15m≥5pt, 30m≥8pt, 1H≥10pt, 4H≥15pt — rejects small gaps
- **FVG recency cap**: only 3 most recent unmitigated FVGs per TF used as liquidity levels (`MAX_FVG_LEVELS_PER_TF=3`)
- **TF-aware FVG tiers**: 1H/4H = A-tier, 15m/30m = B-tier; kind now includes TF e.g. "60m_fvg_high"
- **Hard DOL requirement**: tp1 fallback to 2R removed — if no real opposing major level exists, signal is rejected
- **DOL target finder** (`_find_dol_targets`): TP1 = nearest opposing liquidity level ≥15pts away, NO fallback
- **Detailed confluence descriptions**: `_build_confluence_desc()` with TF-specific FVG labels
- **`generate_screenshots.py`**: generates mplfinance charts from nq_1m.csv, uploads to Discord, embeds in Notion
- **`setup_notion_structure.py`**: builds Year > Month > Week navigation hierarchy in Notion parent page

### Signal count status (post-fix):
- **Before fixes**: 56+ signals/week
- **After FVG size filter + recency cap + hard DOL**: 14 signals
- **After Pine-aligned FVG (displacement candle check) + expiry**: **11 signals for Jan 2023 week 1** ✓ target met (5–25)

### All changes committed to GitHub:
1. SL: sweep candle wick + 2pts buffer
2. 120-min cooldown on re-sweeping same level
3. EQH/EQL: tighter (3+ touches = S, 2 touches + gap≥5 bars = A)
4. HTF FVG liquidity levels: 15m/30m/1H/4H only (LTF excluded)
5. FVG size filter: 15m≥5pt, 30m≥8pt, 1H≥10pt, 4H≥15pt
6. FVG recency cap: max 3 most recent unmitigated FVGs per TF
7. Hard DOL requirement: no R-multiple fallback — needs real opposing level
8. TF-aware tiers: 1H/4H = A-tier, 15m/30m = B-tier
9. Manipulation leg: `_find_leg_start()` uses prior opposing swing as leg_start_ts
10. IFVG leg FVG: `_collect_leg_fvgs()` only includes FVGs from leg_start_ts to sweep.ts
11. FVG displacement candle check: `c1.close > c0.high` (Pine-aligned, from CoWork findings)
12. FVG expiry: 30-bar window for LTF (1m-5m), no expiry for HTF (15m+) — Pine i_invWindow=15

### Notion structure:
- Parent page: `33d537bf-3f5e-8049-b1ea-dacdcbd74ac5`
- Hierarchy: Year > Month > Week pages with summary callout + bulleted trade mentions
- Duplicate year/month pages were cleaned up manually (one empty 2023 + January 2023 deleted)
- Current trades: Jan 2023, week 1 — user confirmed most trades are wrong (detection subpar)

### User's verdict on current trades:
- Most week-1 trades do NOT follow the rules correctly
- Detection works but is subpar — needs alignment with actual TradingView indicator logic
- User wants to review popular TradingView Pine indicators for SMT and HTF FVG to align rules exactly
- User may share indicator links or trade example explanations

### Next steps (in priority order):
1. Re-run `generate_screenshots.py` and `setup_notion_structure.py` to refresh Notion with 11 new trades
2. User reviews Jan 2023 week 1 trades in Notion — confirm detection is correct
3. Apply remaining Pine Script alignment fixes from CoWork/Gemini findings:
   - IFVG inversion: verify `body_high > fvg.top` vs Pine's `close > fvg.top`
   - EQH/EQL tolerance: likely needs fixed-point (e.g. 2pts) not percentage
   - SMT: add temporal proximity check (NQ/ES swings must be within N bars)
   - CISD: should reference confirmed swing point, not most recent bearish candle
   - Swing params: verify left=5, right=2 matches Pine's ta.pivothigh()
4. Expand to more weeks of 2023 once week 1 is confirmed correct

### Multi-agent setup:
- Claude 1 (this): main coding session, auto-pushes to GitHub on every commit
- Claude 2: second subscription, picks up from GitHub + CLAUDE.md
- Claude CoWork: reads Pine Script via TradingView MCP, produces fix tables
- Gemini: token-heavy non-coding tasks — Pine Script research, long doc analysis, indicator comparisons

### Gemini use cases (to save Claude tokens):
- Reading and summarizing long Pine Script source files
- Comparing multiple indicator implementations side-by-side
- ICT/SMC concept research from forums/docs
- NOT for: coding, file edits, commits, backtest runs

---

## Known Issues / TODO

1. **IFVG inversion trigger**: `body_high > fvg.top` may fire too early — Pine may use `close > fvg.top`. Needs confirmation from CoWork/Gemini Pine reading.
2. **EQH/EQL tolerance**: 0.05% (~10pts at NQ 20k) likely too wide — Pine probably uses fixed 1-3pts. Fix: change to absolute point tolerance.
3. **SMT temporal proximity**: no check that NQ/ES diverging swings occurred within N bars — could compare swings hours apart.
4. **CISD reference**: uses most recent opposing candle, not confirmed swing point. Pine's ChoCH uses structural swing.
5. **Swing params**: left=5, right=2 not yet verified against Pine's ta.pivothigh() params.
6. **IFVG FVG must be on leg**: confirmed implemented via `_find_leg_start()` + `_collect_leg_fvgs()`. Monitor for edge cases.
7. **HTF FVG drawing coords**: need to store zone coords when level.kind is *_fvg_high/*_fvg_low for screenshots.
8. **Live data loop**: not built yet. Future phase.
9. **Live executions**: future phase, after everything validated.
10. **C-tier OBs**: order blocks not yet implemented.
11. **TradingView MCP**: can't navigate to Jan 2023 — use generate_screenshots.py (mplfinance) instead.

---

## Architecture Decisions

- **No pandas** in hot path — raw dataclasses for speed
- **SQLite** for journal — portable, no server, easy to inspect
- **Notion** for human-readable journal — grouped by Year/Month/Week for navigation
- **Discord** for screenshot hosting — webhook upload, permanent CDN URLs embedded in Notion
- **One trade at a time** — `max_concurrent_trades=1` to keep risk simple
- **BE at 1R** — configurable via `be_trigger_r`
- **0.5% risk per trade** on $50k simulated account
- **Validate 1 week at a time** before expanding date range
- **TradingView MCP** for data capture and visual validation (not for live execution API)
- **OpenClaw** will handle the live orchestration loop when that phase begins

---

## OpenClaw Note

OpenClaw AI works alongside Claude Code. If `cannot find module` errors appear after restart:
- Fix: `cd C:\Users\yotda\AppData\Roaming\npm\node_modules\openclaw\ && npm install --no-save <package>`
- Root cause: jiti hoisting bug — openclaw's deps must be installed inside its own directory, not globally
