"""Policy comparison runner: run the same usefulness test with different exit policies.

Usage:
    # Compare all 3 policies on default universe with stub extractor
    python scripts/run_policy_comparison.py --start 2025-06-01 --end 2026-01-01

    # With real LLM extractor
    python scripts/run_policy_comparison.py --start 2025-06-01 --end 2026-01-01 --use-llm

    # Specific policies only
    python scripts/run_policy_comparison.py --start 2025-06-01 --end 2026-01-01 --policies baseline,patient

    # Custom tickers
    python scripts/run_policy_comparison.py --start 2025-06-01 --end 2026-01-01 --tickers AAPL,NVDA,MSFT
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

sys.path.insert(0, ".")

from db import get_session
from exit_policy import get_policy, ALL_POLICIES, ExitPolicyConfig
from historical_eval_config import HistoricalEvalConfig, HistoricalRunMode
from empirical_diagnostics import (
    compute_deterioration_diagnostics,
    build_policy_comparison,
    write_policy_comparison_csv,
    format_policy_comparison_section,
    DeteriorationDiagnostics,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Compare exit policy variants")
    parser.add_argument("--start", type=str, default="2025-06-01")
    parser.add_argument("--end", type=str, default="2026-01-01")
    parser.add_argument("--eval-start", type=str, default=None)
    parser.add_argument("--cadence", type=int, default=7)
    parser.add_argument("--tickers", type=str, default=None)
    parser.add_argument("--use-llm", action="store_true")
    parser.add_argument("--policies", type=str, default=None,
                        help="Comma-separated policy names (default: all)")
    parser.add_argument("--output-dir", type=str, default="historical_proof_runs")
    parser.add_argument("--run-id", type=str, default="policy_comparison")
    args = parser.parse_args()

    backfill_start = date.fromisoformat(args.start)
    backfill_end = date.fromisoformat(args.end)
    eval_start = date.fromisoformat(args.eval_start) if args.eval_start else backfill_start + __import__("datetime").timedelta(days=60)
    tickers = args.tickers.split(",") if args.tickers else []

    if args.policies:
        policy_names = args.policies.split(",")
        policies = [get_policy(name.strip()) for name in policy_names]
    else:
        policies = list(ALL_POLICIES)

    print(f"Comparing {len(policies)} exit policies: {[p.label() for p in policies]}")

    # Step 1: Shared backfill
    config = HistoricalEvalConfig(
        run_id=args.run_id,
        mode=HistoricalRunMode.USEFULNESS_RUN,
        tickers=tickers,
        backfill_start=backfill_start,
        backfill_end=backfill_end,
        eval_start=eval_start,
        eval_end=backfill_end,
        cadence_days=args.cadence,
        use_llm=args.use_llm,
        output_dir=args.output_dir,
    )

    from historical_backfill import run_backfill
    print("Step 1: Backfilling historical data...")
    with get_session() as session:
        run_backfill(session, config)

    # Step 2: Shared regeneration (once — policies only affect replay)
    from historical_regeneration import run_regeneration, open_regeneration_db, close_regeneration_db
    print("Step 2: Regenerating thesis state...")
    with get_session() as source_session:
        regen_result = run_regeneration(source_session, config)
    print(f"  {regen_result.total_documents} docs, {regen_result.total_thesis_updates} thesis updates")

    # Step 3: Evaluate each policy
    from historical_evaluation import run_historical_evaluation
    policy_eval_results = {}
    policy_diags = {}

    for policy in policies:
        label = policy.label()
        print(f"Step 3: Evaluating with {label} exit policy...")
        regen_session = open_regeneration_db(regen_result.db_path)
        try:
            eval_result = run_historical_evaluation(regen_session, config, exit_policy=policy)
            policy_eval_results[label] = eval_result
            if eval_result.deterioration_diagnostics:
                policy_diags[label] = eval_result.deterioration_diagnostics
            else:
                policy_diags[label] = compute_deterioration_diagnostics(eval_result.action_outcomes)
        finally:
            close_regeneration_db(regen_session)

    # Step 4: Build comparison
    comparison = build_policy_comparison(policy_eval_results, policy_diags)

    # Step 5: Write outputs
    import os
    from pathlib import Path
    output_dir = os.path.join(args.output_dir, args.run_id)
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    write_policy_comparison_csv(output_dir, comparison)

    # Write per-policy proof packs
    from historical_report import generate_proof_pack
    for label, eval_result in policy_eval_results.items():
        policy_dir = os.path.join(output_dir, f"policy_{label}")
        Path(policy_dir).mkdir(parents=True, exist_ok=True)
        policy_config = HistoricalEvalConfig(
            run_id=f"{args.run_id}_{label}",
            mode=HistoricalRunMode.USEFULNESS_RUN,
            tickers=tickers,
            backfill_start=backfill_start,
            backfill_end=backfill_end,
            eval_start=eval_start,
            eval_end=backfill_end,
            cadence_days=args.cadence,
            use_llm=args.use_llm,
            output_dir=output_dir,
        )
        generate_proof_pack(policy_config, regen_result, eval_result)

    # Write comparison markdown
    md_lines = ["# Exit Policy Comparison Report", ""]
    md_lines.append(f"Window: {backfill_start} to {backfill_end}")
    md_lines.append(f"Eval: {eval_start} to {backfill_end}")
    md_lines.append(f"Policies: {', '.join(p.label() for p in policies)}")
    md_lines.append(f"Extractor: {'real_llm' if args.use_llm else 'stub'}")
    md_lines.append("")
    md_lines.extend(format_policy_comparison_section(comparison))

    with open(os.path.join(output_dir, "comparison_report.md"), "w") as f:
        f.write("\n".join(md_lines))

    # Print summary
    print("\n" + "=" * 70)
    print("Exit Policy Comparison")
    print("=" * 70)
    for label in sorted(comparison.policy_results.keys()):
        r = comparison.policy_results[label]
        ret = f"{r['return_pct']:+.2f}%" if r.get('return_pct') is not None else "N/A"
        exits = r.get('exit_count', 0)
        probs = r.get('probation_count', 0)
        prem = r.get('premature_exits_60d', 0)
        print(f"  {label:12s}  return={ret}  exits={exits}  probations={probs}  premature={prem}")
    print(f"\n  Output: {output_dir}")
    print("=" * 70)


if __name__ == "__main__":
    main()
