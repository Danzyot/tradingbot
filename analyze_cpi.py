"""
CPI Event Impact Analysis on NQ 1m data.

For each CPI release (8:30am ET):
- Manipulation leg: initial spike in first 5 min (open to extreme)
- Distribution leg: subsequent directional move (extreme to 30min/60min later)

Usage: python analyze_cpi.py
"""
import sys
from pathlib import Path
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, "src")
from smc_bot.data.history import load_csv

ET = ZoneInfo("America/New_York")

# ── CPI release dates (8:30am ET) ────────────────────────────────────────────
# US CPI (Consumer Price Index) released by BLS
CPI_DATES = [
    # 2024
    "2024-01-11", "2024-02-13", "2024-03-12", "2024-04-10",
    "2024-05-15", "2024-06-12", "2024-07-11", "2024-08-14",
    "2024-09-11", "2024-10-10", "2024-11-13", "2024-12-11",
    # 2025
    "2025-01-15", "2025-02-12", "2025-03-12", "2025-04-10",
    "2025-05-13", "2025-06-11", "2025-07-15", "2025-08-12",
    "2025-09-10", "2025-10-15", "2025-11-12", "2025-12-10",
    # 2026
    "2026-01-14", "2026-02-12", "2026-03-12",
    # 2026-04-10 (today) may not have full data yet
]

def load_nq_indexed(csv_path: Path) -> dict[datetime, object]:
    """Load NQ 1m candles indexed by UTC timestamp."""
    candles = load_csv(csv_path, timeframe=1)
    return {c.ts: c for c in candles}


def get_candle_at_or_after(index: dict, target_utc: datetime, window_min: int = 2):
    """Find the first candle at or after target_utc within window_min minutes."""
    for delta in range(window_min + 1):
        ts = target_utc + timedelta(minutes=delta)
        if ts in index:
            return index[ts]
    return None


def analyze_cpi_event(date_str: str, index: dict) -> dict | None:
    """
    Analyze one CPI event.

    Returns dict with:
      - date: event date
      - pre_close: NQ close at 8:29am ET (last pre-release print)
      - manip_high: highest NQ in 8:30-8:35am window
      - manip_low:  lowest  NQ in 8:30-8:35am window
      - manip_direction: "up" or "down" (initial spike direction)
      - manip_pts: magnitude of initial spike (points)
      - dist_price_30m: NQ close at ~9:00am ET (30m after release)
      - dist_pts_30m: move from manip extreme to 9:00am close
      - dist_price_60m: NQ close at ~9:30am ET
      - dist_pts_60m: move from manip extreme to 9:30am close
      - dist_direction: did distribution go WITH or AGAINST manipulation?
    """
    dt_et = datetime.strptime(date_str, "%Y-%m-%d")

    # Build UTC timestamps for key moments
    def et_to_utc(h, m) -> datetime:
        local = dt_et.replace(hour=h, minute=m, tzinfo=ET)
        return local.astimezone(ZoneInfo("UTC")).replace(second=0, microsecond=0)

    pre_release_utc   = et_to_utc(8, 29)   # last print before CPI
    release_utc       = et_to_utc(8, 30)   # CPI drops
    manip_end_utc     = et_to_utc(8, 35)   # 5-min manipulation window end
    dist_30m_utc      = et_to_utc(9,  0)   # 30m post-release
    dist_60m_utc      = et_to_utc(9, 30)   # 60m post-release

    # Pre-release price
    pre_candle = get_candle_at_or_after(index, pre_release_utc)
    if not pre_candle:
        return None
    pre_close = pre_candle.close

    # Gather candles in 8:30-8:35 window (manipulation leg)
    manip_candles = []
    ts = release_utc
    while ts <= manip_end_utc:
        if ts in index:
            manip_candles.append(index[ts])
        ts += timedelta(minutes=1)

    if not manip_candles:
        return None

    manip_high = max(c.high for c in manip_candles)
    manip_low  = min(c.low  for c in manip_candles)

    # Determine manipulation direction: which extreme was hit first
    first_candle = manip_candles[0]
    # Compare first candle's move relative to pre_close
    up_move   = manip_high - pre_close
    down_move = pre_close - manip_low

    if up_move >= down_move:
        manip_direction = "up"
        manip_extreme   = manip_high
        manip_pts       = round(up_move, 2)
    else:
        manip_direction = "down"
        manip_extreme   = manip_low
        manip_pts       = round(down_move, 2)

    # Distribution leg: price at 30m and 60m after release
    candle_30m = get_candle_at_or_after(index, dist_30m_utc)
    candle_60m = get_candle_at_or_after(index, dist_60m_utc)

    dist_pts_30m = None
    dist_dir_30m = None
    if candle_30m:
        dist_pts_30m = round(candle_30m.close - manip_extreme, 2)
        dist_dir_30m = "against" if (manip_direction == "up" and dist_pts_30m < 0) or \
                                    (manip_direction == "down" and dist_pts_30m > 0) else "with"

    dist_pts_60m = None
    dist_dir_60m = None
    if candle_60m:
        dist_pts_60m = round(candle_60m.close - manip_extreme, 2)
        dist_dir_60m = "against" if (manip_direction == "up" and dist_pts_60m < 0) or \
                                    (manip_direction == "down" and dist_pts_60m > 0) else "with"

    return {
        "date":           date_str,
        "pre_close":      round(pre_close, 2),
        "manip_direction": manip_direction,
        "manip_pts":      manip_pts,
        "manip_high":     round(manip_high, 2),
        "manip_low":      round(manip_low, 2),
        "dist_price_30m": round(candle_30m.close, 2) if candle_30m else None,
        "dist_pts_30m":   dist_pts_30m,
        "dist_dir_30m":   dist_dir_30m,
        "dist_price_60m": round(candle_60m.close, 2) if candle_60m else None,
        "dist_pts_60m":   dist_pts_60m,
        "dist_dir_60m":   dist_dir_60m,
    }


def main():
    csv_path = Path(r"C:\Users\yotda\tradingbot\data\nq_1m.csv")
    if not csv_path.exists():
        print(f"ERROR: {csv_path} not found")
        return

    print("Loading NQ 1m data...")
    index = load_nq_indexed(csv_path)
    print(f"Loaded {len(index):,} bars\n")

    results = []
    skipped = []
    for date_str in CPI_DATES:
        r = analyze_cpi_event(date_str, index)
        if r:
            results.append(r)
        else:
            skipped.append(date_str)

    if skipped:
        print(f"Skipped (no data): {', '.join(skipped)}\n")

    # ── Print table ───────────────────────────────────────────────────────────
    header = (
        f"{'Date':<12} {'Pre':>8} {'ManipDir':<10} {'ManipPts':>9} "
        f"{'30m Pts':>9} {'30m Dir':<10} {'60m Pts':>9} {'60m Dir':<10}"
    )
    print(header)
    print("-" * len(header))

    for r in results:
        manip_sign = "+" if r["manip_direction"] == "up" else "-"
        d30 = f"{r['dist_pts_30m']:+.1f}" if r["dist_pts_30m"] is not None else "  N/A"
        d60 = f"{r['dist_pts_60m']:+.1f}" if r["dist_pts_60m"] is not None else "  N/A"
        dir30 = r["dist_dir_30m"] or ""
        dir60 = r["dist_dir_60m"] or ""
        print(
            f"{r['date']:<12} {r['pre_close']:>8.2f} {r['manip_direction']:<10} "
            f"{manip_sign}{r['manip_pts']:>8.1f} "
            f"{d30:>9} {dir30:<10} {d60:>9} {dir60:<10}"
        )

    if not results:
        print("No results.")
        return

    # ── Stats ─────────────────────────────────────────────────────────────────
    manip_pts_list = [r["manip_pts"] for r in results]
    dist30 = [r["dist_pts_30m"] for r in results if r["dist_pts_30m"] is not None]
    dist60 = [r["dist_pts_60m"] for r in results if r["dist_pts_60m"] is not None]

    reversal_count_30m = sum(1 for r in results if r["dist_dir_30m"] == "against")
    reversal_count_60m = sum(1 for r in results if r["dist_dir_60m"] == "against")

    print()
    print("=" * 60)
    print("STATISTICS")
    print("=" * 60)
    print(f"Events analyzed       : {len(results)}")
    print()
    print(f"MANIPULATION LEG (first 5 min after CPI)")
    print(f"  Average             : {sum(manip_pts_list)/len(manip_pts_list):.1f} pts")
    print(f"  Min                 : {min(manip_pts_list):.1f} pts")
    print(f"  Max                 : {max(manip_pts_list):.1f} pts")
    print(f"  Median              : {sorted(manip_pts_list)[len(manip_pts_list)//2]:.1f} pts")

    up_count = sum(1 for r in results if r["manip_direction"] == "up")
    print(f"  Direction up/down   : {up_count}/{len(results)-up_count}")

    if dist30:
        abs30 = [abs(x) for x in dist30]
        print()
        print(f"DISTRIBUTION LEG at 30m")
        print(f"  Average magnitude   : {sum(abs30)/len(abs30):.1f} pts")
        print(f"  Min                 : {min(abs30):.1f} pts")
        print(f"  Max                 : {max(abs30):.1f} pts")
        print(f"  Reversal rate       : {reversal_count_30m}/{len(dist30)} ({100*reversal_count_30m/len(dist30):.0f}% go AGAINST manip)")

    if dist60:
        abs60 = [abs(x) for x in dist60]
        print()
        print(f"DISTRIBUTION LEG at 60m")
        print(f"  Average magnitude   : {sum(abs60)/len(abs60):.1f} pts")
        print(f"  Min                 : {min(abs60):.1f} pts")
        print(f"  Max                 : {max(abs60):.1f} pts")
        print(f"  Reversal rate       : {reversal_count_60m}/{len(dist60)} ({100*reversal_count_60m/len(dist60):.0f}% go AGAINST manip)")

    print()
    print("NOTE: 'against' = distribution leg reverses the manipulation spike")
    print("      'with'    = distribution leg continues in same direction as spike")


if __name__ == "__main__":
    main()
