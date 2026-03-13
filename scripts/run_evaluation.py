"""Evaluation runner: CLI for running evaluation experiments.

Usage:
    # Standard evaluation
    python scripts/run_evaluation.py --start 2025-01-01 --end 2025-12-31

    # Memory comparison
    python scripts/run_evaluation.py --start 2025-01-01 --end 2025-12-31 --memory-comparison

    # Strict replay evaluation
    python scripts/run_evaluation.py --start 2025-01-01 --end 2025-12-31 --strict

    # Custom run ID
    python scripts/run_evaluation.py --start 2025-01-01 --end 2025-12-31 --run-id my_experiment
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

# Add project root to path
sys.path.insert(0, ".")

from models import get_session
from eval_config import EvalConfig
from eval_harness import run_evaluation, run_memory_comparison
from eval_report import generate_json_report, generate_markdown_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Run evaluation experiment")
    parser.add_argument("--start", type=str, default="2025-01-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, default="2025-12-31", help="End date (YYYY-MM-DD)")
    parser.add_argument("--cadence", type=int, default=7, help="Review cadence in days")
    parser.add_argument("--initial-cash", type=float, default=1_000_000, help="Initial portfolio cash")
    parser.add_argument("--strict", action="store_true", help="Use strict replay mode")
    parser.add_argument("--no-memory", action="store_true", help="Disable memory retrieval")
    parser.add_argument("--memory-comparison", action="store_true", help="Run memory ON vs OFF comparison")
    parser.add_argument("--run-id", type=str, default="default", help="Run identifier")
    parser.add_argument("--benchmark", type=str, default="SPY", help="Benchmark ticker")
    parser.add_argument("--output-dir", type=str, default="eval_reports", help="Output directory")
    parser.add_argument("--ticker", type=str, default=None, help="Filter to single ticker")
    parser.add_argument("--json-only", action="store_true", help="Only generate JSON report")

    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)

    if args.memory_comparison:
        _run_memory_comparison(args, start, end)
    else:
        _run_single_evaluation(args, start, end)


def _run_single_evaluation(args, start: date, end: date):
    config = EvalConfig(
        run_id=args.run_id,
        run_label=f"Evaluation: {start} to {end}",
        start_date=start,
        end_date=end,
        cadence_days=args.cadence,
        initial_cash=args.initial_cash,
        strict_replay=args.strict,
        memory_enabled=not args.no_memory,
        benchmark_ticker=args.benchmark,
        ticker_filter=args.ticker,
    )

    session = get_session()
    try:
        result = run_evaluation(session, config)

        # Generate reports
        json_path = generate_json_report(result, output_dir=args.output_dir)
        print(f"JSON report: {json_path}")

        if not args.json_only:
            md_path = generate_markdown_report(result, output_dir=args.output_dir)
            print(f"Markdown report: {md_path}")

        # Print key metrics to console
        _print_summary(result)
    finally:
        session.close()


def _run_memory_comparison(args, start: date, end: date):
    config_on, config_off = EvalConfig.memory_comparison_pair(
        start_date=start,
        end_date=end,
        cadence_days=args.cadence,
        initial_cash=args.initial_cash,
        strict_replay=args.strict,
    )

    session = get_session()
    try:
        # Run standard evaluation first
        result_on = run_evaluation(session, config_on)

        # Run memory comparison
        comparison = run_memory_comparison(session, config_on, config_off)

        # Generate reports with comparison data
        json_path = generate_json_report(result_on, comparison, output_dir=args.output_dir)
        print(f"JSON report: {json_path}")

        if not args.json_only:
            md_path = generate_markdown_report(result_on, comparison, output_dir=args.output_dir)
            print(f"Markdown report: {md_path}")

        # Print comparison summary
        _print_comparison_summary(comparison)
    finally:
        session.close()


def _print_summary(result):
    m = result.metrics
    d = result.diagnostics
    b = result.benchmark

    print("\n" + "=" * 60)
    print(f"Evaluation Summary: {result.config.run_id}")
    print("=" * 60)
    print(f"  Return:         {m.total_return_pct:+.2f}%")
    print(f"  Max drawdown:   {m.max_drawdown_pct:.2f}%")
    print(f"  Reviews:        {m.total_review_dates}")
    print(f"  Actions:        {sum(d.action_counts.values())}")
    print(f"  Rec. changes:   {d.recommendation_changes}")
    print(f"  Purity:         {m.purity_level}")
    if b and b.excess_return_pct is not None:
        print(f"  vs {b.benchmark_ticker}:         {b.excess_return_pct:+.2f}%")
    if b and b.vs_equal_weight_pct is not None:
        print(f"  vs EW baseline: {b.vs_equal_weight_pct:+.2f}%")
    print("=" * 60)


def _print_comparison_summary(comparison):
    on = comparison.memory_on_metrics
    off = comparison.memory_off_metrics

    print("\n" + "=" * 60)
    print("Memory Comparison: ON vs OFF")
    print("=" * 60)
    print(f"  {'Metric':<30} {'ON':>10} {'OFF':>10} {'Delta':>10}")
    print(f"  {'-'*30} {'-'*10} {'-'*10} {'-'*10}")

    for key in ["total_return_pct", "state_changes", "state_flips",
                 "recommendation_changes", "total_actions"]:
        v_on = on.get(key, 0)
        v_off = off.get(key, 0)
        delta = v_on - v_off
        fmt_on = f"{v_on:.2f}" if isinstance(v_on, float) else str(v_on)
        fmt_off = f"{v_off:.2f}" if isinstance(v_off, float) else str(v_off)
        delta_str = f"{delta:+.2f}" if isinstance(delta, float) else f"{delta:+d}"
        print(f"  {key:<30} {fmt_on:>10} {fmt_off:>10} {delta_str:>10}")

    print(f"  {'score_volatility':<30} {comparison.score_volatility_on:>10.4f} {comparison.score_volatility_off:>10.4f} {comparison.score_volatility_on - comparison.score_volatility_off:>+10.4f}")
    print("=" * 60)


if __name__ == "__main__":
    main()
