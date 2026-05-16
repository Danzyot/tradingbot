# Research Session — 2026-05-16
## Pre-Ideation Deep Dive: ICT/SMC Trading Bot Planning

---

## What Was Researched

10 parallel agents covering: YouTube, Reddit/forums, GitHub, X/Twitter, ICT rule definitions, NQ statistics, open-source codebases, planning methodology, codebase audit.

---

## 1. Hard Findings — What the Research Confirms

### 1a. The Math Problem (Critical)

At 1:1 R:R (current TP1 = 1R), breakeven win rate is **50%**. Bot is at **31%** in Jan 2023.

That is 19 percentage points below breakeven. This is **not a parameter-tuning problem**. Even if filters were perfect, at 1R you need half your trades to win. No amount of filter adjustment fixes a 19-point structural gap — you need either a higher win rate entry model OR a higher RR target.

The best independently verified SMC backtest found (2,600 trades across 10 assets) achieved **61% WR at multi-R targets** (2.17 profit factor). This is the realistic ceiling, not a floor.

### 1b. The Model Confusion Problem (Critical)

The bot's current **Model 1** (manipulation-leg FVG → IFVG inversion at market) is **NOT the canonical ICT 2022 model**. It is a harder, less-described variant.

The **canonical ICT 2022 "One Setup for Life"** is:
1. Sweep liquidity
2. Price displaces → leaves a **displacement FVG** on the reversal leg
3. Price **retests** back into that displacement FVG
4. **Limit order** at CE (50% of FVG) — SL beyond swept extreme

Your bot does:
1. Sweep liquidity
2. Find FVGs that formed **on the manipulation leg** (before/during the sweep move)
3. Wait for a later candle to **body-close beyond** the far edge of one of those FVGs (inversion)
4. **Market order** at inversion candle close

These are different entries. The canonical model is a FVG *retest* (limit). Your model is a manipulation-leg FVG *inversion* (market). The canonical model is simpler, higher frequency, and better documented.

### 1c. The "All FVGs Must Invert" Rule Is Invented (Critical)

The rule that **all FVGs on the leg of the highest TF must invert** before entry is **not in canonical ICT**. ICT IFVG fires on the FIRST qualifying FVG inversion. Your bot requires every FVG of the highest TF to invert first, meaning the trade signal only fires on the LAST one. This is a self-imposed restriction with no ICT basis and likely responsible for 10-20% of all signal rejections on top of everything else.

### 1d. The Overfitting Death Spiral

The bot currently has approximately **12 tunable parameters** (ATR gates, age gate, body dominance threshold, speed gate bars, displacement window, EQH tolerance, strong-close threshold, min RR, leg size threshold, body return threshold, pin-bar ratio, swing left/right). Per López de Prado's rule, you need ~200 OOS trades per parameter to validate statistically. At 12 parameters: **2,400 OOS trades needed**. Available: **13 in January 2023**.

Every fix added to the bot improved backtest performance on a 6-month window while the OOS data was never held out. This is the textbook overfitting death spiral.

### 1e. 2023 Is the Worst Possible Test Year

NQ returned **+56% in 2023** — best year since 1999. This was nearly pure AI-driven trend with minimal reversals. ICT setups are **reversal setups by design** — they require two-directional price action with liquidity building on both sides. In a strong uptrend, sweeps of lows tend to continue lower 70-79% of the time rather than reverse. The body-close-back-inside requirement correctly rejects these, but there is almost nothing left to trade. The Jun 2023 data (23 sweeps → 1 IFVG signal) is not a bug — it is what a strict reversal model does in a 56% trend year.

Testing on 2022 (NQ -33%, strong bear with swing structure) or range-bound periods would give a completely different picture.

### 1f. The Frequency Target Is Miscalibrated

ICT himself named this "One Trade Setup for Life" and "One Shot One Kill." His recommended cadence is **1-2 quality setups per session**. The most aggressive documented claim is 2-3 per day in good conditions, with serious practitioners targeting 1-3 per **week** in disciplined application.

The 1-5 trades/day target is 5-35x higher than what the 2022 model is designed to produce. Hitting 1-5/day would require either: multiple correlated instruments, a different model (scalping/session model), or significantly loosened qualification chains — each of which trades quality for quantity.

---

## 2. The 16 Gates (Full Pipeline Map)

Every condition a potential signal must pass from raw candle to journal entry:

| # | Gate | Threshold | Adaptive? |
|---|---|---|---|
| 1a | Session killzone | 5 fixed ET windows | No |
| 1b | News blackout | 30min pre / 15min post USD High | No |
| 2a | Level tier | S/A/B only | No |
| 2b | Level direction | Must match kind | No |
| 2c | Already-swept | Binary flag | No |
| 2d | Single-candle grab | wick through + body back | No |
| 2e | Multi-candle sweep fallback | prior closed beyond, current back | No |
| 3a | Wick depth | max(3, atr14 × 0.15-0.20) | YES |
| 3b | Pin-bar shape | wick ≥ 20% of range | No |
| 3c | Body return | max(1, atr14 × 0.05) | YES |
| 4 | Leg significance | max(10, atr14 × 0.80) | YES |
| 5 | 90-min leg cap | Hard 90-min lookback | No |
| 6 | Leg FVGs exist | At least one | No |
| 7a | Sweep cooldown | 5 min per level | No |
| 7b | Consumed levels | Permanent block | No |
| 8 | HTF alignment | DISABLED | — |
| 9 | Displacement | max(3, atr14 × 0.30) body, 30 bars | YES |
| 10 | Re-sweep invalidation | 5pt zone | No |
| 11 | HTF open block | 5 windows, 5min pre-open | No |
| 12a | TF priority | [5,4,3,2,1] min | No |
| 12b | Speed gate | ≤4 bars from first touch | No |
| 12c | Age gate | TF × 8 min | YES |
| 12d | All FVGs must invert | Binary per FVG | No |
| 12e | Inversion detection | Body close past far edge + open in zone | No |
| 13a | Body dominance | ≥50% of range | No |
| 13b | Strong close | ≥2pt beyond far edge | No |
| 14 | Sweep-to-entry cap | ≤60 min | No |
| 15 | Leg extreme retroactive | Rescan for true wick | No |
| 16 | Min RR | ≥1.0 | No |

### Estimated June 2023 Rejection Breakdown (23 sweeps → 1 signal)
- Gate 13b (2pt strong close): ~60% of rejections
- Gates 12b/12c (speed + age): ~18%
- Gate 9 (displacement): ~12%
- Gate 12d (all must invert): ~8%
- Gate 16 (RR): ~2%

### Key Conflicts Identified
1. **FVG collection window vs age gate**: FVGs collected within 90min of sweep, but 5m FVG age limit is 40min. A 5m FVG that forms at sweep+5min expires at sweep+45min. If inversion happens at sweep+50min → expired. Gate 6 passes but gate 12c blocks.
2. **Gates 12b + 12c**: Both filter slow/stale FVGs. Overlap ~30%. Complementary but stack multiplicatively.

---

## 3. What Other Implementations Do

### Canonical sources reviewed:
- **DivergentTrades (TradingView)**: Sweep → MSS → displacement FVG/IFVG. Entry at first FVG after MSS. No "all must invert" rule.
- **automated-trading.ch (NinjaTrader)**: MSS + BOS entry. Broader entry trigger than IFVG. Higher signal frequency by design.
- **Martin254 Asian Turtle Soup Bot (QuantConnect)**: Sweep of Asian range → OB entry. Simpler chain, higher frequency.
- **Farnam Rami (Python)**: ICT 2022 model, `smartmoneyconcepts` library, London sessions only. Accepts all sweeps, enters on first FVG touch. No multi-gate qualification chain.

**Consensus across implementations**: 
- Entry at FIRST qualifying FVG, not last
- No speed/age gates in most implementations
- No "all must invert" rule anywhere
- Most implementations use displacement FVG (after sweep), not manipulation-leg FVG (before sweep)

---

## 4. Resources Worth Studying

### YouTube
- [I Backtested 1000 ICT FVG Trades](https://www.youtube.com/watch?v=OCZzP2H0Axg) — which FVG filters actually matter
- [Herman Channel (NQ/Python/IFVG)](https://www.youtube.com/channel/UCX9rbAtetyuJKiQISbGOcyw/videos) — closest public analog, 10yr Python NQ backtest
- [ICT Turtle Soup on NQ](https://www.youtube.com/watch?v=Xm-NxWAQHVU) — sweep reversal model specifically on NQ
- [Backtesting IFVG Strategy](https://www.youtube.com/watch?v=atl9FhiS48c) — IFVG model results

### GitHub
- [joshyattridge/smart-money-concepts](https://github.com/joshyattridge/smart-money-concepts) — Python SMC library (compare FVG detection)
- [kulaizki/swch-bot](https://github.com/kulaizki/swch-bot) — sweep + ChoCH entry chain
- [martin254/Asian-Turtle-Soup-Trading-Bot](https://github.com/martin254/Asian-Turtle-Soup-Trading-Bot) — sweep reversal on QuantConnect

### Commercial (NQ/ES specific)
- [automated-trading.ch ICT Concepts NT8](https://automated-trading.ch/NT8/strategies/ict-concepts-strategy) — NQ/ES bot with published 2024-2025 backtest

### Communities
- [Platinum Trading SMC Discord](https://platinumsmc.com/) — ICT futures focus (NQ/ES/GC/CL)
- [Automated Trading Strategies Substack](https://automatedtradingstrategies.substack.com) — NQ algo, forward test results

### Books (planning/methodology)
- **Kevin Davey** — "Building Winning Algorithmic Trading Systems" (best for planning process)
- **Robert Carver** — "Systematic Trading" (Appendix B = rule specification template)
- **Ernie Chan** — "Algorithmic Trading: Winning Strategies and Their Rationale"
- **López de Prado** — "Advances in Financial Machine Learning" (overfitting detection)

---

## 5. The Open Questions (Ideation Session Starting Points)

1. **Which model do you actually want?** Manipulation-leg IFVG (current, harder, non-canonical) or displacement FVG retest (canonical 2022, higher frequency, limit orders)?
2. **What win rate is acceptable at what frequency?** 60% WR × 1 trade/week, or 45% WR × 3 trades/week, or something else?
3. **RR target**: Are you committed to 1R TP1, or would 1.5R-2R with partial closes make the math work?
4. **The "all FVGs must invert" rule**: Keep it (strict quality) or replace with "first qualifying FVG inversion" (canonical, more signals)?
5. **Test regime**: Commit to testing on a range-bound or bear market period first (2022 data exists) before drawing conclusions from 2023?
6. **The daily bias gate (Step 9)**: Is the correct implementation the blocker before any other work?
