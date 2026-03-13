"""Portfolio decision engine: convert thesis state + conviction + valuation + context
into explicit portfolio actions under capital constraints.

All decision logic is deterministic code. LLM is not used here.

Decision precedence for holdings (strongest wins, checked in this order):
  Priority 1 — FORCED EXIT:  thesis broken, probation expired
  Priority 2 — STRONG EXIT:  conviction critically low (≤ EXIT_CONVICTION_CEILING),
                              thesis achieved + not BUY, FULL_EXIT valuation zone
  Priority 3 — DEFENSIVE:    enter/continue probation, trim (valuation or weakness)
  Priority 4 — GROWTH:       add to winner, add to loser (with evidence)
  Priority 5 — NEUTRAL:      hold

A stronger rule always takes precedence over a weaker one. For example,
conviction ≤ 25 produces EXIT even though it also satisfies the probation
threshold (≤ 35). Thesis broken produces EXIT regardless of valuation zone.
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
from exit_policy import ExitPolicyConfig, ExitPolicyMode, BASELINE_POLICY
from valuation_policy import zone_from_thesis_and_price, ZoneThresholds, DEFAULT_THRESHOLDS

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


# ---------------------------------------------------------------------------
# Recommendation priority tiers (lower number = higher precedence)
# ---------------------------------------------------------------------------

PRIORITY_FORCED_EXIT = 1       # thesis broken, probation expired
PRIORITY_STRONG_EXIT = 2       # critical conviction, achieved+exhausted, FULL_EXIT zone
PRIORITY_DEFENSIVE = 3         # probation entry, trim
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
    cooldown_flag: bool = False
    cooldown_until: Optional[date] = None
    watch_reason: Optional[str] = None


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
    zone_thresholds: ZoneThresholds = field(default_factory=lambda: DEFAULT_THRESHOLDS)
    relaxed_gates: bool = False               # relax entry gates for historical usefulness runs
    exit_policy: ExitPolicyConfig = field(default_factory=lambda: BASELINE_POLICY)


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
ADD_CONVICTION_FLOOR = 50.0             # minimum conviction for adds
TRIM_CONVICTION_CEILING = 40.0          # trim if conviction drops below this
EXIT_CONVICTION_CEILING = 25.0          # force exit below this
PROBATION_CONVICTION_CEILING = 35.0     # enter probation below this

# Probation rules
PROBATION_MAX_REVIEWS = 2               # forced exit after N weekly reviews without improvement
PROBATION_IMPROVEMENT_DELTA = 3.0       # conviction must improve by this much to exit probation

# Cooldown
COOLDOWN_DAYS = 21                      # re-entry blocked for N days after exit

# Weight sizing
DEFAULT_INITIATION_WEIGHT = 3.0         # starting weight for new positions
ADD_INCREMENT = 1.5                     # weight increment per add
TRIM_DECREMENT = 2.0                    # weight decrement per trim

# Price move threshold
IMMEDIATE_REVIEW_PRICE_MOVE_PCT = 8.0   # flag for immediate review


# ---------------------------------------------------------------------------
# Core decision logic: per-holding evaluation
# ---------------------------------------------------------------------------

def evaluate_holding(
    holding: HoldingSnapshot,
    review_date: date,
    exit_policy: ExitPolicyConfig = BASELINE_POLICY,
) -> TickerDecision:
    """Evaluate a current holding and produce a decision.

    This is pure deterministic logic using thesis state, conviction, valuation zone,
    and checkpoint context. The exit_policy controls thresholds for probation/exit.

    Decision precedence (checked in this order — first match wins):
      1. FORCED EXIT:  thesis broken (score 100)
      2. FORCED EXIT:  probation expired after max reviews (score 90)
      3. STRONG EXIT:  thesis achieved + not in BUY zone (score 85)
      4. STRONG EXIT:  FULL_EXIT valuation zone (score 80)
      5. STRONG EXIT:  conviction critically low (score 95)
        - graduated mode: also immediate exit on sharp conviction drop
      6. DEFENSIVE:    continue probation if already on probation (score 60)
      7. DEFENSIVE:    enter probation if conviction below threshold (score 65)
      8. DEFENSIVE:    trim on TRIM zone or conviction < TRIM + weakening (score 55-70)
      9. GROWTH:       add to winner or loser (score 40-55)
     10. NEUTRAL:      hold (score 0)
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
    # Priority 1 — FORCED EXIT: probation expired
    # ---------------------------------------------------------------
    if holding.probation_flag:
        reasons.append(ReasonCode.PROBATION_ACTIVE)
        if holding.probation_reviews_count >= exit_policy.probation_max_reviews:
            decision.action = ActionType.EXIT
            decision.action_score = 90.0
            decision.recommendation_priority = PRIORITY_FORCED_EXIT
            decision.target_weight_change = -holding.current_weight
            decision.suggested_weight = 0.0
            reasons.append(ReasonCode.PROBATION_EXPIRED)
            decision.rationale = f"Probation expired after {holding.probation_reviews_count} reviews without improvement — forced exit"
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
    # Priority 3 — DEFENSIVE: continue probation (already on probation,
    # not expired — blocks adds, mandates review)
    # ---------------------------------------------------------------
    if holding.probation_flag:
        # reasons already has PROBATION_ACTIVE from the expired check above
        decision.action = ActionType.PROBATION
        decision.action_score = 60.0
        decision.recommendation_priority = PRIORITY_DEFENSIVE
        decision.required_followup.append("Mandatory next-week review — probation active")
        decision.rationale = f"On probation (review {holding.probation_reviews_count + 1}/{exit_policy.probation_max_reviews}) — no adds allowed"
        decision.reason_codes = reasons
        return decision

    # ---------------------------------------------------------------
    # Priority 3 — DEFENSIVE: enter probation (conviction ≤ 35, not yet on probation)
    # ---------------------------------------------------------------
    if holding.conviction_score <= exit_policy.probation_conviction_ceiling:
        decision.action = ActionType.PROBATION
        decision.action_score = 65.0
        decision.recommendation_priority = PRIORITY_DEFENSIVE
        decision.required_followup.append("Enter probation — mandatory next-week review")
        reasons.append(ReasonCode.CONVICTION_LOW)
        decision.rationale = f"Conviction {holding.conviction_score:.0f} below probation threshold {exit_policy.probation_conviction_ceiling:.0f}"
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
        is_winner = (
            holding.current_price is not None
            and holding.avg_cost > 0
            and holding.current_price >= holding.avg_cost
        )

        if is_winner:
            if holding.thesis_state in (ThesisState.STRENGTHENING, ThesisState.STABLE):
                decision.action = ActionType.ADD
                decision.action_score = 50.0
                decision.recommendation_priority = PRIORITY_GROWTH
                decision.target_weight_change = ADD_INCREMENT
                decision.suggested_weight = holding.current_weight + ADD_INCREMENT
                reasons.append(ReasonCode.ADD_TO_WINNER)
                reasons.append(ReasonCode.VALUATION_ATTRACTIVE)
                if holding.thesis_state == ThesisState.STRENGTHENING:
                    reasons.append(ReasonCode.THESIS_STRENGTHENING)
                    decision.action_score = 55.0
                decision.rationale = "Winner with strong conviction and attractive valuation — add"
                decision.reason_codes = reasons
                return decision
        else:
            has_confirming_evidence = holding.confirming_claim_count_7d > 0 or holding.novel_claim_count_7d > 0
            thesis_intact = holding.thesis_state in (
                ThesisState.STRENGTHENING, ThesisState.STABLE, ThesisState.FORMING,
            )

            if has_confirming_evidence and thesis_intact:
                decision.action = ActionType.ADD
                decision.action_score = 40.0
                decision.recommendation_priority = PRIORITY_GROWTH
                decision.target_weight_change = ADD_INCREMENT
                decision.suggested_weight = holding.current_weight + ADD_INCREMENT
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
    """Check all four entry gates for candidate initiation.

    Gates:
    1. Differentiated thesis exists
    2. Credible non-duplicative evidence exists
    3. Valuation asymmetry is attractive
    4. Visible checkpoint ahead

    When relaxed=True (historical usefulness runs), gates 3 and 4 are
    treated as advisory (logged but non-blocking) and the conviction
    floor is lowered to the ADD threshold. This allows the decision
    engine to produce actions for usefulness evaluation even when
    valuation data and checkpoints are unavailable in historical mode.

    Returns:
        (all_pass, reason_codes, blocking_conditions)
    """
    reasons: list[ReasonCode] = []
    blockers: list[str] = []
    all_pass = True

    conviction_floor = ADD_CONVICTION_FLOOR if relaxed else INITIATION_CONVICTION_FLOOR

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

    # Gate 3: Valuation (advisory in relaxed mode)
    zone = candidate.zone_state
    if zone is None:
        zone = zone_from_thesis_and_price(
            candidate.valuation_gap_pct,
            candidate.base_case_rerating,
            candidate.current_price,
        )
    if zone == ZoneState.BUY:
        reasons.append(ReasonCode.VALUATION_ATTRACTIVE)
    elif relaxed:
        # In relaxed mode, valuation gate is non-blocking (advisory only)
        reasons.append(ReasonCode.VALUATION_NEUTRAL)
    else:
        all_pass = False
        reasons.append(ReasonCode.VALUATION_NEUTRAL if zone == ZoneState.HOLD else ReasonCode.VALUATION_STRETCHED)
        blockers.append(f"Valuation zone is {zone.value}, not buy")

    # Gate 4: Checkpoint ahead (advisory in relaxed mode)
    if candidate.has_checkpoint_ahead:
        reasons.append(ReasonCode.CHECKPOINT_AHEAD)
    elif relaxed:
        reasons.append(ReasonCode.NO_CHECKPOINT_AHEAD)
        # Non-blocking in relaxed mode
    else:
        all_pass = False
        reasons.append(ReasonCode.NO_CHECKPOINT_AHEAD)
        blockers.append("No visible checkpoint ahead")

    return all_pass, reasons, blockers


def evaluate_candidate(
    candidate: CandidateSnapshot,
    weakest_holding: Optional[HoldingSnapshot],
    review_date: date,
    *,
    relaxed_gates: bool = False,
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
    decision.action = ActionType.INITIATE
    decision.action_score = candidate_score
    decision.recommendation_priority = PRIORITY_GROWTH
    decision.target_weight_change = DEFAULT_INITIATION_WEIGHT
    decision.suggested_weight = DEFAULT_INITIATION_WEIGHT
    decision.reason_codes = gate_reasons
    decision.rationale = (
        f"All entry gates passed — conviction {candidate_score:.0f}, "
        f"thesis {candidate.thesis_state.value if candidate.thesis_state else 'N/A'}"
    )
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
        d = evaluate_holding(h, inputs.review_date, exit_policy=inputs.exit_policy)
        holding_decisions.append(d)

    # Step 2: Find weakest holding (lowest conviction among active, non-probation)
    active_holdings = [
        h for h in inputs.holdings
        if not h.probation_flag and h.current_weight > 0
    ]
    weakest_holding = None
    if active_holdings:
        weakest_holding = min(active_holdings, key=lambda h: h.conviction_score)

    # Step 3: Evaluate candidates
    candidate_decisions: list[TickerDecision] = []
    for c in inputs.candidates:
        d = evaluate_candidate(
            c, weakest_holding, inputs.review_date,
            relaxed_gates=inputs.relaxed_gates,
        )
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
