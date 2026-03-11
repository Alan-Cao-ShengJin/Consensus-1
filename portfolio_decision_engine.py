"""Portfolio decision engine: convert thesis state + conviction + valuation + context
into explicit portfolio actions under capital constraints.

All decision logic is deterministic code. LLM is not used here.
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


# ---------------------------------------------------------------------------
# Decision output
# ---------------------------------------------------------------------------

@dataclass
class TickerDecision:
    """Structured recommendation for one ticker."""
    ticker: str
    action: ActionType
    action_score: float = 0.0                   # higher = more urgent
    target_weight_change: Optional[float] = None
    suggested_weight: Optional[float] = None
    reason_codes: list[ReasonCode] = field(default_factory=list)
    rationale: str = ""
    blocking_conditions: list[str] = field(default_factory=list)
    required_followup: list[str] = field(default_factory=list)
    generated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "action": self.action.value,
            "action_score": round(self.action_score, 2),
            "target_weight_change": round(self.target_weight_change, 2) if self.target_weight_change is not None else None,
            "suggested_weight": round(self.suggested_weight, 2) if self.suggested_weight is not None else None,
            "reason_codes": [r.value for r in self.reason_codes],
            "rationale": self.rationale,
            "blocking_conditions": self.blocking_conditions,
            "required_followup": self.required_followup,
            "generated_at": self.generated_at.isoformat(),
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

def evaluate_holding(holding: HoldingSnapshot, review_date: date) -> TickerDecision:
    """Evaluate a current holding and produce a decision.

    This is pure deterministic logic using thesis state, conviction, valuation zone,
    and checkpoint context.
    """
    decision = TickerDecision(ticker=holding.ticker, action=ActionType.HOLD)
    reasons: list[ReasonCode] = []

    # --- Immediate review trigger ---
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

    # --- EXIT: thesis broken ---
    if holding.thesis_state == ThesisState.BROKEN:
        decision.action = ActionType.EXIT
        decision.action_score = 100.0
        decision.target_weight_change = -holding.current_weight
        decision.suggested_weight = 0.0
        reasons.append(ReasonCode.THESIS_BROKEN)
        decision.rationale = "Thesis broken — forced exit"
        decision.reason_codes = reasons
        return decision

    # --- EXIT: thesis achieved with no extension ---
    if holding.thesis_state == ThesisState.ACHIEVED and zone != ZoneState.BUY:
        decision.action = ActionType.EXIT
        decision.action_score = 85.0
        decision.target_weight_change = -holding.current_weight
        decision.suggested_weight = 0.0
        reasons.append(ReasonCode.THESIS_ACHIEVED_EXHAUSTED)
        decision.rationale = "Thesis achieved and valuation no longer attractive — exit"
        decision.reason_codes = reasons
        return decision

    # --- PROBATION HANDLING ---
    if holding.probation_flag:
        reasons.append(ReasonCode.PROBATION_ACTIVE)

        # Check if probation expired (2 weekly reviews without improvement)
        if holding.probation_reviews_count >= PROBATION_MAX_REVIEWS:
            decision.action = ActionType.EXIT
            decision.action_score = 90.0
            decision.target_weight_change = -holding.current_weight
            decision.suggested_weight = 0.0
            reasons.append(ReasonCode.PROBATION_EXPIRED)
            decision.rationale = f"Probation expired after {holding.probation_reviews_count} reviews without improvement — forced exit"
            decision.reason_codes = reasons
            return decision

        # Still on probation — no adds, just hold and review
        decision.action = ActionType.PROBATION
        decision.action_score = 60.0
        decision.required_followup.append("Mandatory next-week review — probation active")
        decision.rationale = f"On probation (review {holding.probation_reviews_count + 1}/{PROBATION_MAX_REVIEWS}) — no adds allowed"
        decision.reason_codes = reasons
        return decision

    # --- Should we ENTER probation? ---
    if holding.conviction_score <= PROBATION_CONVICTION_CEILING:
        decision.action = ActionType.PROBATION
        decision.action_score = 65.0
        decision.required_followup.append("Enter probation — mandatory next-week review")
        reasons.append(ReasonCode.CONVICTION_LOW)
        decision.rationale = f"Conviction {holding.conviction_score:.0f} below probation threshold {PROBATION_CONVICTION_CEILING:.0f}"
        decision.reason_codes = reasons
        return decision

    # --- EXIT: conviction very low (below probation, should not normally reach here) ---
    if holding.conviction_score <= EXIT_CONVICTION_CEILING:
        decision.action = ActionType.EXIT
        decision.action_score = 95.0
        decision.target_weight_change = -holding.current_weight
        decision.suggested_weight = 0.0
        reasons.append(ReasonCode.CONVICTION_LOW)
        decision.rationale = f"Conviction {holding.conviction_score:.0f} critically low — exit"
        decision.reason_codes = reasons
        return decision

    # --- TRIM: valuation stretched or thesis weakening ---
    if zone == ZoneState.TRIM or zone == ZoneState.FULL_EXIT:
        decision.action = ActionType.TRIM
        decision.action_score = 70.0
        trim_amount = min(TRIM_DECREMENT, holding.current_weight - 1.0)  # keep at least 1%
        if zone == ZoneState.FULL_EXIT:
            decision.action = ActionType.EXIT
            decision.action_score = 80.0
            trim_amount = holding.current_weight
            reasons.append(ReasonCode.VALUATION_STRETCHED)
            decision.rationale = "Valuation in full exit zone"
        else:
            reasons.append(ReasonCode.VALUATION_STRETCHED)
            decision.rationale = "Valuation stretched — trim position"
        decision.target_weight_change = -trim_amount
        decision.suggested_weight = holding.current_weight - trim_amount
        decision.reason_codes = reasons
        return decision

    if holding.conviction_score < TRIM_CONVICTION_CEILING and holding.thesis_state == ThesisState.WEAKENING:
        decision.action = ActionType.TRIM
        decision.action_score = 55.0
        trim_amount = min(TRIM_DECREMENT, holding.current_weight - 1.0)
        decision.target_weight_change = -trim_amount
        decision.suggested_weight = holding.current_weight - trim_amount
        reasons.append(ReasonCode.THESIS_WEAKENING)
        reasons.append(ReasonCode.CONVICTION_LOW)
        decision.rationale = f"Thesis weakening with conviction {holding.conviction_score:.0f} — trim"
        decision.reason_codes = reasons
        return decision

    # --- ADD evaluation ---
    if zone == ZoneState.BUY and holding.conviction_score >= ADD_CONVICTION_FLOOR:
        # Determine if winner or loser
        is_winner = (
            holding.current_price is not None
            and holding.avg_cost > 0
            and holding.current_price >= holding.avg_cost
        )

        if is_winner:
            # Winner add: easier — just need conviction + valuation
            if holding.thesis_state in (ThesisState.STRENGTHENING, ThesisState.STABLE):
                decision.action = ActionType.ADD
                decision.action_score = 50.0
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
            # Loser add: requires confirming evidence + thesis intact + improved valuation
            has_confirming_evidence = holding.confirming_claim_count_7d > 0 or holding.novel_claim_count_7d > 0
            thesis_intact = holding.thesis_state in (
                ThesisState.STRENGTHENING, ThesisState.STABLE, ThesisState.FORMING,
            )

            if has_confirming_evidence and thesis_intact:
                decision.action = ActionType.ADD
                decision.action_score = 40.0
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

    # --- Default: HOLD ---
    # Add contextual reason codes
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
    decision.rationale = f"Hold — conviction {holding.conviction_score:.0f}, thesis {holding.thesis_state.value}"
    decision.reason_codes = reasons
    return decision


# ---------------------------------------------------------------------------
# Core decision logic: candidate initiation evaluation
# ---------------------------------------------------------------------------

def _check_entry_gates(
    candidate: CandidateSnapshot,
    review_date: date,
) -> tuple[bool, list[ReasonCode], list[str]]:
    """Check all four entry gates for candidate initiation.

    Gates:
    1. Differentiated thesis exists
    2. Credible non-duplicative evidence exists
    3. Valuation asymmetry is attractive
    4. Visible checkpoint ahead

    Returns:
        (all_pass, reason_codes, blocking_conditions)
    """
    reasons: list[ReasonCode] = []
    blockers: list[str] = []
    all_pass = True

    # Gate 1: Thesis exists and is not broken/forming-without-conviction
    if candidate.thesis_id is None or candidate.thesis_state is None:
        all_pass = False
        reasons.append(ReasonCode.NO_THESIS)
        blockers.append("No active thesis")
    elif candidate.thesis_state == ThesisState.BROKEN:
        all_pass = False
        reasons.append(ReasonCode.THESIS_BROKEN)
        blockers.append("Thesis is broken")
    elif candidate.conviction_score is None or candidate.conviction_score < INITIATION_CONVICTION_FLOOR:
        all_pass = False
        reasons.append(ReasonCode.CONVICTION_LOW)
        blockers.append(f"Conviction {candidate.conviction_score or 0:.0f} below initiation floor {INITIATION_CONVICTION_FLOOR:.0f}")

    # Gate 2: Credible evidence
    if candidate.novel_claim_count_7d == 0 and candidate.confirming_claim_count_7d == 0:
        all_pass = False
        reasons.append(ReasonCode.INSUFFICIENT_NOVEL_EVIDENCE)
        blockers.append("No novel or confirming evidence in last 7 days")
    else:
        reasons.append(ReasonCode.SUFFICIENT_NOVEL_EVIDENCE)

    # Gate 3: Valuation
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
        all_pass = False
        reasons.append(ReasonCode.VALUATION_NEUTRAL if zone == ZoneState.HOLD else ReasonCode.VALUATION_STRETCHED)
        blockers.append(f"Valuation zone is {zone.value}, not buy")

    # Gate 4: Checkpoint ahead
    if candidate.has_checkpoint_ahead:
        reasons.append(ReasonCode.CHECKPOINT_AHEAD)
    else:
        all_pass = False
        reasons.append(ReasonCode.NO_CHECKPOINT_AHEAD)
        blockers.append("No visible checkpoint ahead")

    return all_pass, reasons, blockers


def evaluate_candidate(
    candidate: CandidateSnapshot,
    weakest_holding: Optional[HoldingSnapshot],
    review_date: date,
) -> TickerDecision:
    """Evaluate a candidate for initiation.

    Must pass all entry gates AND beat the weakest current holding.
    """
    decision = TickerDecision(ticker=candidate.ticker, action=ActionType.NO_ACTION)

    # Cooldown check
    if candidate.cooldown_flag:
        if candidate.cooldown_until and review_date < candidate.cooldown_until:
            decision.reason_codes = [ReasonCode.COOLDOWN_ACTIVE]
            decision.blocking_conditions.append(
                f"Cooldown active until {candidate.cooldown_until.isoformat()}"
            )
            decision.rationale = "Re-entry blocked by cooldown"
            return decision

    # Check entry gates
    gates_pass, gate_reasons, gate_blockers = _check_entry_gates(candidate, review_date)

    if not gates_pass:
        decision.reason_codes = gate_reasons
        decision.blocking_conditions = gate_blockers
        decision.rationale = f"Failed entry gates: {', '.join(gate_blockers)}"
        return decision

    # Relative hurdle: candidate must beat weakest holding
    candidate_score = candidate.conviction_score or 0.0
    if weakest_holding is not None:
        if candidate_score < weakest_holding.conviction_score + RELATIVE_HURDLE_MARGIN:
            decision.reason_codes = gate_reasons + [ReasonCode.FAILED_RELATIVE_HURDLE]
            decision.blocking_conditions.append(
                f"Candidate conviction {candidate_score:.0f} does not beat weakest holding "
                f"{weakest_holding.ticker} ({weakest_holding.conviction_score:.0f}) "
                f"by required margin of {RELATIVE_HURDLE_MARGIN:.0f}"
            )
            decision.rationale = f"Failed relative hurdle vs {weakest_holding.ticker}"
            return decision
        gate_reasons.append(ReasonCode.BETTER_THAN_WEAKEST_HOLDING)

    # All gates passed + relative hurdle passed → INITIATE
    decision.action = ActionType.INITIATE
    decision.action_score = candidate_score
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

def run_decision_engine(inputs: DecisionInput) -> PortfolioReviewResult:
    """Run the decision engine over all holdings and candidates.

    Steps:
    1. Evaluate each holding → holding decisions
    2. Find weakest holding for relative hurdle
    3. Evaluate each candidate → candidate decisions
    4. Rank all actions by urgency
    5. Enforce weekly turnover cap
    6. If initiation needs capital, suggest trim of weakest holding
    """
    result = PortfolioReviewResult(
        review_date=inputs.review_date,
        turnover_pct_cap=inputs.weekly_turnover_cap_pct,
    )

    # Step 1: Evaluate holdings
    holding_decisions: list[TickerDecision] = []
    for h in inputs.holdings:
        d = evaluate_holding(h, inputs.review_date)
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
        d = evaluate_candidate(c, weakest_holding, inputs.review_date)
        candidate_decisions.append(d)

    # Step 4: Combine and rank all decisions
    all_decisions = holding_decisions + candidate_decisions
    all_decisions.sort(key=lambda d: d.action_score, reverse=True)

    # Step 5: Enforce turnover cap
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
                reason_codes=d.reason_codes + [ReasonCode.TURNOVER_LIMIT],
                rationale=f"Action {d.action.value} blocked by turnover cap (needed {turnover_cost:.1f}%, remaining {turnover_budget:.1f}%)",
                blocking_conditions=[f"Turnover cap: {d.action.value} would use {turnover_cost:.1f}%, only {turnover_budget:.1f}% remaining"],
            )
            approved_decisions.append(d_blocked)
            result.blocked_actions.append({
                "ticker": d.ticker,
                "original_action": d.action.value,
                "blocked_reason": "turnover_limit",
                "turnover_needed": round(turnover_cost, 2),
                "turnover_remaining": round(turnover_budget, 2),
            })

    # Step 6: Capital competition — if initiation approved, suggest trim of weakest
    initiations = [d for d in approved_decisions if d.action == ActionType.INITIATE]
    if initiations and weakest_holding is not None:
        # Check if we need capital from existing positions
        total_current_weight = sum(h.current_weight for h in inputs.holdings)
        weight_needed = sum(d.target_weight_change or 0 for d in initiations)

        if total_current_weight + weight_needed > inputs.total_portfolio_weight:
            for init_d in initiations:
                init_d.required_followup.append(
                    f"Capital needed — consider trimming weakest holding {weakest_holding.ticker} "
                    f"(conviction {weakest_holding.conviction_score:.0f})"
                )
                init_d.reason_codes.append(ReasonCode.CAPITAL_CHALLENGER)

    result.decisions = approved_decisions
    result.turnover_pct_planned = inputs.weekly_turnover_cap_pct - turnover_budget

    return result
