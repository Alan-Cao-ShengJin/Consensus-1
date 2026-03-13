#!/usr/bin/env python
"""Run daily vs weekly cadence comparison.

Generates two proof packs (daily + weekly) from the same regen DB,
then produces a cadence_comparison.csv summary.

Usage:
    python scripts/run_cadence_comparison.py --regen-db historical_proof_runs/usefulness_llm_v7_regen.db
    python scripts/run_cadence_comparison.py --regen-db historical_proof_runs/usefulness_llm_v7_regen.db --use-llm
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from historical_eval_config import HistoricalEvalConfig, HistoricalRunMode
from historical_regeneration import open_regeneration_db, close_regeneration_db
from historical_evaluation import run_historical_evaluation
from historical_report import generate_proof_pack

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Compare daily vs weekly cadence")
    parser.add_argument("--regen-db", type=str, required=True,
                        help="Path to existing regeneration DB")
    parser.add_argument("--start", type=str, default="2024-08-01",
                        help="Eval start date")
    parser.add_argument("--end", type=str, default="2025-01-01",
                        help="Eval end date")
    parser.add_argument("--output-dir", type=str, default="historical_proof_runs",
                        help="Output directory")
    parser.add_argument("--use-llm", action="store_true")
    parser.add_argument("--tickers", type=str, default=None)
    args = parser.parse_args()

    eval_start = date.fromisoformat(args.start)
    eval_end = date.fromisoformat(args.end)
    tickers = args.tickers.split(",") if args.tickers else []

    results = {}
    for cadence, label in [(7, "weekly"), (1, "daily")]:
        run_id = f"cadence_{label}"
        print(f"\n{'='*60}")
        print(f"Running {label} cadence (cadence_days={cadence})...")
        print(f"{'='*60}")

        config = HistoricalEvalConfig(
            run_id=run_id,
            run_label=f"Cadence comparison: {label}",
            mode=HistoricalRunMode.EVALUATE_ONLY,
            tickers=tickers,
            eval_start=eval_start,
            eval_end=eval_end,
            cadence_days=cadence,
            use_llm=args.use_llm,
            output_dir=args.output_dir,
        )

        session = open_regeneration_db(args.regen_db)
        try:
            eval_result = run_historical_evaluation(session, config)
        finally:
            close_regeneration_db(session)

        output_dir = generate_proof_pack(config, None, eval_result)
        results[label] = {
            "config": config,
            "eval_result": eval_result,
            "output_dir": output_dir,
        }
        m = eval_result.metrics
        if m:
            print(f"  Return:       {m.total_return_pct:+.2f}%")
            print(f"  Max drawdown: {m.max_drawdown_pct:.2f}%")
            print(f"  Reviews:      {m.total_review_dates}")

    # Generate comparison
    _write_cadence_comparison(args.output_dir, results)


def _write_cadence_comparison(output_dir: str, results: dict):
    """Write cadence_comparison.csv and summary."""
    path = os.path.join(output_dir, "cadence_comparison.csv")
    fieldnames = ["metric", "daily", "weekly", "delta", "daily_better"]

    weekly = results.get("weekly", {}).get("eval_result")
    daily = results.get("daily", {}).get("eval_result")
    if not weekly or not daily:
        print("Missing results, cannot compare")
        return

    mw = weekly.metrics
    md = daily.metrics
    dw = weekly.diagnostics
    dd = daily.diagnostics

    rows = []

    def add_row(metric, dv, wv, higher_better=True):
        if dv is None or wv is None:
            rows.append({"metric": metric, "daily": dv, "weekly": wv, "delta": None, "daily_better": ""})
            return
        delta = dv - wv
        better = delta > 0 if higher_better else delta < 0
        rows.append({
            "metric": metric,
            "daily": round(dv, 2) if isinstance(dv, float) else dv,
            "weekly": round(wv, 2) if isinstance(wv, float) else wv,
            "delta": round(delta, 2) if isinstance(delta, float) else delta,
            "daily_better": "yes" if better else "no",
        })

    if mw and md:
        add_row("total_return_pct", md.total_return_pct, mw.total_return_pct)
        add_row("annualized_return_pct", md.annualized_return_pct, mw.annualized_return_pct)
        add_row("max_drawdown_pct", md.max_drawdown_pct, mw.max_drawdown_pct, higher_better=False)
        add_row("total_review_dates", md.total_review_dates, mw.total_review_dates)
        add_row("total_trades", md.total_trades_applied, mw.total_trades_applied)
        add_row("total_turnover_pct", md.total_turnover_pct, mw.total_turnover_pct, higher_better=False)
        add_row("avg_turnover_per_review", md.avg_turnover_per_review_pct, mw.avg_turnover_per_review_pct, higher_better=False)

    if dw and dd:
        add_row("recommendation_changes", dd.recommendation_changes, dw.recommendation_changes)
        add_row("short_hold_exits", dd.short_hold_exits, dw.short_hold_exits, higher_better=False)

    # Count meaningful changes from the changes CSV if available
    for label, er in [("daily", daily), ("weekly", weekly)]:
        changes_count = 0
        if er and er.action_outcomes:
            changes_count = sum(1 for o in er.action_outcomes if o.action not in ("hold", "probation", "no_action"))
        add_row(f"meaningful_changes_{label}", changes_count, changes_count)

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    print(f"\n{'='*60}")
    print("Cadence Comparison Summary")
    print(f"{'='*60}")
    for row in rows:
        if row["delta"] is not None:
            better_str = " (daily better)" if row["daily_better"] == "yes" else (" (weekly better)" if row["daily_better"] == "no" else "")
            print(f"  {row['metric']:<30} daily={row['daily']:>10}  weekly={row['weekly']:>10}  delta={row['delta']:>10}{better_str}")
    print(f"\nComparison CSV: {path}")
    print(f"Daily proof pack: {results['daily']['output_dir']}")
    print(f"Weekly proof pack: {results['weekly']['output_dir']}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
