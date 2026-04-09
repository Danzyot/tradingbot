"""
Journal reporter — prints summary stats from the trade journal DB.
"""
from __future__ import annotations

from pathlib import Path

from .database import JournalDB, DEFAULT_DB


def print_summary(db_path: Path = DEFAULT_DB, starting_balance: float = 50_000.0) -> None:
    db = JournalDB(db_path)
    trades = db.all_trades()

    if not trades:
        print("No trades recorded.")
        return

    closed = [t for t in trades if t["outcome"] is not None]
    open_t = [t for t in trades if t["outcome"] is None]
    wins    = [t for t in closed if t["outcome"] == "win"]
    losses  = [t for t in closed if t["outcome"] == "loss"]
    be      = [t for t in closed if t["outcome"] == "be"]

    total_r       = sum(t["pnl_r"] or 0 for t in closed)
    total_dollars = sum(t["pnl_dollars"] or 0 for t in closed)
    win_rate      = len(wins) / len(closed) * 100 if closed else 0
    final_balance = starting_balance + total_dollars

    # Max drawdown (peak-to-trough on running balance)
    peak = starting_balance
    max_dd = 0.0
    running = starting_balance
    for t in closed:
        running += t["pnl_dollars"] or 0
        if running > peak:
            peak = running
        dd = (peak - running) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

    print("=" * 60)
    print("TRADE JOURNAL SUMMARY")
    print("=" * 60)
    print(f"Total signals  : {len(trades)}")
    print(f"  Closed       : {len(closed)} ({len(wins)}W / {len(losses)}L / {len(be)}BE)")
    print(f"  Open         : {len(open_t)}")
    print(f"Win rate       : {win_rate:.1f}%")
    print(f"Total R        : {total_r:+.2f}R")
    print()
    print(f"Account        : ${starting_balance:,.2f} starting")
    print(f"Final balance  : ${final_balance:,.2f}  ({(final_balance/starting_balance-1)*100:+.2f}%)")
    print(f"Net P&L        : ${total_dollars:+,.2f}")
    print(f"Max drawdown   : {max_dd:.2f}%")
    print(f"Risk per trade : 0.5% (${starting_balance * 0.005:,.0f} at start)")
    print()

    # Breakdown by model
    for model in ("ifvg", "ict2022"):
        mt = [t for t in closed if t["model"] == model]
        if not mt:
            continue
        mw = [t for t in mt if t["outcome"] == "win"]
        mr = sum(t["pnl_r"] or 0 for t in mt)
        md = sum(t["pnl_dollars"] or 0 for t in mt)
        print(f"  {model.upper():8s} : {len(mt)} trades | {len(mw)}/{len(mt)} W | {mr:+.2f}R | ${md:+,.2f}")

    print()

    # Recent trades
    print("Last 10 closed trades:")
    print(f"  {'Time':19s} {'Sym':5s} {'Dir':6s} {'Model':7s} {'Out':5s} {'PnL R':7s} {'PnL $':10s} {'Balance':>12s}")
    for t in list(reversed(closed))[:10]:
        bal_after = (t["balance_before"] or starting_balance) + (t["pnl_dollars"] or 0)
        print(
            f"  {t['ts'][:19]:19s} {t['symbol']:5s} {t['direction']:6s} {t['model']:7s} "
            f"{(t['outcome'] or '?'):5s} {(t['pnl_r'] or 0):+7.2f}R "
            f"${(t['pnl_dollars'] or 0):+8.2f}  ${bal_after:>10,.2f}"
        )
    print("=" * 60)
