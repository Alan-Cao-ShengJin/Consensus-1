"""Historical proof run CLI: backfill, regenerate, evaluate, and report.

Usage:
    # Default narrow-universe usefulness run (15 names, stub extractor)
    python scripts/run_historical_proof.py --usefulness-run

    # Usefulness run with real LLM extraction
    python scripts/run_historical_proof.py --usefulness-run --use-llm

    # Usefulness run with memory ablation
    python scripts/run_historical_proof.py --usefulness-run --memory-ablation

    # Custom tickers usefulness run
    python scripts/run_historical_proof.py --usefulness-run --tickers AAPL,MSFT,NVDA

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
import os
import sys
from datetime import date

# Add project root to path
sys.path.insert(0, ".")

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

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
    parser.add_argument("--run-id", type=str, default=None, help="Run identifier (auto-generated if omitted)")
    parser.add_argument("--output-dir", type=str, default="historical_proof_runs", help="Output directory")
    parser.add_argument("--benchmark", type=str, default="SPY", help="Benchmark ticker")
    parser.add_argument("--strict", action="store_true", help="Use strict replay mode")
    parser.add_argument("--no-llm", action="store_true", help="Disable LLM, use stub extractor")

    # Mode flags
    parser.add_argument("--usefulness-run", action="store_true",
                        help="Bounded real usefulness test (narrow proof universe, full diagnostics)")
    parser.add_argument("--backfill-only", action="store_true", help="Only run backfill (no regeneration)")
    parser.add_argument("--evaluate-only", action="store_true", help="Evaluate existing regeneration DB")
    parser.add_argument("--memory-ablation", action="store_true", help="Run memory ON vs OFF comparison")
    parser.add_argument("--regen-db", type=str, default=None, help="Path to existing regeneration DB")

    # Source toggles
    parser.add_argument("--no-sec", action="store_true", help="Skip SEC filing backfill")
    parser.add_argument("--no-news", action="store_true", help="Skip news RSS backfill")
    parser.add_argument("--no-pr", action="store_true", help="Skip PR RSS backfill")
    parser.add_argument("--no-prices", action="store_true", help="Skip price backfill")
    parser.add_argument("--no-finnhub", action="store_true", help="Skip Finnhub news backfill")
    parser.add_argument("--momentum-guards", action="store_true",
                        help="Enable price momentum guards (SMA, stop-loss, trailing stop, regime filter)")
    parser.add_argument("--core-satellite", action="store_true",
                        help="Core-satellite mode: start 95%% in SPY, swap into picks")
    parser.add_argument("--core-pct", type=float, default=95.0,
                        help="Core allocation %% (default 95)")
    parser.add_argument("--smart-signals", action="store_true",
                        help="Enable conviction decay + market sentiment + priced-in detection")
    parser.add_argument("--conviction-decay", action="store_true",
                        help="Enable conviction decay only (stale conviction erosion)")
    parser.add_argument("--market-sentiment", action="store_true",
                        help="Enable market sentiment only (VIX/yield curve/regime gating)")

    args = parser.parse_args()

    backfill_start = date.fromisoformat(args.start)
    backfill_end = date.fromisoformat(args.end)
    eval_start = date.fromisoformat(args.eval_start) if args.eval_start else backfill_start + __import__("datetime").timedelta(days=60)

    tickers = args.tickers.split(",") if args.tickers else []

    if args.usefulness_run:
        if args.memory_ablation:
            _run_usefulness_ablation(args, tickers, backfill_start, backfill_end, eval_start)
        else:
            _run_usefulness(args, tickers, backfill_start, backfill_end, eval_start)
    elif args.memory_ablation:
        _run_memory_ablation(args, tickers, backfill_start, backfill_end, eval_start)
    elif args.backfill_only:
        _run_backfill_only(args, tickers, backfill_start, backfill_end)
    elif args.evaluate_only:
        _run_evaluate_only(args, tickers, backfill_start, backfill_end, eval_start)
    else:
        _run_full_proof(args, tickers, backfill_start, backfill_end, eval_start)


def _build_signal_configs(args):
    """Build sentiment and decay configs from CLI args."""
    from market_sentiment import DISABLED_SENTIMENT_CONFIG, DEFAULT_SENTIMENT_CONFIG
    from conviction_decay import DISABLED_DECAY_CONFIG, DEFAULT_DECAY_CONFIG

    smart = getattr(args, 'smart_signals', False)
    sentiment_cfg = DEFAULT_SENTIMENT_CONFIG if (smart or getattr(args, 'market_sentiment', False)) else DISABLED_SENTIMENT_CONFIG
    decay_cfg = DEFAULT_DECAY_CONFIG if (smart or getattr(args, 'conviction_decay', False)) else DISABLED_DECAY_CONFIG

    if sentiment_cfg.enabled:
        print("  Market sentiment: ENABLED (VIX, yield curve, DXY, regime gating)")
    if decay_cfg.enabled:
        print("  Conviction decay: ENABLED (stale conviction erosion)")

    return sentiment_cfg, decay_cfg


def _build_config(args, tickers, backfill_start, backfill_end, eval_start, mode=None) -> HistoricalEvalConfig:
    run_id = args.run_id or ("usefulness_run" if mode == HistoricalRunMode.USEFULNESS_RUN else "historical_proof")
    return HistoricalEvalConfig(
        run_id=run_id,
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
        backfill_finnhub=not getattr(args, 'no_finnhub', False),
        use_llm=not args.no_llm,
        strict_replay=args.strict,
        benchmark_ticker=args.benchmark,
        output_dir=args.output_dir,
    )


def _run_usefulness(args, tickers, backfill_start, backfill_end, eval_start):
    """Run bounded real usefulness test with full diagnostics."""
    config = _build_config(args, tickers, backfill_start, backfill_end, eval_start,
                           mode=HistoricalRunMode.USEFULNESS_RUN)

    # Validate and print warnings prominently
    validation_warnings = config.validate_for_usefulness_run()
    if validation_warnings:
        print("\n" + "!" * 60)
        print("USEFULNESS RUN WARNINGS:")
        for w in validation_warnings:
            print(f"  {w}")
        print("!" * 60 + "\n")

    from proof_universe import get_proof_universe_rationale
    print(f"Universe: {len(config.effective_tickers())} tickers")
    print(f"Rationale: {get_proof_universe_rationale()}")
    print(f"Extractor: {config.extractor_mode_label()}")
    print()

    from historical_backfill import run_backfill
    from historical_regeneration import run_regeneration, open_regeneration_db, close_regeneration_db
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
    print("Step 3/4: Running historical evaluation with usefulness diagnostics...")

    # Build momentum config if requested
    from price_momentum import DISABLED_MOMENTUM_CONFIG, ENABLED_MOMENTUM_CONFIG
    momentum_cfg = ENABLED_MOMENTUM_CONFIG if getattr(args, 'momentum_guards', False) else DISABLED_MOMENTUM_CONFIG
    if momentum_cfg.enabled:
        print("  Momentum guards: ENABLED (SMA, stop-loss, trailing stop, regime filter)")

    sentiment_cfg, decay_cfg = _build_signal_configs(args)

    regen_session = open_regeneration_db(regen_result.db_path)
    try:
        eval_result = run_historical_evaluation(
            regen_session, config, momentum_config=momentum_cfg,
            core_satellite=getattr(args, 'core_satellite', False),
            core_allocation_pct=getattr(args, 'core_pct', 95.0),
            sentiment_config=sentiment_cfg,
            decay_config=decay_cfg,
        )
    finally:
        close_regeneration_db(regen_session)

    # Step 4: Report
    print("Step 4/4: Generating proof pack with usefulness tables...")
    output_dir = generate_proof_pack(config, regen_result, eval_result)

    _print_usefulness_summary(config, regen_result, eval_result, output_dir)


def _run_usefulness_ablation(args, tickers, backfill_start, backfill_end, eval_start):
    """Run usefulness test with memory ablation."""
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
    config_on.use_llm = not args.no_llm
    config_off.use_llm = not args.no_llm
    # Override mode to usefulness run
    config_on.mode = HistoricalRunMode.USEFULNESS_RUN
    config_off.mode = HistoricalRunMode.USEFULNESS_RUN

    # Validate
    validation_warnings = config_on.validate_for_usefulness_run()
    if validation_warnings:
        print("\n" + "!" * 60)
        print("USEFULNESS RUN WARNINGS:")
        for w in validation_warnings:
            print(f"  {w}")
        print("!" * 60 + "\n")

    # Backfill once
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
        run_id="usefulness_ablation",
        output_dir=args.output_dir,
        mode=HistoricalRunMode.USEFULNESS_RUN,
        use_llm=not args.no_llm,
    )
    output_dir = generate_proof_pack(
        ablation_config, None,
        comparison.eval_on,
        memory_comparison=comparison,
    )

    _print_ablation_summary(comparison, output_dir)


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
    from historical_regeneration import run_regeneration, open_regeneration_db, close_regeneration_db
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
    from price_momentum import DISABLED_MOMENTUM_CONFIG, ENABLED_MOMENTUM_CONFIG
    momentum_cfg = ENABLED_MOMENTUM_CONFIG if getattr(args, 'momentum_guards', False) else DISABLED_MOMENTUM_CONFIG
    sentiment_cfg, decay_cfg = _build_signal_configs(args)
    regen_session = open_regeneration_db(regen_result.db_path)
    try:
        eval_result = run_historical_evaluation(
            regen_session, config, momentum_config=momentum_cfg,
            core_satellite=getattr(args, 'core_satellite', False),
            core_allocation_pct=getattr(args, 'core_pct', 95.0),
            sentiment_config=sentiment_cfg,
            decay_config=decay_cfg,
        )
    finally:
        close_regeneration_db(regen_session)

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

    from historical_regeneration import open_regeneration_db, close_regeneration_db
    from historical_evaluation import run_historical_evaluation
    from historical_report import generate_proof_pack
    from price_momentum import DISABLED_MOMENTUM_CONFIG, ENABLED_MOMENTUM_CONFIG
    momentum_cfg = ENABLED_MOMENTUM_CONFIG if getattr(args, 'momentum_guards', False) else DISABLED_MOMENTUM_CONFIG

    sentiment_cfg, decay_cfg = _build_signal_configs(args)
    regen_session = open_regeneration_db(args.regen_db)
    try:
        eval_result = run_historical_evaluation(
            regen_session, config, momentum_config=momentum_cfg,
            core_satellite=getattr(args, 'core_satellite', False),
            core_allocation_pct=getattr(args, 'core_pct', 95.0),
            sentiment_config=sentiment_cfg,
            decay_config=decay_cfg,
        )
    finally:
        close_regeneration_db(regen_session)

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
    config_on.use_llm = not args.no_llm
    config_off.use_llm = not args.no_llm

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


def _print_usefulness_summary(config, regen_result, eval_result, output_dir):
    """Print usefulness-specific summary with degraded flags and failure highlights."""
    _print_summary(config, regen_result, eval_result, output_dir)

    # Additional usefulness-specific info
    if eval_result:
        if eval_result.best_decisions:
            print("\n  Best decision:")
            bd = eval_result.best_decisions[0]
            f20 = f"{bd['forward_20d_pct']:+.2f}%" if bd.get('forward_20d_pct') is not None else "N/A"
            print(f"    {bd['review_date']} {bd['ticker']} {bd['action']} -> 20D: {f20}")

        if eval_result.worst_decisions:
            print("  Worst decision:")
            wd = eval_result.worst_decisions[0]
            f20 = f"{wd['forward_20d_pct']:+.2f}%" if wd.get('forward_20d_pct') is not None else "N/A"
            print(f"    {wd['review_date']} {wd['ticker']} {wd['action']} -> 20D: {f20}")

        if eval_result.failure_analysis and eval_result.failure_analysis.degraded_flags:
            print("\n  Degraded flags:")
            for flag in eval_result.failure_analysis.degraded_flags:
                print(f"    - {flag}")

    print()


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
