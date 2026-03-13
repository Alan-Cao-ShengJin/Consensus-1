"""Historical evaluation: forward-return analysis and usefulness tables.

Runs decision replay on regenerated thesis state and measures forward
outcomes against actual price data. Produces the decision-quality tables
needed for a proof run.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from historical_eval_config import HistoricalEvalConfig
from replay_runner import run_replay
from replay_engine import ReplayRunResult, _preload_prices
from replay_metrics import ReplayMetrics
from shadow_portfolio import ShadowPortfolio
from models import Price, Candidate, Thesis
from eval_harness import (
    compute_recommendation_diagnostics,
    compute_benchmark_comparison,
    BenchmarkComparison,
    RecommendationDiagnostics,
)

logger = logging.getLogger(__name__)


@dataclass
class ActionOutcome:
    """Outcome record for a single decision action."""
    review_date: date
    ticker: str
    action: str
    conviction: float
    conviction_bucket: str
    rationale: str
    price_at_decision: Optional[float] = None
    forward_5d: Optional[float] = None
    forward_20d: Optional[float] = None
    forward_60d: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "review_date": self.review_date.isoformat(),
            "ticker": self.ticker,
            "action": self.action,
            "conviction": round(self.conviction, 1),
            "conviction_bucket": self.conviction_bucket,
            "rationale": self.rationale[:200] if self.rationale else "",
            "price_at_decision": round(self.price_at_decision, 2) if self.price_at_decision else None,
            "forward_5d_pct": round(self.forward_5d, 2) if self.forward_5d is not None else None,
            "forward_20d_pct": round(self.forward_20d, 2) if self.forward_20d is not None else None,
            "forward_60d_pct": round(self.forward_60d, 2) if self.forward_60d is not None else None,
        }


@dataclass
class ForwardReturnSummary:
    """Aggregated forward returns by action type."""
    action: str
    count: int = 0
    avg_5d: Optional[float] = None
    avg_20d: Optional[float] = None
    avg_60d: Optional[float] = None
    count_with_5d: int = 0
    count_with_20d: int = 0
    count_with_60d: int = 0

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "count": self.count,
            "avg_forward_5d_pct": round(self.avg_5d, 2) if self.avg_5d is not None else None,
            "avg_forward_20d_pct": round(self.avg_20d, 2) if self.avg_20d is not None else None,
            "avg_forward_60d_pct": round(self.avg_60d, 2) if self.avg_60d is not None else None,
            "count_with_5d_data": self.count_with_5d,
            "count_with_20d_data": self.count_with_20d,
            "count_with_60d_data": self.count_with_60d,
        }


@dataclass
class ConvictionBucketSummary:
    """Aggregated stats by conviction bucket."""
    bucket: str
    action_count: int = 0
    avg_conviction: Optional[float] = None
    avg_forward_5d: Optional[float] = None
    avg_forward_20d: Optional[float] = None
    avg_forward_60d: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "bucket": self.bucket,
            "action_count": self.action_count,
            "avg_conviction": round(self.avg_conviction, 1) if self.avg_conviction is not None else None,
            "avg_forward_5d_pct": round(self.avg_forward_5d, 2) if self.avg_forward_5d is not None else None,
            "avg_forward_20d_pct": round(self.avg_forward_20d, 2) if self.avg_forward_20d is not None else None,
            "avg_forward_60d_pct": round(self.avg_forward_60d, 2) if self.avg_forward_60d is not None else None,
        }


@dataclass
class HistoricalEvalResult:
    """Full result of a historical evaluation."""
    config: HistoricalEvalConfig
    run_result: Optional[ReplayRunResult] = None
    portfolio: Optional[ShadowPortfolio] = None
    metrics: Optional[ReplayMetrics] = None
    diagnostics: Optional[RecommendationDiagnostics] = None
    benchmark: Optional[BenchmarkComparison] = None
    action_outcomes: list[ActionOutcome] = field(default_factory=list)
    forward_return_summary: list[ForwardReturnSummary] = field(default_factory=list)
    conviction_buckets: list[ConvictionBucketSummary] = field(default_factory=list)
    decision_rows: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "config": self.config.to_dict(),
            "metrics": self.metrics.to_dict() if self.metrics else None,
            "diagnostics": self.diagnostics.to_dict() if self.diagnostics else None,
            "benchmark": self.benchmark.to_dict() if self.benchmark else None,
            "forward_return_summary": [s.to_dict() for s in self.forward_return_summary],
            "conviction_buckets": [b.to_dict() for b in self.conviction_buckets],
            "action_outcomes_count": len(self.action_outcomes),
            "warnings": self.warnings,
        }


def run_historical_evaluation(
    session: Session,
    config: HistoricalEvalConfig,
) -> HistoricalEvalResult:
    """Run evaluation on regenerated historical state.

    Steps:
      1. Run replay over eval window on the regen DB
      2. Compute diagnostics and benchmark comparison
      3. Compute forward returns for each decision
      4. Aggregate by action type and conviction bucket
      5. Build decision-level rows for CSV export

    Args:
        session: Session pointing to the regeneration DB.
        config: Historical evaluation config.
    """
    result = HistoricalEvalResult(config=config)

    # 1. Run replay
    try:
        run_result, portfolio, metrics = run_replay(
            session,
            start_date=config.eval_start,
            end_date=config.eval_end,
            cadence_days=config.cadence_days,
            initial_cash=config.initial_cash,
            apply_trades=config.apply_trades,
            transaction_cost_bps=config.transaction_cost_bps,
            strict_replay=config.strict_replay,
        )
    except Exception as e:
        result.warnings.append(f"Replay failed: {e}")
        logger.error("Historical replay failed: %s", e)
        return result

    result.run_result = run_result
    result.portfolio = portfolio
    result.metrics = metrics

    # 2. Diagnostics
    try:
        diagnostics = compute_recommendation_diagnostics(run_result, portfolio)
        result.diagnostics = diagnostics
    except Exception as e:
        result.warnings.append(f"Diagnostics computation failed: {e}")

    # Benchmark comparison — adapt HistoricalEvalConfig to EvalConfig interface
    try:
        from eval_config import EvalConfig
        eval_cfg = EvalConfig(
            start_date=config.eval_start,
            end_date=config.eval_end,
            benchmark_ticker=config.benchmark_ticker,
            include_equal_weight_baseline=config.include_equal_weight_baseline,
        )
        benchmark = compute_benchmark_comparison(
            session, eval_cfg, metrics.total_return_pct,
        )
        result.benchmark = benchmark
    except Exception as e:
        result.warnings.append(f"Benchmark comparison failed: {e}")

    # 3. Preload prices for forward-return computation
    tickers = config.effective_tickers()
    prices_by_ticker = _preload_prices(session, tickers)

    # 4. Compute per-decision forward returns
    for rec in run_result.review_records:
        for decision in rec.result.decisions:
            if decision.action.value in ("no_action",):
                continue

            outcome = _compute_action_outcome(
                decision, rec.review_date, prices_by_ticker,
                config,
            )
            result.action_outcomes.append(outcome)

            # Decision row for CSV
            result.decision_rows.append({
                "review_date": rec.review_date.isoformat(),
                "ticker": decision.ticker,
                "action": decision.action.value,
                "conviction": round(decision.action_score, 1),
                "conviction_bucket": outcome.conviction_bucket,
                "rationale": (decision.rationale or "")[:200],
            })

    # 5. Aggregate forward returns by action type
    result.forward_return_summary = _aggregate_by_action(result.action_outcomes)

    # 6. Aggregate by conviction bucket
    result.conviction_buckets = _aggregate_by_conviction(
        result.action_outcomes, config,
    )

    # Check for data quality warnings
    if not result.action_outcomes:
        result.warnings.append("No action outcomes generated — check data availability")
    else:
        actions_missing_price = sum(
            1 for o in result.action_outcomes if o.price_at_decision is None
        )
        if actions_missing_price > 0:
            result.warnings.append(
                f"{actions_missing_price}/{len(result.action_outcomes)} actions "
                f"missing decision-date price"
            )

    return result


def _compute_action_outcome(
    decision,
    review_date: date,
    prices_by_ticker: dict,
    config: HistoricalEvalConfig,
) -> ActionOutcome:
    """Compute forward returns for a single decision."""
    ticker = decision.ticker
    outcome = ActionOutcome(
        review_date=review_date,
        ticker=ticker,
        action=decision.action.value,
        conviction=decision.action_score,
        conviction_bucket=config.conviction_bucket_for(decision.action_score),
        rationale=decision.rationale or "",
    )

    price_data = prices_by_ticker.get(ticker, [])
    if not price_data:
        return outcome

    # Find decision-date price
    decision_price = _get_price_on_date(price_data, review_date)
    if decision_price is None:
        return outcome
    outcome.price_at_decision = decision_price

    # Compute forward returns for each horizon
    for horizon in config.forward_return_days:
        target_date = review_date + timedelta(days=horizon)
        future_price = _get_price_on_date(price_data, target_date)
        if future_price is not None and decision_price > 0:
            fwd_return = ((future_price - decision_price) / decision_price) * 100.0
            if horizon == 5:
                outcome.forward_5d = fwd_return
            elif horizon == 20:
                outcome.forward_20d = fwd_return
            elif horizon == 60:
                outcome.forward_60d = fwd_return

    return outcome


def _get_price_on_date(
    price_data: list,
    target_date: date,
    max_gap_days: int = 5,
) -> Optional[float]:
    """Get the closest price on or before target_date.

    price_data is a list of (date, close) tuples sorted by date ascending.
    """
    best = None
    for d, close in price_data:
        if d <= target_date:
            best = (d, close)
        else:
            break

    if best is None:
        return None
    if (target_date - best[0]).days > max_gap_days:
        return None
    return best[1]


def _aggregate_by_action(outcomes: list[ActionOutcome]) -> list[ForwardReturnSummary]:
    """Aggregate forward returns by action type."""
    by_action: dict[str, list[ActionOutcome]] = defaultdict(list)
    for o in outcomes:
        by_action[o.action].append(o)

    summaries = []
    for action in sorted(by_action.keys()):
        items = by_action[action]
        s = ForwardReturnSummary(action=action, count=len(items))

        fwd_5 = [o.forward_5d for o in items if o.forward_5d is not None]
        fwd_20 = [o.forward_20d for o in items if o.forward_20d is not None]
        fwd_60 = [o.forward_60d for o in items if o.forward_60d is not None]

        s.count_with_5d = len(fwd_5)
        s.count_with_20d = len(fwd_20)
        s.count_with_60d = len(fwd_60)

        if fwd_5:
            s.avg_5d = sum(fwd_5) / len(fwd_5)
        if fwd_20:
            s.avg_20d = sum(fwd_20) / len(fwd_20)
        if fwd_60:
            s.avg_60d = sum(fwd_60) / len(fwd_60)

        summaries.append(s)

    return summaries


def _aggregate_by_conviction(
    outcomes: list[ActionOutcome],
    config: HistoricalEvalConfig,
) -> list[ConvictionBucketSummary]:
    """Aggregate by conviction bucket."""
    by_bucket: dict[str, list[ActionOutcome]] = defaultdict(list)
    for o in outcomes:
        by_bucket[o.conviction_bucket].append(o)

    summaries = []
    for low, high, label in config.conviction_buckets:
        items = by_bucket.get(label, [])
        s = ConvictionBucketSummary(bucket=label, action_count=len(items))

        if items:
            s.avg_conviction = sum(o.conviction for o in items) / len(items)

            fwd_5 = [o.forward_5d for o in items if o.forward_5d is not None]
            fwd_20 = [o.forward_20d for o in items if o.forward_20d is not None]
            fwd_60 = [o.forward_60d for o in items if o.forward_60d is not None]

            if fwd_5:
                s.avg_forward_5d = sum(fwd_5) / len(fwd_5)
            if fwd_20:
                s.avg_forward_20d = sum(fwd_20) / len(fwd_20)
            if fwd_60:
                s.avg_forward_60d = sum(fwd_60) / len(fwd_60)

        summaries.append(s)

    return summaries


@dataclass
class HistoricalMemoryComparisonResult:
    """Result of comparing memory-ON vs memory-OFF historical regeneration."""
    regen_on: dict = field(default_factory=dict)
    regen_off: dict = field(default_factory=dict)
    eval_on: Optional[HistoricalEvalResult] = None
    eval_off: Optional[HistoricalEvalResult] = None
    comparison: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "regeneration_on": self.regen_on,
            "regeneration_off": self.regen_off,
            "eval_on": self.eval_on.to_dict() if self.eval_on else None,
            "eval_off": self.eval_off.to_dict() if self.eval_off else None,
            "comparison": self.comparison,
            "warnings": self.warnings,
        }


def run_historical_memory_ablation(
    source_session: Session,
    config_on: HistoricalEvalConfig,
    config_off: HistoricalEvalConfig,
) -> HistoricalMemoryComparisonResult:
    """Run full historical regeneration with memory ON and OFF, then compare.

    Both runs use the same source data but different memory settings
    during thesis updates.
    """
    from historical_regeneration import run_regeneration, open_regeneration_db

    result = HistoricalMemoryComparisonResult()

    # Run memory-ON regeneration
    logger.info("Running historical regeneration with memory ON...")
    regen_on = run_regeneration(source_session, config_on)
    result.regen_on = regen_on.to_dict()

    # Run memory-OFF regeneration
    logger.info("Running historical regeneration with memory OFF...")
    regen_off = run_regeneration(source_session, config_off)
    result.regen_off = regen_off.to_dict()

    # Evaluate both
    logger.info("Evaluating memory-ON results...")
    regen_on_session = open_regeneration_db(regen_on.db_path)
    try:
        eval_on = run_historical_evaluation(regen_on_session, config_on)
        result.eval_on = eval_on
    finally:
        regen_on_session.close()

    logger.info("Evaluating memory-OFF results...")
    regen_off_session = open_regeneration_db(regen_off.db_path)
    try:
        eval_off = run_historical_evaluation(regen_off_session, config_off)
        result.eval_off = eval_off
    finally:
        regen_off_session.close()

    # Compute comparison deltas
    result.comparison = _compute_memory_comparison(
        regen_on, regen_off, eval_on, eval_off,
    )

    return result


def _compute_memory_comparison(
    regen_on, regen_off,
    eval_on: Optional[HistoricalEvalResult],
    eval_off: Optional[HistoricalEvalResult],
) -> dict:
    """Compute side-by-side comparison metrics."""
    comp = {
        "regeneration": {
            "thesis_updates_on": regen_on.total_thesis_updates,
            "thesis_updates_off": regen_off.total_thesis_updates,
            "state_changes_on": regen_on.total_state_changes,
            "state_changes_off": regen_off.total_state_changes,
            "state_flips_on": regen_on.total_state_flips,
            "state_flips_off": regen_off.total_state_flips,
        },
    }

    if eval_on and eval_on.metrics and eval_off and eval_off.metrics:
        m_on = eval_on.metrics
        m_off = eval_off.metrics
        comp["portfolio"] = {
            "return_on_pct": round(m_on.total_return_pct, 2),
            "return_off_pct": round(m_off.total_return_pct, 2),
            "return_delta_pct": round(m_on.total_return_pct - m_off.total_return_pct, 2),
            "drawdown_on_pct": round(m_on.max_drawdown_pct, 2),
            "drawdown_off_pct": round(m_off.max_drawdown_pct, 2),
            "initiations_on": m_on.total_initiations,
            "initiations_off": m_off.total_initiations,
            "exits_on": m_on.total_exits,
            "exits_off": m_off.total_exits,
        }

    if eval_on and eval_on.diagnostics and eval_off and eval_off.diagnostics:
        d_on = eval_on.diagnostics
        d_off = eval_off.diagnostics
        comp["diagnostics"] = {
            "recommendation_changes_on": d_on.recommendation_changes,
            "recommendation_changes_off": d_off.recommendation_changes,
            "total_actions_on": sum(d_on.action_counts.values()),
            "total_actions_off": sum(d_off.action_counts.values()),
        }

    # Compare forward returns by action type
    if eval_on and eval_off:
        fwd_on = {s.action: s for s in eval_on.forward_return_summary}
        fwd_off = {s.action: s for s in eval_off.forward_return_summary}
        fwd_comp = {}
        for action in set(list(fwd_on.keys()) + list(fwd_off.keys())):
            on = fwd_on.get(action)
            off = fwd_off.get(action)
            fwd_comp[action] = {
                "count_on": on.count if on else 0,
                "count_off": off.count if off else 0,
                "avg_20d_on": round(on.avg_20d, 2) if on and on.avg_20d is not None else None,
                "avg_20d_off": round(off.avg_20d, 2) if off and off.avg_20d is not None else None,
            }
        comp["forward_returns_by_action"] = fwd_comp

    return comp
