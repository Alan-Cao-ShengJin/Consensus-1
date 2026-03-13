"""Historical proof run CLI: backfill, regenerate, evaluate, and report.

Usage:
    # Full proof run (backfill + regenerate + evaluate + report)
    python scripts/run_historical_proof.py --start 2024-06-01 --end 2025-01-01

    # Backfill only
    python scripts/run_historical_proof.py --start 2024-06-01 --end 2025-01-01 --backfill-only

    # Evaluate on existing regeneration DB
    python scripts/run_historical_proof.py --evaluate-only --regen-db path/to/regen.db

    # Memory ablation
    python scripts/run_historical_proof.py --start 2024-06-01 --end 2025-01-01 --memory-ablation

    # Subset of tickers
    python scripts/run_historical_proof.py --start 2024-06-01 --end 2025-01-01 --tickers AAPL,MSFT,NVDA

    # Custom run ID and output
    python scripts/run_historical_proof.py --start 2024-06-01 --end 2025-01-01 --run-id my_proof
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

# Add project root to path
sys.path.insert(0, ".")

from db import get_session
from historical_eval_config import HistoricalEvalConfig, HistoricalRunMode

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Run historical proof run")
    parser.add_argument("--start", type=str, default="2024-06-01", help="Backfill start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, default="2025-01-01", help="Backfill end date (YYYY-MM-DD)")
    parser.add_argument("--eval-start", type=str, default=None, help="Eval start (defaults to start + 60d)")
    parser.add_argument("--cadence", type=int, default=7, help="Review cadence in days")
    parser.add_argument("--initial-cash", type=float, default=1_000_000, help="Initial portfolio cash")
    parser.add_argument("--tickers", type=str, default=None, help="Comma-separated ticker list")
    parser.add_argument("--run-id", type=str, default="historical_proof", help="Run identifier")
    parser.add_argument("--output-dir", type=str, default="historical_proof_runs", help="Output directory")
    parser.add_argument("--benchmark", type=str, default="SPY", help="Benchmark ticker")
    parser.add_argument("--strict", action="store_true", help="Use strict replay mode")
    parser.add_argument("--use-llm", action="store_true", help="Use LLM for claim extraction")

    # Mode flags
    parser.add_argument("--backfill-only", action="store_true", help="Only run backfill (no regeneration)")
    parser.add_argument("--evaluate-only", action="store_true", help="Evaluate existing regeneration DB")
    parser.add_argument("--memory-ablation", action="store_true", help="Run memory ON vs OFF comparison")
    parser.add_argument("--regen-db", type=str, default=None, help="Path to existing regeneration DB")

    # Source toggles
    parser.add_argument("--no-sec", action="store_true", help="Skip SEC filing backfill")
    parser.add_argument("--no-news", action="store_true", help="Skip news RSS backfill")
    parser.add_argument("--no-pr", action="store_true", help="Skip PR RSS backfill")
    parser.add_argument("--no-prices", action="store_true", help="Skip price backfill")

    args = parser.parse_args()

    backfill_start = date.fromisoformat(args.start)
    backfill_end = date.fromisoformat(args.end)
    eval_start = date.fromisoformat(args.eval_start) if args.eval_start else backfill_start + __import__("datetime").timedelta(days=60)

    tickers = args.tickers.split(",") if args.tickers else []

    if args.memory_ablation:
        _run_memory_ablation(args, tickers, backfill_start, backfill_end, eval_start)
    elif args.backfill_only:
        _run_backfill_only(args, tickers, backfill_start, backfill_end)
    elif args.evaluate_only:
        _run_evaluate_only(args, tickers, backfill_start, backfill_end, eval_start)
    else:
        _run_full_proof(args, tickers, backfill_start, backfill_end, eval_start)


def _build_config(args, tickers, backfill_start, backfill_end, eval_start, mode=None) -> HistoricalEvalConfig:
    return HistoricalEvalConfig(
        run_id=args.run_id,
        run_label=f"Historical proof: {backfill_start} to {backfill_end}",
        mode=mode or HistoricalRunMode.REGENERATE,
        tickers=tickers,
        backfill_start=backfill_start,
        backfill_end=backfill_end,
        eval_start=eval_start,
        eval_end=backfill_end,
        cadence_days=args.cadence,
        initial_cash=args.initial_cash,
        backfill_prices=not args.no_prices,
        backfill_sec_filings=not args.no_sec,
        backfill_news_rss=not args.no_news,
        backfill_pr_rss=not args.no_pr,
        use_llm=args.use_llm,
        strict_replay=args.strict,
        benchmark_ticker=args.benchmark,
        output_dir=args.output_dir,
    )


def _run_backfill_only(args, tickers, backfill_start, backfill_end):
    config = _build_config(args, tickers, backfill_start, backfill_end, backfill_start,
                           mode=HistoricalRunMode.BACKFILL_ONLY)

    from historical_backfill import run_backfill

    with get_session() as session:
        result = run_backfill(session, config)

    print("\n" + "=" * 60)
    print("Backfill Complete")
    print("=" * 60)
    for sr in result.source_results:
        print(f"  {sr.source}: {sr.rows_upserted} rows, {sr.docs_inserted} docs, "
              f"{sr.tickers_failed} failures")
    print(f"  Total errors: {result.total_errors}")
    print(f"  Total warnings: {result.total_warnings}")
    print("=" * 60)


def _run_full_proof(args, tickers, backfill_start, backfill_end, eval_start):
    config = _build_config(args, tickers, backfill_start, backfill_end, eval_start)

    from historical_backfill import run_backfill
    from historical_regeneration import run_regeneration, open_regeneration_db
    from historical_evaluation import run_historical_evaluation
    from historical_report import generate_proof_pack

    # Step 1: Backfill
    print("Step 1/4: Backfilling historical data...")
    with get_session() as session:
        backfill_result = run_backfill(session, config)

    print(f"  Backfill: {backfill_result.total_errors} errors, {backfill_result.total_warnings} warnings")

    # Step 2: Regenerate
    print("Step 2/4: Regenerating thesis state chronologically...")
    with get_session() as source_session:
        regen_result = run_regeneration(source_session, config)

    print(f"  Regeneration: {regen_result.total_documents} docs, "
          f"{regen_result.total_thesis_updates} thesis updates, "
          f"{regen_result.total_state_changes} state changes")

    # Step 3: Evaluate
    print("Step 3/4: Running historical evaluation...")
    regen_session = open_regeneration_db(regen_result.db_path)
    try:
        eval_result = run_historical_evaluation(regen_session, config)
    finally:
        regen_session.close()

    # Step 4: Report
    print("Step 4/4: Generating proof pack...")
    output_dir = generate_proof_pack(config, regen_result, eval_result)

    _print_summary(config, regen_result, eval_result, output_dir)


def _run_evaluate_only(args, tickers, backfill_start, backfill_end, eval_start):
    config = _build_config(args, tickers, backfill_start, backfill_end, eval_start,
                           mode=HistoricalRunMode.EVALUATE_ONLY)

    if not args.regen_db:
        print("Error: --evaluate-only requires --regen-db path")
        sys.exit(1)

    from historical_regeneration import open_regeneration_db
    from historical_evaluation import run_historical_evaluation
    from historical_report import generate_proof_pack

    regen_session = open_regeneration_db(args.regen_db)
    try:
        eval_result = run_historical_evaluation(regen_session, config)
    finally:
        regen_session.close()

    output_dir = generate_proof_pack(config, None, eval_result)
    _print_eval_summary(eval_result, output_dir)


def _run_memory_ablation(args, tickers, backfill_start, backfill_end, eval_start):
    from historical_eval_config import HistoricalEvalConfig
    from historical_backfill import run_backfill
    from historical_evaluation import run_historical_memory_ablation
    from historical_report import generate_proof_pack

    config_on, config_off = HistoricalEvalConfig.memory_ablation_pair(
        tickers=tickers or None,
        backfill_start=backfill_start,
        backfill_end=backfill_end,
        eval_start=eval_start,
        eval_end=backfill_end,
        cadence_days=args.cadence,
    )
    config_on.output_dir = args.output_dir
    config_off.output_dir = args.output_dir
    config_on.use_llm = args.use_llm
    config_off.use_llm = args.use_llm

    # Backfill once (shared data)
    print("Step 1/3: Backfilling historical data...")
    with get_session() as session:
        run_backfill(session, config_on)

    # Run ablation
    print("Step 2/3: Running memory ON vs OFF regeneration + evaluation...")
    with get_session() as source_session:
        comparison = run_historical_memory_ablation(source_session, config_on, config_off)

    # Report
    print("Step 3/3: Generating proof pack...")
    ablation_config = HistoricalEvalConfig(
        run_id="memory_ablation",
        output_dir=args.output_dir,
        mode=HistoricalRunMode.MEMORY_ABLATION,
    )
    output_dir = generate_proof_pack(
        ablation_config, None,
        comparison.eval_on,
        memory_comparison=comparison,
    )

    _print_ablation_summary(comparison, output_dir)


def _print_summary(config, regen_result, eval_result, output_dir):
    m = eval_result.metrics if eval_result else None

    print("\n" + "=" * 60)
    print(f"Historical Proof Run: {config.run_id}")
    print("=" * 60)
    if regen_result:
        print(f"  Documents:      {regen_result.total_documents}")
        print(f"  Claims:         {regen_result.total_claims}")
        print(f"  Thesis updates: {regen_result.total_thesis_updates}")
        print(f"  State changes:  {regen_result.total_state_changes}")
    if m:
        print(f"  Return:         {m.total_return_pct:+.2f}%")
        print(f"  Max drawdown:   {m.max_drawdown_pct:.2f}%")
        print(f"  Reviews:        {m.total_review_dates}")
        print(f"  Purity:         {m.purity_level}")
    if eval_result and eval_result.benchmark and eval_result.benchmark.excess_return_pct is not None:
        print(f"  vs SPY:         {eval_result.benchmark.excess_return_pct:+.2f}%")

    if eval_result and eval_result.forward_return_summary:
        print("\n  Forward Returns by Action:")
        for s in eval_result.forward_return_summary:
            f20 = f"{s.avg_20d:+.2f}%" if s.avg_20d is not None else "N/A"
            print(f"    {s.action:<12} n={s.count:>3}  20D avg: {f20}")

    print(f"\n  Output: {output_dir}")
    print("=" * 60)


def _print_eval_summary(eval_result, output_dir):
    m = eval_result.metrics
    print("\n" + "=" * 60)
    print("Historical Evaluation")
    print("=" * 60)
    if m:
        print(f"  Return:       {m.total_return_pct:+.2f}%")
        print(f"  Max drawdown: {m.max_drawdown_pct:.2f}%")
    print(f"  Output: {output_dir}")
    print("=" * 60)


def _print_ablation_summary(comparison, output_dir):
    mc = comparison.comparison

    print("\n" + "=" * 60)
    print("Memory Ablation: ON vs OFF")
    print("=" * 60)

    if "regeneration" in mc:
        r = mc["regeneration"]
        print(f"  Thesis updates:  ON={r.get('thesis_updates_on', 0)}  OFF={r.get('thesis_updates_off', 0)}")
        print(f"  State changes:   ON={r.get('state_changes_on', 0)}  OFF={r.get('state_changes_off', 0)}")
        print(f"  State flips:     ON={r.get('state_flips_on', 0)}  OFF={r.get('state_flips_off', 0)}")

    if "portfolio" in mc:
        p = mc["portfolio"]
        print(f"  Return:          ON={p.get('return_on_pct', 0):+.2f}%  OFF={p.get('return_off_pct', 0):+.2f}%  delta={p.get('return_delta_pct', 0):+.2f}%")

    print(f"\n  Output: {output_dir}")
    print("=" * 60)


if __name__ == "__main__":
    main()
