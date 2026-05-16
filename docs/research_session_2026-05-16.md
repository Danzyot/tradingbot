# Research Session — 2026-05-16
## Full Pre-Ideation Research: ICT/SMC Trading Bot Planning
### 16 parallel agents — YouTube, X, Reddit, GitHub, NQStats, Pine Script, codebase audit

---

## PART 1: WHAT THE CURRENT BOT ACTUALLY DOES (Codebase Audit)

### The Full Pipeline — 16 Gates Every Signal Must Pass

| # | Gate | Threshold | Adaptive? |
|---|---|---|---|
| 1a | Session killzone | 5 ET windows | No |
| 1b | News blackout | 30min pre / 15min post USD High | No |
| 2a | Level tier | S/A/B only | No |
| 2b | Level direction | Must match kind | No |
| 2c | Already-swept | Binary flag | No |
| 2d | Single-candle grab | wick through + body closes back same candle | No |
| 2e | Multi-candle sweep fallback | prior closed beyond, current closes back | No |
| 3a | Wick depth | max(3, atr14 × 0.15–0.20) | YES |
| 3b | Pin-bar shape | wick ≥ 20% of total range | No |
| 3c | Body return | max(1, atr14 × 0.05) | YES |
| 4 | Leg significance | max(10, atr14 × 0.80) | YES |
| 5 | 90-min leg cap | Hard 90-min lookback | No |
| 6 | Leg FVGs exist | At least one | No |
| 7a | Sweep cooldown | 5 min per level | No |
| 7b | Consumed levels | Permanent block | No |
| 8 | HTF alignment | **DISABLED** | — |
| 9 | Displacement | max(3, atr14 × 0.30) body, 30 bars | YES |
| 10 | Re-sweep invalidation | 5pt zone | No |
| 11 | HTF open block | 5 windows, 5min pre-open | No |
| 12a | TF priority | [5,4,3,2,1] min | No |
| 12b | Speed gate | ≤4 bars from first touch to inversion | No |
| 12c | Age gate | TF × 8 min | YES |
| 12d | **All FVGs must invert** | Binary per FVG — ALL before entry fires | No |
| 12e | Inversion detection | Body close past far edge + open in zone | No |
| 13a | Body dominance | ≥50% of range | No |
| 13b | **Strong close** | **≥2pt beyond far edge (FIXED)** | No |
| 14 | Sweep-to-entry cap | ≤60 min | No |
| 15 | Leg extreme retroactive | Rescan to IFVG candle | No |
| 16 | Min RR | ≥1.0 | No |

### Estimated June 2023 Rejection Breakdown (23 sweeps → 1 signal = 4% conversion)

| Gate | Est. % of rejections | Notes |
|---|---|---|
| 13b — 2pt strong close | ~60% | Trending market → small FVGs → small inversion moves |
| 12b/12c — speed + age | ~18% | 5m FVG only lives 40min; speed window narrow |
| 9 — displacement | ~12% | Trend candles have momentum already embedded |
| 12d — all must invert | ~8% | Multiple FVGs on leg, only one may invert |
| 16 — RR gate | ~2% | Wide SL from retroactive leg extreme |

### Real Conflict in the Code
- Gate 6 (leg FVG collection) runs within 90min of sweep
- Gate 12c (age gate) expires a 5m FVG at 40min
- If inversion happens at sweep+50min, FVG passes Gate 6 but fails Gate 12c — collected but then expired

### Gates That Exist ONLY in This Bot (Not Found in Any Public Implementation)
1. **All FVGs on leg must invert** (12d) — canonical IFVG fires on FIRST FVG
2. **2pt minimum strong close** (13b) — all public implementations use binary body-close-past-edge
3. **4-bar speed gate** (12b) — not found anywhere
4. **TF×8 age gate** (12c) — not found anywhere
5. **Open-in-zone check** (12e partial) — not found anywhere
6. **ATR-adaptive leg gates** (3a, 3c, 4, 9) — no public implementation uses ATR scaling here

---

## PART 2: HARD FACTS FROM THE OUTSIDE WORLD

### 2a. The Math Problem (Critical)

At 1:1 R:R, breakeven win rate = **50%**. Bot is at **31%** in Jan 2023.

That is 19 points below breakeven. This is a **structural math problem**, not a filter problem. No parameter tuning fixes a 19-point gap at 1R. Options:
- Get win rate to 50%+ (requires better signal quality)
- Increase RR to 1:2 (breakeven drops to 33%) or 1:3 (breakeven drops to 25%)
- Both

Best independently verified SMC backtest (2,600 trades, 10 assets, 26 months): **61% WR, 2.17 profit factor** at multi-R targets.

### 2b. The Model Confusion (Critical)

**Your Model 1** (manipulation-leg FVG → IFVG inversion → market at close) is **not the canonical ICT 2022 model**.

**Canonical ICT 2022 "One Setup for Life":**
1. Sweep liquidity
2. Price displaces → leaves displacement FVG on reversal leg
3. Price retests that displacement FVG
4. **Limit order at CE (50% of FVG)** — SL beyond swept extreme

Your bot: sweep → manipulation-leg FVG (before sweep) → IFVG inversion → market at close.
These are different. The canonical model is higher-frequency and better documented.

### 2c. Frequency Reality Check

| Source | Frequency | Notes |
|---|---|---|
| ICT "One Setup for Life" | 1-3/week disciplined | ICT's own teaching |
| ICT Silver Bullet | 0-3/day (3 windows) | Time-boxed, often 0-1 quality |
| Automated Trading Strategies Substack | 0.28/day | 18 trades, 65 trading days, NQ algo |
| Reserve Flow H17v2 (morning sweep fade) | ~1/day | Simpler model than full ICT chain |
| Your bot (Jan 2023) | ~0.3/day | 13 signals, full month |
| Your bot (Jun 2023) | ~0.1/day | 1 signal, 2 weeks, strong trend |

**Target of 1-5/day requires either: multiple instruments, a different (simpler) model, or significantly loosened filters.**

### 2d. The Sequential Gate Problem

A 5-condition chain where each fires 70% of the time produces signals only 0.7^5 = **16.8%** of the time.

Your chain has 6+ sequential conditions at the IFVG stage alone. If each fires even 70%:
- 0.7^6 = 11.8% combined pass rate

This is the mathematical explanation of the 4% conversion rate. It's not one bad gate — it's the multiplicative effect of six gates stacked.

### 2e. 2023 Is the Worst Possible Test Year

NQ returned +56% in 2023 (best since 1999). ICT setups are **reversal setups** requiring two-directional price action. In a 56% trend year:
- Sweeps of lows continue lower 70-79% of the time rather than reversing
- Manipulation legs are short (price reverses quickly before a real FVG forms)
- Manipulation-leg FVGs are small → 2pt strong-close gate kills them

Testing on 2022 (NQ -33%) or range-bound periods gives a fundamentally different picture.

### 2f. The Overfitting Death Spiral

The bot has ~12 tunable parameters. Per López de Prado: need ~200 OOS trades per parameter to validate. At 12 parameters: **2,400 OOS trades needed**. Current: **13 in January 2023**.

Pattern: see bad backtest → add filter → better backtest → OOS fails → repeat. Each filter improves in-sample appearance while reducing trade count further. After 10 iterations: strategy fires 3x/month, looks perfect on 6 months, collapses on any other regime.

---

## PART 3: STATISTICAL EDGE FROM NQ-SPECIFIC RESEARCH

### 3a. NQStats.com — 10-Year Session Data (Free)

| Finding | Value | Implication |
|---|---|---|
| Probability of reversal at 09:00 first-segment sweep | **87.4%** | NY AM first sweep is highly likely to reverse |
| Days where both Asia sides swept | ~18% | Not the dominant pattern |
| When London sweeps Asia High → London continues higher | 70-79% | Continuation, not reversal |
| If Asia range present and London sweeps Asia High | 60% close bullish | Weak bias, not enough alone |

**87.4% at the NY 09:00 first-segment sweep** is the most actionable statistical finding. If NQ sweeps the 08:30-09:00 range high or low in the first 20 minutes of NY AM, there is an 87.4% historical reversion. This alone is a statistical edge worth building on.

### 3b. Herman Trading — 17-Year NQ Study (London-Asia Patterns)

From 4,262 trading days:
- **~66% of NQ days sweep the Asia high before 05:00 ET** (pre-London + London)
- If London sweeps Asia High → 60.54% chance day closes higher
- If London sweeps Asia Low → 53.13% chance day closes lower
- Average Asia session range since 2020: 78.45 NQ points

**Herman's core model**: Asia Probability Map outputs % probability of which side sweeps first, and % "Fail" (probability the sweep reverses). He only takes IFVG entries when the probability map agrees with direction. This is the correct HTF gate — probabilistic, session-based, not momentum-based.

### 3c. ALN Session Framework (NQStats)

| Pattern | Frequency | NY breaks London High | NY breaks London Low |
|---|---|---|---|
| P3: London breaks Asia High, holds Asia Low | **41%** (most common) | **80.8%** | 63% |
| P4: London breaks Asia Low, holds Asia High | 30.2% | lower | high |

P3 is the most common pattern. When London sweeps the Asia high and holds the Asia low, NY breaks the London high 80.8% of the time. This is a directional bias filter with real statistical backing.

---

## PART 4: WHAT OTHER IMPLEMENTATIONS DO (Key Comparisons)

### 4a. Turtle Soup — Sweep Definition is Looser

Turtle Soup (most backtested ICT sweep model, 60-81% WR on NQ in studies):
- Sweep: wick penetrates AND **body closes back inside within 1-3 bars** (not same-candle required)
- Your bot requires body closure on the **same candle** — stricter, misses valid setups

### 4b. DivergentTrades — Premium/Discount Zone Filter

Their "high probability" qualification requires:
- Bullish FVGs ONLY shown when price is in **discount** zone (below 50% midpoint of HTF range)
- Bearish FVGs ONLY shown when price is at **premium** (above 50% midpoint)

Your bot has no premium/discount check. This filter eliminates counter-structure entries.

### 4c. ICT Silver Bullet — Hard Time Windows

Fixed 1-hour windows:
- London: 03:00-04:00 ET
- NY AM: **10:00-11:00 ET** (most reliable for NQ)
- NY PM: 14:00-15:00 ET

Within each window: sweep → MSS → FVG limit entry at CE. No IFVG required. Claimed 60-80% WR, varies widely by year.

### 4d. MW Futures Liquidity Scalper (NQ/MNQ)

Uses NDOG/NWOG as directional bias filter. Your bot already tracks NDOG/NWOG for liquidity levels — could also use them as soft directional gates (price above NDOG midpoint → prefer shorts).

### 4e. Trader Kane Lab Model (Closest to Your Model 1)

NQ-specific, manual: 4H candle sweep of 10AM high/low + SMT divergence + IFVG on 1m/3m/5m. This is essentially Model 1 but with a hard time gate and mandatory SMT. Not automated. No published win rate.

### 4f. DodgysDD iFVG Model

Claims 85-88% WR on NQ IFVG setups. Sample: ~60 trades, hand-backtested, unverified. Entry: market at IFVG inversion close (same as your bot). Has active Discord community with backtesting channel.

---

## PART 5: KEY RESOURCES FOUND

### YouTube (Must-Watch)
| Video | URL | Why Important |
|---|---|---|
| 1000 ICT FVG Trades backtested | youtube.com/watch?v=OCZzP2H0Axg | Which FVG filters actually matter |
| Herman Channel (NQ/Python/IFVG) | youtube.com/channel/UCX9rbAtetyuJKiQISbGOcyw | Closest public analog, 10yr NQ |
| ICT Turtle Soup on NQ | youtube.com/watch?v=Xm-NxWAQHVU | Sweep reversal on NQ, 81% WR sample |
| Silver Bullet 5yr backtest ES | youtube.com/watch?v=KH7zA359mDA | Multi-year consistency data |
| DodgysDD iFVG backtest | youtube.com/watch?v=pEJwLyVZ8ng | 85% WR claim, closest to Model 1 |

### GitHub (Open Source)
| Repo | URL | Key Finding |
|---|---|---|
| joshyattridge/smart-money-concepts | github.com/joshyattridge/smart-money-concepts | Sweep = wick only (no body return). No IFVG. No gates. |
| starckyang/smc_quant | github.com/starckyang/smc_quant | 23% WR training, 50% WR live test, OB+FVG+BoS |
| martin254/Asian-Turtle-Soup | github.com/martin254/Asian-Turtle-Soup-Trading-Bot | Asian sweep → OB entry, QuantConnect |

### Critical: Look-Ahead Bias Warning
GitHub issue #101 on joshyattridge repo: with look-ahead bias in swing detection, WR = 81.4%, PF = 7.32. Without it: WR = 52.8%, PF = 1.82. Signal count drops 40%.

Your `SwingDetector(left=5, right=2)` uses confirmation delay — likely safe. Verify no look-ahead in aggregated TF data.

### Communities
| Community | URL | Notes |
|---|---|---|
| Platinum Trading SMC Discord | platinumsmc.com | ICT Futures (NQ/ES/GC/CL), <600 members |
| Automated Trading Strategies | automatedtradingstrategies.substack.com | NQ algo forward tests |
| Reserve Flow Analytics | reserveflowanalytics.substack.com | ES/NQ automation, Python-based |

### People to Follow
- [@_traderkane](https://x.com/_traderkane) — Lab Model, NQ IFVG practitioner
- [@DodgysDD](https://x.com/DodgysDD) — iFVG model, NQ/ES, Discord community
- [@R_Herman_](https://x.com/R_Herman_) — Herman Trading, NQ statistics

### Planning/Methodology Resources
| Resource | Type | Link |
|---|---|---|
| Kevin Davey "Building Winning Algo Systems" | Book | amazon.com/dp/1118778987 |
| Robert Carver "Systematic Trading" | Book (PDF free) | quant-wiki PDF |
| VectorBT Walk-Forward notebook | Free Python tool | github.com/polakowo/vectorbt |
| Build Alpha robustness guide | Free guide | buildalpha.com/robustness-testing-guide |
| Davey's Monkey Test | Free methodology | kjtradingsystems.com/ultimate-guide-to-algo-trading.html |
| ICT 2022 Checklist (Studocu) | PDF | studocu.com — ICT 2022 model checklist |
| Miro Decision Tree template | Free tool | miro.com/templates/decision-tree |

---

## PART 6: THE 20 PRE-CODE QUESTIONS (Compiled From Planning Research)

Every trading strategy must answer all of these before any code is written or changed:

**Edge & Hypothesis**
1. Why should this edge exist? What specific institutional behavior causes it?
2. Can it be explained without referencing backtest data?
3. Has the pattern been observed across multiple timeframes/instruments?

**Rule Completeness**
4. Can every condition be expressed as a binary YES/NO with specific numeric thresholds?
5. Is there any ambiguous word (significant, clean, strong, valid)?
6. What happens when conditions partially satisfy?

**Data**
7. Are timestamps exact, or is there any aggregation rounding that could introduce look-ahead?
8. Does any detection use future bars (centered windows)?

**Risk**
9. What is the exact SL formula?
10. What is the exact TP formula?
11. What is the position sizing formula?
12. What is maximum concurrent exposure?

**Validation**
13. What is the minimum acceptable profit factor? (Davey: beat 70% of random)
14. What is the maximum acceptable drawdown %?
15. What is the minimum trade count before conclusions are drawn? (≥100, preferably 200+)
16. What is the target Sharpe? (>1.0 minimum)

**Regime Sensitivity**
17. Does this strategy assume trending, ranging, or volatile markets?
18. How does it behave when that assumption is violated?
19. What specific market conditions break this strategy?
20. Has it been tested across at least 3 distinct regimes?

---

## PART 7: RECOMMENDED NEXT STEPS (Post-Ideation)

Based on research, in priority order:

### Step A — Run the Monkey Test
Before any filter changes: generate 1,000 random entry signals on the same NQ data for the same date windows. Compute the same P&L metrics. Verify the bot's 13 Jan 2023 signals beat ≥70% of random outcomes. If they don't — the core model has no mechanical edge and filter tuning is irrelevant.

### Step B — Run Rejection Counters
Add debug counters to `_try_model1` at each gate. Run June 2023 (trending market). Confirm which gate causes ~60% of rejections. The 2pt strong-close gate is the prime suspect but verify empirically.

### Step C — Test the Base Model
Strip all non-canonical gates. Run: sweep detected → any FVG on leg → any IFVG inversion (no speed/age/strong-close/all-must-invert/body-dominance). See the raw signal pool. This is the theoretical maximum.

### Step D — Fix RR Structure Before Win Rate
The math: at 1R TP, need 50% WR. Bot is at 31%. Even fixing filters won't get to 50%. Consider moving TP1 to 1.5R (breakeven = 40%) or 2R (breakeven = 33%). This is more achievable.

### Step E — Implement ALN Pattern Gate
Use NQStats P3 pattern (London sweeps Asia High) as the daily directional bias. When P3: prefer shorts in NY (fade London high sweep). When P4: prefer longs. This is a real statistical edge (41% of days, 80.8% NY continuation).

### Step F — Implement Premium/Discount Zone Check
Add entry price zone check relative to prior 4H range midpoint. Longs only in discount (price below midpoint), shorts only in premium (price above midpoint). This is the DivergentTrades approach and aligns with ICT's PD array concept.

---

## PART 8: WHERE TO CONDUCT THE IDEATION SESSION

**Recommendation: Stay in Claude Code (this session).**

Reasons:
1. Full codebase in context — when you answer a model question, I can cross-reference against the 16-gate pipeline immediately
2. GitHub commits after each decision — documented and persistent
3. No need to re-paste CLAUDE.md or explain the 23-sweep/1-signal finding
4. Can reference line numbers and exact gate code
5. Research document is in the repo — both sessions can share it

The only argument for regular Claude chat: a completely clean slate for first-principles thinking, no implementation bias. But given that your problems are implementation-specific, this context is an advantage, not a constraint.
