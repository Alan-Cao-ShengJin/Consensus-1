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

Known v1 impurities (documented, not hidden):
  - Candidate pool uses current DB state (no created_at on Candidate table)
  - valuation_gap_pct and base_case_rerating use current thesis values
    (ThesisStateHistory does not track these fields)
  - Checkpoints may have been ingested after as_of but with date_expected
    before as_of (no created_at on Checkpoint table)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
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
    _get_thesis_state_as_of, build_candidate_snapshot,
)
from valuation_policy import zone_from_thesis_and_price
from shadow_portfolio import ShadowPortfolio, PortfolioSnapshot
from shadow_execution_policy import (
    apply_recommendations, ExecutionResult, get_execution_price,
)

logger = logging.getLogger(__name__)


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


@dataclass
class ReplayRunResult:
    """Complete result of a replay run."""
    start_date: date
    end_date: date
    cadence_days: int
    review_records: list[ReplayReviewRecord] = field(default_factory=list)
    initial_cash: float = 0.0
    apply_trades: bool = True
    # Integrity summary
    total_reviews: int = 0
    total_recommendations: int = 0
    total_trades_applied: int = 0
    total_trades_skipped: int = 0
    total_fallback_count: int = 0
    dates_skipped_no_data: list[date] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "cadence_days": self.cadence_days,
            "initial_cash": self.initial_cash,
            "apply_trades": self.apply_trades,
            "total_reviews": self.total_reviews,
            "total_recommendations": self.total_recommendations,
            "total_trades_applied": self.total_trades_applied,
            "total_trades_skipped": self.total_trades_skipped,
            "total_fallback_count": self.total_fallback_count,
            "dates_skipped_no_data": [d.isoformat() for d in self.dates_skipped_no_data],
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
) -> Optional[HoldingSnapshot]:
    """Build HoldingSnapshot from shadow portfolio state + DB research data.

    Anti-leakage: all DB lookups are bounded by review_date.
    Portfolio state comes from shadow (not live DB positions).
    """
    pos = portfolio.get_position(ticker)
    if pos is None:
        return None

    current_price = _get_latest_price(session, ticker, review_date)
    price_change = _get_price_change_5d(session, ticker, review_date)
    novel, confirming = _count_novel_claims_7d(session, ticker, review_date)
    has_cp, days_cp = _has_checkpoint_ahead(session, ticker, review_date)

    # Historical thesis state
    thesis_state, thesis_conviction = _get_thesis_state_as_of(session, thesis, review_date)

    zone = zone_from_thesis_and_price(
        thesis.valuation_gap_pct,
        thesis.base_case_rerating,
        current_price,
    )

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
        valuation_gap_pct=thesis.valuation_gap_pct,
        base_case_rerating=thesis.base_case_rerating,
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


def run_replay_review(
    session: Session,
    portfolio: ShadowPortfolio,
    review_date: date,
    prices_by_ticker: dict[str, list[tuple[date, float]]],
    ticker_filter: Optional[str] = None,
    apply_trades: bool = True,
) -> ReplayReviewRecord:
    """Run a single replay review at the given date.

    1. Build snapshots from shadow portfolio + DB research state (as-of)
    2. Build candidate snapshots from DB candidates (as-of)
    3. Run decision engine
    4. Optionally apply trades via shadow execution policy

    Anti-leakage: all data lookups bounded by review_date.
    """
    record = ReplayReviewRecord(
        review_date=review_date,
        result=PortfolioReviewResult(review_date=review_date),
    )

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
        snap = _build_shadow_holding_snapshot(session, portfolio, ticker, thesis, review_date)
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

    # Build candidate snapshots from DB
    held_tickers = portfolio.held_tickers()
    cand_query = select(Candidate)
    if ticker_filter:
        cand_query = cand_query.where(Candidate.ticker == ticker_filter)
    all_candidates = session.scalars(cand_query).all()

    candidates: list[CandidateSnapshot] = []
    for cand in all_candidates:
        if cand.ticker not in held_tickers:
            snapshot = build_candidate_snapshot(session, cand, review_date)
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
