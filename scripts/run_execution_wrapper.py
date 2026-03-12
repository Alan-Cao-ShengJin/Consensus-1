"""CLI entrypoint for Step 9 execution wrapper.

Usage examples:
  python scripts/run_execution_wrapper.py --latest-review --validate-only
  python scripts/run_execution_wrapper.py --latest-review --paper-execute
  python scripts/run_execution_wrapper.py --latest-review --json
  python scripts/run_execution_wrapper.py --latest-review --paper-execute --dry-run
  python scripts/run_execution_wrapper.py --demo

The --demo flag runs a self-contained demonstration with synthetic data,
no database required.
"""
from __future__ import annotations

import argparse
import json
import sys
import os
from datetime import date, datetime

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import ActionType
from portfolio_decision_engine import (
    TickerDecision, PortfolioReviewResult, ReasonCode,
    PRIORITY_FORCED_EXIT, PRIORITY_STRONG_EXIT, PRIORITY_DEFENSIVE,
    PRIORITY_GROWTH, PRIORITY_NEUTRAL,
)
from execution_wrapper import build_execution_batch, OrderIntent
from execution_policy import ExecutionPolicyConfig, DEFAULT_POLICY
from execution_guardrails import validate_execution_batch
from paper_execution_engine import (
    PaperPortfolio, paper_execute, export_execution_artifacts,
    format_execution_text,
)


def build_demo_review() -> tuple[PortfolioReviewResult, dict[str, float], float, dict[str, float]]:
    """Build a synthetic review result for demonstration.

    Returns (review_result, current_weights, portfolio_value, reference_prices).
    """
    review_date = date(2025, 10, 1)

    decisions = [
        # EXIT: thesis broken
        TickerDecision(
            ticker="BRKN",
            action=ActionType.EXIT,
            action_score=100.0,
            recommendation_priority=PRIORITY_FORCED_EXIT,
            target_weight_change=-5.0,
            suggested_weight=0.0,
            reason_codes=[ReasonCode.THESIS_BROKEN],
            rationale="Thesis broken -- forced exit",
        ),
        # TRIM: valuation stretched
        TickerDecision(
            ticker="STRCH",
            action=ActionType.TRIM,
            action_score=70.0,
            recommendation_priority=PRIORITY_DEFENSIVE,
            target_weight_change=-2.0,
            suggested_weight=4.0,
            reason_codes=[ReasonCode.VALUATION_STRETCHED],
            rationale="Valuation stretched -- trim",
        ),
        # INITIATE: all gates passed
        TickerDecision(
            ticker="NEWCO",
            action=ActionType.INITIATE,
            action_score=65.0,
            recommendation_priority=PRIORITY_GROWTH,
            target_weight_change=3.0,
            suggested_weight=3.0,
            reason_codes=[ReasonCode.VALUATION_ATTRACTIVE, ReasonCode.SUFFICIENT_NOVEL_EVIDENCE],
            rationale="All entry gates passed -- initiate",
        ),
        # ADD: winner with strong conviction
        TickerDecision(
            ticker="WINR",
            action=ActionType.ADD,
            action_score=55.0,
            recommendation_priority=PRIORITY_GROWTH,
            target_weight_change=1.5,
            suggested_weight=6.5,
            reason_codes=[ReasonCode.ADD_TO_WINNER, ReasonCode.VALUATION_ATTRACTIVE],
            rationale="Winner with strong conviction -- add",
        ),
        # HOLD: neutral
        TickerDecision(
            ticker="STDY",
            action=ActionType.HOLD,
            action_score=0.0,
            recommendation_priority=PRIORITY_NEUTRAL,
            reason_codes=[ReasonCode.VALUATION_NEUTRAL],
            rationale="Hold -- conviction 60, thesis stable",
        ),
        # PROBATION: low conviction
        TickerDecision(
            ticker="PROB",
            action=ActionType.PROBATION,
            action_score=60.0,
            recommendation_priority=PRIORITY_DEFENSIVE,
            reason_codes=[ReasonCode.PROBATION_ACTIVE],
            rationale="On probation -- no adds allowed",
        ),
        # NO_ACTION: blocked candidate
        TickerDecision(
            ticker="BLKD",
            action=ActionType.NO_ACTION,
            action_score=0.0,
            recommendation_priority=PRIORITY_NEUTRAL,
            decision_stage="blocked",
            reason_codes=[ReasonCode.COOLDOWN_ACTIVE],
            blocking_conditions=["Cooldown active until 2025-11-01"],
            rationale="Re-entry blocked by cooldown",
        ),
    ]

    result = PortfolioReviewResult(
        review_date=review_date,
        decisions=decisions,
        turnover_pct_planned=11.5,
        turnover_pct_cap=20.0,
    )

    current_weights = {
        "BRKN": 5.0,
        "STRCH": 6.0,
        "WINR": 5.0,
        "STDY": 4.0,
        "PROB": 3.0,
    }

    portfolio_value = 1_000_000.0

    reference_prices = {
        "BRKN": 45.00,
        "STRCH": 120.00,
        "NEWCO": 85.00,
        "WINR": 200.00,
        "STDY": 150.00,
        "PROB": 60.00,
    }

    return result, current_weights, portfolio_value, reference_prices


def run_from_latest_review(args):
    """Run execution wrapper from the latest DB review.

    Loads the most recent PortfolioReview + PortfolioDecisions from the database,
    reconstructs current weights from PortfolioPositions, and runs the pipeline.
    """
    from db import SessionLocal
    from sqlalchemy import select
    from models import PortfolioReview, PortfolioDecision, PortfolioPosition

    session = SessionLocal()
    try:
        # Find latest review
        stmt = select(PortfolioReview).order_by(PortfolioReview.id.desc()).limit(1)
        review = session.execute(stmt).scalar_one_or_none()
        if review is None:
            print("No portfolio reviews found in database.")
            return

        print(f"Latest review: {review.review_date} (id={review.id}, type={review.review_type})")

        # Load decisions
        stmt = select(PortfolioDecision).where(PortfolioDecision.review_id == review.id)
        db_decisions = session.execute(stmt).scalars().all()
        if not db_decisions:
            print("No decisions found for this review.")
            return

        # Reconstruct TickerDecisions
        decisions = []
        for d in db_decisions:
            td = TickerDecision(
                ticker=d.ticker,
                action=d.action,
                action_score=d.action_score,
                target_weight_change=d.target_weight_change,
                suggested_weight=d.suggested_weight,
                reason_codes=[ReasonCode(r) for r in json.loads(d.reason_codes or "[]")],
                rationale=d.rationale or "",
                blocking_conditions=json.loads(d.blocking_conditions or "[]"),
                required_followup=json.loads(d.required_followup or "[]") if d.required_followup else [],
                decision_stage="blocked" if d.blocking_conditions and json.loads(d.blocking_conditions) else "recommendation",
                generated_at=d.generated_at,
            )
            decisions.append(td)

        review_result = PortfolioReviewResult(
            review_date=review.review_date,
            decisions=decisions,
            turnover_pct_planned=review.turnover_pct,
            turnover_pct_cap=20.0,
        )

        # Get current weights from positions
        stmt = select(PortfolioPosition).where(PortfolioPosition.status == "active")
        positions = session.execute(stmt).scalars().all()
        current_weights = {p.ticker: p.current_weight for p in positions}

        # Estimate portfolio value (sum of weights is approximate)
        portfolio_value = 1_000_000.0  # default if no better estimate

        # Reference prices: use latest from price_history if available
        reference_prices = {}
        for d in decisions:
            reference_prices[d.ticker] = 100.0  # placeholder

        return run_pipeline(
            review_result, current_weights, portfolio_value, reference_prices,
            review_id=review.id, args=args,
        )

    finally:
        session.close()


def run_pipeline(
    review_result: PortfolioReviewResult,
    current_weights: dict[str, float],
    portfolio_value: float,
    reference_prices: dict[str, float],
    review_id=None,
    args=None,
):
    """Core pipeline: review -> intents -> validate -> paper-execute."""
    dry_run = getattr(args, "dry_run", False)
    paper_trade = True
    output_json = getattr(args, "json_output", False)
    validate_only = getattr(args, "validate_only", False)
    do_paper_execute = getattr(args, "paper_execute", False)

    # Step 1: Build execution batch (order intents)
    batch = build_execution_batch(
        review_result=review_result,
        current_weights=current_weights,
        portfolio_value=portfolio_value,
        reference_prices=reference_prices,
        review_id=review_id,
        dry_run=dry_run,
        paper_trade=paper_trade,
    )

    if output_json and not validate_only and not do_paper_execute:
        print(json.dumps(batch.to_dict(), indent=2))
        return batch

    if not output_json:
        print(f"\n  Review date:      {batch.review_date}")
        print(f"  Portfolio value:  ${batch.portfolio_value:,.2f}")
        print(f"  Order intents:    {len(batch.order_intents)}")
        print(f"  Skipped (hold):   {len(batch.skipped_non_trading)}")
        print(f"  Skipped (blocked):{len(batch.skipped_blocked)}")

    # Step 2: Validate
    validation = validate_execution_batch(
        batch=batch,
        current_weights=current_weights,
        config=DEFAULT_POLICY,
    )

    if not output_json:
        print(f"\n  Guardrail validation: {'PASSED' if validation.all_passed else 'FAILED'}")
        print(f"  Approved: {len(validation.approved_intents)}")
        print(f"  Blocked:  {len(validation.blocked_intents)}")
        if validation.batch_violations:
            for v in validation.batch_violations:
                print(f"    BATCH: {v}")
        for gr in validation.intent_results:
            status = "OK" if gr.passed else "BLOCKED"
            print(f"    {gr.ticker:8s} {status}", end="")
            if gr.violations:
                print(f"  ({'; '.join(gr.violations)})", end="")
            print()

    if validate_only:
        if output_json:
            print(json.dumps(validation.to_dict(), indent=2))
        return validation

    # Step 3: Paper execute
    if do_paper_execute:
        portfolio = PaperPortfolio(
            initial_cash=portfolio_value,
            transaction_cost_bps=DEFAULT_POLICY.transaction_cost_bps,
        )

        # For demo: pre-seed existing positions from current weights
        for ticker, weight in current_weights.items():
            if weight > 0 and ticker in reference_prices:
                notional = (weight / 100.0) * portfolio_value
                shares = notional / reference_prices[ticker]
                portfolio.execute_buy(
                    ticker=ticker,
                    shares=shares,
                    price=reference_prices[ticker],
                    action_type="seed",
                    trade_date=review_result.review_date,
                )

        # Reset cash to reflect that seed buys came from initial capital
        # (This is a paper portfolio — we're modeling existing state)
        portfolio.cash = portfolio_value - sum(
            (w / 100.0) * portfolio_value for w in current_weights.values() if w > 0
        )

        summary = paper_execute(
            portfolio=portfolio,
            approved_intents=validation.approved_intents,
            blocked_intents=validation.blocked_intents,
            execution_date=review_result.review_date,
            fill_prices=reference_prices,
            config=DEFAULT_POLICY,
        )

        if output_json:
            print(json.dumps(summary.to_dict(), indent=2))
        else:
            print(format_execution_text(summary))

        # Export artifacts
        if not dry_run:
            out_dir = export_execution_artifacts(summary, batch)
            if not output_json:
                print(f"\n  Artifacts exported to: {out_dir}/")

        return summary

    # Default: just show intents
    if output_json:
        print(json.dumps(batch.to_dict(), indent=2))
    else:
        print("\nORDER INTENTS:")
        for oi in batch.order_intents:
            print(
                f"  {oi.action_type.value:10s} {oi.ticker:8s} "
                f"{oi.side:4s}  weight: {oi.target_weight_before:.1f}% -> {oi.target_weight_after:.1f}%  "
                f"notional: ${oi.notional_delta:+,.0f}"
            )

    return batch


def main():
    parser = argparse.ArgumentParser(description="Step 9: Execution Wrapper & Paper Trading")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--latest-review", action="store_true", help="Use latest review from DB")
    source.add_argument("--demo", action="store_true", help="Run with synthetic demo data")

    parser.add_argument("--validate-only", action="store_true", help="Validate intents only, no execution")
    parser.add_argument("--paper-execute", action="store_true", help="Paper-execute validated intents")
    parser.add_argument("--json", dest="json_output", action="store_true", help="Output as JSON")
    parser.add_argument("--dry-run", action="store_true", help="Dry run (no file output)")

    args = parser.parse_args()

    if args.demo:
        review_result, current_weights, portfolio_value, reference_prices = build_demo_review()
        run_pipeline(review_result, current_weights, portfolio_value, reference_prices, args=args)
    elif args.latest_review:
        run_from_latest_review(args)


if __name__ == "__main__":
    main()
