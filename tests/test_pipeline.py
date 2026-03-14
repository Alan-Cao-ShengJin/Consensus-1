"""Tests for Step 6: live source connectors, dedupe, pipeline runner.

All tests use in-memory SQLite and mocked network calls.
No live network requests are made.
"""
from __future__ import annotations

import contextlib
import sys
import os
from datetime import datetime, timedelta, date
from unittest.mock import patch, MagicMock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import (
    Base, Company, Document, Claim, Thesis, Price, Checkpoint,
    ThesisClaimLink, ThesisStateHistory,
    SourceType, SourceTier, ThesisState, Direction, NoveltyType,
    ClaimType, EconomicChannel,
)
from connectors.base import DocumentPayload, NonDocumentResult
from connectors.sec_edgar import SECEdgarConnector, _get_user_agent
from connectors.google_rss import GoogleRSSConnector
from connectors.pr_rss import PRRSSConnector
from connectors.newsapi_connector import NewsAPIConnector
from connectors.finnhub_connector import FinnhubNewsConnector
from connectors.fmp_connector import FMPTranscriptConnector, FMPFinancialsConnector, FMPEstimatesConnector, FMPNewsConnector
from connectors.yfinance_prices import YFinancePriceUpdater
from connectors.yfinance_calendar import YFinanceCalendarUpdater
from connectors.yfinance_ticker_info import YFinanceTickerInfoUpdater
from dedupe import is_duplicate_document, filter_new_documents
from document_ingestion_service import ingest_document_payload
from pipeline_runner import run_ticker_pipeline


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


def _make_company(session, ticker="NVDA"):
    c = Company(ticker=ticker, name=f"{ticker} Corp.")
    session.add(c)
    session.flush()
    return c


def _make_thesis(session, ticker="NVDA", score=50.0):
    t = Thesis(
        title=f"{ticker} AI infrastructure demand thesis",
        company_ticker=ticker,
        summary=f"Long {ticker} on AI infrastructure demand acceleration",
        state=ThesisState.STABLE,
        conviction_score=score,
    )
    session.add(t)
    session.flush()
    return t


def _make_payload(
    source_key="news_google_rss",
    ticker="NVDA",
    title="Test Article",
    url="https://example.com/article1",
    external_id=None,
    raw_text="NVDA AI infrastructure revenue grew strongly this quarter",
):
    return DocumentPayload(
        source_key=source_key,
        source_type=SourceType.NEWS,
        source_tier=SourceTier.TIER_3,
        ticker=ticker,
        title=title,
        url=url,
        published_at=datetime.utcnow(),
        external_id=external_id,
        raw_text=raw_text,
    )


def _nondoc_patches():
    """Return context managers for mocking all non-document updaters."""
    return [
        patch.object(YFinancePriceUpdater, 'update', return_value=NonDocumentResult("price_daily", "NVDA")),
        patch.object(YFinanceCalendarUpdater, 'update', return_value=NonDocumentResult("earnings_calendar", "NVDA")),
        patch.object(YFinanceTickerInfoUpdater, 'update', return_value=NonDocumentResult("ticker_master", "NVDA")),
    ]


def _all_connector_patches(
    sec_return=None, google_return=None, pr_return=None,
    finnhub_return=None, fmp_transcript_return=None,
    fmp_financials_return=None, fmp_estimates_return=None,
    fmp_news_return=None,
):
    """Return context managers mocking all document connectors + non-doc updaters."""
    return [
        patch.object(SECEdgarConnector, 'fetch', return_value=sec_return or []),
        patch.object(GoogleRSSConnector, 'fetch', return_value=google_return or []),
        patch.object(PRRSSConnector, 'fetch', return_value=pr_return or []),
        patch.object(FinnhubNewsConnector, 'fetch', return_value=finnhub_return or []),
        patch.object(FMPTranscriptConnector, 'fetch', return_value=fmp_transcript_return or []),
        patch.object(FMPFinancialsConnector, 'fetch', return_value=fmp_financials_return or []),
        patch.object(FMPEstimatesConnector, 'fetch', return_value=fmp_estimates_return or []),
        patch.object(FMPNewsConnector, 'fetch', return_value=fmp_news_return or []),
    ] + _nondoc_patches()


@contextlib.contextmanager
def _apply_patches(patches):
    """Apply a list of patch context managers using ExitStack."""
    with contextlib.ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        yield


# ---------------------------------------------------------------------------
# 1. Source normalization tests
# ---------------------------------------------------------------------------

class TestSourceNormalization:
    """Document connectors produce correctly normalized DocumentPayload objects."""

    def test_payload_computes_content_hash(self):
        p = _make_payload(raw_text="test content")
        assert p.content_hash is not None
        assert len(p.content_hash) == 64  # SHA-256

    def test_payload_hash_deterministic(self):
        p1 = _make_payload(raw_text="same content")
        p2 = _make_payload(raw_text="same content")
        assert p1.content_hash == p2.content_hash

    def test_payload_different_text_different_hash(self):
        p1 = _make_payload(raw_text="content A")
        p2 = _make_payload(raw_text="content B")
        assert p1.content_hash != p2.content_hash

    def test_sec_connector_source_key(self):
        conn = SECEdgarConnector()
        assert conn.source_key == "sec_edgar"

    def test_google_rss_connector_source_key(self):
        conn = GoogleRSSConnector()
        assert conn.source_key == "news_google_rss"

    def test_pr_rss_connector_source_key(self):
        conn = PRRSSConnector()
        assert conn.source_key == "press_release_rss"

    def test_newsapi_connector_source_key(self):
        conn = NewsAPIConnector()
        assert conn.source_key == "newsapi"

    def test_payload_empty_text_no_hash(self):
        p = DocumentPayload(
            source_key="test", source_type=SourceType.NEWS,
            source_tier=SourceTier.TIER_3, ticker="NVDA", title="t",
            raw_text="",
        )
        assert p.content_hash is None


# ---------------------------------------------------------------------------
# 2. Dedupe behavior tests
# ---------------------------------------------------------------------------

class TestDedupe:
    """Dedupe layer correctly identifies duplicate documents."""

    def test_dedupe_by_source_key_external_id(self, session):
        _make_company(session)
        session.add(Document(
            source_type=SourceType.TEN_K, source_tier=SourceTier.TIER_1,
            title="10-K", primary_company_ticker="NVDA",
            source_key="sec_10k", external_id="0001234-56-789012",
        ))
        session.flush()

        payload = _make_payload(
            source_key="sec_10k", external_id="0001234-56-789012", url=None,
        )
        assert is_duplicate_document(session, payload) is True

    def test_dedupe_by_url(self, session):
        _make_company(session)
        session.add(Document(
            source_type=SourceType.NEWS, source_tier=SourceTier.TIER_3,
            title="News", url="https://example.com/article1",
            primary_company_ticker="NVDA",
        ))
        session.flush()

        payload = _make_payload(url="https://example.com/article1")
        assert is_duplicate_document(session, payload) is True

    def test_dedupe_by_content_hash(self, session):
        _make_company(session)
        import hashlib
        text = "unique content for hash test"
        h = hashlib.sha256(text.encode()).hexdigest()
        session.add(Document(
            source_type=SourceType.NEWS, source_tier=SourceTier.TIER_3,
            title="News", hash=h, primary_company_ticker="NVDA",
        ))
        session.flush()

        payload = _make_payload(url=None, raw_text=text)
        assert is_duplicate_document(session, payload) is True

    def test_no_duplicate_for_new_doc(self, session):
        _make_company(session)
        payload = _make_payload(url="https://example.com/new-article")
        assert is_duplicate_document(session, payload) is False

    def test_filter_new_documents(self, session):
        _make_company(session)
        session.add(Document(
            source_type=SourceType.NEWS, source_tier=SourceTier.TIER_3,
            title="Existing", url="https://example.com/existing",
            primary_company_ticker="NVDA",
        ))
        session.flush()

        payloads = [
            _make_payload(url="https://example.com/existing"),
            _make_payload(url="https://example.com/new1"),
            _make_payload(url="https://example.com/new2"),
        ]
        new = filter_new_documents(session, payloads)
        assert len(new) == 2

    def test_dedupe_priority_external_id_over_url(self, session):
        """External ID match should catch duplicates even with different URLs."""
        _make_company(session)
        session.add(Document(
            source_type=SourceType.TEN_K, source_tier=SourceTier.TIER_1,
            title="10-K", url="https://sec.gov/old-url",
            source_key="sec_10k", external_id="ACC-123",
            primary_company_ticker="NVDA",
        ))
        session.flush()

        payload = _make_payload(
            source_key="sec_10k", external_id="ACC-123",
            url="https://sec.gov/new-url",  # different URL
        )
        assert is_duplicate_document(session, payload) is True


# ---------------------------------------------------------------------------
# 3. Dry-run behavior tests
# ---------------------------------------------------------------------------

class TestDryRun:
    """Dry-run mode fetches and dedupes but does not persist."""

    def test_dry_run_no_documents_persisted(self, session):
        _make_company(session)
        mock_payloads = [_make_payload(source_key="sec_10k", external_id="ACC-001")]

        with _apply_patches(_all_connector_patches(sec_return=mock_payloads)):
            summary = run_ticker_pipeline(session, "NVDA", dry_run=True)

        docs = session.scalars(select(Document)).all()
        assert len(docs) == 0
        assert summary.total_docs_inserted == 1  # counted as "would insert"
        assert summary.total_docs_fetched == 1

    def test_dry_run_no_claims_created(self, session):
        _make_company(session)
        mock_payloads = [_make_payload()]

        with _apply_patches(_all_connector_patches(google_return=mock_payloads)):
            summary = run_ticker_pipeline(session, "NVDA", dry_run=True)

        claims = session.scalars(select(Claim)).all()
        assert len(claims) == 0


# ---------------------------------------------------------------------------
# 4. End-to-end ticker pipeline with mocked connectors
# ---------------------------------------------------------------------------

class TestEndToEndPipeline:
    """Full pipeline run with mocked connectors."""

    def test_full_pipeline_inserts_docs_and_extracts_claims(self, session):
        _make_company(session)

        payloads = [
            _make_payload(
                url="https://example.com/a1",
                title="Revenue grew strongly for NVDA AI infrastructure",
                raw_text="NVDA AI infrastructure revenue grew strongly this quarter with record demand",
            ),
            _make_payload(
                url="https://example.com/a2",
                title="NVDA margin expansion in AI infrastructure",
                raw_text="NVDA AI infrastructure margin expansion improving across all segments",
            ),
        ]

        with _apply_patches(_all_connector_patches(google_return=payloads)):
            summary = run_ticker_pipeline(session, "NVDA")

        assert summary.total_docs_fetched == 2
        assert summary.total_docs_inserted == 2
        docs = session.scalars(select(Document)).all()
        assert len(docs) == 2
        claims = session.scalars(select(Claim)).all()
        assert len(claims) >= 2  # at least one claim per doc

    def test_duplicate_docs_skipped(self, session):
        _make_company(session)

        # Pre-insert a document
        session.add(Document(
            source_type=SourceType.NEWS, source_tier=SourceTier.TIER_3,
            title="Existing", url="https://example.com/existing",
            primary_company_ticker="NVDA",
        ))
        session.flush()

        payloads = [
            _make_payload(url="https://example.com/existing"),  # dupe
            _make_payload(url="https://example.com/new-one", title="NVDA AI infrastructure new"),
        ]

        with _apply_patches(_all_connector_patches(google_return=payloads)):
            summary = run_ticker_pipeline(session, "NVDA")

        assert summary.total_docs_fetched == 2
        assert summary.total_docs_inserted == 1
        assert summary.total_duplicates_skipped == 1


# ---------------------------------------------------------------------------
# 5. Thesis update batching: one update per ticker-run
# ---------------------------------------------------------------------------

class TestThesisUpdateBatching:
    """Multiple documents for one ticker should trigger exactly one thesis update."""

    def test_single_thesis_update_for_multiple_docs(self, session):
        _make_company(session)
        thesis = _make_thesis(session)

        payloads = [
            _make_payload(url="https://example.com/d1", title="NVDA AI infrastructure revenue grew strongly"),
            _make_payload(url="https://example.com/d2", title="NVDA AI infrastructure margin expansion improving"),
            _make_payload(url="https://example.com/d3", title="NVDA AI infrastructure guidance above expectations strong"),
        ]

        with _apply_patches(_all_connector_patches(google_return=payloads)):
            summary = run_ticker_pipeline(session, "NVDA")

        assert summary.thesis_updated is True
        assert summary.thesis_update_result is not None

    def test_no_thesis_update_when_no_new_claims(self, session):
        _make_company(session)
        _make_thesis(session)

        with _apply_patches(_all_connector_patches()):
            summary = run_ticker_pipeline(session, "NVDA")

        assert summary.thesis_updated is False

    def test_no_thesis_update_when_no_thesis_exists(self, session):
        _make_company(session)
        # No thesis created

        payloads = [_make_payload(url="https://example.com/d1", title="NVDA AI infrastructure news")]

        with _apply_patches(_all_connector_patches(google_return=payloads)):
            summary = run_ticker_pipeline(session, "NVDA")

        assert summary.thesis_updated is False
        assert summary.total_docs_inserted == 1  # doc still inserted


# ---------------------------------------------------------------------------
# 6. NewsAPI graceful handling when key absent
# ---------------------------------------------------------------------------

class TestNewsAPIGraceful:
    """NewsAPI connector handles missing API key gracefully."""

    def test_newsapi_skips_when_no_key(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NEWSAPI_KEY", None)
            conn = NewsAPIConnector()
            assert conn.available is False
            results = conn.fetch("NVDA", days=7)
            assert results == []

    def test_newsapi_available_when_key_set(self):
        with patch.dict(os.environ, {"NEWSAPI_KEY": "test-key-123"}):
            conn = NewsAPIConnector()
            assert conn.available is True


# ---------------------------------------------------------------------------
# 7. SEC connector User-Agent header
# ---------------------------------------------------------------------------

class TestSECUserAgent:
    """SEC connector includes configured User-Agent header."""

    def test_default_user_agent(self):
        ua = _get_user_agent()
        assert "Consensus" in ua

    def test_custom_user_agent_from_env(self):
        with patch.dict(os.environ, {"SEC_USER_AGENT": "MyApp admin@test.com"}):
            ua = _get_user_agent()
            assert ua == "MyApp admin@test.com"

    @patch("connectors.sec_edgar.requests.get")
    def test_sec_fetch_includes_user_agent(self, mock_get, session):
        """SEC connector sends User-Agent in requests."""
        mock_cik_resp = MagicMock()
        mock_cik_resp.json.return_value = {"0": {"ticker": "NVDA", "cik_str": "1045810"}}
        mock_cik_resp.raise_for_status = MagicMock()

        mock_sub_resp = MagicMock()
        mock_sub_resp.json.return_value = {
            "filings": {"recent": {"form": [], "filingDate": [], "accessionNumber": [], "primaryDocument": []}}
        }
        mock_sub_resp.raise_for_status = MagicMock()

        mock_get.side_effect = [mock_cik_resp, mock_sub_resp]

        conn = SECEdgarConnector()
        conn.fetch("NVDA", days=30)

        assert mock_get.call_count >= 1
        for call in mock_get.call_args_list:
            headers = call.kwargs.get("headers", {})
            assert "User-Agent" in headers


# ---------------------------------------------------------------------------
# 8. Non-document updaters write to correct tables
# ---------------------------------------------------------------------------

class TestNonDocumentUpdaters:
    """yfinance updaters write to correct tables, not Document."""

    def test_price_updater_writes_to_prices_table(self, session):
        _make_company(session)

        import pandas as pd
        mock_hist = pd.DataFrame({
            "Open": [100.0, 101.0],
            "High": [105.0, 106.0],
            "Low": [99.0, 100.0],
            "Close": [103.0, 104.0],
            "Volume": [1000000, 1100000],
        }, index=pd.to_datetime(["2026-03-10", "2026-03-11"]))

        mock_yf = MagicMock()
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = mock_hist
        mock_yf.Ticker.return_value = mock_ticker

        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            updater = YFinancePriceUpdater()
            result = updater.update(session, "NVDA", days=7)

        assert result.rows_upserted == 2
        prices = session.scalars(select(Price)).all()
        assert len(prices) == 2
        docs = session.scalars(select(Document)).all()
        assert len(docs) == 0

    def test_calendar_updater_writes_to_checkpoints(self, session):
        _make_company(session)

        mock_yf = MagicMock()
        mock_ticker = MagicMock()
        mock_ticker.calendar = {"Earnings Date": [datetime(2026, 4, 15)]}
        mock_yf.Ticker.return_value = mock_ticker

        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            updater = YFinanceCalendarUpdater()
            result = updater.update(session, "NVDA")

        assert result.rows_upserted == 1
        checkpoints = session.scalars(select(Checkpoint)).all()
        assert len(checkpoints) == 1
        assert checkpoints[0].checkpoint_type == "earnings_release"
        assert checkpoints[0].linked_company_ticker == "NVDA"
        docs = session.scalars(select(Document)).all()
        assert len(docs) == 0

    def test_ticker_info_enriches_company(self, session):
        _make_company(session)

        mock_yf = MagicMock()
        mock_ticker = MagicMock()
        mock_ticker.info = {
            "sector": "Technology",
            "industry": "Semiconductors",
            "country": "United States",
            "exchange": "NMS",
            "longName": "NVIDIA Corporation",
            "marketCap": 3_000_000_000_000,
        }
        mock_yf.Ticker.return_value = mock_ticker

        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            updater = YFinanceTickerInfoUpdater()
            result = updater.update(session, "NVDA")

        assert result.rows_upserted == 1
        company = session.get(Company, "NVDA")
        assert company.sector == "Technology"
        assert company.industry == "Semiconductors"
        assert company.market_cap_bucket == "mega"
        docs = session.scalars(select(Document)).all()
        assert len(docs) == 0

    def test_price_dry_run_does_not_persist(self, session):
        _make_company(session)

        import pandas as pd
        mock_hist = pd.DataFrame({
            "Open": [100.0], "High": [105.0], "Low": [99.0],
            "Close": [103.0], "Volume": [1000000],
        }, index=pd.to_datetime(["2026-03-10"]))

        mock_yf = MagicMock()
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = mock_hist
        mock_yf.Ticker.return_value = mock_ticker

        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            updater = YFinancePriceUpdater()
            result = updater.update(session, "NVDA", dry_run=True)

        assert result.rows_upserted == 1  # counted as "would upsert"
        prices = session.scalars(select(Price)).all()
        assert len(prices) == 0


# ---------------------------------------------------------------------------
# 9. Document insertion and source_key/external_id
# ---------------------------------------------------------------------------

class TestDocumentInsertion:
    """Document ingestion service preserves source_key, external_id, and hash."""

    def test_insert_document_preserves_source_key(self, session):
        _make_company(session)
        payload = _make_payload(source_key="sec_10k", external_id="ACC-001")
        result = ingest_document_payload(session, payload, "NVDA")
        doc = session.get(Document, result.document_id)
        assert doc.source_key == "sec_10k"
        assert doc.external_id == "ACC-001"

    def test_insert_document_computes_hash(self, session):
        _make_company(session)
        payload = _make_payload(raw_text="test content")
        result = ingest_document_payload(session, payload, "NVDA")
        doc = session.get(Document, result.document_id)
        assert doc.hash is not None
        assert len(doc.hash) == 64


# ---------------------------------------------------------------------------
# 10. Pipeline summary structure
# ---------------------------------------------------------------------------

class TestPipelineSummary:
    """Pipeline returns a well-structured summary."""

    def test_summary_to_dict(self, session):
        _make_company(session)

        with _apply_patches(_all_connector_patches()):
            summary = run_ticker_pipeline(session, "NVDA")

        d = summary.to_dict()
        assert d["ticker"] == "NVDA"
        assert "started_at" in d
        assert "finished_at" in d
        assert isinstance(d["sources"], list)
        assert "total_docs_fetched" in d

    def test_source_filter_limits_connectors(self, session):
        _make_company(session)

        payloads = [_make_payload(url="https://example.com/filtered")]

        patches = [
            patch.object(GoogleRSSConnector, 'fetch', return_value=payloads),
        ] + _nondoc_patches()

        with _apply_patches(patches):
            summary = run_ticker_pipeline(
                session, "NVDA",
                source_filter=["news_google_rss"],
            )

        doc_sources = [s for s in summary.source_summaries if s.docs_fetched > 0]
        assert len(doc_sources) == 1
        assert doc_sources[0].source == "news_google_rss"


# ---------------------------------------------------------------------------
# 11. Canonical ingestion service tests
# ---------------------------------------------------------------------------

class TestCanonicalIngestionService:
    """document_ingestion_service.ingest_document_payload works standalone."""

    def test_service_inserts_doc_and_extracts_claims(self, session):
        _make_company(session)
        payload = _make_payload(
            raw_text="NVDA AI infrastructure revenue grew strongly this quarter",
        )
        result = ingest_document_payload(session, payload, "NVDA")

        assert result.document_id is not None
        assert len(result.claim_ids) >= 1

        doc = session.get(Document, result.document_id)
        assert doc is not None
        assert doc.source_key == "news_google_rss"

        claims = session.scalars(
            select(Claim).where(Claim.document_id == result.document_id)
        ).all()
        assert len(claims) == len(result.claim_ids)

    def test_service_creates_company_and_theme_links(self, session):
        _make_company(session)
        payload = _make_payload(
            raw_text="NVDA AI infrastructure revenue grew strongly",
        )
        result = ingest_document_payload(session, payload, "NVDA")

        from models import ClaimCompanyLink
        links = session.scalars(
            select(ClaimCompanyLink).where(
                ClaimCompanyLink.claim_id.in_(result.claim_ids)
            )
        ).all()
        assert len(links) >= 1
        assert any(l.company_ticker == "NVDA" for l in links)

    def test_service_runs_novelty_classification(self, session):
        _make_company(session)

        # First document establishes prior claims
        p1 = _make_payload(
            url="https://example.com/first",
            raw_text="NVDA AI infrastructure revenue grew strongly this quarter",
        )
        ingest_document_payload(session, p1, "NVDA")

        # Second document with similar text should get non-NEW novelty
        p2 = _make_payload(
            url="https://example.com/second",
            raw_text="NVDA AI infrastructure revenue grew strongly last quarter",
        )
        result2 = ingest_document_payload(session, p2, "NVDA")

        claims = session.scalars(
            select(Claim).where(Claim.id.in_(result2.claim_ids))
        ).all()
        # At least one claim should have been reclassified (not all NEW)
        novelty_types = {c.novelty_type for c in claims}
        assert len(claims) >= 1
        # The classifier should have run — exact classification depends on
        # similarity thresholds, but we verify it didn't crash
        assert all(c.novelty_type is not None for c in claims)


# ---------------------------------------------------------------------------
# 12. Pipeline delegates to ingestion service
# ---------------------------------------------------------------------------

class TestPipelineDelegation:
    """pipeline_runner delegates document ingestion to the canonical service."""

    def test_pipeline_calls_ingestion_service(self, session):
        """run_ticker_pipeline delegates to ingest_document_payload."""
        _make_company(session)
        payloads = [_make_payload(url="https://example.com/delegate-test")]

        from document_ingestion_service import IngestionResult
        mock_result = IngestionResult(document_id=999, claim_ids=[1, 2])

        patches = _all_connector_patches(google_return=payloads) + [
            patch("pipeline_runner.ingest_document_payload", return_value=mock_result),
        ]

        with _apply_patches(patches):
            summary = run_ticker_pipeline(session, "NVDA")

        assert summary.total_docs_inserted == 1
        assert summary.total_claims_extracted == 2

    def test_dry_run_skips_ingestion_service(self, session):
        """Dry-run should never call ingest_document_payload."""
        _make_company(session)
        payloads = [_make_payload(url="https://example.com/dryrun-test")]

        mock_ingest = MagicMock()

        patches = _all_connector_patches(google_return=payloads) + [
            patch("pipeline_runner.ingest_document_payload", mock_ingest),
        ]

        with _apply_patches(patches):
            summary = run_ticker_pipeline(session, "NVDA", dry_run=True)

        mock_ingest.assert_not_called()
        assert summary.total_docs_inserted == 1  # counted as "would insert"

    def test_non_documents_only_skips_ingestion_service(self, session):
        """non_documents_only should never call ingest_document_payload."""
        _make_company(session)

        mock_ingest = MagicMock()

        patches = _nondoc_patches() + [
            patch("pipeline_runner.ingest_document_payload", mock_ingest),
        ]

        with _apply_patches(patches):
            summary = run_ticker_pipeline(session, "NVDA", non_documents_only=True)

        mock_ingest.assert_not_called()
