from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from smc_bot.config import RiskConfig
from smc_bot.risk.risk_manager import RiskManager

NY = ZoneInfo("America/New_York")
BASE = datetime(2024, 1, 15, 9, 30, tzinfo=NY)


def test_can_trade_initially():
    rm = RiskManager(RiskConfig())
    allowed, reason = rm.can_trade(BASE)
    assert allowed is True
    assert reason == ""


def test_daily_halt():
    rm = RiskManager(RiskConfig(daily_halt_pct=-2.0))
    rm._state.daily_pnl_pct = -2.1
    allowed, reason = rm.can_trade(BASE)
    assert allowed is False
    assert "Daily" in reason


def test_max_trades_per_day():
    rm = RiskManager(RiskConfig(max_trades_per_day=3))
    rm._state.trades_today = 3
    allowed, reason = rm.can_trade(BASE)
    assert allowed is False
    assert "Max trades" in reason


def test_consecutive_loss_pause():
    config = RiskConfig(consecutive_loss_pause=2, pause_duration_minutes=120, daily_halt_pct=-10.0)
    rm = RiskManager(config)

    rm.record_trade_open()
    rm.record_trade_close(-1.0, BASE)
    rm.record_trade_open()
    rm.record_trade_close(-1.0, BASE + timedelta(minutes=5))

    allowed, reason = rm.can_trade(BASE + timedelta(minutes=10))
    assert allowed is False
    assert "consecutive" in reason.lower()

    allowed_after, _ = rm.can_trade(BASE + timedelta(minutes=130))
    assert allowed_after is True


def test_reset_daily():
    rm = RiskManager(RiskConfig())
    rm._state.daily_pnl_pct = -1.5
    rm._state.trades_today = 2
    rm._state.halted = True
    rm._state.halt_reason = "Daily loss limit hit"

    rm.reset_daily()

    assert rm._state.daily_pnl_pct == 0.0
    assert rm._state.trades_today == 0
    assert rm._state.halted is False
