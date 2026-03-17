#!/usr/bin/env python
"""Compare old (pre-hardening) vs new (institutional) parameter sets.

Runs two replays against the real database:
  OLD: baseline exit policy, disabled momentum guards
  NEW: graduated exit policy, enabled momentum guards

Usage:
    python scripts/compare_old_vs_new_params.py --start 2025-01-01 --end 2025-12-31
    python scripts/compare_old_vs_new_params.py --start 2025-06-01 --end 2026-03-01 --strict
"""
import argparse
import logging
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from models import Base
from replay_runner import run_replay, format_replay_text
from exit_policy import BASELINE_POLICY, GRADUATED_POLICY
from price_momentum import DISABLED_MOMENTUM_CONFIG, ENABLED_MOMENTUM_CONFIG


def main():
    parser = argparse.ArgumentParser(description="Compare old vs new parameter sets")
    parser.add_argument("--start", type=str, required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--initial-cash", type=float, default=1_000_000.0)
    parser.add_argument("--cadence", type=int, default=7)
    parser.add_argument("--strict", action="store_true", help="Use strict replay mode")
    parser.add_argument("--db", type=str, default=None,
                        help="Database path (default: consensus.db, or use a regen DB)")
    parser.add_argument("--no-core-satellite", action="store_true",
                        help="Disable core-satellite (SPY as cash proxy)")
    parser.add_argument("--core-alloc", type=float, default=95.0,
                        help="Core allocation %% (default: 95)")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)

    db_path = args.db or os.environ.get("DATABASE_URL", "sqlite:///consensus.db")
    db_url = db_path if db_path.startswith("sqlite") else f"sqlite:///{db_path}"
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        core_satellite = not args.no_core_satellite
        core_alloc = args.core_alloc

        # ===== OLD PARAMS: baseline exit, no momentum guards =====
        print("Running OLD params (baseline exit, momentum OFF)...")
        r_old, p_old, m_old = run_replay(
            session,
            start_date=start,
            end_date=end,
            cadence_days=args.cadence,
            initial_cash=args.initial_cash,
            strict_replay=args.strict,
            exit_policy=BASELINE_POLICY,
            momentum_config=DISABLED_MOMENTUM_CONFIG,
            core_satellite=core_satellite,
            core_allocation_pct=core_alloc,
        )

        # ===== NEW PARAMS: graduated exit, momentum guards on =====
        print("Running NEW params (graduated exit, momentum ON)...")
        r_new, p_new, m_new = run_replay(
            session,
            start_date=start,
            end_date=end,
            cadence_days=args.cadence,
            initial_cash=args.initial_cash,
            strict_replay=args.strict,
            exit_policy=GRADUATED_POLICY,
            momentum_config=ENABLED_MOMENTUM_CONFIG,
            core_satellite=core_satellite,
            core_allocation_pct=core_alloc,
        )

    # ===== FULL REPORTS =====
    print()
    print("=" * 80)
    print("OLD PARAMS (Baseline exit, Momentum OFF)")
    print("=" * 80)
    print(format_replay_text(r_old, p_old, m_old))

    print()
    print("=" * 80)
    print("NEW PARAMS (Graduated exit, Momentum ON)")
    print("=" * 80)
    print(format_replay_text(r_new, p_new, m_new))

    # ===== SIDE-BY-SIDE DELTA =====
    print()
    print("=" * 80)
    print("DELTA: OLD vs NEW")
    print("=" * 80)

    def delta(old, new, fmt="+.2f", suffix=""):
        diff = new - old
        return f"{old:{fmt[1:]}}{suffix}  ->  {new:{fmt[1:]}}{suffix}  ({diff:{fmt}}{suffix})"

    print()
    print("--- PERFORMANCE ---")
    print(f"  Total return:      {delta(m_old.total_return_pct, m_new.total_return_pct, suffix='%')}")
    if m_old.annualized_return_pct is not None and m_new.annualized_return_pct is not None:
        print(f"  Annualized return: {delta(m_old.annualized_return_pct, m_new.annualized_return_pct, suffix='%')}")
    print(f"  Max drawdown:      {delta(m_old.max_drawdown_pct, m_new.max_drawdown_pct, suffix='%')}")

    print()
    print("--- RISK-ADJUSTED ---")
    if m_old.sharpe_ratio is not None and m_new.sharpe_ratio is not None:
        print(f"  Sharpe ratio:      {delta(m_old.sharpe_ratio, m_new.sharpe_ratio)}")
    if m_old.sortino_ratio is not None and m_new.sortino_ratio is not None:
        print(f"  Sortino ratio:     {delta(m_old.sortino_ratio, m_new.sortino_ratio)}")
    if m_old.calmar_ratio is not None and m_new.calmar_ratio is not None:
        print(f"  Calmar ratio:      {delta(m_old.calmar_ratio, m_new.calmar_ratio)}")
    if m_old.win_rate_pct is not None and m_new.win_rate_pct is not None:
        print(f"  Win rate:          {delta(m_old.win_rate_pct, m_new.win_rate_pct, suffix='%')}")
    if m_old.profit_factor is not None and m_new.profit_factor is not None:
        print(f"  Profit factor:     {delta(m_old.profit_factor, m_new.profit_factor)}")

    print()
    print("--- ACTIVITY ---")
    print(f"  Initiations:  {m_old.total_initiations:3d}  ->  {m_new.total_initiations:3d}")
    print(f"  Adds:         {m_old.total_adds:3d}  ->  {m_new.total_adds:3d}")
    print(f"  Trims:        {m_old.total_trims:3d}  ->  {m_new.total_trims:3d}")
    print(f"  Exits:        {m_old.total_exits:3d}  ->  {m_new.total_exits:3d}")
    print(f"  Holds:        {m_old.total_holds:3d}  ->  {m_new.total_holds:3d}")
    print(f"  Blocked:      {m_old.total_blocked:3d}  ->  {m_new.total_blocked:3d}")

    print()
    print("--- TURNOVER ---")
    print(f"  Total turnover:    {delta(m_old.total_turnover_pct, m_new.total_turnover_pct, suffix='%')}")
    print(f"  Avg per review:    {delta(m_old.avg_turnover_per_review_pct, m_new.avg_turnover_per_review_pct, suffix='%')}")

    print()
    print("--- CASH EXPOSURE ---")
    print(f"  Avg cash:   {delta(m_old.avg_cash_pct, m_new.avg_cash_pct, suffix='%')}")
    print(f"  Min cash:   {delta(m_old.min_cash_pct, m_new.min_cash_pct, suffix='%')}")
    print(f"  Max cash:   {delta(m_old.max_cash_pct, m_new.max_cash_pct, suffix='%')}")

    print()
    print("--- DISCIPLINE ---")
    print(f"  Funded pairings:   {m_old.funded_pairing_count:3d}  ->  {m_new.funded_pairing_count:3d}")
    print(f"  Turnover blocked:  {m_old.turnover_cap_blocked_count:3d}  ->  {m_new.turnover_cap_blocked_count:3d}")
    if m_old.avg_initiation_conviction is not None and m_new.avg_initiation_conviction is not None:
        print(f"  Avg init conviction: {m_old.avg_initiation_conviction:.0f}  ->  {m_new.avg_initiation_conviction:.0f}")

    # Final portfolio comparison
    if p_old.snapshots and p_new.snapshots:
        old_final = p_old.snapshots[-1]
        new_final = p_new.snapshots[-1]
        print()
        print("--- FINAL PORTFOLIO ---")
        print(f"  Value:     ${old_final.total_value:>12,.2f}  ->  ${new_final.total_value:>12,.2f}")
        print(f"  Cash:      ${old_final.cash:>12,.2f}  ->  ${new_final.cash:>12,.2f}")
        print(f"  Positions: {old_final.num_positions:>12d}  ->  {new_final.num_positions:>12d}")

        print()
        # Combine all tickers from both portfolios
        all_tickers = sorted(
            set(old_final.weights.keys()) | set(new_final.weights.keys()),
            key=lambda t: -(new_final.weights.get(t, 0)),
        )
        if all_tickers:
            print("  Ticker      OLD wt%   NEW wt%   Delta")
            print("  " + "-" * 42)
            for t in all_tickers:
                ow = old_final.weights.get(t, 0)
                nw = new_final.weights.get(t, 0)
                d = nw - ow
                marker = " <-" if abs(d) > 2.0 else ""
                print(f"  {t:8s}  {ow:7.1f}%  {nw:7.1f}%  {d:+6.1f}%{marker}")

    print()
    print("=" * 80)
    print("KEY CHANGES: graduated exit (sharp drop >15pt = exit), momentum guards")
    print("(stop-loss -30%, trailing stop -30%, SMA guard, underwater add block)")
    print("=" * 80)


if __name__ == "__main__":
    main()
