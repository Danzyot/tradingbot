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

## Current State — Where We Left Off (last updated 2026-05-04, session 2)

### CRITICAL: Read before coding anything

All steps 1–8 done. Fixes E/F/H/I applied. Step 9 (HTF gate) disabled (wrong logic). GitHub up to date at commit `aff92a0`.

**KEY FINDING (2026-05-04):** Jun 2023 sweep-only mode = **23 sweeps detected → only 1 IFVG signal**. The IFVG qualification chain is the bottleneck, NOT sweep detection. In strong-trend markets, manipulation-leg FVGs tend to be small and fail the 2pt strong-close gate. Need to investigate rejection counts at each IFVG filter stage.

**Session 2 changes (commit aff92a0):**
- Fixed circular import in `cisd.py` (was broken: TYPE_CHECKING guard removed by mistake)
- `confluence.py`: retroactive leg extreme — at IFVG fire time, rescan from `leg_start_ts` to current candle (not capped at `sweep.ts`). SL now at TRUE leg extreme wick.
- `confluence.py`: `_last_quality_sweeps` list populated after each `update()` call (sweeps passing wick+leg gates, before IFVG)
- `run_legs_scan.py`: scans all quality sweeps + 5m swing points → `data/legs_scan.json`
- `visualize_legs.py`: generates per-day 5m candlestick charts with swing markers (▲▼), shaded manipulation legs, swept level lines, leg extreme × markers
- Jan 2023 backtest with retroactive fix: **13 signals | 4W/5L/4BE | 31% WR | -1R** (was 11/3W/5L/3BE/-2R)

---

### Cumulative changes (all committed):

**Detection quality**
- `TF_PRIORITY = [5,4,3,2,1]` + 2m/4m FVG trackers in backtest
- All FVGs of highest TF on leg must invert before entry (FVG `inverted` flag)
- Strong IFVG close: candle closes ≥ 2pt beyond FVG far edge (`_ifvg_close_is_strong`)
- IFVG open-in-zone: candle.open must be within the FVG zone (not already past the edge)
- IFVG inversion candle body dominance: body ≥ 50% of total range
- IFVG speed gate: FVG first-touch to inversion ≤ 4 bars of FVG's own TF
- IFVG age gate: TF-relative — `max_age = tf_minutes × 8` (1m=8min, 3m=24min, 5m=40min) ← Fix H
  (Was flat 10min — blocked all 5m FVGs since a 5m FVG takes 15min to form, leaving only 5min to invert)
- EQH/EQL grouping now transitive (sort by price, sequential chain) ← Fix E
- EQH/EQL tolerance widened 0.25pt → 1.0pt ← Fix F

**Sweep quality**
- Wick penetration + pin-bar shape + body return all checked on same `sweep_candle` (Bug D fix)
- Body dominance check removed from sweep candle (Bug C fix — sweeps show REJECTION, not body)
- ATR-adaptive gates: wick, leg size, displacement all scale with ATR(14)
- Displacement check: ≥1 body-dominant reversal candle within 30 bars of sweep ← Fix I (was 20)
- Setup invalidation on re-sweep (within 5pt clears old setup)
- 5-min sweep cooldown per level
- 90-min cap on leg lookback for FVG collection

**SL / TP / BE**
- SL: `leg_extreme_candle.low - 2.0` (long) / `leg_extreme_candle.high + 2.0` (short)
- TP1: fixed 1R (entry ± risk). DOL level used as `tp2` runner label only
- BE: triggers at first liquidity level between entry and TP1, BEFORE the standard 1R BE trigger

**DOL targeting**
- Sorted by tier: S (EQH/EQL) > A (unmitigated HTF FVGs) > B (session H/L, PDH/PDL, NWOG/NDOG)
- Only S/A/B tier levels are valid DOL targets; F/C excluded
- Min DOL distance: 15pt from entry

**FVG mitigation race fix** (Bug A/B)
- `_collect_leg_fvgs` uses `tracker.active + tracker.mitigated` — inversion candle can mitigate the FVG in the same bar it fires
- `fvg.inverted` flag: set only when close passes the far edge, NOT on regular mitigation

**Liquidity levels used as sweep targets**
- S-tier: EQH/EQL (3+ touches or ≥4 bars separation)
- A-tier: EQH/EQL (2 touches, 1-3 bars), PDH/PDL
- B-tier: Asia/London/NY session H/L, NWOG/NDOG, major swing H/L (≥15pt wick)
- HTF FVG edges (30m, 1H, 4H) used as A/B-tier sweep targets

---

### MASTER PLAN — Step status:

| Step | Description | Status |
|------|-------------|--------|
| 1 | Fix Bug A: mitigation race (tracker.mitigated) | ✅ Done |
| 2 | Fix Bug B: inverted≠mitigated (fvg.inverted flag) | ✅ Done |
| 3 | Fix Bug C: remove body dominance from sweep candle | ✅ Done |
| 4 | Fix Bug D: wick check uses sweep_candle consistently | ✅ Done |
| 5 | Fixed 1R TP; DOL as runner reference only | ✅ Done |
| 6 | BE at first liquidity level between entry and TP1 | ✅ Done |
| 7 | IFVG speed gate (4-bar first-touch window) | ✅ Done |
| 8 | IFVG open-in-zone check + DOL tier sorting | ✅ Done |
| E | EQH/EQL transitive grouping (sort-then-chain) | ✅ Done |
| F | EQH/EQL tolerance 0.25pt → 1.0pt | ✅ Done |
| H | IFVG age gate: flat 10min → TF-relative (tf × 8) | ✅ Done |
| I | Displacement window: 20 bars → 30 bars | ✅ Done |
| 9 | HTF alignment gate | ⚠️ DISABLED — see below |

---

### Step 9 (HTF Gate) — DISABLED, here's why:

Implemented `_htf_regime_allows()` in `models/confluence.py` — 4H momentum > 150pts filter.

**Problem**: ICT setups are REVERSALS, not trend continuations. Original gate blocked SHORT entries when 4H was bullish — exactly backwards. ICT shorts when price is at PREMIUM (just had a big 4H rally). Debug confirmed: the gate blocked 60 entries in a single 5-day window (Feb 6-10 2023), collapsing Feb/Mar signals to 0.

**What the correct HTF gate should do**: Filter based on DAILY BIAS (daily candle direction and premium/discount position), NOT on 4H momentum direction. Example: "Daily candle is decisively bearish → prefer shorts, be more conservative on longs." This is more nuanced and not yet implemented.

**Method preserved**: `_htf_regime_allows()` exists in `models/confluence.py` but is not called. Constants `_HTF_REGIME_THRESHOLD_PTS` and `_HTF_REGIME_LOOKBACK_BARS` kept for future use.

---

### Fix G (LTF FVG min size) — ATTEMPTED, REVERTED:

Added `LTF_FVG_MIN_SIZE = {1:2.0, 2:2.5, 3:3.0, 4:3.5, 5:4.0}` to FVGTracker init. Reverted because it blocked legitimate manipulation-leg FVGs on quiet/low-volatility days (not all FVGs are 2pt+). The existing `_ifvg_close_is_strong` check (2pt close beyond FVG edge) already prevents entries from tiny FVGs.

---

### Signal count — current state (post all fixes):

Previously (with bugs A-D): Q1 2023 = 44 signals, 43% WR, -1.83R net.

**January 2023 (with fixes H+I, 2026-05-04, session 1):** 11 signals | 3W/5L/3BE | 27% WR | -2R net
- Added 1 new signal (Jan-10 14:46 SHORT) from the TF-relative age gate fix — that signal lost

**January 2023 (with retroactive leg fix, 2026-05-04, session 2):** 13 signals | 4W/5L/4BE | 31% WR | -1R net
- Retroactive SL fix widened stop placement → 2 more signals now meet min RR 1.0
- Note: full-month runs show 2 apparent duplicates on Jan 30 (different setups, same minute); isolated Jan 30 run shows 2 unique signals correctly — likely a pre-existing concurrent-limit edge case

**June 2023 2-week (2023-06-05 to 2023-06-16):** 1 signal | 0W/1L/0BE | 0% WR | -1R
- Sweep-only mode showed 23 sweeps → only 1 IFVG signal (4% conversion)
- Strong AI bull trend market: manipulation legs were small, FVGs didn't pass 2pt strong-close gate
- This is the primary open problem

**User target: 1-5 trades per day** (5-25 per week). Current: ~0.1-0.5/day — far below target.

---

### Signal count investigation — OPEN:

The 23-sweep → 1-IFVG finding in June 2023 shows the IFVG chain is too strict for trending markets.
Specific filter causing most rejections is unknown — need debug rejection counters.
Prime suspect: `_ifvg_close_is_strong` (2pt gate) combined with small manipulation-leg FVGs in trends.

Potential fix: add debug counters to `_try_model1` to see rejections at each gate.

---

### DB Concurrency Warning:
Multiple simultaneous `run_backtest.py` runs corrupt journal.db. Always use a unique `db_path`:
```python
run_backtest(..., db_path=Path('C:/tmp/bt_NAME.db'), clear_db=True)
```

---

### NEXT STEP (do this first when resuming):

1. **Visual review of swing + legs charts** — run `python visualize_legs.py` and check if:
   - Swing highs ▲ / swing lows ▼ are structurally correct
   - Manipulation legs (shaded zones) cover the right candle range
   - Leg extreme × aligns with the actual wick tip of the leg
   Then report back — if swings look wrong, adjust `SWING_VIZ_LEFT/RIGHT` params in `run_legs_scan.py`.

2. **Add IFVG rejection debug counters** to `_try_model1` in `confluence.py`. Count rejections at each gate:
   - displacement failed
   - no FVG on leg
   - ifvg_detector returned None (age gate? speed gate? no inversion?)
   - body_dominance failed
   - strong_close failed
   - rr < min_rr
   Re-run Jun 2023 with debug mode and see which gate rejects the most setups.

3. **If strong_close (2pt) is the culprit**: test 1pt threshold and compare signal count/quality.

4. **After debug investigation**, implement daily-bias HTF gate (Step 9 correct ICT version):
   - Daily candle direction: `d_close > d_open` → bullish bias → weight longs
   - Premium/discount: price above midpoint of last 5 daily range → premium → weight shorts
   - Soft filter (weight/score adjustment), not hard block

5. **Notion progress page**: needs NOTION_TOKEN added to Windows user env variables.
   Run `create_notion_progress.py` after setting the token.

---

### DOL tier hierarchy (from cheat sheet):
1. **S-tier:** EQH/EQL (especially when aligned with PDH/PDL/PWH/PWL)
2. **A-tier:** Unmitigated FVGs (bullish FVG below for long, bearish above for short)
3. **B-tier:** PDH/PDL, Asia/London/NY session H/L, NWOG/NDOG
4. **B-tier:** Data highs/lows (news candle extremes)
5. **B-tier:** Intermediate H/L inside/adjacent to FVG
- **F-tier (ignore):** H/L that took out another H/L inside an FVG

### Multi-agent setup:
- Claude 1 (this): main coding session, auto-pushes to GitHub on every commit
- Claude 2: second subscription, picks up from GitHub + CLAUDE.md
- Claude CoWork: reads Pine Script via TradingView MCP, produces fix tables

### Working preferences:
- Fully autonomous mode — continue without asking for approval on each step
- Use subagents freely (research, code audit, web search)
- Short validation windows (1-2 weeks max per run, not full Q1)
- Commit after every logical unit of work — both subscriptions share GitHub
- After fixes: run backtest → upload screenshots to Discord → visually review → iterate

---

## Known Issues / TODO

1. **Signal frequency** — 0.1-0.5/day vs target 1-5/day. Root cause: IFVG chain converts only 4% of sweeps in strong-trend markets. 2pt strong-close gate is prime suspect. Need rejection counters.
2. **HTF alignment gate** — disabled; needs daily-bias implementation. Do NOT re-enable the 4H momentum version.
3. **NOTION_TOKEN** — not in Windows user env. Add to HKCU\Environment to use Notion sync.
4. **/grill-me skill** — added to `C:\Users\yotda\.claude\commands\grill-me.md`. Type `/grill-me` to use.
5. **create_notion_progress.py** — in repo root, creates Notion progress dashboard. Needs NOTION_TOKEN.
4. **CISD reference** — uses most recent opposing candle, not structural swing. Model 2 is disabled; low priority.
5. **HTF FVG drawing coords** — screenshots don't draw the HTF FVG zone box when the swept level was an FVG edge. The data is in `level.kind` (`60m_fvg_high`, etc.) but `fvg_top/bottom` coords for the zone aren't stored.
6. **Daily bias filter** — proper ICT premium/discount approach not yet implemented (Step 9 placeholder).
7. **Live data loop** — not built yet. Future phase.
8. **C-tier order blocks** — not yet implemented.
9. **TradingView MCP** — can't navigate to Jan 2023 (3yr+ ago). Use `generate_screenshots.py` instead.

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
