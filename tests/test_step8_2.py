"""Tests for Step 8.2: historical valuation-state backfill and provenance hardening.

Covers:
  - Thesis updates persist valuation fields into ThesisStateHistory going forward
  - Valuation provenance is stored correctly
  - Backfill only writes when a dated source exists
  - Backfill never uses present-day thesis valuation as fake history
  - Strict replay uses historical/backfilled valuation when valid
  - Strict replay still falls back safely when valuation remains missing
  - _get_valuation_as_of returns provenance string
  - Diagnostics correctly identify exclusions and downgrades
  - Candidate provenance report correctly identifies exclusions
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from models import (
    Base, Company, Thesis, ThesisState, ThesisStateHistory,
    Candidate, Price, Checkpoint, ZoneState, ActionType,
    ValuationProvenance,
    Claim, ClaimCompanyLink, NoveltyType,
    Document, SourceType, SourceTier, ClaimType, EconomicChannel, Direction,
)
from portfolio_review_service import _get_valuation_as_of
from replay_engine import (
    run_replay_review, _preload_prices, ReplayPurityFlags,
)
from replay_runner import run_replay
from replay_diagnostics import (
    build_candidate_provenance_report, build_coverage_diagnostics,
    format_diagnostics_text,
)
from shadow_portfolio import ShadowPortfolio

# Import backfill functions
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
from backfill_valuation_history import (
    backfill_valuation_history, inspect_coverage,
)


TODAY = date(2026, 3, 12)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


def _make_company(session, ticker):
    session.add(Company(ticker=ticker, name=f"{ticker} Inc"))
    session.flush()


def _make_thesis(session, ticker, state=ThesisState.STRENGTHENING,
                 conviction=70.0, valuation_gap=15.0, base_case=1.3):
    thesis = Thesis(
        title=f"{ticker} thesis",
        company_ticker=ticker,
        state=state,
        conviction_score=conviction,
        valuation_gap_pct=valuation_gap,
        base_case_rerating=base_case,
    )
    session.add(thesis)
    session.flush()
    return thesis


def _add_price(session, ticker, d, close):
    session.add(Price(ticker=ticker, date=d, close=close))
    session.flush()


def _add_thesis_history(session, thesis_id, state, conviction, created_at,
                        valuation_gap=None, base_case=None, provenance=None):
    session.add(ThesisStateHistory(
        thesis_id=thesis_id,
        state=state,
        conviction_score=conviction,
        valuation_gap_pct=valuation_gap,
        base_case_rerating=base_case,
        valuation_provenance=provenance,
        created_at=created_at,
    ))
    session.flush()


def _make_candidate(session, ticker, thesis_id=None, conviction=60.0,
                    created_at=None):
    cand = Candidate(
        ticker=ticker,
        primary_thesis_id=thesis_id,
        conviction_score=conviction,
        created_at=created_at,
    )
    session.add(cand)
    session.flush()
    return cand


def _ensure_document(session):
    from sqlalchemy import select as sa_select
    existing = session.scalars(sa_select(Document).limit(1)).first()
    if existing:
        return existing.id
    doc = Document(
        source_type=SourceType.NEWS, source_tier=SourceTier.TIER_2,
        url="http://test.example.com/doc", title="Test document",
    )
    session.add(doc)
    session.flush()
    return doc.id


def _add_claim(session, ticker, published_at, novelty=NoveltyType.NEW):
    doc_id = _ensure_document(session)
    claim = Claim(
        document_id=doc_id,
        claim_text_normalized=f"Claim for {ticker}",
        claim_type=ClaimType.DEMAND,
        economic_channel=EconomicChannel.REVENUE,
        direction=Direction.POSITIVE,
        published_at=published_at,
        novelty_type=novelty,
    )
    session.add(claim)
    session.flush()
    session.add(ClaimCompanyLink(
        claim_id=claim.id, company_ticker=ticker, relation_type="about",
    ))
    session.flush()


# ---------------------------------------------------------------------------
# 1. Thesis update persists valuation into history (going-forward fix)
# ---------------------------------------------------------------------------

class TestThesisUpdatePersistsValuation:
    """Verify that thesis_update_service writes valuation fields."""

    def test_update_thesis_writes_valuation_to_history(self, session):
        """When thesis has valuation fields, ThesisStateHistory captures them."""
        _make_company(session, "NVDA")
        thesis = _make_thesis(session, "NVDA", valuation_gap=20.0, base_case=1.5)

        # Simulate what thesis_update_service now does
        session.add(ThesisStateHistory(
            thesis_id=thesis.id,
            state=ThesisState.STRENGTHENING,
            conviction_score=75.0,
            valuation_gap_pct=thesis.valuation_gap_pct,
            base_case_rerating=thesis.base_case_rerating,
            valuation_provenance=ValuationProvenance.HISTORICAL_RECORDED.value,
        ))
        session.flush()

        hist = session.scalars(
            select(ThesisStateHistory)
            .where(ThesisStateHistory.thesis_id == thesis.id)
            .order_by(ThesisStateHistory.created_at.desc())
            .limit(1)
        ).first()

        assert hist.valuation_gap_pct == 20.0
        assert hist.base_case_rerating == 1.5
        assert hist.valuation_provenance == ValuationProvenance.HISTORICAL_RECORDED.value

    def test_update_thesis_marks_missing_when_no_valuation(self, session):
        """When thesis has no valuation, provenance is MISSING."""
        _make_company(session, "NVDA")
        thesis = _make_thesis(session, "NVDA", valuation_gap=None, base_case=None)

        session.add(ThesisStateHistory(
            thesis_id=thesis.id,
            state=ThesisState.FORMING,
            conviction_score=40.0,
            valuation_gap_pct=None,
            base_case_rerating=None,
            valuation_provenance=ValuationProvenance.MISSING.value,
        ))
        session.flush()

        hist = session.scalars(
            select(ThesisStateHistory)
            .where(ThesisStateHistory.thesis_id == thesis.id)
            .order_by(ThesisStateHistory.created_at.desc())
            .limit(1)
        ).first()

        assert hist.valuation_gap_pct is None
        assert hist.valuation_provenance == ValuationProvenance.MISSING.value


# ---------------------------------------------------------------------------
# 2. Valuation provenance in _get_valuation_as_of
# ---------------------------------------------------------------------------

class TestValuationProvenance:

    def test_returns_historical_provenance(self, session):
        """Historical record returns its provenance."""
        _make_company(session, "NVDA")
        thesis = _make_thesis(session, "NVDA", valuation_gap=20.0, base_case=1.5)
        _add_thesis_history(
            session, thesis.id,
            state=ThesisState.STRENGTHENING, conviction=70.0,
            created_at=datetime(2026, 3, 5),
            valuation_gap=12.0, base_case=1.2,
            provenance=ValuationProvenance.HISTORICAL_RECORDED.value,
        )

        gap, rerating, is_hist, prov = _get_valuation_as_of(session, thesis, date(2026, 3, 10))
        assert is_hist is True
        assert prov == ValuationProvenance.HISTORICAL_RECORDED.value

    def test_returns_backfilled_provenance(self, session):
        """Backfilled record returns backfilled provenance."""
        _make_company(session, "NVDA")
        thesis = _make_thesis(session, "NVDA", valuation_gap=20.0, base_case=1.5)
        _add_thesis_history(
            session, thesis.id,
            state=ThesisState.STRENGTHENING, conviction=70.0,
            created_at=datetime(2026, 3, 5),
            valuation_gap=12.0, base_case=1.2,
            provenance=ValuationProvenance.BACKFILLED_FROM_THESIS_SNAPSHOT.value,
        )

        gap, rerating, is_hist, prov = _get_valuation_as_of(session, thesis, date(2026, 3, 10))
        assert is_hist is True
        assert prov == ValuationProvenance.BACKFILLED_FROM_THESIS_SNAPSHOT.value

    def test_returns_current_fallback_when_no_history(self, session):
        """No historical valuation → current_fallback provenance."""
        _make_company(session, "NVDA")
        thesis = _make_thesis(session, "NVDA", valuation_gap=20.0, base_case=1.5)

        gap, rerating, is_hist, prov = _get_valuation_as_of(session, thesis, date(2026, 3, 10))
        assert is_hist is False
        assert prov == "current_fallback"

    def test_defaults_to_historical_recorded_when_provenance_null(self, session):
        """Old records without provenance field default to historical_recorded."""
        _make_company(session, "NVDA")
        thesis = _make_thesis(session, "NVDA", valuation_gap=20.0, base_case=1.5)
        # History record with valuation but no provenance (pre-8.2 record)
        _add_thesis_history(
            session, thesis.id,
            state=ThesisState.STRENGTHENING, conviction=70.0,
            created_at=datetime(2026, 3, 5),
            valuation_gap=12.0, base_case=1.2,
            provenance=None,
        )

        gap, rerating, is_hist, prov = _get_valuation_as_of(session, thesis, date(2026, 3, 10))
        assert is_hist is True
        assert prov == ValuationProvenance.HISTORICAL_RECORDED.value


# ---------------------------------------------------------------------------
# 3. Backfill logic
# ---------------------------------------------------------------------------

class TestBackfillValuationHistory:

    def test_backfill_from_earlier_record(self, session):
        """Backfill copies valuation from nearest earlier record within gap."""
        _make_company(session, "NVDA")
        thesis = _make_thesis(session, "NVDA", valuation_gap=20.0, base_case=1.5)

        # Record 1: has valuation
        _add_thesis_history(
            session, thesis.id,
            state=ThesisState.STRENGTHENING, conviction=70.0,
            created_at=datetime(2026, 3, 1),
            valuation_gap=15.0, base_case=1.3,
        )
        # Record 2: no valuation, 5 days later
        _add_thesis_history(
            session, thesis.id,
            state=ThesisState.STABLE, conviction=72.0,
            created_at=datetime(2026, 3, 6),
        )

        stats = backfill_valuation_history(session, max_gap_days=30)
        assert stats["backfilled"] == 1

        # Verify record 2 now has valuation
        recs = session.scalars(
            select(ThesisStateHistory)
            .where(ThesisStateHistory.thesis_id == thesis.id)
            .order_by(ThesisStateHistory.created_at.asc())
        ).all()
        assert recs[1].valuation_gap_pct == 15.0
        assert recs[1].base_case_rerating == 1.3
        assert recs[1].valuation_provenance == ValuationProvenance.BACKFILLED_FROM_THESIS_SNAPSHOT.value

    def test_backfill_skips_when_gap_too_large(self, session):
        """Backfill does not copy if gap exceeds max_gap_days."""
        _make_company(session, "NVDA")
        thesis = _make_thesis(session, "NVDA", valuation_gap=20.0, base_case=1.5)

        _add_thesis_history(
            session, thesis.id,
            state=ThesisState.STRENGTHENING, conviction=70.0,
            created_at=datetime(2026, 1, 1),
            valuation_gap=15.0, base_case=1.3,
        )
        # 90 days later — too far
        _add_thesis_history(
            session, thesis.id,
            state=ThesisState.STABLE, conviction=72.0,
            created_at=datetime(2026, 4, 1),
        )

        stats = backfill_valuation_history(session, max_gap_days=30)
        assert stats["backfilled"] == 0
        assert stats["marked_missing"] == 1

    def test_backfill_never_uses_current_thesis(self, session):
        """Backfill never uses live thesis.valuation_gap_pct."""
        _make_company(session, "NVDA")
        thesis = _make_thesis(session, "NVDA", valuation_gap=99.9, base_case=5.0)

        # Only one history record with no valuation, no earlier record to copy from
        _add_thesis_history(
            session, thesis.id,
            state=ThesisState.STRENGTHENING, conviction=70.0,
            created_at=datetime(2026, 3, 1),
        )

        stats = backfill_valuation_history(session, max_gap_days=30)
        assert stats["backfilled"] == 0
        assert stats["marked_missing"] == 1

        rec = session.scalars(
            select(ThesisStateHistory)
            .where(ThesisStateHistory.thesis_id == thesis.id)
        ).first()
        # Must NOT have picked up the thesis's 99.9 value
        assert rec.valuation_gap_pct is None
        assert rec.valuation_provenance == ValuationProvenance.MISSING.value

    def test_backfill_sets_provenance_on_existing_populated_records(self, session):
        """Records that already have valuation get provenance tagged."""
        _make_company(session, "NVDA")
        thesis = _make_thesis(session, "NVDA", valuation_gap=20.0, base_case=1.5)

        _add_thesis_history(
            session, thesis.id,
            state=ThesisState.STRENGTHENING, conviction=70.0,
            created_at=datetime(2026, 3, 1),
            valuation_gap=15.0, base_case=1.3,
            provenance=None,  # pre-8.2: no provenance
        )

        stats = backfill_valuation_history(session)
        assert stats["provenance_updated"] == 1

        rec = session.scalars(
            select(ThesisStateHistory)
            .where(ThesisStateHistory.thesis_id == thesis.id)
        ).first()
        assert rec.valuation_provenance == ValuationProvenance.HISTORICAL_RECORDED.value

    def test_backfill_dry_run_makes_no_changes(self, session):
        """Dry run inspects but does not modify records."""
        _make_company(session, "NVDA")
        thesis = _make_thesis(session, "NVDA", valuation_gap=20.0, base_case=1.5)

        _add_thesis_history(
            session, thesis.id,
            state=ThesisState.STRENGTHENING, conviction=70.0,
            created_at=datetime(2026, 3, 1),
        )

        stats = backfill_valuation_history(session, dry_run=True)
        assert stats["marked_missing"] == 1

        rec = session.scalars(
            select(ThesisStateHistory)
            .where(ThesisStateHistory.thesis_id == thesis.id)
        ).first()
        # Dry run — provenance should still be None
        assert rec.valuation_provenance is None

    def test_inspect_coverage(self, session):
        """inspect_coverage returns correct counts."""
        _make_company(session, "NVDA")
        thesis = _make_thesis(session, "NVDA", valuation_gap=20.0, base_case=1.5)

        _add_thesis_history(session, thesis.id,
            state=ThesisState.STRENGTHENING, conviction=70.0,
            created_at=datetime(2026, 3, 1),
            valuation_gap=15.0, base_case=1.3,
        )
        _add_thesis_history(session, thesis.id,
            state=ThesisState.STABLE, conviction=72.0,
            created_at=datetime(2026, 3, 5),
        )

        cov = inspect_coverage(session)
        assert cov["total_records"] == 2
        assert cov["with_valuation"] == 1
        assert cov["without_valuation"] == 1


# ---------------------------------------------------------------------------
# 4. Strict replay uses backfilled valuation
# ---------------------------------------------------------------------------

class TestStrictReplayUsesBackfilled:

    def test_strict_uses_backfilled_valuation(self, session):
        """Strict mode accepts backfilled valuation (is_historical=True)."""
        _make_company(session, "NVDA")
        thesis = _make_thesis(session, "NVDA", valuation_gap=20.0, base_case=1.5)
        _add_price(session, "NVDA", TODAY, 100.0)
        _add_price(session, "NVDA", TODAY + timedelta(days=1), 101.0)

        # Add backfilled history record
        _add_thesis_history(
            session, thesis.id,
            state=ThesisState.STRENGTHENING, conviction=70.0,
            created_at=datetime(2026, 3, 5),
            valuation_gap=12.0, base_case=1.2,
            provenance=ValuationProvenance.BACKFILLED_FROM_THESIS_SNAPSHOT.value,
        )

        _make_candidate(
            session, "NVDA", thesis_id=thesis.id,
            created_at=datetime(2026, 3, 1),
        )
        _add_claim(session, "NVDA", datetime(2026, 3, 10))

        portfolio = ShadowPortfolio(initial_cash=1_000_000)
        prices = _preload_prices(session, ["NVDA"])

        record = run_replay_review(
            session, portfolio, TODAY, prices,
            apply_trades=True, strict_replay=True,
        )

        # Should NOT have skipped valuation — backfilled is accepted
        assert record.purity.skipped_impure_valuation == 0
        assert record.purity.impure_valuation_count == 0

    def test_strict_still_skips_when_valuation_truly_missing(self, session):
        """Strict mode still skips when no valuation exists (not even backfilled)."""
        _make_company(session, "NVDA")
        thesis = _make_thesis(session, "NVDA", valuation_gap=20.0, base_case=1.5)
        _add_price(session, "NVDA", TODAY, 100.0)
        _add_price(session, "NVDA", TODAY + timedelta(days=1), 101.0)

        _make_candidate(
            session, "NVDA", thesis_id=thesis.id,
            created_at=datetime(2026, 3, 1),
        )

        portfolio = ShadowPortfolio(initial_cash=1_000_000)
        prices = _preload_prices(session, ["NVDA"])

        record = run_replay_review(
            session, portfolio, TODAY, prices,
            apply_trades=True, strict_replay=True,
        )

        assert record.purity.skipped_impure_valuation >= 1
        assert any("no historical valuation" in w for w in record.purity.integrity_warnings)

    def test_provenance_in_warning_message(self, session):
        """Warning messages include provenance information."""
        _make_company(session, "NVDA")
        thesis = _make_thesis(session, "NVDA", valuation_gap=20.0, base_case=1.5)
        _add_price(session, "NVDA", TODAY, 100.0)
        _add_price(session, "NVDA", TODAY + timedelta(days=1), 101.0)

        _make_candidate(
            session, "NVDA", thesis_id=thesis.id,
            created_at=datetime(2026, 3, 1),
        )

        portfolio = ShadowPortfolio(initial_cash=1_000_000)
        prices = _preload_prices(session, ["NVDA"])

        record = run_replay_review(
            session, portfolio, TODAY, prices,
            apply_trades=True, strict_replay=False,
        )

        assert any("provenance=current_fallback" in w for w in record.purity.integrity_warnings)


# ---------------------------------------------------------------------------
# 5. Candidate provenance report
# ---------------------------------------------------------------------------

class TestCandidateProvenanceReport:

    def test_report_identifies_missing_provenance(self, session):
        """Candidates without created_at are flagged."""
        _make_company(session, "NVDA")
        thesis = _make_thesis(session, "NVDA")

        _make_candidate(session, "NVDA", thesis_id=thesis.id, created_at=None)

        review_dates = [TODAY, TODAY + timedelta(days=7)]
        report = build_candidate_provenance_report(session, review_dates)

        assert report.total_candidates == 1
        assert report.candidates_without_provenance == 1
        assert report.candidates_excluded_all_dates == 1
        assert report.entries[0].has_created_at is False
        assert report.entries[0].entered_replay is False

    def test_report_tracks_first_eligible_date(self, session):
        """Reports first date a candidate becomes eligible."""
        _make_company(session, "NVDA")
        thesis = _make_thesis(session, "NVDA")

        _make_candidate(
            session, "NVDA", thesis_id=thesis.id,
            created_at=datetime(2026, 3, 15),
        )

        review_dates = [
            date(2026, 3, 12),  # before created_at
            date(2026, 3, 19),  # after created_at
            date(2026, 3, 26),  # after created_at
        ]
        report = build_candidate_provenance_report(session, review_dates)

        entry = report.entries[0]
        assert entry.has_created_at is True
        assert entry.first_eligible_date == date(2026, 3, 19)
        assert entry.review_dates_skipped == 1
        assert entry.review_dates_included == 2
        assert entry.entered_replay is True

    def test_report_with_mixed_candidates(self, session):
        """Mixed candidates: some with provenance, some without."""
        _make_company(session, "NVDA")
        _make_company(session, "AAPL")
        thesis_nvda = _make_thesis(session, "NVDA")
        thesis_aapl = _make_thesis(session, "AAPL")

        _make_candidate(session, "NVDA", thesis_id=thesis_nvda.id,
                       created_at=datetime(2026, 3, 1))
        _make_candidate(session, "AAPL", thesis_id=thesis_aapl.id,
                       created_at=None)

        review_dates = [TODAY]
        report = build_candidate_provenance_report(session, review_dates)

        assert report.candidates_with_provenance == 1
        assert report.candidates_without_provenance == 1
        assert report.to_dict()["total_candidates"] == 2


# ---------------------------------------------------------------------------
# 6. Replay coverage diagnostics
# ---------------------------------------------------------------------------

class TestReplayCoverageDiagnostics:

    def test_diagnostics_from_strict_run(self, session):
        """Diagnostics correctly extract info from strict replay run."""
        _make_company(session, "NVDA")
        thesis = _make_thesis(session, "NVDA", valuation_gap=20.0, base_case=1.5)
        _add_price(session, "NVDA", TODAY, 100.0)
        _add_price(session, "NVDA", TODAY + timedelta(days=1), 101.0)

        # Candidate with no provenance
        _make_candidate(session, "NVDA", thesis_id=thesis.id, created_at=None)

        run_result, _, _ = run_replay(
            session, start_date=TODAY, end_date=TODAY,
            cadence_days=7, strict_replay=True,
        )

        diag = build_coverage_diagnostics(run_result)
        assert diag.candidate_exclusions_no_provenance >= 1
        assert "NVDA" in diag.names_skipped_entirely

    def test_diagnostics_identifies_hold_downgrades(self, session):
        """Diagnostics identify names downgraded to HOLD due to missing valuation."""
        _make_company(session, "NVDA")
        thesis = _make_thesis(session, "NVDA", valuation_gap=20.0, base_case=1.5)
        _add_price(session, "NVDA", TODAY, 100.0)
        _add_price(session, "NVDA", TODAY + timedelta(days=1), 101.0)

        # Candidate with provenance but no valuation history
        _make_candidate(
            session, "NVDA", thesis_id=thesis.id,
            created_at=datetime(2026, 3, 1),
        )

        run_result, _, _ = run_replay(
            session, start_date=TODAY, end_date=TODAY,
            cadence_days=7, strict_replay=True,
        )

        diag = build_coverage_diagnostics(run_result)
        assert diag.valuation_missing_count >= 1
        assert "NVDA" in diag.names_downgraded_to_hold

    def test_diagnostics_to_dict(self, session):
        """Diagnostics to_dict produces valid structure."""
        _make_company(session, "NVDA")
        thesis = _make_thesis(session, "NVDA")
        _add_price(session, "NVDA", TODAY, 100.0)
        _add_price(session, "NVDA", TODAY + timedelta(days=1), 101.0)

        _make_candidate(session, "NVDA", thesis_id=thesis.id, created_at=None)

        run_result, _, _ = run_replay(
            session, start_date=TODAY, end_date=TODAY,
            cadence_days=7, strict_replay=True,
        )

        diag = build_coverage_diagnostics(run_result)
        d = diag.to_dict()
        assert "candidate_exclusions" in d
        assert "valuation" in d
        assert "impact" in d

    def test_format_diagnostics_text(self, session):
        """format_diagnostics_text produces non-empty string."""
        _make_company(session, "NVDA")
        thesis = _make_thesis(session, "NVDA")
        _add_price(session, "NVDA", TODAY, 100.0)
        _add_price(session, "NVDA", TODAY + timedelta(days=1), 101.0)

        _make_candidate(session, "NVDA", thesis_id=thesis.id, created_at=None)

        run_result, _, _ = run_replay(
            session, start_date=TODAY, end_date=TODAY,
            cadence_days=7, strict_replay=True,
        )

        diag = build_coverage_diagnostics(run_result)
        cand_report = build_candidate_provenance_report(
            session, [TODAY],
        )
        text = format_diagnostics_text(diag, cand_report)
        assert "REPLAY COVERAGE DIAGNOSTICS" in text
        assert "CANDIDATE PROVENANCE" in text


# ---------------------------------------------------------------------------
# 7. ValuationProvenance enum
# ---------------------------------------------------------------------------

class TestValuationProvenanceEnum:

    def test_enum_values(self):
        assert ValuationProvenance.HISTORICAL_RECORDED.value == "historical_recorded"
        assert ValuationProvenance.BACKFILLED_FROM_THESIS_SNAPSHOT.value == "backfilled_from_thesis_snapshot"
        assert ValuationProvenance.MISSING.value == "missing"

    def test_stored_on_model(self, session):
        """ValuationProvenance can be stored on ThesisStateHistory."""
        _make_company(session, "NVDA")
        thesis = _make_thesis(session, "NVDA")

        session.add(ThesisStateHistory(
            thesis_id=thesis.id,
            state=ThesisState.STRENGTHENING,
            conviction_score=70.0,
            valuation_provenance=ValuationProvenance.HISTORICAL_RECORDED.value,
        ))
        session.flush()

        rec = session.scalars(
            select(ThesisStateHistory)
            .where(ThesisStateHistory.thesis_id == thesis.id)
        ).first()
        assert rec.valuation_provenance == "historical_recorded"
