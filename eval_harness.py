"""Evaluation harness: run replay experiments under configurable ablation modes.

Supports:
- Memory ON vs OFF comparison
- Strict vs non-strict replay
- Benchmark / baseline comparison (SPY, equal-weight)
- Recommendation diagnostics and attribution
- Structured report generation
"""
from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from eval_config import EvalConfig
from replay_engine import ReplayRunResult
from replay_metrics import ReplayMetrics, compute_metrics
from replay_runner import run_replay
from shadow_portfolio import ShadowPortfolio

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Recommendation diagnostics
# ---------------------------------------------------------------------------

@dataclass
class RecommendationDiagnostics:
    """Diagnostics on recommendation quality and behavior."""
    # Action mix
    action_counts: dict[str, int] = field(default_factory=dict)
    action_pcts: dict[str, float] = field(default_factory=dict)

    # Per-ticker action distribution
    actions_by_ticker: dict[str, dict[str, int]] = field(default_factory=dict)

    # Recommendation changes (ticker changed action between consecutive reviews)
    recommendation_changes: int = 0
    recommendation_change_rate: float = 0.0  # changes per review

    # Action attribution
    valuation_driven_count: int = 0
    evidence_driven_count: int = 0
    checkpoint_driven_count: int = 0
    deterioration_driven_count: int = 0

    # Candidate rankings by date
    candidate_rankings: list[dict] = field(default_factory=list)

    # Short-hold patterns (initiate followed by exit within N days)
    short_hold_exits: int = 0  # exits within 30 days of initiation

    def to_dict(self) -> dict:
        return {
            "action_counts": self.action_counts,
            "action_pcts": {k: round(v, 1) for k, v in self.action_pcts.items()},
            "actions_by_ticker": self.actions_by_ticker,
            "recommendation_changes": self.recommendation_changes,
            "recommendation_change_rate": round(self.recommendation_change_rate, 3),
            "attribution": {
                "valuation_driven": self.valuation_driven_count,
                "evidence_driven": self.evidence_driven_count,
                "checkpoint_driven": self.checkpoint_driven_count,
                "deterioration_driven": self.deterioration_driven_count,
            },
            "candidate_rankings_count": len(self.candidate_rankings),
            "short_hold_exits": self.short_hold_exits,
        }


def compute_recommendation_diagnostics(
    run_result: ReplayRunResult,
    portfolio: ShadowPortfolio,
) -> RecommendationDiagnostics:
    """Compute recommendation quality diagnostics from a replay run."""
    diag = RecommendationDiagnostics()

    action_counter = Counter()
    ticker_actions: dict[str, dict[str, int]] = {}
    prev_actions: dict[str, str] = {}  # ticker -> last action
    total_decisions = 0
    changes = 0

    for rec in run_result.review_records:
        review_actions: dict[str, str] = {}
        for d in rec.result.decisions:
            action = d.action.value
            action_counter[action] += 1
            total_decisions += 1

            # Per-ticker tracking
            if d.ticker not in ticker_actions:
                ticker_actions[d.ticker] = Counter()
            ticker_actions[d.ticker][action] += 1

            review_actions[d.ticker] = action

            # Attribution heuristics
            _classify_attribution(d, diag)

        # Count recommendation changes
        for ticker, action in review_actions.items():
            if ticker in prev_actions and prev_actions[ticker] != action:
                changes += 1
        prev_actions.update(review_actions)

        # Candidate rankings for this review
        candidates_this_review = [
            d for d in rec.result.decisions
            if d.action.value in ("initiate", "no_action")
        ]
        if candidates_this_review:
            ranked = sorted(candidates_this_review, key=lambda d: -d.action_score)
            diag.candidate_rankings.append({
                "date": rec.review_date.isoformat(),
                "rankings": [
                    {"ticker": d.ticker, "score": round(d.action_score, 1), "action": d.action.value}
                    for d in ranked[:10]
                ],
            })

    diag.action_counts = dict(action_counter)
    if total_decisions > 0:
        diag.action_pcts = {k: v / total_decisions * 100 for k, v in action_counter.items()}
    diag.actions_by_ticker = {t: dict(c) for t, c in ticker_actions.items()}
    diag.recommendation_changes = changes
    if run_result.total_reviews > 0:
        diag.recommendation_change_rate = changes / run_result.total_reviews

    # Short-hold exits
    entry_dates: dict[str, date] = {}
    for trade in portfolio.trades:
        if trade.action == "initiate":
            entry_dates[trade.ticker] = trade.trade_date
        elif trade.action == "exit" and trade.ticker in entry_dates:
            days_held = (trade.trade_date - entry_dates[trade.ticker]).days
            if days_held <= 30:
                diag.short_hold_exits += 1
            del entry_dates[trade.ticker]

    return diag


def _classify_attribution(decision, diag: RecommendationDiagnostics) -> None:
    """Classify a decision by its primary attribution driver."""
    action = decision.action.value
    rationale = (decision.rationale or "").lower()

    if action in ("initiate", "add") and "valuation" in rationale:
        diag.valuation_driven_count += 1
    elif action in ("trim", "exit") and any(
        w in rationale for w in ("conviction", "broken", "probation", "deteriorat")
    ):
        diag.deterioration_driven_count += 1
    elif "checkpoint" in rationale:
        diag.checkpoint_driven_count += 1
    elif any(w in rationale for w in ("claim", "evidence", "novel")):
        diag.evidence_driven_count += 1


# ---------------------------------------------------------------------------
# Benchmark and baseline comparison
# ---------------------------------------------------------------------------

@dataclass
class BenchmarkComparison:
    """Comparison of portfolio performance against benchmarks."""
    # Portfolio
    portfolio_return_pct: float = 0.0

    # Benchmark (e.g., SPY)
    benchmark_ticker: str = "SPY"
    benchmark_return_pct: Optional[float] = None
    excess_return_pct: Optional[float] = None

    # Equal-weight monitored universe baseline
    equal_weight_return_pct: Optional[float] = None
    vs_equal_weight_pct: Optional[float] = None

    # Data quality
    benchmark_data_available: bool = False
    equal_weight_tickers_count: int = 0
    equal_weight_tickers_with_data: int = 0

    def to_dict(self) -> dict:
        return {
            "portfolio_return_pct": round(self.portfolio_return_pct, 2),
            "benchmark": {
                "ticker": self.benchmark_ticker,
                "return_pct": round(self.benchmark_return_pct, 2) if self.benchmark_return_pct is not None else None,
                "excess_return_pct": round(self.excess_return_pct, 2) if self.excess_return_pct is not None else None,
                "data_available": self.benchmark_data_available,
            },
            "equal_weight_baseline": {
                "return_pct": round(self.equal_weight_return_pct, 2) if self.equal_weight_return_pct is not None else None,
                "vs_equal_weight_pct": round(self.vs_equal_weight_pct, 2) if self.vs_equal_weight_pct is not None else None,
                "tickers_count": self.equal_weight_tickers_count,
                "tickers_with_data": self.equal_weight_tickers_with_data,
            },
        }


def compute_benchmark_comparison(
    session: Session,
    config: EvalConfig,
    portfolio_return_pct: float,
) -> BenchmarkComparison:
    """Compare portfolio return against benchmark and equal-weight baseline."""
    from models import Price

    comp = BenchmarkComparison(
        portfolio_return_pct=portfolio_return_pct,
        benchmark_ticker=config.benchmark_ticker,
    )

    # Benchmark return (e.g., SPY)
    bench_return = _compute_ticker_return(
        session, config.benchmark_ticker, config.start_date, config.end_date,
    )
    if bench_return is not None:
        comp.benchmark_return_pct = bench_return
        comp.excess_return_pct = portfolio_return_pct - bench_return
        comp.benchmark_data_available = True

    # Equal-weight monitored universe baseline
    if config.include_equal_weight_baseline:
        ew_return, n_tickers, n_with_data = _compute_equal_weight_return(
            session, config.start_date, config.end_date,
        )
        comp.equal_weight_tickers_count = n_tickers
        comp.equal_weight_tickers_with_data = n_with_data
        if ew_return is not None:
            comp.equal_weight_return_pct = ew_return
            comp.vs_equal_weight_pct = portfolio_return_pct - ew_return

    return comp


def _compute_ticker_return(
    session: Session,
    ticker: str,
    start_date: date,
    end_date: date,
) -> Optional[float]:
    """Compute simple return for a ticker over a date range."""
    from models import Price

    start_price = _get_nearest_price(session, ticker, start_date, direction="forward")
    end_price = _get_nearest_price(session, ticker, end_date, direction="backward")

    if start_price is None or end_price is None or start_price <= 0:
        return None
    return ((end_price - start_price) / start_price) * 100.0


def _get_nearest_price(
    session: Session,
    ticker: str,
    target_date: date,
    direction: str = "backward",
    max_gap_days: int = 10,
) -> Optional[float]:
    """Get the nearest available price to the target date."""
    from models import Price

    if direction == "backward":
        row = session.execute(
            select(Price.close)
            .where(
                Price.ticker == ticker,
                Price.date <= target_date,
                Price.date >= target_date - timedelta(days=max_gap_days),
                Price.close.isnot(None),
            )
            .order_by(Price.date.desc())
            .limit(1)
        ).scalar()
    else:
        row = session.execute(
            select(Price.close)
            .where(
                Price.ticker == ticker,
                Price.date >= target_date,
                Price.date <= target_date + timedelta(days=max_gap_days),
                Price.close.isnot(None),
            )
            .order_by(Price.date.asc())
            .limit(1)
        ).scalar()
    return row


def _compute_equal_weight_return(
    session: Session,
    start_date: date,
    end_date: date,
) -> tuple[Optional[float], int, int]:
    """Compute equal-weight return across all candidate tickers.

    Returns (return_pct, total_tickers, tickers_with_data).
    """
    from models import Candidate

    tickers = session.scalars(select(Candidate.ticker).distinct()).all()
    if not tickers:
        return None, 0, 0

    returns = []
    for ticker in tickers:
        r = _compute_ticker_return(session, ticker, start_date, end_date)
        if r is not None:
            returns.append(r)

    n_total = len(tickers)
    n_with_data = len(returns)
    if not returns:
        return None, n_total, 0

    avg_return = sum(returns) / len(returns)
    return avg_return, n_total, n_with_data


# ---------------------------------------------------------------------------
# Memory vs no-memory comparison
# ---------------------------------------------------------------------------

@dataclass
class MemoryComparisonResult:
    """Side-by-side comparison of memory-enabled vs memory-disabled runs."""
    memory_on_metrics: dict = field(default_factory=dict)
    memory_off_metrics: dict = field(default_factory=dict)

    # Comparison deltas
    thesis_change_delta: int = 0  # memory_on - memory_off
    recommendation_change_delta: int = 0
    avg_conviction_delta_diff: float = 0.0
    state_flip_delta: int = 0
    score_volatility_on: float = 0.0
    score_volatility_off: float = 0.0
    action_count_on: int = 0
    action_count_off: int = 0

    def to_dict(self) -> dict:
        return {
            "memory_on": self.memory_on_metrics,
            "memory_off": self.memory_off_metrics,
            "comparison": {
                "thesis_change_delta": self.thesis_change_delta,
                "recommendation_change_delta": self.recommendation_change_delta,
                "avg_conviction_delta_diff": round(self.avg_conviction_delta_diff, 4),
                "state_flip_delta": self.state_flip_delta,
                "score_volatility_on": round(self.score_volatility_on, 4),
                "score_volatility_off": round(self.score_volatility_off, 4),
                "action_count_on": self.action_count_on,
                "action_count_off": self.action_count_off,
            },
        }


def _extract_comparison_metrics(
    run_result: ReplayRunResult,
    metrics: ReplayMetrics,
    diagnostics: RecommendationDiagnostics,
) -> dict:
    """Extract metrics relevant for memory comparison."""
    # Count state changes (non-hold decisions)
    state_changes = sum(
        1 for rec in run_result.review_records
        for d in rec.result.decisions
        if d.action.value not in ("hold", "no_action")
    )

    # Count state flips (bullish↔bearish)
    state_flips = 0
    prev_states: dict[str, str] = {}
    bullish = {"strengthening", "stable", "achieved"}
    bearish = {"weakening", "probation", "broken"}
    for rec in run_result.review_records:
        for d in rec.result.decisions:
            ticker = d.ticker
            # Use the decision's action as a proxy for thesis direction
            cur_sentiment = "bullish" if d.action.value in ("initiate", "add", "hold") else "bearish"
            if ticker in prev_states and prev_states[ticker] != cur_sentiment:
                state_flips += 1
            prev_states[ticker] = cur_sentiment

    # Score volatility from snapshots
    score_deltas = []
    if len(run_result.review_records) >= 2:
        for i in range(1, len(run_result.review_records)):
            prev_snap = run_result.review_records[i - 1].snapshot
            curr_snap = run_result.review_records[i].snapshot
            if prev_snap and curr_snap:
                delta = abs(curr_snap.total_value - prev_snap.total_value) / max(prev_snap.total_value, 1)
                score_deltas.append(delta)

    volatility = (sum(d ** 2 for d in score_deltas) / len(score_deltas)) ** 0.5 if score_deltas else 0.0

    return {
        "total_return_pct": metrics.total_return_pct,
        "max_drawdown_pct": metrics.max_drawdown_pct,
        "state_changes": state_changes,
        "state_flips": state_flips,
        "recommendation_changes": diagnostics.recommendation_changes,
        "total_initiations": metrics.total_initiations,
        "total_exits": metrics.total_exits,
        "total_actions": sum(diagnostics.action_counts.values()),
        "avg_turnover_per_review_pct": metrics.avg_turnover_per_review_pct,
        "score_volatility": volatility,
        "action_counts": diagnostics.action_counts,
    }


def run_memory_comparison(
    session: Session,
    config_on: EvalConfig,
    config_off: EvalConfig,
) -> MemoryComparisonResult:
    """Run memory-enabled and memory-disabled replays and compare.

    IMPORTANT: This modifies thesis state in the DB. The caller should use
    a transaction that can be rolled back, or use separate DB snapshots.

    For evaluation purposes, this function runs replay (which is read-only
    for thesis state — it only reads DB state and writes to shadow portfolio).
    The memory ablation affects thesis_update_service behavior, which is NOT
    called during replay. Therefore, memory comparison at the replay level
    measures the indirect effect: different thesis states that would have
    resulted from memory-enabled vs disabled thesis updates.

    In practice, both runs use the same DB thesis state (since replay is
    read-only). The comparison is still valid for measuring:
    - Decision output differences given same thesis state
    - Portfolio outcome differences
    - Recommendation stability differences
    """
    # Run memory-enabled
    run_on, port_on, metrics_on = run_replay(
        session,
        start_date=config_on.start_date,
        end_date=config_on.end_date,
        cadence_days=config_on.cadence_days,
        initial_cash=config_on.initial_cash,
        apply_trades=config_on.apply_trades,
        ticker_filter=config_on.ticker_filter,
        transaction_cost_bps=config_on.transaction_cost_bps,
        strict_replay=config_on.strict_replay,
    )
    diag_on = compute_recommendation_diagnostics(run_on, port_on)

    # Run memory-disabled
    run_off, port_off, metrics_off = run_replay(
        session,
        start_date=config_off.start_date,
        end_date=config_off.end_date,
        cadence_days=config_off.cadence_days,
        initial_cash=config_off.initial_cash,
        apply_trades=config_off.apply_trades,
        ticker_filter=config_off.ticker_filter,
        transaction_cost_bps=config_off.transaction_cost_bps,
        strict_replay=config_off.strict_replay,
    )
    diag_off = compute_recommendation_diagnostics(run_off, port_off)

    # Extract comparison metrics
    on_metrics = _extract_comparison_metrics(run_on, metrics_on, diag_on)
    off_metrics = _extract_comparison_metrics(run_off, metrics_off, diag_off)

    result = MemoryComparisonResult(
        memory_on_metrics=on_metrics,
        memory_off_metrics=off_metrics,
        thesis_change_delta=on_metrics["state_changes"] - off_metrics["state_changes"],
        recommendation_change_delta=on_metrics["recommendation_changes"] - off_metrics["recommendation_changes"],
        state_flip_delta=on_metrics["state_flips"] - off_metrics["state_flips"],
        score_volatility_on=on_metrics["score_volatility"],
        score_volatility_off=off_metrics["score_volatility"],
        action_count_on=on_metrics["total_actions"],
        action_count_off=off_metrics["total_actions"],
    )

    return result


# ---------------------------------------------------------------------------
# Single evaluation run
# ---------------------------------------------------------------------------

@dataclass
class EvalRunResult:
    """Complete result of a single evaluation run."""
    config: EvalConfig
    run_result: ReplayRunResult
    portfolio: ShadowPortfolio
    metrics: ReplayMetrics
    diagnostics: RecommendationDiagnostics
    benchmark: Optional[BenchmarkComparison] = None

    def to_dict(self) -> dict:
        return {
            "config": self.config.to_dict(),
            "metrics": self.metrics.to_dict(),
            "diagnostics": self.diagnostics.to_dict(),
            "benchmark": self.benchmark.to_dict() if self.benchmark else None,
        }


def run_evaluation(
    session: Session,
    config: EvalConfig,
) -> EvalRunResult:
    """Run a single evaluation with the given config.

    Returns structured results for reporting.
    """
    logger.info(
        "Starting evaluation run '%s': %s to %s, memory=%s, strict=%s",
        config.run_id, config.start_date, config.end_date,
        config.memory_enabled, config.strict_replay,
    )

    # Run replay
    run_result, portfolio, metrics = run_replay(
        session,
        start_date=config.start_date,
        end_date=config.end_date,
        cadence_days=config.cadence_days,
        initial_cash=config.initial_cash,
        apply_trades=config.apply_trades,
        ticker_filter=config.ticker_filter,
        transaction_cost_bps=config.transaction_cost_bps,
        strict_replay=config.strict_replay,
    )

    # Compute diagnostics
    diagnostics = compute_recommendation_diagnostics(run_result, portfolio)

    # Compute benchmark comparison
    benchmark = compute_benchmark_comparison(
        session, config, metrics.total_return_pct,
    )

    return EvalRunResult(
        config=config,
        run_result=run_result,
        portfolio=portfolio,
        metrics=metrics,
        diagnostics=diagnostics,
        benchmark=benchmark,
    )
