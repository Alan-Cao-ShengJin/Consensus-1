"""Replay engine: run the decision system through historical time.

For each replay date:
  1. Reconstruct research state as-of that date (leakage-aware)
  2. Build holding/candidate snapshots from shadow portfolio state + DB research data
  3. Run the portfolio decision engine
  4. Capture recommendations
  5. Optionally apply them to a shadow portfolio via the execution policy
  6. Advance to next review date

Anti-leakage contract:
  - At every replay point, only information available on or before that date is used
  - Documents, claims, prices, thesis states are all filtered by as_of
  - Shadow trades execute at next-trading-day close (not same-day)

Step 8.1 hardening:
  - Candidate pool filtered by created_at <= as_of (strict mode)
  - valuation_gap_pct and base_case_rerating use ThesisStateHistory when available
  - Checkpoints filtered by created_at <= as_of (strict mode)
  - Purity tracking: every fallback is counted and reported
  - strict_replay mode: skip decisions that depend on impure inputs
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import (
    Candidate, Thesis, Price, ThesisState, ActionType,
)
from portfolio_decision_engine import (
    DecisionInput, HoldingSnapshot, CandidateSnapshot,
    PortfolioReviewResult, run_decision_engine,
)
from portfolio_review_service import (
    _get_latest_price, _get_price_change_5d,
    _count_novel_claims_7d, _has_checkpoint_ahead,
    _get_thesis_state_as_of, _get_valuation_as_of,
    build_candidate_snapshot,
)
from valuation_policy import zone_from_thesis_and_price
from shadow_portfolio import ShadowPortfolio, PortfolioSnapshot
from shadow_execution_policy import (
    apply_recommendations, ExecutionResult, get_execution_price,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Purity tracking
# ---------------------------------------------------------------------------

@dataclass
class ReplayPurityFlags:
    """Track impurity fallbacks for a single review date."""
    impure_candidate_count: int = 0       # candidates without created_at or created after as_of
    impure_valuation_count: int = 0       # holdings/candidates using current valuation (no history)
    impure_checkpoint_count: int = 0      # checkpoints without created_at
    skipped_impure_candidates: int = 0    # candidates skipped in strict mode
    skipped_impure_valuation: int = 0     # holdings skipped zone calc in strict mode
    skipped_impure_checkpoints: int = 0   # checkpoints excluded in strict mode
    integrity_warnings: list[str] = field(default_factory=list)

    @property
    def is_pure(self) -> bool:
        return (
            self.impure_candidate_count == 0
            and self.impure_valuation_count == 0
            and self.impure_checkpoint_count == 0
        )

    def to_dict(self) -> dict:
        return {
            "impure_candidate_count": self.impure_candidate_count,
            "impure_valuation_count": self.impure_valuation_count,
            "impure_checkpoint_count": self.impure_checkpoint_count,
            "skipped_impure_candidates": self.skipped_impure_candidates,
            "skipped_impure_valuation": self.skipped_impure_valuation,
            "skipped_impure_checkpoints": self.skipped_impure_checkpoints,
            "integrity_warnings": self.integrity_warnings,
            "is_pure": self.is_pure,
        }


@dataclass
class ReplayReviewRecord:
    """Record of one review date in a replay run."""
    review_date: date
    result: PortfolioReviewResult
    execution_result: Optional[ExecutionResult] = None
    snapshot: Optional[PortfolioSnapshot] = None
    # Integrity tracking
    missing_prices: list[str] = field(default_factory=list)  # tickers with no price
    fallback_thesis_count: int = 0  # theses using live fallback
    purity: ReplayPurityFlags = field(default_factory=ReplayPurityFlags)


@dataclass
class ReplayRunResult:
    """Complete result of a replay run."""
    start_date: date
    end_date: date
    cadence_days: int
    review_records: list[ReplayReviewRecord] = field(default_factory=list)
    initial_cash: float = 0.0
    apply_trades: bool = True
    strict_replay: bool = False
    # Integrity summary
    total_reviews: int = 0
    total_recommendations: int = 0
    total_trades_applied: int = 0
    total_trades_skipped: int = 0
    total_fallback_count: int = 0
    dates_skipped_no_data: list[date] = field(default_factory=list)
    # Step 8.1 purity summary
    purity_level: str = "unknown"  # strict, degraded, mixed
    total_impure_candidates: int = 0
    total_impure_valuations: int = 0
    total_impure_checkpoints: int = 0
    total_skipped_impure: int = 0
    integrity_warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "cadence_days": self.cadence_days,
            "initial_cash": self.initial_cash,
            "apply_trades": self.apply_trades,
            "strict_replay": self.strict_replay,
            "total_reviews": self.total_reviews,
            "total_recommendations": self.total_recommendations,
            "total_trades_applied": self.total_trades_applied,
            "total_trades_skipped": self.total_trades_skipped,
            "total_fallback_count": self.total_fallback_count,
            "dates_skipped_no_data": [d.isoformat() for d in self.dates_skipped_no_data],
            "purity": {
                "purity_level": self.purity_level,
                "total_impure_candidates": self.total_impure_candidates,
                "total_impure_valuations": self.total_impure_valuations,
                "total_impure_checkpoints": self.total_impure_checkpoints,
                "total_skipped_impure": self.total_skipped_impure,
                "integrity_warnings": self.integrity_warnings,
            },
            "reviews": [
                {
                    "review_date": r.review_date.isoformat(),
                    "decisions": [d.to_dict() for d in r.result.decisions],
                    "trades_applied": (
                        [t.to_dict() for t in r.execution_result.trades_applied]
                        if r.execution_result else []
                    ),
                    "trades_skipped": (
                        r.execution_result.trades_skipped
                        if r.execution_result else []
                    ),
                    "snapshot": r.snapshot.to_dict() if r.snapshot else None,
                    "missing_prices": r.missing_prices,
                    "fallback_thesis_count": r.fallback_thesis_count,
                    "purity": r.purity.to_dict(),
                }
                for r in self.review_records
            ],
        }


def _preload_prices(
    session: Session, tickers: list[str],
) -> dict[str, list[tuple[date, float]]]:
    """Preload all price history for replay tickers, sorted ascending by date."""
    result: dict[str, list[tuple[date, float]]] = {}
    for ticker in tickers:
        rows = session.execute(
            select(Price.date, Price.close)
            .where(Price.ticker == ticker, Price.close.isnot(None))
            .order_by(Price.date.asc())
        ).all()
        result[ticker] = [(r[0], r[1]) for r in rows]
    return result


def _build_shadow_holding_snapshot(
    session: Session,
    portfolio: ShadowPortfolio,
    ticker: str,
    thesis: Thesis,
    review_date: date,
    *,
    strict_replay: bool = False,
    purity: Optional[ReplayPurityFlags] = None,
) -> Optional[HoldingSnapshot]:
    """Build HoldingSnapshot from shadow portfolio state + DB research data.

    Anti-leakage: all DB lookups are bounded by review_date.
    Portfolio state comes from shadow (not live DB positions).

    Step 8.1: uses historical valuation when available. In strict mode,
    uses HOLD zone as fallback when valuation history is missing.
    Checkpoints filtered by created_at in strict mode.
    """
    if purity is None:
        purity = ReplayPurityFlags()

    pos = portfolio.get_position(ticker)
    if pos is None:
        return None

    current_price = _get_latest_price(session, ticker, review_date)
    price_change = _get_price_change_5d(session, ticker, review_date)
    novel, confirming = _count_novel_claims_7d(session, ticker, review_date)

    # Checkpoint: filter by created_at in strict mode
    has_cp, days_cp = _has_checkpoint_ahead(
        session, ticker, review_date,
        filter_created_at=strict_replay,
    )

    # Historical thesis state
    thesis_state, thesis_conviction = _get_thesis_state_as_of(session, thesis, review_date)

    # Historical valuation (Step 8.1 + 8.2 provenance)
    val_gap, base_rerating, val_is_historical, val_provenance = _get_valuation_as_of(
        session, thesis, review_date,
    )

    if not val_is_historical:
        if strict_replay:
            # Strict mode: use None valuation → zone defaults to HOLD
            purity.skipped_impure_valuation += 1
            purity.integrity_warnings.append(
                f"Holding {ticker}: no historical valuation (provenance={val_provenance}), zone defaulted to HOLD"
            )
            val_gap = None
            base_rerating = None
        else:
            purity.impure_valuation_count += 1
            purity.integrity_warnings.append(
                f"Holding {ticker}: using current valuation (provenance={val_provenance})"
            )

    zone = zone_from_thesis_and_price(val_gap, base_rerating, current_price)

    return HoldingSnapshot(
        ticker=ticker,
        position_id=0,  # shadow position, no DB id
        thesis_id=thesis.id,
        thesis_state=thesis_state,
        conviction_score=thesis_conviction or 50.0,
        current_weight=pos.weight_pct,
        target_weight=pos.weight_pct,
        avg_cost=pos.avg_cost,
        current_price=current_price,
        valuation_gap_pct=val_gap,
        base_case_rerating=base_rerating,
        zone_state=zone,
        probation_flag=pos.probation_flag,
        probation_start_date=pos.probation_start_date,
        probation_reviews_count=pos.probation_reviews_count,
        has_checkpoint_ahead=has_cp,
        days_to_checkpoint=days_cp,
        novel_claim_count_7d=novel,
        confirming_claim_count_7d=confirming,
        price_change_pct_5d=price_change,
    )


def _build_replay_candidate_snapshot(
    session: Session,
    cand: Candidate,
    review_date: date,
    *,
    strict_replay: bool = False,
    purity: Optional[ReplayPurityFlags] = None,
) -> Optional[CandidateSnapshot]:
    """Build CandidateSnapshot for replay with purity-aware valuation and checkpoints.

    Step 8.1: uses historical valuation when available. In strict mode,
    uses None valuation when history is missing. Checkpoints filtered by
    created_at in strict mode.
    """
    if purity is None:
        purity = ReplayPurityFlags()

    thesis = None
    thesis_state = None
    conviction = cand.conviction_score
    valuation_gap = None
    base_case = None
    val_is_historical = True

    if cand.primary_thesis_id:
        thesis = session.get(Thesis, cand.primary_thesis_id)
        if thesis:
            hist_state, hist_conviction = _get_thesis_state_as_of(session, thesis, review_date)
            thesis_state = hist_state
            conviction = hist_conviction or cand.conviction_score

            # Historical valuation (Step 8.1 + 8.2 provenance)
            val_gap, base_rerating, val_is_historical, val_provenance = _get_valuation_as_of(
                session, thesis, review_date,
            )
            if val_is_historical:
                valuation_gap = val_gap
                base_case = base_rerating
            elif strict_replay:
                purity.skipped_impure_valuation += 1
                purity.integrity_warnings.append(
                    f"Candidate {cand.ticker}: no historical valuation (provenance={val_provenance}), zone defaulted to HOLD"
                )
                valuation_gap = None
                base_case = None
            else:
                purity.impure_valuation_count += 1
                purity.integrity_warnings.append(
                    f"Candidate {cand.ticker}: using current valuation (provenance={val_provenance})"
                )
                valuation_gap = val_gap
                base_case = base_rerating

    current_price = _get_latest_price(session, cand.ticker, review_date)
    novel, confirming = _count_novel_claims_7d(session, cand.ticker, review_date)

    # Checkpoint: filter by created_at in strict mode
    has_cp, days_cp = _has_checkpoint_ahead(
        session, cand.ticker, review_date,
        filter_created_at=strict_replay,
    )

    zone = zone_from_thesis_and_price(valuation_gap, base_case, current_price)

    return CandidateSnapshot(
        ticker=cand.ticker,
        candidate_id=cand.id,
        thesis_id=thesis.id if thesis else None,
        thesis_state=thesis_state,
        conviction_score=conviction or 0.0,
        valuation_gap_pct=valuation_gap,
        base_case_rerating=base_case,
        zone_state=zone,
        has_checkpoint_ahead=has_cp,
        days_to_checkpoint=days_cp,
        novel_claim_count_7d=novel,
        confirming_claim_count_7d=confirming,
        cooldown_flag=cand.cooldown_flag,
        cooldown_until=cand.cooldown_until,
    )


def run_replay_review(
    session: Session,
    portfolio: ShadowPortfolio,
    review_date: date,
    prices_by_ticker: dict[str, list[tuple[date, float]]],
    ticker_filter: Optional[str] = None,
    apply_trades: bool = True,
    *,
    strict_replay: bool = False,
) -> ReplayReviewRecord:
    """Run a single replay review at the given date.

    1. Build snapshots from shadow portfolio + DB research state (as-of)
    2. Build candidate snapshots from DB candidates (as-of)
    3. Run decision engine
    4. Optionally apply trades via shadow execution policy

    Anti-leakage: all data lookups bounded by review_date.

    Step 8.1:
      - strict_replay=True: exclude candidates without temporal provenance,
        skip valuation-dependent decisions when no history, filter checkpoints
      - strict_replay=False: use documented fallbacks, record warnings
    """
    record = ReplayReviewRecord(
        review_date=review_date,
        result=PortfolioReviewResult(review_date=review_date),
    )
    purity = record.purity

    # Build holding snapshots from shadow positions
    holdings: list[HoldingSnapshot] = []
    for ticker in list(portfolio.held_tickers()):
        if ticker_filter and ticker != ticker_filter:
            continue
        # Find the thesis for this ticker
        thesis = session.scalars(
            select(Thesis)
            .where(Thesis.company_ticker == ticker, Thesis.status_active.is_(True))
            .order_by(Thesis.updated_at.desc())
            .limit(1)
        ).first()
        if thesis is None:
            logger.warning("No active thesis for shadow holding %s — skipping", ticker)
            continue
        snap = _build_shadow_holding_snapshot(
            session, portfolio, ticker, thesis, review_date,
            strict_replay=strict_replay, purity=purity,
        )
        if snap:
            # Update weight from current portfolio state
            prices_now = {
                t: _get_price_on_date(prices_by_ticker, t, review_date)
                for t in portfolio.held_tickers()
            }
            snap.current_weight = portfolio.get_weight(ticker, prices_now)
            snap.target_weight = snap.current_weight
            if snap.current_price is None:
                record.missing_prices.append(ticker)
            holdings.append(snap)

    # Build candidate snapshots from DB — with temporal filtering (Step 8.1)
    held_tickers = portfolio.held_tickers()
    cand_query = select(Candidate)
    if ticker_filter:
        cand_query = cand_query.where(Candidate.ticker == ticker_filter)
    all_candidates = session.scalars(cand_query).all()

    as_of_dt = datetime.combine(review_date, datetime.max.time())
    candidates: list[CandidateSnapshot] = []
    for cand in all_candidates:
        if cand.ticker in held_tickers:
            continue

        # Step 8.1: candidate temporal filtering
        if cand.created_at is not None and cand.created_at > as_of_dt:
            # Candidate created after replay date — always exclude
            if strict_replay:
                purity.skipped_impure_candidates += 1
            continue

        if cand.created_at is None:
            # No temporal provenance — strict mode excludes, non-strict warns
            if strict_replay:
                purity.skipped_impure_candidates += 1
                purity.integrity_warnings.append(
                    f"Candidate {cand.ticker}: no created_at, excluded in strict mode"
                )
                continue
            else:
                purity.impure_candidate_count += 1
                purity.integrity_warnings.append(
                    f"Candidate {cand.ticker}: no created_at, included with warning"
                )

        snapshot = _build_replay_candidate_snapshot(
            session, cand, review_date,
            strict_replay=strict_replay, purity=purity,
        )
        if snapshot:
            candidates.append(snapshot)

    # Run decision engine
    engine_input = DecisionInput(
        review_date=review_date,
        holdings=holdings,
        candidates=candidates,
    )
    result = run_decision_engine(engine_input)
    result.review_type = "replay"
    record.result = result

    # Optionally apply trades
    if apply_trades:
        exec_result = apply_recommendations(portfolio, result, prices_by_ticker)
        record.execution_result = exec_result

        # Update shadow position probation state based on decisions
        for decision in result.decisions:
            if decision.action == ActionType.PROBATION:
                pos = portfolio.get_position(decision.ticker)
                if pos and not pos.probation_flag:
                    pos.probation_flag = True
                    pos.probation_start_date = review_date
                    pos.probation_reviews_count = 0
                elif pos and pos.probation_flag:
                    pos.probation_reviews_count += 1

        # Take portfolio snapshot
        prices_now = {
            t: _get_price_on_date(prices_by_ticker, t, review_date)
            for t in portfolio.held_tickers()
        }
        record.snapshot = portfolio.take_snapshot(review_date, prices_now)

    return record


def _get_price_on_date(
    prices_by_ticker: dict[str, list[tuple[date, float]]],
    ticker: str,
    as_of: date,
) -> float:
    """Get latest price on or before as_of from preloaded data."""
    ticker_prices = prices_by_ticker.get(ticker, [])
    best = 0.0
    for d, price in ticker_prices:
        if d <= as_of:
            best = price
        else:
            break
    return best


def generate_review_dates(
    start: date, end: date, cadence_days: int = 7,
) -> list[date]:
    """Generate review dates from start to end at the given cadence."""
    dates = []
    current = start
    while current <= end:
        dates.append(current)
        current += timedelta(days=cadence_days)
    return dates
