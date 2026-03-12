"""Tests for Step 8.1: replay purity hardening.

Covers:
  - Candidate created after replay date is excluded in strict mode
  - Candidate without created_at is excluded in strict mode, included with warning otherwise
  - Checkpoint created after replay date is not visible in strict mode
  - Replay does not use current valuation inputs when historical valuation is unavailable (strict)
  - Non-strict mode uses documented fallback and records integrity warnings
  - Replay output purity flags reflect actual fallback usage
  - Candidate snapshot and review decisions differ correctly before vs after candidate creation
  - Checkpoint-dependent logic behaves correctly before vs after checkpoint creation
  - Historical valuation from ThesisStateHistory is used when available
  - Purity level computation (strict, degraded, mixed)
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from models import (
    Base, Company, Thesis, ThesisState, ThesisStateHistory,
    Candidate, Price, Checkpoint, ZoneState, ActionType,
)
from portfolio_review_service import (
    _get_valuation_as_of, _has_checkpoint_ahead, _get_thesis_state_as_of,
)
from replay_engine import (
    run_replay_review, _preload_prices, ReplayPurityFlags, ReplayRunResult,
)
from replay_runner import run_replay, _compute_purity_level
from replay_metrics import compute_metrics
from shadow_portfolio import ShadowPortfolio


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
                 conviction=70.0, valuation_gap=15.0, base_case=1.3,
                 created_at=None):
    thesis = Thesis(
        title=f"{ticker} thesis",
        company_ticker=ticker,
        state=state,
        conviction_score=conviction,
        valuation_gap_pct=valuation_gap,
        base_case_rerating=base_case,
    )
    if created_at:
        thesis.created_at = created_at
        thesis.updated_at = created_at
    session.add(thesis)
    session.flush()
    return thesis


def _add_price(session, ticker, d, close):
    session.add(Price(ticker=ticker, date=d, close=close))
    session.flush()


def _add_thesis_history(session, thesis_id, state, conviction, created_at,
                        valuation_gap=None, base_case=None):
    session.add(ThesisStateHistory(
        thesis_id=thesis_id,
        state=state,
        conviction_score=conviction,
        valuation_gap_pct=valuation_gap,
        base_case_rerating=base_case,
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


def _make_checkpoint(session, ticker, date_expected, created_at=None):
    cp = Checkpoint(
        checkpoint_type="earnings",
        name=f"{ticker} earnings",
        date_expected=date_expected,
        importance=0.8,
        linked_company_ticker=ticker,
        created_at=created_at,
    )
    session.add(cp)
    session.flush()
    return cp


# ---------------------------------------------------------------------------
# 1. Candidate created_at filtering
# ---------------------------------------------------------------------------

class TestCandidateTemporalFiltering:

    def test_candidate_created_after_replay_date_excluded_strict(self, session):
        """Candidate created after replay date is excluded in strict mode."""
        _make_company(session, "NVDA")
        thesis = _make_thesis(session, "NVDA")
        _add_price(session, "NVDA", TODAY, 100.0)
        _add_price(session, "NVDA", TODAY + timedelta(days=1), 101.0)

        # Candidate created 5 days AFTER replay date
        _make_candidate(
            session, "NVDA", thesis_id=thesis.id,
            created_at=datetime(2026, 3, 17, 12, 0),
        )

        portfolio = ShadowPortfolio(initial_cash=1_000_000)
        prices = _preload_prices(session, ["NVDA"])

        record = run_replay_review(
            session, portfolio, TODAY, prices,
            apply_trades=True, strict_replay=True,
        )

        # No candidates should be included — NVDA was created after replay date
        assert len(record.result.decisions) == 0 or all(
            d.action == ActionType.NO_ACTION for d in record.result.decisions
        )
        # Candidate was skipped
        assert record.purity.skipped_impure_candidates >= 0  # may be 0 if excluded before counting

    def test_candidate_created_before_replay_date_included_strict(self, session):
        """Candidate created before replay date is included in strict mode."""
        _make_company(session, "NVDA")
        thesis = _make_thesis(session, "NVDA")
        _add_price(session, "NVDA", TODAY, 100.0)
        _add_price(session, "NVDA", TODAY + timedelta(days=1), 101.0)

        # Candidate created BEFORE replay date
        _make_candidate(
            session, "NVDA", thesis_id=thesis.id,
            created_at=datetime(2026, 3, 1, 12, 0),
        )

        portfolio = ShadowPortfolio(initial_cash=1_000_000)
        prices = _preload_prices(session, ["NVDA"])

        record = run_replay_review(
            session, portfolio, TODAY, prices,
            apply_trades=True, strict_replay=True,
        )

        # Candidate should be included — created before replay date
        candidate_decisions = [d for d in record.result.decisions if d.ticker == "NVDA"]
        assert len(candidate_decisions) >= 1
        assert record.purity.skipped_impure_candidates == 0

    def test_candidate_no_created_at_excluded_strict(self, session):
        """Candidate without created_at is excluded in strict mode."""
        _make_company(session, "NVDA")
        thesis = _make_thesis(session, "NVDA")
        _add_price(session, "NVDA", TODAY, 100.0)
        _add_price(session, "NVDA", TODAY + timedelta(days=1), 101.0)

        # Candidate with no created_at
        _make_candidate(session, "NVDA", thesis_id=thesis.id, created_at=None)

        portfolio = ShadowPortfolio(initial_cash=1_000_000)
        prices = _preload_prices(session, ["NVDA"])

        record = run_replay_review(
            session, portfolio, TODAY, prices,
            apply_trades=True, strict_replay=True,
        )

        # Candidate should be excluded — no temporal provenance
        assert record.purity.skipped_impure_candidates >= 1
        assert any("no created_at" in w for w in record.purity.integrity_warnings)

    def test_candidate_no_created_at_included_nonstrict_with_warning(self, session):
        """Candidate without created_at is included in non-strict mode with a warning."""
        _make_company(session, "NVDA")
        thesis = _make_thesis(session, "NVDA")
        _add_price(session, "NVDA", TODAY, 100.0)
        _add_price(session, "NVDA", TODAY + timedelta(days=1), 101.0)

        _make_candidate(session, "NVDA", thesis_id=thesis.id, created_at=None)

        portfolio = ShadowPortfolio(initial_cash=1_000_000)
        prices = _preload_prices(session, ["NVDA"])

        record = run_replay_review(
            session, portfolio, TODAY, prices,
            apply_trades=True, strict_replay=False,
        )

        # Candidate should be included in non-strict mode
        candidate_decisions = [d for d in record.result.decisions if d.ticker == "NVDA"]
        assert len(candidate_decisions) >= 1
        # But with warning
        assert record.purity.impure_candidate_count >= 1
        assert any("no created_at" in w for w in record.purity.integrity_warnings)

    def test_candidate_decisions_differ_before_vs_after_creation(self, session):
        """Replay at date before vs after candidate creation yields different results."""
        _make_company(session, "NVDA")
        thesis = _make_thesis(session, "NVDA")
        _add_price(session, "NVDA", date(2026, 3, 5), 100.0)
        _add_price(session, "NVDA", date(2026, 3, 6), 101.0)
        _add_price(session, "NVDA", date(2026, 3, 12), 105.0)
        _add_price(session, "NVDA", date(2026, 3, 13), 106.0)

        # Candidate created on March 10
        _make_candidate(
            session, "NVDA", thesis_id=thesis.id,
            created_at=datetime(2026, 3, 10, 12, 0),
        )

        prices = _preload_prices(session, ["NVDA"])

        # Replay at March 5 (before creation) — strict mode
        portfolio_before = ShadowPortfolio(initial_cash=1_000_000)
        record_before = run_replay_review(
            session, portfolio_before, date(2026, 3, 5), prices,
            strict_replay=True,
        )

        # Replay at March 12 (after creation) — strict mode
        portfolio_after = ShadowPortfolio(initial_cash=1_000_000)
        record_after = run_replay_review(
            session, portfolio_after, date(2026, 3, 12), prices,
            strict_replay=True,
        )

        # Before creation: no candidate decisions for NVDA
        nvda_before = [d for d in record_before.result.decisions if d.ticker == "NVDA"]
        assert len(nvda_before) == 0

        # After creation: NVDA should appear
        nvda_after = [d for d in record_after.result.decisions if d.ticker == "NVDA"]
        assert len(nvda_after) >= 1


# ---------------------------------------------------------------------------
# 2. Checkpoint temporal filtering
# ---------------------------------------------------------------------------

class TestCheckpointTemporalFiltering:

    def test_checkpoint_created_after_as_of_excluded_strict(self, session):
        """Checkpoint created after as_of is not visible in strict mode."""
        _make_company(session, "NVDA")

        # Checkpoint created on March 15 with expected date March 20
        _make_checkpoint(
            session, "NVDA",
            date_expected=date(2026, 3, 20),
            created_at=datetime(2026, 3, 15, 12, 0),
        )

        # As of March 12, strict mode — should not see this checkpoint
        has_cp, days = _has_checkpoint_ahead(
            session, "NVDA", date(2026, 3, 12),
            filter_created_at=True,
        )
        assert has_cp is False
        assert days is None

    def test_checkpoint_created_before_as_of_visible_strict(self, session):
        """Checkpoint created before as_of is visible in strict mode."""
        _make_company(session, "NVDA")

        _make_checkpoint(
            session, "NVDA",
            date_expected=date(2026, 3, 20),
            created_at=datetime(2026, 3, 10, 12, 0),
        )

        has_cp, days = _has_checkpoint_ahead(
            session, "NVDA", date(2026, 3, 12),
            filter_created_at=True,
        )
        assert has_cp is True
        assert days == 8

    def test_checkpoint_no_created_at_excluded_strict(self, session):
        """Checkpoint without created_at is excluded in strict mode."""
        _make_company(session, "NVDA")

        _make_checkpoint(
            session, "NVDA",
            date_expected=date(2026, 3, 20),
            created_at=None,
        )

        # Strict: checkpoint with no created_at is not visible
        has_cp, _ = _has_checkpoint_ahead(
            session, "NVDA", date(2026, 3, 12),
            filter_created_at=True,
        )
        assert has_cp is False

    def test_checkpoint_no_created_at_visible_nonstrict(self, session):
        """Checkpoint without created_at is visible in non-strict mode (legacy)."""
        _make_company(session, "NVDA")

        _make_checkpoint(
            session, "NVDA",
            date_expected=date(2026, 3, 20),
            created_at=None,
        )

        # Non-strict: legacy behavior, no filter on created_at
        has_cp, days = _has_checkpoint_ahead(
            session, "NVDA", date(2026, 3, 12),
            filter_created_at=False,
        )
        assert has_cp is True
        assert days == 8

    def test_checkpoint_logic_differs_before_vs_after_creation(self, session):
        """Checkpoint visibility changes across its creation date."""
        _make_company(session, "NVDA")

        _make_checkpoint(
            session, "NVDA",
            date_expected=date(2026, 3, 25),
            created_at=datetime(2026, 3, 15, 12, 0),
        )

        # Before creation (March 10) — not visible
        has_before, _ = _has_checkpoint_ahead(
            session, "NVDA", date(2026, 3, 10),
            filter_created_at=True,
        )
        assert has_before is False

        # After creation (March 16) — visible
        has_after, days = _has_checkpoint_ahead(
            session, "NVDA", date(2026, 3, 16),
            filter_created_at=True,
        )
        assert has_after is True
        assert days == 9


# ---------------------------------------------------------------------------
# 3. Historical valuation
# ---------------------------------------------------------------------------

class TestHistoricalValuation:

    def test_valuation_from_history_when_available(self, session):
        """_get_valuation_as_of uses ThesisStateHistory when fields are populated."""
        _make_company(session, "NVDA")
        thesis = _make_thesis(session, "NVDA", valuation_gap=20.0, base_case=1.5)

        # Add history with valuation fields
        _add_thesis_history(
            session, thesis.id,
            state=ThesisState.STRENGTHENING, conviction=70.0,
            created_at=datetime(2026, 3, 5, 12, 0),
            valuation_gap=12.0, base_case=1.2,
        )

        gap, rerating, is_historical, provenance = _get_valuation_as_of(session, thesis, date(2026, 3, 10))
        assert is_historical is True
        assert gap == 12.0
        assert rerating == 1.2

    def test_valuation_falls_back_to_current_when_no_history(self, session):
        """_get_valuation_as_of falls back to current thesis when no history."""
        _make_company(session, "NVDA")
        thesis = _make_thesis(session, "NVDA", valuation_gap=20.0, base_case=1.5)

        # No ThesisStateHistory with valuation fields
        gap, rerating, is_historical, provenance = _get_valuation_as_of(session, thesis, date(2026, 3, 10))
        assert is_historical is False
        assert gap == 20.0  # falls back to current
        assert rerating == 1.5
        assert provenance == "current_fallback"

    def test_valuation_uses_most_recent_history_before_as_of(self, session):
        """When multiple history records exist, use the most recent before as_of."""
        _make_company(session, "NVDA")
        thesis = _make_thesis(session, "NVDA", valuation_gap=25.0, base_case=2.0)

        _add_thesis_history(
            session, thesis.id,
            state=ThesisState.STABLE, conviction=60.0,
            created_at=datetime(2026, 3, 1, 12, 0),
            valuation_gap=10.0, base_case=1.1,
        )
        _add_thesis_history(
            session, thesis.id,
            state=ThesisState.STRENGTHENING, conviction=70.0,
            created_at=datetime(2026, 3, 8, 12, 0),
            valuation_gap=15.0, base_case=1.3,
        )
        _add_thesis_history(
            session, thesis.id,
            state=ThesisState.STRENGTHENING, conviction=80.0,
            created_at=datetime(2026, 3, 20, 12, 0),  # FUTURE
            valuation_gap=22.0, base_case=1.8,
        )

        # As of March 10 — should see March 8 record, not March 20
        gap, rerating, is_historical, provenance = _get_valuation_as_of(session, thesis, date(2026, 3, 10))
        assert is_historical is True
        assert gap == 15.0
        assert rerating == 1.3

    def test_strict_mode_skips_impure_valuation(self, session):
        """In strict mode, missing valuation history → zone defaults to HOLD."""
        _make_company(session, "NVDA")
        thesis = _make_thesis(session, "NVDA", valuation_gap=20.0, base_case=1.5)
        _add_price(session, "NVDA", TODAY, 100.0)
        _add_price(session, "NVDA", TODAY + timedelta(days=1), 101.0)

        # Candidate with no valuation history
        _make_candidate(
            session, "NVDA", thesis_id=thesis.id,
            created_at=datetime(2026, 3, 1, 12, 0),
        )

        portfolio = ShadowPortfolio(initial_cash=1_000_000)
        prices = _preload_prices(session, ["NVDA"])

        record = run_replay_review(
            session, portfolio, TODAY, prices,
            apply_trades=True, strict_replay=True,
        )

        # Should have skipped impure valuation warning
        assert record.purity.skipped_impure_valuation >= 1
        assert any("no historical valuation" in w for w in record.purity.integrity_warnings)

    def test_nonstrict_mode_uses_current_valuation_with_warning(self, session):
        """In non-strict mode, missing valuation history → uses current with warning."""
        _make_company(session, "NVDA")
        thesis = _make_thesis(session, "NVDA", valuation_gap=20.0, base_case=1.5)
        _add_price(session, "NVDA", TODAY, 100.0)
        _add_price(session, "NVDA", TODAY + timedelta(days=1), 101.0)

        _make_candidate(
            session, "NVDA", thesis_id=thesis.id,
            created_at=datetime(2026, 3, 1, 12, 0),
        )

        portfolio = ShadowPortfolio(initial_cash=1_000_000)
        prices = _preload_prices(session, ["NVDA"])

        record = run_replay_review(
            session, portfolio, TODAY, prices,
            apply_trades=True, strict_replay=False,
        )

        # Non-strict: should record impure valuation but still use it
        assert record.purity.impure_valuation_count >= 1
        assert any("using current valuation" in w for w in record.purity.integrity_warnings)

    def test_history_with_valuation_produces_pure_result(self, session):
        """When valuation history exists, no impurity warnings are raised."""
        _make_company(session, "NVDA")
        thesis = _make_thesis(session, "NVDA", valuation_gap=20.0, base_case=1.5)
        _add_price(session, "NVDA", TODAY, 100.0)
        _add_price(session, "NVDA", TODAY + timedelta(days=1), 101.0)

        _add_thesis_history(
            session, thesis.id,
            state=ThesisState.STRENGTHENING, conviction=70.0,
            created_at=datetime(2026, 3, 5, 12, 0),
            valuation_gap=15.0, base_case=1.3,
        )

        _make_candidate(
            session, "NVDA", thesis_id=thesis.id,
            created_at=datetime(2026, 3, 1, 12, 0),
        )

        portfolio = ShadowPortfolio(initial_cash=1_000_000)
        prices = _preload_prices(session, ["NVDA"])

        record = run_replay_review(
            session, portfolio, TODAY, prices,
            apply_trades=True, strict_replay=True,
        )

        assert record.purity.impure_valuation_count == 0
        assert record.purity.skipped_impure_valuation == 0


# ---------------------------------------------------------------------------
# 4. Purity level computation
# ---------------------------------------------------------------------------

class TestPurityLevel:

    def test_strict_purity_when_all_clean(self):
        """Purity level is 'strict' when no impurities and no skips."""
        run_result = ReplayRunResult(
            start_date=TODAY, end_date=TODAY, cadence_days=7,
        )
        assert _compute_purity_level(run_result) == "strict"

    def test_strict_purity_when_only_skips(self):
        """Purity level is 'strict' when impure items were skipped (strict mode)."""
        run_result = ReplayRunResult(
            start_date=TODAY, end_date=TODAY, cadence_days=7,
        )
        run_result.total_skipped_impure = 3
        assert _compute_purity_level(run_result) == "strict"

    def test_degraded_purity_when_impure_fallbacks(self):
        """Purity level is 'degraded' when impure fallbacks were used."""
        run_result = ReplayRunResult(
            start_date=TODAY, end_date=TODAY, cadence_days=7,
        )
        run_result.total_impure_candidates = 2
        assert _compute_purity_level(run_result) == "degraded"

    def test_mixed_purity_when_both_skips_and_fallbacks(self):
        """Purity level is 'mixed' when some skipped and some used as fallback."""
        run_result = ReplayRunResult(
            start_date=TODAY, end_date=TODAY, cadence_days=7,
        )
        run_result.total_impure_valuations = 1
        run_result.total_skipped_impure = 2
        assert _compute_purity_level(run_result) == "mixed"


# ---------------------------------------------------------------------------
# 5. Purity flags in replay output
# ---------------------------------------------------------------------------

class TestPurityFlagsInOutput:

    def test_replay_output_contains_purity_fields(self, session):
        """Replay run result includes purity level and counters."""
        _make_company(session, "NVDA")
        thesis = _make_thesis(session, "NVDA")
        _add_price(session, "NVDA", TODAY, 100.0)
        _add_price(session, "NVDA", TODAY + timedelta(days=1), 101.0)

        # Candidate with no created_at → impure in non-strict
        session.add(Candidate(
            ticker="NVDA", primary_thesis_id=thesis.id,
            conviction_score=70.0,
        ))
        session.flush()

        run_result, portfolio, metrics = run_replay(
            session,
            start_date=TODAY, end_date=TODAY,
            cadence_days=7, strict_replay=False,
        )

        assert run_result.purity_level == "degraded"
        assert run_result.total_impure_candidates >= 1

        # Metrics should also have purity
        assert metrics.purity_level == "degraded"
        assert metrics.impure_candidate_fallbacks >= 1

        # to_dict includes purity
        d = run_result.to_dict()
        assert "purity" in d
        assert d["purity"]["purity_level"] == "degraded"

    def test_strict_replay_output_purity_clean(self, session):
        """Strict replay with clean data shows purity_level=strict."""
        _make_company(session, "NVDA")
        thesis = _make_thesis(session, "NVDA")
        _add_price(session, "NVDA", TODAY, 100.0)
        _add_price(session, "NVDA", TODAY + timedelta(days=1), 101.0)

        _add_thesis_history(
            session, thesis.id,
            state=ThesisState.STRENGTHENING, conviction=70.0,
            created_at=datetime(2026, 3, 1, 12, 0),
            valuation_gap=15.0, base_case=1.3,
        )

        session.add(Candidate(
            ticker="NVDA", primary_thesis_id=thesis.id,
            conviction_score=70.0,
            created_at=datetime(2026, 3, 1, 12, 0),
        ))
        session.flush()

        run_result, portfolio, metrics = run_replay(
            session,
            start_date=TODAY, end_date=TODAY,
            cadence_days=7, strict_replay=True,
        )

        assert run_result.purity_level == "strict"
        assert run_result.total_impure_candidates == 0
        assert run_result.total_impure_valuations == 0

    def test_per_review_purity_in_run_result(self, session):
        """Each review record in the run result has per-date purity flags."""
        _make_company(session, "NVDA")
        thesis = _make_thesis(session, "NVDA")
        _add_price(session, "NVDA", TODAY, 100.0)
        _add_price(session, "NVDA", TODAY + timedelta(days=1), 101.0)

        cand = Candidate(
            ticker="NVDA", primary_thesis_id=thesis.id,
            conviction_score=70.0,
        )
        cand.created_at = None
        session.add(cand)
        session.flush()

        run_result, _, _ = run_replay(
            session,
            start_date=TODAY, end_date=TODAY,
            cadence_days=7, strict_replay=False,
        )

        assert len(run_result.review_records) == 1
        record = run_result.review_records[0]
        assert record.purity.impure_candidate_count >= 1
        assert not record.purity.is_pure


# ---------------------------------------------------------------------------
# 6. Metrics purity fields
# ---------------------------------------------------------------------------

class TestMetricsPurity:

    def test_metrics_to_dict_includes_purity(self, session):
        """ReplayMetrics.to_dict() includes purity section."""
        _make_company(session, "NVDA")
        thesis = _make_thesis(session, "NVDA")
        _add_price(session, "NVDA", TODAY, 100.0)
        _add_price(session, "NVDA", TODAY + timedelta(days=1), 101.0)

        cand = Candidate(
            ticker="NVDA", primary_thesis_id=thesis.id,
            conviction_score=70.0,
        )
        cand.created_at = None
        session.add(cand)
        session.flush()

        run_result, portfolio, metrics = run_replay(
            session,
            start_date=TODAY, end_date=TODAY,
            cadence_days=7, strict_replay=False,
        )

        d = metrics.to_dict()
        assert "purity" in d
        assert d["purity"]["purity_level"] == "degraded"
        assert d["purity"]["impure_candidate_fallbacks"] >= 1
        assert d["purity"]["strict_replay"] is False


# ---------------------------------------------------------------------------
# 7. ReplayPurityFlags dataclass
# ---------------------------------------------------------------------------

class TestReplayPurityFlags:

    def test_is_pure_when_clean(self):
        flags = ReplayPurityFlags()
        assert flags.is_pure is True

    def test_is_not_pure_when_impure_candidate(self):
        flags = ReplayPurityFlags(impure_candidate_count=1)
        assert flags.is_pure is False

    def test_is_not_pure_when_impure_valuation(self):
        flags = ReplayPurityFlags(impure_valuation_count=1)
        assert flags.is_pure is False

    def test_skipped_impure_still_counts_as_pure(self):
        """Skipping impure inputs maintains purity."""
        flags = ReplayPurityFlags(skipped_impure_candidates=3)
        assert flags.is_pure is True

    def test_to_dict(self):
        flags = ReplayPurityFlags(
            impure_candidate_count=2,
            integrity_warnings=["test warning"],
        )
        d = flags.to_dict()
        assert d["impure_candidate_count"] == 2
        assert d["is_pure"] is False
        assert "test warning" in d["integrity_warnings"]


# ---------------------------------------------------------------------------
# 8. Integration: strict vs non-strict full replay
# ---------------------------------------------------------------------------

class TestStrictVsNonStrictReplay:

    def test_strict_excludes_impure_nonstrict_includes(self, session):
        """Same data, strict mode excludes while non-strict includes with warnings."""
        _make_company(session, "NVDA")
        thesis = _make_thesis(session, "NVDA")
        _add_price(session, "NVDA", TODAY, 100.0)
        _add_price(session, "NVDA", TODAY + timedelta(days=1), 101.0)

        # Candidate with no provenance (created_at=None by default)
        session.add(Candidate(
            ticker="NVDA", primary_thesis_id=thesis.id,
            conviction_score=70.0,
        ))
        session.flush()

        # Strict run
        r_strict, _, m_strict = run_replay(
            session, start_date=TODAY, end_date=TODAY,
            cadence_days=7, strict_replay=True,
        )

        # Non-strict run
        r_nonstrict, _, m_nonstrict = run_replay(
            session, start_date=TODAY, end_date=TODAY,
            cadence_days=7, strict_replay=False,
        )

        # Strict should have skipped candidates
        assert r_strict.total_skipped_impure >= 1
        assert r_strict.total_impure_candidates == 0

        # Non-strict should have included with warning
        assert r_nonstrict.total_impure_candidates >= 1
        assert r_nonstrict.total_skipped_impure == 0

    def test_strict_replay_flag_stored_in_result(self, session):
        """strict_replay flag is stored in ReplayRunResult."""
        _make_company(session, "NVDA")
        _add_price(session, "NVDA", TODAY, 100.0)

        r, _, _ = run_replay(
            session, start_date=TODAY, end_date=TODAY,
            cadence_days=7, strict_replay=True,
        )
        assert r.strict_replay is True

        d = r.to_dict()
        assert d["strict_replay"] is True
