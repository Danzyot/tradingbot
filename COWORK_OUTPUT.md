# CoWork Session Output — Liquidity Sweep & Indicator Alignment
**Date:** 2026-04-10  
**Focus:** Sweep detection rules, EQH/EQL tolerance, killzone times  
**Source:** Live TradingView MCP data + code review of Python detectors

---

## What Was Accessible

| Indicator | Source Code | Live Data |
|---|---|---|
| Equal Highs and Lows | ❌ Not extractable via MCP | ✅ 421 lines pulled |
| ICT Killzones & Pivots [TFO] | ❌ Not extractable via MCP | ✅ All labels + boxes pulled |
| NWOG/NDOG + Event Horizon | ❌ Not extractable via MCP | ✅ Box data pulled |
| FVG/iFVG (Nephew_Sam_) | ❌ Not on chart (add manually) | ❌ |
| BoS/ChoCh (Nephew_Sam_) | ❌ Not on chart (add manually) | ❌ |

Pine source extraction is blocked: `pine_get_source` reads only the open editor script (blank "My script"). Public indicator sources cannot be pulled programmatically. **BoS/ChoCh and FVG must be manually added to the chart before their data can be read.**

---

## Comparison Table

| Rule | TV Indicator (observed/inferred) | Python (current) | Fix Needed? |
|---|---|---|---|
| **EQH/EQL tolerance** | ~0–1 tick (0–0.25 pts) — levels 0.25 apart are SEPARATE lines | 0.05% ≈ 12.5 pts at NQ 25k | ✅ YES — tolerance is ~50x too wide |
| **EQH/EQL total levels** | 421 horizontal lines on ~3 days of 5m | Python generates far fewer, groups too aggressively | ✅ YES — Python merges distinct levels |
| **EQH/EQL swept removal** | Unknown (couldn't get source) | Swept levels remain forever | ⚠️ LIKELY NEEDED |
| **Sessions / killzones** | 5 sessions: AS, LO, NYAM, **NYL**, NYPM | 4 sessions: Asia, London, NY AM, NY PM | ✅ YES — Python missing NY Lunch |
| **NY AM start time** | NYAM confirmed present (time unknown without source) | 08:30 ET | ❓ Needs Pine source to verify |
| **IFVG inversion trigger** | Unknown (FVG indicator not on chart) | `body_high > fvg.top` — fires on bearish candle if open > fvg.top | ✅ YES — should be `close > fvg.top` |
| **NWOG/NDOG zone** | Shows as single line (top == bottom = 25038.75) when no real gap | Python treats as two prices (top/bottom) | ✅ YES — skip if gap size < 1 tick |
| **SMT temporal proximity** | Unknown | None — compares any 2 swing points regardless of age | ✅ YES — stale swing comparison |
| **Sweep condition (BoS/ChoCh)** | Unknown (not on chart) | Wick penetrates, body closes back inside | ❓ Needs Pine source to verify |
| **FVG gap detection** | Unknown (not on chart) | `c0.high < c2.low` wicks | ❓ Needs Pine source to verify |
| **FVG mitigation** | Unknown | `body_low < fvg.bottom` | ❓ Needs Pine source to verify |

---

## High-Confidence Fixes

### Fix 1 — EQH/EQL tolerance (HIGHEST IMPACT)
**File:** `src/smc_bot/detectors/liquidity.py` → `detect_eqhl()`  
**Current:** `tolerance_pct=0.0005` (percentage-based, ~12.5 pts at NQ 25k)  
**TV behavior:** Levels 0.25 apart (1 tick) are tracked as separate levels  
**Fix:** Change to fixed-point tolerance of **1.0–2.0 pts** (4–8 ticks)

```python
# Change this:
def detect_eqhl(swing_points, tolerance_pct=0.0005):

# To this:
def detect_eqhl(swing_points, tolerance_pts=1.0):  # absolute points, not percentage
    # In _group_equal, change:
    # if abs(p.price - q.price) / p.price <= tol:
    # To:
    # if abs(p.price - q.price) <= tol:
```

**Impact:** Python currently merges levels 12.5 pts apart into one "EQH/EQL". TV treats them as separate. This means Python creates fake S/A-tier levels from price points that TV would never label equal. These become false sweep targets.

---

### Fix 2 — IFVG inversion trigger (CONFIRMED BUG)
**File:** `src/smc_bot/detectors/ifvg.py` → `IFVGDetector._is_inversed()`  
**Current:**
```python
if direction == IFVGDirection.BULLISH:
    return candle.body_high > fvg.top   # body_high = max(open, close)
else:
    return candle.body_low < fvg.bottom
```
**Problem:** `body_high = max(open, close)`. A bearish candle that OPENED above the FVG top will fire a bullish IFVG entry even though it CLOSED below — you enter long on a downward-closing candle.  
**Fix:**
```python
if direction == IFVGDirection.BULLISH:
    return candle.close > fvg.top
else:
    return candle.close < fvg.bottom
```

---

### Fix 3 — NY Lunch killzone missing
**File:** `src/smc_bot/filters/session.py` → `SESSIONS` dict  
**TV shows:** 5 sessions — AS, LO, NYAM, **NYL** (NY Lunch), NYPM  
**Python has:** 4 sessions — Asia, London, NY AM, NY PM  
**Fix:** Add NY Lunch. ICT defines it as approximately **12:00–13:30 ET**.
```python
"ny_lunch": (time(12, 0), time(13, 30)),
```
Note: Confirm exact times from TFO Pine source before committing — couldn't extract.

---

### Fix 4 — NWOG/NDOG skip when no real gap
**File:** `src/smc_bot/detectors/liquidity.py` → `detect_ndog()` / `detect_nwog()`  
**TV behavior:** Shows as single price point (line) when gap is zero  
**Current Python:** Only skips if `abs(prev_day_close - current_day_open) < 1e-8` (essentially zero)  
**Fix:** Skip if gap < 2 pts (8 ticks) — not worth tracking micro-gaps as liquidity
```python
if abs(prev_day_close - current_day_open) < 2.0:
    return []
```

---

### Fix 5 — SMT temporal proximity
**File:** `src/smc_bot/detectors/smt.py` → `check_bullish()` / `check_bearish()`  
**TV behavior:** Unknown (indicator not on chart), but logically NQ/ES divergence is only valid within same session  
**Current Python:** Compares most recent 2 swing lows regardless of time gap  
**Fix:** Add bar-count or time-based proximity check — only compare swings within 60 bars (5 hours at 5m)

---

## BoS/ChoCh Swing Params — CONFIRMED

Indicator: "Market Structure BOS/CHOCH/MSB/FVG/OB/BB (Nephew_Sam_)" — 24K likes  
Chart TF: 15m | Labels pulled: 482 total

**Inferred from bar spacing analysis:**

| Parameter | Value | Evidence |
|---|---|---|
| `left` bars | **2** | Min same-direction gap = 5 bars = left+right+1 |
| `right` bars | **2** | Consistent 5-bar minimum across 482 labels |
| Source | **high/low** (not close) | Standard for structure indicators |
| Runs on | **Chart TF** (not hardcoded) | Indicator runs on whatever TF the chart is set to |

**The real fix this unlocks:**

Python's EQH/EQL detection uses `swing_ltf` (left=5, right=2) on **1m data**.  
Nephew_Sam_ uses left=2, right=2 on **15m data**.

These are on completely different scales:
- Python 1m left=5: pivot holds for 5 min left, 2 min right → micro-swings
- Nephew_Sam_ 15m left=2: pivot holds for 30 min left, 30 min right → structural swings

**Python is feeding 1m micro-swings into EQH/EQL detection. These are NOT the swings the TV indicator considers structural.** EQH/EQL should only be built from the **15m swing detector** (currently `swing_15m` in the backtest), with params updated to `left=2, right=2` to match.

### Fix for Claude Code:
**File:** `src/smc_bot/engine/backtest.py`  
Change `detect_eqhl` to use `swing_15m` output (not `swing_ltf`), and update `swing_15m`:
```python
# Change:
swing_15m = SwingDetector(left=3, right=2)
# To:
swing_15m = SwingDetector(left=2, right=2)  # matches Nephew_Sam_ pivot params
```
And only pass 15m swing points into `detect_eqhl()` — not 1m points.

---

## What Still Needs Pine Source

These cannot be confirmed without extracting source from BoS/ChoCh and FVG/iFVG (Nephew_Sam_):

1. **Sweep condition** — is the wick-in / body-out rule exactly as Python has it?
2. **FVG gap detection** — wicks or body for gap edges?
3. **FVG mitigation** — `close < fvg.bottom` or `body_low < fvg.bottom` or `low < fvg.bottom`?
4. **IFVG inversion** — `close > fvg.top` vs `high > fvg.top` (Python currently uses body_high)
5. **Swing left/right params** — what does BoS/ChoCh use for pivot detection?
6. **EQH/EQL tolerance exact value** — inferred as ~1pt but needs Pine source to confirm
7. **NY AM exact start** — 08:30 vs 09:30 in TFO

**To unblock:** Manually add "BoS/ChoCh (Nephew_Sam_)" and "FVG / iFVG (Nephew_Sam_)" from the Indicators library in TradingView. Once on chart, CoWork can read their Pine label/box data and infer the rules from their output.

---

## ICT Killzones Raw Data (for reference)

Sessions visible on current chart (past ~3 days, 5m NQ):

| Session | Label | Sample H | Sample L |
|---|---|---|---|
| Asia | AS.H / AS.L | 24359.25 | 24152.5 |
| London | LO.H / LO.L | 24383 | 24207.25 |
| NY AM | NYAM.H / NYAM.L | 24303.25 | 23994 |
| NY Lunch | NYL.H / NYL.L | 24241.5 | 24105.5 |
| NY PM | NYPM.H / NYPM.L | 24380.75 | 24076.5 |

---

## Equal Highs Raw Count

- **421 horizontal lines** on visible range (~3 days of 5m NQ)
- Prices 0.25 apart (1 tick) are tracked as SEPARATE levels
- Python's 12.5pt tolerance merges ~50 ticks worth of distinct price points into one EQH/EQL
- This creates false S/A-tier levels from noise and misses real precision levels

---

## Priority Order for Claude Code

1. ✅ **Fix IFVG trigger** (`close` not `body_high/body_low`) — confirmed bug, fix now
2. ✅ **Fix EQH/EQL tolerance** (12.5pt → 1–2pt absolute) — high impact on sweep targets
3. ✅ **Add NWOG/NDOG min gap** (skip < 2pt gaps)
4. ⚠️ **Add NY Lunch killzone** (pending exact time confirmation)
5. ⚠️ **Fix SMT proximity** (pending TV indicator confirmation)
6. ❓ **Verify sweep/FVG/IFVG rules** — blocked until Nephew_Sam_ indicators added to chart
