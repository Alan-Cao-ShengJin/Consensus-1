"""Tests for the empirical diagnostics and policy improvement layer.

Tests:
1. Hold decisions preserve usable conviction fields
2. Probation/exit event tables generate with expected columns
3. Policy variant selection works and affects outputs
4. Policy comparison generates correctly
5. Multi-window aggregation works
6. Premature-exit / recovery detection works
7. Enhanced failure analysis works
8. Deterministic behavior holds for same inputs
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import date
from dataclasses import dataclass

import pytest

sys.path.insert(0, ".")

from portfolio_decision_engine import (
    evaluate_holding, evaluate_candidate,
    HoldingSnapshot, CandidateSnapshot, DecisionInput,
    run_decision_engine, ActionType,
    BASELINE_POLICY,
)
from exit_policy import (
    ExitPolicyConfig, ExitPolicyMode, BASELINE_POLICY, PATIENT_POLICY,
    GRADUATED_POLICY, get_policy, ALL_POLICIES,
)
from models import ThesisState, ZoneState


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_holding(
    ticker="TEST",
    conviction=60.0,
    thesis_state=ThesisState.STABLE,
    probation_flag=False,
    probation_reviews=0,
    prior_conviction=None,
    current_weight=3.0,
) -> HoldingSnapshot:
    return HoldingSnapshot(
        ticker=ticker,
        position_id=1,
        thesis_id=1,
        thesis_state=thesis_state,
        conviction_score=conviction,
        current_weight=current_weight,
        target_weight=current_weight,
        avg_cost=100.0,
        current_price=100.0,
        probation_flag=probation_flag,
        probation_reviews_count=probation_reviews,
        prior_conviction=prior_conviction,
    )


def _make_action_outcome(
    review_date, ticker, action, thesis_conviction, action_score=0.0,
    fwd_5d=None, fwd_20d=None, fwd_60d=None,
):
    """Create a mock ActionOutcome-like object for testing."""
    @dataclass
    class MockOutcome:
        review_date: date
        ticker: str
        action: str
        thesis_conviction: float
        action_score: float
        conviction_bucket: str = "medium"
        rationale: str = ""
        forward_5d: float = None
        forward_20d: float = None
        forward_60d: float = None
        price_at_decision: float = None

        @property
        def conviction(self):
            return self.thesis_conviction

    return MockOutcome(
        review_date=review_date,
        ticker=ticker,
        action=action,
        thesis_conviction=thesis_conviction,
        action_score=action_score,
        forward_5d=fwd_5d,
        forward_20d=fwd_20d,
        forward_60d=fwd_60d,
    )


# ---------------------------------------------------------------------------
# Test 1: Hold decisions preserve thesis conviction
# ---------------------------------------------------------------------------

class TestHoldConviction:
    def test_hold_has_thesis_conviction(self):
        """Hold action should have thesis_conviction set, not just 0."""
        h = _make_holding(conviction=67.5)
        d = evaluate_holding(h, date(2025, 9, 1))
        assert d.action == ActionType.HOLD
        assert d.action_score == 0.0  # action_score is 0 for holds
        assert d.thesis_conviction == 67.5  # thesis conviction is preserved

    def test_trim_has_thesis_conviction(self):
        h = _make_holding(conviction=30.0)
        d = evaluate_holding(h, date(2025, 9, 1))
        assert d.action == ActionType.TRIM  # low conviction triggers trim
        assert d.thesis_conviction == 30.0

    def test_exit_has_thesis_conviction(self):
        h = _make_holding(conviction=20.0)
        d = evaluate_holding(h, date(2025, 9, 1))
        assert d.action == ActionType.EXIT
        assert d.thesis_conviction == 20.0

    def test_candidate_has_thesis_conviction(self):
        c = CandidateSnapshot(ticker="TEST", conviction_score=62.0,
                              thesis_id=1, thesis_state=ThesisState.STABLE)
        d = evaluate_candidate(c, None, date(2025, 9, 1), relaxed_gates=True)
        assert d.thesis_conviction == 62.0

    def test_to_dict_includes_thesis_conviction(self):
        h = _make_holding(conviction=55.0)
        d = evaluate_holding(h, date(2025, 9, 1))
        dd = d.to_dict()
        assert "thesis_conviction" in dd
        assert dd["thesis_conviction"] == 55.0


# ---------------------------------------------------------------------------
# Test 2: Probation/exit event generation
# ---------------------------------------------------------------------------

class TestDeteriorationDiagnostics:
    def test_probation_event_extracted(self):
        from empirical_diagnostics import compute_deterioration_diagnostics
        outcomes = [
            _make_action_outcome(date(2025, 8, 1), "AAPL", "hold", 60.0),
            _make_action_outcome(date(2025, 8, 8), "AAPL", "probation", 30.0, action_score=65.0, fwd_20d=-5.0),
            _make_action_outcome(date(2025, 8, 15), "AAPL", "exit", 20.0, action_score=95.0, fwd_20d=8.0),
        ]
        diag = compute_deterioration_diagnostics(outcomes)
        assert diag.total_probations == 1
        assert diag.total_exits == 1
        assert diag.probation_events[0].ticker == "AAPL"
        assert diag.probation_events[0].followed_by_exit is True
        assert diag.exit_events[0].preceded_by_probation is True

    def test_premature_exit_detected(self):
        from empirical_diagnostics import compute_deterioration_diagnostics
        outcomes = [
            _make_action_outcome(date(2025, 8, 1), "TSLA", "exit", 22.0, action_score=95.0,
                                 fwd_20d=12.0, fwd_60d=25.0),
        ]
        diag = compute_deterioration_diagnostics(outcomes)
        assert diag.premature_exits_20d == 1
        assert diag.premature_exits_60d == 1
        assert diag.exit_events[0].recovery_20d is True
        assert diag.exit_events[0].recovery_60d is True

    def test_false_alarm_probation(self):
        from empirical_diagnostics import compute_deterioration_diagnostics
        outcomes = [
            _make_action_outcome(date(2025, 8, 1), "GOOGL", "probation", 33.0, fwd_20d=10.0),
            _make_action_outcome(date(2025, 8, 8), "GOOGL", "hold", 45.0),
        ]
        diag = compute_deterioration_diagnostics(outcomes)
        assert diag.probation_false_alarm_count == 1

    def test_empty_outcomes(self):
        from empirical_diagnostics import compute_deterioration_diagnostics
        diag = compute_deterioration_diagnostics([])
        assert diag.total_probations == 0
        assert diag.total_exits == 0

    def test_probation_event_has_expected_fields(self):
        from empirical_diagnostics import compute_deterioration_diagnostics
        outcomes = [
            _make_action_outcome(date(2025, 8, 1), "X", "hold", 50.0),
            _make_action_outcome(date(2025, 8, 8), "X", "probation", 32.0, action_score=65.0),
        ]
        diag = compute_deterioration_diagnostics(outcomes)
        pe = diag.probation_events[0]
        d = pe.to_dict()
        assert "review_date" in d
        assert "ticker" in d
        assert "thesis_conviction" in d
        assert "prior_action" in d
        assert "followed_by_exit" in d

    def test_exit_event_has_expected_fields(self):
        from empirical_diagnostics import compute_deterioration_diagnostics
        outcomes = [
            _make_action_outcome(date(2025, 8, 1), "X", "exit", 20.0, action_score=95.0),
        ]
        diag = compute_deterioration_diagnostics(outcomes)
        ee = diag.exit_events[0]
        d = ee.to_dict()
        assert "review_date" in d
        assert "premature_exit_20d" in d
        assert "preceded_by_probation" in d


# ---------------------------------------------------------------------------
# Test 3: Policy variant selection
# ---------------------------------------------------------------------------

class TestPolicyVariants:
    def test_get_policy_by_name(self):
        p = get_policy("baseline")
        assert p.mode == ExitPolicyMode.BASELINE

        p = get_policy("patient")
        assert p.mode == ExitPolicyMode.PATIENT
        assert p.probation_max_reviews == 3
        assert p.exit_conviction_ceiling == 20.0

        p = get_policy("graduated")
        assert p.mode == ExitPolicyMode.GRADUATED

    def test_invalid_policy_raises(self):
        with pytest.raises(ValueError):
            get_policy("nonexistent")

    def test_baseline_exit_at_25(self):
        h = _make_holding(conviction=24.0)
        d = evaluate_holding(h, date(2025, 9, 1), exit_policy=BASELINE_POLICY)
        assert d.action == ActionType.EXIT

    def test_patient_no_exit_at_24(self):
        """Patient policy has exit ceiling at 20, so conviction 24 should trim, not exit."""
        h = _make_holding(conviction=24.0)
        d = evaluate_holding(h, date(2025, 9, 1), exit_policy=PATIENT_POLICY)
        assert d.action == ActionType.TRIM  # 24 <= 35 (trim), but > 20 (exit)

    def test_patient_exit_at_19(self):
        h = _make_holding(conviction=19.0)
        d = evaluate_holding(h, date(2025, 9, 1), exit_policy=PATIENT_POLICY)
        assert d.action == ActionType.EXIT

    def test_patient_low_conviction_trims(self):
        """Patient policy: conviction 30 triggers trim (probation replaced)."""
        h = _make_holding(conviction=30.0)
        d = evaluate_holding(h, date(2025, 9, 1), exit_policy=PATIENT_POLICY)
        assert d.action == ActionType.TRIM  # low conviction → trim

    def test_graduated_sharp_drop_exit(self):
        """Graduated policy: sharp conviction drop triggers immediate exit."""
        h = _make_holding(conviction=45.0, prior_conviction=65.0)
        d = evaluate_holding(h, date(2025, 9, 1), exit_policy=GRADUATED_POLICY)
        assert d.action == ActionType.EXIT  # drop of 20 > threshold of 15
        assert "Sharp conviction drop" in d.rationale

    def test_graduated_moderate_drop_no_exit(self):
        """Graduated policy: moderate drop does NOT trigger immediate exit."""
        h = _make_holding(conviction=55.0, prior_conviction=65.0)
        d = evaluate_holding(h, date(2025, 9, 1), exit_policy=GRADUATED_POLICY)
        assert d.action == ActionType.HOLD  # drop of 10 < threshold of 15

    def test_baseline_low_conviction_trims(self):
        """Baseline: conviction 30 triggers trim."""
        h = _make_holding(conviction=30.0)
        d = evaluate_holding(h, date(2025, 9, 1), exit_policy=BASELINE_POLICY)
        assert d.action == ActionType.TRIM

    def test_policy_affects_outputs(self):
        """Different policies produce different actions for same holding."""
        # Conviction 24: baseline exits (ceiling=25), patient trims (ceiling=20)
        h = _make_holding(conviction=24.0)
        d_baseline = evaluate_holding(h, date(2025, 9, 1), exit_policy=BASELINE_POLICY)
        d_patient = evaluate_holding(h, date(2025, 9, 1), exit_policy=PATIENT_POLICY)
        assert d_baseline.action == ActionType.EXIT
        assert d_patient.action == ActionType.TRIM  # 24 > patient exit ceiling (20)

    def test_all_policies_list(self):
        assert len(ALL_POLICIES) == 3


# ---------------------------------------------------------------------------
# Test 4: Policy comparison table
# ---------------------------------------------------------------------------

class TestPolicyComparison:
    def test_comparison_generates(self):
        from empirical_diagnostics import build_policy_comparison, DeteriorationDiagnostics

        # Mock eval results
        @dataclass
        class MockMetrics:
            total_return_pct: float = 3.0
            annualized_return_pct: float = 6.0
            max_drawdown_pct: float = 5.0

        @dataclass
        class MockDiagnostics:
            action_counts: dict = None
            def __post_init__(self):
                if self.action_counts is None:
                    self.action_counts = {"hold": 100, "initiate": 5, "exit": 1, "probation": 2}

        @dataclass
        class MockEvalResult:
            metrics: MockMetrics = None
            diagnostics: MockDiagnostics = None
            best_decisions: list = None
            worst_decisions: list = None
            def __post_init__(self):
                self.metrics = MockMetrics()
                self.diagnostics = MockDiagnostics()
                self.best_decisions = []
                self.worst_decisions = []

        policy_results = {
            "baseline": MockEvalResult(),
            "patient": MockEvalResult(),
        }
        policy_diags = {
            "baseline": DeteriorationDiagnostics(total_exits=1, premature_exits_20d=0, premature_exits_60d=0),
            "patient": DeteriorationDiagnostics(total_exits=0, premature_exits_20d=0, premature_exits_60d=0),
        }

        comp = build_policy_comparison(policy_results, policy_diags)
        assert "baseline" in comp.policy_results
        assert "patient" in comp.policy_results
        assert comp.policy_results["baseline"]["return_pct"] == 3.0


# ---------------------------------------------------------------------------
# Test 5: Multi-window aggregation
# ---------------------------------------------------------------------------

class TestMultiWindow:
    def test_aggregate_multiple_windows(self):
        from empirical_diagnostics import WindowResult, aggregate_multi_window

        windows = [
            WindowResult("W1", date(2025, 3, 1), date(2025, 7, 1), return_pct=5.0, max_drawdown_pct=3.0, total_actions=50, exit_count=1, premature_exits=0),
            WindowResult("W2", date(2025, 7, 1), date(2025, 12, 1), return_pct=-2.0, max_drawdown_pct=8.0, total_actions=60, exit_count=2, premature_exits=1),
            WindowResult("W3", date(2025, 10, 1), date(2026, 3, 1), return_pct=3.0, max_drawdown_pct=4.0, total_actions=55, exit_count=1, premature_exits=0),
        ]
        mw = aggregate_multi_window(windows)
        assert len(mw.windows) == 3
        assert mw.aggregate["avg_return_pct"] == 2.0
        assert mw.aggregate["total_exits"] == 4
        assert mw.aggregate["total_premature_exits"] == 1

    def test_sign_change_warning(self):
        from empirical_diagnostics import WindowResult, aggregate_multi_window
        windows = [
            WindowResult("W1", date(2025, 1, 1), date(2025, 6, 1), return_pct=5.0, max_drawdown_pct=3.0),
            WindowResult("W2", date(2025, 6, 1), date(2025, 12, 1), return_pct=-3.0, max_drawdown_pct=6.0),
        ]
        mw = aggregate_multi_window(windows)
        assert any("sign" in w.lower() for w in mw.warnings)

    def test_small_sample_warning(self):
        from empirical_diagnostics import WindowResult, aggregate_multi_window
        windows = [
            WindowResult("W1", date(2025, 1, 1), date(2025, 6, 1), return_pct=5.0, max_drawdown_pct=3.0),
        ]
        mw = aggregate_multi_window(windows)
        assert any("sample too small" in w.lower() for w in mw.warnings)

    def test_empty_windows(self):
        from empirical_diagnostics import aggregate_multi_window
        mw = aggregate_multi_window([])
        assert len(mw.windows) == 0
        assert "No windows" in mw.warnings[0]

    def test_generates_per_window_and_aggregate(self):
        from empirical_diagnostics import WindowResult, aggregate_multi_window
        windows = [
            WindowResult("W1", date(2025, 3, 1), date(2025, 7, 1), return_pct=4.0, max_drawdown_pct=2.0),
            WindowResult("W2", date(2025, 7, 1), date(2025, 12, 1), return_pct=6.0, max_drawdown_pct=3.0),
            WindowResult("W3", date(2025, 10, 1), date(2026, 3, 1), return_pct=2.0, max_drawdown_pct=5.0),
        ]
        mw = aggregate_multi_window(windows)
        d = mw.to_dict()
        assert len(d["windows"]) == 3
        assert "aggregate" in d
        assert d["aggregate"]["windows_count"] == 3


# ---------------------------------------------------------------------------
# Test 6: CSV writers
# ---------------------------------------------------------------------------

class TestCSVWriters:
    def test_probation_csv(self, tmp_path):
        from empirical_diagnostics import ProbationEvent, write_probation_events_csv
        events = [
            ProbationEvent(date(2025, 8, 1), "AAPL", 32.0, 65.0, forward_20d=-3.0),
        ]
        write_probation_events_csv(str(tmp_path), events)
        path = tmp_path / "probation_events.csv"
        assert path.exists()
        content = path.read_text()
        assert "thesis_conviction" in content
        assert "AAPL" in content

    def test_exit_csv(self, tmp_path):
        from empirical_diagnostics import ExitEvent, write_exit_events_csv
        events = [
            ExitEvent(date(2025, 8, 1), "TSLA", 20.0, 95.0, forward_20d=12.0, recovery_20d=True),
        ]
        write_exit_events_csv(str(tmp_path), events)
        path = tmp_path / "exit_events.csv"
        assert path.exists()
        content = path.read_text()
        assert "premature_exit_20d" in content

    def test_policy_comparison_csv(self, tmp_path):
        from empirical_diagnostics import PolicyComparisonResult, write_policy_comparison_csv
        comp = PolicyComparisonResult(policy_results={
            "baseline": {"policy": "baseline", "return_pct": 3.0, "exit_count": 1},
            "patient": {"policy": "patient", "return_pct": 3.5, "exit_count": 0},
        })
        write_policy_comparison_csv(str(tmp_path), comp)
        path = tmp_path / "policy_comparison.csv"
        assert path.exists()

    def test_window_summary_csv(self, tmp_path):
        from empirical_diagnostics import WindowResult, MultiWindowResult, write_window_summary_csv
        mw = MultiWindowResult(windows=[
            WindowResult("W1", date(2025, 3, 1), date(2025, 7, 1), return_pct=4.0, max_drawdown_pct=2.0),
        ])
        write_window_summary_csv(str(tmp_path), mw)
        path = tmp_path / "window_summary.csv"
        assert path.exists()


# ---------------------------------------------------------------------------
# Test 7: Markdown formatting
# ---------------------------------------------------------------------------

class TestMarkdownFormatting:
    def test_deterioration_section(self):
        from empirical_diagnostics import (
            DeteriorationDiagnostics, ProbationEvent, ExitEvent,
            format_deterioration_section,
        )
        diag = DeteriorationDiagnostics(
            probation_events=[ProbationEvent(date(2025, 8, 1), "X", 32.0, 65.0)],
            exit_events=[ExitEvent(date(2025, 8, 8), "X", 20.0, 95.0)],
            total_probations=1,
            total_exits=1,
        )
        lines = format_deterioration_section(diag)
        text = "\n".join(lines)
        assert "Probation/Exit Diagnostics" in text
        assert "Exit Events" in text
        assert "Probation Events" in text

    def test_policy_comparison_section(self):
        from empirical_diagnostics import PolicyComparisonResult, format_policy_comparison_section
        comp = PolicyComparisonResult(policy_results={
            "baseline": {"return_pct": 3.0, "max_drawdown_pct": 5.0, "exit_count": 1, "probation_count": 2, "premature_exits_60d": 0, "avg_exit_forward_20d_pct": 2.0},
        })
        lines = format_policy_comparison_section(comp)
        text = "\n".join(lines)
        assert "Exit Policy Comparison" in text

    def test_multi_window_section(self):
        from empirical_diagnostics import WindowResult, MultiWindowResult, format_multi_window_section
        mw = MultiWindowResult(
            windows=[WindowResult("W1", date(2025, 3, 1), date(2025, 7, 1), return_pct=4.0)],
            aggregate={"avg_return_pct": 4.0},
        )
        lines = format_multi_window_section(mw)
        text = "\n".join(lines)
        assert "Multi-Window Summary" in text


# ---------------------------------------------------------------------------
# Test 8: Deterministic behavior
# ---------------------------------------------------------------------------

class TestDeterminism:
    def test_same_inputs_same_output(self):
        """Same holding + same policy -> same decision."""
        h = _make_holding(conviction=30.0)
        d1 = evaluate_holding(h, date(2025, 9, 1), exit_policy=BASELINE_POLICY)
        d2 = evaluate_holding(h, date(2025, 9, 1), exit_policy=BASELINE_POLICY)
        assert d1.action == d2.action
        assert d1.action_score == d2.action_score
        assert d1.thesis_conviction == d2.thesis_conviction

    def test_policy_change_changes_output(self):
        h = _make_holding(conviction=24.0)
        d1 = evaluate_holding(h, date(2025, 9, 1), exit_policy=BASELINE_POLICY)
        d2 = evaluate_holding(h, date(2025, 9, 1), exit_policy=PATIENT_POLICY)
        assert d1.action != d2.action  # baseline exits, patient does probation

    def test_diagnostics_deterministic(self):
        from empirical_diagnostics import compute_deterioration_diagnostics
        outcomes = [
            _make_action_outcome(date(2025, 8, 1), "X", "probation", 30.0, fwd_20d=-5.0),
            _make_action_outcome(date(2025, 8, 8), "X", "exit", 20.0, fwd_20d=8.0),
        ]
        d1 = compute_deterioration_diagnostics(outcomes)
        d2 = compute_deterioration_diagnostics(outcomes)
        assert d1.total_probations == d2.total_probations
        assert d1.total_exits == d2.total_exits
        assert d1.premature_exits_20d == d2.premature_exits_20d
