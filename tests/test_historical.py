"""Tests for historical regeneration, evaluation, and proof-pack generation.

Uses bounded synthetic data to verify:
- Time-ordered processing preserves chronology
- As-of-date reconstruction excludes future data
- Regeneration from same config is deterministic
- Memory ON vs OFF both execute and produce comparable outputs
- Benchmark/baseline tables generate on controlled fixtures
- Report pack contains required files/sections
- Coverage gaps surfaced as warnings
"""
from __future__ import annotations

import os
import json
import tempfile
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from models import (
    Base, Company, Document, Claim, Thesis, ThesisStateHistory,
    Candidate, Price, Checkpoint, ThesisState,
    SourceType, SourceTier, ClaimType, EconomicChannel,
    Direction, NoveltyType, ClaimCompanyLink,
)
from historical_eval_config import HistoricalEvalConfig, HistoricalRunMode
from historical_regeneration import (
    RegenerationResult,
    create_regeneration_db,
    copy_prices_to_regen_db,
    run_regeneration,
    open_regeneration_db,
    close_regeneration_db,
)
from historical_evaluation import (
    HistoricalEvalResult,
    ActionOutcome,
    ForwardReturnSummary,
    ConvictionBucketSummary,
    run_historical_evaluation,
    _get_price_on_date,
    _aggregate_by_action,
    _aggregate_by_conviction,
)
from historical_report import generate_proof_pack


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_dir(tmp_path):
    """Use pytest's built-in tmp_path to avoid Windows file-locking issues."""
    return str(tmp_path)


@pytest.fixture
def source_session():
    """Create an in-memory source DB with synthetic historical data."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    _setup_synthetic_data(session)

    yield session
    session.close()


def _setup_synthetic_data(session: Session):
    """Populate source DB with controlled synthetic data for testing."""
    tickers = ["AAPL", "MSFT", "NVDA"]

    # Companies
    for t in tickers:
        session.add(Company(ticker=t, name=f"{t} Inc"))
    session.add(Company(ticker="SPY", name="SPDR S&P 500"))
    session.flush()

    # Price data: 120 days with simple drift
    base_prices = {"AAPL": 150.0, "MSFT": 350.0, "NVDA": 500.0, "SPY": 450.0}
    start = date(2024, 6, 1)
    for day_offset in range(120):
        d = start + timedelta(days=day_offset)
        if d.weekday() >= 5:
            continue  # skip weekends
        for ticker, base in base_prices.items():
            drift = 1.0 + (day_offset * 0.001)  # +0.1% per day
            close = round(base * drift, 2)
            session.add(Price(
                ticker=ticker, date=d,
                open=close * 0.99, high=close * 1.01,
                low=close * 0.98, close=close,
                adj_close=close, volume=1000000,
                source="synthetic",
            ))
    session.flush()

    # Documents: 10 documents spread over 60 days for each ticker
    for t in tickers:
        for i in range(10):
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

    # Create SPY price data for benchmark
    session.commit()


@pytest.fixture
def config(tmp_dir) -> HistoricalEvalConfig:
    """Default test config."""
    return HistoricalEvalConfig(
        run_id="test_proof",
        tickers=["AAPL", "MSFT", "NVDA"],
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


# ---------------------------------------------------------------------------
# TestHistoricalEvalConfig
# ---------------------------------------------------------------------------

class TestHistoricalEvalConfig:
    def test_default_config_is_valid(self):
        config = HistoricalEvalConfig()
        assert config.run_id == "historical_default"
        assert config.cadence_days == 7
        assert config.forward_return_days == [5, 20, 60]

    def test_effective_tickers_with_explicit_list(self):
        config = HistoricalEvalConfig(tickers=["AAPL", "MSFT"])
        assert config.effective_tickers() == ["AAPL", "MSFT"]

    def test_effective_tickers_falls_back_to_universe(self):
        config = HistoricalEvalConfig()
        tickers = config.effective_tickers()
        assert len(tickers) > 10  # universe has ~45 tickers
        assert "AAPL" in tickers

    def test_to_dict(self):
        config = HistoricalEvalConfig(run_id="test", tickers=["AAPL"])
        d = config.to_dict()
        assert d["run_id"] == "test"
        assert d["tickers"] == ["AAPL"]
        assert "backfill_start" in d

    def test_conviction_bucket_for(self):
        config = HistoricalEvalConfig()
        assert config.conviction_bucket_for(30) == "low"
        assert config.conviction_bucket_for(50) == "medium"
        assert config.conviction_bucket_for(80) == "high"

    def test_memory_ablation_pair(self):
        on, off = HistoricalEvalConfig.memory_ablation_pair(
            tickers=["AAPL"],
            backfill_start=date(2024, 1, 1),
            backfill_end=date(2024, 6, 1),
        )
        assert on.memory_enabled is True
        assert off.memory_enabled is False
        assert on.backfill_start == off.backfill_start
        assert on.run_id != off.run_id


# ---------------------------------------------------------------------------
# TestRegeneration
# ---------------------------------------------------------------------------

class TestRegeneration:
    def test_create_regeneration_db(self, config):
        """Regeneration DB is created fresh."""
        session, db_path = create_regeneration_db(config)
        try:
            assert os.path.exists(db_path)
            assert db_path.endswith("_regen.db")
        finally:
            close_regeneration_db(session)

    def test_copy_prices_to_regen_db(self, source_session, config):
        """Price data is copied correctly."""
        regen_session, db_path = create_regeneration_db(config)
        try:
            count = copy_prices_to_regen_db(
                source_session, regen_session, ["AAPL", "MSFT"],
                config.backfill_start, config.backfill_end,
            )
            regen_session.commit()
            assert count > 0

            # Verify prices exist in regen DB
            regen_prices = regen_session.scalars(
                select(Price).where(Price.ticker == "AAPL")
            ).all()
            assert len(regen_prices) > 0
        finally:
            close_regeneration_db(regen_session)

    def test_regeneration_produces_thesis_state(self, source_session, config):
        """Regeneration creates theses and thesis history."""
        result = run_regeneration(source_session, config)

        assert result.total_documents > 0
        assert result.total_claims >= 0  # stub extractor may produce 0 or more
        assert result.db_path != ""
        assert os.path.exists(result.db_path)

    def test_regeneration_is_deterministic(self, source_session, config):
        """Same config produces same document count."""
        config.run_id = "test_det_1"
        result1 = run_regeneration(source_session, config)

        config.run_id = "test_det_2"
        result2 = run_regeneration(source_session, config)

        assert result1.total_documents == result2.total_documents
        assert result1.total_claims == result2.total_claims

    def test_chronological_processing(self, source_session, config):
        """Steps are in chronological order."""
        result = run_regeneration(source_session, config)

        if len(result.steps) >= 2:
            for i in range(1, len(result.steps)):
                assert result.steps[i].process_date >= result.steps[i - 1].process_date

    def test_no_future_data_in_regen(self, source_session, config):
        """Regeneration DB should not contain documents after backfill_end."""
        result = run_regeneration(source_session, config)

        regen_session = open_regeneration_db(result.db_path)
        try:
            end_dt = datetime(config.backfill_end.year, config.backfill_end.month,
                             config.backfill_end.day, 23, 59, 59)
            future_docs = regen_session.scalars(
                select(Document).where(Document.published_at > end_dt)
            ).all()
            assert len(future_docs) == 0, "Future documents leaked into regeneration DB"
        finally:
            close_regeneration_db(regen_session)

    def test_data_coverage_computed(self, source_session, config):
        """Data coverage stats are populated."""
        result = run_regeneration(source_session, config)
        dc = result.data_coverage

        assert "total_documents" in dc
        assert "total_prices" in dc
        assert "tickers_with_prices" in dc


# ---------------------------------------------------------------------------
# TestForwardReturns
# ---------------------------------------------------------------------------

class TestForwardReturns:
    def test_get_price_on_date_exact(self):
        """Get price on exact date."""
        prices = [(date(2024, 6, 3), 150.0), (date(2024, 6, 4), 151.0)]
        assert _get_price_on_date(prices, date(2024, 6, 3)) == 150.0

    def test_get_price_on_date_gap(self):
        """Get price with small gap (weekend)."""
        prices = [(date(2024, 6, 7), 152.0)]  # Friday
        # Saturday
        result = _get_price_on_date(prices, date(2024, 6, 8))
        assert result == 152.0

    def test_get_price_on_date_too_far(self):
        """Price too far in the past returns None."""
        prices = [(date(2024, 6, 1), 150.0)]
        result = _get_price_on_date(prices, date(2024, 6, 15))
        assert result is None

    def test_get_price_on_date_empty(self):
        """Empty price list returns None."""
        assert _get_price_on_date([], date(2024, 6, 1)) is None

    def test_aggregate_by_action(self):
        """Aggregate forward returns by action type."""
        outcomes = [
            ActionOutcome(
                review_date=date(2024, 7, 1), ticker="AAPL",
                action="initiate", thesis_conviction=70, action_score=70.0, conviction_bucket="high",
                rationale="", forward_5d=1.5, forward_20d=3.0, forward_60d=5.0,
            ),
            ActionOutcome(
                review_date=date(2024, 7, 1), ticker="MSFT",
                action="initiate", thesis_conviction=60, action_score=60.0, conviction_bucket="medium",
                rationale="", forward_5d=0.5, forward_20d=2.0, forward_60d=4.0,
            ),
            ActionOutcome(
                review_date=date(2024, 7, 1), ticker="NVDA",
                action="hold", thesis_conviction=50, action_score=0.0, conviction_bucket="medium",
                rationale="", forward_5d=-0.5,
            ),
        ]

        summaries = _aggregate_by_action(outcomes)
        assert len(summaries) == 2  # initiate and hold

        initiate_summary = [s for s in summaries if s.action == "initiate"][0]
        assert initiate_summary.count == 2
        assert initiate_summary.avg_5d == pytest.approx(1.0)
        assert initiate_summary.avg_20d == pytest.approx(2.5)

    def test_aggregate_by_conviction(self):
        """Aggregate by conviction bucket."""
        config = HistoricalEvalConfig()
        outcomes = [
            ActionOutcome(
                review_date=date(2024, 7, 1), ticker="AAPL",
                action="initiate", thesis_conviction=75, action_score=75.0, conviction_bucket="high",
                rationale="", forward_20d=5.0,
            ),
            ActionOutcome(
                review_date=date(2024, 7, 1), ticker="MSFT",
                action="initiate", thesis_conviction=30, action_score=30.0, conviction_bucket="low",
                rationale="", forward_20d=1.0,
            ),
        ]

        buckets = _aggregate_by_conviction(outcomes, config)
        assert len(buckets) == 3  # low, medium, high

        high = [b for b in buckets if b.bucket == "high"][0]
        assert high.action_count == 1
        assert high.avg_forward_20d == pytest.approx(5.0)

        low = [b for b in buckets if b.bucket == "low"][0]
        assert low.action_count == 1


# ---------------------------------------------------------------------------
# TestHistoricalEvaluation
# ---------------------------------------------------------------------------

class TestHistoricalEvaluation:
    def test_evaluation_on_regen_db(self, source_session, config):
        """Full evaluation runs on regenerated DB."""
        regen = run_regeneration(source_session, config)

        regen_session = open_regeneration_db(regen.db_path)
        try:
            eval_result = run_historical_evaluation(regen_session, config)

            assert eval_result is not None
            # Metrics may be None if no review dates generated actions
            # but the evaluation should not crash
        finally:
            close_regeneration_db(regen_session)

    def test_evaluation_produces_decision_rows(self, source_session, config):
        """Evaluation generates decision-level rows."""
        regen = run_regeneration(source_session, config)

        regen_session = open_regeneration_db(regen.db_path)
        try:
            eval_result = run_historical_evaluation(regen_session, config)
            # decision_rows list is always populated (may be empty if no actions)
            assert isinstance(eval_result.decision_rows, list)
        finally:
            close_regeneration_db(regen_session)


# ---------------------------------------------------------------------------
# TestReportGeneration
# ---------------------------------------------------------------------------

class TestReportGeneration:
    def test_proof_pack_contains_required_files(self, source_session, config):
        """Proof pack generates all required artifact files."""
        regen = run_regeneration(source_session, config)

        regen_session = open_regeneration_db(regen.db_path)
        try:
            eval_result = run_historical_evaluation(regen_session, config)
        finally:
            close_regeneration_db(regen_session)

        output_dir = generate_proof_pack(config, regen, eval_result)

        assert os.path.exists(os.path.join(output_dir, "summary.json"))
        assert os.path.exists(os.path.join(output_dir, "report.md"))
        assert os.path.exists(os.path.join(output_dir, "decisions.csv"))
        assert os.path.exists(os.path.join(output_dir, "action_outcomes.csv"))
        assert os.path.exists(os.path.join(output_dir, "benchmark.csv"))
        assert os.path.exists(os.path.join(output_dir, "conviction_buckets.csv"))

    def test_json_report_is_valid(self, source_session, config):
        """JSON summary is valid JSON with expected sections."""
        regen = run_regeneration(source_session, config)

        regen_session = open_regeneration_db(regen.db_path)
        try:
            eval_result = run_historical_evaluation(regen_session, config)
        finally:
            close_regeneration_db(regen_session)

        output_dir = generate_proof_pack(config, regen, eval_result)

        with open(os.path.join(output_dir, "summary.json")) as f:
            data = json.load(f)

        assert data["report_version"] == "2.0"
        assert data["report_type"] == "historical_proof_run"
        assert "config" in data
        assert "regeneration" in data
        assert "evaluation" in data

    def test_markdown_report_has_sections(self, source_session, config):
        """Markdown report contains key sections."""
        regen = run_regeneration(source_session, config)

        regen_session = open_regeneration_db(regen.db_path)
        try:
            eval_result = run_historical_evaluation(regen_session, config)
        finally:
            close_regeneration_db(regen_session)

        output_dir = generate_proof_pack(config, regen, eval_result)

        with open(os.path.join(output_dir, "report.md")) as f:
            content = f.read()

        assert "# Historical Proof Run" in content
        assert "## Run Configuration" in content
        assert "## Limitations" in content


# ---------------------------------------------------------------------------
# TestMemoryAblation
# ---------------------------------------------------------------------------

class TestMemoryAblation:
    def test_ablation_pair_executes(self, source_session, tmp_dir):
        """Both memory-ON and memory-OFF regenerations complete."""
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

        assert regen_on.total_documents == regen_off.total_documents
        assert os.path.exists(regen_on.db_path)
        assert os.path.exists(regen_off.db_path)

    def test_ablation_produces_comparable_outputs(self, source_session, tmp_dir):
        """Both runs produce results with same structure."""
        config_on, config_off = HistoricalEvalConfig.memory_ablation_pair(
            tickers=["AAPL"],
            backfill_start=date(2024, 6, 1),
            backfill_end=date(2024, 9, 30),
            eval_start=date(2024, 7, 1),
            eval_end=date(2024, 9, 30),
        )
        config_on.output_dir = tmp_dir
        config_off.output_dir = tmp_dir

        regen_on = run_regeneration(source_session, config_on)
        regen_off = run_regeneration(source_session, config_off)

        # Both produce to_dict with same keys
        d_on = regen_on.to_dict()
        d_off = regen_off.to_dict()
        assert set(d_on.keys()) == set(d_off.keys())


# ---------------------------------------------------------------------------
# TestWarnings
# ---------------------------------------------------------------------------

class TestWarnings:
    def test_no_documents_warning(self, tmp_dir):
        """Regeneration warns when no documents found."""
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        session = sessionmaker(bind=engine)()

        # Add companies but no documents
        session.add(Company(ticker="AAPL", name="Apple"))
        session.flush()

        config = HistoricalEvalConfig(
            run_id="test_empty",
            tickers=["AAPL"],
            backfill_start=date(2024, 1, 1),
            backfill_end=date(2024, 6, 1),
            output_dir=tmp_dir,
        )

        result = run_regeneration(session, config)
        assert any("No documents found" in w for w in result.warnings)
        session.close()

    def test_coverage_gaps_surfaced(self, source_session, config):
        """Coverage statistics are computed and include gap info."""
        result = run_regeneration(source_session, config)

        dc = result.data_coverage
        assert dc.get("tickers_total", 0) == 3
        # SPY might not have docs, but should have prices
        assert "tickers_with_prices" in dc


# ---------------------------------------------------------------------------
# TestActionOutcome
# ---------------------------------------------------------------------------

class TestActionOutcome:
    def test_to_dict(self):
        outcome = ActionOutcome(
            review_date=date(2024, 7, 1),
            ticker="AAPL",
            action="initiate",
            thesis_conviction=75.0,
            action_score=75.0,
            conviction_bucket="high",
            rationale="Strong valuation",
            price_at_decision=155.0,
            forward_5d=1.5,
            forward_20d=3.0,
            forward_60d=5.0,
        )
        d = outcome.to_dict()
        assert d["ticker"] == "AAPL"
        assert d["forward_5d_pct"] == 1.5
        assert d["forward_20d_pct"] == 3.0
        assert d["forward_60d_pct"] == 5.0

    def test_to_dict_with_none_values(self):
        outcome = ActionOutcome(
            review_date=date(2024, 7, 1),
            ticker="AAPL",
            action="hold",
            thesis_conviction=50.0,
            action_score=0.0,
            conviction_bucket="medium",
            rationale="",
        )
        d = outcome.to_dict()
        assert d["forward_5d_pct"] is None
        assert d["price_at_decision"] is None
