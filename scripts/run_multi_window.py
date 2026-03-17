"""Multi-window runner: run the same usefulness test across multiple date windows.

Usage:
    # Default 3 windows (automatic)
    python scripts/run_multi_window.py

    # Without LLM (stub mode)
    python scripts/run_multi_window.py --no-llm

    # Custom windows
    python scripts/run_multi_window.py --windows "2025-01-01:2025-07-01,2025-04-01:2025-10-01,2025-06-01:2026-01-01"

    # Custom tickers
    python scripts/run_multi_window.py --tickers AAPL,NVDA,MSFT
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, ".")

from db import get_session
from exit_policy import BASELINE_POLICY
from historical_eval_config import HistoricalEvalConfig, HistoricalRunMode
from empirical_diagnostics import (
    compute_deterioration_diagnostics,
    WindowResult,
    MultiWindowResult,
    aggregate_multi_window,
    write_window_summary_csv,
    format_multi_window_section,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


# Default windows: 3 non-overlapping 6-month periods
DEFAULT_WINDOWS = [
    ("W1", date(2025, 1, 1), date(2025, 7, 1)),
    ("W2", date(2025, 4, 1), date(2025, 10, 1)),
    ("W3", date(2025, 6, 1), date(2026, 1, 1)),
]


def parse_windows(spec: str) -> list[tuple[str, date, date]]:
    """Parse window spec: 'start:end,start:end,...' """
    windows = []
    for i, part in enumerate(spec.split(",")):
        start_s, end_s = part.strip().split(":")
        label = f"W{i + 1}"
        windows.append((label, date.fromisoformat(start_s), date.fromisoformat(end_s)))
    return windows


def main():
    parser = argparse.ArgumentParser(description="Multi-window empirical runs")
    parser.add_argument("--windows", type=str, default=None,
                        help="Window spec: 'start:end,start:end,...'")
    parser.add_argument("--cadence", type=int, default=7)
    parser.add_argument("--tickers", type=str, default=None)
    parser.add_argument("--no-llm", action="store_true", help="Disable LLM, use stub extractor")
    parser.add_argument("--output-dir", type=str, default="historical_proof_runs")
    parser.add_argument("--run-id", type=str, default="multi_window")
    parser.add_argument("--policy", type=str, default="baseline")
    args = parser.parse_args()

    tickers = args.tickers.split(",") if args.tickers else []
    windows = parse_windows(args.windows) if args.windows else DEFAULT_WINDOWS

    from exit_policy import get_policy
    exit_policy = get_policy(args.policy)

    print(f"Running {len(windows)} windows with {exit_policy.label()} policy")
    for label, start, end in windows:
        print(f"  {label}: {start} to {end}")

    from historical_backfill import run_backfill
    from historical_regeneration import run_regeneration, open_regeneration_db, close_regeneration_db
    from historical_evaluation import run_historical_evaluation
    from historical_report import generate_proof_pack

    window_results = []

    for idx, (label, bf_start, bf_end) in enumerate(windows):
        eval_start = bf_start + timedelta(days=60)
        print(f"\n{'=' * 50}")
        print(f"Window {label}: {bf_start} to {bf_end} (eval from {eval_start})")
        print(f"{'=' * 50}")

        config = HistoricalEvalConfig(
            run_id=f"{args.run_id}_{label}",
            mode=HistoricalRunMode.USEFULNESS_RUN,
            tickers=tickers,
            backfill_start=bf_start,
            backfill_end=bf_end,
            eval_start=eval_start,
            eval_end=bf_end,
            cadence_days=args.cadence,
            use_llm=not args.no_llm,
            output_dir=args.output_dir,
        )

        # Backfill
        print(f"  Backfilling {label}...")
        with get_session() as session:
            run_backfill(session, config)

        # Regenerate
        print(f"  Regenerating {label}...")
        with get_session() as source_session:
            regen_result = run_regeneration(source_session, config)
        print(f"    {regen_result.total_documents} docs, {regen_result.total_thesis_updates} updates")

        # Evaluate
        print(f"  Evaluating {label}...")
        regen_session = open_regeneration_db(regen_result.db_path)
        try:
            eval_result = run_historical_evaluation(regen_session, config, exit_policy=exit_policy)
        finally:
            close_regeneration_db(regen_session)

        # Generate per-window proof pack
        generate_proof_pack(config, regen_result, eval_result)

        # Collect results
        m = eval_result.metrics
        diag = eval_result.deterioration_diagnostics
        d = eval_result.diagnostics

        wr = WindowResult(
            window_label=label,
            start_date=eval_start,
            end_date=bf_end,
            return_pct=m.total_return_pct if m else None,
            annualized_return_pct=m.annualized_return_pct if m else None,
            max_drawdown_pct=m.max_drawdown_pct if m else None,
            total_actions=sum(d.action_counts.values()) if d else 0,
            initiation_count=d.action_counts.get("initiate", 0) if d else 0,
            exit_count=d.action_counts.get("exit", 0) if d else 0,
            probation_count=d.action_counts.get("probation", 0) if d else 0,
            premature_exits=diag.premature_exits_60d if diag else 0,
        )
        window_results.append(wr)

        if m:
            print(f"    Return: {m.total_return_pct:+.2f}%  Drawdown: {m.max_drawdown_pct:.2f}%")

    # Aggregate
    mw = aggregate_multi_window(window_results)

    # Write outputs
    output_dir = os.path.join(args.output_dir, args.run_id)
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    write_window_summary_csv(output_dir, mw)

    # Write markdown
    md_lines = ["# Multi-Window Empirical Summary", ""]
    md_lines.append(f"Policy: {exit_policy.label()}")
    md_lines.append(f"Extractor: {'real_llm' if not args.no_llm else 'stub'}")
    md_lines.append("")
    md_lines.extend(format_multi_window_section(mw))

    with open(os.path.join(output_dir, "multi_window_report.md"), "w") as f:
        f.write("\n".join(md_lines))

    import json
    with open(os.path.join(output_dir, "multi_window_summary.json"), "w") as f:
        json.dump(mw.to_dict(), f, indent=2, default=str)

    # Print summary
    print("\n" + "=" * 70)
    print("Multi-Window Summary")
    print("=" * 70)
    for w in mw.windows:
        ret = f"{w.return_pct:+.2f}%" if w.return_pct is not None else "N/A"
        print(f"  {w.window_label}: {w.start_date} to {w.end_date}  return={ret}  exits={w.exit_count}")
    if mw.aggregate:
        print(f"\n  Avg return: {mw.aggregate.get('avg_return_pct', 'N/A')}%")
        print(f"  Return spread: {mw.aggregate.get('return_spread_pct', 'N/A')}%")
    if mw.warnings:
        print("\n  Warnings:")
        for w in mw.warnings:
            print(f"    - {w}")
    print(f"\n  Output: {output_dir}")
    print("=" * 70)


if __name__ == "__main__":
    main()
