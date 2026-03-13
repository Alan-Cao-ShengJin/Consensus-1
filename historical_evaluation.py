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

from exit_policy import ExitPolicyConfig, BASELINE_POLICY
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
    """Outcome record for a single decision action.

    conviction fields:
      - thesis_conviction: the raw thesis conviction score (0-100), meaningful
        for ALL action types including hold.  Use this for analysis.
      - action_score: the decision-engine urgency score (0 for holds, 50-100
        for active actions).  Use only for priority/urgency analysis.
    """
    review_date: date
    ticker: str
    action: str
    thesis_conviction: float       # raw thesis conviction, always meaningful
    action_score: float            # decision-engine urgency score
    conviction_bucket: str
    rationale: str
    price_at_decision: Optional[float] = None
    forward_5d: Optional[float] = None
    forward_20d: Optional[float] = None
    forward_60d: Optional[float] = None

    @property
    def conviction(self) -> float:
        """Alias for thesis_conviction (backwards compat for bucket logic)."""
        return self.thesis_conviction

    def to_dict(self) -> dict:
        return {
            "review_date": self.review_date.isoformat(),
            "ticker": self.ticker,
            "action": self.action,
            "thesis_conviction": round(self.thesis_conviction, 1),
            "action_score": round(self.action_score, 1),
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
class PerNameSummary:
    """Per-ticker usefulness summary."""
    ticker: str
    action_count: int = 0
    initiate_count: int = 0
    exit_count: int = 0
    hold_count: int = 0
    avg_forward_5d: Optional[float] = None
    avg_forward_20d: Optional[float] = None
    avg_forward_60d: Optional[float] = None
    doc_count: int = 0
    claim_count: int = 0
    price_coverage_pct: float = 0.0

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "action_count": self.action_count,
            "initiate_count": self.initiate_count,
            "exit_count": self.exit_count,
            "hold_count": self.hold_count,
            "avg_forward_5d_pct": round(self.avg_forward_5d, 2) if self.avg_forward_5d is not None else None,
            "avg_forward_20d_pct": round(self.avg_forward_20d, 2) if self.avg_forward_20d is not None else None,
            "avg_forward_60d_pct": round(self.avg_forward_60d, 2) if self.avg_forward_60d is not None else None,
            "doc_count": self.doc_count,
            "claim_count": self.claim_count,
            "price_coverage_pct": round(self.price_coverage_pct, 1),
        }


@dataclass
class CoverageDiagnostics:
    """Source coverage diagnostics for a usefulness run."""
    docs_by_ticker: dict[str, int] = field(default_factory=dict)
    docs_by_source_type: dict[str, int] = field(default_factory=dict)
    docs_by_month: dict[str, int] = field(default_factory=dict)
    claims_by_ticker: dict[str, int] = field(default_factory=dict)
    source_gaps: list[dict] = field(default_factory=list)
    extractor_mode: str = "stub_heuristic"
    benchmark_available: bool = False
    tickers_with_prices: int = 0
    tickers_without_prices: int = 0
    total_price_rows: int = 0

    def to_dict(self) -> dict:
        return {
            "docs_by_ticker": self.docs_by_ticker,
            "docs_by_source_type": self.docs_by_source_type,
            "docs_by_month": self.docs_by_month,
            "claims_by_ticker": self.claims_by_ticker,
            "source_gaps": self.source_gaps,
            "extractor_mode": self.extractor_mode,
            "benchmark_available": self.benchmark_available,
            "tickers_with_prices": self.tickers_with_prices,
            "tickers_without_prices": self.tickers_without_prices,
            "total_price_rows": self.total_price_rows,
        }


@dataclass
class FailureAnalysis:
    """Structured failure analysis from a usefulness run."""
    sparse_coverage_tickers: list[dict] = field(default_factory=list)
    negative_return_actions: list[dict] = field(default_factory=list)
    non_differentiating_buckets: list[dict] = field(default_factory=list)
    repeated_bad_recommendations: list[dict] = field(default_factory=list)
    low_evidence_periods: list[dict] = field(default_factory=list)
    degraded_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "sparse_coverage_tickers": self.sparse_coverage_tickers,
            "negative_return_actions": self.negative_return_actions,
            "non_differentiating_buckets": self.non_differentiating_buckets,
            "repeated_bad_recommendations": self.repeated_bad_recommendations,
            "low_evidence_periods": self.low_evidence_periods,
            "degraded_flags": self.degraded_flags,
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
    # New usefulness-run fields
    best_decisions: list[dict] = field(default_factory=list)
    worst_decisions: list[dict] = field(default_factory=list)
    per_name_summary: list[PerNameSummary] = field(default_factory=list)
    coverage_diagnostics: Optional[CoverageDiagnostics] = None
    failure_analysis: Optional[FailureAnalysis] = None
    exit_policy_label: str = "baseline"
    # Empirical diagnostics (populated for usefulness runs)
    deterioration_diagnostics: Optional[object] = None  # DeteriorationDiagnostics
    enhanced_failure_analysis: Optional[object] = None   # EnhancedFailureAnalysis

    def to_dict(self) -> dict:
        return {
            "config": self.config.to_dict(),
            "metrics": self.metrics.to_dict() if self.metrics else None,
            "diagnostics": self.diagnostics.to_dict() if self.diagnostics else None,
            "benchmark": self.benchmark.to_dict() if self.benchmark else None,
            "forward_return_summary": [s.to_dict() for s in self.forward_return_summary],
            "conviction_buckets": [b.to_dict() for b in self.conviction_buckets],
            "action_outcomes_count": len(self.action_outcomes),
            "best_decisions": self.best_decisions,
            "worst_decisions": self.worst_decisions,
            "per_name_summary": [p.to_dict() for p in self.per_name_summary],
            "coverage_diagnostics": self.coverage_diagnostics.to_dict() if self.coverage_diagnostics else None,
            "failure_analysis": self.failure_analysis.to_dict() if self.failure_analysis else None,
            "warnings": self.warnings,
        }


def run_historical_evaluation(
    session: Session,
    config: HistoricalEvalConfig,
    exit_policy: ExitPolicyConfig = BASELINE_POLICY,
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
    result.exit_policy_label = exit_policy.label()

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
            relaxed_gates=config.is_usefulness_run(),
            exit_policy=exit_policy,
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
                "thesis_conviction": round(decision.thesis_conviction, 1),
                "action_score": round(decision.action_score, 1),
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

    # 7. Best/worst decisions
    result.best_decisions = _compute_best_worst(result.action_outcomes, best=True)
    result.worst_decisions = _compute_best_worst(result.action_outcomes, best=False)

    # 8. Per-name summary
    result.per_name_summary = _compute_per_name_summary(
        result.action_outcomes, session, config,
    )

    # 9. Coverage diagnostics
    result.coverage_diagnostics = _compute_coverage_diagnostics(
        session, config,
    )

    # 10. Failure analysis
    result.failure_analysis = _compute_failure_analysis(
        result, config,
    )

    # 11. Empirical diagnostics (probation/exit)
    try:
        from empirical_diagnostics import (
            compute_deterioration_diagnostics,
            compute_enhanced_failure_analysis,
        )
        result.deterioration_diagnostics = compute_deterioration_diagnostics(
            result.action_outcomes,
        )
        result.enhanced_failure_analysis = compute_enhanced_failure_analysis(
            result.action_outcomes,
            result.deterioration_diagnostics,
            result.per_name_summary,
        )
    except Exception as e:
        result.warnings.append(f"Empirical diagnostics failed: {e}")

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
        thesis_conviction=decision.thesis_conviction,
        action_score=decision.action_score,
        conviction_bucket=config.conviction_bucket_for(decision.thesis_conviction),
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


def _compute_best_worst(
    outcomes: list[ActionOutcome],
    best: bool = True,
    n: int = 10,
) -> list[dict]:
    """Return top N best or worst decisions by 20D forward return."""
    scored = [
        o for o in outcomes
        if o.forward_20d is not None and o.action not in ("no_action", "hold")
    ]
    if not scored:
        # Fall back to 5D if 20D is sparse
        scored = [o for o in outcomes if o.forward_5d is not None and o.action not in ("no_action", "hold")]
        sort_key = lambda o: o.forward_5d if o.forward_5d is not None else 0.0
    else:
        sort_key = lambda o: o.forward_20d if o.forward_20d is not None else 0.0

    scored.sort(key=sort_key, reverse=best)
    top = scored[:n]

    return [
        {
            "review_date": o.review_date.isoformat(),
            "ticker": o.ticker,
            "action": o.action,
            "thesis_conviction": round(o.thesis_conviction, 1),
            "action_score": round(o.action_score, 1),
            "conviction_bucket": o.conviction_bucket,
            "price_at_decision": round(o.price_at_decision, 2) if o.price_at_decision else None,
            "forward_5d_pct": round(o.forward_5d, 2) if o.forward_5d is not None else None,
            "forward_20d_pct": round(o.forward_20d, 2) if o.forward_20d is not None else None,
            "forward_60d_pct": round(o.forward_60d, 2) if o.forward_60d is not None else None,
            "rationale": o.rationale[:200] if o.rationale else "",
        }
        for o in top
    ]


def _compute_per_name_summary(
    outcomes: list[ActionOutcome],
    session: Session,
    config: HistoricalEvalConfig,
) -> list[PerNameSummary]:
    """Compute per-ticker usefulness summary."""
    from sqlalchemy import func

    by_ticker: dict[str, list[ActionOutcome]] = defaultdict(list)
    for o in outcomes:
        by_ticker[o.ticker].append(o)

    tickers = config.effective_tickers()
    summaries = []

    for ticker in sorted(tickers):
        items = by_ticker.get(ticker, [])
        s = PerNameSummary(ticker=ticker, action_count=len(items))

        s.initiate_count = sum(1 for o in items if o.action == "initiate")
        s.exit_count = sum(1 for o in items if o.action == "exit")
        s.hold_count = sum(1 for o in items if o.action == "hold")

        fwd_5 = [o.forward_5d for o in items if o.forward_5d is not None]
        fwd_20 = [o.forward_20d for o in items if o.forward_20d is not None]
        fwd_60 = [o.forward_60d for o in items if o.forward_60d is not None]

        if fwd_5:
            s.avg_forward_5d = sum(fwd_5) / len(fwd_5)
        if fwd_20:
            s.avg_forward_20d = sum(fwd_20) / len(fwd_20)
        if fwd_60:
            s.avg_forward_60d = sum(fwd_60) / len(fwd_60)

        # Document and claim counts from DB
        try:
            from models import Document, Claim
            doc_count = session.query(func.count(Document.id)).filter(
                Document.primary_company_ticker == ticker
            ).scalar() or 0
            s.doc_count = doc_count

            claim_count = session.query(func.count(Claim.id)).join(
                Document, Claim.document_id == Document.id
            ).filter(
                Document.primary_company_ticker == ticker
            ).scalar() or 0
            s.claim_count = claim_count
        except Exception:
            pass

        # Price coverage
        try:
            total_days = (config.eval_end - config.eval_start).days
            if total_days > 0:
                price_count = session.query(func.count(Price.id)).filter(
                    Price.ticker == ticker,
                    Price.date >= config.eval_start,
                    Price.date <= config.eval_end,
                ).scalar() or 0
                trading_days = total_days * 5 / 7  # approximate
                s.price_coverage_pct = min(100.0, (price_count / max(1, trading_days)) * 100)
        except Exception:
            pass

        summaries.append(s)

    return summaries


def _compute_coverage_diagnostics(
    session: Session,
    config: HistoricalEvalConfig,
) -> CoverageDiagnostics:
    """Compute source coverage diagnostics."""
    from sqlalchemy import func
    from models import Document, Claim

    diag = CoverageDiagnostics()
    diag.extractor_mode = config.extractor_mode_label()

    tickers = config.effective_tickers()

    # Documents by ticker
    try:
        rows = session.query(
            Document.primary_company_ticker, func.count(Document.id)
        ).filter(
            Document.primary_company_ticker.in_(tickers)
        ).group_by(Document.primary_company_ticker).all()
        diag.docs_by_ticker = {r[0]: r[1] for r in rows}
    except Exception:
        pass

    # Documents by source type
    try:
        rows = session.query(
            Document.source_type, func.count(Document.id)
        ).group_by(Document.source_type).all()
        diag.docs_by_source_type = {str(r[0].value if hasattr(r[0], 'value') else r[0]): r[1] for r in rows}
    except Exception:
        pass

    # Documents by month
    try:
        all_docs = session.query(Document.published_at).filter(
            Document.primary_company_ticker.in_(tickers)
        ).all()
        by_month: dict[str, int] = defaultdict(int)
        for (pub_at,) in all_docs:
            if pub_at:
                key = pub_at.strftime("%Y-%m")
                by_month[key] += 1
        diag.docs_by_month = dict(sorted(by_month.items()))
    except Exception:
        pass

    # Claims by ticker
    try:
        rows = session.query(
            Document.primary_company_ticker, func.count(Claim.id)
        ).join(Document, Claim.document_id == Document.id).filter(
            Document.primary_company_ticker.in_(tickers)
        ).group_by(Document.primary_company_ticker).all()
        diag.claims_by_ticker = {r[0]: r[1] for r in rows}
    except Exception:
        pass

    # Source gaps: tickers with zero documents
    tickers_with_docs = set(diag.docs_by_ticker.keys())
    for t in tickers:
        if t not in tickers_with_docs:
            diag.source_gaps.append({
                "ticker": t,
                "issue": "no_documents",
                "detail": f"No documents found for {t} in evaluation window",
            })

    # Months with zero documents
    if diag.docs_by_month:
        start_month = config.backfill_start.strftime("%Y-%m")
        end_month = config.backfill_end.strftime("%Y-%m")
        current = config.backfill_start
        while current <= config.backfill_end:
            month_key = current.strftime("%Y-%m")
            if month_key not in diag.docs_by_month:
                diag.source_gaps.append({
                    "ticker": "ALL",
                    "issue": "empty_month",
                    "detail": f"No documents ingested in {month_key}",
                })
            current = (current.replace(day=1) + timedelta(days=32)).replace(day=1)

    # Price coverage
    try:
        price_rows = session.query(
            Price.ticker, func.count(Price.id)
        ).filter(Price.ticker.in_(tickers)).group_by(Price.ticker).all()
        tickers_with_p = {r[0] for r in price_rows}
        diag.tickers_with_prices = len(tickers_with_p)
        diag.tickers_without_prices = len(set(tickers) - tickers_with_p)
        diag.total_price_rows = sum(r[1] for r in price_rows)
    except Exception:
        pass

    # Benchmark availability
    try:
        bench_count = session.query(func.count(Price.id)).filter(
            Price.ticker == config.benchmark_ticker
        ).scalar() or 0
        diag.benchmark_available = bench_count > 0
    except Exception:
        pass

    return diag


def _compute_failure_analysis(
    result: HistoricalEvalResult,
    config: HistoricalEvalConfig,
) -> FailureAnalysis:
    """Compute structured failure analysis from evaluation results."""
    fa = FailureAnalysis()

    # 1. Degraded flags
    if not config.use_llm:
        fa.degraded_flags.append(
            "Stub extraction: claims are heuristic, not LLM-generated"
        )
    if not config.backfill_sec_filings:
        fa.degraded_flags.append("SEC filings disabled")
    if not config.backfill_news_rss:
        fa.degraded_flags.append("News RSS disabled")
    if not config.backfill_pr_rss:
        fa.degraded_flags.append("PR RSS disabled")

    # 2. Sparse coverage tickers
    for pns in result.per_name_summary:
        issues = []
        if pns.doc_count == 0:
            issues.append("no documents")
        elif pns.doc_count < 3:
            issues.append(f"only {pns.doc_count} documents")
        if pns.claim_count == 0:
            issues.append("no claims extracted")
        if pns.price_coverage_pct < 50:
            issues.append(f"price coverage {pns.price_coverage_pct:.0f}%")
        if issues:
            fa.sparse_coverage_tickers.append({
                "ticker": pns.ticker,
                "issues": issues,
                "doc_count": pns.doc_count,
                "claim_count": pns.claim_count,
                "price_coverage_pct": round(pns.price_coverage_pct, 1),
            })

    # 3. Negative return actions
    for frs in result.forward_return_summary:
        neg = {}
        if frs.avg_20d is not None and frs.avg_20d < 0 and frs.count >= 2:
            neg = {
                "action": frs.action,
                "count": frs.count,
                "avg_20d_pct": round(frs.avg_20d, 2),
                "concern": f"{frs.action} actions have negative avg 20D return ({frs.avg_20d:+.2f}%)",
            }
        elif frs.avg_5d is not None and frs.avg_5d < 0 and frs.count >= 2:
            neg = {
                "action": frs.action,
                "count": frs.count,
                "avg_5d_pct": round(frs.avg_5d, 2),
                "concern": f"{frs.action} actions have negative avg 5D return ({frs.avg_5d:+.2f}%)",
            }
        if neg:
            fa.negative_return_actions.append(neg)

    # 4. Non-differentiating conviction buckets
    bucket_returns = {}
    for cb in result.conviction_buckets:
        if cb.avg_forward_20d is not None and cb.action_count >= 2:
            bucket_returns[cb.bucket] = cb.avg_forward_20d

    if len(bucket_returns) >= 2:
        vals = list(bucket_returns.values())
        spread = max(vals) - min(vals)
        if spread < 1.0:  # less than 1% spread
            fa.non_differentiating_buckets.append({
                "buckets": bucket_returns,
                "spread_pct": round(spread, 2),
                "concern": "Conviction buckets do not meaningfully differentiate outcomes",
            })

    # 5. Repeated bad recommendations
    by_ticker_neg: dict[str, int] = defaultdict(int)
    for o in result.action_outcomes:
        if o.forward_20d is not None and o.forward_20d < -5.0 and o.action in ("initiate", "add"):
            by_ticker_neg[o.ticker] += 1
    for ticker, count in by_ticker_neg.items():
        if count >= 2:
            fa.repeated_bad_recommendations.append({
                "ticker": ticker,
                "bad_initiate_add_count": count,
                "concern": f"{ticker} had {count} initiate/add actions followed by >5% loss at 20D",
            })

    # 6. Low evidence periods
    if result.coverage_diagnostics and result.coverage_diagnostics.docs_by_month:
        for month, count in result.coverage_diagnostics.docs_by_month.items():
            if count < 3:
                fa.low_evidence_periods.append({
                    "period": month,
                    "doc_count": count,
                    "concern": f"Only {count} document(s) in {month}",
                })

    return fa


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
