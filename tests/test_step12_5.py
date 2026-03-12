"""Step 12.5 tests: operator console and live observability.

Tests:
  - Console API data layer returns correct data from DB
  - Document detail maps to real claim/thesis objects
  - Thesis timeline uses real state history
  - Review view reflects actual latest review data
  - Event timeline shows pipeline stages
  - Graph panel consumes real graph output
  - System status returns correct counts
  - Console app is read-only (no mutations)
  - Demo mode is clearly labeled
  - Flask routes return correct status codes
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import (
    Base, Company, Document, Claim, Theme, Thesis, ThesisStateHistory,
    PortfolioPosition, Candidate, PortfolioReview, PortfolioDecision,
    ClaimCompanyLink, ClaimThemeLink, ThesisClaimLink,
    ExecutionIntentRecord, PaperFillRecord, PaperPortfolioSnapshotRecord,
    SourceType, SourceTier, ClaimType, EconomicChannel, Direction,
    NoveltyType, ThesisState, ZoneState, PositionStatus, ActionType,
)
from console_api import (
    get_recent_documents,
    get_document_detail,
    get_thesis_detail,
    get_ticker_theses,
    get_latest_review,
    get_portfolio_positions,
    get_candidates,
    get_latest_execution,
    get_company_overview,
    get_system_status,
    get_event_timeline,
    get_all_tickers,
    get_graph_company_view,
    get_graph_full_summary,
)


def _make_session():
    """Create an in-memory SQLite session with schema."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def _seed_basic(session):
    """Seed basic test data: company, document, claims, thesis, position."""
    # Company
    session.add(Company(ticker="NVDA", name="NVIDIA Corp", sector="Technology"))
    session.add(Company(ticker="MSFT", name="Microsoft Corp", sector="Technology"))
    session.flush()

    # Theme
    session.add(Theme(id=1, theme_name="AI Accelerators", theme_type="secular"))
    session.flush()

    # Document
    doc = Document(
        id=1,
        source_type=SourceType.EIGHT_K,
        source_tier=SourceTier.TIER_1,
        title="NVIDIA Q4 2025 8-K Filing",
        publisher="SEC",
        published_at=datetime(2025, 2, 15, 10, 0),
        ingested_at=datetime(2025, 2, 15, 10, 5),
        primary_company_ticker="NVDA",
        document_type="8K",
    )
    session.add(doc)
    session.flush()

    # Claims
    c1 = Claim(
        id=1, document_id=1,
        claim_text_normalized="Data center revenue grew 40% YoY",
        claim_text_short="DC revenue +40% YoY",
        claim_type=ClaimType.DEMAND,
        economic_channel=EconomicChannel.REVENUE,
        direction=Direction.POSITIVE,
        strength=0.85,
        novelty_type=NoveltyType.NEW,
        confidence=0.9,
        published_at=datetime(2025, 2, 15, 10, 0),
    )
    c2 = Claim(
        id=2, document_id=1,
        claim_text_normalized="Gross margin expanded to 76%",
        claim_text_short="Gross margin 76%",
        claim_type=ClaimType.MARGIN,
        economic_channel=EconomicChannel.GROSS_MARGIN,
        direction=Direction.POSITIVE,
        strength=0.7,
        novelty_type=NoveltyType.CONFIRMING,
        confidence=0.85,
        published_at=datetime(2025, 2, 15, 10, 0),
    )
    session.add_all([c1, c2])
    session.flush()

    # Claim-company links
    session.add(ClaimCompanyLink(claim_id=1, company_ticker="NVDA", relation_type="about"))
    session.add(ClaimCompanyLink(claim_id=2, company_ticker="NVDA", relation_type="about"))
    session.flush()

    # Claim-theme links
    session.add(ClaimThemeLink(claim_id=1, theme_id=1))
    session.flush()

    # Thesis
    thesis = Thesis(
        id=1, title="NVIDIA AI dominance thesis",
        company_ticker="NVDA", state=ThesisState.STRENGTHENING,
        conviction_score=72.0, valuation_gap_pct=15.0,
        base_case_rerating=25.0, status_active=True,
        created_at=datetime(2025, 1, 1), updated_at=datetime(2025, 2, 15),
    )
    session.add(thesis)
    session.flush()

    # Thesis-claim links
    session.add(ThesisClaimLink(thesis_id=1, claim_id=1, link_type="supports"))
    session.add(ThesisClaimLink(thesis_id=1, claim_id=2, link_type="supports"))
    session.flush()

    # Thesis state history
    session.add(ThesisStateHistory(
        id=1, thesis_id=1, state=ThesisState.FORMING,
        conviction_score=50.0, valuation_gap_pct=20.0,
        note="Initial thesis formation",
        created_at=datetime(2025, 1, 1),
    ))
    session.add(ThesisStateHistory(
        id=2, thesis_id=1, state=ThesisState.STRENGTHENING,
        conviction_score=72.0, valuation_gap_pct=15.0,
        note="Q4 earnings confirmed DC demand",
        created_at=datetime(2025, 2, 15),
    ))
    session.flush()

    # Position
    session.add(PortfolioPosition(
        id=1, ticker="NVDA", thesis_id=1,
        entry_date=date(2025, 1, 15), avg_cost=450.0,
        current_weight=8.0, target_weight=10.0,
        conviction_score=72.0, zone_state=ZoneState.BUY,
        status=PositionStatus.ACTIVE,
    ))
    session.flush()

    # Candidate
    session.add(Candidate(
        id=1, ticker="MSFT", primary_thesis_id=None,
        conviction_score=55.0, buyable_flag=True,
        zone_state=ZoneState.HOLD, watch_reason="Cloud growth thesis forming",
    ))
    session.flush()

    # Review + decisions
    review = PortfolioReview(
        id=1, review_date=date(2025, 2, 15), review_type="weekly",
        holdings_reviewed=1, candidates_reviewed=1, turnover_pct=3.5,
        created_at=datetime(2025, 2, 15, 12, 0),
    )
    session.add(review)
    session.flush()

    session.add(PortfolioDecision(
        id=1, review_id=1, ticker="NVDA",
        action=ActionType.ADD, action_score=75.0,
        target_weight_change=2.0, suggested_weight=10.0,
        reason_codes=json.dumps(["THESIS_STRENGTHENING", "VALUATION_ATTRACTIVE"]),
        rationale="Conviction increased on Q4 results",
        was_executed=True,
        generated_at=datetime(2025, 2, 15, 12, 0),
    ))
    session.add(PortfolioDecision(
        id=2, review_id=1, ticker="MSFT",
        action=ActionType.NO_ACTION, action_score=10.0,
        reason_codes=json.dumps([]),
        rationale="Watchlist — thesis not yet formed",
        was_executed=False,
        generated_at=datetime(2025, 2, 15, 12, 0),
    ))
    session.flush()

    return session


# ===========================================================================
# Test: Console API — Recent Documents
# ===========================================================================

class TestRecentDocuments(unittest.TestCase):
    def setUp(self):
        self.session = _make_session()
        _seed_basic(self.session)

    def test_returns_documents(self):
        docs = get_recent_documents(self.session, limit=10)
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["ticker"], "NVDA")

    def test_document_has_claim_count(self):
        docs = get_recent_documents(self.session, limit=10)
        self.assertEqual(docs[0]["claim_count"], 2)

    def test_document_has_novelty_counts(self):
        docs = get_recent_documents(self.session, limit=10)
        nc = docs[0]["novelty_counts"]
        self.assertEqual(nc.get("new"), 1)
        self.assertEqual(nc.get("confirming"), 1)

    def test_thesis_update_triggered(self):
        docs = get_recent_documents(self.session, limit=10)
        self.assertTrue(docs[0]["thesis_update_triggered"])

    def test_ingestion_status(self):
        docs = get_recent_documents(self.session, limit=10)
        self.assertEqual(docs[0]["ingestion_status"], "OK")

    def test_limit_respected(self):
        docs = get_recent_documents(self.session, limit=0)
        self.assertEqual(len(docs), 0)


# ===========================================================================
# Test: Console API — Document Detail
# ===========================================================================

class TestDocumentDetail(unittest.TestCase):
    def setUp(self):
        self.session = _make_session()
        _seed_basic(self.session)

    def test_returns_document(self):
        detail = get_document_detail(self.session, 1)
        self.assertIsNotNone(detail)
        self.assertEqual(detail["document"]["ticker"], "NVDA")

    def test_claims_present(self):
        detail = get_document_detail(self.session, 1)
        self.assertEqual(len(detail["claims"]), 2)

    def test_claim_has_linked_tickers(self):
        detail = get_document_detail(self.session, 1)
        c = detail["claims"][0]
        self.assertIn("NVDA", c["linked_tickers"])

    def test_claim_has_linked_themes(self):
        detail = get_document_detail(self.session, 1)
        # First claim is linked to theme
        c = detail["claims"][0]
        self.assertTrue(len(c["linked_themes"]) > 0)
        self.assertEqual(c["linked_themes"][0]["name"], "AI Accelerators")

    def test_claim_has_linked_theses(self):
        detail = get_document_detail(self.session, 1)
        c = detail["claims"][0]
        self.assertTrue(len(c["linked_theses"]) > 0)
        self.assertEqual(c["linked_theses"][0]["link_type"], "supports")

    def test_not_found(self):
        detail = get_document_detail(self.session, 999)
        self.assertIsNone(detail)

    def test_claim_fields(self):
        detail = get_document_detail(self.session, 1)
        c = detail["claims"][0]
        self.assertEqual(c["claim_type"], "demand")
        self.assertEqual(c["direction"], "positive")
        self.assertEqual(c["novelty_type"], "new")
        self.assertAlmostEqual(c["strength"], 0.85)


# ===========================================================================
# Test: Console API — Thesis Detail
# ===========================================================================

class TestThesisDetail(unittest.TestCase):
    def setUp(self):
        self.session = _make_session()
        _seed_basic(self.session)

    def test_returns_thesis(self):
        detail = get_thesis_detail(self.session, 1)
        self.assertIsNotNone(detail)
        self.assertEqual(detail["ticker"], "NVDA")
        self.assertEqual(detail["state"], "strengthening")

    def test_has_history(self):
        detail = get_thesis_detail(self.session, 1)
        self.assertEqual(len(detail["history"]), 2)
        self.assertEqual(detail["history"][0]["state"], "forming")
        self.assertEqual(detail["history"][1]["state"], "strengthening")

    def test_history_ordered(self):
        detail = get_thesis_detail(self.session, 1)
        times = [h["created_at"] for h in detail["history"]]
        self.assertEqual(times, sorted(times))

    def test_conviction_in_history(self):
        detail = get_thesis_detail(self.session, 1)
        self.assertAlmostEqual(detail["history"][0]["conviction_score"], 50.0)
        self.assertAlmostEqual(detail["history"][1]["conviction_score"], 72.0)

    def test_not_found(self):
        detail = get_thesis_detail(self.session, 999)
        self.assertIsNone(detail)


class TestTickerTheses(unittest.TestCase):
    def setUp(self):
        self.session = _make_session()
        _seed_basic(self.session)

    def test_returns_theses(self):
        theses = get_ticker_theses(self.session, "NVDA")
        self.assertEqual(len(theses), 1)
        self.assertEqual(theses[0]["title"], "NVIDIA AI dominance thesis")

    def test_empty_for_unknown(self):
        theses = get_ticker_theses(self.session, "ZZZZ")
        self.assertEqual(len(theses), 0)


# ===========================================================================
# Test: Console API — Portfolio / Reviews
# ===========================================================================

class TestPortfolioReview(unittest.TestCase):
    def setUp(self):
        self.session = _make_session()
        _seed_basic(self.session)

    def test_latest_review(self):
        review = get_latest_review(self.session)
        self.assertIsNotNone(review)
        self.assertEqual(review["review_type"], "weekly")
        self.assertEqual(len(review["decisions"]), 2)

    def test_decisions_sorted(self):
        review = get_latest_review(self.session)
        actions = [d["action"] for d in review["decisions"]]
        # add comes before no_action in our sort
        self.assertEqual(actions[0], "add")

    def test_decision_has_reason_codes(self):
        review = get_latest_review(self.session)
        add_dec = [d for d in review["decisions"] if d["action"] == "add"][0]
        self.assertIn("THESIS_STRENGTHENING", add_dec["reason_codes"])

    def test_no_review(self):
        session = _make_session()
        review = get_latest_review(session)
        self.assertIsNone(review)


class TestPositions(unittest.TestCase):
    def setUp(self):
        self.session = _make_session()
        _seed_basic(self.session)

    def test_returns_positions(self):
        positions = get_portfolio_positions(self.session)
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0]["ticker"], "NVDA")
        self.assertAlmostEqual(positions[0]["current_weight"], 8.0)

    def test_zone_state(self):
        positions = get_portfolio_positions(self.session)
        self.assertEqual(positions[0]["zone_state"], "buy")


class TestCandidates(unittest.TestCase):
    def setUp(self):
        self.session = _make_session()
        _seed_basic(self.session)

    def test_returns_candidates(self):
        candidates = get_candidates(self.session)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["ticker"], "MSFT")
        self.assertTrue(candidates[0]["buyable_flag"])


# ===========================================================================
# Test: Console API — Company Overview
# ===========================================================================

class TestCompanyOverview(unittest.TestCase):
    def setUp(self):
        self.session = _make_session()
        _seed_basic(self.session)

    def test_overview(self):
        ov = get_company_overview(self.session, "NVDA")
        self.assertIsNotNone(ov)
        self.assertEqual(ov["ticker"], "NVDA")
        self.assertEqual(ov["documents"], 1)
        self.assertEqual(ov["claims"], 2)
        self.assertEqual(ov["theses"], 1)
        self.assertTrue(ov["is_owned"])
        self.assertAlmostEqual(ov["current_weight"], 8.0)

    def test_not_found(self):
        ov = get_company_overview(self.session, "ZZZZ")
        self.assertIsNone(ov)

    def test_candidate_company(self):
        ov = get_company_overview(self.session, "MSFT")
        self.assertIsNotNone(ov)
        self.assertFalse(ov["is_owned"])
        self.assertTrue(ov["is_candidate"])


# ===========================================================================
# Test: Console API — System Status
# ===========================================================================

class TestSystemStatus(unittest.TestCase):
    def setUp(self):
        self.session = _make_session()
        _seed_basic(self.session)

    def test_counts(self):
        status = get_system_status(self.session)
        self.assertEqual(status["companies"], 2)
        self.assertEqual(status["documents"], 1)
        self.assertEqual(status["claims"], 2)
        self.assertEqual(status["theses"], 1)
        self.assertEqual(status["active_positions"], 1)
        self.assertEqual(status["candidates"], 1)
        self.assertEqual(status["reviews"], 1)

    def test_empty_db(self):
        session = _make_session()
        status = get_system_status(session)
        self.assertEqual(status["companies"], 0)
        self.assertEqual(status["documents"], 0)


# ===========================================================================
# Test: Console API — Event Timeline
# ===========================================================================

class TestEventTimeline(unittest.TestCase):
    def setUp(self):
        self.session = _make_session()
        _seed_basic(self.session)

    def test_timeline_has_ingest(self):
        timeline = get_event_timeline(self.session, 1)
        stages = [e["stage"] for e in timeline]
        self.assertIn("INGEST", stages)

    def test_timeline_has_claims(self):
        timeline = get_event_timeline(self.session, 1)
        stages = [e["stage"] for e in timeline]
        self.assertIn("CLAIMS", stages)

    def test_timeline_has_memory(self):
        timeline = get_event_timeline(self.session, 1)
        stages = [e["stage"] for e in timeline]
        self.assertIn("MEMORY", stages)

    def test_timeline_has_thesis(self):
        timeline = get_event_timeline(self.session, 1)
        stages = [e["stage"] for e in timeline]
        self.assertIn("THESIS", stages)

    def test_timeline_ticker(self):
        timeline = get_event_timeline(self.session, 1)
        ingest = [e for e in timeline if e["stage"] == "INGEST"][0]
        self.assertEqual(ingest["ticker"], "NVDA")

    def test_not_found(self):
        timeline = get_event_timeline(self.session, 999)
        self.assertEqual(len(timeline), 0)


# ===========================================================================
# Test: Console API — All Tickers
# ===========================================================================

class TestAllTickers(unittest.TestCase):
    def setUp(self):
        self.session = _make_session()
        _seed_basic(self.session)

    def test_returns_all(self):
        tickers = get_all_tickers(self.session)
        self.assertEqual(len(tickers), 2)
        ticker_names = [t["ticker"] for t in tickers]
        self.assertIn("NVDA", ticker_names)
        self.assertIn("MSFT", ticker_names)

    def test_sorted(self):
        tickers = get_all_tickers(self.session)
        names = [t["ticker"] for t in tickers]
        self.assertEqual(names, sorted(names))


# ===========================================================================
# Test: Console API — Graph Integration
# ===========================================================================

class TestGraphIntegration(unittest.TestCase):
    def test_graph_summary(self):
        """Ensure graph summary works with an in-memory graph."""
        from graph_memory import ConsensusGraph
        cg = ConsensusGraph()
        summary = get_graph_full_summary(cg)
        self.assertEqual(summary["total_nodes"], 0)
        self.assertEqual(summary["total_edges"], 0)

    def test_graph_company_view_empty(self):
        """Company view on empty graph returns empty data."""
        from graph_memory import ConsensusGraph
        cg = ConsensusGraph()
        data = get_graph_company_view(cg, "NVDA")
        self.assertEqual(len(data["nodes"]), 0)
        self.assertEqual(len(data["edges"]), 0)

    def test_graph_company_view_with_data(self):
        """Company view with seeded graph returns nodes/edges."""
        from graph_memory import ConsensusGraph, NodeType, EdgeType
        cg = ConsensusGraph()
        cg.add_node(NodeType.COMPANY, "NVDA", name="NVIDIA", sector="Tech")
        cg.add_node(NodeType.THESIS, 1, title="AI thesis", company_ticker="NVDA",
                     state="strengthening", conviction_score=72)
        cg.add_edge(
            f"Thesis:1", f"Company:NVDA", EdgeType.THESIS_FOR_COMPANY,
        )
        data = get_graph_company_view(cg, "NVDA")
        self.assertGreaterEqual(len(data["nodes"]), 2)
        self.assertGreaterEqual(len(data["edges"]), 1)


# ===========================================================================
# Test: Console App — Flask Routes
# ===========================================================================

class TestConsoleApp(unittest.TestCase):
    def setUp(self):
        # Patch db.get_session to use in-memory DB
        import db as db_module
        self._orig_get_session = db_module.get_session

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)

        from contextlib import contextmanager
        @contextmanager
        def mock_get_session():
            session = Session()
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        db_module.get_session = mock_get_session

        # Seed data
        session = Session()
        _seed_basic(session)
        session.commit()
        session.close()

        # Recreate to verify seeded data persists
        self._Session = Session

        from console_app import create_console_app
        app = create_console_app(graph=None, demo_mode=True)
        app.config["TESTING"] = True
        self.client = app.test_client()

    def tearDown(self):
        import db as db_module
        db_module.get_session = self._orig_get_session

    def test_index(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"CONSENSUS", resp.data)

    def test_api_status(self):
        resp = self.client.get("/api/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["demo_mode"])
        self.assertFalse(data["graph_loaded"])

    def test_api_recent_docs(self):
        resp = self.client.get("/api/documents/recent")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIsInstance(data, list)

    def test_api_document_detail(self):
        resp = self.client.get("/api/documents/1")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("document", data)
        self.assertIn("claims", data)

    def test_api_document_not_found(self):
        resp = self.client.get("/api/documents/999")
        self.assertEqual(resp.status_code, 404)

    def test_api_document_timeline(self):
        resp = self.client.get("/api/documents/1/timeline")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIsInstance(data, list)
        stages = [e["stage"] for e in data]
        self.assertIn("INGEST", stages)

    def test_api_thesis(self):
        resp = self.client.get("/api/theses/1")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["ticker"], "NVDA")

    def test_api_ticker_theses(self):
        resp = self.client.get("/api/tickers/NVDA/theses")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIsInstance(data, list)

    def test_api_latest_review(self):
        resp = self.client.get("/api/reviews/latest")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("decisions", data)

    def test_api_positions(self):
        resp = self.client.get("/api/positions")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIsInstance(data, list)

    def test_api_candidates(self):
        resp = self.client.get("/api/candidates")
        self.assertEqual(resp.status_code, 200)

    def test_api_tickers(self):
        resp = self.client.get("/api/tickers")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        tickers = [t["ticker"] for t in data]
        self.assertIn("NVDA", tickers)

    def test_api_company_overview(self):
        resp = self.client.get("/api/tickers/NVDA/overview")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["ticker"], "NVDA")
        self.assertTrue(data["is_owned"])

    def test_api_graph_not_loaded(self):
        resp = self.client.get("/api/graph/company/NVDA")
        self.assertEqual(resp.status_code, 503)

    def test_demo_mode_flag(self):
        resp = self.client.get("/api/status")
        data = resp.get_json()
        self.assertTrue(data["demo_mode"])


# ===========================================================================
# Test: Read-only — Console Cannot Mutate State
# ===========================================================================

class TestReadOnly(unittest.TestCase):
    """Verify the console has no mutation endpoints."""

    def setUp(self):
        import db as db_module
        self._orig_get_session = db_module.get_session

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)

        from contextlib import contextmanager
        @contextmanager
        def mock_get_session():
            session = Session()
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        db_module.get_session = mock_get_session
        self._Session = Session

        session = Session()
        _seed_basic(session)
        session.commit()
        session.close()

        from console_app import create_console_app
        app = create_console_app(graph=None, demo_mode=False)
        app.config["TESTING"] = True
        self.client = app.test_client()

    def tearDown(self):
        import db as db_module
        db_module.get_session = self._orig_get_session

    def test_no_post_endpoints(self):
        """POST to API endpoints should return 405 (method not allowed)."""
        endpoints = [
            "/api/status",
            "/api/documents/recent",
            "/api/documents/1",
            "/api/tickers",
            "/api/positions",
        ]
        for ep in endpoints:
            resp = self.client.post(ep)
            self.assertIn(resp.status_code, [405, 308],
                          f"POST to {ep} returned {resp.status_code}")

    def test_no_put_endpoints(self):
        """PUT to API endpoints should return 405."""
        resp = self.client.put("/api/documents/1")
        self.assertIn(resp.status_code, [405, 308])

    def test_no_delete_endpoints(self):
        """DELETE to API endpoints should return 405."""
        resp = self.client.delete("/api/documents/1")
        self.assertIn(resp.status_code, [405, 308])

    def test_data_unchanged_after_reads(self):
        """Multiple reads should not change underlying data."""
        session = self._Session()
        count_before = session.query(Document).count()
        session.close()

        # Make several read requests
        self.client.get("/api/documents/recent")
        self.client.get("/api/documents/1")
        self.client.get("/api/status")
        self.client.get("/api/positions")

        session = self._Session()
        count_after = session.query(Document).count()
        session.close()
        self.assertEqual(count_before, count_after)


# ===========================================================================
# Test: Console API — Serialization helpers
# ===========================================================================

class TestSerialization(unittest.TestCase):
    def test_ser_none(self):
        from console_api import _ser
        self.assertIsNone(_ser(None))

    def test_ser_enum(self):
        from console_api import _ser
        self.assertEqual(_ser(SourceType.NEWS), "news")

    def test_ser_datetime(self):
        from console_api import _ser
        dt = datetime(2025, 1, 15, 10, 0)
        result = _ser(dt)
        self.assertIn("2025-01-15", result)

    def test_ser_date(self):
        from console_api import _ser
        d = date(2025, 1, 15)
        result = _ser(d)
        self.assertEqual(result, "2025-01-15")

    def test_ser_string(self):
        from console_api import _ser
        self.assertEqual(_ser("hello"), "hello")


# ===========================================================================
# Test: Console API — Demo Subjects
# ===========================================================================

class TestDemoSubjects(unittest.TestCase):
    def setUp(self):
        self.session = _make_session()
        _seed_basic(self.session)

    def test_returns_all_keys(self):
        from console_api import get_demo_subjects
        result = get_demo_subjects(self.session)
        self.assertIn("latest_thesis_delta", result)
        self.assertIn("latest_actionable", result)
        self.assertIn("latest_thesis_trigger", result)
        self.assertIn("latest_conviction_change", result)

    def test_latest_thesis_delta_found(self):
        from console_api import get_demo_subjects
        result = get_demo_subjects(self.session)
        td = result["latest_thesis_delta"]
        self.assertIsNotNone(td)
        self.assertEqual(td["ticker"], "NVDA")
        self.assertEqual(td["old_state"], "forming")
        self.assertEqual(td["new_state"], "strengthening")
        self.assertAlmostEqual(td["conviction_delta"], 22.0)

    def test_latest_actionable_found(self):
        from console_api import get_demo_subjects
        result = get_demo_subjects(self.session)
        a = result["latest_actionable"]
        self.assertIsNotNone(a)
        self.assertEqual(a["ticker"], "NVDA")
        self.assertEqual(a["action"], "add")

    def test_latest_thesis_trigger_found(self):
        from console_api import get_demo_subjects
        result = get_demo_subjects(self.session)
        tt = result["latest_thesis_trigger"]
        self.assertIsNotNone(tt)
        self.assertEqual(tt["doc_id"], 1)
        self.assertEqual(tt["ticker"], "NVDA")

    def test_latest_conviction_change(self):
        from console_api import get_demo_subjects
        result = get_demo_subjects(self.session)
        cc = result["latest_conviction_change"]
        self.assertIsNotNone(cc)
        self.assertEqual(cc["ticker"], "NVDA")
        self.assertAlmostEqual(cc["delta"], 22.0)

    def test_empty_db_returns_all_none(self):
        from console_api import get_demo_subjects
        session = _make_session()
        result = get_demo_subjects(session)
        self.assertIsNone(result["latest_thesis_delta"])
        self.assertIsNone(result["latest_actionable"])
        self.assertIsNone(result["latest_thesis_trigger"])
        self.assertIsNone(result["latest_conviction_change"])


# ===========================================================================
# Test: Console API — What Changed
# ===========================================================================

class TestWhatChanged(unittest.TestCase):
    def setUp(self):
        self.session = _make_session()
        _seed_basic(self.session)

    def test_returns_summary(self):
        from console_api import get_what_changed
        result = get_what_changed(self.session, 1)
        self.assertIsNotNone(result)
        self.assertIn("document", result)
        self.assertIn("new_information", result)
        self.assertIn("retrieved_memory", result)
        self.assertIn("thesis_delta", result)
        self.assertIn("recommendation_delta", result)
        self.assertIn("why_it_matters", result)

    def test_document_field(self):
        from console_api import get_what_changed
        result = get_what_changed(self.session, 1)
        self.assertEqual(result["document"]["ticker"], "NVDA")
        self.assertEqual(result["document"]["id"], 1)

    def test_new_information_from_claims(self):
        from console_api import get_what_changed
        result = get_what_changed(self.session, 1)
        self.assertEqual(len(result["new_information"]), 2)
        types = [c["claim_type"] for c in result["new_information"]]
        self.assertIn("demand", types)

    def test_retrieved_memory_has_themes(self):
        from console_api import get_what_changed
        result = get_what_changed(self.session, 1)
        self.assertIn("AI Accelerators", result["retrieved_memory"])

    def test_thesis_delta_present(self):
        from console_api import get_what_changed
        result = get_what_changed(self.session, 1)
        self.assertEqual(len(result["thesis_delta"]), 1)
        td = result["thesis_delta"][0]
        self.assertEqual(td["old_state"], "forming")
        self.assertEqual(td["new_state"], "strengthening")
        self.assertAlmostEqual(td["conviction_delta"], 22.0)

    def test_recommendation_delta(self):
        from console_api import get_what_changed
        result = get_what_changed(self.session, 1)
        self.assertTrue(len(result["recommendation_delta"]) >= 1)
        actions = [r["action"] for r in result["recommendation_delta"]]
        self.assertIn("add", actions)

    def test_why_it_matters_not_empty(self):
        from console_api import get_what_changed
        result = get_what_changed(self.session, 1)
        self.assertTrue(len(result["why_it_matters"]) > 0)

    def test_not_found(self):
        from console_api import get_what_changed
        result = get_what_changed(self.session, 999)
        self.assertIsNone(result)


# ===========================================================================
# Test: Console API — Narrative Export
# ===========================================================================

class TestNarrativeExport(unittest.TestCase):
    def setUp(self):
        self.session = _make_session()
        _seed_basic(self.session)

    def test_returns_steps(self):
        from console_api import get_narrative_export
        result = get_narrative_export(self.session, 1)
        self.assertIsInstance(result, list)
        self.assertTrue(len(result) >= 4)

    def test_has_all_stages(self):
        from console_api import get_narrative_export
        result = get_narrative_export(self.session, 1)
        stages = [s["stage"] for s in result]
        self.assertIn("INGEST", stages)
        self.assertIn("CLAIMS", stages)
        self.assertIn("MEMORY", stages)
        self.assertIn("THESIS", stages)
        self.assertIn("GRAPH", stages)

    def test_ingest_has_title(self):
        from console_api import get_narrative_export
        result = get_narrative_export(self.session, 1)
        ingest = [s for s in result if s["stage"] == "INGEST"][0]
        self.assertIn("NVIDIA", ingest["text"])

    def test_claims_has_count(self):
        from console_api import get_narrative_export
        result = get_narrative_export(self.session, 1)
        claims = [s for s in result if s["stage"] == "CLAIMS"][0]
        self.assertIn("2 claims", claims["text"])

    def test_not_found(self):
        from console_api import get_narrative_export
        result = get_narrative_export(self.session, 999)
        self.assertEqual(len(result), 0)

    def test_recommendation_stage(self):
        from console_api import get_narrative_export
        result = get_narrative_export(self.session, 1)
        stages = [s["stage"] for s in result]
        self.assertIn("RECOMMENDATION", stages)


# ===========================================================================
# Test: Console App — Demo Polish Routes
# ===========================================================================

class TestDemoPolishRoutes(unittest.TestCase):
    def setUp(self):
        import db as db_module
        self._orig_get_session = db_module.get_session

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)

        from contextlib import contextmanager
        @contextmanager
        def mock_get_session():
            session = Session()
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        db_module.get_session = mock_get_session

        session = Session()
        _seed_basic(session)
        session.commit()
        session.close()

        from console_app import create_console_app
        app = create_console_app(graph=None, demo_mode=True)
        app.config["TESTING"] = True
        self.client = app.test_client()

    def tearDown(self):
        import db as db_module
        db_module.get_session = self._orig_get_session

    def test_demo_subjects_endpoint(self):
        resp = self.client.get("/api/demo/subjects")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("latest_thesis_delta", data)
        self.assertIn("latest_actionable", data)

    def test_what_changed_endpoint(self):
        resp = self.client.get("/api/documents/1/what-changed")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("document", data)
        self.assertIn("new_information", data)
        self.assertIn("thesis_delta", data)
        self.assertIn("why_it_matters", data)

    def test_what_changed_not_found(self):
        resp = self.client.get("/api/documents/999/what-changed")
        self.assertEqual(resp.status_code, 404)

    def test_narrative_endpoint(self):
        resp = self.client.get("/api/documents/1/narrative")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIsInstance(data, list)
        stages = [s["stage"] for s in data]
        self.assertIn("INGEST", stages)

    def test_narrative_not_found(self):
        resp = self.client.get("/api/documents/999/narrative")
        self.assertEqual(resp.status_code, 404)

    def test_demo_mode_labeled(self):
        resp = self.client.get("/api/status")
        data = resp.get_json()
        self.assertTrue(data["demo_mode"])

    def test_real_mode_labeled(self):
        import db as db_module
        from console_app import create_console_app
        app = create_console_app(graph=None, demo_mode=False)
        app.config["TESTING"] = True
        client = app.test_client()
        resp = client.get("/api/status")
        data = resp.get_json()
        self.assertFalse(data["demo_mode"])


# ===========================================================================
# Test: Demo Fixtures
# ===========================================================================

class TestDemoFixtures(unittest.TestCase):
    def test_seed_creates_data(self):
        from demo_fixtures import create_demo_session_factory
        _engine, SessionFactory = create_demo_session_factory()
        session = SessionFactory()
        self.assertTrue(session.query(Company).count() >= 3)
        self.assertTrue(session.query(Document).count() >= 5)
        self.assertTrue(session.query(Claim).count() >= 8)
        self.assertTrue(session.query(Thesis).count() >= 3)
        self.assertTrue(session.query(ThesisStateHistory).count() >= 4)
        self.assertTrue(session.query(PortfolioPosition).count() >= 2)
        self.assertTrue(session.query(PortfolioReview).count() >= 1)
        self.assertTrue(session.query(PortfolioDecision).count() >= 3)
        session.close()

    def test_demo_feed_non_empty(self):
        from demo_fixtures import create_demo_session_factory
        _engine, SessionFactory = create_demo_session_factory()
        session = SessionFactory()
        docs = get_recent_documents(session, limit=50)
        self.assertTrue(len(docs) >= 5)
        # Check that first doc has expected structure
        d = docs[0]
        self.assertIn("ticker", d)
        self.assertIn("title", d)
        self.assertIn("claim_count", d)
        self.assertTrue(d["claim_count"] > 0)
        session.close()

    def test_demo_subjects_non_empty(self):
        from demo_fixtures import create_demo_session_factory
        from console_api import get_demo_subjects
        _engine, SessionFactory = create_demo_session_factory()
        session = SessionFactory()
        subjects = get_demo_subjects(session)
        self.assertIsNotNone(subjects["latest_thesis_delta"])
        self.assertIsNotNone(subjects["latest_actionable"])
        self.assertIsNotNone(subjects["latest_thesis_trigger"])
        self.assertIsNotNone(subjects["latest_conviction_change"])
        session.close()

    def test_demo_what_changed_non_empty(self):
        from demo_fixtures import create_demo_session_factory
        from console_api import get_what_changed
        _engine, SessionFactory = create_demo_session_factory()
        session = SessionFactory()
        result = get_what_changed(session, 1)
        self.assertIsNotNone(result)
        self.assertTrue(len(result["new_information"]) >= 2)
        self.assertTrue(len(result["thesis_delta"]) >= 1)
        session.close()

    def test_demo_portfolio_non_empty(self):
        from demo_fixtures import create_demo_session_factory
        _engine, SessionFactory = create_demo_session_factory()
        session = SessionFactory()
        positions = get_portfolio_positions(session)
        self.assertTrue(len(positions) >= 2)
        review = get_latest_review(session)
        self.assertIsNotNone(review)
        self.assertTrue(len(review["decisions"]) >= 3)
        session.close()


# ===========================================================================
# Test: Health Endpoint
# ===========================================================================

class TestHealthEndpoint(unittest.TestCase):
    def setUp(self):
        import db as db_module
        self._orig_get_session = db_module.get_session

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)

        from contextlib import contextmanager
        @contextmanager
        def mock_get_session():
            session = Session()
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        db_module.get_session = mock_get_session

        session = Session()
        _seed_basic(session)
        session.commit()
        session.close()

        from console_app import create_console_app
        app = create_console_app(graph=None, demo_mode=False)
        app.config["TESTING"] = True
        self.client = app.test_client()

    def tearDown(self):
        import db as db_module
        db_module.get_session = self._orig_get_session

    def test_health_endpoint_exists(self):
        resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)

    def test_health_reports_mode(self):
        resp = self.client.get("/api/health")
        data = resp.get_json()
        self.assertEqual(data["mode"], "real")
        self.assertFalse(data["demo_fixtures_loaded"])

    def test_health_reports_counts(self):
        resp = self.client.get("/api/health")
        data = resp.get_json()
        self.assertIn("counts", data)
        self.assertEqual(data["counts"]["documents"], 1)
        self.assertEqual(data["counts"]["claims"], 2)
        self.assertEqual(data["counts"]["theses"], 1)

    def test_health_api_reachable(self):
        resp = self.client.get("/api/health")
        data = resp.get_json()
        self.assertTrue(data["api_reachable"])

    def test_health_has_started_at(self):
        resp = self.client.get("/api/health")
        data = resp.get_json()
        self.assertIn("started_at", data)
        self.assertTrue(len(data["started_at"]) > 0)


# ===========================================================================
# Test: Demo Mode End-to-End (via Flask)
# ===========================================================================

class TestDemoModeEndToEnd(unittest.TestCase):
    def setUp(self):
        import db as db_module
        self._orig_get_session = db_module.get_session

        from console_app import create_console_app
        app = create_console_app(graph=None, demo_mode=True)
        app.config["TESTING"] = True
        self.client = app.test_client()

    def tearDown(self):
        import db as db_module
        db_module.get_session = self._orig_get_session

    def test_demo_health_reports_demo_mode(self):
        resp = self.client.get("/api/health")
        data = resp.get_json()
        self.assertEqual(data["mode"], "demo")
        self.assertTrue(data["demo_fixtures_loaded"])

    def test_demo_feed_returns_data(self):
        resp = self.client.get("/api/documents/recent?limit=50")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(len(data) >= 5)

    def test_demo_status_has_counts(self):
        resp = self.client.get("/api/status")
        data = resp.get_json()
        self.assertTrue(data["demo_mode"])
        self.assertTrue(data["documents"] >= 5)
        self.assertTrue(data["claims"] >= 8)
        self.assertTrue(data["theses"] >= 3)

    def test_demo_subjects_has_data(self):
        resp = self.client.get("/api/demo/subjects")
        data = resp.get_json()
        self.assertIsNotNone(data["latest_thesis_delta"])
        self.assertIsNotNone(data["latest_actionable"])

    def test_demo_what_changed_has_data(self):
        resp = self.client.get("/api/documents/1/what-changed")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(len(data["new_information"]) >= 2)
        self.assertTrue(len(data["thesis_delta"]) >= 1)

    def test_demo_positions_non_empty(self):
        resp = self.client.get("/api/positions")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(len(data) >= 2)

    def test_demo_review_has_decisions(self):
        resp = self.client.get("/api/reviews/latest")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(len(data["decisions"]) >= 3)

    def test_demo_narrative_has_stages(self):
        resp = self.client.get("/api/documents/1/narrative")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        stages = [s["stage"] for s in data]
        self.assertIn("INGEST", stages)
        self.assertIn("CLAIMS", stages)


# ===========================================================================
# Test: Empty DB Diagnostic (real mode, no data)
# ===========================================================================

class TestEmptyDbDiagnostic(unittest.TestCase):
    def setUp(self):
        import db as db_module
        self._orig_get_session = db_module.get_session

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)

        from contextlib import contextmanager
        @contextmanager
        def mock_get_session():
            session = Session()
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        db_module.get_session = mock_get_session

        from console_app import create_console_app
        app = create_console_app(graph=None, demo_mode=False)
        app.config["TESTING"] = True
        self.client = app.test_client()

    def tearDown(self):
        import db as db_module
        db_module.get_session = self._orig_get_session

    def test_empty_feed_returns_empty_list(self):
        resp = self.client.get("/api/documents/recent")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data, [])

    def test_empty_health_shows_zero_counts(self):
        resp = self.client.get("/api/health")
        data = resp.get_json()
        self.assertEqual(data["mode"], "real")
        self.assertEqual(data["counts"]["documents"], 0)
        self.assertEqual(data["counts"]["claims"], 0)
        self.assertEqual(data["counts"]["theses"], 0)

    def test_empty_status_returns_zeros(self):
        resp = self.client.get("/api/status")
        data = resp.get_json()
        self.assertEqual(data["documents"], 0)
        self.assertFalse(data["demo_mode"])


if __name__ == "__main__":
    unittest.main()

