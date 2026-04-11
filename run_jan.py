import sys
sys.path.insert(0, 'src')
from pathlib import Path
from smc_bot.engine.backtest import run_backtest

run_backtest(
    mnq_csv=Path('data/nq_1m.csv'),
    mes_csv=Path('data/es_1m.csv'),
    max_concurrent_trades=1,
    be_trigger_r=1.0,
    min_rr=1.0,
    starting_balance=50_000.0,
    risk_pct=0.005,
    date_from='2023-01-02',
    date_to='2023-01-31',
    sweep_entry=False,
    verbose=True,
)
