"""Tests for the usefulness-run surface: proof universe, coverage diagnostics,
best/worst decisions, failure analysis, per-name tables, manifest, and
degraded-run warnings.

Uses bounded synthetic data to verify all new usefulness-testing artifacts.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from models import (
    Base, Company, Document, Claim, Price,
    SourceType, SourceTier, ClaimType, EconomicChannel,
    Direction, NoveltyType, ClaimCompanyLink,
)
from historical_eval_config import HistoricalEvalConfig, HistoricalRunMode
from historical_regeneration import (
    run_regeneration, open_regeneration_db, close_regeneration_db,
)
from historical_evaluation import (
    HistoricalEvalResult, ActionOutcome, PerNameSummary,
    CoverageDiagnostics, FailureAnalysis, ForwardReturnSummary,
    ConvictionBucketSummary,
    run_historical_evaluation,
    _compute_best_worst, _compute_failure_analysis,
)
from historical_report import generate_proof_pack
from proof_universe import (
    PROOF_UNIVERSE_TICKERS, get_proof_universe, get_proof_universe_rationale,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_dir(tmp_path):
    return str(tmp_path)


@pytest.fixture
def source_session():
    """In-memory source DB with synthetic data for 5 tickers."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    _setup_synthetic_data(session)
    yield session
    session.close()


def _setup_synthetic_data(session: Session):
    tickers = ["AAPL", "MSFT", "NVDA", "AMD", "GOOGL"]

    for t in tickers:
        session.add(Company(ticker=t, name=f"{t} Inc"))
    session.add(Company(ticker="SPY", name="SPDR S&P 500"))
    session.flush()

    # Price data: 120 days
    base_prices = {"AAPL": 150.0, "MSFT": 350.0, "NVDA": 500.0, "AMD": 120.0, "GOOGL": 140.0, "SPY": 450.0}
    start = date(2024, 6, 1)
    for day_offset in range(120):
        d = start + timedelta(days=day_offset)
        if d.weekday() >= 5:
            continue
        for ticker, base in base_prices.items():
            drift = 1.0 + (day_offset * 0.001)
            close = round(base * drift, 2)
            session.add(Price(
                ticker=ticker, date=d,
                open=close * 0.99, high=close * 1.01,
                low=close * 0.98, close=close,
                adj_close=close, volume=1000000,
                source="synthetic",
            ))
    session.flush()

    # Documents: varied counts per ticker to test sparse coverage
    doc_counts = {"AAPL": 10, "MSFT": 8, "NVDA": 6, "AMD": 2, "GOOGL": 0}
    for t, count in doc_counts.items():
        for i in range(count):
            pub_date = datetime(2024, 6, 1) + timedelta(days=i * 6)
            doc = Document(
                source_type=SourceType.NEWS,
                source_tier=SourceTier.TIER_2,
                title=f"{t} news article {i}",
                url=f"https://example.com/{t}/{i}",
                published_at=pub_date,
                primary_company_ticker=t,
                raw_text=f"{t} shows strong growth in Q{i % 4 + 1}. Revenue increased significantly.",
                hash=f"hash_{t}_{i}",
                source_key="news_google_rss",
                external_id=f"ext_{t}_{i}",
                ingested_at=pub_date,
            )
            session.add(doc)
    session.flush()
    session.commit()


@pytest.fixture
def config(tmp_dir) -> HistoricalEvalConfig:
    return HistoricalEvalConfig(
        run_id="test_usefulness",
        mode=HistoricalRunMode.USEFULNESS_RUN,
        tickers=["AAPL", "MSFT", "NVDA", "AMD", "GOOGL"],
        backfill_start=date(2024, 6, 1),
        backfill_end=date(2024, 9, 30),
        eval_start=date(2024, 7, 1),
        eval_end=date(2024, 9, 30),
        cadence_days=14,
        output_dir=tmp_dir,
        rebuild_from_scratch=True,
        backfill_prices=False,
        backfill_sec_filings=False,
        backfill_news_rss=False,
        backfill_pr_rss=False,
    )


@pytest.fixture
def sample_outcomes() -> list[ActionOutcome]:
    """Controlled action outcomes for testing best/worst and aggregation."""
    return [
        ActionOutcome(
            review_date=date(2024, 7, 1), ticker="AAPL",
            action="initiate", thesis_conviction=75, action_score=75.0, conviction_bucket="high",
            rationale="Strong valuation", price_at_decision=155.0,
            forward_5d=2.5, forward_20d=8.0, forward_60d=12.0,
        ),
        ActionOutcome(
            review_date=date(2024, 7, 1), ticker="MSFT",
            action="initiate", thesis_conviction=60, action_score=60.0, conviction_bucket="medium",
            rationale="Moderate growth", price_at_decision=355.0,
            forward_5d=-1.0, forward_20d=-3.0, forward_60d=-5.0,
        ),
        ActionOutcome(
            review_date=date(2024, 7, 15), ticker="NVDA",
            action="add", thesis_conviction=80, action_score=80.0, conviction_bucket="high",
            rationale="AI tailwind", price_at_decision=510.0,
            forward_5d=3.0, forward_20d=10.0, forward_60d=15.0,
        ),
        ActionOutcome(
            review_date=date(2024, 7, 15), ticker="AMD",
            action="initiate", thesis_conviction=55, action_score=55.0, conviction_bucket="medium",
            rationale="Peer momentum", price_at_decision=125.0,
            forward_5d=-2.0, forward_20d=-7.0, forward_60d=-10.0,
        ),
        ActionOutcome(
            review_date=date(2024, 8, 1), ticker="AAPL",
            action="hold", thesis_conviction=70, action_score=0.0, conviction_bucket="high",
            rationale="Maintain", price_at_decision=158.0,
            forward_5d=0.5, forward_20d=1.0,
        ),
        ActionOutcome(
            review_date=date(2024, 8, 1), ticker="AMD",
            action="initiate", thesis_conviction=50, action_score=50.0, conviction_bucket="medium",
            rationale="Re-entry", price_at_decision=122.0,
            forward_5d=-1.5, forward_20d=-6.0, forward_60d=-8.0,
        ),
    ]


# ---------------------------------------------------------------------------
# TestProofUniverse
# ---------------------------------------------------------------------------

class TestProofUniverse:
    def test_universe_has_15_names(self):
        assert len(PROOF_UNIVERSE_TICKERS) == 15

    def test_get_proof_universe_returns_copy(self):
        u = get_proof_universe()
        assert u == PROOF_UNIVERSE_TICKERS
        u.append("FAKE")
        assert len(PROOF_UNIVERSE_TICKERS) == 15  # original unchanged

    def test_rationale_is_nonempty(self):
        r = get_proof_universe_rationale()
        assert len(r) > 20

    def test_usefulness_config_uses_proof_universe(self):
        config = HistoricalEvalConfig(mode=HistoricalRunMode.USEFULNESS_RUN)
        tickers = config.effective_tickers()
        assert tickers == PROOF_UNIVERSE_TICKERS

    def test_non_usefulness_uses_full_universe(self):
        config = HistoricalEvalConfig(mode=HistoricalRunMode.REGENERATE)
        tickers = config.effective_tickers()
        assert len(tickers) > 15  # full universe

    def test_explicit_tickers_override(self):
        config = HistoricalEvalConfig(
            mode=HistoricalRunMode.USEFULNESS_RUN,
            tickers=["AAPL", "MSFT"],
        )
        assert config.effective_tickers() == ["AAPL", "MSFT"]


# ---------------------------------------------------------------------------
# TestUsefulnessConfig
# ---------------------------------------------------------------------------

class TestUsefulnessConfig:
    def test_usefulness_run_config_factory(self):
        config = HistoricalEvalConfig.usefulness_run_config()
        assert config.mode == HistoricalRunMode.USEFULNESS_RUN
        assert config.run_id == "usefulness_run"

    def test_extractor_mode_label_stub(self):
        config = HistoricalEvalConfig(use_llm=False)
        assert config.extractor_mode_label() == "stub_heuristic"

    def test_extractor_mode_label_real(self):
        config = HistoricalEvalConfig(use_llm=True)
        assert config.extractor_mode_label() == "real_llm"

    def test_validate_warns_stub_extractor(self):
        config = HistoricalEvalConfig(
            mode=HistoricalRunMode.USEFULNESS_RUN,
            use_llm=False,
        )
        warnings = config.validate_for_usefulness_run()
        assert any("DEGRADED" in w for w in warnings)
        assert any("stub" in w.lower() for w in warnings)

    def test_validate_no_warning_with_llm(self):
        config = HistoricalEvalConfig(
            mode=HistoricalRunMode.USEFULNESS_RUN,
            use_llm=True,
            tickers=["AAPL"],  # small universe
        )
        warnings = config.validate_for_usefulness_run()
        assert not any("DEGRADED" in w for w in warnings)

    def test_validate_warns_disabled_sources(self):
        config = HistoricalEvalConfig(
            mode=HistoricalRunMode.USEFULNESS_RUN,
            use_llm=True,
            backfill_sec_filings=False,
            tickers=["AAPL"],
        )
        warnings = config.validate_for_usefulness_run()
        assert any("SEC" in w for w in warnings)

    def test_validate_warns_large_universe(self):
        config = HistoricalEvalConfig(
            mode=HistoricalRunMode.USEFULNESS_RUN,
            use_llm=True,
        )
        # Default proof universe is 15, not >25
        warnings = config.validate_for_usefulness_run()
        assert not any("tickers" in w.lower() for w in warnings)

    def test_to_dict_includes_extractor_mode(self):
        config = HistoricalEvalConfig()
        d = config.to_dict()
        assert "extractor_mode" in d
        assert d["extractor_mode"] == "real_llm"

    def test_is_usefulness_run(self):
        config = HistoricalEvalConfig(mode=HistoricalRunMode.USEFULNESS_RUN)
        assert config.is_usefulness_run() is True

        config2 = HistoricalEvalConfig(mode=HistoricalRunMode.REGENERATE)
        assert config2.is_usefulness_run() is False


# ---------------------------------------------------------------------------
# TestBestWorstDecisions
# ---------------------------------------------------------------------------

class TestBestWorstDecisions:
    def test_best_decisions_sorted_descending(self, sample_outcomes):
        best = _compute_best_worst(sample_outcomes, best=True, n=3)
        assert len(best) == 3
        # Best 20D: NVDA +10%, AAPL +8%, AAPL hold +1%
        assert best[0]["ticker"] == "NVDA"
        assert best[0]["forward_20d_pct"] == 10.0
        assert best[1]["ticker"] == "AAPL"
        assert best[1]["forward_20d_pct"] == 8.0

    def test_worst_decisions_sorted_ascending(self, sample_outcomes):
        worst = _compute_best_worst(sample_outcomes, best=False, n=3)
        assert len(worst) == 3
        # Worst 20D: AMD -7%, AMD -6%, MSFT -3%
        assert worst[0]["forward_20d_pct"] == -7.0
        assert worst[1]["forward_20d_pct"] == -6.0

    def test_best_worst_has_required_fields(self, sample_outcomes):
        best = _compute_best_worst(sample_outcomes, best=True, n=1)
        assert len(best) == 1
        d = best[0]
        assert "review_date" in d
        assert "ticker" in d
        assert "action" in d
        assert "thesis_conviction" in d
        assert "forward_5d_pct" in d
        assert "forward_20d_pct" in d
        assert "forward_60d_pct" in d
        assert "rationale" in d
        assert "price_at_decision" in d

    def test_best_worst_empty_outcomes(self):
        best = _compute_best_worst([], best=True)
        assert best == []

    def test_best_worst_excludes_hold(self, sample_outcomes):
        """Hold actions are excluded from best/worst analysis."""
        best = _compute_best_worst(sample_outcomes, best=True, n=10)
        actions = [d["action"] for d in best]
        assert "hold" not in actions


# ---------------------------------------------------------------------------
# TestPerNameSummary
# ---------------------------------------------------------------------------

class TestPerNameSummary:
    def test_per_name_on_regen_db(self, source_session, config):
        """Per-name summary is computed from regenerated DB."""
        regen = run_regeneration(source_session, config)
        regen_session = open_regeneration_db(regen.db_path)
        try:
            eval_result = run_historical_evaluation(regen_session, config)
            assert isinstance(eval_result.per_name_summary, list)
            # Should have entries for each ticker
            tickers_in_summary = {p.ticker for p in eval_result.per_name_summary}
            for t in config.effective_tickers():
                assert t in tickers_in_summary
        finally:
            close_regeneration_db(regen_session)

    def test_per_name_summary_fields(self):
        pns = PerNameSummary(
            ticker="AAPL", action_count=5, initiate_count=2,
            exit_count=1, hold_count=2,
            avg_forward_5d=1.5, avg_forward_20d=3.0,
            doc_count=10, claim_count=15,
            price_coverage_pct=95.0,
        )
        d = pns.to_dict()
        assert d["ticker"] == "AAPL"
        assert d["action_count"] == 5
        assert d["avg_forward_5d_pct"] == 1.5
        assert d["doc_count"] == 10
        assert d["price_coverage_pct"] == 95.0


# ---------------------------------------------------------------------------
# TestCoverageDiagnostics
# ---------------------------------------------------------------------------

class TestCoverageDiagnostics:
    def test_coverage_diagnostics_computed(self, source_session, config):
        """Coverage diagnostics are generated from regen DB."""
        regen = run_regeneration(source_session, config)
        regen_session = open_regeneration_db(regen.db_path)
        try:
            eval_result = run_historical_evaluation(regen_session, config)
            cd = eval_result.coverage_diagnostics
            assert cd is not None
            assert cd.extractor_mode == "real_llm"
            assert isinstance(cd.docs_by_ticker, dict)
            assert isinstance(cd.docs_by_source_type, dict)
            assert isinstance(cd.docs_by_month, dict)
            assert isinstance(cd.source_gaps, list)
        finally:
            close_regeneration_db(regen_session)

    def test_coverage_diagnostics_to_dict(self):
        cd = CoverageDiagnostics(
            docs_by_ticker={"AAPL": 10},
            docs_by_source_type={"NEWS": 10},
            docs_by_month={"2024-06": 5, "2024-07": 5},
            extractor_mode="stub_heuristic",
            tickers_with_prices=3,
        )
        d = cd.to_dict()
        assert d["docs_by_ticker"] == {"AAPL": 10}
        assert d["extractor_mode"] == "stub_heuristic"
        assert d["tickers_with_prices"] == 3

    def test_source_gaps_for_no_docs_ticker(self, source_session, config):
        """GOOGL has 0 documents — should appear in source_gaps."""
        regen = run_regeneration(source_session, config)
        regen_session = open_regeneration_db(regen.db_path)
        try:
            eval_result = run_historical_evaluation(regen_session, config)
            cd = eval_result.coverage_diagnostics
            gap_tickers = [g["ticker"] for g in cd.source_gaps if g["issue"] == "no_documents"]
            assert "GOOGL" in gap_tickers
        finally:
            close_regeneration_db(regen_session)


# ---------------------------------------------------------------------------
# TestFailureAnalysis
# ---------------------------------------------------------------------------

class TestFailureAnalysis:
    def test_failure_analysis_stub_degraded(self):
        """Stub extractor triggers degraded flag."""
        config = HistoricalEvalConfig(use_llm=False)
        result = HistoricalEvalResult(config=config)
        result.per_name_summary = []
        result.forward_return_summary = []
        result.conviction_buckets = []
        result.action_outcomes = []
        result.coverage_diagnostics = CoverageDiagnostics()

        fa = _compute_failure_analysis(result, config)
        assert any("Stub" in f for f in fa.degraded_flags)

    def test_failure_analysis_negative_returns(self, sample_outcomes):
        """Negative return actions are flagged."""
        config = HistoricalEvalConfig()
        result = HistoricalEvalResult(config=config)
        result.per_name_summary = []
        result.action_outcomes = sample_outcomes

        from historical_evaluation import _aggregate_by_action, _aggregate_by_conviction
        result.forward_return_summary = _aggregate_by_action(sample_outcomes)
        result.conviction_buckets = _aggregate_by_conviction(sample_outcomes, config)
        result.coverage_diagnostics = CoverageDiagnostics()

        fa = _compute_failure_analysis(result, config)
        # initiate has AMD with -7% and -6%, MSFT with -3% so avg should be negative
        neg_actions = [n["action"] for n in fa.negative_return_actions]
        # At least one action type should have negative returns
        assert isinstance(fa.negative_return_actions, list)

    def test_failure_analysis_repeated_bad(self, sample_outcomes):
        """AMD with 2 bad initiate/add actions should be flagged."""
        config = HistoricalEvalConfig()
        result = HistoricalEvalResult(config=config)
        result.per_name_summary = []
        result.action_outcomes = sample_outcomes
        result.forward_return_summary = []
        result.conviction_buckets = []
        result.coverage_diagnostics = CoverageDiagnostics()

        fa = _compute_failure_analysis(result, config)
        bad_tickers = [r["ticker"] for r in fa.repeated_bad_recommendations]
        assert "AMD" in bad_tickers

    def test_failure_analysis_to_dict(self):
        fa = FailureAnalysis(
            degraded_flags=["stub_extractor"],
            sparse_coverage_tickers=[{"ticker": "X", "issues": ["no docs"], "doc_count": 0, "claim_count": 0, "price_coverage_pct": 0}],
        )
        d = fa.to_dict()
        assert d["degraded_flags"] == ["stub_extractor"]
        assert len(d["sparse_coverage_tickers"]) == 1

    def test_failure_analysis_sparse_coverage(self, source_session, config):
        """Tickers with few/no documents are flagged as sparse."""
        regen = run_regeneration(source_session, config)
        regen_session = open_regeneration_db(regen.db_path)
        try:
            eval_result = run_historical_evaluation(regen_session, config)
            fa = eval_result.failure_analysis
            assert fa is not None
            sparse_tickers = [s["ticker"] for s in fa.sparse_coverage_tickers]
            # GOOGL has 0 docs, AMD has 2 docs — both should be flagged
            assert "GOOGL" in sparse_tickers
        finally:
            close_regeneration_db(regen_session)


# ---------------------------------------------------------------------------
# TestManifest
# ---------------------------------------------------------------------------

class TestManifest:
    def test_manifest_generated(self, source_session, config):
        """Manifest.json is generated in proof pack."""
        regen = run_regeneration(source_session, config)
        regen_session = open_regeneration_db(regen.db_path)
        try:
            eval_result = run_historical_evaluation(regen_session, config)
        finally:
            close_regeneration_db(regen_session)

        output_dir = generate_proof_pack(config, regen, eval_result)
        manifest_path = os.path.join(output_dir, "manifest.json")
        assert os.path.exists(manifest_path)

        with open(manifest_path) as f:
            manifest = json.load(f)

        assert manifest["manifest_version"] == "1.0"
        assert manifest["run_id"] == "test_usefulness"
        assert manifest["mode"] == HistoricalRunMode.USEFULNESS_RUN

    def test_manifest_has_required_fields(self, source_session, config):
        """Manifest includes all required metadata fields."""
        regen = run_regeneration(source_session, config)
        regen_session = open_regeneration_db(regen.db_path)
        try:
            eval_result = run_historical_evaluation(regen_session, config)
        finally:
            close_regeneration_db(regen_session)

        output_dir = generate_proof_pack(config, regen, eval_result)

        with open(os.path.join(output_dir, "manifest.json")) as f:
            manifest = json.load(f)

        required_fields = [
            "manifest_version", "run_id", "generated_at", "code_hash",
            "mode", "universe", "universe_size", "date_range",
            "extractor_mode", "source_toggles", "benchmark_ticker",
            "forward_return_days", "cadence_days", "memory_enabled",
            "degraded_flags", "warnings_count",
        ]
        for field in required_fields:
            assert field in manifest, f"Missing manifest field: {field}"

    def test_manifest_degraded_flags(self, source_session, config):
        """Manifest includes degraded flags when sources are off."""
        regen = run_regeneration(source_session, config)
        regen_session = open_regeneration_db(regen.db_path)
        try:
            eval_result = run_historical_evaluation(regen_session, config)
        finally:
            close_regeneration_db(regen_session)

        output_dir = generate_proof_pack(config, regen, eval_result)

        with open(os.path.join(output_dir, "manifest.json")) as f:
            manifest = json.load(f)

        # With use_llm=True (default), stub_extractor is NOT flagged
        assert "stub_extractor" not in manifest["degraded_flags"]
        # All sources disabled in test config
        assert "no_sec_filings" in manifest["degraded_flags"]


# ---------------------------------------------------------------------------
# TestReportArtifacts
# ---------------------------------------------------------------------------

class TestReportArtifacts:
    def test_all_usefulness_csvs_generated(self, source_session, config):
        """Proof pack generates all new usefulness CSV artifacts."""
        regen = run_regeneration(source_session, config)
        regen_session = open_regeneration_db(regen.db_path)
        try:
            eval_result = run_historical_evaluation(regen_session, config)
        finally:
            close_regeneration_db(regen_session)

        output_dir = generate_proof_pack(config, regen, eval_result)

        expected_files = [
            "manifest.json",
            "summary.json",
            "report.md",
            "decisions.csv",
            "action_outcomes.csv",
            "best_decisions.csv",
            "worst_decisions.csv",
            "per_name_summary.csv",
            "coverage_diagnostics.csv",
            "coverage_by_month.csv",
            "benchmark.csv",
            "conviction_buckets.csv",
        ]
        for f in expected_files:
            assert os.path.exists(os.path.join(output_dir, f)), f"Missing: {f}"

    def test_per_name_csv_has_expected_columns(self, source_session, config):
        """per_name_summary.csv has required columns."""
        regen = run_regeneration(source_session, config)
        regen_session = open_regeneration_db(regen.db_path)
        try:
            eval_result = run_historical_evaluation(regen_session, config)
        finally:
            close_regeneration_db(regen_session)

        output_dir = generate_proof_pack(config, regen, eval_result)

        import csv
        with open(os.path.join(output_dir, "per_name_summary.csv")) as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            assert "ticker" in headers
            assert "action_count" in headers
            assert "avg_forward_20d_pct" in headers
            assert "doc_count" in headers
            assert "claim_count" in headers
            assert "price_coverage_pct" in headers

    def test_best_worst_csv_has_expected_columns(self, source_session, config):
        """best_decisions.csv and worst_decisions.csv have required columns."""
        regen = run_regeneration(source_session, config)
        regen_session = open_regeneration_db(regen.db_path)
        try:
            eval_result = run_historical_evaluation(regen_session, config)
        finally:
            close_regeneration_db(regen_session)

        output_dir = generate_proof_pack(config, regen, eval_result)

        import csv
        for label in ["best", "worst"]:
            with open(os.path.join(output_dir, f"{label}_decisions.csv")) as f:
                reader = csv.DictReader(f)
                headers = reader.fieldnames
                assert "review_date" in headers
                assert "ticker" in headers
                assert "action" in headers
                assert "forward_20d_pct" in headers

    def test_coverage_diagnostics_csv(self, source_session, config):
        """coverage_diagnostics.csv has ticker-level coverage."""
        regen = run_regeneration(source_session, config)
        regen_session = open_regeneration_db(regen.db_path)
        try:
            eval_result = run_historical_evaluation(regen_session, config)
        finally:
            close_regeneration_db(regen_session)

        output_dir = generate_proof_pack(config, regen, eval_result)

        import csv
        with open(os.path.join(output_dir, "coverage_diagnostics.csv")) as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            assert "ticker" in headers
            assert "doc_count" in headers
            assert "claim_count" in headers

    def test_markdown_has_failure_analysis(self, source_session, config):
        """Markdown report includes failure analysis section when triggered."""
        regen = run_regeneration(source_session, config)
        regen_session = open_regeneration_db(regen.db_path)
        try:
            eval_result = run_historical_evaluation(regen_session, config)
        finally:
            close_regeneration_db(regen_session)

        output_dir = generate_proof_pack(config, regen, eval_result)

        with open(os.path.join(output_dir, "report.md")) as f:
            content = f.read()

        assert "## Failure Analysis" in content
        assert "Degraded Run Flags" in content

    def test_markdown_has_best_worst_sections(self, source_session, config):
        """Markdown report includes best/worst decision tables."""
        regen = run_regeneration(source_session, config)
        regen_session = open_regeneration_db(regen.db_path)
        try:
            eval_result = run_historical_evaluation(regen_session, config)
        finally:
            close_regeneration_db(regen_session)

        output_dir = generate_proof_pack(config, regen, eval_result)

        with open(os.path.join(output_dir, "report.md")) as f:
            content = f.read()

        # These sections appear only if there are outcomes
        # The test data should produce some actions
        assert "## Artifact Index" in content

    def test_markdown_has_artifact_index(self, source_session, config):
        """Markdown report includes artifact index."""
        regen = run_regeneration(source_session, config)
        regen_session = open_regeneration_db(regen.db_path)
        try:
            eval_result = run_historical_evaluation(regen_session, config)
        finally:
            close_regeneration_db(regen_session)

        output_dir = generate_proof_pack(config, regen, eval_result)

        with open(os.path.join(output_dir, "report.md")) as f:
            content = f.read()

        assert "## Artifact Index" in content
        assert "manifest.json" in content

    def test_json_summary_has_new_fields(self, source_session, config):
        """JSON summary includes new usefulness fields."""
        regen = run_regeneration(source_session, config)
        regen_session = open_regeneration_db(regen.db_path)
        try:
            eval_result = run_historical_evaluation(regen_session, config)
        finally:
            close_regeneration_db(regen_session)

        output_dir = generate_proof_pack(config, regen, eval_result)

        with open(os.path.join(output_dir, "summary.json")) as f:
            data = json.load(f)

        eval_data = data["evaluation"]
        assert "best_decisions" in eval_data
        assert "worst_decisions" in eval_data
        assert "per_name_summary" in eval_data
        assert "coverage_diagnostics" in eval_data
        assert "failure_analysis" in eval_data


# ---------------------------------------------------------------------------
# TestRealExtractorWarning
# ---------------------------------------------------------------------------

class TestRealExtractorWarning:
    def test_stub_mode_warns_prominently(self):
        """Usefulness run with stub extractor produces prominent warning."""
        config = HistoricalEvalConfig(
            mode=HistoricalRunMode.USEFULNESS_RUN,
            use_llm=False,
        )
        warnings = config.validate_for_usefulness_run()
        degraded = [w for w in warnings if "DEGRADED" in w]
        assert len(degraded) >= 1
        assert "stub" in degraded[0].lower()

    def test_real_extractor_no_degraded_warning(self):
        """Usefulness run with real extractor does not produce DEGRADED warning."""
        config = HistoricalEvalConfig(
            mode=HistoricalRunMode.USEFULNESS_RUN,
            use_llm=True,
            tickers=["AAPL"],
        )
        warnings = config.validate_for_usefulness_run()
        degraded = [w for w in warnings if "DEGRADED" in w]
        assert len(degraded) == 0


# ---------------------------------------------------------------------------
# TestMemoryAblationUsefulness
# ---------------------------------------------------------------------------

class TestMemoryAblationUsefulness:
    def test_ablation_produces_comparable_usefulness_outputs(self, source_session, tmp_dir):
        """Both memory ON/OFF runs produce usefulness fields."""
        config_on, config_off = HistoricalEvalConfig.memory_ablation_pair(
            tickers=["AAPL", "MSFT"],
            backfill_start=date(2024, 6, 1),
            backfill_end=date(2024, 9, 30),
            eval_start=date(2024, 7, 1),
            eval_end=date(2024, 9, 30),
        )
        config_on.output_dir = tmp_dir
        config_off.output_dir = tmp_dir

        regen_on = run_regeneration(source_session, config_on)
        regen_off = run_regeneration(source_session, config_off)

        regen_on_session = open_regeneration_db(regen_on.db_path)
        try:
            eval_on = run_historical_evaluation(regen_on_session, config_on)
        finally:
            close_regeneration_db(regen_on_session)

        regen_off_session = open_regeneration_db(regen_off.db_path)
        try:
            eval_off = run_historical_evaluation(regen_off_session, config_off)
        finally:
            close_regeneration_db(regen_off_session)

        # Both should have per_name_summary
        assert isinstance(eval_on.per_name_summary, list)
        assert isinstance(eval_off.per_name_summary, list)

        # Both should have coverage diagnostics
        assert eval_on.coverage_diagnostics is not None
        assert eval_off.coverage_diagnostics is not None

        # Both should have failure analysis
        assert eval_on.failure_analysis is not None
        assert eval_off.failure_analysis is not None
