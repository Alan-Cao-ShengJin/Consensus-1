"""Replay runner: orchestrate a full replay run over a date range.

Takes start/end/cadence, steps through review dates, runs as-of reviews,
optionally applies to shadow portfolio, computes summary metrics.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from replay_engine import (
    ReplayRunResult, generate_review_dates, run_replay_review,
    _preload_prices,
)
from replay_metrics import compute_metrics, ReplayMetrics
from shadow_portfolio import ShadowPortfolio
from models import Candidate

logger = logging.getLogger(__name__)


def run_replay(
    session: Session,
    *,
    start_date: date,
    end_date: date,
    cadence_days: int = 7,
    initial_cash: float = 1_000_000.0,
    apply_trades: bool = True,
    ticker_filter: Optional[str] = None,
    transaction_cost_bps: float = 10.0,
    strict_replay: bool = False,
) -> tuple[ReplayRunResult, ShadowPortfolio, ReplayMetrics]:
    """Run a full replay over the given date range.

    Args:
        session: DB session (read-only for replay — no mutations to live data).
        start_date: First review date.
        end_date: Last review date (inclusive).
        cadence_days: Days between reviews (default 7 = weekly).
        initial_cash: Starting cash for shadow portfolio.
        apply_trades: If True, apply recommendations to shadow portfolio.
        ticker_filter: If set, only replay this ticker.
        transaction_cost_bps: Transaction cost in basis points.
        strict_replay: If True, skip impure inputs rather than using fallbacks.

    Returns:
        (run_result, portfolio, metrics) tuple.
    """
    logger.info(
        "Starting replay: %s to %s, cadence=%dd, cash=%.0f, apply=%s, strict=%s",
        start_date, end_date, cadence_days, initial_cash, apply_trades, strict_replay,
    )

    portfolio = ShadowPortfolio(
        initial_cash=initial_cash,
        transaction_cost_bps=transaction_cost_bps,
    )

    review_dates = generate_review_dates(start_date, end_date, cadence_days)
    if not review_dates:
        logger.warning("No review dates generated for range %s to %s", start_date, end_date)

    # Preload prices for all candidate tickers
    candidate_tickers = _get_all_tickers(session, ticker_filter)
    prices_by_ticker = _preload_prices(session, candidate_tickers)

    run_result = ReplayRunResult(
        start_date=start_date,
        end_date=end_date,
        cadence_days=cadence_days,
        initial_cash=initial_cash,
        apply_trades=apply_trades,
        strict_replay=strict_replay,
    )

    for review_date in review_dates:
        logger.info("Replay review: %s", review_date.isoformat())

        record = run_replay_review(
            session=session,
            portfolio=portfolio,
            review_date=review_date,
            prices_by_ticker=prices_by_ticker,
            ticker_filter=ticker_filter,
            apply_trades=apply_trades,
            strict_replay=strict_replay,
        )
        run_result.review_records.append(record)

        # Accumulate integrity counters
        run_result.total_reviews += 1
        run_result.total_recommendations += len(record.result.decisions)
        if record.execution_result:
            run_result.total_trades_applied += len(record.execution_result.trades_applied)
            run_result.total_trades_skipped += len(record.execution_result.trades_skipped)
            run_result.total_fallback_count += record.execution_result.fallback_count

        # Accumulate purity counters (Step 8.1)
        run_result.total_impure_candidates += record.purity.impure_candidate_count
        run_result.total_impure_valuations += record.purity.impure_valuation_count
        run_result.total_impure_checkpoints += record.purity.impure_checkpoint_count
        run_result.total_skipped_impure += (
            record.purity.skipped_impure_candidates
            + record.purity.skipped_impure_valuation
            + record.purity.skipped_impure_checkpoints
        )
        run_result.integrity_warnings.extend(record.purity.integrity_warnings)

    # Compute purity level
    run_result.purity_level = _compute_purity_level(run_result)

    # Compute metrics
    metrics = compute_metrics(run_result, portfolio)

    logger.info(
        "Replay complete: %d reviews, %d recommendations, %d trades, return=%.2f%%, purity=%s",
        run_result.total_reviews, run_result.total_recommendations,
        run_result.total_trades_applied, metrics.total_return_pct,
        run_result.purity_level,
    )

    return run_result, portfolio, metrics


def _compute_purity_level(run_result: ReplayRunResult) -> str:
    """Determine overall purity level of the replay run."""
    total_impure = (
        run_result.total_impure_candidates
        + run_result.total_impure_valuations
        + run_result.total_impure_checkpoints
    )
    total_skipped = run_result.total_skipped_impure

    if total_impure == 0 and total_skipped == 0:
        return "strict"
    if total_impure == 0 and total_skipped > 0:
        # All impurities were skipped (strict mode)
        return "strict"
    if total_impure > 0 and total_skipped == 0:
        return "degraded"
    return "mixed"


def _get_all_tickers(
    session: Session, ticker_filter: Optional[str],
) -> list[str]:
    """Get all tickers that might be involved in replay."""
    if ticker_filter:
        return [ticker_filter]
    from sqlalchemy import select
    from models import Candidate, Thesis
    cand_tickers = session.scalars(select(Candidate.ticker).distinct()).all()
    thesis_tickers = session.scalars(
        select(Thesis.company_ticker).where(Thesis.status_active.is_(True)).distinct()
    ).all()
    return list(set(cand_tickers) | set(thesis_tickers))


def export_replay_json(
    run_result: ReplayRunResult,
    portfolio: ShadowPortfolio,
    metrics: ReplayMetrics,
    output_dir: str = "replay_outputs",
) -> str:
    """Export replay results to a JSON file.

    Returns the output file path.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    filename = f"replay_{run_result.start_date}_{run_result.end_date}.json"
    filepath = os.path.join(output_dir, filename)

    output = {
        "run": run_result.to_dict(),
        "portfolio": portfolio.to_dict(),
        "metrics": metrics.to_dict(),
        "trades": [t.to_dict() for t in portfolio.trades],
        "snapshots": [s.to_dict() for s in portfolio.snapshots],
    }

    with open(filepath, "w") as f:
        json.dump(output, f, indent=2)

    logger.info("Replay exported to %s", filepath)
    return filepath


def format_replay_text(
    run_result: ReplayRunResult,
    portfolio: ShadowPortfolio,
    metrics: ReplayMetrics,
) -> str:
    """Format a human-readable replay summary."""
    m = metrics
    lines = [
        f"Replay Summary: {run_result.start_date} to {run_result.end_date}",
        "=" * 70,
        f"Cadence: {run_result.cadence_days}d | Initial cash: ${run_result.initial_cash:,.0f}",
        f"Trades applied: {run_result.apply_trades} | Strict mode: {run_result.strict_replay}",
        f"Purity level: {run_result.purity_level}",
        "",
        "--- PERFORMANCE ---",
        f"  Total return:      {m.total_return_pct:+.2f}%",
    ]
    if m.annualized_return_pct is not None:
        lines.append(f"  Annualized return: {m.annualized_return_pct:+.2f}%")
    lines.extend([
        f"  Max drawdown:      {m.max_drawdown_pct:.2f}%",
        "",
        "--- ACTIVITY ---",
        f"  Initiations: {m.total_initiations}  Adds: {m.total_adds}  "
        f"Trims: {m.total_trims}  Exits: {m.total_exits}",
        f"  Holds: {m.total_holds}  Probations: {m.total_probations}  "
        f"Blocked: {m.total_blocked}",
    ])
    if m.avg_holding_period_days is not None:
        lines.append(f"  Avg holding period: {m.avg_holding_period_days:.0f} days")
    lines.extend([
        "",
        "--- TURNOVER ---",
        f"  Total turnover:    {m.total_turnover_pct:.1f}%",
        f"  Avg per review:    {m.avg_turnover_per_review_pct:.1f}%",
        "",
        "--- CASH EXPOSURE ---",
        f"  Avg: {m.avg_cash_pct:.1f}%  Min: {m.min_cash_pct:.1f}%  Max: {m.max_cash_pct:.1f}%",
        "",
        "--- DISCIPLINE ---",
        f"  Probation -> exit:     {m.probation_to_exit_count}",
        f"  Funded pairings used: {m.funded_pairing_count}",
        f"  Turnover cap blocked: {m.turnover_cap_blocked_count}",
    ])
    if m.avg_initiation_conviction is not None:
        lines.append(f"  Avg initiation conviction: {m.avg_initiation_conviction:.0f}")
    lines.extend([
        "",
        "--- REPLAY INTEGRITY ---",
        f"  Review dates processed:   {m.total_review_dates}",
        f"  Recommendations generated: {m.total_recommendations}",
        f"  Trades applied:           {m.total_trades_applied}",
        f"  Trades skipped (no price): {m.total_trades_skipped}",
        f"  Fallback behaviors:       {m.total_fallback_count}",
        f"  Missing price events:     {m.missing_price_events}",
        "",
        "--- PURITY (Step 8.1) ---",
        f"  Purity level:             {run_result.purity_level}",
        f"  Impure candidates used:   {run_result.total_impure_candidates}",
        f"  Impure valuations used:   {run_result.total_impure_valuations}",
        f"  Impure checkpoints used:  {run_result.total_impure_checkpoints}",
        f"  Inputs skipped (strict):  {run_result.total_skipped_impure}",
    ])

    if run_result.integrity_warnings:
        lines.append("")
        lines.append("--- INTEGRITY WARNINGS ---")
        # Deduplicate warnings for display
        seen = set()
        for w in run_result.integrity_warnings:
            if w not in seen:
                lines.append(f"  {w}")
                seen.add(w)

    if portfolio.snapshots:
        final = portfolio.snapshots[-1]
        lines.extend([
            "",
            "--- FINAL PORTFOLIO ---",
            f"  Total value: ${final.total_value:,.2f}",
            f"  Cash: ${final.cash:,.2f}",
            f"  Positions: {final.num_positions}",
        ])
        for ticker, weight in sorted(final.weights.items(), key=lambda x: -x[1]):
            lines.append(f"    {ticker:8s} {weight:.1f}%")

    return "\n".join(lines)
