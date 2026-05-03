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

## Current State — Where We Left Off (last updated 2026-04-13)

### What was built across sessions (cumulative):
- **SL fixed**: `leg_extreme_candle` (actual manipulation wick extreme, 90-min capped) → `low - 2.0` for longs, `high + 2.0` for shorts. Separate from `sweep_candle` (close-back detection candle) which is only used for quality gate checks.
- **RR-aware DOL target**: `_find_dol_targets` skips levels too close to satisfy `min_rr` given the real SL distance — no more 0.4R trades
- **5-min sweep cooldown** (changed from 120 min)
- **EQH/EQL tightened**: 0.25pt tolerance, S-tier (3+ touches), A-tier (2 touches + gap≥5)
- **HTF FVG liquidity levels**: 15m, 30m, 1H, 4H unmitigated FVG edges as sweep targets
- **FVG size filter** (backtest.py): 15m≥5pt, 30m≥8pt, 1H≥10pt, 4H≥15pt
- **FVG recency cap**: 3 most recent unmitigated FVGs per TF (`MAX_FVG_LEVELS_PER_TF=3`)
- **Hard DOL requirement**: TP1 must be a real opposing major level ≥15pts away — no R fallback
- **TF_PRIORITY = [5,4,3,2,1]** + 2m/4m FVG trackers in backtest (Priority 1 ✓)
- **All FVGs of highest TF on leg must invert before entry** (Priority 2 ✓)
- **Sweep candle body dominance**: body ≥ 50% of total range in sweep.py `_check()` (Priority 3 ✓)
- **Strong IFVG close**: close ≥ 2pt beyond FVG far edge (`_ifvg_close_is_strong`) (Priority 4 ✓)
- **DOL = LRL only**: hard DOL requirement, no HRL targets (Priority 5 ✓)
- **IFVG inversion candle body dominance**: body ≥ 50% of range (`_ifvg_close_is_body_dominant`)
- **near_htf_open filter**: blocks IFVG signal emission 1-5 min before 9:30/10:00/10:30/15:00/15:30 ET
- **90-min leg FVG cap**: FVGs on manipulation leg must be within 90 min of sweep candle
- **Setup invalidation**: when re-sweep fires near existing setup level (within 5pt), old setup killed
- **ATR-adaptive sweep gates**: wick penetration, leg size, displacement all scale with ATR(14)
- **Multi-candle sweep detection** (SweepType.GRAB / SWEEP)
- **Displacement check**: ≥1 body-dominant reversal candle within 20 bars of sweep

### Research synthesis priority list — status:
| # | Change | Status |
|---|--------|--------|
| 1 | TF_PRIORITY = [5,4,3,2,1] + 2m/4m trackers | ✅ Done |
| 2 | All FVGs of same TF on leg must invert | ✅ Done (but see Bug B below) |
| 3 | Sweep candle body ≥ 50% of range | ❌ WRONG — remove this filter (see Bug C) |
| 4 | Strong IFVG close ≥ 2pt beyond far edge | ✅ Done |
| 5 | DOL = LRL only | ✅ Done |
| 6 | BE at first internal H/L (not at 1R) | ❌ Not yet |
| 7 | Intermediate H/L as top-tier sweep targets | Partial |
| 8 | HTF alignment gate (4H 72h momentum) | ⚠️ Written but not committed — needs tuning |

### CONFIRMED BUGS (from agent code review 2026-04-14):

**Bug A — Mitigation race / late entry** (`detectors/fvg.py`, `detectors/ifvg.py`)
- Root cause: `fvg_trackers[tf].update()` runs BEFORE `engine.update()` in backtest loop
- When the inversion candle also mitigates the FVG, `_check_mitigation` removes the FVG from `tracker.active` BEFORE the IFVG detector sees it
- Result: signal fires on a LATER candle (or not at all for that FVG), giving terrible RR
- Fix: In `_collect_leg_fvgs` and `_update_leg_fvgs`, also include FVGs from `tracker.mitigated` where `fvg.mitigated_ts == current_candle.ts`

**Bug B — Mitigation ≠ Inversion (false "cleared" status)** (`detectors/ifvg.py` line ~116)
- Root cause: `IFVGDetector.check()` treats a mitigated FVG as "cleared" for the "all must invert" rule
- Mitigation uses `body_high > fvg.top` (= open for bearish candle). A bearish candle with `open > fvg.top` but `close < fvg.top` mitigates the FVG without inverting it
- Next candle sees `fvg.mitigated and fvg.mitigated_ts != candle.ts` → counts as cleared → can fire signal when close never exceeded FVG edge
- This explains the "candle didn't close over FVG" trades in screenshots
- Fix: Track inversion explicitly. Only count FVG as cleared if `close > fvg.top` (long) or `close < fvg.bottom` (short) was observed on a prior candle. Add `inverted: bool` flag to FVG, set only on inversion, not on mitigation

**Bug C — Wrong filter on sweep candle** (`detectors/sweep.py` `_check()`)
- Root cause: Body ≥ 50% filter applied to the SWEEP candle. But sweep candles should show REJECTION (big wick, small body). Sources confirm: "WICKS DO DAMAGE" on sweep candles, "BODIES TELL STORY" on inversion candles
- This filter is filtering out VALID high-wick rejection sweeps
- Fix: Remove body dominance check from `sweep.py _check()`. Body dominance stays only on IFVG inversion candle (already in `_ifvg_close_is_body_dominant`)

**Bug D — Mixed-candle wick quality check** (`models/confluence.py` `_sweep_has_valid_penetration`)
- Root cause: Wick penetration uses `leg_extreme_candle`, but pin-bar shape check uses `sweep_candle` — two different candles for different sub-checks
- A deep wick from a prior candle on the leg can satisfy the wick depth requirement while the actual sweep candle barely ticked the level
- Fix: Both checks should use the same candle. Require `sweep_candle` itself to have minimum wick penetration. `leg_extreme_candle` only used for SL placement

### Signal count status (Q1 2023):
| Month | Signals | W/L/BE | WR | Net R |
|-------|---------|--------|-----|-------|
| Jan 2023 | 20 | 8W/12L | 40% | -3.14R |
| Feb 2023 | 15 | 8W/7L | 53% | +2.58R |
| Mar 2023 | 9 | 3W/5L/1BE | 33% | -1.27R |
| Q1 total | 44 | 19W/24L/1BE | 43% | -1.83R |
- NOTE: These numbers contain false signals from Bugs A/B/C/D above. Real quality will shift after fixes.

### DB Concurrency Warning:
Multiple simultaneous `run_backtest.py` runs corrupt journal.db. Always use unique `db_path` per run:
```python
run_backtest(..., db_path=Path('C:/tmp/bt_clean.db'), clear_db=True)
```
Then copy result to data/journal.db once done.

### MASTER PLAN — Next steps (priority order, do NOT start without reading this):

**STEP 1 — Fix Bug A (mitigation race / late entry)** ✅ DONE
- `_collect_leg_fvgs` includes `tracker.mitigated` — FVGs mitigated on the inversion candle are still visible to IFVG detector

**STEP 2 — Fix Bug B (mitigation ≠ inversion)** ✅ DONE
- `inverted: bool = False` on FVG dataclass
- `IFVGDetector.check()` uses `fvg.inverted` — only counts FVG as "cleared" if it was actually inverted via `close > fvg.top`
- `_is_inversed` uses `candle.close` (not body_high/body_low)

**STEP 3 — Fix Bug C (remove body dominance from sweep candle)** ✅ DONE
- No body dominance check in `detectors/sweep.py` `_check()`
- Body dominance only on IFVG inversion candle (`_ifvg_close_is_body_dominant` in confluence.py)

**STEP 4 — Fix Bug D (sweep wick check same candle)** ✅ DONE
- `_sweep_has_valid_penetration` uses `sweep_candle` for all 3 checks consistently

**STEP 5 — Change TP to fixed 1:1 (1R)** ✅ DONE
- `_calculate_targets()`: TP1 = entry ± risk (always 1R)
- DOL level lookup kept as `tp2` runner reference/label only
- RR-aware DOL skipping removed — 1R TP always fires
- `tp1 is None` guards removed from `_try_model1`, `_try_model2`, `_try_sweep_entry`

**STEP 6 — BE at intermediate liquidity level** ✅ DONE
- `record_signal(signal, liquidity_levels=levels)` in backtest.py
- `_be_level_price` stored per trade = nearest level between entry and TP1 at signal time
- `check_outcomes()` checks `_be_level_price` BEFORE standard `be_trigger_r` BE trigger

**STEP 7 — IFVG inversion speed gate** ✅ DONE
- `first_touch_bar: Optional[int]` on FVG dataclass — set when price first enters the zone
- `FVGTracker.update()` records first touch bar when `candle.low <= fvg.top and candle.high >= fvg.bottom`
- `IFVGDetector.check()` filters out FVGs touched > `IFVG_MAX_CANDLES_AFTER_TOUCH = 4` bars ago

**STEP 8 — HTF Alignment Gate (Priority 8) — next to tackle**
- Code written in `models/confluence.py` `_get_htf_regime()` — currently not called anywhere (placeholder)
- Need to wire it into `_try_model1` / `_try_model2` with tuned threshold
- Approach: only apply when momentum is DECISIVE (diff > 1% of price, ~120pts for NQ at 20k)
- Run backtest validation FIRST (steps 1-7 are now done), then add this gate

### What's currently uncommitted:
- Nothing blocking — all steps 1-7 done. Step 8 (HTF gate) is safe to tackle next.

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

1. **IFVG inversion trigger**: confirmed using `close > fvg.top` (not wick). Resolved.
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
