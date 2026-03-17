"""Portfolio decision engine: convert thesis state + conviction + valuation + context
into explicit portfolio actions under capital constraints.

All decision logic is deterministic code. LLM is not used here.

Decision precedence for holdings (strongest wins, checked in this order):
  Priority 1 — FORCED EXIT:  thesis broken
  Priority 2 — STRONG EXIT:  conviction critically low (≤ 25),
                              thesis achieved + not BUY, FULL_EXIT valuation zone
  Priority 3 — DEFENSIVE:    trim on low conviction (≤ 35), trim on stretched valuation
  Priority 4 — GROWTH:       add to winner, add to loser (with evidence)
  Priority 5 — NEUTRAL:      hold

A stronger rule always takes precedence over a weaker one. For example,
conviction ≤ 25 produces EXIT. Thesis broken produces EXIT regardless of
valuation zone.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Optional

from models import (
    ActionType, ThesisState, ZoneState, PositionStatus,
)
from exit_policy import ExitPolicyConfig, ExitPolicyMode, BASELINE_POLICY, GRADUATED_POLICY
from valuation_policy import zone_from_thesis_and_price, ZoneThresholds, DEFAULT_THRESHOLDS
from price_momentum import (
    MomentumGuardConfig, MomentumSignals,
    DISABLED_MOMENTUM_CONFIG, ENABLED_MOMENTUM_CONFIG,
)
from market_sentiment import (
    MarketSentimentScore, MarketRegime,
    MarketSentimentConfig, DISABLED_SENTIMENT_CONFIG,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Reason codes
# ---------------------------------------------------------------------------

class ReasonCode(str, Enum):
    THESIS_STRENGTHENING = "THESIS_STRENGTHENING"
    THESIS_WEAKENING = "THESIS_WEAKENING"
    THESIS_BROKEN = "THESIS_BROKEN"
    THESIS_ACHIEVED = "THESIS_ACHIEVED"
    THESIS_FORMING = "THESIS_FORMING"
    VALUATION_ATTRACTIVE = "VALUATION_ATTRACTIVE"
    VALUATION_STRETCHED = "VALUATION_STRETCHED"
    VALUATION_NEUTRAL = "VALUATION_NEUTRAL"
    CHECKPOINT_AHEAD = "CHECKPOINT_AHEAD"
    NO_CHECKPOINT_AHEAD = "NO_CHECKPOINT_AHEAD"
    INSUFFICIENT_NOVEL_EVIDENCE = "INSUFFICIENT_NOVEL_EVIDENCE"
    SUFFICIENT_NOVEL_EVIDENCE = "SUFFICIENT_NOVEL_EVIDENCE"
    BETTER_THAN_WEAKEST_HOLDING = "BETTER_THAN_WEAKEST_HOLDING"
    FAILED_RELATIVE_HURDLE = "FAILED_RELATIVE_HURDLE"
    PROBATION_ACTIVE = "PROBATION_ACTIVE"
    PROBATION_EXPIRED = "PROBATION_EXPIRED"
    COOLDOWN_ACTIVE = "COOLDOWN_ACTIVE"
    TURNOVER_LIMIT = "TURNOVER_LIMIT"
    NO_THESIS = "NO_THESIS"
    CONVICTION_HIGH = "CONVICTION_HIGH"
    CONVICTION_LOW = "CONVICTION_LOW"
    ADD_TO_WINNER = "ADD_TO_WINNER"
    ADD_TO_LOSER_CONFIRMED = "ADD_TO_LOSER_CONFIRMED"
    PRICE_MOVE_ALERT = "PRICE_MOVE_ALERT"
    NO_IMPROVEMENT_ON_PROBATION = "NO_IMPROVEMENT_ON_PROBATION"
    THESIS_ACHIEVED_EXHAUSTED = "THESIS_ACHIEVED_EXHAUSTED"
    CAPITAL_CHALLENGER = "CAPITAL_CHALLENGER"
    FUNDED_BY_TRIM = "FUNDED_BY_TRIM"
    FUNDED_BY_EXIT = "FUNDED_BY_EXIT"
    # Momentum guard reason codes
    MOMENTUM_BELOW_SMA = "MOMENTUM_BELOW_SMA"
    STOP_LOSS_TRIGGERED = "STOP_LOSS_TRIGGERED"
    TRAILING_STOP_TRIGGERED = "TRAILING_STOP_TRIGGERED"
    UNDERWATER_ADD_BLOCKED = "UNDERWATER_ADD_BLOCKED"
    MARKET_REGIME_BEARISH = "MARKET_REGIME_BEARISH"
    OVERBOUGHT_ADD_BLOCKED = "OVERBOUGHT_ADD_BLOCKED"
    OVERBOUGHT_INITIATE_BLOCKED = "OVERBOUGHT_INITIATE_BLOCKED"
    # Market sentiment reason codes
    MARKET_SENTIMENT_RISK_OFF = "MARKET_SENTIMENT_RISK_OFF"
    MARKET_SENTIMENT_EXTREME_FEAR = "MARKET_SENTIMENT_EXTREME_FEAR"
    # Conviction decay
    CONVICTION_DECAYED = "CONVICTION_DECAYED"
    # Priced-in detection
    PRICED_IN_DAMPENED = "PRICED_IN_DAMPENED"
    # Sector concentration
    SECTOR_CAP_REACHED = "SECTOR_CAP_REACHED"


# ---------------------------------------------------------------------------
# Recommendation priority tiers (lower number = higher precedence)
# ---------------------------------------------------------------------------

PRIORITY_FORCED_EXIT = 1       # thesis broken
PRIORITY_STRONG_EXIT = 2       # critical conviction, achieved+exhausted, FULL_EXIT zone
PRIORITY_DEFENSIVE = 3         # trim (low conviction or stretched valuation)
PRIORITY_CAPITAL_REDEPLOY = 4  # funded initiations
PRIORITY_GROWTH = 5            # adds, unfunded initiations
PRIORITY_NEUTRAL = 6           # hold, no_action


# ---------------------------------------------------------------------------
# Input snapshots
# ---------------------------------------------------------------------------

@dataclass
class HoldingSnapshot:
    """Point-in-time view of a current holding for decision evaluation."""
    ticker: str
    position_id: int
    thesis_id: int
    thesis_state: ThesisState
    conviction_score: float          # 0-100
    current_weight: float            # portfolio weight %
    target_weight: float
    avg_cost: float
    current_price: Optional[float] = None
    valuation_gap_pct: Optional[float] = None
    base_case_rerating: Optional[float] = None
    zone_state: ZoneState = ZoneState.HOLD
    probation_flag: bool = False
    probation_start_date: Optional[date] = None
    probation_reviews_count: int = 0
    has_checkpoint_ahead: bool = False
    days_to_checkpoint: Optional[int] = None
    novel_claim_count_7d: int = 0       # new/confirming claims in last 7 days
    confirming_claim_count_7d: int = 0
    price_change_pct_5d: Optional[float] = None   # 5-day price move %
    prior_conviction: Optional[float] = None       # conviction at previous review (for graduated policy)
    claim_impact_signal: float = 0.0               # weighted expected-impact from recent claims (from profiler)
    add_count: int = 0                             # number of adds already made to this position
    sector: Optional[str] = None                   # GICS sector for concentration tracking
    momentum: MomentumSignals = field(default_factory=MomentumSignals)


@dataclass
class CandidateSnapshot:
    """Point-in-time view of a candidate for initiation evaluation."""
    ticker: str
    candidate_id: Optional[int] = None
    thesis_id: Optional[int] = None
    thesis_state: Optional[ThesisState] = None
    conviction_score: Optional[float] = None
    valuation_gap_pct: Optional[float] = None
    base_case_rerating: Optional[float] = None
    current_price: Optional[float] = None
    zone_state: Optional[ZoneState] = None
    has_checkpoint_ahead: bool = False
    days_to_checkpoint: Optional[int] = None
    novel_claim_count_7d: int = 0
    confirming_claim_count_7d: int = 0
    claim_impact_signal: float = 0.0               # weighted expected-impact from recent claims
    cooldown_flag: bool = False
    cooldown_until: Optional[date] = None
    watch_reason: Optional[str] = None
    sector: Optional[str] = None                   # GICS sector for concentration tracking
    momentum: MomentumSignals = field(default_factory=MomentumSignals)


@dataclass
class DecisionInput:
    """All inputs needed for one portfolio review cycle."""
    review_date: date
    holdings: list[HoldingSnapshot] = field(default_factory=list)
    candidates: list[CandidateSnapshot] = field(default_factory=list)
    total_portfolio_weight: float = 100.0     # sum of current weights (should be ~100)
    weekly_turnover_cap_pct: float = 20.0     # max % of portfolio that can change in one week
    max_position_weight: float = 10.0         # max single position weight %
    min_initiation_weight: float = 2.0        # minimum starting weight %
    max_satellite_positions: int = 10         # max number of non-core positions
    max_initiations_per_review: int = 3       # pace deployment: max new positions per review cycle
    zone_thresholds: ZoneThresholds = field(default_factory=lambda: DEFAULT_THRESHOLDS)
    relaxed_gates: bool = False               # relax entry gates for historical usefulness runs
    exit_policy: ExitPolicyConfig = field(default_factory=lambda: GRADUATED_POLICY)
    momentum_config: MomentumGuardConfig = field(default_factory=lambda: ENABLED_MOMENTUM_CONFIG)
    max_sector_weight: float = 30.0               # max % of portfolio in any single sector
    market_sentiment: Optional[MarketSentimentScore] = None  # macro risk-on/risk-off signal


# ---------------------------------------------------------------------------
# Decision output
# ---------------------------------------------------------------------------

@dataclass
class TickerDecision:
    """Structured recommendation for one ticker.

    This is a recommendation object, not an execution record.
    Fields like funded_by_* and state_mutation_* support Step 8 replay/audit.
    """
    ticker: str
    action: ActionType
    action_score: float = 0.0                   # higher = more urgent
    thesis_conviction: float = 0.0              # raw thesis conviction (0-100), preserved for all actions
    recommendation_priority: int = PRIORITY_NEUTRAL  # deterministic tier (1=highest)
    target_weight_change: Optional[float] = None
    suggested_weight: Optional[float] = None
    reason_codes: list[ReasonCode] = field(default_factory=list)
    rationale: str = ""
    blocking_conditions: list[str] = field(default_factory=list)
    required_followup: list[str] = field(default_factory=list)
    generated_at: datetime = field(default_factory=datetime.utcnow)
    # Funded pairing: set when initiation requires capital from existing holdings
    funded_by_ticker: Optional[str] = None
    funded_by_action: Optional[ActionType] = None
    # Audit trail: what review-level state mutation occurred (if any)
    decision_stage: str = "recommendation"       # "recommendation" or "blocked"
    state_mutation_performed: bool = False
    state_mutation_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "action": self.action.value,
            "action_score": round(self.action_score, 2),
            "thesis_conviction": round(self.thesis_conviction, 2),
            "recommendation_priority": self.recommendation_priority,
            "target_weight_change": round(self.target_weight_change, 2) if self.target_weight_change is not None else None,
            "suggested_weight": round(self.suggested_weight, 2) if self.suggested_weight is not None else None,
            "reason_codes": [r.value for r in self.reason_codes],
            "rationale": self.rationale,
            "blocking_conditions": self.blocking_conditions,
            "required_followup": self.required_followup,
            "generated_at": self.generated_at.isoformat(),
            "funded_by_ticker": self.funded_by_ticker,
            "funded_by_action": self.funded_by_action.value if self.funded_by_action else None,
            "decision_stage": self.decision_stage,
            "state_mutation_performed": self.state_mutation_performed,
            "state_mutation_notes": self.state_mutation_notes,
        }


@dataclass
class PortfolioReviewResult:
    """Output of a full portfolio review cycle."""
    review_date: date
    review_type: str = "weekly"
    decisions: list[TickerDecision] = field(default_factory=list)
    turnover_pct_planned: float = 0.0
    turnover_pct_cap: float = 20.0
    blocked_actions: list[dict] = field(default_factory=list)

    @property
    def initiations(self) -> list[TickerDecision]:
        return [d for d in self.decisions if d.action == ActionType.INITIATE]

    @property
    def adds(self) -> list[TickerDecision]:
        return [d for d in self.decisions if d.action == ActionType.ADD]

    @property
    def trims(self) -> list[TickerDecision]:
        return [d for d in self.decisions if d.action == ActionType.TRIM]

    @property
    def exits(self) -> list[TickerDecision]:
        return [d for d in self.decisions if d.action == ActionType.EXIT]

    @property
    def probations(self) -> list[TickerDecision]:
        return [d for d in self.decisions if d.action == ActionType.PROBATION]

    @property
    def holds(self) -> list[TickerDecision]:
        return [d for d in self.decisions if d.action == ActionType.HOLD]

    def to_dict(self) -> dict:
        return {
            "review_date": self.review_date.isoformat(),
            "review_type": self.review_type,
            "turnover_pct_planned": round(self.turnover_pct_planned, 2),
            "turnover_pct_cap": self.turnover_pct_cap,
            "summary": {
                "initiations": len(self.initiations),
                "adds": len(self.adds),
                "trims": len(self.trims),
                "exits": len(self.exits),
                "probations": len(self.probations),
                "holds": len(self.holds),
                "total_decisions": len(self.decisions),
            },
            "decisions": [d.to_dict() for d in self.decisions],
            "blocked_actions": self.blocked_actions,
        }


# ---------------------------------------------------------------------------
# Engine configuration
# ---------------------------------------------------------------------------

# Conviction thresholds (0-100 scale, matching thesis_update_service)
INITIATION_CONVICTION_FLOOR = 55.0      # absolute minimum for initiation
RELATIVE_HURDLE_MARGIN = 5.0            # candidate must beat weakest holding by this margin
ADD_CONVICTION_FLOOR = 60.0             # minimum conviction for adds (above default 50)
TRIM_CONVICTION_CEILING = 40.0          # trim if conviction drops below this
EXIT_CONVICTION_CEILING = 25.0          # force exit below this
PROBATION_CONVICTION_CEILING = 35.0     # enter probation below this

# Trim threshold (replaces probation system — simpler, more defensible)
TRIM_CONVICTION_THRESHOLD = 35.0        # trim when conviction falls to this level

# Cooldown
COOLDOWN_DAYS = 14                      # re-entry blocked for 2 weeks after exit

# Weight sizing
DEFAULT_INITIATION_WEIGHT = 3.0         # starting weight for new positions (fallback)
ADD_INCREMENT = 1.5                     # weight increment per add (fallback)
TRIM_DECREMENT = 2.0                    # weight decrement per trim
MAX_POSITION_WEIGHT = 10.0              # hard cap per position


def conviction_weighted_initiation_size(conviction: float) -> float:
    """Scale initiation weight by conviction score (smooth linear curve).

    conviction 40 (floor) -> 1.0%   — low conviction, minimal sizing
    conviction 50         -> 2.5%
    conviction 60         -> 4.0%
    conviction 65         -> 4.75%
    conviction 70         -> 5.5%
    conviction 75         -> 6.25%
    conviction 80+        -> 7.0%   — high conviction, max sizing

    Every point of conviction earns proportional sizing.
    """
    floor_conv, floor_wt = 40.0, 1.0
    ceil_conv, ceil_wt = 80.0, 7.0
    if conviction <= floor_conv:
        return floor_wt
    if conviction >= ceil_conv:
        return ceil_wt
    t = (conviction - floor_conv) / (ceil_conv - floor_conv)
    return round(floor_wt + t * (ceil_wt - floor_wt), 1)


def conviction_weighted_add_increment(conviction: float, current_weight: float) -> float:
    """Scale add increment by conviction. Higher conviction -> larger adds.

    conviction 50-60  -> 1.0% add
    conviction 60-70  -> 1.5% add
    conviction 70-80  -> 2.0% add
    conviction 80+    -> 2.5% add

    Capped so total never exceeds MAX_POSITION_WEIGHT.
    """
    if conviction >= 80:
        increment = 2.5
    elif conviction >= 70:
        increment = 2.0
    elif conviction >= 60:
        increment = 1.5
    else:
        increment = 1.0
    return min(increment, MAX_POSITION_WEIGHT - current_weight)

# Price move threshold
IMMEDIATE_REVIEW_PRICE_MOVE_PCT = 8.0   # flag for immediate review


# ---------------------------------------------------------------------------
# Core decision logic: per-holding evaluation
# ---------------------------------------------------------------------------

def evaluate_holding(
    holding: HoldingSnapshot,
    review_date: date,
    exit_policy: ExitPolicyConfig = BASELINE_POLICY,
    relaxed_gates: bool = False,
    momentum_config: MomentumGuardConfig = ENABLED_MOMENTUM_CONFIG,
) -> TickerDecision:
    """Evaluate a current holding and produce a decision.

    This is pure deterministic logic using thesis state, conviction, valuation zone,
    and checkpoint context. The exit_policy controls thresholds for probation/exit.

    Decision precedence (checked in this order — first match wins):
      1. FORCED EXIT:  thesis broken (score 100)
      2. STRONG EXIT:  thesis achieved + not in BUY zone (score 85)
      3. STRONG EXIT:  FULL_EXIT valuation zone (score 80)
      4. STRONG EXIT:  conviction critically low ≤25 (score 95)
        - graduated mode: also immediate exit on sharp conviction drop
      5. DEFENSIVE:    trim on low conviction ≤35 (score 65)
      6. DEFENSIVE:    trim on TRIM zone or conviction < 40 + weakening (score 55-70)
      7. GROWTH:       add to winner or loser (score 40-55)
      8. NEUTRAL:      hold (score 0)
    """
    decision = TickerDecision(ticker=holding.ticker, action=ActionType.HOLD)
    decision.thesis_conviction = holding.conviction_score
    reasons: list[ReasonCode] = []

    # --- Immediate review trigger (informational, does not imply execution) ---
    if holding.price_change_pct_5d is not None and abs(holding.price_change_pct_5d) >= IMMEDIATE_REVIEW_PRICE_MOVE_PCT:
        decision.required_followup.append(
            f"Price moved {holding.price_change_pct_5d:+.1f}% in 5 days — immediate review needed"
        )
        reasons.append(ReasonCode.PRICE_MOVE_ALERT)

    # --- Compute zone from available data ---
    zone = zone_from_thesis_and_price(
        holding.valuation_gap_pct,
        holding.base_case_rerating,
        holding.current_price,
    )
    # In relaxed mode (usefulness runs), treat missing valuation data as BUY
    # so that add-to-winner/loser logic can fire
    if relaxed_gates and zone == ZoneState.HOLD and holding.valuation_gap_pct is None:
        zone = ZoneState.BUY

    # ---------------------------------------------------------------
    # Priority 1 — FORCED EXIT: thesis broken (strongest rule)
    # ---------------------------------------------------------------
    if holding.thesis_state == ThesisState.BROKEN:
        decision.action = ActionType.EXIT
        decision.action_score = 100.0
        decision.recommendation_priority = PRIORITY_FORCED_EXIT
        decision.target_weight_change = -holding.current_weight
        decision.suggested_weight = 0.0
        reasons.append(ReasonCode.THESIS_BROKEN)
        decision.rationale = "Thesis broken — forced exit"
        decision.reason_codes = reasons
        return decision

    # ---------------------------------------------------------------
    # Priority 2 — STRONG EXIT: thesis achieved + not in BUY zone
    # ---------------------------------------------------------------
    if holding.thesis_state == ThesisState.ACHIEVED and zone != ZoneState.BUY:
        decision.action = ActionType.EXIT
        decision.action_score = 85.0
        decision.recommendation_priority = PRIORITY_STRONG_EXIT
        decision.target_weight_change = -holding.current_weight
        decision.suggested_weight = 0.0
        reasons.append(ReasonCode.THESIS_ACHIEVED_EXHAUSTED)
        decision.rationale = "Thesis achieved and valuation no longer attractive — exit"
        decision.reason_codes = reasons
        return decision

    # ---------------------------------------------------------------
    # Priority 2 — STRONG EXIT: FULL_EXIT valuation zone
    # ---------------------------------------------------------------
    if zone == ZoneState.FULL_EXIT:
        decision.action = ActionType.EXIT
        decision.action_score = 80.0
        decision.recommendation_priority = PRIORITY_STRONG_EXIT
        decision.target_weight_change = -holding.current_weight
        decision.suggested_weight = 0.0
        reasons.append(ReasonCode.VALUATION_STRETCHED)
        decision.rationale = "Valuation in full exit zone"
        decision.reason_codes = reasons
        return decision

    # ---------------------------------------------------------------
    # Priority 2 — STRONG EXIT: graduated policy — sharp conviction drop
    # If conviction dropped by more than sharp_drop_threshold in one
    # review period, exit immediately regardless of absolute level.
    # ---------------------------------------------------------------
    if exit_policy.mode == ExitPolicyMode.GRADUATED and holding.prior_conviction is not None:
        drop = holding.prior_conviction - holding.conviction_score
        if drop >= exit_policy.sharp_drop_threshold:
            decision.action = ActionType.EXIT
            decision.action_score = 92.0
            decision.recommendation_priority = PRIORITY_STRONG_EXIT
            decision.target_weight_change = -holding.current_weight
            decision.suggested_weight = 0.0
            reasons.append(ReasonCode.CONVICTION_LOW)
            decision.rationale = (
                f"Sharp conviction drop {drop:.0f}pts "
                f"({holding.prior_conviction:.0f} -> {holding.conviction_score:.0f}) "
                f"— graduated policy immediate exit"
            )
            decision.reason_codes = reasons
            return decision

    # ---------------------------------------------------------------
    # Priority 2 — STRONG EXIT: conviction critically low
    # Must be checked BEFORE probation entry (conviction ≤ exit_ceiling is
    # a subset of conviction ≤ probation_ceiling, so without this ordering
    # the weaker probation rule would swallow the stronger exit rule).
    # ---------------------------------------------------------------
    if holding.conviction_score <= exit_policy.exit_conviction_ceiling:
        decision.action = ActionType.EXIT
        decision.action_score = 95.0
        decision.recommendation_priority = PRIORITY_STRONG_EXIT
        decision.target_weight_change = -holding.current_weight
        decision.suggested_weight = 0.0
        reasons.append(ReasonCode.CONVICTION_LOW)
        decision.rationale = f"Conviction {holding.conviction_score:.0f} critically low — exit"
        decision.reason_codes = reasons
        return decision

    # ---------------------------------------------------------------
    # Priority 2.5 — MOMENTUM: stop-loss from cost basis
    # ---------------------------------------------------------------
    if momentum_config.enabled and momentum_config.stop_loss_enabled:
        dd_cost = holding.momentum.drawdown_from_cost_pct
        if dd_cost is not None:
            if dd_cost <= momentum_config.stop_loss_exit_pct:
                decision.action = ActionType.EXIT
                decision.action_score = 88.0
                decision.recommendation_priority = PRIORITY_STRONG_EXIT
                decision.target_weight_change = -holding.current_weight
                decision.suggested_weight = 0.0
                reasons.append(ReasonCode.STOP_LOSS_TRIGGERED)
                decision.rationale = (
                    f"Stop-loss EXIT: position {dd_cost:.1f}% below cost basis "
                    f"(threshold {momentum_config.stop_loss_exit_pct:.0f}%)"
                )
                decision.reason_codes = reasons
                return decision
            elif dd_cost <= momentum_config.stop_loss_trim_pct:
                decision.action = ActionType.TRIM
                decision.action_score = 75.0
                decision.recommendation_priority = PRIORITY_DEFENSIVE
                trim_amount = min(TRIM_DECREMENT, holding.current_weight - 1.0)
                decision.target_weight_change = -trim_amount
                decision.suggested_weight = holding.current_weight - trim_amount
                reasons.append(ReasonCode.STOP_LOSS_TRIGGERED)
                decision.rationale = (
                    f"Stop-loss TRIM: position {dd_cost:.1f}% below cost basis "
                    f"(threshold {momentum_config.stop_loss_trim_pct:.0f}%)"
                )
                decision.reason_codes = reasons
                return decision

    # ---------------------------------------------------------------
    # Priority 2.5 — MOMENTUM: trailing stop from peak
    # ---------------------------------------------------------------
    if momentum_config.enabled and momentum_config.trailing_stop_enabled:
        dd_peak = holding.momentum.drawdown_from_peak_pct
        if dd_peak is not None and dd_peak <= momentum_config.trailing_stop_pct:
            decision.action = ActionType.EXIT
            decision.action_score = 86.0
            decision.recommendation_priority = PRIORITY_STRONG_EXIT
            decision.target_weight_change = -holding.current_weight
            decision.suggested_weight = 0.0
            reasons.append(ReasonCode.TRAILING_STOP_TRIGGERED)
            decision.rationale = (
                f"Trailing stop EXIT: {dd_peak:.1f}% from {momentum_config.trailing_stop_lookback}-day peak "
                f"(threshold {momentum_config.trailing_stop_pct:.0f}%)"
            )
            decision.reason_codes = reasons
            return decision

    # ---------------------------------------------------------------
    # Priority 3 — DEFENSIVE: trim on low conviction (≤ 35)
    # Replaces the old probation system — simpler, more defensible.
    # ---------------------------------------------------------------
    if holding.conviction_score <= TRIM_CONVICTION_THRESHOLD:
        decision.action = ActionType.TRIM
        decision.action_score = 65.0
        decision.recommendation_priority = PRIORITY_DEFENSIVE
        trim_amount = min(TRIM_DECREMENT, holding.current_weight - 1.0)
        decision.target_weight_change = -trim_amount
        decision.suggested_weight = holding.current_weight - trim_amount
        reasons.append(ReasonCode.CONVICTION_LOW)
        decision.rationale = f"Conviction {holding.conviction_score:.0f} below trim threshold {TRIM_CONVICTION_THRESHOLD:.0f} — reduce exposure"
        decision.reason_codes = reasons
        return decision

    # ---------------------------------------------------------------
    # Priority 3 — DEFENSIVE: trim on stretched valuation
    # ---------------------------------------------------------------
    if zone == ZoneState.TRIM:
        decision.action = ActionType.TRIM
        decision.action_score = 70.0
        decision.recommendation_priority = PRIORITY_DEFENSIVE
        trim_amount = min(TRIM_DECREMENT, holding.current_weight - 1.0)  # keep at least 1%
        decision.target_weight_change = -trim_amount
        decision.suggested_weight = holding.current_weight - trim_amount
        reasons.append(ReasonCode.VALUATION_STRETCHED)
        decision.rationale = "Valuation stretched — trim position"
        decision.reason_codes = reasons
        return decision

    if holding.conviction_score < TRIM_CONVICTION_CEILING and holding.thesis_state == ThesisState.WEAKENING:
        decision.action = ActionType.TRIM
        decision.action_score = 55.0
        decision.recommendation_priority = PRIORITY_DEFENSIVE
        trim_amount = min(TRIM_DECREMENT, holding.current_weight - 1.0)
        decision.target_weight_change = -trim_amount
        decision.suggested_weight = holding.current_weight - trim_amount
        reasons.append(ReasonCode.THESIS_WEAKENING)
        reasons.append(ReasonCode.CONVICTION_LOW)
        decision.rationale = f"Thesis weakening with conviction {holding.conviction_score:.0f} — trim"
        decision.reason_codes = reasons
        return decision

    # ---------------------------------------------------------------
    # Priority 4/5 — GROWTH: add evaluation
    # ---------------------------------------------------------------
    if zone == ZoneState.BUY and holding.conviction_score >= ADD_CONVICTION_FLOOR:
        # --- Momentum guard: SMA check before any ADD ---
        if momentum_config.enabled and momentum_config.sma_guard_enabled:
            if holding.momentum.price_above_sma is False:
                reasons.append(ReasonCode.MOMENTUM_BELOW_SMA)
                decision.blocking_conditions.append(
                    f"ADD blocked: price below {momentum_config.sma_period}-day SMA"
                )
                # Fall through to HOLD instead of ADD
                zone = ZoneState.HOLD  # prevent ADD path

        # --- Momentum guard: underwater add blocking ---
        if momentum_config.enabled and momentum_config.underwater_guard_enabled:
            dd_cost = holding.momentum.drawdown_from_cost_pct
            if dd_cost is not None and dd_cost <= momentum_config.underwater_block_pct:
                reasons.append(ReasonCode.UNDERWATER_ADD_BLOCKED)
                decision.blocking_conditions.append(
                    f"ADD blocked: position {dd_cost:.1f}% underwater (threshold {momentum_config.underwater_block_pct:.0f}%)"
                )
                zone = ZoneState.HOLD  # prevent ADD path

        # --- Momentum guard: overbought add blocking ---
        if momentum_config.enabled and momentum_config.overbought_guard_enabled:
            if holding.momentum.is_overbought is True:
                dist = holding.momentum.distance_from_high_pct
                reasons.append(ReasonCode.OVERBOUGHT_ADD_BLOCKED)
                decision.blocking_conditions.append(
                    f"ADD blocked: price within {abs(dist or 0):.1f}% of {momentum_config.overbought_lookback}-day high"
                )
                zone = ZoneState.HOLD  # prevent ADD path

    if zone == ZoneState.BUY and holding.conviction_score >= ADD_CONVICTION_FLOOR:
        # Trend filter: block adds when price is below SMA (downtrend)
        if momentum_config.enabled and holding.momentum.price_above_sma is False:
            reasons.append(ReasonCode.MOMENTUM_BELOW_SMA)
            decision.blocking_conditions.append(
                f"Add blocked: price below {momentum_config.sma_period}-day SMA (downtrend)"
            )
            zone = ZoneState.HOLD  # fall through to HOLD

        # Max adds per position: prevent concentration from repeated adds
        MAX_ADDS_PER_POSITION = 2
        if holding.add_count >= MAX_ADDS_PER_POSITION:
            decision.blocking_conditions.append(
                f"Add blocked: {holding.add_count} adds already (max {MAX_ADDS_PER_POSITION})"
            )
            zone = ZoneState.HOLD

        # If trend filter or add cap changed zone to HOLD, skip the add path
        if zone != ZoneState.BUY:
            decision.action = ActionType.HOLD
            decision.rationale = "Hold — add blocked by guard"
            decision.reason_codes = reasons
            return decision

        is_winner = (
            holding.current_price is not None
            and holding.avg_cost > 0
            and holding.current_price >= holding.avg_cost
        )

        # Compute add size, applying underwater scaling if needed
        def _scaled_add_size() -> float:
            base = conviction_weighted_add_increment(holding.conviction_score, holding.current_weight)
            if momentum_config.enabled and momentum_config.underwater_guard_enabled:
                dd = holding.momentum.drawdown_from_cost_pct
                if dd is not None and dd < 0:
                    return base * momentum_config.underwater_add_scale
            return base

        if is_winner:
            if holding.thesis_state in (ThesisState.STRENGTHENING, ThesisState.STABLE):
                # Block add if claim impact signal is negative (historically, these claims hurt)
                if holding.claim_impact_signal < -1.0:
                    reasons.append(ReasonCode.INSUFFICIENT_NOVEL_EVIDENCE)
                    decision.blocking_conditions.append(
                        f"Add blocked: claim impact signal {holding.claim_impact_signal:.1f}% (negative history)"
                    )
                else:
                    add_size = _scaled_add_size()
                    decision.action = ActionType.ADD
                    decision.action_score = 50.0
                    decision.recommendation_priority = PRIORITY_GROWTH
                    decision.target_weight_change = add_size
                    decision.suggested_weight = holding.current_weight + add_size
                    reasons.append(ReasonCode.ADD_TO_WINNER)
                    reasons.append(ReasonCode.VALUATION_ATTRACTIVE)
                    if holding.thesis_state == ThesisState.STRENGTHENING:
                        reasons.append(ReasonCode.THESIS_STRENGTHENING)
                        decision.action_score = 55.0
                    # Boost/penalize action score based on claim impact
                    if holding.claim_impact_signal > 0:
                        decision.action_score += min(holding.claim_impact_signal * 2, 10.0)
                    decision.rationale = "Winner with strong conviction and attractive valuation — add"
                    decision.reason_codes = reasons
                    return decision
        else:
            has_confirming_evidence = holding.confirming_claim_count_7d > 0 or holding.novel_claim_count_7d > 0
            thesis_intact = holding.thesis_state in (
                ThesisState.STRENGTHENING, ThesisState.STABLE, ThesisState.FORMING,
            )

            # Block add-to-loser if claim impact signal is negative
            if has_confirming_evidence and thesis_intact and holding.claim_impact_signal >= -1.0:
                add_size = _scaled_add_size()
                decision.action = ActionType.ADD
                decision.action_score = 40.0 + min(max(holding.claim_impact_signal * 2, 0), 10.0)
                decision.recommendation_priority = PRIORITY_GROWTH
                decision.target_weight_change = add_size
                decision.suggested_weight = holding.current_weight + add_size
                reasons.append(ReasonCode.ADD_TO_LOSER_CONFIRMED)
                reasons.append(ReasonCode.SUFFICIENT_NOVEL_EVIDENCE)
                reasons.append(ReasonCode.VALUATION_ATTRACTIVE)
                decision.rationale = "Loser with intact thesis, confirming evidence, and attractive valuation — add"
                decision.reason_codes = reasons
                return decision
            else:
                if not has_confirming_evidence:
                    reasons.append(ReasonCode.INSUFFICIENT_NOVEL_EVIDENCE)
                    decision.blocking_conditions.append("Add to loser blocked: no confirming evidence in last 7 days")

    # ---------------------------------------------------------------
    # Priority 6 — NEUTRAL: hold
    # ---------------------------------------------------------------
    if holding.thesis_state == ThesisState.STRENGTHENING:
        reasons.append(ReasonCode.THESIS_STRENGTHENING)
    elif holding.thesis_state == ThesisState.WEAKENING:
        reasons.append(ReasonCode.THESIS_WEAKENING)

    if zone == ZoneState.BUY:
        reasons.append(ReasonCode.VALUATION_ATTRACTIVE)
    elif zone == ZoneState.HOLD:
        reasons.append(ReasonCode.VALUATION_NEUTRAL)

    if holding.has_checkpoint_ahead:
        reasons.append(ReasonCode.CHECKPOINT_AHEAD)

    decision.action = ActionType.HOLD
    decision.action_score = 0.0
    decision.recommendation_priority = PRIORITY_NEUTRAL
    decision.rationale = f"Hold — conviction {holding.conviction_score:.0f}, thesis {holding.thesis_state.value}"
    decision.reason_codes = reasons
    return decision


# ---------------------------------------------------------------------------
# Core decision logic: candidate initiation evaluation
# ---------------------------------------------------------------------------

def _check_entry_gates(
    candidate: CandidateSnapshot,
    review_date: date,
    *,
    relaxed: bool = False,
) -> tuple[bool, list[ReasonCode], list[str]]:
    """Check entry gates for candidate initiation.

    Gates (hard requirements):
    1. Differentiated thesis exists with conviction above floor
    2. Credible non-duplicative evidence exists

    Advisory signals (logged but non-blocking):
    3. Valuation zone
    4. Checkpoint ahead

    Simplified from original 4-gate system: valuation and checkpoint
    gates were too restrictive in practice (blocked 60% of valid
    initiations due to data availability). Conviction + evidence are
    the defensible gates; valuation/checkpoint are sizing signals.

    Returns:
        (all_pass, reason_codes, blocking_conditions)
    """
    reasons: list[ReasonCode] = []
    blockers: list[str] = []
    all_pass = True

    # In relaxed mode (usefulness runs with stub extractor), use a lower bar
    # so initiations can fire at the default conviction of 50
    RELAXED_INITIATION_FLOOR = 45.0
    conviction_floor = RELAXED_INITIATION_FLOOR if relaxed else INITIATION_CONVICTION_FLOOR

    # Gate 1: Thesis exists and is not broken/forming-without-conviction
    if candidate.thesis_id is None or candidate.thesis_state is None:
        all_pass = False
        reasons.append(ReasonCode.NO_THESIS)
        blockers.append("No active thesis")
    elif candidate.thesis_state == ThesisState.BROKEN:
        all_pass = False
        reasons.append(ReasonCode.THESIS_BROKEN)
        blockers.append("Thesis is broken")
    elif candidate.conviction_score is None or candidate.conviction_score < conviction_floor:
        all_pass = False
        reasons.append(ReasonCode.CONVICTION_LOW)
        blockers.append(f"Conviction {candidate.conviction_score or 0:.0f} below initiation floor {conviction_floor:.0f}")

    # Gate 2: Credible evidence
    if candidate.novel_claim_count_7d == 0 and candidate.confirming_claim_count_7d == 0:
        if not relaxed:
            all_pass = False
        reasons.append(ReasonCode.INSUFFICIENT_NOVEL_EVIDENCE)
        if not relaxed:
            blockers.append("No novel or confirming evidence in last 7 days")
    else:
        reasons.append(ReasonCode.SUFFICIENT_NOVEL_EVIDENCE)

    # Gate 3: Valuation (advisory — logged but non-blocking)
    zone = candidate.zone_state
    if zone is None:
        zone = zone_from_thesis_and_price(
            candidate.valuation_gap_pct,
            candidate.base_case_rerating,
            candidate.current_price,
        )
    if zone == ZoneState.BUY:
        reasons.append(ReasonCode.VALUATION_ATTRACTIVE)
    else:
        reasons.append(ReasonCode.VALUATION_NEUTRAL if zone == ZoneState.HOLD else ReasonCode.VALUATION_STRETCHED)

    # Gate 4: Checkpoint ahead (advisory — logged but non-blocking)
    if candidate.has_checkpoint_ahead:
        reasons.append(ReasonCode.CHECKPOINT_AHEAD)
    else:
        reasons.append(ReasonCode.NO_CHECKPOINT_AHEAD)

    return all_pass, reasons, blockers


def evaluate_candidate(
    candidate: CandidateSnapshot,
    weakest_holding: Optional[HoldingSnapshot],
    review_date: date,
    *,
    relaxed_gates: bool = False,
    momentum_config: MomentumGuardConfig = ENABLED_MOMENTUM_CONFIG,
) -> TickerDecision:
    """Evaluate a candidate for initiation.

    Must pass all entry gates AND beat the weakest current holding.
    When relaxed_gates=True, valuation/checkpoint gates are non-blocking.
    """
    decision = TickerDecision(ticker=candidate.ticker, action=ActionType.NO_ACTION)
    decision.thesis_conviction = candidate.conviction_score or 0.0
    decision.recommendation_priority = PRIORITY_NEUTRAL

    # Cooldown check — blocks initiation even if all other gates pass
    if candidate.cooldown_flag:
        if candidate.cooldown_until and review_date < candidate.cooldown_until:
            decision.reason_codes = [ReasonCode.COOLDOWN_ACTIVE]
            decision.blocking_conditions.append(
                f"Cooldown active until {candidate.cooldown_until.isoformat()}"
            )
            decision.decision_stage = "blocked"
            decision.rationale = "Re-entry blocked by cooldown"
            return decision

    # Momentum guard: market regime filter (block initiations in bearish regime)
    if momentum_config.enabled and momentum_config.regime_guard_enabled:
        if candidate.momentum.market_regime_bullish is False:
            decision.reason_codes = [ReasonCode.MARKET_REGIME_BEARISH]
            decision.blocking_conditions.append(
                f"Initiation blocked: benchmark below {momentum_config.regime_sma_period}-day SMA (bearish regime)"
            )
            decision.decision_stage = "blocked"
            decision.rationale = "Market regime bearish — initiation blocked"
            return decision

    # Momentum guard: overbought filter (block initiations near recent highs)
    if momentum_config.enabled and momentum_config.overbought_guard_enabled:
        if candidate.momentum.is_overbought is True:
            dist = candidate.momentum.distance_from_high_pct
            decision.reason_codes = [ReasonCode.OVERBOUGHT_INITIATE_BLOCKED]
            decision.blocking_conditions.append(
                f"Initiation blocked: price within {abs(dist or 0):.1f}% of {momentum_config.overbought_lookback}-day high"
            )
            decision.decision_stage = "blocked"
            decision.rationale = f"Overbought — price within {abs(dist or 0):.1f}% of {momentum_config.overbought_lookback}-day high"
            return decision

    # Check entry gates
    gates_pass, gate_reasons, gate_blockers = _check_entry_gates(
        candidate, review_date, relaxed=relaxed_gates,
    )

    if not gates_pass:
        decision.reason_codes = gate_reasons
        decision.blocking_conditions = gate_blockers
        decision.decision_stage = "blocked"
        decision.rationale = f"Failed entry gates: {', '.join(gate_blockers)}"
        return decision

    # Relative hurdle: candidate must beat weakest holding
    # In relaxed mode (usefulness runs), skip the hurdle to maximize scorable actions
    candidate_score = candidate.conviction_score or 0.0
    if weakest_holding is not None and not relaxed_gates:
        if candidate_score < weakest_holding.conviction_score + RELATIVE_HURDLE_MARGIN:
            decision.reason_codes = gate_reasons + [ReasonCode.FAILED_RELATIVE_HURDLE]
            decision.blocking_conditions.append(
                f"Candidate conviction {candidate_score:.0f} does not beat weakest holding "
                f"{weakest_holding.ticker} ({weakest_holding.conviction_score:.0f}) "
                f"by required margin of {RELATIVE_HURDLE_MARGIN:.0f}"
            )
            decision.decision_stage = "blocked"
            decision.rationale = f"Failed relative hurdle vs {weakest_holding.ticker}"
            return decision
        gate_reasons.append(ReasonCode.BETTER_THAN_WEAKEST_HOLDING)

    # All gates passed + relative hurdle passed → INITIATE
    sized_weight = conviction_weighted_initiation_size(candidate_score)
    decision.action = ActionType.INITIATE
    decision.action_score = candidate_score
    decision.recommendation_priority = PRIORITY_GROWTH
    decision.target_weight_change = sized_weight
    decision.suggested_weight = sized_weight
    decision.reason_codes = gate_reasons

    # Modulate by claim impact signal: boost score if historically predictive
    if candidate.claim_impact_signal > 0:
        decision.action_score += min(candidate.claim_impact_signal * 2, 10.0)
    elif candidate.claim_impact_signal < -1.0:
        decision.action_score -= min(abs(candidate.claim_impact_signal), 10.0)

    decision.rationale = (
        f"All entry gates passed — conviction {candidate_score:.0f}, "
        f"thesis {candidate.thesis_state.value if candidate.thesis_state else 'N/A'}"
    )
    if candidate.claim_impact_signal != 0:
        decision.rationale += f" (claim impact: {candidate.claim_impact_signal:+.1f}%)"
    if candidate.has_checkpoint_ahead and candidate.days_to_checkpoint:
        decision.required_followup.append(
            f"Checkpoint in {candidate.days_to_checkpoint} days"
        )

    return decision


# ---------------------------------------------------------------------------
# Full portfolio evaluation with capital competition + turnover enforcement
# ---------------------------------------------------------------------------

def _decision_sort_key(d: TickerDecision) -> tuple:
    """Sort key: lower priority number first, then higher score first."""
    return (d.recommendation_priority, -d.action_score)


def run_decision_engine(inputs: DecisionInput) -> PortfolioReviewResult:
    """Run the decision engine over all holdings and candidates.

    Steps:
    1. Evaluate each holding → holding decisions
    2. Find weakest holding for relative hurdle
    3. Evaluate each candidate → candidate decisions
       (blocked during RISK_OFF/EXTREME_FEAR market sentiment)
    4. Rank by recommendation_priority (tier), then action_score within tier
    5. Enforce weekly turnover cap (higher-priority actions processed first)
    6. If initiation needs capital, create explicit funded pairing
    """
    result = PortfolioReviewResult(
        review_date=inputs.review_date,
        turnover_pct_cap=inputs.weekly_turnover_cap_pct,
    )

    # Step 1: Evaluate holdings
    holding_decisions: list[TickerDecision] = []
    for h in inputs.holdings:
        d = evaluate_holding(h, inputs.review_date, exit_policy=inputs.exit_policy,
                             relaxed_gates=inputs.relaxed_gates,
                             momentum_config=inputs.momentum_config)
        holding_decisions.append(d)

    # Step 2: Find weakest holding (lowest conviction among active, non-probation)
    active_holdings = [
        h for h in inputs.holdings
        if not h.probation_flag and h.current_weight > 0
    ]
    weakest_holding = None
    if active_holdings:
        weakest_holding = min(active_holdings, key=lambda h: h.conviction_score)

    # Step 3: Evaluate candidates (with market sentiment gating)
    candidate_decisions: list[TickerDecision] = []

    # Market sentiment: block all initiations during extreme fear
    sentiment_blocks_initiations = False
    if inputs.market_sentiment and inputs.market_sentiment.block_initiations:
        sentiment_blocks_initiations = True

    # Count current non-core satellite positions for cap enforcement
    current_position_count = len(inputs.holdings)
    approved_initiations = 0

    # Compute current sector weights for concentration cap
    sector_weights: dict[str, float] = {}
    for h in inputs.holdings:
        if h.sector:
            sector_weights[h.sector] = sector_weights.get(h.sector, 0.0) + h.current_weight

    for c in inputs.candidates:
        # Position count cap — block new initiations if at max
        if current_position_count + approved_initiations >= inputs.max_satellite_positions:
            d = TickerDecision(
                ticker=c.ticker,
                action=ActionType.NO_ACTION,
                thesis_conviction=c.conviction_score or 0.0,
                recommendation_priority=PRIORITY_NEUTRAL,
                reason_codes=[ReasonCode.CONVICTION_LOW],
                decision_stage="blocked",
                rationale=f"Position cap: {inputs.max_satellite_positions} satellite positions reached",
                blocking_conditions=[f"Max satellite positions ({inputs.max_satellite_positions}) reached"],
            )
            candidate_decisions.append(d)
            continue

        # Deployment pacing — max N initiations per review cycle
        if approved_initiations >= inputs.max_initiations_per_review:
            d = TickerDecision(
                ticker=c.ticker,
                action=ActionType.NO_ACTION,
                thesis_conviction=c.conviction_score or 0.0,
                recommendation_priority=PRIORITY_NEUTRAL,
                reason_codes=[ReasonCode.CONVICTION_LOW],
                decision_stage="blocked",
                rationale=f"Pacing: max {inputs.max_initiations_per_review} initiations per review reached",
                blocking_conditions=[f"Max initiations per review ({inputs.max_initiations_per_review}) reached"],
            )
            candidate_decisions.append(d)
            continue

        # Sector concentration cap — block initiation if sector is already at limit
        if c.sector and inputs.max_sector_weight > 0:
            current_sector_wt = sector_weights.get(c.sector, 0.0)
            if current_sector_wt >= inputs.max_sector_weight:
                d = TickerDecision(
                    ticker=c.ticker,
                    action=ActionType.NO_ACTION,
                    thesis_conviction=c.conviction_score or 0.0,
                    recommendation_priority=PRIORITY_NEUTRAL,
                    reason_codes=[ReasonCode.SECTOR_CAP_REACHED],
                    decision_stage="blocked",
                    rationale=f"Sector cap: {c.sector} at {current_sector_wt:.1f}% (limit {inputs.max_sector_weight:.0f}%)",
                    blocking_conditions=[f"Sector {c.sector} weight {current_sector_wt:.1f}% >= cap {inputs.max_sector_weight:.0f}%"],
                )
                candidate_decisions.append(d)
                continue

        # Market sentiment pre-filter
        if sentiment_blocks_initiations:
            regime = inputs.market_sentiment.regime
            reason_code = (
                ReasonCode.MARKET_SENTIMENT_EXTREME_FEAR
                if regime == MarketRegime.EXTREME_FEAR
                else ReasonCode.MARKET_SENTIMENT_RISK_OFF
            )
            d = TickerDecision(
                ticker=c.ticker,
                action=ActionType.NO_ACTION,
                thesis_conviction=c.conviction_score or 0.0,
                recommendation_priority=PRIORITY_NEUTRAL,
                reason_codes=[reason_code],
                decision_stage="blocked",
                rationale=f"Initiation blocked: market sentiment {regime.value} — {inputs.market_sentiment.explanation}",
                blocking_conditions=[f"Market regime: {regime.value}"],
            )
            candidate_decisions.append(d)
            continue

        d = evaluate_candidate(
            c, weakest_holding, inputs.review_date,
            relaxed_gates=inputs.relaxed_gates,
            momentum_config=inputs.momentum_config,
        )

        # Market sentiment: scale down initiation sizing during CAUTIOUS regime
        if (
            d.action == ActionType.INITIATE
            and inputs.market_sentiment
            and inputs.market_sentiment.sizing_multiplier < 1.0
        ):
            if d.target_weight_change is not None:
                d.target_weight_change *= inputs.market_sentiment.sizing_multiplier
                d.suggested_weight = d.target_weight_change
                d.rationale += f" (sized down {inputs.market_sentiment.sizing_multiplier:.0%} — {inputs.market_sentiment.regime.value})"

        if d.action == ActionType.INITIATE:
            approved_initiations += 1
            # Update sector weight tracker for subsequent candidates
            if c.sector and d.target_weight_change:
                sector_weights[c.sector] = sector_weights.get(c.sector, 0.0) + d.target_weight_change
        candidate_decisions.append(d)

    # Step 4: Combine and rank by priority tier, then score within tier
    all_decisions = holding_decisions + candidate_decisions
    all_decisions.sort(key=_decision_sort_key)

    # Step 5: Enforce turnover cap (processes highest-priority actions first)
    turnover_budget = inputs.weekly_turnover_cap_pct
    approved_decisions: list[TickerDecision] = []

    for d in all_decisions:
        turnover_cost = abs(d.target_weight_change) if d.target_weight_change else 0.0

        if d.action in (ActionType.HOLD, ActionType.NO_ACTION, ActionType.PROBATION):
            # These don't consume turnover budget
            approved_decisions.append(d)
            continue

        if turnover_cost <= turnover_budget:
            approved_decisions.append(d)
            turnover_budget -= turnover_cost
        else:
            # Block this action due to turnover limit
            d_blocked = TickerDecision(
                ticker=d.ticker,
                action=ActionType.HOLD if d.action in (ActionType.ADD, ActionType.TRIM) else ActionType.NO_ACTION,
                action_score=0.0,
                recommendation_priority=PRIORITY_NEUTRAL,
                decision_stage="blocked",
                reason_codes=d.reason_codes + [ReasonCode.TURNOVER_LIMIT],
                rationale=f"Action {d.action.value} blocked by turnover cap (needed {turnover_cost:.1f}%, remaining {turnover_budget:.1f}%)",
                blocking_conditions=[f"Turnover cap: {d.action.value} would use {turnover_cost:.1f}%, only {turnover_budget:.1f}% remaining"],
            )
            approved_decisions.append(d_blocked)
            result.blocked_actions.append({
                "ticker": d.ticker,
                "original_action": d.action.value,
                "original_priority": d.recommendation_priority,
                "blocked_reason": "turnover_limit",
                "turnover_needed": round(turnover_cost, 2),
                "turnover_remaining": round(turnover_budget, 2),
            })

    # Step 6: Funded pairing — only when capital is actually constrained
    initiations = [d for d in approved_decisions if d.action == ActionType.INITIATE]
    if initiations and weakest_holding is not None:
        total_current_weight = sum(h.current_weight for h in inputs.holdings)
        weight_needed = sum(d.target_weight_change or 0 for d in initiations)
        available_capacity = inputs.total_portfolio_weight - total_current_weight

        if weight_needed > available_capacity:
            # Capital is constrained — create explicit funded pairing
            # Determine funding action based on weakest holding's state
            weakest_decision = next(
                (d for d in approved_decisions if d.ticker == weakest_holding.ticker),
                None,
            )
            # Decide trim vs exit as funding source
            if weakest_holding.conviction_score <= EXIT_CONVICTION_CEILING:
                funding_action = ActionType.EXIT
                funding_reason = ReasonCode.FUNDED_BY_EXIT
            else:
                funding_action = ActionType.TRIM
                funding_reason = ReasonCode.FUNDED_BY_TRIM

            for init_d in initiations:
                init_d.funded_by_ticker = weakest_holding.ticker
                init_d.funded_by_action = funding_action
                init_d.recommendation_priority = PRIORITY_CAPITAL_REDEPLOY
                init_d.reason_codes.append(ReasonCode.CAPITAL_CHALLENGER)
                init_d.reason_codes.append(funding_reason)
                init_d.required_followup.append(
                    f"Funded by {funding_action.value} of {weakest_holding.ticker} "
                    f"(conviction {weakest_holding.conviction_score:.0f})"
                )

    result.decisions = approved_decisions
    result.turnover_pct_planned = inputs.weekly_turnover_cap_pct - turnover_budget

    return result
