# Claude CoWork Session Plan — Pine Script Indicator Review

**Purpose:** Extract exact detection logic from TradingView Pine indicators and compare
against the Python bot's detectors. Work confluence by confluence.

**Operator:** A Claude instance with TradingView MCP access.  
**Output:** A comparison table + fix list handed back to the coding Claude.  
**Mode:** Read-only — do not edit any Python files during this session.

---

## ⚡ CURRENT PHASE: Phase 1 — Liquidity Sweep + CISD

Focus: Read **BoS/ChoCh (Nephew_Sam_)** and **Equal Highs and Lows**.
These two indicators answer all open questions for Phase 1.

**Already fixed (don't report these):**
- EQH/EQL tolerance: changed from 0.05% percentage → 2.0pts fixed ✓
- Session H/L: now tracks last 5 sessions (not just most recent) ✓
- PDH/PDL: now tracks last 5 days (not just yesterday) ✓
- CISD temporal guard: CISD must occur after sweep candle ✓

**Open questions for Phase 1 (what to extract from Pine):**

| # | Question | Where to find | Python current |
|---|----------|---------------|----------------|
| 1 | Exact sweep condition — wick rule | BoS/ChoCh source | `c.low < level.price AND c.body_low >= level.price` |
| 2 | Sweep: strict `<` or `<=` on wick? | BoS/ChoCh source | strict `<` |
| 3 | EQH/EQL: tolerance in pts (not %) | Equal Highs and Lows | 2.0pts (changed today) |
| 4 | EQH/EQL: min bar gap between touches | Equal Highs and Lows | 5 bars |
| 5 | EQH/EQL: max levels tracked | Equal Highs and Lows | unlimited |
| 6 | Swing pivot left/right params (15m) | BoS/ChoCh source | left=3, right=2 |
| 7 | ChoCh trigger — body or close? | BoS/ChoCh source (ChoCh section) | `body_high > prior_bearish.open` |
| 8 | ChoCh reference — candle open or swing? | BoS/ChoCh source | most recent opposing candle |

**Start here — go directly to Part 2 (BoS/ChoCh) and Part 3 (Equal H/L).**
Skip Parts 1, 4, 5 for now unless you have time.

---

---

## Part 0: Environment Check

```
mcp__tradingview__chart_get_state()
```

Confirm:
- Symbol: `CME_MINI:NQM2026` (or current NQ front month)
- Timeframe: `5` (5-minute)
- These indicators are visible: `FVG/iFVG (Nephew_Sam_)`, `BoS/ChoCh (Nephew_Sam_)`,
  `Equal Highs and Lows`, `NWOG/NDOG+Event Horizon`, `ICT Killzones & Pivots [TFO]`

If any are missing:
```
mcp__tradingview__chart_manage_indicator(action="add", name="FVG/iFVG (Nephew_Sam_)")
```

---

## Part 1: FVG / iFVG — Nephew_Sam_ (HIGHEST PRIORITY)

### Get the source
```
mcp__tradingview__pine_list_scripts(query="FVG iFVG Nephew_Sam_")
mcp__tradingview__pine_get_source(script_id="<id from above>")
```

### What to extract — answer each question with the exact Pine code

**FVG formation:**
- What three candles define the gap? (`candle[0].high`, `candle[1]`, `candle[2].low` or different indices?)
- Is there a minimum gap size filter? (look for `input`, `min_size`, `atr` comparisons near detection)
- Does it require a specific middle candle direction (e.g., middle candle must be bullish for bullish FVG)?
- Does it use `high`/`low` (wicks) or `open`/`close` (body) for gap edges?
  → **Python uses wicks**: `c0.high < c2.low` for bullish FVG

**Mitigation:**
- Exact condition to mark an FVG as mitigated: is it `close < fvg.bottom` or `low < fvg.bottom`?
  → **Python uses**: `candle.body_low < fvg.bottom` (body, not close)
- Is there a "50% rule" (mitigated when price crosses the CE midpoint)?
- Does Pine auto-expire FVGs after N bars?
- Does Pine limit how many FVGs are tracked at once (e.g., last 5 only)?

**IFVG inversion:**
- Exact condition for inversion: `close > fvg.top` or `high > fvg.top`?
  → **Python uses**: `candle.body_high > fvg.top` — fires when any part of the body is above the top
- Can a mitigated FVG still invert?
- Minimum candles between FVG formation and inversion?

### Read current chart output
```
mcp__tradingview__data_get_pine_boxes(study_filter="FVG/iFVG (Nephew_Sam_)")
mcp__tradingview__data_get_pine_labels(study_filter="FVG/iFVG (Nephew_Sam_)")
```
Record: number of active boxes, price levels, bullish vs bearish count.

### Python files to compare against
- `src/smc_bot/detectors/fvg.py` — `FVGTracker._detect_at()` (formation), `_is_mitigated()` (mitigation)
- `src/smc_bot/detectors/ifvg.py` — `IFVGDetector._is_inversed()`

---

## Part 2: BoS / ChoCh — Nephew_Sam_ (PHASE 1 PRIORITY — covers sweep + CISD)

### Get the source
```
mcp__tradingview__pine_list_scripts(query="BoS ChoCh Nephew_Sam_")
mcp__tradingview__pine_get_source(script_id="<id>")
```

### What to extract — SWEEP DETECTION

**We need to verify our sweep condition against this indicator's LiqSweep/sweep logic:**
- Current Python: `c.low < level.price AND c.body_low >= level.price` (wick below, body closes back above)
- Does this indicator detect sweeps the same way?
- Is the wick condition `<` (strict, must go below) or `<=` (includes exact touch)?
- Is there any minimum wick penetration depth required?
- Does the indicator track which levels are "swept" and skip them afterward?

Copy the exact Pine sweep detection block.

### What to extract — SWING DETECTION

**Pivot parameters:**
- What `left` and `right` values does Pine use in `ta.pivothigh()` / `ta.pivotlow()`?
  → **Python uses**: `left=3, right=2` for 15m swing detection (EQH/EQL)
- Does Pine use `high`/`low` (wicks) or `close` as pivot source?

### What to extract — ChoCh = CISD (THIS IS THE KEY)

In ICT's model, **ChoCh (Change of Character) = CISD (Change in State of Delivery)**.
The user does NOT want BoS — focus on the ChoCh logic specifically.

**Questions:**
- What is the exact ChoCh trigger condition? (the exact Pine line)
  → **Python current**: `current.body_high > most_recent_bearish_candle.open`
- Does Pine check `close > swing.price` or `body_high > opposing.open`?
- Does ChoCh reference the most recent opposing CANDLE open, or a confirmed SWING POINT?
  → **Python uses**: most recent opposing candle — Pine likely uses confirmed swing high/low
- Is it body-based (`close`) or wick-based (`high`/`low`)?

Copy the exact Pine ChoCh detection block.

### Read current chart output
```
mcp__tradingview__data_get_pine_labels(study_filter="BoS/ChoCh (Nephew_Sam_)")
mcp__tradingview__data_get_pine_lines(study_filter="BoS/ChoCh (Nephew_Sam_)")
```
Record: How many ChoCh labels are visible? At what price levels?

### Python files to compare against
- `src/smc_bot/detectors/cisd.py` — `CISDDetector._check_bullish()` / `_check_bearish()`
- `src/smc_bot/detectors/swing.py` — `SwingDetector.__init__()` left/right parameters
- `src/smc_bot/detectors/sweep.py` — `SweepDetector._check()`

---

## Part 3: Equal Highs and Lows

### Get the source
```
mcp__tradingview__pine_list_scripts(query="Equal Highs and Lows")
mcp__tradingview__pine_get_source(script_id="<id>")
```

### What to extract
- Tolerance: fixed points (e.g., `input.float(0.5)`) or percentage?
  → **Python uses**: `tolerance_pct=0.0005` = 0.05% ≈ 10 points at NQ 20,000 — likely WAY too wide
- Minimum bar separation between the equal highs/lows?
- Maximum number of EQH/EQL tracked simultaneously?
- Does Pine remove a level after it has been swept?
  → **Python does NOT remove swept EQH/EQL** — levels stay in the list forever

### Read current chart output
```
mcp__tradingview__data_get_pine_lines(study_filter="Equal Highs and Lows")
mcp__tradingview__data_get_pine_labels(study_filter="Equal Highs and Lows")
```
Count how many EQH/EQL are currently visible. Python currently generates too many.

### Python files to compare against
- `src/smc_bot/detectors/liquidity.py` — `detect_eqhl()`, `_group_equal()`

---

## Part 4: SMT Divergence (find a popular one)

### Find and load
```
mcp__tradingview__pine_list_scripts(query="SMT divergence ICT NQ ES")
```
Pick the most popular result (highest likes). Load it if not already on chart:
```
mcp__tradingview__chart_manage_indicator(action="add", name="<indicator name>")
mcp__tradingview__pine_get_source(script_id="<id>")
```

### What to extract
- Swing parameters: what `left`/`right` for pivot detection?
- **Temporal proximity**: must the two diverging swings occur within N bars of each other?
  → **Python has NO proximity check** — compares most recent NQ swing vs most recent ES swing regardless of time gap
- Price comparison: `low` (wick) or `close` to determine lower low?
- Confirmation required after divergence before signaling?
- Direction logic: "NQ lower low, ES holds higher low → trade ES long" — does Pine agree?
  → **Python**: `a_made_lower and not b_made_lower → trade_symbol = symbol_b (ES)`

### Read current chart output
```
mcp__tradingview__data_get_pine_labels(study_filter="<smt indicator name>")
mcp__tradingview__data_get_pine_lines(study_filter="<smt indicator name>")
```

### Python files to compare against
- `src/smc_bot/detectors/smt.py` — `SMTDetector.check_bullish()` / `check_bearish()`

---

## Part 5: ICT Killzones & Pivots [TFO]

### Get the source
```
mcp__tradingview__pine_list_scripts(query="ICT Killzones Pivots TFO")
mcp__tradingview__pine_get_source(script_id="<id>")
```

### What to extract
- Exact start/end times for each killzone. Compare against Python:
  - **Python**: Asia 19:00–21:00, London 02:00–05:00, NY AM 08:30–11:00, NY PM 13:30–16:00 (all ET)
- Timezone used in Pine: ET, UTC, or CT (CME exchange time)?
- NY AM: does Pine start at 08:30 or 09:30?
- Are there macro windows (9:50–10:10, 10:50–11:10)? Python does not have these.

### Read current chart output
```
mcp__tradingview__data_get_pine_boxes(study_filter="ICT Killzones & Pivots [TFO]")
mcp__tradingview__data_get_pine_labels(study_filter="ICT Killzones & Pivots [TFO]")
```

### Python files to compare against
- `src/smc_bot/filters/session.py` — `SESSIONS` dict, `in_killzone()`

---

## Part 6: Visual Validation Against a Known Bad Signal

Pick a recent date from the journal DB where a trade was wrong.
(The user can query: `SELECT ts, direction, entry_price, outcome FROM trades ORDER BY ts DESC LIMIT 10`)

```
mcp__tradingview__chart_set_timeframe(timeframe="5")
mcp__tradingview__chart_scroll_to_date(date="YYYY-MM-DD")
```

If `chart_scroll_to_date` fails (known issue for dates before 2024):
```
mcp__tradingview__ui_keyboard(key="ctrl+g")
mcp__tradingview__ui_type_text(text="YYYY-MM-DD")
```

Read all indicator outputs at that date and compare to what the Python bot recorded in the DB.

```
mcp__tradingview__capture_screenshot(filename="validation_check.png", region="chart")
```

---

## Session Output Format

At the end, produce this exact structure and hand it to the coding Claude:

```
COMPARISON TABLE
| Rule                    | Pine Script (exact) | Python (current)        | Match? |
|-------------------------|---------------------|-------------------------|--------|
| FVG gap detection       |                     | high[2] < low[0] wicks  |        |
| FVG min gap size        |                     | None                    |        |
| FVG mitigation trigger  |                     | body_low < fvg.bottom   |        |
| FVG max age (bars)      |                     | None                    |        |
| IFVG inversion trigger  |                     | body_high > fvg.top     |        |
| EQH/EQL tolerance       |                     | 0.05% (~10pts at 20k)   |        |
| EQH/EQL swept removal   |                     | Never removed           |        |
| Swing left/right        |                     | left=5, right=2         |        |
| CISD reference point    |                     | Most recent bearish bar |        |
| CISD min body size      |                     | None                    |        |
| SMT temporal proximity  |                     | None                    |        |
| NY AM killzone start    |                     | 08:30 ET                |        |

FIX LIST (one per discrepancy, with exact file + line + change)
Fix 1: ...
Fix 2: ...
```

---

## Quick Reference — MCP Tools

| Goal | Tool |
|------|------|
| Get Pine source | `pine_get_source(script_id=...)` |
| Search indicators | `pine_list_scripts(query=...)` |
| Read FVG zones | `data_get_pine_boxes(study_filter=...)` |
| Read labels/text | `data_get_pine_labels(study_filter=...)` |
| Read price lines | `data_get_pine_lines(study_filter=...)` |
| Change symbol | `chart_set_symbol(symbol=...)` |
| Change timeframe | `chart_set_timeframe(timeframe=...)` |
| Jump to date | `chart_scroll_to_date(date="YYYY-MM-DD")` |
| Screenshot | `capture_screenshot(region="chart")` |
| Add indicator | `chart_manage_indicator(action="add", name=...)` |
| Chart state | `chart_get_state()` |

## Python File Reference

| File | What it contains |
|------|-----------------|
| `src/smc_bot/detectors/fvg.py` | FVG detection + mitigation |
| `src/smc_bot/detectors/ifvg.py` | IFVG inversion entry logic |
| `src/smc_bot/detectors/cisd.py` | CISD / ChoCH detection |
| `src/smc_bot/detectors/swing.py` | Pivot detection (left/right params) |
| `src/smc_bot/detectors/liquidity.py` | EQH/EQL, session levels |
| `src/smc_bot/detectors/smt.py` | SMT divergence NQ/ES |
| `src/smc_bot/filters/session.py` | Killzone time filters |
| `src/smc_bot/models/confluence.py` | Main orchestrator |
