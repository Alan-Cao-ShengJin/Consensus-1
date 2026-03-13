"""Evaluation report generator: structured output from evaluation runs.

Produces JSON and markdown reports suitable for operator review,
downstream console consumption, or archival.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from eval_config import EvalConfig
from eval_harness import (
    BenchmarkComparison,
    EvalRunResult,
    MemoryComparisonResult,
    RecommendationDiagnostics,
)
from replay_metrics import ReplayMetrics

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# JSON report
# ---------------------------------------------------------------------------

def generate_json_report(
    eval_result: EvalRunResult,
    memory_comparison: Optional[MemoryComparisonResult] = None,
    output_dir: str = "eval_reports",
) -> str:
    """Generate a structured JSON evaluation report.

    Returns the output file path.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    report = _build_report_dict(eval_result, memory_comparison)

    filename = f"eval_{eval_result.config.run_id}_{eval_result.config.start_date}_{eval_result.config.end_date}.json"
    filepath = os.path.join(output_dir, filename)

    with open(filepath, "w") as f:
        json.dump(report, f, indent=2, default=str)

    logger.info("JSON report written to %s", filepath)
    return filepath


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------

def generate_markdown_report(
    eval_result: EvalRunResult,
    memory_comparison: Optional[MemoryComparisonResult] = None,
    output_dir: str = "eval_reports",
) -> str:
    """Generate a human-readable markdown evaluation report.

    Returns the output file path.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    lines = _build_markdown_lines(eval_result, memory_comparison)

    filename = f"eval_{eval_result.config.run_id}_{eval_result.config.start_date}_{eval_result.config.end_date}.md"
    filepath = os.path.join(output_dir, filename)

    with open(filepath, "w") as f:
        f.write("\n".join(lines))

    logger.info("Markdown report written to %s", filepath)
    return filepath


# ---------------------------------------------------------------------------
# Report building
# ---------------------------------------------------------------------------

def _build_report_dict(
    eval_result: EvalRunResult,
    memory_comparison: Optional[MemoryComparisonResult] = None,
) -> dict:
    """Build the structured report dictionary."""
    config = eval_result.config
    metrics = eval_result.metrics
    diag = eval_result.diagnostics
    bench = eval_result.benchmark

    report = {
        "report_version": "1.0",
        "generated_at": datetime.utcnow().isoformat(),
        "run_metadata": {
            "run_id": config.run_id,
            "run_label": config.run_label,
            "start_date": config.start_date.isoformat(),
            "end_date": config.end_date.isoformat(),
            "cadence_days": config.cadence_days,
            "initial_cash": config.initial_cash,
            "strict_replay": config.strict_replay,
            "memory_enabled": config.memory_enabled,
            "contradiction_metadata_enabled": config.contradiction_metadata_enabled,
            "evidence_downweighting_enabled": config.evidence_downweighting_enabled,
            "seed": config.seed,
        },
        "replay_purity": {
            "purity_level": metrics.purity_level,
            "strict_replay": metrics.strict_replay,
            "impure_candidates": metrics.impure_candidate_fallbacks,
            "impure_valuations": metrics.impure_valuation_fallbacks,
            "impure_checkpoints": metrics.impure_checkpoint_fallbacks,
            "skipped_impure": metrics.skipped_impure_total,
        },
        "decision_summary": {
            "total_reviews": metrics.total_review_dates,
            "total_recommendations": metrics.total_recommendations,
            "action_counts": diag.action_counts,
            "action_pcts": {k: round(v, 1) for k, v in diag.action_pcts.items()},
            "recommendation_changes": diag.recommendation_changes,
            "recommendation_change_rate": round(diag.recommendation_change_rate, 3),
        },
        "recommendation_quality": {
            "attribution": {
                "valuation_driven": diag.valuation_driven_count,
                "evidence_driven": diag.evidence_driven_count,
                "checkpoint_driven": diag.checkpoint_driven_count,
                "deterioration_driven": diag.deterioration_driven_count,
            },
            "short_hold_exits": diag.short_hold_exits,
            "avg_initiation_conviction": (
                round(metrics.avg_initiation_conviction, 1)
                if metrics.avg_initiation_conviction is not None else None
            ),
            "probation_to_exit": metrics.probation_to_exit_count,
        },
        "candidate_summary": {
            "total_candidate_rankings": len(diag.candidate_rankings),
            "actions_by_ticker": diag.actions_by_ticker,
        },
        "portfolio_summary": {
            "total_return_pct": round(metrics.total_return_pct, 2),
            "annualized_return_pct": (
                round(metrics.annualized_return_pct, 2)
                if metrics.annualized_return_pct is not None else None
            ),
            "max_drawdown_pct": round(metrics.max_drawdown_pct, 2),
            "total_turnover_pct": round(metrics.total_turnover_pct, 2),
            "avg_cash_pct": round(metrics.avg_cash_pct, 1),
            "trades_applied": metrics.total_trades_applied,
            "trades_skipped": metrics.total_trades_skipped,
        },
        "benchmark_comparison": bench.to_dict() if bench else None,
        "key_metrics": _compute_key_metrics(metrics, diag, bench),
        "warnings": _collect_warnings(eval_result),
    }

    if memory_comparison is not None:
        report["memory_comparison"] = memory_comparison.to_dict()

    return report


def _compute_key_metrics(
    metrics: ReplayMetrics,
    diag: RecommendationDiagnostics,
    bench: Optional[BenchmarkComparison],
) -> dict:
    """Extract the most important metrics for quick review."""
    key = {
        "total_return_pct": round(metrics.total_return_pct, 2),
        "max_drawdown_pct": round(metrics.max_drawdown_pct, 2),
        "total_actions": sum(diag.action_counts.values()),
        "recommendation_change_rate": round(diag.recommendation_change_rate, 3),
        "purity_level": metrics.purity_level,
    }
    if bench and bench.excess_return_pct is not None:
        key["excess_return_vs_benchmark_pct"] = round(bench.excess_return_pct, 2)
    if bench and bench.vs_equal_weight_pct is not None:
        key["excess_return_vs_equal_weight_pct"] = round(bench.vs_equal_weight_pct, 2)
    return key


def _collect_warnings(eval_result: EvalRunResult) -> list[str]:
    """Collect warnings and degraded conditions."""
    warnings = []
    m = eval_result.metrics

    if m.purity_level == "degraded":
        warnings.append("Replay purity is degraded — some inputs used fallback values")
    if m.missing_price_events > 0:
        warnings.append(f"Missing price data for {m.missing_price_events} ticker-date combinations")
    if m.total_trades_skipped > 0:
        warnings.append(f"{m.total_trades_skipped} trades skipped (no execution price)")
    if m.total_review_dates == 0:
        warnings.append("No review dates processed — check date range and data availability")
    if eval_result.diagnostics.short_hold_exits > 0:
        warnings.append(
            f"{eval_result.diagnostics.short_hold_exits} positions exited within 30 days of initiation"
        )
    bench = eval_result.benchmark
    if bench and not bench.benchmark_data_available:
        warnings.append(f"Benchmark data ({bench.benchmark_ticker}) not available for comparison")
    if bench and bench.equal_weight_tickers_with_data == 0 and bench.equal_weight_tickers_count > 0:
        warnings.append("Equal-weight baseline: no price data available for any candidate ticker")

    return warnings


# ---------------------------------------------------------------------------
# Markdown formatting
# ---------------------------------------------------------------------------

def _build_markdown_lines(
    eval_result: EvalRunResult,
    memory_comparison: Optional[MemoryComparisonResult] = None,
) -> list[str]:
    """Build markdown report lines."""
    config = eval_result.config
    m = eval_result.metrics
    d = eval_result.diagnostics
    bench = eval_result.benchmark
    lines = []

    lines.append(f"# Evaluation Report: {config.run_id}")
    lines.append(f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("")

    # Run metadata
    lines.append("## Run Metadata")
    lines.append(f"- **Date range**: {config.start_date} to {config.end_date}")
    lines.append(f"- **Cadence**: {config.cadence_days} days")
    lines.append(f"- **Initial cash**: ${config.initial_cash:,.0f}")
    lines.append(f"- **Strict replay**: {config.strict_replay}")
    lines.append(f"- **Memory enabled**: {config.memory_enabled}")
    lines.append(f"- **Purity level**: {m.purity_level}")
    lines.append("")

    # Key metrics
    lines.append("## Key Metrics")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Total return | {m.total_return_pct:+.2f}% |")
    if m.annualized_return_pct is not None:
        lines.append(f"| Annualized return | {m.annualized_return_pct:+.2f}% |")
    lines.append(f"| Max drawdown | {m.max_drawdown_pct:.2f}% |")
    lines.append(f"| Total actions | {sum(d.action_counts.values())} |")
    lines.append(f"| Rec. change rate | {d.recommendation_change_rate:.3f} per review |")
    if bench and bench.excess_return_pct is not None:
        lines.append(f"| Excess vs {bench.benchmark_ticker} | {bench.excess_return_pct:+.2f}% |")
    if bench and bench.vs_equal_weight_pct is not None:
        lines.append(f"| Excess vs equal-weight | {bench.vs_equal_weight_pct:+.2f}% |")
    lines.append("")

    # Decision summary
    lines.append("## Decision Summary")
    lines.append(f"- Reviews: {m.total_review_dates}")
    lines.append(f"- Recommendations: {m.total_recommendations}")
    lines.append(f"- Recommendation changes: {d.recommendation_changes}")
    lines.append("")
    if d.action_counts:
        lines.append("### Action Mix")
        lines.append("| Action | Count | % |")
        lines.append("|--------|-------|---|")
        for action, count in sorted(d.action_counts.items(), key=lambda x: -x[1]):
            pct = d.action_pcts.get(action, 0)
            lines.append(f"| {action} | {count} | {pct:.1f}% |")
        lines.append("")

    # Attribution
    lines.append("### Decision Attribution")
    lines.append(f"- Valuation-driven: {d.valuation_driven_count}")
    lines.append(f"- Evidence-driven: {d.evidence_driven_count}")
    lines.append(f"- Checkpoint-driven: {d.checkpoint_driven_count}")
    lines.append(f"- Deterioration-driven: {d.deterioration_driven_count}")
    lines.append("")

    # Portfolio summary
    lines.append("## Portfolio Summary")
    lines.append(f"- Total turnover: {m.total_turnover_pct:.1f}%")
    lines.append(f"- Avg cash exposure: {m.avg_cash_pct:.1f}%")
    lines.append(f"- Trades applied: {m.total_trades_applied}")
    lines.append(f"- Trades skipped: {m.total_trades_skipped}")
    if m.avg_initiation_conviction is not None:
        lines.append(f"- Avg initiation conviction: {m.avg_initiation_conviction:.0f}")
    lines.append(f"- Short-hold exits (<30d): {d.short_hold_exits}")
    lines.append("")

    # Benchmark
    if bench:
        lines.append("## Benchmark Comparison")
        lines.append(f"| Benchmark | Return | Data Available |")
        lines.append(f"|-----------|--------|----------------|")
        lines.append(
            f"| Portfolio | {bench.portfolio_return_pct:+.2f}% | Yes |"
        )
        bench_str = f"{bench.benchmark_return_pct:+.2f}%" if bench.benchmark_return_pct is not None else "N/A"
        lines.append(f"| {bench.benchmark_ticker} | {bench_str} | {bench.benchmark_data_available} |")
        ew_str = f"{bench.equal_weight_return_pct:+.2f}%" if bench.equal_weight_return_pct is not None else "N/A"
        lines.append(
            f"| Equal-weight ({bench.equal_weight_tickers_with_data}/{bench.equal_weight_tickers_count} tickers) "
            f"| {ew_str} | {bench.equal_weight_tickers_with_data > 0} |"
        )
        lines.append("")

    # Memory comparison
    if memory_comparison:
        lines.append("## Memory Comparison (ON vs OFF)")
        mc = memory_comparison
        lines.append("| Metric | Memory ON | Memory OFF | Delta |")
        lines.append("|--------|-----------|------------|-------|")
        on = mc.memory_on_metrics
        off = mc.memory_off_metrics
        for key in ["total_return_pct", "state_changes", "state_flips",
                     "recommendation_changes", "total_actions"]:
            v_on = on.get(key, 0)
            v_off = off.get(key, 0)
            delta = v_on - v_off if isinstance(v_on, (int, float)) else "—"
            fmt = f"{v_on:.2f}" if isinstance(v_on, float) else str(v_on)
            fmt_off = f"{v_off:.2f}" if isinstance(v_off, float) else str(v_off)
            delta_str = f"{delta:+.2f}" if isinstance(delta, float) else f"{delta:+d}" if isinstance(delta, int) else delta
            lines.append(f"| {key} | {fmt} | {fmt_off} | {delta_str} |")
        lines.append(f"| score_volatility | {mc.score_volatility_on:.4f} | {mc.score_volatility_off:.4f} | {mc.score_volatility_on - mc.score_volatility_off:+.4f} |")
        lines.append("")

    # Warnings
    warnings = _collect_warnings(eval_result)
    if warnings:
        lines.append("## Warnings")
        for w in warnings:
            lines.append(f"- {w}")
        lines.append("")

    # Limitations
    lines.append("## Limitations")
    lines.append("- Returns are not statistically significant over short replay windows")
    lines.append("- Stub LLM mode: thesis updates use deterministic stub, not real LLM")
    lines.append("- No sector-level attribution (sector data not in schema)")
    lines.append("- Equal-weight baseline assumes no transaction costs")
    lines.append("")

    return lines
