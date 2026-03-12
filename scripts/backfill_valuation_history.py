"""Backfill valuation fields on existing ThesisStateHistory records.

Conservative strategy:
  1. For each ThesisStateHistory record with valuation_gap_pct=NULL:
     a. Look for the closest EARLIER history record on the same thesis that
        has valuation_gap_pct populated. If found within 30 days, backfill
        with provenance BACKFILLED_FROM_THESIS_SNAPSHOT.
     b. Otherwise, mark provenance as MISSING.
  2. Never uses the current mutable Thesis.valuation_gap_pct as a historical
     source — that would be fake history.
  3. Reports what was backfilled and what remains missing.

Usage:
    PYTHONPATH=. python scripts/backfill_valuation_history.py [--db URL] [--dry-run] [--max-gap-days 30]
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import timedelta

from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session

from models import (
    Base, Thesis, ThesisStateHistory, ValuationProvenance,
)

logger = logging.getLogger(__name__)

# Maximum gap (in days) between a source record and a target record
# for backfill to be considered defensible.
DEFAULT_MAX_GAP_DAYS = 30


def inspect_coverage(session: Session) -> dict:
    """Report current valuation coverage in ThesisStateHistory.

    Returns a dict with summary stats.
    """
    total = session.scalar(select(func.count(ThesisStateHistory.id)))
    with_val = session.scalar(
        select(func.count(ThesisStateHistory.id))
        .where(ThesisStateHistory.valuation_gap_pct.isnot(None))
    )
    without_val = total - with_val

    with_prov = session.scalar(
        select(func.count(ThesisStateHistory.id))
        .where(ThesisStateHistory.valuation_provenance.isnot(None))
    )

    # Per-thesis breakdown
    thesis_ids = session.scalars(
        select(ThesisStateHistory.thesis_id).distinct()
    ).all()

    per_thesis = []
    for tid in thesis_ids:
        thesis = session.get(Thesis, tid)
        t_total = session.scalar(
            select(func.count(ThesisStateHistory.id))
            .where(ThesisStateHistory.thesis_id == tid)
        )
        t_with = session.scalar(
            select(func.count(ThesisStateHistory.id))
            .where(
                ThesisStateHistory.thesis_id == tid,
                ThesisStateHistory.valuation_gap_pct.isnot(None),
            )
        )
        per_thesis.append({
            "thesis_id": tid,
            "ticker": thesis.company_ticker if thesis else "?",
            "total_records": t_total,
            "with_valuation": t_with,
            "without_valuation": t_total - t_with,
            "coverage_pct": round(100.0 * t_with / t_total, 1) if t_total else 0.0,
        })

    return {
        "total_records": total,
        "with_valuation": with_val,
        "without_valuation": without_val,
        "with_provenance": with_prov,
        "without_provenance": total - with_prov,
        "per_thesis": per_thesis,
    }


def backfill_valuation_history(
    session: Session,
    *,
    max_gap_days: int = DEFAULT_MAX_GAP_DAYS,
    dry_run: bool = False,
) -> dict:
    """Backfill valuation fields on ThesisStateHistory records.

    Returns a summary dict of actions taken.
    """
    stats = {
        "inspected": 0,
        "already_populated": 0,
        "backfilled": 0,
        "marked_missing": 0,
        "provenance_updated": 0,
        "details": [],
    }

    # Get all thesis IDs that have history
    thesis_ids = session.scalars(
        select(ThesisStateHistory.thesis_id).distinct()
    ).all()

    for tid in thesis_ids:
        # Get all history records for this thesis, ordered by created_at
        records = session.scalars(
            select(ThesisStateHistory)
            .where(ThesisStateHistory.thesis_id == tid)
            .order_by(ThesisStateHistory.created_at.asc())
        ).all()

        for rec in records:
            stats["inspected"] += 1

            # Already has valuation — just ensure provenance is set
            if rec.valuation_gap_pct is not None:
                stats["already_populated"] += 1
                if rec.valuation_provenance is None:
                    if not dry_run:
                        rec.valuation_provenance = ValuationProvenance.HISTORICAL_RECORDED.value
                    stats["provenance_updated"] += 1
                    stats["details"].append({
                        "thesis_id": tid,
                        "history_id": rec.id,
                        "action": "provenance_set",
                        "provenance": ValuationProvenance.HISTORICAL_RECORDED.value,
                    })
                continue

            # No valuation — try to backfill from closest earlier record
            source = session.scalars(
                select(ThesisStateHistory)
                .where(
                    ThesisStateHistory.thesis_id == tid,
                    ThesisStateHistory.created_at < rec.created_at,
                    ThesisStateHistory.valuation_gap_pct.isnot(None),
                )
                .order_by(ThesisStateHistory.created_at.desc())
                .limit(1)
            ).first()

            if source is not None:
                gap = rec.created_at - source.created_at
                if gap <= timedelta(days=max_gap_days):
                    if not dry_run:
                        rec.valuation_gap_pct = source.valuation_gap_pct
                        rec.base_case_rerating = source.base_case_rerating
                        rec.valuation_provenance = ValuationProvenance.BACKFILLED_FROM_THESIS_SNAPSHOT.value
                    stats["backfilled"] += 1
                    stats["details"].append({
                        "thesis_id": tid,
                        "history_id": rec.id,
                        "action": "backfilled",
                        "source_history_id": source.id,
                        "gap_days": gap.days,
                        "valuation_gap_pct": source.valuation_gap_pct,
                        "base_case_rerating": source.base_case_rerating,
                    })
                    continue

            # No defensible source — mark as missing
            if not dry_run:
                rec.valuation_provenance = ValuationProvenance.MISSING.value
            stats["marked_missing"] += 1
            stats["details"].append({
                "thesis_id": tid,
                "history_id": rec.id,
                "action": "marked_missing",
            })

    if not dry_run:
        session.flush()

    return stats


def print_report(coverage: dict, backfill_stats: dict) -> None:
    """Print a human-readable report."""
    print("=" * 70)
    print("VALUATION HISTORY COVERAGE REPORT")
    print("=" * 70)
    print(f"  Total history records:     {coverage['total_records']}")
    print(f"  With valuation:            {coverage['with_valuation']}")
    print(f"  Without valuation:         {coverage['without_valuation']}")
    print(f"  With provenance:           {coverage['with_provenance']}")
    print(f"  Without provenance:        {coverage['without_provenance']}")
    print()

    if coverage["per_thesis"]:
        print("Per-thesis breakdown:")
        for t in coverage["per_thesis"]:
            print(
                f"  {t['ticker']:8s} (thesis {t['thesis_id']:3d}): "
                f"{t['with_valuation']}/{t['total_records']} records "
                f"({t['coverage_pct']:.0f}% coverage)"
            )
        print()

    print("=" * 70)
    print("BACKFILL RESULTS")
    print("=" * 70)
    print(f"  Records inspected:         {backfill_stats['inspected']}")
    print(f"  Already populated:         {backfill_stats['already_populated']}")
    print(f"  Backfilled:                {backfill_stats['backfilled']}")
    print(f"  Marked missing:            {backfill_stats['marked_missing']}")
    print(f"  Provenance tags added:     {backfill_stats['provenance_updated']}")
    print()

    if backfill_stats["details"]:
        print("Details:")
        for d in backfill_stats["details"]:
            if d["action"] == "backfilled":
                print(
                    f"  thesis={d['thesis_id']} hist={d['history_id']}: "
                    f"backfilled from hist={d['source_history_id']} "
                    f"(gap={d['gap_days']}d, val_gap={d['valuation_gap_pct']})"
                )
            elif d["action"] == "marked_missing":
                print(
                    f"  thesis={d['thesis_id']} hist={d['history_id']}: "
                    f"no defensible source — marked missing"
                )
            elif d["action"] == "provenance_set":
                print(
                    f"  thesis={d['thesis_id']} hist={d['history_id']}: "
                    f"provenance set to {d['provenance']}"
                )


def main():
    parser = argparse.ArgumentParser(description="Backfill valuation history")
    parser.add_argument(
        "--db", default=os.environ.get("DATABASE_URL", "sqlite:///consensus.db"),
        help="Database URL (default: sqlite:///consensus.db or DATABASE_URL env)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Inspect and report without writing changes",
    )
    parser.add_argument(
        "--max-gap-days", type=int, default=DEFAULT_MAX_GAP_DAYS,
        help=f"Max days gap for backfill source (default: {DEFAULT_MAX_GAP_DAYS})",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    engine = create_engine(args.db)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        # Pre-backfill coverage
        coverage_before = inspect_coverage(session)

        # Run backfill
        stats = backfill_valuation_history(
            session,
            max_gap_days=args.max_gap_days,
            dry_run=args.dry_run,
        )

        if not args.dry_run:
            session.commit()

        # Post-backfill coverage
        coverage_after = inspect_coverage(session)

        print_report(coverage_after, stats)

        if args.dry_run:
            print("\n*** DRY RUN — no changes written ***")
        else:
            print(f"\nCoverage improvement: "
                  f"{coverage_before['with_valuation']}/{coverage_before['total_records']} → "
                  f"{coverage_after['with_valuation']}/{coverage_after['total_records']}")


if __name__ == "__main__":
    main()
