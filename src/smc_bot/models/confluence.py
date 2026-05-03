from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from smc_bot.config import Settings
from smc_bot.data.candle import Candle
from smc_bot.detectors.cisd import CISD, CISDDetector, CISDDirection
from smc_bot.detectors.fvg import FVG, FVGDetector, FVGDirection
from smc_bot.detectors.ifvg import IFVG, IFVGDetector, IFVGDirection, select_highest_tf_ifvg
from smc_bot.detectors.liquidity import DOLTier, LiquidityDetector, LiquidityLevel
from smc_bot.detectors.market_structure import MarketStructureDetector
from smc_bot.detectors.nwog_ndog import NWOGNDOGDetector
from smc_bot.detectors.premium_discount import DealingRange
from smc_bot.detectors.smt import SMTDetector, SMTDivergence, SMTDirection
from smc_bot.detectors.sweep import Sweep, SweepDetector, SweepDirection
from smc_bot.detectors.swing import SwingDetector, SwingPoint, SwingType
from smc_bot.filters.news import NewsFilter
from smc_bot.filters.session import SessionFilter
from smc_bot.models.base import (
    ModelType,
    Setup,
    SetupState,
    Signal,
    TradeDirection,
)


class ConfluenceEngine:
    def __init__(self, settings: Settings, instrument: str = "NQ"):
        self._settings = settings
        self._instrument = instrument

        self._swing_detectors: dict[str, SwingDetector] = {}
        self._fvg_detectors: dict[str, FVGDetector] = {}
        self._ifvg_detectors: dict[str, IFVGDetector] = {}
        self._cisd_detectors: dict[str, CISDDetector] = {}
        self._liquidity = LiquidityDetector(
            tolerance_pct=settings.liquidity.eqhl_tolerance_pct,
            min_candles_apart_s=settings.liquidity.eqhl_min_candles_apart_s,
            min_candles_apart_a=settings.liquidity.eqhl_min_candles_apart_a,
        )
        self._sweep_detector = SweepDetector(
            cooldown_minutes=settings.sweep.cooldown_minutes
        )
        self._nwog_ndog = NWOGNDOGDetector()
        self._market_structure = MarketStructureDetector()
        self._smt: SMTDetector | None = None
        self._session_filter = SessionFilter(
            timezone=settings.sessions.timezone
        )
        self._news_filter = NewsFilter(
            buffer_before_minutes=settings.news.buffer_minutes_before,
            buffer_after_minutes=settings.news.buffer_minutes_after,
        )

        for tf in settings.fvg.timeframes:
            is_htf = tf in ("15m", "30m", "1H", "4H")
            left = settings.swing.htf_left if is_htf else settings.swing.ltf_left
            right = settings.swing.htf_right if is_htf else settings.swing.ltf_right
            self._swing_detectors[tf] = SwingDetector(left=left, right=right, timeframe=tf)
            self._fvg_detectors[tf] = FVGDetector(timeframe=tf)

        for tf in settings.ifvg.preferred_timeframes:
            self._ifvg_detectors[tf] = IFVGDetector(timeframe=tf)
            self._cisd_detectors[tf] = CISDDetector(timeframe=tf)

        self._active_setups: list[Setup] = []
        self._triggered_signals: list[Signal] = []
        self._expiry_minutes = settings.models.setup_expiry_minutes

    @property
    def active_setups(self) -> list[Setup]:
        return [s for s in self._active_setups if s.is_active]

    @property
    def signals(self) -> list[Signal]:
        return self._triggered_signals

    @property
    def session_filter(self) -> SessionFilter:
        return self._session_filter

    @property
    def news_filter(self) -> NewsFilter:
        return self._news_filter

    def set_smt_detector(self, smt: SMTDetector) -> None:
        self._smt = smt

    def update(
        self, timeframe: str, candle: Candle, smt_divergence: SMTDivergence | None = None
    ) -> list[Signal]:
        new_signals: list[Signal] = []

        if timeframe in self._swing_detectors:
            new_swings = self._swing_detectors[timeframe].update(candle)
            if new_swings:
                self._liquidity.update_from_swings(
                    self._swing_detectors[timeframe].swings
                )
                for swing in new_swings:
                    self._market_structure.update(swing)

        if timeframe in self._fvg_detectors:
            self._fvg_detectors[timeframe].update(candle)

        if timeframe in self._cisd_detectors:
            self._cisd_detectors[timeframe].update(candle)

        if timeframe in self._ifvg_detectors:
            for setup in self._active_setups:
                if not setup.is_active:
                    continue
                self._ifvg_detectors[timeframe].update(
                    candle, sweep_timestamp=setup.sweep_timestamp
                )

        self._liquidity.update_daily(candle)

        gap_levels = self._nwog_ndog.update(candle)
        for level in gap_levels:
            self._liquidity._levels.append(level)

        self._expire_setups(candle.timestamp)

        if timeframe in self._fvg_detectors:
            sweeps = self._sweep_detector.update(candle, self._liquidity.unswept)
            for sweep in sweeps:
                self._create_setup(sweep, candle.timestamp)

        for setup in self._active_setups:
            if not setup.is_active:
                continue
            signal = self._evaluate_setup(setup, timeframe, candle, smt_divergence)
            if signal:
                new_signals.append(signal)

        self._triggered_signals.extend(new_signals)
        return new_signals

    def _create_setup(self, sweep: Sweep, timestamp: datetime) -> None:
        direction = (
            TradeDirection.LONG
            if sweep.direction == SweepDirection.BULLISH
            else TradeDirection.SHORT
        )

        expiry = timestamp + timedelta(minutes=self._expiry_minutes)

        setup = Setup(
            direction=direction,
            sweep_price=sweep.price,
            sweep_timestamp=timestamp,
            expiry=expiry,
            confluences={"sweep_tier": sweep.tier.value, "sweep_level": sweep.level.type.value},
        )
        self._active_setups.append(setup)

        for tf in self._settings.ifvg.preferred_timeframes:
            fvg_det = self._fvg_detectors.get(tf)
            if fvg_det:
                manipulation_fvgs = [
                    f for f in fvg_det.unmitigated
                    if self._is_from_manipulation_leg(f, sweep)
                ]
                self._ifvg_detectors[tf].track_fvgs_from_sweep(
                    manipulation_fvgs, timestamp
                )

    def _evaluate_setup(
        self,
        setup: Setup,
        timeframe: str,
        candle: Candle,
        smt_divergence: SMTDivergence | None,
    ) -> Signal | None:
        if not self._session_filter.is_in_killzone(candle.timestamp):
            return None
        if self._news_filter.is_blocked(candle.timestamp):
            return None

        signal = self._try_model1(setup, timeframe, candle, smt_divergence)
        if signal:
            setup.trigger(signal)
            return signal

        if self._settings.models.model1_priority:
            already_triggered = any(
                s.state == SetupState.TRIGGERED and s.model == ModelType.IFVG
                for s in self._active_setups
                if s.sweep_timestamp == setup.sweep_timestamp
            )
            if already_triggered:
                return None

        signal = self._try_model2(setup, timeframe, candle, smt_divergence)
        if signal:
            setup.trigger(signal)
            return signal

        return None

    def _try_model1(
        self,
        setup: Setup,
        timeframe: str,
        candle: Candle,
        smt_divergence: SMTDivergence | None,
    ) -> Signal | None:
        if timeframe not in self._ifvg_detectors:
            return None

        all_ifvgs: dict[str, list[IFVG]] = {}
        for tf, det in self._ifvg_detectors.items():
            relevant = [
                i for i in det.ifvgs
                if i.sweep_timestamp == setup.sweep_timestamp
                and i.inversion_timestamp == candle.timestamp
            ]
            if relevant:
                all_ifvgs[tf] = relevant

        best_ifvg = select_highest_tf_ifvg(
            all_ifvgs, self._settings.ifvg.preferred_timeframes
        )
        if best_ifvg is None:
            return None

        if setup.direction == TradeDirection.LONG and best_ifvg.direction != IFVGDirection.BULLISH:
            return None
        if setup.direction == TradeDirection.SHORT and best_ifvg.direction != IFVGDirection.BEARISH:
            return None

        score = 0
        confluences: dict[str, Any] = {
            "ifvg_tf": best_ifvg.timeframe,
            "ifvg_high": best_ifvg.high,
            "ifvg_low": best_ifvg.low,
        }

        if smt_divergence:
            if setup.direction == TradeDirection.LONG and smt_divergence.direction == SMTDirection.BULLISH:
                score += 1
                confluences["smt"] = "bullish"
            elif setup.direction == TradeDirection.SHORT and smt_divergence.direction == SMTDirection.BEARISH:
                score += 1
                confluences["smt"] = "bearish"

        for tf, det in self._cisd_detectors.items():
            if det.last_cisd and det.last_cisd.timestamp == candle.timestamp:
                if setup.direction == TradeDirection.LONG and det.last_cisd.direction == CISDDirection.BULLISH:
                    score += 1
                    confluences["cisd"] = "bullish"
                    break
                elif setup.direction == TradeDirection.SHORT and det.last_cisd.direction == CISDDirection.BEARISH:
                    score += 1
                    confluences["cisd"] = "bearish"
                    break

        entry_price = candle.close
        stop_loss = setup.sweep_price
        tp1 = self._find_tp1(setup.direction, entry_price)

        if tp1 is None:
            return None

        risk = abs(entry_price - stop_loss)
        reward = abs(tp1 - entry_price)
        if risk == 0 or reward / risk < self._settings.risk.min_rr:
            return None

        killzone = self._session_filter.get_active_killzone(candle.timestamp) or "unknown"

        return Signal(
            direction=setup.direction,
            model=ModelType.IFVG,
            entry_price=entry_price,
            stop_loss=stop_loss,
            tp1=tp1,
            tp2=self._find_tp2(setup.direction, tp1),
            timestamp=candle.timestamp,
            instrument=self._instrument,
            killzone=killzone,
            score=score,
            confluences={**setup.confluences, **confluences},
        )

    def _try_model2(
        self,
        setup: Setup,
        timeframe: str,
        candle: Candle,
        smt_divergence: SMTDivergence | None,
    ) -> Signal | None:
        if timeframe not in self._cisd_detectors:
            return None

        cisd_det = self._cisd_detectors[timeframe]
        if not cisd_det.last_cisd:
            return None
        if cisd_det.last_cisd.timestamp != candle.timestamp:
            return None

        cisd = cisd_det.last_cisd
        if setup.direction == TradeDirection.LONG and cisd.direction != CISDDirection.BULLISH:
            return None
        if setup.direction == TradeDirection.SHORT and cisd.direction != CISDDirection.BEARISH:
            return None

        fvg_det = self._fvg_detectors.get(timeframe)
        if not fvg_det:
            return None

        target_fvgs = [
            f for f in fvg_det.unmitigated
            if f.timestamp >= setup.sweep_timestamp
            and not f.mitigated
        ]

        if setup.direction == TradeDirection.LONG:
            target_fvgs = [f for f in target_fvgs if f.direction == FVGDirection.BULLISH]
        else:
            target_fvgs = [f for f in target_fvgs if f.direction == FVGDirection.BEARISH]

        if not target_fvgs:
            return None

        fvg = target_fvgs[-1]
        entry_price = fvg.ce
        stop_loss = setup.sweep_price

        if setup.direction == TradeDirection.LONG:
            stop_loss = min(stop_loss, fvg.low)
        else:
            stop_loss = max(stop_loss, fvg.high)

        tp1 = self._find_tp1(setup.direction, entry_price)
        if tp1 is None:
            return None

        risk = abs(entry_price - stop_loss)
        reward = abs(tp1 - entry_price)
        if risk == 0 or reward / risk < self._settings.risk.min_rr:
            return None

        score = 0
        confluences: dict[str, Any] = {
            "cisd_tf": timeframe,
            "fvg_ce": fvg.ce,
            "fvg_high": fvg.high,
            "fvg_low": fvg.low,
        }

        if smt_divergence:
            if setup.direction == TradeDirection.LONG and smt_divergence.direction == SMTDirection.BULLISH:
                score += 1
                confluences["smt"] = "bullish"
            elif setup.direction == TradeDirection.SHORT and smt_divergence.direction == SMTDirection.BEARISH:
                score += 1
                confluences["smt"] = "bearish"

        killzone = self._session_filter.get_active_killzone(candle.timestamp) or "unknown"

        return Signal(
            direction=setup.direction,
            model=ModelType.ICT2022,
            entry_price=entry_price,
            stop_loss=stop_loss,
            tp1=tp1,
            tp2=self._find_tp2(setup.direction, tp1),
            timestamp=candle.timestamp,
            instrument=self._instrument,
            killzone=killzone,
            score=score,
            confluences={**setup.confluences, **confluences},
        )

    def _find_tp1(self, direction: TradeDirection, entry: float) -> float | None:
        levels = sorted(self._liquidity.unswept, key=lambda l: l.price)

        if direction == TradeDirection.LONG:
            targets = [l for l in levels if l.price > entry]
            targets.sort(key=lambda l: (
                0 if l.tier == DOLTier.S else 1 if l.tier == DOLTier.A else 2
            ))
            return targets[0].price if targets else None
        else:
            targets = [l for l in levels if l.price < entry]
            targets.sort(key=lambda l: (
                0 if l.tier == DOLTier.S else 1 if l.tier == DOLTier.A else 2
            ))
            return targets[-1].price if targets else None

    def _find_tp2(self, direction: TradeDirection, tp1: float) -> float | None:
        levels = sorted(self._liquidity.unswept, key=lambda l: l.price)

        if direction == TradeDirection.LONG:
            targets = [l for l in levels if l.price > tp1]
            return targets[0].price if targets else None
        else:
            targets = [l for l in levels if l.price < tp1]
            return targets[-1].price if targets else None

    def _expire_setups(self, now: datetime) -> None:
        for setup in self._active_setups:
            if setup.is_active and now >= setup.expiry:
                setup.expire()

    def _is_from_manipulation_leg(self, fvg: FVG, sweep: Sweep) -> bool:
        if sweep.direction == SweepDirection.BULLISH:
            return fvg.direction == FVGDirection.BEARISH
        return fvg.direction == FVGDirection.BULLISH
