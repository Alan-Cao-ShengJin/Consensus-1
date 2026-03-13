"""Historical proof-pack report generation.

Produces a structured artifact pack from a historical evaluation run:
- manifest.json: Run manifest with metadata and degraded flags
- summary.json: Machine-readable full report
- report.md: Human-readable markdown report
- decisions.csv: Per-review-date decisions
- action_outcomes.csv: Per-action forward returns
- best_decisions.csv: Top N decisions by forward return
- worst_decisions.csv: Bottom N decisions by forward return
- per_name_summary.csv: Per-ticker usefulness summary
- coverage_diagnostics.csv: Source coverage by ticker
- coverage_by_month.csv: Source coverage by month
- benchmark.csv: Benchmark comparison
- conviction_buckets.csv: Conviction bucket summary
- memory_comparison.csv: Memory ON vs OFF (if ablation run)
"""
from __future__ import annotations

import csv
import hashlib
import json
import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from historical_eval_config import HistoricalEvalConfig
from historical_evaluation import (
    HistoricalEvalResult,
    HistoricalMemoryComparisonResult,
)
from historical_regeneration import RegenerationResult

logger = logging.getLogger(__name__)


def generate_proof_pack(
    config: HistoricalEvalConfig,
    regen_result: Optional[RegenerationResult],
    eval_result: Optional[HistoricalEvalResult],
    memory_comparison: Optional[HistoricalMemoryComparisonResult] = None,
) -> str:
    """Generate the full proof-pack artifact directory.

    Returns the output directory path.
    """
    output_dir = os.path.join(config.output_dir, config.run_id)
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # 1. Run manifest
    _write_manifest(output_dir, config, regen_result, eval_result)

    # 2. JSON summary
    _write_json_summary(output_dir, config, regen_result, eval_result, memory_comparison)

    # 3. Markdown report
    _write_markdown_report(output_dir, config, regen_result, eval_result, memory_comparison)

    # 4. CSV tables
    if eval_result:
        _write_decisions_csv(output_dir, eval_result)
        _write_action_outcomes_csv(output_dir, eval_result)
        _write_benchmark_csv(output_dir, eval_result)
        _write_conviction_buckets_csv(output_dir, eval_result)
        _write_best_worst_csv(output_dir, eval_result)
        _write_per_name_csv(output_dir, eval_result)
        _write_coverage_diagnostics_csv(output_dir, eval_result)
        _write_coverage_by_month_csv(output_dir, eval_result)
        _write_empirical_diagnostics_csv(output_dir, eval_result)
        _write_portfolio_timeline_csv(output_dir, eval_result)
        _write_portfolio_trades_csv(output_dir, eval_result)

        _write_portfolio_composition_csv(output_dir, eval_result)
        _write_portfolio_changes_csv(output_dir, eval_result)

    # 5. Memory comparison CSV
    if memory_comparison:
        _write_memory_comparison_csv(output_dir, memory_comparison)

    logger.info("Proof pack written to %s", output_dir)
    return output_dir


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def _write_manifest(
    output_dir: str,
    config: HistoricalEvalConfig,
    regen_result: Optional[RegenerationResult],
    eval_result: Optional[HistoricalEvalResult],
) -> None:
    """Write run manifest with metadata for empirical trust."""
    # Try to get git hash
    code_hash = _get_git_hash()

    # Collect degraded flags
    degraded_flags = []
    if not config.use_llm:
        degraded_flags.append("stub_extractor")
    if not config.backfill_sec_filings:
        degraded_flags.append("no_sec_filings")
    if not config.backfill_news_rss:
        degraded_flags.append("no_news_rss")
    if not config.backfill_pr_rss:
        degraded_flags.append("no_pr_rss")
    if not config.backfill_prices:
        degraded_flags.append("no_price_data")

    warnings = []
    if regen_result and regen_result.warnings:
        warnings.extend(regen_result.warnings)
    if eval_result and eval_result.warnings:
        warnings.extend(eval_result.warnings)

    manifest = {
        "manifest_version": "1.0",
        "run_id": config.run_id,
        "generated_at": datetime.utcnow().isoformat(),
        "code_hash": code_hash,
        "mode": config.mode,
        "universe": config.effective_tickers(),
        "universe_size": len(config.effective_tickers()),
        "date_range": {
            "backfill_start": config.backfill_start.isoformat(),
            "backfill_end": config.backfill_end.isoformat(),
            "eval_start": config.eval_start.isoformat(),
            "eval_end": config.eval_end.isoformat(),
        },
        "extractor_mode": config.extractor_mode_label(),
        "source_toggles": {
            "prices": config.backfill_prices,
            "sec_filings": config.backfill_sec_filings,
            "news_rss": config.backfill_news_rss,
            "pr_rss": config.backfill_pr_rss,
        },
        "benchmark_ticker": config.benchmark_ticker,
        "forward_return_days": config.forward_return_days,
        "cadence_days": config.cadence_days,
        "memory_enabled": config.memory_enabled,
        "strict_replay": config.strict_replay,
        "exit_policy": eval_result.exit_policy_label if eval_result else "baseline",
        "seed": config.seed,
        "degraded_flags": degraded_flags,
        "warnings_count": len(warnings),
        "warnings": warnings[:20],  # cap at 20
    }

    path = os.path.join(output_dir, "manifest.json")
    with open(path, "w") as f:
        json.dump(manifest, f, indent=2, default=str)
    logger.info("Manifest: %s", path)


def _get_git_hash() -> str:
    """Try to get current git commit hash."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"


# ---------------------------------------------------------------------------
# JSON summary
# ---------------------------------------------------------------------------

def _write_json_summary(
    output_dir: str,
    config: HistoricalEvalConfig,
    regen_result: Optional[RegenerationResult],
    eval_result: Optional[HistoricalEvalResult],
    memory_comparison: Optional[HistoricalMemoryComparisonResult],
) -> None:
    """Write machine-readable JSON summary."""
    report = {
        "report_version": "2.0",
        "report_type": "historical_proof_run",
        "generated_at": datetime.utcnow().isoformat(),
        "config": config.to_dict(),
        "regeneration": regen_result.to_dict() if regen_result else None,
        "evaluation": eval_result.to_dict() if eval_result else None,
        "memory_comparison": memory_comparison.to_dict() if memory_comparison else None,
    }

    path = os.path.join(output_dir, "summary.json")
    with open(path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    logger.info("JSON summary: %s", path)


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------

def _write_markdown_report(
    output_dir: str,
    config: HistoricalEvalConfig,
    regen_result: Optional[RegenerationResult],
    eval_result: Optional[HistoricalEvalResult],
    memory_comparison: Optional[HistoricalMemoryComparisonResult],
) -> None:
    """Write human-readable markdown report."""
    lines = []

    lines.append(f"# Historical Proof Run: {config.run_id}")
    lines.append(f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("")

    # Config
    lines.append("## Run Configuration")
    lines.append(f"- **Mode**: {config.mode}")
    lines.append(f"- **Backfill window**: {config.backfill_start} to {config.backfill_end}")
    lines.append(f"- **Eval window**: {config.eval_start} to {config.eval_end}")
    lines.append(f"- **Cadence**: {config.cadence_days} days")
    lines.append(f"- **Initial cash**: ${config.initial_cash:,.0f}")
    lines.append(f"- **Universe**: {len(config.effective_tickers())} tickers")
    lines.append(f"- **Extractor**: {config.extractor_mode_label()}")
    lines.append(f"- **Memory**: {'enabled' if config.memory_enabled else 'disabled'}")
    lines.append(f"- **Benchmark**: {config.benchmark_ticker}")
    lines.append("")

    # Degraded warnings (prominent at top)
    if config.is_usefulness_run():
        validation_warnings = config.validate_for_usefulness_run()
        if validation_warnings:
            lines.append("## Degraded Run Warnings")
            for w in validation_warnings:
                lines.append(f"- **{w}**")
            lines.append("")

    # Regeneration summary
    if regen_result:
        lines.append("## Regeneration Summary")
        lines.append(f"- Documents processed: {regen_result.total_documents}")
        lines.append(f"- Claims created: {regen_result.total_claims}")
        lines.append(f"- Thesis updates: {regen_result.total_thesis_updates}")
        lines.append(f"- State changes: {regen_result.total_state_changes}")
        lines.append(f"- State flips: {regen_result.total_state_flips}")
        lines.append("")

        if regen_result.data_coverage:
            dc = regen_result.data_coverage
            lines.append("### Data Coverage")
            lines.append(f"- Tickers with price data: {dc.get('tickers_with_prices', 0)}/{dc.get('tickers_total', 0)}")
            lines.append(f"- Total price rows: {dc.get('total_prices', 0)}")
            lines.append(f"- Total documents: {dc.get('total_documents', 0)}")
            if dc.get("documents_by_source_type"):
                for st, count in sorted(dc["documents_by_source_type"].items()):
                    lines.append(f"  - {st}: {count}")
            lines.append("")

    # Evaluation results
    if eval_result and eval_result.metrics:
        m = eval_result.metrics

        lines.append("## Key Metrics")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        lines.append(f"| Total return | {m.total_return_pct:+.2f}% |")
        if m.annualized_return_pct is not None:
            lines.append(f"| Annualized return | {m.annualized_return_pct:+.2f}% |")
        lines.append(f"| Max drawdown | {m.max_drawdown_pct:.2f}% |")
        lines.append(f"| Reviews | {m.total_review_dates} |")
        lines.append(f"| Purity | {m.purity_level} |")
        lines.append("")

        # Benchmark
        if eval_result.benchmark:
            b = eval_result.benchmark
            lines.append("## Benchmark Comparison")
            lines.append("| Benchmark | Return |")
            lines.append("|-----------|--------|")
            lines.append(f"| Portfolio | {b.portfolio_return_pct:+.2f}% |")
            if b.benchmark_return_pct is not None:
                lines.append(f"| {b.benchmark_ticker} | {b.benchmark_return_pct:+.2f}% |")
            if b.excess_return_pct is not None:
                lines.append(f"| Excess vs {b.benchmark_ticker} | {b.excess_return_pct:+.2f}% |")
            if b.equal_weight_return_pct is not None:
                lines.append(f"| Equal-weight | {b.equal_weight_return_pct:+.2f}% |")
            if b.vs_equal_weight_pct is not None:
                lines.append(f"| Excess vs EW | {b.vs_equal_weight_pct:+.2f}% |")
            lines.append("")

        # Forward returns by action
        if eval_result.forward_return_summary:
            lines.append("## Forward Returns by Action Type")
            lines.append("| Action | Count | Avg 5D | Avg 20D | Avg 60D |")
            lines.append("|--------|-------|--------|---------|---------|")
            for s in eval_result.forward_return_summary:
                f5 = f"{s.avg_5d:+.2f}%" if s.avg_5d is not None else "N/A"
                f20 = f"{s.avg_20d:+.2f}%" if s.avg_20d is not None else "N/A"
                f60 = f"{s.avg_60d:+.2f}%" if s.avg_60d is not None else "N/A"
                lines.append(f"| {s.action} | {s.count} | {f5} | {f20} | {f60} |")
            lines.append("")

        # Conviction buckets
        if eval_result.conviction_buckets:
            lines.append("## Conviction Bucket Analysis")
            lines.append("| Bucket | Actions | Avg Conviction | Avg 5D | Avg 20D | Avg 60D |")
            lines.append("|--------|---------|----------------|--------|---------|---------|")
            for b in eval_result.conviction_buckets:
                conv = f"{b.avg_conviction:.0f}" if b.avg_conviction is not None else "N/A"
                f5 = f"{b.avg_forward_5d:+.2f}%" if b.avg_forward_5d is not None else "N/A"
                f20 = f"{b.avg_forward_20d:+.2f}%" if b.avg_forward_20d is not None else "N/A"
                f60 = f"{b.avg_forward_60d:+.2f}%" if b.avg_forward_60d is not None else "N/A"
                lines.append(f"| {b.bucket} | {b.action_count} | {conv} | {f5} | {f20} | {f60} |")
            lines.append("")

        # Best decisions
        if eval_result.best_decisions:
            lines.append("## Best Decisions (by 20D forward return)")
            lines.append("| Date | Ticker | Action | Conviction | 5D | 20D | 60D |")
            lines.append("|------|--------|--------|------------|-----|------|------|")
            for d in eval_result.best_decisions[:10]:
                conv = d.get('thesis_conviction', d.get('conviction', 0))
                f5 = f"{d['forward_5d_pct']:+.2f}%" if d.get('forward_5d_pct') is not None else "—"
                f20 = f"{d['forward_20d_pct']:+.2f}%" if d.get('forward_20d_pct') is not None else "—"
                f60 = f"{d['forward_60d_pct']:+.2f}%" if d.get('forward_60d_pct') is not None else "—"
                lines.append(f"| {d['review_date']} | {d['ticker']} | {d['action']} | {conv} | {f5} | {f20} | {f60} |")
            lines.append("")

        # Worst decisions
        if eval_result.worst_decisions:
            lines.append("## Worst Decisions (by 20D forward return)")
            lines.append("| Date | Ticker | Action | Conviction | 5D | 20D | 60D |")
            lines.append("|------|--------|--------|------------|-----|------|------|")
            for d in eval_result.worst_decisions[:10]:
                conv = d.get('thesis_conviction', d.get('conviction', 0))
                f5 = f"{d['forward_5d_pct']:+.2f}%" if d.get('forward_5d_pct') is not None else "—"
                f20 = f"{d['forward_20d_pct']:+.2f}%" if d.get('forward_20d_pct') is not None else "—"
                f60 = f"{d['forward_60d_pct']:+.2f}%" if d.get('forward_60d_pct') is not None else "—"
                lines.append(f"| {d['review_date']} | {d['ticker']} | {d['action']} | {conv} | {f5} | {f20} | {f60} |")
            lines.append("")

        # Per-name summary
        if eval_result.per_name_summary:
            lines.append("## Per-Name Usefulness Summary")
            lines.append("| Ticker | Actions | Docs | Claims | Avg 5D | Avg 20D | Avg 60D | Price Cov |")
            lines.append("|--------|---------|------|--------|--------|---------|---------|-----------|")
            for p in eval_result.per_name_summary:
                f5 = f"{p.avg_forward_5d:+.2f}%" if p.avg_forward_5d is not None else "—"
                f20 = f"{p.avg_forward_20d:+.2f}%" if p.avg_forward_20d is not None else "—"
                f60 = f"{p.avg_forward_60d:+.2f}%" if p.avg_forward_60d is not None else "—"
                lines.append(f"| {p.ticker} | {p.action_count} | {p.doc_count} | {p.claim_count} | {f5} | {f20} | {f60} | {p.price_coverage_pct:.0f}% |")
            lines.append("")

        # Coverage diagnostics summary
        if eval_result.coverage_diagnostics:
            cd = eval_result.coverage_diagnostics
            lines.append("## Source Coverage Diagnostics")
            lines.append(f"- **Extractor mode**: {cd.extractor_mode}")
            lines.append(f"- **Benchmark available**: {'yes' if cd.benchmark_available else 'no'}")
            lines.append(f"- **Tickers with prices**: {cd.tickers_with_prices}")
            lines.append(f"- **Tickers without prices**: {cd.tickers_without_prices}")
            lines.append(f"- **Total price rows**: {cd.total_price_rows}")
            lines.append("")

            if cd.docs_by_source_type:
                lines.append("### Documents by Source Type")
                lines.append("| Source Type | Count |")
                lines.append("|------------|-------|")
                for st, count in sorted(cd.docs_by_source_type.items()):
                    lines.append(f"| {st} | {count} |")
                lines.append("")

            if cd.source_gaps:
                lines.append("### Source Gaps")
                for gap in cd.source_gaps[:20]:
                    lines.append(f"- **{gap['ticker']}**: {gap['detail']}")
                lines.append("")

        # Diagnostics
        if eval_result.diagnostics:
            d = eval_result.diagnostics
            lines.append("## Decision Summary")
            lines.append(f"- Total actions: {sum(d.action_counts.values())}")
            lines.append(f"- Recommendation changes: {d.recommendation_changes}")
            lines.append(f"- Change rate: {d.recommendation_change_rate:.3f} per review")
            lines.append(f"- Short-hold exits (<30d): {d.short_hold_exits}")
            lines.append("")

            if d.action_counts:
                lines.append("### Action Mix")
                lines.append("| Action | Count | % |")
                lines.append("|--------|-------|---|")
                for action, count in sorted(d.action_counts.items(), key=lambda x: -x[1]):
                    pct = d.action_pcts.get(action, 0)
                    lines.append(f"| {action} | {count} | {pct:.1f}% |")
                lines.append("")

    # Failure analysis
    if eval_result and eval_result.failure_analysis:
        fa = eval_result.failure_analysis
        has_failures = (
            fa.degraded_flags or fa.sparse_coverage_tickers or
            fa.negative_return_actions or fa.non_differentiating_buckets or
            fa.repeated_bad_recommendations or fa.low_evidence_periods
        )
        if has_failures:
            lines.append("## Failure Analysis")
            lines.append("")

            if fa.degraded_flags:
                lines.append("### Degraded Run Flags")
                for flag in fa.degraded_flags:
                    lines.append(f"- {flag}")
                lines.append("")

            if fa.sparse_coverage_tickers:
                lines.append("### Sparse Coverage Tickers")
                lines.append("| Ticker | Issues | Docs | Claims | Price Cov |")
                lines.append("|--------|--------|------|--------|-----------|")
                for sc in fa.sparse_coverage_tickers:
                    issues = "; ".join(sc["issues"])
                    lines.append(f"| {sc['ticker']} | {issues} | {sc['doc_count']} | {sc['claim_count']} | {sc['price_coverage_pct']}% |")
                lines.append("")

            if fa.negative_return_actions:
                lines.append("### Action Types with Negative Forward Returns")
                for nra in fa.negative_return_actions:
                    lines.append(f"- {nra['concern']}")
                lines.append("")

            if fa.non_differentiating_buckets:
                lines.append("### Non-Differentiating Conviction Buckets")
                for ndb in fa.non_differentiating_buckets:
                    lines.append(f"- {ndb['concern']} (spread: {ndb['spread_pct']}%)")
                lines.append("")

            if fa.repeated_bad_recommendations:
                lines.append("### Repeated Bad Recommendations")
                for rbr in fa.repeated_bad_recommendations:
                    lines.append(f"- {rbr['concern']}")
                lines.append("")

            if fa.low_evidence_periods:
                lines.append("### Low Evidence Periods")
                for lep in fa.low_evidence_periods:
                    lines.append(f"- {lep['concern']}")
                lines.append("")

    # Empirical diagnostics sections
    if eval_result:
        try:
            from empirical_diagnostics import (
                format_deterioration_section,
                format_enhanced_failure_section,
            )
            if eval_result.deterioration_diagnostics:
                lines.extend(format_deterioration_section(eval_result.deterioration_diagnostics))
            if eval_result.enhanced_failure_analysis:
                lines.extend(format_enhanced_failure_section(eval_result.enhanced_failure_analysis))
        except Exception:
            pass

    # Memory comparison
    if memory_comparison and memory_comparison.comparison:
        lines.append("## Memory Ablation: ON vs OFF")
        mc = memory_comparison.comparison

        if "regeneration" in mc:
            r = mc["regeneration"]
            lines.append("### Regeneration Differences")
            lines.append("| Metric | Memory ON | Memory OFF |")
            lines.append("|--------|-----------|------------|")
            lines.append(f"| Thesis updates | {r.get('thesis_updates_on', 0)} | {r.get('thesis_updates_off', 0)} |")
            lines.append(f"| State changes | {r.get('state_changes_on', 0)} | {r.get('state_changes_off', 0)} |")
            lines.append(f"| State flips | {r.get('state_flips_on', 0)} | {r.get('state_flips_off', 0)} |")
            lines.append("")

        if "portfolio" in mc:
            p = mc["portfolio"]
            lines.append("### Portfolio Differences")
            lines.append("| Metric | Memory ON | Memory OFF | Delta |")
            lines.append("|--------|-----------|------------|-------|")
            lines.append(f"| Return | {p.get('return_on_pct', 0):+.2f}% | {p.get('return_off_pct', 0):+.2f}% | {p.get('return_delta_pct', 0):+.2f}% |")
            lines.append(f"| Drawdown | {p.get('drawdown_on_pct', 0):.2f}% | {p.get('drawdown_off_pct', 0):.2f}% | — |")
            lines.append(f"| Initiations | {p.get('initiations_on', 0)} | {p.get('initiations_off', 0)} | — |")
            lines.append(f"| Exits | {p.get('exits_on', 0)} | {p.get('exits_off', 0)} | — |")
            lines.append("")

    # Warnings
    all_warnings = []
    if regen_result and regen_result.warnings:
        all_warnings.extend(regen_result.warnings)
    if eval_result and eval_result.warnings:
        all_warnings.extend(eval_result.warnings)
    if memory_comparison and memory_comparison.warnings:
        all_warnings.extend(memory_comparison.warnings)

    if all_warnings:
        lines.append("## Warnings")
        for w in all_warnings:
            lines.append(f"- {w}")
        lines.append("")

    # Limitations
    lines.append("## Limitations")
    if not config.use_llm:
        lines.append("- **Stub LLM mode**: claim extraction uses deterministic stub, not real LLM")
    lines.append("- Returns are not statistically significant over short replay windows")
    lines.append("- No earnings transcript backfill (manual source only)")
    lines.append("- News coverage degrades rapidly for periods >90 days ago")
    lines.append("- Equal-weight baseline assumes no transaction costs")
    lines.append("- Forward returns assume execution at close price on decision date")
    lines.append("- No sector-level attribution (sector data not versioned historically)")
    lines.append("")

    # Artifact index
    lines.append("## Artifact Index")
    lines.append("| File | Description |")
    lines.append("|------|-------------|")
    lines.append("| manifest.json | Run manifest with metadata and degraded flags |")
    lines.append("| summary.json | Machine-readable full report |")
    lines.append("| report.md | This report |")
    lines.append("| decisions.csv | Per-review-date decisions |")
    lines.append("| action_outcomes.csv | Per-action forward returns |")
    lines.append("| best_decisions.csv | Top decisions by forward return |")
    lines.append("| worst_decisions.csv | Bottom decisions by forward return |")
    lines.append("| per_name_summary.csv | Per-ticker usefulness summary |")
    lines.append("| coverage_diagnostics.csv | Source coverage by ticker |")
    lines.append("| coverage_by_month.csv | Source coverage by month |")
    lines.append("| benchmark.csv | Benchmark comparison |")
    lines.append("| conviction_buckets.csv | Conviction bucket summary |")
    lines.append("| probation_events.csv | Probation event diagnostics |")
    lines.append("| exit_events.csv | Exit event diagnostics |")
    if memory_comparison:
        lines.append("| memory_comparison.csv | Memory ON vs OFF comparison |")
    lines.append("")

    path = os.path.join(output_dir, "report.md")
    with open(path, "w") as f:
        f.write("\n".join(lines))
    logger.info("Markdown report: %s", path)


# ---------------------------------------------------------------------------
# CSV writers
# ---------------------------------------------------------------------------

def _write_decisions_csv(output_dir: str, eval_result: HistoricalEvalResult) -> None:
    """Write per-review-date decisions CSV."""
    path = os.path.join(output_dir, "decisions.csv")
    fieldnames = [
        "review_date", "ticker", "action", "thesis_conviction", "action_score",
        "conviction_bucket", "prior_weight", "new_weight", "weight_change",
        "suggested_weight", "rationale",
    ]

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in eval_result.decision_rows:
            writer.writerow(row)

    logger.info("Decisions CSV: %s (%d rows)", path, len(eval_result.decision_rows))


def _write_action_outcomes_csv(output_dir: str, eval_result: HistoricalEvalResult) -> None:
    """Write per-action forward-return outcomes CSV."""
    path = os.path.join(output_dir, "action_outcomes.csv")
    fieldnames = [
        "review_date", "ticker", "action", "thesis_conviction", "action_score",
        "conviction_bucket", "prior_weight", "new_weight", "weight_change",
        "price_at_decision", "forward_5d_pct", "forward_20d_pct", "forward_60d_pct",
    ]

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for outcome in eval_result.action_outcomes:
            d = outcome.to_dict()
            row = {k: d.get(k) for k in fieldnames}
            writer.writerow(row)

    logger.info("Action outcomes CSV: %s (%d rows)", path, len(eval_result.action_outcomes))


def _write_benchmark_csv(output_dir: str, eval_result: HistoricalEvalResult) -> None:
    """Write benchmark comparison CSV."""
    path = os.path.join(output_dir, "benchmark.csv")
    fieldnames = ["benchmark", "return_pct", "data_available"]

    rows = []
    m = eval_result.metrics
    if m:
        rows.append({"benchmark": "Portfolio", "return_pct": round(m.total_return_pct, 2), "data_available": True})

    b = eval_result.benchmark
    if b:
        rows.append({
            "benchmark": b.benchmark_ticker,
            "return_pct": round(b.benchmark_return_pct, 2) if b.benchmark_return_pct is not None else None,
            "data_available": b.benchmark_data_available,
        })
        rows.append({
            "benchmark": "Equal-weight",
            "return_pct": round(b.equal_weight_return_pct, 2) if b.equal_weight_return_pct is not None else None,
            "data_available": b.equal_weight_tickers_with_data > 0,
        })

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    logger.info("Benchmark CSV: %s", path)


def _write_conviction_buckets_csv(output_dir: str, eval_result: HistoricalEvalResult) -> None:
    """Write conviction bucket summary CSV."""
    path = os.path.join(output_dir, "conviction_buckets.csv")
    fieldnames = [
        "bucket", "action_count", "avg_conviction",
        "avg_forward_5d_pct", "avg_forward_20d_pct", "avg_forward_60d_pct",
    ]

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for b in eval_result.conviction_buckets:
            writer.writerow(b.to_dict())

    logger.info("Conviction buckets CSV: %s", path)


def _write_best_worst_csv(output_dir: str, eval_result: HistoricalEvalResult) -> None:
    """Write best and worst decisions CSVs."""
    fieldnames = [
        "review_date", "ticker", "action", "thesis_conviction", "action_score",
        "conviction_bucket",
        "price_at_decision", "forward_5d_pct", "forward_20d_pct", "forward_60d_pct",
        "rationale",
    ]

    for label, decisions in [("best", eval_result.best_decisions), ("worst", eval_result.worst_decisions)]:
        path = os.path.join(output_dir, f"{label}_decisions.csv")
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for d in decisions:
                writer.writerow({k: d.get(k) for k in fieldnames})
        logger.info("%s decisions CSV: %s (%d rows)", label.title(), path, len(decisions))


def _write_per_name_csv(output_dir: str, eval_result: HistoricalEvalResult) -> None:
    """Write per-ticker usefulness summary CSV."""
    path = os.path.join(output_dir, "per_name_summary.csv")
    fieldnames = [
        "ticker", "action_count", "initiate_count", "exit_count", "hold_count",
        "avg_forward_5d_pct", "avg_forward_20d_pct", "avg_forward_60d_pct",
        "doc_count", "claim_count", "price_coverage_pct",
    ]

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for p in eval_result.per_name_summary:
            writer.writerow(p.to_dict())

    logger.info("Per-name summary CSV: %s (%d rows)", path, len(eval_result.per_name_summary))


def _write_coverage_diagnostics_csv(output_dir: str, eval_result: HistoricalEvalResult) -> None:
    """Write source coverage diagnostics CSV (per ticker)."""
    path = os.path.join(output_dir, "coverage_diagnostics.csv")
    fieldnames = ["ticker", "doc_count", "claim_count", "has_prices"]

    cd = eval_result.coverage_diagnostics
    if not cd:
        return

    tickers = sorted(set(list(cd.docs_by_ticker.keys()) + list(cd.claims_by_ticker.keys())))
    if not tickers:
        tickers = sorted(eval_result.config.effective_tickers())

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for t in tickers:
            writer.writerow({
                "ticker": t,
                "doc_count": cd.docs_by_ticker.get(t, 0),
                "claim_count": cd.claims_by_ticker.get(t, 0),
                "has_prices": t in cd.docs_by_ticker or cd.tickers_with_prices > 0,
            })

    logger.info("Coverage diagnostics CSV: %s", path)


def _write_coverage_by_month_csv(output_dir: str, eval_result: HistoricalEvalResult) -> None:
    """Write source coverage by month CSV."""
    path = os.path.join(output_dir, "coverage_by_month.csv")
    fieldnames = ["month", "doc_count"]

    cd = eval_result.coverage_diagnostics
    if not cd or not cd.docs_by_month:
        # Write empty file with headers
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
        return

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for month, count in sorted(cd.docs_by_month.items()):
            writer.writerow({"month": month, "doc_count": count})

    logger.info("Coverage by month CSV: %s", path)


def _write_empirical_diagnostics_csv(output_dir: str, eval_result: HistoricalEvalResult) -> None:
    """Write probation/exit event CSVs if diagnostics are available."""
    try:
        from empirical_diagnostics import (
            write_probation_events_csv,
            write_exit_events_csv,
        )
        diag = eval_result.deterioration_diagnostics
        if diag:
            write_probation_events_csv(output_dir, diag.probation_events)
            write_exit_events_csv(output_dir, diag.exit_events)
    except Exception as e:
        logger.warning("Failed to write empirical diagnostics CSVs: %s", e)


def _write_portfolio_timeline_csv(output_dir: str, eval_result: HistoricalEvalResult) -> None:
    """Write portfolio value at each review date."""
    rr = eval_result.run_result
    if not rr or not rr.review_records:
        return

    path = os.path.join(output_dir, "portfolio_timeline.csv")
    fieldnames = [
        "review_date", "total_value", "cash", "invested", "num_positions",
        "cash_weight_pct", "top_holding", "top_holding_weight",
    ]

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for rec in rr.review_records:
            snap = rec.snapshot
            if not snap:
                continue
            cash_weight = (snap.cash / snap.total_value * 100.0) if snap.total_value > 0 else 100.0
            top_holding = ""
            top_weight = 0.0
            if snap.weights:
                top_holding = max(snap.weights, key=snap.weights.get)
                top_weight = snap.weights[top_holding]
            writer.writerow({
                "review_date": snap.date.isoformat() if snap.date else rec.review_date.isoformat(),
                "total_value": round(snap.total_value, 2),
                "cash": round(snap.cash, 2),
                "invested": round(snap.invested, 2),
                "num_positions": snap.num_positions,
                "cash_weight_pct": round(cash_weight, 2),
                "top_holding": top_holding,
                "top_holding_weight": round(top_weight, 2),
            })

    logger.info("Portfolio timeline CSV: %s", path)


def _write_portfolio_trades_csv(output_dir: str, eval_result: HistoricalEvalResult) -> None:
    """Write all portfolio trades."""
    portfolio = eval_result.portfolio
    if not portfolio or not portfolio.trades:
        return

    path = os.path.join(output_dir, "portfolio_trades.csv")
    fieldnames = ["trade_date", "ticker", "action", "shares", "price", "notional", "reason"]

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for t in portfolio.trades:
            writer.writerow({
                "trade_date": t.trade_date.isoformat() if t.trade_date else "",
                "ticker": t.ticker,
                "action": t.action,
                "shares": round(t.shares, 4) if t.shares else 0,
                "price": round(t.price, 2) if t.price else 0,
                "notional": round(t.notional, 2) if t.notional else 0,
                "reason": (t.reason or "")[:200],
            })

    logger.info("Portfolio trades CSV: %s (%d trades)", path, len(portfolio.trades))


def _write_portfolio_composition_csv(output_dir: str, eval_result: HistoricalEvalResult) -> None:
    """Write per-position weights at each review date.

    Each row is (review_date, ticker, weight_pct, market_value, shares).
    This is the data that was computed in PortfolioSnapshot.weights but previously discarded.
    """
    rr = eval_result.run_result
    if not rr or not rr.review_records:
        return

    path = os.path.join(output_dir, "portfolio_composition.csv")
    fieldnames = [
        "review_date", "ticker", "weight_pct", "market_value",
        "portfolio_total", "cash", "cash_weight_pct", "num_positions",
    ]

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for rec in rr.review_records:
            snap = rec.snapshot
            if not snap:
                continue
            rd = snap.date.isoformat() if snap.date else rec.review_date.isoformat()
            cash_weight = (snap.cash / snap.total_value * 100.0) if snap.total_value > 0 else 100.0
            for ticker in sorted(snap.weights.keys()):
                writer.writerow({
                    "review_date": rd,
                    "ticker": ticker,
                    "weight_pct": round(snap.weights[ticker], 2),
                    "market_value": round(snap.positions.get(ticker, 0), 2),
                    "portfolio_total": round(snap.total_value, 2),
                    "cash": round(snap.cash, 2),
                    "cash_weight_pct": round(cash_weight, 2),
                    "num_positions": snap.num_positions,
                })

    logger.info("Portfolio composition CSV: %s", path)


def _write_portfolio_changes_csv(output_dir: str, eval_result: HistoricalEvalResult) -> None:
    """Write meaningful portfolio change events.

    A 'change' is a decision where the portfolio actually moved (not hold/no_action).
    Includes before/after weights, conviction, and action context.
    """
    rr = eval_result.run_result
    if not rr or not rr.review_records:
        return

    path = os.path.join(output_dir, "portfolio_changes.csv")
    fieldnames = [
        "review_date", "ticker", "event_type", "prior_weight", "new_weight",
        "delta_weight", "conviction_before", "conviction_after",
        "rationale_summary", "forward_5d_pct", "forward_20d_pct", "forward_60d_pct",
    ]

    # Build outcome lookup
    outcome_lookup = {}
    for ao in eval_result.action_outcomes:
        key = (ao.review_date.isoformat(), ao.ticker)
        outcome_lookup[key] = ao

    # Build per-review-date conviction lookup from decisions
    # (conviction_before = prior review's conviction for that ticker)
    prev_conviction = {}  # ticker -> last known conviction

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        prev_snap = None
        for rec in rr.review_records:
            snap = rec.snapshot
            rd = rec.review_date.isoformat()

            for decision in rec.result.decisions:
                action = decision.action.value
                # Only meaningful changes
                if action in ("no_action", "hold"):
                    # Update conviction tracking even for holds
                    prev_conviction[decision.ticker] = decision.thesis_conviction
                    continue

                ticker = decision.ticker
                prior_weight = prev_snap.weights.get(ticker, 0.0) if prev_snap else 0.0
                new_weight = snap.weights.get(ticker, 0.0) if snap else 0.0
                conv_before = prev_conviction.get(ticker, 0.0)
                conv_after = decision.thesis_conviction

                # Map action to event type
                event_type = action  # initiate, add, trim, exit, probation

                # Get forward returns from outcomes
                ao = outcome_lookup.get((rd, ticker))

                writer.writerow({
                    "review_date": rd,
                    "ticker": ticker,
                    "event_type": event_type,
                    "prior_weight": round(prior_weight, 2),
                    "new_weight": round(new_weight, 2),
                    "delta_weight": round(new_weight - prior_weight, 2),
                    "conviction_before": round(conv_before, 1),
                    "conviction_after": round(conv_after, 1),
                    "rationale_summary": (decision.rationale or "")[:200],
                    "forward_5d_pct": round(ao.forward_5d, 2) if ao and ao.forward_5d is not None else None,
                    "forward_20d_pct": round(ao.forward_20d, 2) if ao and ao.forward_20d is not None else None,
                    "forward_60d_pct": round(ao.forward_60d, 2) if ao and ao.forward_60d is not None else None,
                })

                prev_conviction[ticker] = conv_after

            if snap:
                prev_snap = snap

    logger.info("Portfolio changes CSV: %s", path)


def _write_memory_comparison_csv(
    output_dir: str,
    comparison: HistoricalMemoryComparisonResult,
) -> None:
    """Write memory ON vs OFF comparison CSV."""
    path = os.path.join(output_dir, "memory_comparison.csv")
    fieldnames = ["metric", "memory_on", "memory_off", "delta"]

    rows = []
    mc = comparison.comparison

    if "regeneration" in mc:
        r = mc["regeneration"]
        for key in ["thesis_updates", "state_changes", "state_flips"]:
            on_val = r.get(f"{key}_on", 0)
            off_val = r.get(f"{key}_off", 0)
            rows.append({
                "metric": key,
                "memory_on": on_val,
                "memory_off": off_val,
                "delta": on_val - off_val,
            })

    if "portfolio" in mc:
        p = mc["portfolio"]
        for key in ["return", "drawdown", "initiations", "exits"]:
            if key == "return":
                on_key = "return_on_pct"
                off_key = "return_off_pct"
            elif key == "drawdown":
                on_key = "drawdown_on_pct"
                off_key = "drawdown_off_pct"
            else:
                on_key = f"{key}_on"
                off_key = f"{key}_off"

            on_val = p.get(on_key, 0)
            off_val = p.get(off_key, 0)
            rows.append({
                "metric": key,
                "memory_on": on_val,
                "memory_off": off_val,
                "delta": round(on_val - off_val, 2) if isinstance(on_val, float) else on_val - off_val,
            })

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    logger.info("Memory comparison CSV: %s", path)
