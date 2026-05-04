"""
Scan historical data for quality manipulation sweeps + swing points.
Outputs JSON consumed by visualize_legs.py for visual verification.

Quality sweeps = wick-penetration + leg-significance gates (no IFVG required).
Swing points use a 5m/left=5/right=2 window for visual clarity.

Usage:
    python run_legs_scan.py
"""
import sys, json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, "src")

from smc_bot.data.history import load_csv
from smc_bot.data.aggregator import MultiTFAggregator
from smc_bot.detectors.fvg import FVGTracker
from smc_bot.detectors.swing import SwingDetector
from smc_bot.detectors.liquidity import (
    detect_eqhl, detect_swing_levels, detect_session_levels,
    detect_pdhl, detect_ndog, fvg_as_liquidity,
)
from smc_bot.detectors.sweep import LiqTier
from smc_bot.filters.session import SESSIONS
from smc_bot.models.confluence import ConfluenceEngine
from smc_bot.engine.backtest import (
    TFS, EQL_SWING_LEFT, EQL_SWING_RIGHT, LTF_SWING_LEFT, LTF_SWING_RIGHT,
    MIN_FVG_SIZE, LTF_FVG_MIN_SIZE, MAX_FVG_LEVELS_PER_TF,
)

DATE_FROM = "2023-01-02"
DATE_TO   = "2023-01-31"
MNQ_CSV   = Path("data/nq_1m.csv")
OUTPUT    = Path("data/legs_scan.json")

# Swing parameters for 5m visualization (lighter than the structural left=20/right=5)
SWING_VIZ_LEFT  = 5
SWING_VIZ_RIGHT = 2


def run_scan(
    mnq_csv: Path = MNQ_CSV,
    date_from: str = DATE_FROM,
    date_to: str = DATE_TO,
    output: Path = OUTPUT,
) -> None:
    candles = load_csv(mnq_csv, timeframe=1)
    if date_from:
        dt_from = datetime.fromisoformat(date_from).replace(tzinfo=timezone.utc)
        candles = [c for c in candles if c.ts >= dt_from]
    if date_to:
        dt_to = datetime.fromisoformat(date_to).replace(tzinfo=timezone.utc)
        candles = [c for c in candles if c.ts <= dt_to]

    date_range = f"{candles[0].ts.strftime('%Y-%m-%d')} to {candles[-1].ts.strftime('%Y-%m-%d')}" if candles else "?"
    print(f"Loaded {len(candles)} bars ({date_range})")

    fvg_trackers = {
        tf: FVGTracker(
            timeframe=tf,
            inversion_window=30 if tf < 15 else 0,
            min_size=LTF_FVG_MIN_SIZE.get(tf, 0.0),
        )
        for tf in TFS
    }
    swing_ltf = SwingDetector(left=LTF_SWING_LEFT, right=LTF_SWING_RIGHT)
    swing_15m = SwingDetector(left=EQL_SWING_LEFT, right=EQL_SWING_RIGHT)
    swing_viz = SwingDetector(left=SWING_VIZ_LEFT, right=SWING_VIZ_RIGHT)

    aggregator = MultiTFAggregator(timeframes=TFS)
    engine = ConfluenceEngine(
        fvg_trackers=fvg_trackers,
        swing_detector=swing_ltf,
        min_rr=1.0,
    )

    all_sweeps: list[dict] = []
    all_swings: list[dict] = []
    seen_swing_ts: set[str] = set()
    prev_5m_count = 0

    ET = ZoneInfo("America/New_York")

    for i, candle in enumerate(candles):
        aggregator.push(candle)
        candles_by_tf = {tf: aggregator.get(tf).as_list() for tf in TFS}
        for tf, cs in candles_by_tf.items():
            if cs:
                fvg_trackers[tf].update(cs)

        ltf_candles = candles_by_tf.get(1, [])
        candles_15m = candles_by_tf.get(15, [])
        candles_5m  = candles_by_tf.get(5, [])

        # Build levels (identical to run_backtest)
        levels = []
        swings_15m = swing_15m.detect(candles_15m) if len(candles_15m) >= 10 else []
        levels.extend(detect_eqhl(swings_15m))
        levels.extend(detect_swing_levels(swings_15m, candles_15m))
        if len(ltf_candles) >= 60:
            MAJOR_SESSIONS = {k: v for k, v in SESSIONS.items() if k != "ny_lunch"}
            for sess_name, (sess_start, sess_end) in MAJOR_SESSIONS.items():
                levels.extend(detect_session_levels(ltf_candles, sess_name, sess_start, sess_end))
            levels.extend(detect_pdhl(ltf_candles, candle.ts.date()))
            today_et = candle.ts.astimezone(ET).date()
            today_c = [c for c in ltf_candles if c.ts.astimezone(ET).date() == today_et]
            prev_c  = [c for c in ltf_candles if c.ts.astimezone(ET).date() < today_et]
            if today_c and prev_c:
                levels.extend(detect_ndog(prev_c[-1].close, today_c[0].open, today_c[0].ts))
        for tf in [30, 60, 240]:
            min_size = MIN_FVG_SIZE.get(tf, 5.0)
            candidates = [
                f for f in fvg_trackers[tf].active
                if not f.mitigated and f.size >= min_size
            ]
            for fvg in sorted(candidates, key=lambda f: f.ts, reverse=True)[:MAX_FVG_LEVELS_PER_TF]:
                levels.extend(fvg_as_liquidity(fvg.top, fvg.bottom, fvg.ts, tf=tf))

        TIER_RANK = {LiqTier.S: 0, LiqTier.A: 1, LiqTier.B: 2, LiqTier.C: 3, LiqTier.F: 4}
        seen_prices: dict[float, object] = {}
        for lvl in levels:
            p = round(lvl.price, 2)
            if p not in seen_prices:
                seen_prices[p] = lvl
            else:
                existing = seen_prices[p]
                if TIER_RANK[lvl.tier] < TIER_RANK[existing.tier]:
                    seen_prices[p] = lvl
                elif TIER_RANK[lvl.tier] == TIER_RANK[existing.tier] and lvl.ts > existing.ts:
                    seen_prices[p] = lvl
        levels = list(seen_prices.values())

        engine.set_liquidity_levels(levels)
        swings_nq = swing_ltf.detect(ltf_candles) if len(ltf_candles) >= 10 else []
        engine.update(candle=candle, candles_by_tf=candles_by_tf, swings_nq=swings_nq)

        # Capture quality sweeps from this candle
        for sweep in engine._last_quality_sweeps:
            leg_start = sweep.leg_start_ts.isoformat() if sweep.leg_start_ts else None
            leg_ext_ts = sweep.leg_extreme_candle.ts.isoformat() if sweep.leg_extreme_candle else None
            if sweep.leg_extreme_candle:
                leg_ext_price = (
                    sweep.leg_extreme_candle.low
                    if sweep.direction.value == "bullish"
                    else sweep.leg_extreme_candle.high
                )
            else:
                leg_ext_price = None

            all_sweeps.append({
                "sweep_ts": sweep.ts.isoformat(),
                "direction": sweep.direction.value,
                "level_price": sweep.level.price,
                "level_kind": sweep.level.kind,
                "level_tier": sweep.level.tier.value,
                "leg_start_ts": leg_start,
                "leg_extreme_ts": leg_ext_ts,
                "leg_extreme_price": leg_ext_price,
            })

        # Detect 5m swings only when a new 5m candle closes (efficiency)
        if len(candles_5m) > prev_5m_count:
            prev_5m_count = len(candles_5m)
            min_bars = SWING_VIZ_LEFT + SWING_VIZ_RIGHT + 1
            if len(candles_5m) >= min_bars:
                for s in swing_viz.detect(candles_5m):
                    key = s.ts.isoformat()
                    if key not in seen_swing_ts:
                        seen_swing_ts.add(key)
                        all_swings.append({
                            "ts": key,
                            "price": s.price,
                            "kind": s.kind.value,
                            "tf": 5,
                        })

        if i % 1000 == 0:
            print(f"  [{i+1}/{len(candles)}] {candle.ts.strftime('%Y-%m-%d %H:%M')} | "
                  f"{len(all_sweeps)} sweeps | {len(all_swings)} swings")

    result = {"sweeps": all_sweeps, "swings": all_swings, "date_from": date_from, "date_to": date_to}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2))
    print(f"\nDone: {len(all_sweeps)} quality sweeps, {len(all_swings)} 5m swing points -> {output}")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--from", dest="date_from", default=DATE_FROM)
    p.add_argument("--to",   dest="date_to",   default=DATE_TO)
    p.add_argument("--csv",  type=Path,         default=MNQ_CSV)
    p.add_argument("--out",  type=Path,         default=OUTPUT)
    args = p.parse_args()
    run_scan(mnq_csv=args.csv, date_from=args.date_from, date_to=args.date_to, output=args.out)
