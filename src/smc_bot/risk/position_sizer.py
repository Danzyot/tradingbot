from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PositionSize:
    contracts: int
    risk_amount: float
    risk_per_contract: float


def calculate_position_size(
    equity: float,
    risk_pct: float,
    entry_price: float,
    stop_loss: float,
    tick_size: float,
    tick_value: float,
) -> PositionSize:
    risk_amount = equity * (risk_pct / 100.0)
    price_risk = abs(entry_price - stop_loss)
    ticks_risk = price_risk / tick_size
    risk_per_contract = ticks_risk * tick_value

    if risk_per_contract <= 0:
        return PositionSize(contracts=0, risk_amount=risk_amount, risk_per_contract=0)

    contracts = int(risk_amount / risk_per_contract)
    contracts = max(contracts, 1)

    return PositionSize(
        contracts=contracts,
        risk_amount=risk_amount,
        risk_per_contract=risk_per_contract,
    )
