from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from smc_bot.journal.database import JournalDB


@dataclass
class PerformanceReport:
    total_signals: int
    total_trades: int
    wins: int
    losses: int
    breakeven: int
    win_rate: float
    total_pnl_r: float
    avg_pnl_r: float
    best_trade_r: float
    worst_trade_r: float
    model1_signals: int
    model2_signals: int
    by_killzone: dict[str, dict[str, Any]]
    by_model: dict[str, dict[str, Any]]


def generate_report(db: JournalDB, start_date: str, end_date: str) -> PerformanceReport:
    conn = db._conn
    signals = conn.execute(
        "SELECT * FROM signals WHERE timestamp >= ? AND timestamp <= ?",
        (start_date, end_date + "T23:59:59"),
    ).fetchall()

    trades = conn.execute(
        "SELECT * FROM trades WHERE open_timestamp >= ? AND open_timestamp <= ?",
        (start_date, end_date + "T23:59:59"),
    ).fetchall()

    total_signals = len(signals)
    total_trades = len(trades)
    wins = sum(1 for t in trades if t["outcome"] == "win")
    losses = sum(1 for t in trades if t["outcome"] == "loss")
    breakeven = sum(1 for t in trades if t["outcome"] == "breakeven")
    win_rate = wins / total_trades * 100 if total_trades > 0 else 0

    pnls = [t["pnl_r"] or 0 for t in trades]
    total_pnl_r = sum(pnls)
    avg_pnl_r = total_pnl_r / total_trades if total_trades > 0 else 0
    best = max(pnls) if pnls else 0
    worst = min(pnls) if pnls else 0

    model1_signals = sum(1 for s in signals if s["model"] == "model1_ifvg")
    model2_signals = sum(1 for s in signals if s["model"] == "model2_ict2022")

    by_killzone: dict[str, dict[str, Any]] = {}
    for t in trades:
        kz = t["killzone"]
        if kz not in by_killzone:
            by_killzone[kz] = {"trades": 0, "wins": 0, "pnl_r": 0}
        by_killzone[kz]["trades"] += 1
        if t["outcome"] == "win":
            by_killzone[kz]["wins"] += 1
        by_killzone[kz]["pnl_r"] += t["pnl_r"] or 0

    by_model: dict[str, dict[str, Any]] = {}
    for t in trades:
        m = t["model"]
        if m not in by_model:
            by_model[m] = {"trades": 0, "wins": 0, "pnl_r": 0}
        by_model[m]["trades"] += 1
        if t["outcome"] == "win":
            by_model[m]["wins"] += 1
        by_model[m]["pnl_r"] += t["pnl_r"] or 0

    return PerformanceReport(
        total_signals=total_signals,
        total_trades=total_trades,
        wins=wins,
        losses=losses,
        breakeven=breakeven,
        win_rate=win_rate,
        total_pnl_r=total_pnl_r,
        avg_pnl_r=avg_pnl_r,
        best_trade_r=best,
        worst_trade_r=worst,
        model1_signals=model1_signals,
        model2_signals=model2_signals,
        by_killzone=by_killzone,
        by_model=by_model,
    )


def print_report(report: PerformanceReport) -> str:
    lines = [
        "=" * 60,
        "PERFORMANCE REPORT",
        "=" * 60,
        f"Total Signals: {report.total_signals}",
        f"  Model 1 (IFVG): {report.model1_signals}",
        f"  Model 2 (ICT 2022): {report.model2_signals}",
        "",
        f"Total Trades: {report.total_trades}",
        f"  Wins: {report.wins} | Losses: {report.losses} | BE: {report.breakeven}",
        f"  Win Rate: {report.win_rate:.1f}%",
        "",
        f"P&L (in R): {report.total_pnl_r:+.2f}R",
        f"  Avg Trade: {report.avg_pnl_r:+.2f}R",
        f"  Best: {report.best_trade_r:+.2f}R | Worst: {report.worst_trade_r:+.2f}R",
        "",
        "By Killzone:",
    ]
    for kz, data in report.by_killzone.items():
        wr = data["wins"] / data["trades"] * 100 if data["trades"] > 0 else 0
        lines.append(f"  {kz}: {data['trades']} trades, {wr:.0f}% WR, {data['pnl_r']:+.2f}R")

    lines.append("")
    lines.append("By Model:")
    for m, data in report.by_model.items():
        wr = data["wins"] / data["trades"] * 100 if data["trades"] > 0 else 0
        lines.append(f"  {m}: {data['trades']} trades, {wr:.0f}% WR, {data['pnl_r']:+.2f}R")

    lines.append("=" * 60)
    return "\n".join(lines)
