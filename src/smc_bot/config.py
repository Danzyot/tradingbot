from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel


class RiskConfig(BaseModel):
    risk_per_trade_pct: float = 1.0
    max_daily_risk_pct: float = 3.0
    max_concurrent_trades: int = 2
    max_trades_per_day: int = 3
    daily_halt_pct: float = -2.0
    weekly_halt_pct: float = -5.0
    consecutive_loss_pause: int = 2
    pause_duration_minutes: int = 120
    min_rr: float = 1.0
    tp1_close_pct: float = 50.0


class SwingConfig(BaseModel):
    ltf_left: int = 5
    ltf_right: int = 2
    htf_left: int = 3
    htf_right: int = 1


class KillzoneTime(BaseModel):
    start: str
    end: str


class SessionConfig(BaseModel):
    timezone: str = "America/New_York"
    killzones: dict[str, KillzoneTime] = {}


class FVGConfig(BaseModel):
    timeframes: list[str] = ["1m", "3m", "5m", "15m", "30m", "1H", "4H"]
    htf_timeframes: list[str] = ["15m", "30m", "1H", "4H"]


class IFVGConfig(BaseModel):
    preferred_timeframes: list[str] = ["5m", "3m", "1m"]


class LiquidityConfig(BaseModel):
    eqhl_tolerance_pct: float = 0.1
    eqhl_min_candles_apart_s: int = 3
    eqhl_min_candles_apart_a: int = 1


class SweepConfig(BaseModel):
    cooldown_minutes: int = 5


class SMTConfig(BaseModel):
    window_candles: int = 3


class NewsConfig(BaseModel):
    buffer_minutes_before: int = 5
    buffer_minutes_after: int = 5


class ModelsConfig(BaseModel):
    setup_expiry_minutes: int = 30
    model1_priority: bool = True


class Settings(BaseModel):
    risk: RiskConfig = RiskConfig()
    swing: SwingConfig = SwingConfig()
    sessions: SessionConfig = SessionConfig()
    fvg: FVGConfig = FVGConfig()
    ifvg: IFVGConfig = IFVGConfig()
    liquidity: LiquidityConfig = LiquidityConfig()
    sweep: SweepConfig = SweepConfig()
    smt: SMTConfig = SMTConfig()
    news: NewsConfig = NewsConfig()
    models: ModelsConfig = ModelsConfig()


def load_settings(path: Path | None = None) -> Settings:
    if path is None:
        path = Path(__file__).parent.parent.parent / "config" / "settings.yaml"
    if path.exists():
        with open(path) as f:
            data: dict[str, Any] = yaml.safe_load(f) or {}
        return Settings(**data)
    return Settings()
