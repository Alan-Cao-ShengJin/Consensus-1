"""Historical proof-pack report generation.

Produces a structured artifact pack from a historical evaluation run:
- summary.json: Machine-readable full report
- report.md: Human-readable markdown report
- decisions.csv: Per-review-date decisions
- action_outcomes.csv: Per-action forward returns
- benchmark.csv: Benchmark comparison
- conviction_buckets.csv: Conviction bucket summary
- memory_comparison.csv: Memory ON vs OFF (if ablation run)
"""
from __future__ import annotations

import csv
import json
import logging
import os
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

    # 1. JSON summary
    _write_json_summary(output_dir, config, regen_result, eval_result, memory_comparison)

    # 2. Markdown report
    _write_markdown_report(output_dir, config, regen_result, eval_result, memory_comparison)

    # 3. CSV tables
    if eval_result:
        _write_decisions_csv(output_dir, eval_result)
        _write_action_outcomes_csv(output_dir, eval_result)
        _write_benchmark_csv(output_dir, eval_result)
        _write_conviction_buckets_csv(output_dir, eval_result)

    # 4. Memory comparison CSV
    if memory_comparison:
        _write_memory_comparison_csv(output_dir, memory_comparison)

    logger.info("Proof pack written to %s", output_dir)
    return output_dir


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
    lines.append(f"- **LLM mode**: {'real' if config.use_llm else 'stub'}")
    lines.append(f"- **Memory**: {'enabled' if config.memory_enabled else 'disabled'}")
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
    lines.append("- Stub LLM mode: claim extraction uses deterministic stub, not real LLM")
    lines.append("- Returns are not statistically significant over short replay windows")
    lines.append("- No earnings transcript backfill (manual source only)")
    lines.append("- News coverage degrades rapidly for periods >90 days ago")
    lines.append("- Equal-weight baseline assumes no transaction costs")
    lines.append("- Forward returns assume execution at close price on decision date")
    lines.append("- No sector-level attribution (sector data not versioned historically)")
    lines.append("")

    path = os.path.join(output_dir, "report.md")
    with open(path, "w") as f:
        f.write("\n".join(lines))
    logger.info("Markdown report: %s", path)


def _write_decisions_csv(output_dir: str, eval_result: HistoricalEvalResult) -> None:
    """Write per-review-date decisions CSV."""
    path = os.path.join(output_dir, "decisions.csv")
    fieldnames = ["review_date", "ticker", "action", "conviction", "conviction_bucket", "rationale"]

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
        "review_date", "ticker", "action", "conviction", "conviction_bucket",
        "price_at_decision", "forward_5d_pct", "forward_20d_pct", "forward_60d_pct",
    ]

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for outcome in eval_result.action_outcomes:
            d = outcome.to_dict()
            # Remove rationale from this CSV (it's in decisions.csv)
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
            on_key = f"{key}_on" if key != "return" else "return_on_pct"
            off_key = f"{key}_off" if key != "return" else "return_off_pct"
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
