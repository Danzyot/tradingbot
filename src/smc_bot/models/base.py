from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from ..detectors.sweep import Sweep
from ..detectors.ifvg import IFVG
from ..detectors.cisd import CISDSignal
from ..detectors.smt import SMTSignal


class TradeDirection(Enum):
    LONG = "long"
    SHORT = "short"


class ModelType(Enum):
    IFVG = "ifvg"           # Model 1: sweep → IFVG
    ICT2022 = "ict2022"     # Model 2: sweep → CISD → FVG retest


@dataclass
class Setup:
    """
    An active setup initiated by a liquidity sweep.
    Lives until IFVG/ICT2022 entry triggers or it expires.
    """
    id: str
    direction: TradeDirection
    sweep: Sweep
    created_ts: datetime
    expires_ts: datetime            # setup is invalidated after this

    # Filled when entry model fires
    model: Optional[ModelType] = None
    ifvg: Optional[IFVG] = None
    cisd: Optional[CISDSignal] = None
    smt: Optional[SMTSignal] = None

    # Optional bonus confirmations
    smt_confirmed: bool = False
    cisd_confirmed: bool = False

    def is_expired(self, now: datetime) -> bool:
        return now > self.expires_ts


@dataclass
class Signal:
    """A confirmed entry signal ready for execution."""
    setup: Setup
    model: ModelType
    direction: TradeDirection
    symbol: str                 # which instrument to trade (NQ or ES, based on SMT)

    entry_price: float          # market order on candle close
    stop_loss: float            # below/above sweep point
    tp1: float                  # 50% close target
    tp2: float                  # runner target

    rr_ratio: float             # calculated R:R at signal time
    session: str                # "london", "ny_am", etc.
    ts: datetime

    # Entry context
    entry_tf: int = 1            # timeframe of the IFVG/FVG that triggered entry (1/3/5)
    confluence_desc: str = ""    # human-readable confluence summary for journal/Notion

    # FVG zone coordinates (for chart drawing on screenshots)
    fvg_top: Optional[float] = None
    fvg_bottom: Optional[float] = None
    fvg_ts: Optional[datetime] = None    # when the FVG formed (left edge of rectangle)
    fvg_kind: Optional[str] = None       # 'bullish' or 'bearish' → green or red rectangle

    # Sweep wick (actual candle extreme that swept the level, for $ marker)
    sweep_wick: Optional[float] = None

    # SMT drawing coords (orange trend line between diverging wicks)
    smt_ts_a: Optional[datetime] = None
    smt_price_a: Optional[float] = None
    smt_ts_b: Optional[datetime] = None
    smt_price_b: Optional[float] = None

    # Scoring
    mandatory_passed: bool = True
    smt_bonus: bool = False
    cisd_bonus: bool = False

    @property
    def score(self) -> int:
        return 2 + int(self.smt_bonus) + int(self.cisd_bonus)
