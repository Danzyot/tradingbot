"""
Confluence engine — orchestrates all detectors and emits Signals.

Flow per 1m candle close:
  1. New sweeps detected → create Setup (30-60min expiry)
  2. For each active Setup → check for IFVG inversion (Model 1)
  3. For each active Setup → check for CISD + FVG retest (Model 2)
  4. Calculate R:R; if >= min_rr → emit Signal
  5. Model 1 has priority; if Model 1 fires, Model 2 skips same setup
"""
from __future__ import annotations
import uuid
from datetime import datetime, timedelta
from typing import Optional

from ..data.candle import Candle
from ..detectors.sweep import Sweep, SweepDetector, SweepDirection, LiquidityLevel
from ..detectors.fvg import FVG, FVGType, FVGTracker
from ..detectors.ifvg import IFVGDetector, IFVG, IFVGDirection
from ..detectors.cisd import CISDDetector, CISDSignal
from ..detectors.smt import SMTDetector, SMTSignal
from ..detectors.swing import SwingDetector, SwingPoint, SwingType
from ..filters.session import in_killzone, active_session
from ..filters.news import is_blocked
from .base import Setup, Signal, TradeDirection, ModelType


class ConfluenceEngine:
    """
    The main signal engine. Call `update()` every 1m candle close.
    """

    def __init__(
        self,
        fvg_trackers: dict[int, FVGTracker],   # keyed by TF minutes
        swing_detector: SwingDetector,
        smt_detector: Optional[SMTDetector] = None,
        setup_expiry_minutes: int = 60,
        min_rr: float = 1.0,
    ):
        self.fvg_trackers = fvg_trackers
        self.swing_detector = swing_detector
        self.smt = smt_detector
        self.setup_expiry_minutes = setup_expiry_minutes
        self.min_rr = min_rr

        self.sweep_detector = SweepDetector()
        self.ifvg_detector = IFVGDetector(fvg_trackers)
        self.cisd_detector = CISDDetector()

        self._active_setups: list[Setup] = []
        self._liquidity_levels: list[LiquidityLevel] = []

        # Track FVGs from each sweep leg: {setup_id: {tf: [FVG]}}
        self._leg_fvgs: dict[str, dict[int, list[FVG]]] = {}

        # Cooldown: prevent the same price level from creating a new setup too quickly.
        # Maps rounded price → timestamp it was last swept.
        self._swept_levels: dict[float, datetime] = {}
        self._SWEEP_COOLDOWN_MIN = 120   # 2 hours between sweeps of the same level

    # ── Public API ────────────────────────────────────────────────────────────

    def set_liquidity_levels(self, levels: list[LiquidityLevel]) -> None:
        """Update liquidity map (call whenever levels change)."""
        self._liquidity_levels = levels

    def update(
        self,
        candle: Candle,
        candles_by_tf: dict[int, list[Candle]],       # {tf: candle list}
        swings_nq: Optional[list[SwingPoint]] = None,  # for SMT
        swings_es: Optional[list[SwingPoint]] = None,  # for SMT
    ) -> list[Signal]:
        """
        Process one closed candle. Returns any signals generated.
        """
        now = candle.ts
        signals: list[Signal] = []

        # 1. Expire old setups
        self._active_setups = [s for s in self._active_setups if not s.is_expired(now)]

        # 2. Check session + news before doing anything
        if not in_killzone(now):
            return signals
        if is_blocked(now):
            return signals

        # 3. Detect new sweeps → create Setups
        new_sweeps = self.sweep_detector.detect(candle, self._liquidity_levels)
        for sweep in new_sweeps:
            # Cooldown: skip if same level was swept recently
            price_key = round(sweep.level.price, 2)
            if price_key in self._swept_levels:
                elapsed = (now - self._swept_levels[price_key]).total_seconds() / 60
                if elapsed < self._SWEEP_COOLDOWN_MIN:
                    continue
            self._swept_levels[price_key] = now

            setup = self._create_setup(sweep, now)
            self._active_setups.append(setup)
            # Collect FVGs from the sweep leg across all tracked TFs
            self._leg_fvgs[setup.id] = self._collect_leg_fvgs(sweep, candles_by_tf)

        # 4. Check SMT (optional, updates setup bonus flag)
        smt_signal = self._check_smt(swings_nq, swings_es, now)

        # 5. Try to fire entry models on active setups
        for setup in list(self._active_setups):
            # Update leg FVGs with any new ones formed since sweep
            self._update_leg_fvgs(setup, candles_by_tf)

            # Update optional confirmations
            if smt_signal:
                if self._smt_matches_setup(smt_signal, setup):
                    setup.smt_confirmed = True
                    setup.smt = smt_signal

            # Model 1: IFVG
            signal = self._try_model1(setup, candle, candles_by_tf, now)
            if signal:
                signals.append(signal)
                self._active_setups.remove(setup)
                continue

            # Model 2: ICT 2022 (only if Model 1 didn't fire)
            signal = self._try_model2(setup, candle, candles_by_tf, now)
            if signal:
                signals.append(signal)
                self._active_setups.remove(setup)

        return signals

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _create_setup(self, sweep: Sweep, now: datetime) -> Setup:
        return Setup(
            id=str(uuid.uuid4())[:8],
            direction=(
                TradeDirection.LONG if sweep.direction == SweepDirection.BULLISH
                else TradeDirection.SHORT
            ),
            sweep=sweep,
            created_ts=now,
            expires_ts=now + timedelta(minutes=self.setup_expiry_minutes),
        )

    # How far back (in minutes) to look for FVGs on the manipulation leg.
    # The leg is the move that creates the sweep — typically 30–90 min on LTF.
    # Anything older than this is from a previous move, not the current leg.
    LEG_LOOKBACK_MIN = 90

    def _collect_leg_fvgs(
        self, sweep: Sweep, candles_by_tf: dict[int, list[Candle]]
    ) -> dict[int, list[FVG]]:
        """FVGs that formed ON the manipulation leg — within LEG_LOOKBACK_MIN before the sweep."""
        from datetime import timedelta
        leg_start = sweep.ts - timedelta(minutes=self.LEG_LOOKBACK_MIN)
        result: dict[int, list[FVG]] = {}
        for tf, tracker in self.fvg_trackers.items():
            leg = [
                fvg for fvg in tracker.active
                if leg_start <= fvg.ts <= sweep.ts and not fvg.mitigated
            ]
            result[tf] = leg
        return result

    def _update_leg_fvgs(self, setup: Setup, candles_by_tf: dict[int, list[Candle]]) -> None:
        """Add FVGs that formed AT the sweep candle itself (same 1-min bar) to the leg.
        These are edge cases where the sweep candle also creates an FVG.
        FVGs formed well after the sweep belong to the reversal, not the leg."""
        leg = self._leg_fvgs.setdefault(setup.id, {})
        for tf, tracker in self.fvg_trackers.items():
            existing_ids = {f.id for f in leg.get(tf, [])}
            new = [
                fvg for fvg in tracker.active
                if fvg.id not in existing_ids
                and fvg.ts == setup.sweep.ts   # only the sweep candle's own FVG
                and not fvg.mitigated
            ]
            leg.setdefault(tf, []).extend(new)

    def _try_model1(
        self, setup: Setup, candle: Candle,
        candles_by_tf: dict[int, list[Candle]], now: datetime
    ) -> Optional[Signal]:
        """Model 1: sweep → IFVG inversion → market entry."""
        leg_fvgs = self._leg_fvgs.get(setup.id, {})
        ifvg = self.ifvg_detector.check(candle, setup.sweep, leg_fvgs)
        if not ifvg:
            return None

        # Calculate R:R
        sl, tp1, tp2 = self._calculate_targets(setup, candle)
        rr = self._calc_rr(candle.close, sl, tp1)
        if rr < self.min_rr:
            return None

        entry_tf = ifvg.timeframe
        desc = self._build_confluence_desc(
            setup, ModelType.IFVG, entry_tf,
            ifvg=ifvg, smt=setup.smt_confirmed, cisd=setup.cisd_confirmed,
        )

        return Signal(
            setup=setup,
            model=ModelType.IFVG,
            direction=setup.direction,
            symbol=self._pick_symbol(setup),
            entry_price=candle.close,
            stop_loss=sl,
            tp1=tp1,
            tp2=tp2,
            rr_ratio=rr,
            session=active_session(now) or "",
            ts=now,
            entry_tf=entry_tf,
            confluence_desc=desc,
            fvg_top=ifvg.source_fvg.top,
            fvg_bottom=ifvg.source_fvg.bottom,
            fvg_ts=ifvg.source_fvg.ts,
            fvg_kind=ifvg.source_fvg.kind.value if hasattr(ifvg.source_fvg.kind, 'value') else str(ifvg.source_fvg.kind),
            sweep_wick=(setup.sweep.sweep_candle.low if setup.direction == TradeDirection.LONG
                        else setup.sweep.sweep_candle.high),
            smt_ts_a=setup.smt.ts_a if setup.smt else None,
            smt_price_a=(setup.smt.low_a or setup.smt.high_a) if setup.smt else None,
            smt_ts_b=setup.smt.ts_b if setup.smt else None,
            smt_price_b=(setup.smt.low_b or setup.smt.high_b) if setup.smt else None,
            smt_bonus=setup.smt_confirmed,
            cisd_bonus=setup.cisd_confirmed,
        )

    def _try_model2(
        self, setup: Setup, candle: Candle,
        candles_by_tf: dict[int, list[Candle]], now: datetime
    ) -> Optional[Signal]:
        """Model 2: sweep → CISD → FVG retest entry at CE."""
        # Step 1: CISD
        ltf_candles = candles_by_tf.get(1, []) or candles_by_tf.get(5, [])
        cisd = self.cisd_detector.detect(ltf_candles)
        if not cisd:
            return None
        if cisd.direction.value != setup.direction.value:
            return None

        setup.cisd_confirmed = True
        setup.cisd = cisd

        # Step 2: FVG after CISD → price must have retraced to FVG CE
        leg_fvgs = self._leg_fvgs.get(setup.id, {})
        result = self._find_post_cisd_fvg(setup, cisd, leg_fvgs, candle)
        if not result:
            return None
        post_cisd_fvg, fvg_tf = result

        # Entry at CE of FVG
        entry = post_cisd_fvg.ce
        sl, tp1, tp2 = self._calculate_targets(setup, candle)
        rr = self._calc_rr(entry, sl, tp1)
        if rr < self.min_rr:
            return None

        desc = self._build_confluence_desc(
            setup, ModelType.ICT2022, fvg_tf,
            smt=setup.smt_confirmed, cisd=True,
        )


        return Signal(
            setup=setup,
            model=ModelType.ICT2022,
            direction=setup.direction,
            symbol=self._pick_symbol(setup),
            entry_price=entry,
            stop_loss=sl,
            tp1=tp1,
            tp2=tp2,
            rr_ratio=rr,
            session=active_session(now) or "",
            ts=now,
            entry_tf=fvg_tf,
            confluence_desc=desc,
            fvg_top=post_cisd_fvg.top,
            fvg_bottom=post_cisd_fvg.bottom,
            fvg_ts=post_cisd_fvg.ts,
            fvg_kind=post_cisd_fvg.kind.value if hasattr(post_cisd_fvg.kind, 'value') else str(post_cisd_fvg.kind),
            sweep_wick=(setup.sweep.sweep_candle.low if setup.direction == TradeDirection.LONG
                        else setup.sweep.sweep_candle.high),
            smt_ts_a=setup.smt.ts_a if setup.smt else None,
            smt_price_a=(setup.smt.low_a or setup.smt.high_a) if setup.smt else None,
            smt_ts_b=setup.smt.ts_b if setup.smt else None,
            smt_price_b=(setup.smt.low_b or setup.smt.high_b) if setup.smt else None,
            smt_bonus=setup.smt_confirmed,
            cisd_bonus=True,
        )

    def _find_post_cisd_fvg(
        self, setup: Setup, cisd: CISDSignal,
        leg_fvgs: dict[int, list[FVG]], current_candle: Candle
    ) -> Optional[tuple[FVG, int]]:
        """Find an unmitigated FVG after CISD that price is currently retesting.
        Returns (fvg, timeframe) or None."""
        expected = (
            FVGType.BULLISH if setup.direction == TradeDirection.LONG
            else FVGType.BEARISH
        )
        for tf in [5, 3, 1]:
            for fvg in reversed(leg_fvgs.get(tf, [])):
                if fvg.kind != expected:
                    continue
                if fvg.ts < cisd.ts:
                    continue
                if fvg.mitigated:
                    continue
                # Price must be inside or touching the FVG CE
                if fvg.bottom <= current_candle.close <= fvg.top:
                    return fvg, tf
        return None

    # Buffer below/above the sweep wick when placing SL
    _SL_BUFFER = 2.0
    # Minimum TP distance to the DOL target — if nearest level is too close, skip
    _MIN_TP_POINTS = 15.0

    def _calculate_targets(
        self, setup: Setup, candle: Candle
    ) -> tuple[float, float, float]:
        """
        SL: beyond the sweep candle wick + buffer.
        TP1: nearest opposing liquidity level (DOL target).
        TP2: second nearest or 4R fallback.
        """
        entry = candle.close

        if setup.direction == TradeDirection.LONG:
            sl = setup.sweep.sweep_candle.low - self._SL_BUFFER
            # Find nearest level ABOVE entry as TP target
            tp1, tp2 = self._find_dol_targets(entry, above=True)
        else:
            sl = setup.sweep.sweep_candle.high + self._SL_BUFFER
            # Find nearest level BELOW entry as TP target
            tp1, tp2 = self._find_dol_targets(entry, above=False)

        risk = abs(entry - sl)
        # Fallback if no usable DOL target
        if tp1 is None or abs(tp1 - entry) < self._MIN_TP_POINTS:
            tp1 = entry + risk * 2 if setup.direction == TradeDirection.LONG else entry - risk * 2
        if tp2 is None:
            tp2 = entry + risk * 4 if setup.direction == TradeDirection.LONG else entry - risk * 4

        return sl, tp1, tp2

    def _find_dol_targets(
        self, entry: float, above: bool
    ) -> tuple[Optional[float], Optional[float]]:
        """Return the two nearest liquidity levels on the target side."""
        candidates = []
        for level in self._liquidity_levels:
            if above and level.price > entry + self._MIN_TP_POINTS:
                candidates.append(level.price)
            elif not above and level.price < entry - self._MIN_TP_POINTS:
                candidates.append(level.price)

        if not candidates:
            return None, None

        if above:
            candidates.sort()
        else:
            candidates.sort(reverse=True)

        tp1 = candidates[0] if candidates else None
        tp2 = candidates[1] if len(candidates) > 1 else None
        return tp1, tp2

    def _calc_rr(self, entry: float, sl: float, tp1: float) -> float:
        risk   = abs(entry - sl)
        reward = abs(tp1 - entry)
        return reward / risk if risk > 0 else 0.0

    def _check_smt(
        self,
        swings_nq: Optional[list[SwingPoint]],
        swings_es: Optional[list[SwingPoint]],
        now: datetime,
    ) -> Optional[SMTSignal]:
        if not self.smt or not swings_nq or not swings_es:
            return None
        return (
            self.smt.check_bullish(swings_nq, swings_es, now) or
            self.smt.check_bearish(swings_nq, swings_es, now)
        )

    def _smt_matches_setup(self, smt: SMTSignal, setup: Setup) -> bool:
        return smt.direction.value == setup.direction.value

    _KIND_LABELS = {
        "eqh": "Equal Highs (EQH)", "eql": "Equal Lows (EQL)",
        "pdh": "Previous Day High (PDH)", "pdl": "Previous Day Low (PDL)",
        "asia_high": "Asia High", "asia_low": "Asia Low",
        "london_high": "London High", "london_low": "London Low",
        "ny_am_high": "NY AM High", "ny_am_low": "NY AM Low",
        "ny_pm_high": "NY PM High", "ny_pm_low": "NY PM Low",
        "session_high": "Session High", "session_low": "Session Low",
        "swing_high": "Swing High", "swing_low": "Swing Low",
        "fvg_high": "HTF FVG High", "fvg_low": "HTF FVG Low",
        "nwog_high": "NWOG High", "nwog_low": "NWOG Low",
        "ndog_high": "NDOG High", "ndog_low": "NDOG Low",
    }

    def _build_confluence_desc(
        self,
        setup: Setup,
        model: ModelType,
        entry_tf: int,
        ifvg: Optional[object] = None,   # IFVG object for FVG TF info
        smt: bool = False,
        cisd: bool = False,
    ) -> str:
        """
        Full confluence description listing every factor used in the trade decision.
        Format: Bullish sweep of [Level] ([Tier]-tier) | [HTF FVG context] | [IFVG TF]m IFVG | SMT | CISD
        """
        direction = "Bullish" if setup.direction == TradeDirection.LONG else "Bearish"
        kind_raw = setup.sweep.level.kind
        kind = self._KIND_LABELS.get(kind_raw, kind_raw.replace("_", " ").title())
        tier = setup.sweep.level.tier.value

        parts = [f"{direction} sweep of {kind} ({tier}-tier)"]

        # FVG context: if the swept level was an HTF FVG edge, note which TF the FVG was on
        if "fvg" in kind_raw:
            parts.append("HTF FVG liquidity zone")

        # SMT divergence
        if smt:
            parts.append("SMT divergence (NQ/ES)")

        # CISD
        if cisd:
            parts.append("CISD confirmation")

        # Entry signal
        if model == ModelType.IFVG:
            fvg_tf_label = f"{entry_tf}m"
            parts.append(f"{fvg_tf_label} IFVG inversion entry")
        else:
            parts.append(f"{entry_tf}m FVG CE retest (ICT 2022)")

        return " | ".join(parts)

    def _pick_symbol(self, setup: Setup) -> str:
        """If SMT confirmed, trade the stronger symbol. Else trade primary."""
        if setup.smt and setup.smt.trade_symbol:
            return setup.smt.trade_symbol
        return "MNQ"    # default, overridden by config
