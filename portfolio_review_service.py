"""Weekly portfolio review service: loads positions/candidates from DB,
calls the decision engine, enforces turnover limits, persists results.

This is the first weekly decision loop for Step 7.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from models import (
    PortfolioPosition, Candidate, Thesis, Checkpoint, Price,
    Claim, ClaimCompanyLink, NoveltyType,
    PortfolioReview, PortfolioDecision,
    ThesisState, PositionStatus, ZoneState, ActionType,
)
from portfolio_decision_engine import (
    DecisionInput, HoldingSnapshot, CandidateSnapshot,
    TickerDecision, PortfolioReviewResult,
    run_decision_engine, COOLDOWN_DAYS, PROBATION_IMPROVEMENT_DELTA,
)
from valuation_policy import zone_from_thesis_and_price

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Snapshot builders: load DB state into engine input objects
# ---------------------------------------------------------------------------

def _get_latest_price(session: Session, ticker: str) -> Optional[float]:
    """Get most recent closing price for a ticker."""
    row = session.scalars(
        select(Price.close)
        .where(Price.ticker == ticker)
        .order_by(Price.date.desc())
        .limit(1)
    ).first()
    return row


def _get_price_change_5d(session: Session, ticker: str) -> Optional[float]:
    """Compute 5-day price change percentage."""
    prices = session.scalars(
        select(Price.close)
        .where(Price.ticker == ticker)
        .order_by(Price.date.desc())
        .limit(6)
    ).all()
    if len(prices) >= 2:
        current = prices[0]
        past = prices[-1]
        if past and past > 0:
            return ((current - past) / past) * 100.0
    return None


def _count_novel_claims_7d(
    session: Session, ticker: str, as_of: date,
) -> tuple[int, int]:
    """Count new and confirming claims for a ticker in the last 7 days.

    Returns (novel_count, confirming_count).
    """
    cutoff = datetime.combine(as_of - timedelta(days=7), datetime.min.time())

    claim_ids_q = (
        select(ClaimCompanyLink.claim_id)
        .where(ClaimCompanyLink.company_ticker == ticker)
    )

    novel = session.scalar(
        select(func.count(Claim.id))
        .where(
            Claim.id.in_(claim_ids_q),
            Claim.published_at >= cutoff,
            Claim.novelty_type == NoveltyType.NEW,
        )
    ) or 0

    confirming = session.scalar(
        select(func.count(Claim.id))
        .where(
            Claim.id.in_(claim_ids_q),
            Claim.published_at >= cutoff,
            Claim.novelty_type == NoveltyType.CONFIRMING,
        )
    ) or 0

    return novel, confirming


def _has_checkpoint_ahead(
    session: Session, ticker: str, as_of: date,
) -> tuple[bool, Optional[int]]:
    """Check if there is an upcoming checkpoint for the ticker.

    Returns (has_checkpoint, days_to_checkpoint).
    """
    checkpoint = session.scalars(
        select(Checkpoint)
        .where(
            Checkpoint.linked_company_ticker == ticker,
            Checkpoint.date_expected >= as_of,
        )
        .order_by(Checkpoint.date_expected.asc())
        .limit(1)
    ).first()

    if checkpoint and checkpoint.date_expected:
        days = (checkpoint.date_expected - as_of).days
        return True, days
    return False, None


def build_holding_snapshot(
    session: Session, position: PortfolioPosition, thesis: Thesis, as_of: date,
) -> HoldingSnapshot:
    """Build a HoldingSnapshot from DB objects."""
    current_price = _get_latest_price(session, position.ticker)
    price_change = _get_price_change_5d(session, position.ticker)
    novel, confirming = _count_novel_claims_7d(session, position.ticker, as_of)
    has_cp, days_cp = _has_checkpoint_ahead(session, position.ticker, as_of)

    zone = zone_from_thesis_and_price(
        thesis.valuation_gap_pct,
        thesis.base_case_rerating,
        current_price,
    )

    return HoldingSnapshot(
        ticker=position.ticker,
        position_id=position.id,
        thesis_id=thesis.id,
        thesis_state=thesis.state,
        conviction_score=thesis.conviction_score or position.conviction_score,
        current_weight=position.current_weight,
        target_weight=position.target_weight,
        avg_cost=position.avg_cost,
        current_price=current_price,
        valuation_gap_pct=thesis.valuation_gap_pct,
        base_case_rerating=thesis.base_case_rerating,
        zone_state=zone,
        probation_flag=position.probation_flag,
        probation_start_date=position.probation_start_date,
        probation_reviews_count=position.probation_reviews_count,
        has_checkpoint_ahead=has_cp,
        days_to_checkpoint=days_cp,
        novel_claim_count_7d=novel,
        confirming_claim_count_7d=confirming,
        price_change_pct_5d=price_change,
    )


def build_candidate_snapshot(
    session: Session, candidate: Candidate, as_of: date,
) -> CandidateSnapshot:
    """Build a CandidateSnapshot from DB objects."""
    thesis = None
    thesis_state = None
    conviction = candidate.conviction_score
    valuation_gap = None
    base_case = None

    if candidate.primary_thesis_id:
        thesis = session.get(Thesis, candidate.primary_thesis_id)
        if thesis:
            thesis_state = thesis.state
            conviction = thesis.conviction_score or candidate.conviction_score
            valuation_gap = thesis.valuation_gap_pct
            base_case = thesis.base_case_rerating

    current_price = _get_latest_price(session, candidate.ticker)
    novel, confirming = _count_novel_claims_7d(session, candidate.ticker, as_of)
    has_cp, days_cp = _has_checkpoint_ahead(session, candidate.ticker, as_of)

    zone = zone_from_thesis_and_price(valuation_gap, base_case, current_price)

    return CandidateSnapshot(
        ticker=candidate.ticker,
        candidate_id=candidate.id,
        thesis_id=candidate.primary_thesis_id,
        thesis_state=thesis_state,
        conviction_score=conviction,
        valuation_gap_pct=valuation_gap,
        base_case_rerating=base_case,
        current_price=current_price,
        zone_state=zone,
        has_checkpoint_ahead=has_cp,
        days_to_checkpoint=days_cp,
        novel_claim_count_7d=novel,
        confirming_claim_count_7d=confirming,
        cooldown_flag=candidate.cooldown_flag,
        cooldown_until=candidate.cooldown_until,
        watch_reason=candidate.watch_reason,
    )


# ---------------------------------------------------------------------------
# Main review entry point
# ---------------------------------------------------------------------------

def run_portfolio_review(
    session: Session,
    *,
    as_of: Optional[date] = None,
    review_type: str = "weekly",
    ticker_filter: Optional[str] = None,
    persist: bool = True,
) -> PortfolioReviewResult:
    """Run a portfolio review cycle.

    Args:
        session: DB session.
        as_of: Review date (defaults to today).
        review_type: "weekly", "immediate", or "ad_hoc".
        ticker_filter: If set, only review this one ticker.
        persist: If True, persist review + decisions to DB.

    Returns:
        PortfolioReviewResult with all decisions.
    """
    if as_of is None:
        as_of = date.today()

    logger.info("=== Portfolio review: %s (%s) ===", as_of.isoformat(), review_type)

    # Load active positions
    pos_query = (
        select(PortfolioPosition)
        .where(PortfolioPosition.status == PositionStatus.ACTIVE)
    )
    if ticker_filter:
        pos_query = pos_query.where(PortfolioPosition.ticker == ticker_filter)
    positions = session.scalars(pos_query).all()

    # Build holding snapshots
    holdings: list[HoldingSnapshot] = []
    for pos in positions:
        thesis = session.get(Thesis, pos.thesis_id)
        if thesis:
            snapshot = build_holding_snapshot(session, pos, thesis, as_of)
            holdings.append(snapshot)
        else:
            logger.warning("Position %s has no thesis (id=%d) — skipping", pos.ticker, pos.thesis_id)

    # Load candidates (not already held)
    held_tickers = {h.ticker for h in holdings}
    cand_query = select(Candidate)
    if ticker_filter:
        cand_query = cand_query.where(Candidate.ticker == ticker_filter)
    all_candidates = session.scalars(cand_query).all()

    candidates: list[CandidateSnapshot] = []
    for cand in all_candidates:
        if cand.ticker not in held_tickers:
            snapshot = build_candidate_snapshot(session, cand, as_of)
            candidates.append(snapshot)

    # Build engine input
    engine_input = DecisionInput(
        review_date=as_of,
        holdings=holdings,
        candidates=candidates,
    )

    # Run decision engine
    result = run_decision_engine(engine_input)
    result.review_type = review_type

    # Apply side effects to positions
    _apply_position_side_effects(session, result, positions, as_of)

    # Persist review
    if persist:
        _persist_review(session, result)

    logger.info(
        "Review complete: %d holdings, %d candidates, %d decisions "
        "(initiations=%d, adds=%d, trims=%d, exits=%d, probations=%d)",
        len(holdings), len(candidates), len(result.decisions),
        len(result.initiations), len(result.adds),
        len(result.trims), len(result.exits), len(result.probations),
    )

    return result


# ---------------------------------------------------------------------------
# Side effects: update position flags based on decisions
# ---------------------------------------------------------------------------

def _apply_position_side_effects(
    session: Session,
    result: PortfolioReviewResult,
    positions: list[PortfolioPosition],
    review_date: date,
) -> None:
    """Apply review-level side effects to position records.

    RECOMMENDATION vs EXECUTION BOUNDARY:
    This function may persist:
      - Probation tracking state (enter/continue/exit probation) — review metadata
      - Probation review counters — review metadata
    This function must NOT:
      - Set position status to CLOSED (execution-only)
      - Zero position weights (execution-only)
      - Write exit_date on the live position (execution-only)
      - Activate cooldown on position or candidate (execution-only, begins
        only after an actual exit is executed in Step 8+)

    Exit recommendations are captured in the PortfolioDecision record
    (action=EXIT, rationale, reason_codes). The live position remains
    ACTIVE until an execution layer confirms the trade.
    """
    pos_by_ticker = {p.ticker: p for p in positions}

    for decision in result.decisions:
        pos = pos_by_ticker.get(decision.ticker)
        if pos is None:
            continue

        if decision.action == ActionType.PROBATION and not pos.probation_flag:
            # Enter probation — review tracking state
            pos.probation_flag = True
            pos.probation_start_date = review_date
            pos.probation_reviews_count = 0
            decision.state_mutation_performed = True
            decision.state_mutation_notes.append("probation_flag set to True")
            logger.info("Position %s entering probation", pos.ticker)

        elif decision.action == ActionType.PROBATION and pos.probation_flag:
            # Already on probation — increment review count
            pos.probation_reviews_count += 1
            decision.state_mutation_performed = True
            decision.state_mutation_notes.append(
                f"probation_reviews_count incremented to {pos.probation_reviews_count}"
            )
            logger.info(
                "Position %s probation review %d",
                pos.ticker, pos.probation_reviews_count,
            )

        elif decision.action == ActionType.EXIT:
            # EXIT is recommendation-only in Step 7.
            # Do NOT close position, zero weight, write exit_date, or set cooldown.
            # These mutations happen in Step 8+ execution layer.
            decision.state_mutation_performed = False
            decision.state_mutation_notes.append(
                "exit recommended — position remains ACTIVE until execution"
            )
            logger.info(
                "Position %s exit recommended (not executed — awaiting Step 8)",
                pos.ticker,
            )

        elif pos.probation_flag and decision.action in (ActionType.HOLD, ActionType.ADD):
            # Check if conviction improved enough to exit probation
            thesis = session.get(Thesis, pos.thesis_id)
            if thesis and thesis.conviction_score and thesis.conviction_score > (pos.conviction_score + PROBATION_IMPROVEMENT_DELTA):
                pos.probation_flag = False
                pos.probation_start_date = None
                pos.probation_reviews_count = 0
                pos.conviction_score = thesis.conviction_score
                decision.state_mutation_performed = True
                decision.state_mutation_notes.append("probation cleared — conviction improved")
                logger.info("Position %s exiting probation — conviction improved", pos.ticker)

    session.flush()


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _persist_review(session: Session, result: PortfolioReviewResult) -> PortfolioReview:
    """Persist review run and decisions to DB."""
    review = PortfolioReview(
        review_date=result.review_date,
        review_type=result.review_type,
        holdings_reviewed=len([d for d in result.decisions if d.action != ActionType.NO_ACTION and d.action != ActionType.INITIATE]),
        candidates_reviewed=len([d for d in result.decisions if d.action in (ActionType.INITIATE, ActionType.NO_ACTION)]),
        turnover_pct=result.turnover_pct_planned,
        summary=json.dumps(result.to_dict().get("summary", {})),
    )
    session.add(review)
    session.flush()

    for d in result.decisions:
        pd = PortfolioDecision(
            review_id=review.id,
            ticker=d.ticker,
            action=d.action,
            action_score=d.action_score,
            target_weight_change=d.target_weight_change,
            suggested_weight=d.suggested_weight,
            reason_codes=json.dumps([r.value for r in d.reason_codes]),
            rationale=d.rationale,
            blocking_conditions=json.dumps(d.blocking_conditions) if d.blocking_conditions else None,
            required_followup=json.dumps(d.required_followup) if d.required_followup else None,
            generated_at=d.generated_at,
        )
        session.add(pd)

    session.flush()
    return review


# ---------------------------------------------------------------------------
# Text report
# ---------------------------------------------------------------------------

def format_review_text(result: PortfolioReviewResult) -> str:
    """Format a human-readable review report."""
    lines = [
        f"Portfolio Review — {result.review_date.isoformat()} ({result.review_type})",
        "=" * 70,
        f"Turnover: {result.turnover_pct_planned:.1f}% planned (cap: {result.turnover_pct_cap:.1f}%)",
        "",
    ]

    sections = [
        ("EXITS", result.exits),
        ("PROBATION", result.probations),
        ("TRIMS", result.trims),
        ("INITIATIONS", result.initiations),
        ("ADDS", result.adds),
        ("HOLDS", result.holds),
    ]

    for label, decisions in sections:
        if not decisions:
            continue
        lines.append(f"--- {label} ({len(decisions)}) ---")
        for d in sorted(decisions, key=lambda x: x.action_score, reverse=True):
            weight_info = ""
            if d.target_weight_change is not None:
                weight_info = f"  weight: {d.target_weight_change:+.1f}%"
                if d.suggested_weight is not None:
                    weight_info += f" → {d.suggested_weight:.1f}%"
            lines.append(f"  {d.ticker:8s} score={d.action_score:5.1f}{weight_info}")
            lines.append(f"           {d.rationale}")
            if d.blocking_conditions:
                for b in d.blocking_conditions:
                    lines.append(f"           BLOCKED: {b}")
            if d.required_followup:
                for f in d.required_followup:
                    lines.append(f"           TODO: {f}")
            lines.append("")

    if result.blocked_actions:
        lines.append("--- BLOCKED ACTIONS ---")
        for b in result.blocked_actions:
            lines.append(f"  {b['ticker']:8s} {b['original_action']} blocked: {b['blocked_reason']}")
        lines.append("")

    no_actions = [d for d in result.decisions if d.action == ActionType.NO_ACTION]
    if no_actions:
        lines.append(f"--- NO ACTION ({len(no_actions)} candidates) ---")
        for d in no_actions:
            lines.append(f"  {d.ticker:8s} {d.rationale[:60]}")
        lines.append("")

    return "\n".join(lines)
