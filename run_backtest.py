import sys
sys.path.insert(0, 'src')

from pathlib import Path
from smc_bot.engine.backtest import run_backtest

run_backtest(
    mnq_csv=Path('data/nq_1m.csv'),    # full-size NQ for backtesting
    mes_csv=Path('data/es_1m.csv'),    # full-size ES for SMT
    max_concurrent_trades=1,
    be_trigger_r=1.0,
    min_rr=1.0,
    starting_balance=50_000.0,
    risk_pct=0.005,                    # 0.5% risk per trade
    date_from="2023-01-02",            # full January 2023
    date_to="2023-01-31",
    sweep_entry=False,                 # IFVG mode: require sweep → IFVG inversion
)
