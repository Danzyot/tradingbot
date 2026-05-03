"""
Liquidity level mapping.

Levels tracked (by DOL tier):
  S: Perfect EQH/EQL (3+ candles apart), data high/low with massive wick
  A: Perfect EQH/EQL (1-3 candles apart), unmitigated imbalances (HTF FVGs)
  B: H/L inside FVG, NWOG/NDOG, session H/L, REQL/REQH
  C: Order blocks (future)
  F: H/L that took out another H/L inside FVG → IGNORED

The bot only acts on S/A/B tiers.
"""
from __future__ import annotations
from datetime import datetime, date, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from ..data.candle import Candle
from .swing import SwingPoint, SwingType
from .sweep import LiquidityLevel, LiqTier


# ── Equal Highs / Equal Lows ─────────────────────────────────────────────────

def detect_eqhl(
    swing_points: list[SwingPoint],
    tolerance_pts: float = 1.0,  # 4 ticks — NQ equal highs/lows are rarely perfectly flat; 1pt catches real clustering
) -> list[LiquidityLevel]:
    """
    Group swing points within tolerance_pts of each other.
    Tier rules match the ICT tier list exactly:
      S = 3+ touches (any gap), OR 2 touches > 3 candles apart
      A = 2 touches, 1–3 candles apart
      Skip: same bar or only 1 touch

    Fixed-point tolerance (not percentage) — at NQ ~20k, 0.05% = 10pts which is too wide.
    Old 0.25pt (1 tick) was too tight — misses 2-4 tick apart equal levels that are
    visually and structurally equal in NQ price action.
    """
    levels: list[LiquidityLevel] = []

    highs = [p for p in swing_points if p.kind == SwingType.HIGH]
    lows  = [p for p in swing_points if p.kind == SwingType.LOW]

    levels.extend(_group_equal(highs, tolerance_pts, "eqh"))
    levels.extend(_group_equal(lows,  tolerance_pts, "eql"))
    return levels


def _group_equal(
    points: list[SwingPoint],
    tol_pts: float,
    kind: str,
) -> list[LiquidityLevel]:
    """
    Group swing points within tol_pts of each other using transitive sequential clustering.

    Sort by price first so that consecutive comparisons are always between adjacent
    prices — this guarantees transitivity: if A≈B and B≈C then A,B,C all land in one
    cluster rather than splitting at the first-vs-last distance.

    Old approach compared each new point only against the GROUP'S FIRST point, which
    caused [100.0, 100.6, 1.2] to group 100.0+100.6 correctly but miss 100.6+1.2 if
    |100.0 - 1.2| > tol, even though they're adjacent within tolerance.
    """
    if not points:
        return []

    sorted_pts = sorted(points, key=lambda p: p.price)
    groups: list[list[SwingPoint]] = []
    current: list[SwingPoint] = [sorted_pts[0]]

    for p in sorted_pts[1:]:
        if abs(p.price - current[-1].price) <= tol_pts:
            current.append(p)
        else:
            groups.append(current)
            current = [p]
    groups.append(current)

    levels = []
    for group in groups:
        if len(group) < 2:
            continue
        # Use min/max candle_index — after price-sort, chronological order is arbitrary
        min_idx = min(p.candle_index for p in group)
        max_idx = max(p.candle_index for p in group)
        candle_gap = max_idx - min_idx
        if candle_gap == 0:
            continue   # same bar — skip

        if len(group) >= 3:
            tier = LiqTier.S
        elif candle_gap > 3:
            tier = LiqTier.S   # perfect EQH/EQL — well separated
        elif 1 <= candle_gap <= 3:
            tier = LiqTier.A   # close but still a double-tap
        else:
            continue

        avg_price = sum(p.price for p in group) / len(group)
        earliest = min(group, key=lambda p: p.candle_index)
        levels.append(LiquidityLevel(
            price=avg_price,
            tier=tier,
            kind=kind,
            ts=earliest.ts,
        ))
    return levels


# ── Individual Swing High/Low as Liquidity Levels ────────────────────────────

def detect_swing_levels(
    swing_points: list[SwingPoint],
    candles: list[Candle],
    min_wick_pts: float = 15.0,   # only major structural pivots — 5pt was picking up random local highs
    wick_s_tier_multiplier: float = 2.0,
) -> list[LiquidityLevel]:
    """
    Individual major swing highs/lows as sweep targets, classified by wick size.

    S-tier ("data high/low with massive wick"): wick >= 2x average wick — these are
    prominent stop-hunt candles; institutions already hit stops here, making them
    magnets for future sweeps.
    B-tier: notable swing with wick >= min_wick_pts but below S threshold.
    Skip: swings with tiny wicks (micro pivots, not real levels).

    Only the last 20 swing points are used — older levels are less relevant.
    """
    if not swing_points or not candles:
        return []

    # Compute average wick size from recent candles for context
    recent = candles[-50:] if len(candles) >= 50 else candles
    avg_wick = sum(
        max(c.high - max(c.open, c.close), min(c.open, c.close) - c.low)
        for c in recent
    ) / len(recent)

    levels: list[LiquidityLevel] = []
    candle_by_ts = {c.ts: c for c in candles}

    for sp in swing_points[-20:]:
        c = candle_by_ts.get(sp.ts)
        if c is None:
            continue

        if sp.kind == SwingType.HIGH:
            wick = c.high - max(c.open, c.close)   # upper wick
            if wick < min_wick_pts:
                continue
            tier = LiqTier.S if wick >= avg_wick * wick_s_tier_multiplier else LiqTier.B
            levels.append(LiquidityLevel(price=c.high, tier=tier, kind="swing_high", ts=sp.ts))
        else:
            wick = min(c.open, c.close) - c.low    # lower wick
            if wick < min_wick_pts:
                continue
            tier = LiqTier.S if wick >= avg_wick * wick_s_tier_multiplier else LiqTier.B
            levels.append(LiquidityLevel(price=c.low, tier=tier, kind="swing_low", ts=sp.ts))

    return levels


# ── Session High/Low ─────────────────────────────────────────────────────────

def detect_session_levels(
    candles: list[Candle],
    session_name: str,
    session_start: time,
    session_end: time,
    max_sessions: int = 5,  # how many prior sessions to track as sweep targets
) -> list[LiquidityLevel]:
    """
    Extract high and low of the most recent N occurrences of a session.
    Tracks multiple past sessions — price can sweep any prior unswept session H/L.
    Asia crosses midnight so we group by session date.
    """
    ET = ZoneInfo("America/New_York")

    def _in(t: time) -> bool:
        if session_end == time(0, 0):   # midnight boundary
            return t >= session_start
        return session_start <= t < session_end

    session_candles_all = [c for c in candles if _in(c.ts.astimezone(ET).time())]
    if not session_candles_all:
        return []

    # Group by date in ET
    def _session_date(c: Candle) -> date:
        et = c.ts.astimezone(ET)
        if session_end == time(0, 0) and et.time() < session_start:
            return (et - timedelta(days=1)).date()
        return et.date()

    by_date: dict[date, list[Candle]] = {}
    for c in session_candles_all:
        d = _session_date(c)
        by_date.setdefault(d, []).append(c)

    # Most recent N sessions (sorted descending, skip incomplete current session)
    all_dates = sorted(by_date.keys(), reverse=True)
    levels: list[LiquidityLevel] = []
    for d in all_dates[:max_sessions]:
        sess = by_date[d]
        sh = max(sess, key=lambda c: c.high)
        sl = min(sess, key=lambda c: c.low)
        levels.append(LiquidityLevel(price=sh.high, tier=LiqTier.B,
                                     kind=f"{session_name}_high", ts=sh.ts))
        levels.append(LiquidityLevel(price=sl.low,  tier=LiqTier.B,
                                     kind=f"{session_name}_low",  ts=sl.ts))
    return levels


# ── Previous Day High/Low ─────────────────────────────────────────────────────

def detect_pdhl(candles: list[Candle], today: date, lookback_days: int = 5) -> list[LiquidityLevel]:
    """PDH and PDL from the previous N trading days (ET). All are valid sweep targets."""
    prev_candles = [c for c in candles if c.ts.date() < today]
    if not prev_candles:
        return []

    all_prev_dates = sorted({c.ts.date() for c in prev_candles}, reverse=True)
    levels: list[LiquidityLevel] = []
    for d in all_prev_dates[:lookback_days]:
        day_candles = [c for c in prev_candles if c.ts.date() == d]
        pdh = max(day_candles, key=lambda c: c.high)
        pdl = min(day_candles, key=lambda c: c.low)
        # A-tier: PDH/PDL are significant daily structure — same importance as EQH/EQL 2-touch
        levels.append(LiquidityLevel(price=pdh.high, tier=LiqTier.A, kind="pdh", ts=pdh.ts))
        levels.append(LiquidityLevel(price=pdl.low,  tier=LiqTier.A, kind="pdl", ts=pdl.ts))
    return levels


# ── NWOG / NDOG ───────────────────────────────────────────────────────────────

def _opening_gap_levels(
    price_a: float,
    price_b: float,
    ts: datetime,
    kind_prefix: str,
    min_gap_pts: float,
) -> list[LiquidityLevel]:
    """
    Shared helper for NDOG and NWOG: returns a high/low level pair when the
    gap between two prices exceeds min_gap_pts, otherwise an empty list.
    """
    if abs(price_a - price_b) < min_gap_pts:
        return []
    top    = max(price_a, price_b)
    bottom = min(price_a, price_b)
    return [
        LiquidityLevel(price=top,    tier=LiqTier.B, kind=f"{kind_prefix}_high", ts=ts),
        LiquidityLevel(price=bottom, tier=LiqTier.B, kind=f"{kind_prefix}_low",  ts=ts),
    ]


def detect_ndog(
    prev_day_close: float,
    current_day_open: float,
    ts: datetime,
    min_gap_pts: float = 2.0,  # skip micro-gaps — CoWork: TFO shows single line when no real gap
) -> list[LiquidityLevel]:
    """New Day Opening Gap: gap between previous day close and today's open."""
    return _opening_gap_levels(prev_day_close, current_day_open, ts, "ndog", min_gap_pts)


def detect_nwog(
    friday_close: float,
    sunday_open: float,
    ts: datetime,
    min_gap_pts: float = 2.0,  # skip micro-gaps — same rule as NDOG
) -> list[LiquidityLevel]:
    """New Week Opening Gap: gap between Friday close and Sunday open."""
    return _opening_gap_levels(friday_close, sunday_open, ts, "nwog", min_gap_pts)


# ── FVG as Liquidity Level ─────────────────────────────────────────────────────

def fvg_as_liquidity(fvg_top: float, fvg_bottom: float, ts: datetime, tf: int = 60) -> list[LiquidityLevel]:
    """
    Unmitigated HTF FVG edges as liquidity sweep targets.
    1H (60m) and 4H (240m) = A-tier (significant imbalances).
    15m and 30m = B-tier (useful but less powerful).
    kind includes the TF for clear labelling: e.g. "60m_fvg_high".
    """
    tier = LiqTier.A if tf >= 60 else LiqTier.B
    kind_suffix = f"{tf}m_fvg"
    return [
        LiquidityLevel(price=fvg_top,    tier=tier, kind=f"{kind_suffix}_high", ts=ts),
        LiquidityLevel(price=fvg_bottom, tier=tier, kind=f"{kind_suffix}_low",  ts=ts),
    ]
