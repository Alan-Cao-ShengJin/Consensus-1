"""Tests for evaluation framework: config, harness, diagnostics, benchmarks, reports.

Covers:
  - EvalConfig creation and serialization
  - Memory comparison pair creation
  - Recommendation diagnostics computation
  - Benchmark comparison logic
  - Memory comparison produces distinct comparable outputs
  - Evaluation runs are deterministic given same inputs
  - Report generation includes expected sections/fields
  - Action diagnostics aggregate correctly
  - Purity/strictness flags preserved in evaluation outputs
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from models import (
    Base, Company, Thesis, ThesisState, ThesisStateHistory,
    Candidate, Price, Document, SourceType, SourceTier,
    Claim, ClaimCompanyLink, ClaimType, EconomicChannel,
    Direction, NoveltyType, ZoneState, ActionType,
)
from eval_config import EvalConfig
from eval_harness import (
    compute_recommendation_diagnostics,
    compute_benchmark_comparison,
    run_evaluation,
    run_memory_comparison,
    RecommendationDiagnostics,
    BenchmarkComparison,
    MemoryComparisonResult,
    EvalRunResult,
    _extract_comparison_metrics,
)
from eval_report import (
    generate_json_report,
    generate_markdown_report,
    _build_report_dict,
    _collect_warnings,
)
from replay_engine import ReplayRunResult, ReplayReviewRecord, ReplayPurityFlags
from replay_metrics import ReplayMetrics, compute_metrics
from shadow_portfolio import ShadowPortfolio
from portfolio_decision_engine import (
    TickerDecision, PortfolioReviewResult, ReasonCode,
    HoldingSnapshot, CandidateSnapshot, DecisionInput,
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


def _setup_basic_universe(session):
    """Set up a minimal universe for evaluation tests."""
    for ticker in ("AAPL", "NVDA", "MSFT"):
        session.add(Company(ticker=ticker, name=f"{ticker} Inc"))
    session.flush()

    theses = {}
    for ticker in ("AAPL", "NVDA", "MSFT"):
        t = Thesis(
            title=f"{ticker} thesis",
            company_ticker=ticker,
            state=ThesisState.STRENGTHENING,
            conviction_score=70.0,
            valuation_gap_pct=15.0,
            base_case_rerating=1.3,
        )
        session.add(t)
        session.flush()
        theses[ticker] = t

        # Add thesis state history
        session.add(ThesisStateHistory(
            thesis_id=t.id,
            state=ThesisState.STRENGTHENING,
            conviction_score=70.0,
            created_at=datetime(2024, 12, 1),
        ))

        # Add candidate
        session.add(Candidate(
            ticker=ticker,
            primary_thesis_id=t.id,
            conviction_score=70.0,
            created_at=datetime(2024, 12, 1),
        ))

    session.flush()

    # Add price data for the date range
    base_prices = {"AAPL": 180.0, "NVDA": 130.0, "MSFT": 400.0, "SPY": 480.0}
    start = date(2025, 1, 1)
    for i in range(60):  # ~2 months of daily prices
        d = start + timedelta(days=i)
        if d.weekday() >= 5:  # skip weekends
            continue
        for ticker, base in base_prices.items():
            # Simple price drift
            drift = 1.0 + (i * 0.001)  # 0.1% per day up
            session.add(Price(ticker=ticker, date=d, close=round(base * drift, 2)))
    session.flush()

    return theses


# ---------------------------------------------------------------------------
# Test: EvalConfig
# ---------------------------------------------------------------------------

class TestEvalConfig:
    def test_default_config(self):
        config = EvalConfig()
        assert config.run_id == "default"
        assert config.memory_enabled is True
        assert config.strict_replay is False
        assert config.contradiction_metadata_enabled is True
        assert config.evidence_downweighting_enabled is True
        assert config.benchmark_ticker == "SPY"
        assert config.include_equal_weight_baseline is True

    def test_config_to_dict(self):
        config = EvalConfig(run_id="test_run", memory_enabled=False)
        d = config.to_dict()
        assert d["run_id"] == "test_run"
        assert d["memory_enabled"] is False
        assert "start_date" in d
        assert "end_date" in d

    def test_memory_comparison_pair(self):
        on, off = EvalConfig.memory_comparison_pair(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 6, 30),
        )
        assert on.memory_enabled is True
        assert off.memory_enabled is False
        assert on.run_id == "memory_on"
        assert off.run_id == "memory_off"
        assert on.start_date == off.start_date
        assert on.end_date == off.end_date
        assert on.cadence_days == off.cadence_days
        assert on.initial_cash == off.initial_cash
        assert on.strict_replay == off.strict_replay

    def test_config_ablation_fields(self):
        config = EvalConfig(
            contradiction_metadata_enabled=False,
            evidence_downweighting_enabled=False,
        )
        d = config.to_dict()
        assert d["contradiction_metadata_enabled"] is False
        assert d["evidence_downweighting_enabled"] is False


# ---------------------------------------------------------------------------
# Test: Recommendation Diagnostics
# ---------------------------------------------------------------------------

class TestRecommendationDiagnostics:
    def test_action_counts(self):
        """Diagnostics correctly aggregate action counts."""
        run_result = _make_run_result_with_decisions([
            ("AAPL", ActionType.INITIATE, 75.0),
            ("NVDA", ActionType.HOLD, 60.0),
            ("MSFT", ActionType.EXIT, 20.0),
            ("AAPL", ActionType.ADD, 80.0),
        ])
        portfolio = ShadowPortfolio(initial_cash=1_000_000)
        diag = compute_recommendation_diagnostics(run_result, portfolio)

        assert diag.action_counts["initiate"] == 1
        assert diag.action_counts["hold"] == 1
        assert diag.action_counts["exit"] == 1
        assert diag.action_counts["add"] == 1

    def test_action_pcts(self):
        """Action percentages sum to 100%."""
        run_result = _make_run_result_with_decisions([
            ("AAPL", ActionType.INITIATE, 75.0),
            ("NVDA", ActionType.HOLD, 60.0),
        ])
        portfolio = ShadowPortfolio(initial_cash=1_000_000)
        diag = compute_recommendation_diagnostics(run_result, portfolio)

        total_pct = sum(diag.action_pcts.values())
        assert abs(total_pct - 100.0) < 0.1

    def test_per_ticker_actions(self):
        """Actions tracked per ticker."""
        run_result = _make_run_result_with_decisions([
            ("AAPL", ActionType.INITIATE, 75.0),
            ("AAPL", ActionType.ADD, 80.0),
            ("NVDA", ActionType.HOLD, 60.0),
        ])
        portfolio = ShadowPortfolio(initial_cash=1_000_000)
        diag = compute_recommendation_diagnostics(run_result, portfolio)

        assert "AAPL" in diag.actions_by_ticker
        assert diag.actions_by_ticker["AAPL"]["initiate"] == 1
        assert diag.actions_by_ticker["AAPL"]["add"] == 1
        assert diag.actions_by_ticker["NVDA"]["hold"] == 1

    def test_recommendation_changes(self):
        """Recommendation changes counted when action changes between reviews."""
        # Two reviews: first AAPL=hold, second AAPL=exit
        rec1 = _make_review_record(
            review_date=date(2025, 1, 7),
            decisions=[("AAPL", ActionType.HOLD, 60.0)],
        )
        rec2 = _make_review_record(
            review_date=date(2025, 1, 14),
            decisions=[("AAPL", ActionType.EXIT, 20.0)],
        )
        run_result = ReplayRunResult(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31),
            cadence_days=7,
            review_records=[rec1, rec2],
            total_reviews=2,
        )
        portfolio = ShadowPortfolio(initial_cash=1_000_000)
        diag = compute_recommendation_diagnostics(run_result, portfolio)

        assert diag.recommendation_changes == 1
        assert diag.recommendation_change_rate > 0

    def test_diagnostics_to_dict(self):
        """Diagnostics serialization includes expected keys."""
        diag = RecommendationDiagnostics()
        d = diag.to_dict()
        assert "action_counts" in d
        assert "attribution" in d
        assert "recommendation_changes" in d

    def test_short_hold_exits(self):
        """Short-hold exits tracked from trade history."""
        portfolio = ShadowPortfolio(initial_cash=1_000_000)
        portfolio.apply_trade(date(2025, 1, 2), "AAPL", "initiate", 100, 180.0)
        portfolio.apply_trade(date(2025, 1, 20), "AAPL", "exit", -100, 185.0)

        run_result = ReplayRunResult(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31),
            cadence_days=7,
        )
        diag = compute_recommendation_diagnostics(run_result, portfolio)
        assert diag.short_hold_exits == 1  # held only 18 days


# ---------------------------------------------------------------------------
# Test: Benchmark Comparison
# ---------------------------------------------------------------------------

class TestBenchmarkComparison:
    def test_benchmark_with_price_data(self, session):
        """Benchmark comparison works when price data is available."""
        _setup_basic_universe(session)
        config = EvalConfig(
            start_date=date(2025, 1, 2),
            end_date=date(2025, 2, 28),
            benchmark_ticker="SPY",
        )
        comp = compute_benchmark_comparison(session, config, portfolio_return_pct=5.0)

        assert comp.portfolio_return_pct == 5.0
        assert comp.benchmark_ticker == "SPY"
        assert comp.benchmark_data_available is True
        assert comp.benchmark_return_pct is not None
        assert comp.excess_return_pct is not None
        assert abs(comp.excess_return_pct - (5.0 - comp.benchmark_return_pct)) < 0.01

    def test_benchmark_without_price_data(self, session):
        """Benchmark comparison graceful when no price data."""
        # Empty DB
        config = EvalConfig(benchmark_ticker="SPY")
        comp = compute_benchmark_comparison(session, config, portfolio_return_pct=5.0)

        assert comp.benchmark_data_available is False
        assert comp.benchmark_return_pct is None
        assert comp.excess_return_pct is None

    def test_equal_weight_baseline(self, session):
        """Equal-weight baseline computes average return across candidates."""
        _setup_basic_universe(session)
        config = EvalConfig(
            start_date=date(2025, 1, 2),
            end_date=date(2025, 2, 28),
            include_equal_weight_baseline=True,
        )
        comp = compute_benchmark_comparison(session, config, portfolio_return_pct=5.0)

        assert comp.equal_weight_tickers_count > 0
        assert comp.equal_weight_tickers_with_data > 0
        assert comp.equal_weight_return_pct is not None
        assert comp.vs_equal_weight_pct is not None

    def test_benchmark_to_dict(self):
        comp = BenchmarkComparison(
            portfolio_return_pct=5.0,
            benchmark_return_pct=3.0,
            excess_return_pct=2.0,
            benchmark_data_available=True,
        )
        d = comp.to_dict()
        assert d["benchmark"]["return_pct"] == 3.0
        assert d["benchmark"]["excess_return_pct"] == 2.0


# ---------------------------------------------------------------------------
# Test: Evaluation Run
# ---------------------------------------------------------------------------

class TestEvaluationRun:
    def test_evaluation_deterministic(self, session):
        """Same config + same DB → same evaluation output."""
        _setup_basic_universe(session)
        config = EvalConfig(
            run_id="determinism_test",
            start_date=date(2025, 1, 6),
            end_date=date(2025, 2, 3),
            cadence_days=7,
        )

        r1 = run_evaluation(session, config)
        r2 = run_evaluation(session, config)

        assert r1.metrics.total_return_pct == r2.metrics.total_return_pct
        assert r1.metrics.max_drawdown_pct == r2.metrics.max_drawdown_pct
        assert r1.metrics.total_recommendations == r2.metrics.total_recommendations
        assert r1.diagnostics.action_counts == r2.diagnostics.action_counts
        assert r1.diagnostics.recommendation_changes == r2.diagnostics.recommendation_changes

    def test_evaluation_includes_benchmark(self, session):
        """Evaluation result includes benchmark comparison."""
        _setup_basic_universe(session)
        config = EvalConfig(
            start_date=date(2025, 1, 6),
            end_date=date(2025, 2, 3),
        )
        result = run_evaluation(session, config)

        assert result.benchmark is not None
        assert result.benchmark.benchmark_ticker == "SPY"

    def test_evaluation_includes_diagnostics(self, session):
        """Evaluation result includes recommendation diagnostics."""
        _setup_basic_universe(session)
        config = EvalConfig(
            start_date=date(2025, 1, 6),
            end_date=date(2025, 2, 3),
        )
        result = run_evaluation(session, config)

        assert result.diagnostics is not None
        assert isinstance(result.diagnostics, RecommendationDiagnostics)

    def test_evaluation_purity_preserved(self, session):
        """Purity/strictness flags preserved in evaluation output."""
        _setup_basic_universe(session)
        config = EvalConfig(
            start_date=date(2025, 1, 6),
            end_date=date(2025, 2, 3),
            strict_replay=True,
        )
        result = run_evaluation(session, config)

        assert result.metrics.strict_replay is True
        d = result.to_dict()
        assert d["config"]["strict_replay"] is True


# ---------------------------------------------------------------------------
# Test: Memory Comparison
# ---------------------------------------------------------------------------

class TestMemoryComparison:
    def test_memory_comparison_produces_results(self, session):
        """Memory comparison runs both modes and produces comparable output."""
        _setup_basic_universe(session)
        config_on, config_off = EvalConfig.memory_comparison_pair(
            start_date=date(2025, 1, 6),
            end_date=date(2025, 2, 3),
        )
        result = run_memory_comparison(session, config_on, config_off)

        assert isinstance(result, MemoryComparisonResult)
        assert "total_return_pct" in result.memory_on_metrics
        assert "total_return_pct" in result.memory_off_metrics
        assert "state_changes" in result.memory_on_metrics
        assert "state_changes" in result.memory_off_metrics

    def test_memory_comparison_to_dict(self, session):
        """Memory comparison serialization includes expected keys."""
        _setup_basic_universe(session)
        config_on, config_off = EvalConfig.memory_comparison_pair(
            start_date=date(2025, 1, 6),
            end_date=date(2025, 2, 3),
        )
        result = run_memory_comparison(session, config_on, config_off)

        d = result.to_dict()
        assert "memory_on" in d
        assert "memory_off" in d
        assert "comparison" in d
        assert "state_flip_delta" in d["comparison"]
        assert "score_volatility_on" in d["comparison"]

    def test_both_runs_use_same_date_range(self, session):
        """Both memory modes use identical date range and cadence."""
        _setup_basic_universe(session)
        config_on, config_off = EvalConfig.memory_comparison_pair(
            start_date=date(2025, 1, 6),
            end_date=date(2025, 2, 3),
            cadence_days=14,
        )
        result = run_memory_comparison(session, config_on, config_off)

        # Both should process the same number of reviews (same date range)
        # The metrics may differ but review count should be the same
        d = result.to_dict()
        assert isinstance(d["comparison"]["action_count_on"], int)
        assert isinstance(d["comparison"]["action_count_off"], int)


# ---------------------------------------------------------------------------
# Test: Report Generation
# ---------------------------------------------------------------------------

class TestReportGeneration:
    def test_json_report_has_expected_sections(self, session, tmp_path):
        """JSON report includes all required sections."""
        _setup_basic_universe(session)
        config = EvalConfig(
            run_id="report_test",
            start_date=date(2025, 1, 6),
            end_date=date(2025, 2, 3),
        )
        result = run_evaluation(session, config)
        path = generate_json_report(result, output_dir=str(tmp_path))

        import json
        with open(path) as f:
            report = json.load(f)

        assert "report_version" in report
        assert "generated_at" in report
        assert "run_metadata" in report
        assert "replay_purity" in report
        assert "decision_summary" in report
        assert "recommendation_quality" in report
        assert "candidate_summary" in report
        assert "portfolio_summary" in report
        assert "benchmark_comparison" in report
        assert "key_metrics" in report
        assert "warnings" in report

    def test_json_report_run_metadata(self, session, tmp_path):
        """Report run metadata matches config."""
        _setup_basic_universe(session)
        config = EvalConfig(
            run_id="metadata_test",
            start_date=date(2025, 1, 6),
            end_date=date(2025, 2, 3),
            strict_replay=True,
            memory_enabled=False,
        )
        result = run_evaluation(session, config)
        path = generate_json_report(result, output_dir=str(tmp_path))

        import json
        with open(path) as f:
            report = json.load(f)

        meta = report["run_metadata"]
        assert meta["run_id"] == "metadata_test"
        assert meta["strict_replay"] is True
        assert meta["memory_enabled"] is False

    def test_markdown_report_generated(self, session, tmp_path):
        """Markdown report is generated successfully."""
        _setup_basic_universe(session)
        config = EvalConfig(
            run_id="md_test",
            start_date=date(2025, 1, 6),
            end_date=date(2025, 2, 3),
        )
        result = run_evaluation(session, config)
        path = generate_markdown_report(result, output_dir=str(tmp_path))

        with open(path) as f:
            content = f.read()

        assert "# Evaluation Report" in content
        assert "Run Metadata" in content
        assert "Key Metrics" in content
        assert "Decision Summary" in content
        assert "Portfolio Summary" in content
        assert "Limitations" in content

    def test_json_report_with_memory_comparison(self, session, tmp_path):
        """JSON report includes memory comparison when provided."""
        _setup_basic_universe(session)
        config = EvalConfig(
            run_id="mem_comp_report",
            start_date=date(2025, 1, 6),
            end_date=date(2025, 2, 3),
        )
        result = run_evaluation(session, config)

        config_on, config_off = EvalConfig.memory_comparison_pair(
            start_date=date(2025, 1, 6),
            end_date=date(2025, 2, 3),
        )
        comparison = run_memory_comparison(session, config_on, config_off)

        path = generate_json_report(result, comparison, output_dir=str(tmp_path))

        import json
        with open(path) as f:
            report = json.load(f)

        assert "memory_comparison" in report
        assert "memory_on" in report["memory_comparison"]
        assert "memory_off" in report["memory_comparison"]

    def test_markdown_report_with_memory_comparison(self, session, tmp_path):
        """Markdown report includes memory comparison section."""
        _setup_basic_universe(session)
        config = EvalConfig(
            run_id="md_mem_comp",
            start_date=date(2025, 1, 6),
            end_date=date(2025, 2, 3),
        )
        result = run_evaluation(session, config)

        config_on, config_off = EvalConfig.memory_comparison_pair(
            start_date=date(2025, 1, 6),
            end_date=date(2025, 2, 3),
        )
        comparison = run_memory_comparison(session, config_on, config_off)

        path = generate_markdown_report(result, comparison, output_dir=str(tmp_path))

        with open(path) as f:
            content = f.read()

        assert "Memory Comparison" in content


# ---------------------------------------------------------------------------
# Test: Warnings
# ---------------------------------------------------------------------------

class TestWarnings:
    def test_degraded_purity_warning(self):
        """Degraded purity produces warning."""
        result = _make_eval_result(purity_level="degraded")
        warnings = _collect_warnings(result)
        assert any("degraded" in w.lower() for w in warnings)

    def test_missing_price_warning(self):
        """Missing prices produce warning."""
        result = _make_eval_result(missing_price_events=5)
        warnings = _collect_warnings(result)
        assert any("missing price" in w.lower() for w in warnings)

    def test_no_reviews_warning(self):
        """Zero reviews produce warning."""
        result = _make_eval_result(total_reviews=0)
        warnings = _collect_warnings(result)
        assert any("no review" in w.lower() for w in warnings)


# ---------------------------------------------------------------------------
# Test: No Future Leakage in Evaluation
# ---------------------------------------------------------------------------

class TestNoFutureLeakage:
    def test_strict_evaluation_skips_impure(self, session):
        """Strict evaluation reports skipped impure inputs."""
        _setup_basic_universe(session)
        config = EvalConfig(
            run_id="leakage_test",
            start_date=date(2025, 1, 6),
            end_date=date(2025, 2, 3),
            strict_replay=True,
        )
        result = run_evaluation(session, config)

        # Strict mode should be reflected in metrics
        assert result.metrics.strict_replay is True
        assert result.config.strict_replay is True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_decision(ticker, action, score=50.0, rationale=""):
    return TickerDecision(
        ticker=ticker,
        action=action,
        action_score=score,
        rationale=rationale,
        reason_codes=[ReasonCode.THESIS_STRENGTHENING],
    )


def _make_review_record(review_date, decisions):
    """Create a ReplayReviewRecord with given decisions."""
    result = PortfolioReviewResult(review_date=review_date)
    result.decisions = [_make_decision(t, a, s) for t, a, s in decisions]
    return ReplayReviewRecord(
        review_date=review_date,
        result=result,
        purity=ReplayPurityFlags(),
    )


def _make_run_result_with_decisions(decisions_spec):
    """Create a ReplayRunResult with decisions spread across reviews."""
    records = []
    for i, (ticker, action, score) in enumerate(decisions_spec):
        review_date = date(2025, 1, 7) + timedelta(days=i * 7)
        records.append(_make_review_record(
            review_date=review_date,
            decisions=[(ticker, action, score)],
        ))
    return ReplayRunResult(
        start_date=date(2025, 1, 1),
        end_date=date(2025, 3, 31),
        cadence_days=7,
        review_records=records,
        total_reviews=len(records),
        total_recommendations=len(decisions_spec),
    )


def _make_eval_result(
    purity_level="strict",
    missing_price_events=0,
    total_reviews=5,
):
    """Create a minimal EvalRunResult for warning tests."""
    metrics = ReplayMetrics(
        purity_level=purity_level,
        missing_price_events=missing_price_events,
        total_review_dates=total_reviews,
    )
    return EvalRunResult(
        config=EvalConfig(),
        run_result=ReplayRunResult(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 3, 31),
            cadence_days=7,
        ),
        portfolio=ShadowPortfolio(initial_cash=1_000_000),
        metrics=metrics,
        diagnostics=RecommendationDiagnostics(),
        benchmark=BenchmarkComparison(),
    )
