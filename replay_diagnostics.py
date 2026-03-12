"""Replay coverage diagnostics: explain why strict replay stayed conservative.

Provides structured reports on:
  - Candidate exclusions due to missing provenance
  - Checkpoint exclusions due to missing provenance
  - Valuation fallback/missing counts and reasons
  - Names downgraded to HOLD due to missing historical valuation
  - Names skipped entirely due to strict purity requirements
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from models import (
    Candidate, Checkpoint, Thesis, ThesisStateHistory,
    ValuationProvenance,
)
from replay_engine import ReplayRunResult, ReplayReviewRecord


# ---------------------------------------------------------------------------
# Candidate provenance report
# ---------------------------------------------------------------------------

@dataclass
class CandidateProvenanceEntry:
    """Provenance status for a single candidate."""
    ticker: str
    candidate_id: int
    has_created_at: bool
    created_at: Optional[datetime]
    first_eligible_date: Optional[date]  # first review date where created_at <= review_date
    review_dates_skipped: int  # how many review dates it was excluded
    review_dates_included: int  # how many review dates it was included
    entered_replay: bool  # whether it ever entered the replay universe


@dataclass
class CandidateProvenanceReport:
    """Summary of candidate provenance across a replay period."""
    total_candidates: int = 0
    candidates_with_provenance: int = 0
    candidates_without_provenance: int = 0
    candidates_excluded_all_dates: int = 0
    entries: list[CandidateProvenanceEntry] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "total_candidates": self.total_candidates,
            "candidates_with_provenance": self.candidates_with_provenance,
            "candidates_without_provenance": self.candidates_without_provenance,
            "candidates_excluded_all_dates": self.candidates_excluded_all_dates,
            "entries": [
                {
                    "ticker": e.ticker,
                    "candidate_id": e.candidate_id,
                    "has_created_at": e.has_created_at,
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                    "first_eligible_date": e.first_eligible_date.isoformat() if e.first_eligible_date else None,
                    "review_dates_skipped": e.review_dates_skipped,
                    "review_dates_included": e.review_dates_included,
                    "entered_replay": e.entered_replay,
                }
                for e in self.entries
            ],
        }


def build_candidate_provenance_report(
    session: Session,
    review_dates: list[date],
    *,
    ticker_filter: Optional[str] = None,
) -> CandidateProvenanceReport:
    """Build a provenance report for all candidates over the given review dates."""
    report = CandidateProvenanceReport()

    q = select(Candidate)
    if ticker_filter:
        q = q.where(Candidate.ticker == ticker_filter)
    candidates = session.scalars(q).all()

    report.total_candidates = len(candidates)

    for cand in candidates:
        has_created_at = cand.created_at is not None
        if has_created_at:
            report.candidates_with_provenance += 1
        else:
            report.candidates_without_provenance += 1

        first_eligible = None
        skipped = 0
        included = 0

        for rd in review_dates:
            as_of_dt = datetime.combine(rd, datetime.max.time())
            if not has_created_at:
                # No provenance — skipped in strict mode for all dates
                skipped += 1
            elif cand.created_at > as_of_dt:
                skipped += 1
            else:
                if first_eligible is None:
                    first_eligible = rd
                included += 1

        entered = included > 0

        if not entered:
            report.candidates_excluded_all_dates += 1

        report.entries.append(CandidateProvenanceEntry(
            ticker=cand.ticker,
            candidate_id=cand.id,
            has_created_at=has_created_at,
            created_at=cand.created_at,
            first_eligible_date=first_eligible,
            review_dates_skipped=skipped,
            review_dates_included=included,
            entered_replay=entered,
        ))

    return report


# ---------------------------------------------------------------------------
# Replay coverage diagnostics from a completed run
# ---------------------------------------------------------------------------

@dataclass
class ReplayCoverageDiagnostics:
    """Structured diagnostics explaining strict replay conservatism."""
    # Candidate exclusions
    candidate_exclusions_no_provenance: int = 0
    candidate_exclusions_future_created: int = 0
    # Checkpoint exclusions
    checkpoint_exclusions_no_provenance: int = 0
    # Valuation
    valuation_fallback_count: int = 0   # non-strict: used current as fallback
    valuation_missing_count: int = 0    # strict: no valuation at all
    valuation_historical_count: int = 0  # used proper historical valuation
    valuation_backfilled_count: int = 0  # used backfilled valuation
    # Impact
    names_downgraded_to_hold: list[str] = field(default_factory=list)
    names_skipped_entirely: list[str] = field(default_factory=list)
    # Provenance breakdown
    valuation_provenance_counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "candidate_exclusions": {
                "no_provenance": self.candidate_exclusions_no_provenance,
                "future_created": self.candidate_exclusions_future_created,
            },
            "checkpoint_exclusions": {
                "no_provenance": self.checkpoint_exclusions_no_provenance,
            },
            "valuation": {
                "fallback_count": self.valuation_fallback_count,
                "missing_count": self.valuation_missing_count,
                "historical_count": self.valuation_historical_count,
                "backfilled_count": self.valuation_backfilled_count,
                "provenance_breakdown": self.valuation_provenance_counts,
            },
            "impact": {
                "names_downgraded_to_hold": sorted(set(self.names_downgraded_to_hold)),
                "names_skipped_entirely": sorted(set(self.names_skipped_entirely)),
            },
        }


def build_coverage_diagnostics(
    run_result: ReplayRunResult,
) -> ReplayCoverageDiagnostics:
    """Extract coverage diagnostics from a completed replay run."""
    diag = ReplayCoverageDiagnostics()

    for record in run_result.review_records:
        purity = record.purity

        # Candidate exclusions
        diag.candidate_exclusions_no_provenance += purity.skipped_impure_candidates

        # Checkpoint exclusions
        diag.checkpoint_exclusions_no_provenance += purity.skipped_impure_checkpoints

        # Valuation
        diag.valuation_fallback_count += purity.impure_valuation_count
        diag.valuation_missing_count += purity.skipped_impure_valuation

        # Parse warnings for specific impact details
        for w in purity.integrity_warnings:
            if "no historical valuation" in w and "zone defaulted to HOLD" in w:
                # Extract ticker name
                ticker = _extract_ticker_from_warning(w)
                if ticker:
                    diag.names_downgraded_to_hold.append(ticker)
            if "no created_at, excluded" in w:
                ticker = _extract_ticker_from_warning(w)
                if ticker:
                    diag.names_skipped_entirely.append(ticker)

    # Count valuation provenance from history records if available
    # (This is done from the warnings since we don't store provenance on purity flags)

    return diag


def build_valuation_provenance_summary(
    session: Session,
    thesis_ids: Optional[list[int]] = None,
) -> dict[str, int]:
    """Count ThesisStateHistory records by valuation_provenance value."""
    q = select(
        ThesisStateHistory.valuation_provenance,
        func.count(ThesisStateHistory.id),
    ).group_by(ThesisStateHistory.valuation_provenance)

    if thesis_ids:
        q = q.where(ThesisStateHistory.thesis_id.in_(thesis_ids))

    rows = session.execute(q).all()
    return {str(prov or "unset"): count for prov, count in rows}


def _extract_ticker_from_warning(warning: str) -> Optional[str]:
    """Extract ticker from warning like 'Candidate NVDA: ...' or 'Holding NVDA: ...'."""
    for prefix in ("Candidate ", "Holding "):
        if warning.startswith(prefix):
            rest = warning[len(prefix):]
            colon = rest.find(":")
            if colon > 0:
                return rest[:colon]
    return None


# ---------------------------------------------------------------------------
# Formatted text output
# ---------------------------------------------------------------------------

def format_diagnostics_text(
    diag: ReplayCoverageDiagnostics,
    candidate_report: Optional[CandidateProvenanceReport] = None,
) -> str:
    """Format diagnostics as human-readable text."""
    lines = [
        "REPLAY COVERAGE DIAGNOSTICS",
        "=" * 50,
        "",
        "--- CANDIDATE EXCLUSIONS ---",
        f"  No provenance (missing created_at): {diag.candidate_exclusions_no_provenance}",
        f"  Future created_at:                  {diag.candidate_exclusions_future_created}",
        "",
        "--- CHECKPOINT EXCLUSIONS ---",
        f"  No provenance (missing created_at): {diag.checkpoint_exclusions_no_provenance}",
        "",
        "--- VALUATION STATUS ---",
        f"  Historical (pure):     {diag.valuation_historical_count}",
        f"  Backfilled (accepted): {diag.valuation_backfilled_count}",
        f"  Fallback (impure):     {diag.valuation_fallback_count}",
        f"  Missing (skipped):     {diag.valuation_missing_count}",
        "",
        "--- IMPACT ---",
        f"  Names downgraded to HOLD: {sorted(set(diag.names_downgraded_to_hold))}",
        f"  Names skipped entirely:   {sorted(set(diag.names_skipped_entirely))}",
    ]

    if candidate_report:
        lines.extend([
            "",
            "--- CANDIDATE PROVENANCE ---",
            f"  Total candidates:        {candidate_report.total_candidates}",
            f"  With provenance:         {candidate_report.candidates_with_provenance}",
            f"  Without provenance:      {candidate_report.candidates_without_provenance}",
            f"  Excluded all dates:      {candidate_report.candidates_excluded_all_dates}",
        ])
        for e in candidate_report.entries:
            status = "OK" if e.entered_replay else "EXCLUDED"
            lines.append(
                f"    {e.ticker:8s} id={e.candidate_id:3d}  "
                f"created_at={'yes' if e.has_created_at else 'NO ':3s}  "
                f"eligible={e.first_eligible_date or 'never':10s}  "
                f"included={e.review_dates_included:2d}/{e.review_dates_skipped + e.review_dates_included:2d}  "
                f"[{status}]"
            )

    return "\n".join(lines)
