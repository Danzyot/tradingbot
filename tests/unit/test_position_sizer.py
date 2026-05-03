from smc_bot.risk.position_sizer import calculate_position_size


def test_basic_position_size():
    """10k equity, 1% risk, 4 point SL on MNQ (tick=0.25, value=0.50)"""
    result = calculate_position_size(
        equity=10000.0,
        risk_pct=1.0,
        entry_price=18000.0,
        stop_loss=17996.0,
        tick_size=0.25,
        tick_value=0.50,
    )
    # risk_amount = 100
    # price_risk = 4.0, ticks = 16, risk_per_contract = 16 * 0.50 = 8.0
    # contracts = 100 / 8 = 12
    assert result.contracts == 12
    assert result.risk_amount == 100.0
    assert result.risk_per_contract == 8.0


def test_minimum_one_contract():
    """Even if risk amount is less than risk per contract, use 1"""
    result = calculate_position_size(
        equity=1000.0,
        risk_pct=1.0,
        entry_price=5000.0,
        stop_loss=4990.0,
        tick_size=0.25,
        tick_value=12.50,
    )
    # risk_amount = 10
    # price_risk = 10, ticks = 40, risk_per_contract = 40 * 12.50 = 500
    # contracts = 10 / 500 = 0 → clamped to 1
    assert result.contracts == 1


def test_zero_risk():
    """Entry == SL → 0 contracts"""
    result = calculate_position_size(
        equity=10000.0,
        risk_pct=1.0,
        entry_price=5000.0,
        stop_loss=5000.0,
        tick_size=0.25,
        tick_value=12.50,
    )
    assert result.contracts == 0
