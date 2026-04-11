# Liquidity Sweep — Action Plan for Claude Code
**Scope:** Perfect the liquidity sweep detection only. No IFVG, no CISD, no SMT changes in this sprint.  
**Sources:** TradingView live data (BoS/ChoCh Nephew_Sam_, Equal H/L), tier list image, ICT research, CoWork code review.  
**Status of current code:** Sweep condition correct. Level quality is the problem.

---

## What's Wrong Right Now (Root Causes)

1. **EQH/EQL tier rules don't match the tier list** — 2-touch levels with gap 1–3 bars are silently skipped. These are A-tier per the tier list.
2. **Individual swing H/L not tracked as levels at all** — "data high/low with massive wick" (S-tier) is documented but never built. A major swing low with a big wick is the most-swept level in ICT and the bot ignores it entirely.
3. **Sweep has no minimum wick filter** — a 0.25pt wick beyond the level triggers a sweep setup. Real manipulation legs wick well beyond the level.
4. **No displacement candle check** — after a sweep, the bot doesn't verify that price moved away aggressively. Without displacement, you can't know if the sweep was real or random noise.
5. **Swing detector params for 15m don't match Nephew_Sam_** — currently `left=3, right=2`. Should be `left=2, right=2` to match the indicator that defines structural pivots.
6. **EQH/EQL tolerance** — currently 1.0pt. TV indicator tracks levels 0.25pt apart as separate. Should be 0.5pt max.

---

## Exact Changes — Ordered by Impact

---

### Fix 1 — `src/smc_bot/engine/backtest.py`: SwingDetector params

**Current:**
```python
HTF_SWING_LEFT = 3
HTF_SWING_RIGHT = 2
swing_15m = SwingDetector(left=3, right=2)
```

**Change to:**
```python
HTF_SWING_LEFT = 2
HTF_SWING_RIGHT = 2
swing_15m = SwingDetector(left=2, right=2)   # matches Nephew_Sam_ pivot params (confirmed via TradingView MCP)
```

**Why:** BoS/ChoCh (Nephew_Sam_) uses left=2, right=2 at 15m — inferred from minimum 5-bar spacing between 482 structural events. This is the pivot lookback that defines what counts as a "major high/low" in ICT. Python's current left=3 detects fewer pivots, meaning it misses structural swing points the market actually respects.

---

### Fix 2 — `src/smc_bot/detectors/liquidity.py`: EQH/EQL tolerance + tier rules

**Current `_group_equal` logic:**
```python
candle_gap = group[-1].candle_index - group[0].candle_index ...
if len(group) >= 3:
    tier = LiqTier.S
elif len(group) == 2 and candle_gap >= 5:
    tier = LiqTier.A
else:
    continue   # skips 2-touch levels with gap < 5
```

**Change to:**
```python
# Tolerance: change detect_eqhl default
def detect_eqhl(swing_points, tolerance_pts: float = 0.5):  # 0.5pt = 2 ticks — tight but not 1-tick noise

# Tier rules — match the tier list image exactly:
# S = 3+ touches (any gap), OR 2 touches > 3 candles apart
# A = 2 touches, 1–3 candles apart
# Skip: 0 candles apart (same bar) or only 1 touch

if len(group) >= 3:
    tier = LiqTier.S
elif len(group) == 2 and candle_gap > 3:
    tier = LiqTier.S   # > 3 candles apart = perfect EQH/EQL (S-tier per tier list)
elif len(group) == 2 and 1 <= candle_gap <= 3:
    tier = LiqTier.A   # 1–3 candles apart = still significant (A-tier per tier list)
else:
    continue   # same bar or no gap — skip
```

**Why:** The tier list clearly shows: S = "more than 3 candles apart", A = "one–three candles away". Current code assigns A-tier only to levels with gap ≥ 5, which is wrong — it skips A-tier levels (gap 1–3) entirely. This means the bot ignores a huge category of valid sweep targets.

---

### Fix 3 — `src/smc_bot/detectors/liquidity.py`: Add individual swing H/L as levels

Add a new function after `detect_eqhl`:

```python
def detect_swing_levels(
    swing_points: list[SwingPoint],
    candles: list[Candle],
    min_wick_pts: float = 5.0,   # minimum wick size to be considered a notable level
    wick_s_tier_multiplier: float = 2.0,  # wick ≥ 2× avg wick → S-tier ("massive wick")
) -> list[LiquidityLevel]:
    """
    Individual swing highs/lows as sweep targets.
    
    S-tier ("data high/low with massive wick"): swing point with wick ≥ 2× average wick
    B-tier: notable swing point with wick ≥ min_wick_pts
    Skip: minor swings with small wicks (noise)

    Only uses the last 20 swing points to avoid a flood of old levels.
    """
    if not swing_points or not candles:
        return []

    # Average wick size for context
    recent = candles[-50:] if len(candles) >= 50 else candles
    avg_wick = (
        sum(max(c.high - c.body_high, c.body_low - c.low) for c in recent) / len(recent)
    )

    levels: list[LiquidityLevel] = []
    for sp in swing_points[-20:]:   # last 20 structural swings only
        # Find the candle at this swing point
        matching = [c for c in candles if c.ts == sp.ts]
        if not matching:
            continue
        candle = matching[0]

        if sp.kind == SwingType.HIGH:
            wick = candle.high - candle.body_high   # upper wick
            if wick < min_wick_pts:
                continue   # not notable enough
            tier = LiqTier.S if wick >= avg_wick * wick_s_tier_multiplier else LiqTier.B
            levels.append(LiquidityLevel(
                price=candle.high,
                tier=tier,
                kind="swing_high",
                ts=sp.ts,
            ))
        else:
            wick = candle.body_low - candle.low    # lower wick
            if wick < min_wick_pts:
                continue
            tier = LiqTier.S if wick >= avg_wick * wick_s_tier_multiplier else LiqTier.B
            levels.append(LiquidityLevel(
                price=candle.low,
                tier=tier,
                kind="swing_low",
                ts=sp.ts,
            ))

    return levels
```

Then in `backtest.py`, add after the EQH/EQL detection:
```python
# Individual notable swing H/L (major pivots with significant wicks)
levels.extend(detect_swing_levels(swings_15m, candles_15m))
```

**Why:** "Data high/low with massive wick" is the S-tier definition in the tier list and is currently completely absent from the bot. These are the most-swept levels in ICT — prominent intraday and prior-day pivots where large wicks indicate stop hunts already happened, making them magnets for future sweeps.

---

### Fix 4 — `src/smc_bot/detectors/sweep.py`: Minimum wick penetration

**Current `_check` method:**
```python
if (c.low < level.price and c.body_low >= level.price):
    return Sweep(...)
```

**Change to:**
```python
_MIN_WICK_BEYOND = 2.0   # pts the wick must extend BEYOND the level (not just touch it)

def _check(self, c: Candle, level: LiquidityLevel) -> Sweep | None:
    # Bullish sweep: wick below, body closes above
    wick_beyond = level.price - c.low   # how far wick went past level
    if (c.low < level.price and
            c.body_low >= level.price and
            wick_beyond >= self._MIN_WICK_BEYOND):
        return Sweep(...)

    # Bearish sweep: wick above, body closes below
    wick_beyond = c.high - level.price
    if (c.high > level.price and
            c.body_high <= level.price and
            wick_beyond >= self._MIN_WICK_BEYOND):
        return Sweep(...)
```

Also add `wick_beyond` to the `Sweep` dataclass so it's logged:
```python
@dataclass
class Sweep:
    ...
    wick_beyond_pts: float = 0.0   # how far the wick extended past the level
```

**Why:** Any candle that barely touches a level is not a sweep — it's noise. A real manipulation leg takes liquidity by a meaningful amount. 2pts minimum (8 ticks on NQ at 0.25 tick size) is conservative but filters single-tick tags. Start here; tune upward if still too many signals after backtest.

---

### Fix 5 — `src/smc_bot/models/confluence.py`: Displacement candle check

Add this method to `ConfluenceEngine`:

```python
_MIN_DISPLACEMENT_BODY_PTS = 8.0   # minimum body size for displacement candle (8pts at NQ)
# Alternatively use ATR-relative: displacement body >= 0.4 * ATR(14)

def _has_displacement(
    self, sweep: Sweep, candles_by_tf: dict[int, list[Candle]]
) -> bool:
    """
    Check that within 3 bars after the sweep, at least one candle shows
    strong displacement in the reversal direction.
    
    Displacement = a candle with a large body moving AWAY from the swept level.
    This is the candle that creates the FVG on the manipulation leg.
    Without it, the sweep is random noise, not institutional manipulation.
    """
    ltf = candles_by_tf.get(1, [])
    if not ltf:
        return False

    sweep_ts = sweep.ts
    post_sweep = [c for c in ltf if c.ts > sweep_ts][:5]  # first 5 candles after sweep

    for c in post_sweep:
        body = c.body_size
        if body < self._MIN_DISPLACEMENT_BODY_PTS:
            continue

        if sweep.direction == SweepDirection.BULLISH:
            # Need a bullish displacement (strong move UP away from swept low)
            if c.bullish and c.close > sweep.sweep_candle.body_low:
                return True
        else:
            # Need a bearish displacement (strong move DOWN away from swept high)
            if c.bearish and c.close < sweep.sweep_candle.body_high:
                return True

    return False
```

Then in `_try_model1` and `_try_model2`, add displacement check after the sweep setup is created:
```python
# In _try_model1, before the IFVG check:
if not self._has_displacement(setup.sweep, candles_by_tf):
    return None   # no displacement = sweep is noise, skip
```

**Why:** The other CoWork session confirmed this from ttrades research — displacement is the key missing filter. After a real liquidity sweep, institutions enter aggressively in the other direction. This creates: (1) the FVG on the leg, and (2) the IFVG later. If there's no displacement, there's no institutional entry, and the IFVG is fake. This single check should remove a large portion of false setups.

---

### Fix 6 — `src/smc_bot/detectors/ifvg.py`: IFVG trigger bug (confirmed)

**Current:**
```python
if direction == IFVGDirection.BULLISH:
    return candle.body_high > fvg.top   # WRONG: body_high = max(open, close) fires on bearish open
```

**Change to:**
```python
if direction == IFVGDirection.BULLISH:
    return candle.close > fvg.top       # close only — must be a bullish close above the FVG
else:
    return candle.close < fvg.bottom    # close only — must be a bearish close below the FVG
```

**Why:** `body_high = max(open, close)`. A bearish candle that opens above the FVG top and closes below it will fire a bullish IFVG entry — long entry on a down-close candle. This is a confirmed bug. The fix is one line.

---

## What NOT to Change in This Sprint

- **CISD**: Keep as optional bonus only, not a gate. Don't add it to sweep detection.
- **SMT**: Separate concern, separate sprint after sweeps are validated.
- **Confluence scoring system** (0–14 proposed by other session): Good idea, but add it only after binary gates are validated in backtest. Premature optimization.
- **Order blocks (C-tier)**: Not yet. Focus on S/A/B.
- **Trend line liquidity (LRLR)**: Complex, skip for now.
- **F-tier filter** (H/L inside FVG): Nice to have, not urgent. Add later.

---

## Backtest Validation Sequence

After the code changes, run in this order:

```python
# Step 1: One week, tight
run_backtest(date_from="2023-01-02", date_to="2023-01-08")
# Target: 3–10 signals. If > 15, tighten _MIN_DISPLACEMENT_BODY_PTS or _MIN_WICK_BEYOND.
# If < 3, loosen tolerance_pts back to 1.0 or lower _MIN_WICK_BEYOND to 1.5.

# Step 2: One month (if week 1 looks right)
run_backtest(date_from="2023-01-02", date_to="2023-01-31")
# Target: 15–50 signals. Check sweep level distribution in the DB.

# Step 3: Check the DB after each run
SELECT sweep_kind, sweep_tier, COUNT(*), AVG(pnl_r) FROM trades GROUP BY sweep_kind, sweep_tier;
# S-tier sweeps should have best PnL per R. If B-tier is performing better, something is wrong.
```

---

## Summary: Files to Touch

| File | Change | Priority |
|---|---|---|
| `engine/backtest.py` | SwingDetector left=2, right=2; add swing_levels call | 1 |
| `detectors/liquidity.py` | EQH/EQL tier rules fix; add detect_swing_levels() | 1 |
| `detectors/sweep.py` | Min wick filter; add wick_beyond to Sweep dataclass | 2 |
| `detectors/ifvg.py` | close instead of body_high/body_low | 2 |
| `models/confluence.py` | Add _has_displacement() check | 3 |

Do fixes 1–2 first, run backtest, check signal count, then add 3–5.

---

## Key Numbers (NQ-specific)

| Parameter | Value | Reasoning |
|---|---|---|
| EQH/EQL tolerance | 0.5pt | TV tracks 0.25pt apart as separate; 0.5pt = 2 ticks, tight but not single-tick noise |
| Swing detector (15m) | left=2, right=2 | Matched from Nephew_Sam_ BOS/ChoCh — 482 labels at min 5-bar spacing |
| Min wick beyond level | 2.0pt | Start conservative; tune up if too noisy |
| Min displacement body | 8.0pt | ~32 ticks on NQ; filters micro-candles |
| Min leg size | 10pt | Already in place — keep |
| Sweep cooldown | 120min | Already in place — keep |
| FVG recency cap | 3 per TF | Already in place — keep |
