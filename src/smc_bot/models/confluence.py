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
from ..detectors.sweep import Sweep, SweepDetector, SweepDirection, LiquidityLevel, LiqTier
from ..detectors.fvg import FVG, FVGType, FVGTracker
from ..detectors.ifvg import IFVGDetector, IFVG, IFVGDirection
from ..detectors.cisd import CISDDetector, CISDSignal
from ..detectors.smt import SMTDetector, SMTSignal
from ..detectors.swing import SwingDetector, SwingPoint, SwingType
from ..filters.session import in_killzone, active_session, near_htf_open
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
        enable_model2: bool = False,   # Model 2 (CISD retest) off until Model 1 is validated
    ):
        self.fvg_trackers = fvg_trackers
        self.swing_detector = swing_detector
        self.smt = smt_detector
        self.setup_expiry_minutes = setup_expiry_minutes
        self.min_rr = min_rr

        self.enable_model2 = enable_model2
        self.enable_sweep_entry = False   # sweep-only mode: enter on sweep close, no IFVG
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
        self._SWEEP_COOLDOWN_MIN = 5     # 5 min between sweeps of the same level (allow re-sweeps)

        # Permanently consumed levels — any major level, once swept, is gone.
        # The liquidity pool at that price has been taken. Price won't return to it as a target.
        # Tracks rounded price → so same price from different level sources is also blocked.
        self._consumed_prices: set[float] = set()

    # ── Public API ────────────────────────────────────────────────────────────

    def set_liquidity_levels(self, levels: list[LiquidityLevel]) -> None:
        """Update liquidity map (call whenever levels change).

        Levels that were previously swept are permanently filtered — their liquidity
        pool has been consumed and price won't revisit them as a target.
        """
        self._liquidity_levels = [
            lvl for lvl in levels
            if round(lvl.price, 2) not in self._consumed_prices
        ]

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

        # 3. Detect new sweeps → validate quality → create Setups
        ltf_candles_1m = candles_by_tf.get(1, [])
        new_sweeps = self.sweep_detector.detect(candle, self._liquidity_levels, candle_history=ltf_candles_1m)
        atr14 = self._compute_atr(ltf_candles_1m, period=14)

        for sweep in new_sweeps:
            price_key = round(sweep.level.price, 2)

            # ALWAYS invalidate any existing active setup near this level — even if we
            # don't create a new setup (due to cooldown), the old leg is stale.
            # Re-sweep = the prior manipulation leg is consumed; old FVGs no longer valid.
            self._active_setups = [
                s for s in self._active_setups
                if abs(round(s.sweep.level.price, 2) - price_key) > 5.0
            ]

            # Cooldown: prevent the exact same level from creating a duplicate setup
            # within a few minutes (same candle / same leg). 5 min is enough — we want
            # re-sweeps after 5+ min to replace the old setup, not be blocked.
            if price_key in self._swept_levels:
                elapsed = (now - self._swept_levels[price_key]).total_seconds() / 60
                if elapsed < self._SWEEP_COOLDOWN_MIN:
                    continue
            self._swept_levels[price_key] = now

            # Anchor the manipulation leg to the prior opposing swing point.
            leg_start_ts = self._find_leg_start(sweep, swings_nq or [])
            if leg_start_ts:
                sweep.leg_start_ts = leg_start_ts

            # Find the ACTUAL manipulation leg extreme for SL placement.
            # _check() fires on the close-back candle (body closes back inside level),
            # which may NOT be the highest/lowest candle of the leg.
            # We store the leg extreme separately as leg_extreme_candle — used ONLY for SL.
            # sweep_candle stays as the original close-back candle for quality gate checks.
            # Apply the same 90-min cap as FVGs — don't reach back more than 90 min.
            _leg_cap_ts = sweep.ts - timedelta(minutes=self._MAX_LEG_LOOKBACK_MIN)
            _effective_start = max(sweep.leg_start_ts, _leg_cap_ts) if sweep.leg_start_ts else _leg_cap_ts
            leg_candles = [c for c in ltf_candles_1m
                           if _effective_start <= c.ts <= sweep.ts]
            if leg_candles:
                if sweep.direction == SweepDirection.BEARISH:
                    sweep.leg_extreme_candle = max(leg_candles, key=lambda c: c.high)
                else:
                    sweep.leg_extreme_candle = min(leg_candles, key=lambda c: c.low)

            # Quality gate 1: wick must penetrate the level meaningfully (no micro-taps)
            if not self._sweep_has_valid_penetration(sweep, atr14):
                continue

            # Quality gate 2: manipulation leg must be large enough (real directional move)
            if not self._leg_is_significant(sweep, ltf_candles_1m, atr14):
                continue

            setup = self._create_setup(sweep, now)

            # Permanently consume the swept level only AFTER quality gates pass.
            # Consuming before quality gates meant a micro-tap (< 3pt wick) would permanently
            # block the real sweep of that level from ever forming a setup.
            self._consumed_prices.add(price_key)

            # Sweep-only mode: emit signal immediately at sweep candle close, no IFVG
            if self.enable_sweep_entry:
                sig = self._try_sweep_entry(setup, candle, now)
                if sig:
                    signals.append(sig)
                continue   # don't add to active setups — sweep-only doesn't wait for IFVG

            # Collect FVGs from the sweep leg across all tracked TFs
            leg_fvgs = self._collect_leg_fvgs(sweep, candles_by_tf)

            # Quality gate 3: must have at least one FVG on the leg
            if not any(fvgs for fvgs in leg_fvgs.values()):
                continue

            self._active_setups.append(setup)
            self._leg_fvgs[setup.id] = leg_fvgs

        # 4. Check SMT (optional, updates setup bonus flag)
        smt_signal = self._check_smt(swings_nq, swings_es, now)

        # Block signal emission 1-5 min before major HTF candle opens.
        # Sweeps are still detected and setups created — only entry is blocked.
        # 9:30, 10:00, 10:30, 15:00, 15:30 ET — PO3 manipulation timing.
        if near_htf_open(now):
            return signals

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

            # Model 2: ICT 2022 (only if Model 1 didn't fire, and Model 2 is enabled)
            if self.enable_model2:
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

    # Maximum lookback for leg FVGs.
    # If the swing-anchored leg start is older than this, we cap it.
    # Prevents FVGs from a FIRST approach to a level being included when
    # price revisits and sweeps that level on a second, deeper manipulation leg.
    # NQ intraday manipulation legs are typically 5–60 min; 90 min covers all valid legs.
    _MAX_LEG_LOOKBACK_MIN = 90

    def _collect_leg_fvgs(
        self, sweep: Sweep, candles_by_tf: dict[int, list[Candle]]
    ) -> dict[int, list[FVG]]:
        """FVGs that formed ON the manipulation leg.

        The leg is bounded by:
        - Upper bound: sweep candle timestamp
        - Lower bound: max(leg_start_ts from swing detection, sweep.ts - 90 min)

        The 90-min cap prevents stale FVGs from an earlier approach to the same
        level from polluting the leg. Only the MOST RECENT manipulation counts.
        """
        hard_min_ts = sweep.ts - timedelta(minutes=self._MAX_LEG_LOOKBACK_MIN)
        if sweep.leg_start_ts:
            effective_start = max(sweep.leg_start_ts, hard_min_ts)
        else:
            effective_start = hard_min_ts

        result: dict[int, list[FVG]] = {}
        for tf, tracker in self.fvg_trackers.items():
            all_fvgs = tracker.active + tracker.mitigated
            leg = [
                fvg for fvg in all_fvgs
                if fvg.ts <= sweep.ts
                and fvg.ts >= effective_start
            ]
            result[tf] = leg
        return result

    def _find_leg_start(
        self, sweep: Sweep, swings: list["SwingPoint"]
    ) -> Optional[datetime]:
        """
        Manipulation leg starts at the most recent opposing swing before the sweep.
        - Bullish sweep (swept a low) → leg descended FROM a prior swing HIGH
        - Bearish sweep (swept a high) → leg ascended FROM a prior swing LOW
        Returns the timestamp of that swing, or None if no swings are available.
        """
        if not swings:
            return None

        target_kind = (
            SwingType.HIGH if sweep.direction.value == "bullish"
            else SwingType.LOW
        )
        candidates = [s for s in swings if s.kind == target_kind and s.ts < sweep.ts]
        if not candidates:
            return None
        return max(candidates, key=lambda s: s.ts).ts

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

    # Max time between sweep and IFVG inversion.
    # Must match setup_expiry_min in run_backtest (60 min).
    # 20 min was too tight — most valid IFVGs fire 20–60 min after sweep as price retests.
    _MAX_SWEEP_TO_ENTRY_MIN = 60

    # Base displacement minimum — overridden by ATR at runtime
    _BASE_MIN_DISPLACEMENT_BODY_PTS = 3.0

    def _has_displacement(
        self, sweep: "Sweep", candles_by_tf: dict[int, list[Candle]], atr14: float = 15.0
    ) -> bool:
        """
        Within 20 bars after the sweep, at least one candle must show displacement
        moving AWAY from the swept level in the reversal direction.
        Threshold scales with ATR — 30% of ATR(14), floored at 3pt.
        During volatile NY (ATR ~25) requires 7.5pt body; Asia (ATR ~8) requires 3pt.
        """
        ltf = candles_by_tf.get(1, [])
        if not ltf:
            return False

        min_body = max(self._BASE_MIN_DISPLACEMENT_BODY_PTS, atr14 * 0.30)
        post_sweep = [c for c in ltf if c.ts > sweep.ts][:20]
        for c in post_sweep:
            body = abs(c.close - c.open)
            if body < min_body:
                continue
            if sweep.direction == SweepDirection.BULLISH:
                if c.close > c.open:
                    return True
            else:
                if c.close < c.open:
                    return True

        return False

    def _try_model1(
        self, setup: Setup, candle: Candle,
        candles_by_tf: dict[int, list[Candle]], now: datetime
    ) -> Optional[Signal]:
        """Model 1: sweep → IFVG inversion → market entry."""
        # Time cap: IFVG must fire within N minutes of the sweep
        minutes_since_sweep = (now - setup.sweep.ts).total_seconds() / 60
        if minutes_since_sweep > self._MAX_SWEEP_TO_ENTRY_MIN:
            return None

        # Require displacement: at least one aggressive reversal candle after the sweep.
        # Without it the sweep is noise — no institutional entry, no valid IFVG.
        ltf_candles_1m_check = candles_by_tf.get(1, [])
        atr14_check = self._compute_atr(ltf_candles_1m_check, period=14)
        if not self._has_displacement(setup.sweep, candles_by_tf, atr14_check):
            return None

        # Step 9: HTF alignment gate — only enter if 4H trend doesn't decisively oppose setup
        if not self._htf_regime_allows(setup.direction, candles_by_tf):
            return None

        leg_fvgs = self._leg_fvgs.get(setup.id, {})
        ifvg = self.ifvg_detector.check(candle, setup.sweep, leg_fvgs)
        if not ifvg:
            return None

        # IFVG close quality: inversion candle must be body-dominant (≥ 50% body/range).
        # Wick-dominant closes show rejection, not committed delivery.
        if not self._ifvg_close_is_body_dominant(candle):
            return None

        # Priority 4: strong close — must close ≥ 2pt beyond FVG far edge.
        # Barely clipping the far edge = weak inversion. Want strong displacement.
        if not self._ifvg_close_is_strong(ifvg, candle):
            return None

        # TP1 is always fixed 1R (Step 5 — master plan)
        sl, tp1, tp2, tp1_label = self._calculate_targets(setup, candle)
        rr = self._calc_rr(candle.close, sl, tp1)
        if rr < self.min_rr:
            return None

        entry_tf = ifvg.timeframe
        desc = self._build_confluence_desc(
            setup, ModelType.IFVG, entry_tf,
            ifvg=ifvg, smt=setup.smt_confirmed, cisd=setup.cisd_confirmed,
        )
        if tp1_label:
            desc = f"{desc} | DOL: {tp1_label}"

        return self._make_signal(
            setup=setup, model=ModelType.IFVG,
            entry_price=candle.close, stop_loss=sl, tp1=tp1, tp2=tp2, rr=rr,
            now=now, entry_tf=entry_tf, confluence_desc=desc,
            fvg=ifvg.source_fvg,
        )

    def _try_model2(
        self, setup: Setup, candle: Candle,
        candles_by_tf: dict[int, list[Candle]], now: datetime
    ) -> Optional[Signal]:
        """Model 2: sweep → CISD (FVG inversion) → FVG retest entry at CE.

        CoWork fix: CISD = the candle whose body crosses the FVG boundary.
        After CISD fires, price must retrace to the FVG zone for entry.
        """
        # Step 9: HTF alignment gate
        if not self._htf_regime_allows(setup.direction, candles_by_tf):
            return None

        # Step 1: CISD — body must cross a leg FVG boundary (same as IFVG trigger)
        leg_fvgs = self._leg_fvgs.get(setup.id, {})
        cisd = self.cisd_detector.detect(candle, leg_fvgs, setup.direction)
        if not cisd:
            return None

        setup.cisd_confirmed = True
        setup.cisd = cisd

        # Step 2: price must have RETRACED to the FVG that was just inverted (the CISD FVG)
        # Entry is on the retest at CE — not at the inversion candle itself (that's Model 1)
        post_cisd_fvg = cisd.source_fvg
        fvg_tf = post_cisd_fvg.timeframe
        # Price must currently be inside the FVG zone (the retest)
        if not (post_cisd_fvg.bottom <= candle.close <= post_cisd_fvg.top):
            return None

        # Entry at CE of FVG — TP1 is always fixed 1R (Step 5)
        entry = post_cisd_fvg.ce
        sl, tp1, tp2, tp1_label = self._calculate_targets(setup, candle)
        rr = self._calc_rr(entry, sl, tp1)
        if rr < self.min_rr:
            return None

        desc = self._build_confluence_desc(
            setup, ModelType.ICT2022, fvg_tf,
            smt=setup.smt_confirmed, cisd=True,
        )

        return self._make_signal(
            setup=setup, model=ModelType.ICT2022,
            entry_price=entry, stop_loss=sl, tp1=tp1, tp2=tp2, rr=rr,
            now=now, entry_tf=fvg_tf, confluence_desc=desc,
            fvg=post_cisd_fvg, cisd_bonus=True,
        )

    # ── Signal construction helpers ───────────────────────────────────────────

    def _sweep_wick_price(self, setup: Setup) -> float:
        """Return the wick extreme of the manipulation leg for chart drawing.

        Uses leg_extreme_candle when available (the actual wick extreme of the
        full leg), otherwise falls back to sweep_candle (the close-back candle).
        """
        candle = setup.sweep.leg_extreme_candle or setup.sweep.sweep_candle
        return candle.low if setup.direction == TradeDirection.LONG else candle.high

    @staticmethod
    def _fvg_kind_str(fvg: FVG) -> str:
        """Return the FVG kind as a plain string ('bullish' or 'bearish')."""
        return fvg.kind.value if hasattr(fvg.kind, "value") else str(fvg.kind)

    def _make_signal(
        self,
        setup: Setup,
        model: ModelType,
        entry_price: float,
        stop_loss: float,
        tp1: float,
        tp2: Optional[float],
        rr: float,
        now: datetime,
        entry_tf: int,
        confluence_desc: str,
        fvg: Optional[FVG] = None,
        cisd_bonus: Optional[bool] = None,
    ) -> Signal:
        """
        Construct a Signal with all common fields pre-filled.

        Callers pass only the fields that differ between models; sweep_wick and
        SMT drawing coordinates are derived from setup in a single place.
        cisd_bonus defaults to setup.cisd_confirmed when not provided.
        """
        smt = setup.smt
        return Signal(
            setup=setup,
            model=model,
            direction=setup.direction,
            symbol=self._pick_symbol(setup),
            entry_price=entry_price,
            stop_loss=stop_loss,
            tp1=tp1,
            tp2=tp2,
            rr_ratio=rr,
            session=active_session(now) or "",
            ts=now,
            entry_tf=entry_tf,
            confluence_desc=confluence_desc,
            fvg_top=fvg.top if fvg else None,
            fvg_bottom=fvg.bottom if fvg else None,
            fvg_ts=fvg.ts if fvg else None,
            fvg_kind=self._fvg_kind_str(fvg) if fvg else None,
            sweep_wick=self._sweep_wick_price(setup),
            smt_ts_a=smt.ts_a if smt else None,
            smt_price_a=(smt.low_a or smt.high_a) if smt else None,
            smt_ts_b=smt.ts_b if smt else None,
            smt_price_b=(smt.low_b or smt.high_b) if smt else None,
            smt_bonus=setup.smt_confirmed,
            cisd_bonus=cisd_bonus if cisd_bonus is not None else setup.cisd_confirmed,
        )

    def _try_sweep_entry(
        self, setup: Setup, candle: Candle, now: datetime
    ) -> Optional[Signal]:
        """Sweep-only model: enter at the close of the sweep candle itself.

        No IFVG or any other confluence required — the sweep IS the signal.
        Used to validate that the sweep detection and level quality are correct
        before layering confluence filters on top.
        """
        sl, tp1, tp2, tp1_label = self._calculate_targets(setup, candle)
        rr = self._calc_rr(candle.close, sl, tp1)
        if rr < self.min_rr:
            return None

        sweep = setup.sweep
        direction_label = "Bullish" if setup.direction == TradeDirection.LONG else "Bearish"
        kind = self._KIND_LABELS.get(sweep.level.kind, sweep.level.kind.replace("_", " ").title())
        desc = f"{direction_label} sweep of {kind} ({sweep.level.tier.value}-tier) | sweep-entry"

        return self._make_signal(
            setup=setup, model=ModelType.SWEEP,
            entry_price=candle.close, stop_loss=sl, tp1=tp1, tp2=tp2, rr=rr,
            now=now, entry_tf=1, confluence_desc=desc,
        )

    # ── Sweep quality gates ───────────────────────────────────────────────────

    # Base minimums — all scale up with ATR at runtime (see _compute_atr)
    _BASE_MIN_WICK_PENETRATION = 3.0   # pts floor
    _BASE_MIN_LEG_SIZE         = 10.0  # pts floor
    _BASE_MIN_CLOSE_RETURN     = 1.0   # pts floor

    # ATR multipliers — thresholds = max(base, atr * multiplier)
    _ATR_MULT_WICK       = 0.15   # 15% ATR for wick penetration (S/A-tier)
    _ATR_MULT_WICK_B     = 0.20   # 20% ATR for wick penetration (B-tier — slightly stricter)
    _ATR_MULT_LEG        = 0.80   # 80% ATR for leg size
    _ATR_MULT_CLOSE      = 0.05   # 5% ATR for body return

    # Sweep candle pin-bar shape check (not ATR-scaled)
    _MIN_WICK_BODY_RATIO = 0.20   # wick >= 20% of total candle range

    def _compute_atr(self, candles: list[Candle], period: int = 14) -> float:
        """ATR(14) from 1m candles. Falls back to 15.0 (typical NQ 1m ATR) if insufficient data."""
        if len(candles) < period + 1:
            return 15.0
        trs = []
        for i in range(1, len(candles)):
            c = candles[i]
            prev_close = candles[i - 1].close
            tr = max(c.high - c.low, abs(c.high - prev_close), abs(c.low - prev_close))
            trs.append(tr)
        return sum(trs[-period:]) / period

    def _sweep_has_valid_penetration(self, sweep: "Sweep", atr14: float = 15.0) -> bool:
        """
        Three checks on the sweep candle itself:
        1. Wick extends >= max(3.0, atr14 * 0.15) pts beyond the level
           → measured on sweep_candle (the close-back candle)
        2. Wick through level is >= 20% of total candle range (pin bar shape)
           → measured on sweep_candle
        3. Body closes >= max(1.0, atr14 * 0.05) pts back inside the level
           → measured on sweep_candle (body is always inside by design)

        All three checks use the same sweep_candle so that the actual close-back
        candle must itself demonstrate meaningful wick penetration.
        """
        c = sweep.sweep_candle            # close-back candle — body is inside the level

        total_range = c.high - c.low
        if total_range == 0:
            return False

        # B-tier levels require a larger wick — less reliable
        wick_mult = (
            self._ATR_MULT_WICK_B
            if sweep.level.tier == LiqTier.B
            else self._ATR_MULT_WICK
        )
        min_wick = max(self._BASE_MIN_WICK_PENETRATION, atr14 * wick_mult)
        min_close = max(self._BASE_MIN_CLOSE_RETURN, atr14 * self._ATR_MULT_CLOSE)

        if sweep.direction.value == "bullish":
            wick_through = sweep.level.price - c.low   # sweep_candle wick depth
            close_return = c.body_low - sweep.level.price  # close-back candle body
            return (
                wick_through >= min_wick
                and (c.lower_wick / total_range) >= self._MIN_WICK_BODY_RATIO
                and close_return >= min_close
            )
        else:
            wick_through = c.high - sweep.level.price  # sweep_candle wick height
            close_return = sweep.level.price - c.body_high  # close-back candle body
            return (
                wick_through >= min_wick
                and (c.upper_wick / total_range) >= self._MIN_WICK_BODY_RATIO
                and close_return >= min_close
            )

    def _leg_is_significant(self, sweep: "Sweep", candles_1m: list[Candle], atr14: float = 15.0) -> bool:
        """
        The manipulation leg must cover at least max(10.0, atr14 * 0.80) pts.
        Measures the max range across ALL candles from leg_start to sweep candle.
        Scales with ATR — during volatile sessions, requires a proportionally larger leg.
        """
        if not candles_1m:
            return True

        min_leg = max(self._BASE_MIN_LEG_SIZE, atr14 * self._ATR_MULT_LEG)
        c = sweep.sweep_candle

        if sweep.leg_start_ts:
            leg_candles = [x for x in candles_1m
                           if sweep.leg_start_ts <= x.ts <= c.ts]
        else:
            idx = next((i for i, x in enumerate(candles_1m) if x.ts == c.ts), None)
            if idx is None:
                return True
            leg_candles = candles_1m[max(0, idx - 30): idx + 1]

        if not leg_candles:
            return True

        if sweep.direction.value == "bullish":
            leg_high = max(x.high for x in leg_candles)
            return (leg_high - c.low) >= min_leg
        else:
            leg_low = min(x.low for x in leg_candles)
            return (c.high - leg_low) >= min_leg

    # ── IFVG close quality filters ────────────────────────────────────────────

    _MIN_BODY_DOMINANCE = 0.50   # body must be >= 50% of total candle range

    def _ifvg_close_is_body_dominant(self, candle: Candle) -> bool:
        """
        Inversion candle must have a body >= 50% of total range.
        Wick-dominant closes show rejection, not committed delivery.
        """
        total_range = candle.high - candle.low
        if total_range <= 0:
            return True   # flat candle — allow through (edge case)
        body = abs(candle.close - candle.open)
        return body / total_range >= self._MIN_BODY_DOMINANCE

    _STRONG_INVERSION_MIN_PTS = 2.0   # minimum close beyond FVG far edge

    def _ifvg_close_is_strong(self, ifvg: "IFVG", candle: Candle) -> bool:
        """
        Priority 4 (research synthesis): close must be ≥ 2pt beyond the FVG far edge.
        Barely clipping the edge = weak inversion = likely failure.
        Source: FfFt0L-NyDI + 9hmFnAbu5xo — "want strong displacement through".
        """
        fvg = ifvg.source_fvg
        if ifvg.direction == IFVGDirection.BULLISH:
            # Bearish FVG inversed: close must be 2pt above fvg.top
            return (candle.close - fvg.top) >= self._STRONG_INVERSION_MIN_PTS
        else:
            # Bullish FVG inversed: close must be 2pt below fvg.bottom
            return (fvg.bottom - candle.close) >= self._STRONG_INVERSION_MIN_PTS

    # Buffer below/above the sweep wick when placing SL
    _SL_BUFFER = 2.0
    # Minimum distance (points) between entry and TP — levels closer than this are ignored
    _MIN_TP_POINTS = 15.0

    def _calculate_targets(
        self, setup: Setup, candle: Candle
    ) -> tuple[float, Optional[float], Optional[float], Optional[str]]:
        """
        SL: beyond the sweep candle wick + buffer.
        TP1: fixed 1R (entry ± risk distance).  Simple, consistent.
        TP2: nearest opposing major liquidity (DOL target) — runner label/reference only.
        tp1_label: DOL level nearest to the fixed 1R TP (informational).

        STEP 5 (master plan): TP is always 1:1. DOL lookup is kept for labelling only.
        No RR-aware DOL skipping — the 1R TP always fires.
        """
        entry = candle.close

        # Use leg_extreme_candle for SL (actual wick extreme) if available,
        # else fall back to sweep_candle (the close-back detection candle)
        sl_candle = setup.sweep.leg_extreme_candle or setup.sweep.sweep_candle
        if setup.direction == TradeDirection.LONG:
            sl = sl_candle.low - self._SL_BUFFER
            risk = abs(entry - sl)
            tp1 = entry + risk          # fixed 1R
            dol, _, tp1_label = self._find_dol_targets(entry, above=True)
            tp2 = dol   # DOL as runner reference — may be None
        else:
            sl = sl_candle.high + self._SL_BUFFER
            risk = abs(entry - sl)
            tp1 = entry - risk          # fixed 1R
            dol, _, tp1_label = self._find_dol_targets(entry, above=False)
            tp2 = dol   # DOL as runner reference — may be None

        return sl, tp1, tp2, tp1_label

    # DOL tier priority: S (EQH/EQL) → A (unmitigated FVGs) → B (session/PDH/PDL/gaps)
    # Per cheat sheet: #1 EQH/EQL, #2 Unmitigated FVGs, #3 Session/PDH, #4 Data H/L, #5 Intermediate
    _DOL_TIER_RANK = {LiqTier.S: 0, LiqTier.A: 1, LiqTier.B: 2}
    _DOL_VALID_TIERS = {LiqTier.S, LiqTier.A, LiqTier.B}

    def _find_dol_targets(
        self, entry: float, above: bool, sl: float = 0.0, min_rr: float = 0.0
    ) -> tuple[Optional[float], Optional[float], Optional[str]]:
        """Return DOL targets on the target side (informational — TP1 is always 1R).

        Sorted by tier (S > A > B) first, then by proximity within the same tier.
        Only S/A/B tier levels are valid DOL targets per the DOL cheat sheet.
        sl and min_rr kept for signature compat (Step 5 — TP is always 1R).
        """
        candidates = []
        for level in self._liquidity_levels:
            if level.tier not in self._DOL_VALID_TIERS:
                continue
            if above and level.price > entry + self._MIN_TP_POINTS:
                candidates.append((level.price, level.kind, level.tier))
            elif not above and level.price < entry - self._MIN_TP_POINTS:
                candidates.append((level.price, level.kind, level.tier))

        if not candidates:
            return None, None, None

        # Prefer highest tier (S over A over B). Within same tier, prefer nearest.
        candidates.sort(key=lambda x: (
            self._DOL_TIER_RANK.get(x[2], 9),
            x[0] if above else -x[0],
        ))

        tp1 = candidates[0]
        tp2 = candidates[1] if len(candidates) > 1 else None

        tp1_price = tp1[0]
        tp1_label = f"{tp1[1]} ({tp1[2].value})"
        tp2_price = tp2[0] if tp2 else None
        return tp1_price, tp2_price, tp1_label


    # HTF alignment gate — minimum 4H momentum (points) to block a counter-trend entry.
    # Only applies when the 4H trend is DECISIVE enough to be meaningful.
    # Too low: over-filters choppy/ranging days. Too high: never activates.
    # 150pts ≈ 0.75% of ~20k NQ — a clear directional 4H move, not just noise.
    # Measured over 3 × 4H bars (12 hours) to capture intraday regime, not multi-day.
    _HTF_REGIME_THRESHOLD_PTS = 150.0
    _HTF_REGIME_LOOKBACK_BARS = 3  # 3 × 4H = 12 hours

    def _htf_regime_allows(
        self, direction: "TradeDirection", candles_by_tf: dict[int, list["Candle"]]
    ) -> bool:
        """
        Returns True when the 4H regime is either aligned with `direction` or too
        ambiguous to filter (< threshold momentum). Returns False only when the 4H
        trend is decisively AGAINST the proposed trade direction.

        Logic: compare last 4H close to the close N bars ago. If the move is large
        (> _HTF_REGIME_THRESHOLD_PTS), it's a decisive trend — block the opposing
        direction. If small, we're ranging — allow both directions.

        Falls back to True (allow) when 4H data is insufficient.
        """
        candles_4h = candles_by_tf.get(240, [])
        n = self._HTF_REGIME_LOOKBACK_BARS
        if len(candles_4h) < n + 1:
            return True   # not enough 4H history — don't filter

        current_close = candles_4h[-1].close
        prior_close = candles_4h[-1 - n].close
        momentum = current_close - prior_close

        if momentum > self._HTF_REGIME_THRESHOLD_PTS:
            # Decisive 4H bullish move — block SHORT entries
            return direction == TradeDirection.LONG
        elif momentum < -self._HTF_REGIME_THRESHOLD_PTS:
            # Decisive 4H bearish move — block LONG entries
            return direction == TradeDirection.SHORT
        return True  # ranging / ambiguous — allow both directions

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
        # Legacy fallback (pre-TF labels)
        "fvg_high": "HTF FVG High", "fvg_low": "HTF FVG Low",
        "nwog_high": "NWOG High", "nwog_low": "NWOG Low",
        "ndog_high": "NDOG High", "ndog_low": "NDOG Low",
        # TF-specific FVG labels (e.g. "15m_fvg_high")
        "15m_fvg_high": "15m FVG High", "15m_fvg_low": "15m FVG Low",
        "30m_fvg_high": "30m FVG High", "30m_fvg_low": "30m FVG Low",
        "60m_fvg_high": "1H FVG High",  "60m_fvg_low": "1H FVG Low",
        "240m_fvg_high": "4H FVG High", "240m_fvg_low": "4H FVG Low",
    }

    def _build_confluence_desc(
        self,
        setup: Setup,
        model: ModelType,
        entry_tf: int,
        ifvg: Optional[IFVG] = None,
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

        # FVG context: if the swept level was an HTF FVG edge, note which TF
        if "fvg" in kind_raw:
            # kind is e.g. "60m_fvg_high" → label is "1H FVG" → extract cleanly
            tf_label = kind.rsplit(" FVG", 1)[0] if " FVG" in kind else "HTF"
            parts.append(f"{tf_label} FVG liquidity zone")

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
