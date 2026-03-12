"""Tests for Step 10.5: graph-native memory layer and visual knowledge graph.

All tests are deterministic — no live network, no real DB required.
Uses in-memory SQLite for DB tests, direct graph construction for unit tests.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import (
    Base, Company, Document, Claim, Theme, Thesis, Checkpoint,
    ThesisStateHistory, PeerGroup, PortfolioPosition, Candidate,
    PortfolioReview, PortfolioDecision,
    ClaimCompanyLink, ClaimThemeLink, ThesisClaimLink, ThesisThemeLink,
    CompanyPeerGroupLink,
    SourceType, SourceTier, ClaimType, EconomicChannel, Direction,
    NoveltyType, ThesisState, ZoneState, PositionStatus, ActionType,
)
from graph_memory import ConsensusGraph, NodeType, EdgeType, node_id
from graph_sync import build_full_graph, build_ticker_graph, export_graph
from graph_queries import (
    claims_for_thesis, thesis_evolution, thesis_evolution_by_ticker,
    themes_for_company, companies_sharing_theme, cross_company_themes,
    checkpoint_evidence, why_own, thesis_evidence, documents_for_thesis,
    explain_state_transition, company_summary,
    format_why_own, format_thesis_evolution,
)
from graph_visualizer import (
    graph_to_vis_json, export_html, export_vis_json,
    company_view, thesis_view, theme_view, thesis_evolution_view,
)


# ---------------------------------------------------------------------------
# Fixtures: in-memory DB with toy dataset
# ---------------------------------------------------------------------------

@pytest.fixture
def db_session():
    """Create an in-memory SQLite DB with a toy dataset."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    # Companies
    session.add_all([
        Company(ticker="NVDA", name="NVIDIA Corp", sector="Technology", industry="Semiconductors"),
        Company(ticker="MSFT", name="Microsoft Corp", sector="Technology", industry="Software"),
        Company(ticker="AAPL", name="Apple Inc", sector="Technology", industry="Hardware"),
    ])
    session.flush()

    # Themes
    t1 = Theme(theme_name="AI Acceleration", theme_type="secular", description="GPU demand from AI")
    t2 = Theme(theme_name="Cloud Growth", theme_type="secular", description="Cloud infrastructure expansion")
    session.add_all([t1, t2])
    session.flush()

    # Peer group
    pg = PeerGroup(name="Large-Cap Semis", sector="Technology", region="US")
    session.add(pg)
    session.flush()

    # Documents
    doc1 = Document(
        source_type=SourceType.EARNINGS_TRANSCRIPT, source_tier=SourceTier.TIER_1,
        title="NVDA Q4 2025 Earnings Call", primary_company_ticker="NVDA",
        published_at=datetime(2025, 2, 15), ingested_at=datetime(2025, 2, 16),
    )
    doc2 = Document(
        source_type=SourceType.NEWS, source_tier=SourceTier.TIER_2,
        title="AI chip demand surges", primary_company_ticker="NVDA",
        published_at=datetime(2025, 3, 1), ingested_at=datetime(2025, 3, 1),
    )
    doc3 = Document(
        source_type=SourceType.EARNINGS_TRANSCRIPT, source_tier=SourceTier.TIER_1,
        title="MSFT Q3 2025 Earnings", primary_company_ticker="MSFT",
        published_at=datetime(2025, 1, 25), ingested_at=datetime(2025, 1, 26),
    )
    session.add_all([doc1, doc2, doc3])
    session.flush()

    # Claims
    c1 = Claim(
        document_id=doc1.id,
        claim_text_normalized="Data center revenue beat expectations by 15%",
        claim_text_short="DC revenue beat 15%",
        claim_type=ClaimType.DEMAND, economic_channel=EconomicChannel.REVENUE,
        direction=Direction.POSITIVE, strength=0.9, novelty_type=NoveltyType.NEW,
        published_at=datetime(2025, 2, 15),
    )
    c2 = Claim(
        document_id=doc1.id,
        claim_text_normalized="Gross margin compressed due to Blackwell ramp",
        claim_text_short="Margin compression from Blackwell",
        claim_type=ClaimType.MARGIN, economic_channel=EconomicChannel.GROSS_MARGIN,
        direction=Direction.NEGATIVE, strength=0.6, novelty_type=NoveltyType.NEW,
        published_at=datetime(2025, 2, 15),
    )
    c3 = Claim(
        document_id=doc2.id,
        claim_text_normalized="AI chip demand continues to accelerate",
        claim_text_short="AI chip demand accelerating",
        claim_type=ClaimType.DEMAND, economic_channel=EconomicChannel.REVENUE,
        direction=Direction.POSITIVE, strength=0.8, novelty_type=NoveltyType.CONFIRMING,
        published_at=datetime(2025, 3, 1),
    )
    c4 = Claim(
        document_id=doc3.id,
        claim_text_normalized="Azure revenue grew 30% YoY",
        claim_text_short="Azure +30% YoY",
        claim_type=ClaimType.DEMAND, economic_channel=EconomicChannel.REVENUE,
        direction=Direction.POSITIVE, strength=0.85, novelty_type=NoveltyType.CONFIRMING,
        published_at=datetime(2025, 1, 25),
    )
    session.add_all([c1, c2, c3, c4])
    session.flush()

    # Checkpoint
    cp = Checkpoint(
        checkpoint_type="earnings", name="NVDA Q1 2026 Earnings",
        date_expected=date(2025, 5, 20), importance=0.9,
        linked_company_ticker="NVDA",
    )
    session.add(cp)
    session.flush()

    # Theses
    th1 = Thesis(
        title="NVDA AI data center dominance", company_ticker="NVDA",
        state=ThesisState.STRENGTHENING, conviction_score=78.0,
        valuation_gap_pct=15.0, base_case_rerating=25.0,
        checkpoint_next_id=cp.id,
        created_at=datetime(2025, 1, 1), updated_at=datetime(2025, 3, 1),
    )
    th2 = Thesis(
        title="MSFT cloud + AI monetization", company_ticker="MSFT",
        state=ThesisState.STABLE, conviction_score=65.0,
        valuation_gap_pct=8.0, base_case_rerating=12.0,
        created_at=datetime(2025, 1, 1), updated_at=datetime(2025, 2, 1),
    )
    session.add_all([th1, th2])
    session.flush()

    # Thesis state history
    sh1 = ThesisStateHistory(
        thesis_id=th1.id, state=ThesisState.FORMING,
        conviction_score=55.0, note="Initial thesis formation",
        created_at=datetime(2025, 1, 1),
    )
    sh2 = ThesisStateHistory(
        thesis_id=th1.id, state=ThesisState.STABLE,
        conviction_score=65.0, note="Earnings confirmed base case",
        created_at=datetime(2025, 2, 1),
    )
    sh3 = ThesisStateHistory(
        thesis_id=th1.id, state=ThesisState.STRENGTHENING,
        conviction_score=78.0, note="Demand acceleration confirmed",
        created_at=datetime(2025, 3, 1),
    )
    sh4 = ThesisStateHistory(
        thesis_id=th2.id, state=ThesisState.FORMING,
        conviction_score=50.0, note="Cloud growth thesis started",
        created_at=datetime(2025, 1, 1),
    )
    sh5 = ThesisStateHistory(
        thesis_id=th2.id, state=ThesisState.STABLE,
        conviction_score=65.0, note="Azure results confirmed thesis",
        created_at=datetime(2025, 2, 1),
    )
    session.add_all([sh1, sh2, sh3, sh4, sh5])
    session.flush()

    # Portfolio position
    pos = PortfolioPosition(
        ticker="NVDA", thesis_id=th1.id, entry_date=date(2025, 1, 15),
        avg_cost=120.0, current_weight=5.0, target_weight=5.0,
        conviction_score=78.0, zone_state=ZoneState.BUY, status=PositionStatus.ACTIVE,
    )
    session.add(pos)
    session.flush()

    # Candidate
    cand = Candidate(
        ticker="MSFT", primary_thesis_id=th2.id,
        conviction_score=65.0, buyable_flag=True,
        watch_reason="Cloud growth thesis maturing",
        created_at=datetime(2025, 2, 1),
    )
    session.add(cand)
    session.flush()

    # Portfolio review + decisions
    rev = PortfolioReview(
        review_date=date(2025, 3, 1), review_type="weekly",
        holdings_reviewed=1, candidates_reviewed=1, turnover_pct=3.0,
        created_at=datetime(2025, 3, 1),
    )
    session.add(rev)
    session.flush()

    dec1 = PortfolioDecision(
        review_id=rev.id, ticker="NVDA", action=ActionType.HOLD,
        action_score=0.5, rationale="Maintain position",
        generated_at=datetime(2025, 3, 1),
    )
    dec2 = PortfolioDecision(
        review_id=rev.id, ticker="MSFT", action=ActionType.INITIATE,
        action_score=0.7, target_weight_change=3.0,
        rationale="Initiate on cloud thesis strength",
        generated_at=datetime(2025, 3, 1),
    )
    session.add_all([dec1, dec2])
    session.flush()

    # Link tables
    # Claim-company links
    session.add_all([
        ClaimCompanyLink(claim_id=c1.id, company_ticker="NVDA", relation_type="about"),
        ClaimCompanyLink(claim_id=c2.id, company_ticker="NVDA", relation_type="about"),
        ClaimCompanyLink(claim_id=c3.id, company_ticker="NVDA", relation_type="about"),
        ClaimCompanyLink(claim_id=c4.id, company_ticker="MSFT", relation_type="about"),
    ])

    # Claim-theme links
    session.add_all([
        ClaimThemeLink(claim_id=c1.id, theme_id=t1.id),
        ClaimThemeLink(claim_id=c3.id, theme_id=t1.id),
        ClaimThemeLink(claim_id=c4.id, theme_id=t2.id),
    ])

    # Thesis-claim links
    session.add_all([
        ThesisClaimLink(thesis_id=th1.id, claim_id=c1.id, link_type="supports"),
        ThesisClaimLink(thesis_id=th1.id, claim_id=c2.id, link_type="weakens"),
        ThesisClaimLink(thesis_id=th1.id, claim_id=c3.id, link_type="supports"),
        ThesisClaimLink(thesis_id=th2.id, claim_id=c4.id, link_type="supports"),
    ])

    # Thesis-theme links
    session.add_all([
        ThesisThemeLink(thesis_id=th1.id, theme_id=t1.id),
        ThesisThemeLink(thesis_id=th2.id, theme_id=t2.id),
    ])

    # Company-peer group link
    session.add(CompanyPeerGroupLink(company_ticker="NVDA", peer_group_id=pg.id, role="current"))
    session.flush()

    session.commit()

    # Store IDs for test access
    session._test_ids = {
        "nvda_thesis_id": th1.id,
        "msft_thesis_id": th2.id,
        "theme_ai_id": t1.id,
        "theme_cloud_id": t2.id,
        "checkpoint_id": cp.id,
        "claim_ids": [c1.id, c2.id, c3.id, c4.id],
        "doc_ids": [doc1.id, doc2.id, doc3.id],
        "position_id": pos.id,
        "candidate_id": cand.id,
        "peer_group_id": pg.id,
        "review_id": rev.id,
    }

    yield session
    session.close()


@pytest.fixture
def full_graph(db_session):
    """Build full graph from the toy dataset."""
    return build_full_graph(db_session)


# ---------------------------------------------------------------------------
# Test: Graph build from DB
# ---------------------------------------------------------------------------

class TestGraphBuild:
    """Test graph construction from relational objects."""

    def test_full_graph_has_nodes(self, full_graph):
        summary = full_graph.summary()
        assert summary["total_nodes"] > 0
        assert summary["total_edges"] > 0

    def test_company_nodes(self, full_graph):
        companies = full_graph.nodes_of_type(NodeType.COMPANY)
        assert len(companies) == 3
        assert node_id(NodeType.COMPANY, "NVDA") in companies

    def test_document_nodes(self, full_graph):
        docs = full_graph.nodes_of_type(NodeType.DOCUMENT)
        assert len(docs) == 3

    def test_claim_nodes(self, full_graph):
        claims = full_graph.nodes_of_type(NodeType.CLAIM)
        assert len(claims) == 4

    def test_thesis_nodes(self, full_graph):
        theses = full_graph.nodes_of_type(NodeType.THESIS)
        assert len(theses) == 2

    def test_theme_nodes(self, full_graph):
        themes = full_graph.nodes_of_type(NodeType.THEME)
        assert len(themes) == 2

    def test_state_history_nodes(self, full_graph):
        states = full_graph.nodes_of_type(NodeType.THESIS_STATE)
        assert len(states) == 5

    def test_checkpoint_node(self, full_graph):
        cps = full_graph.nodes_of_type(NodeType.CHECKPOINT)
        assert len(cps) == 1

    def test_position_node(self, full_graph):
        positions = full_graph.nodes_of_type(NodeType.PORTFOLIO_POSITION)
        assert len(positions) == 1

    def test_candidate_node(self, full_graph):
        candidates = full_graph.nodes_of_type(NodeType.CANDIDATE)
        assert len(candidates) == 1

    def test_peer_group_node(self, full_graph):
        pgs = full_graph.nodes_of_type(NodeType.PEER_GROUP)
        assert len(pgs) == 1

    def test_review_and_decision_nodes(self, full_graph):
        reviews = full_graph.nodes_of_type(NodeType.PORTFOLIO_REVIEW)
        decisions = full_graph.nodes_of_type(NodeType.PORTFOLIO_DECISION)
        assert len(reviews) == 1
        assert len(decisions) == 2


class TestEdgeCounts:
    """Test that edges are created from link tables and relationships."""

    def test_document_has_claim_edges(self, full_graph):
        edges = full_graph.edges_of_type(EdgeType.DOCUMENT_HAS_CLAIM)
        assert len(edges) == 4

    def test_claim_about_company_edges(self, full_graph):
        edges = full_graph.edges_of_type(EdgeType.CLAIM_ABOUT_COMPANY)
        assert len(edges) == 4

    def test_thesis_for_company_edges(self, full_graph):
        edges = full_graph.edges_of_type(EdgeType.THESIS_FOR_COMPANY)
        assert len(edges) == 2

    def test_thesis_has_state_edges(self, full_graph):
        edges = full_graph.edges_of_type(EdgeType.THESIS_HAS_STATE)
        assert len(edges) == 5

    def test_claim_linked_to_thesis_edges(self, full_graph):
        edges = full_graph.edges_of_type(EdgeType.CLAIM_LINKED_TO_THESIS)
        assert len(edges) == 4

    def test_thesis_linked_to_theme_edges(self, full_graph):
        edges = full_graph.edges_of_type(EdgeType.THESIS_LINKED_TO_THEME)
        assert len(edges) == 2

    def test_claim_supports_theme_edges(self, full_graph):
        edges = full_graph.edges_of_type(EdgeType.CLAIM_SUPPORTS_THEME)
        assert len(edges) == 3

    def test_position_edges(self, full_graph):
        pos_company = full_graph.edges_of_type(EdgeType.POSITION_FOR_COMPANY)
        pos_thesis = full_graph.edges_of_type(EdgeType.POSITION_LINKED_TO_THESIS)
        assert len(pos_company) == 1
        assert len(pos_thesis) == 1

    def test_company_peergroup_edge(self, full_graph):
        edges = full_graph.edges_of_type(EdgeType.COMPANY_IN_PEERGROUP)
        assert len(edges) == 1

    def test_thesis_has_checkpoint_edge(self, full_graph):
        edges = full_graph.edges_of_type(EdgeType.THESIS_HAS_CHECKPOINT)
        assert len(edges) == 1

    def test_review_decision_edges(self, full_graph):
        edges = full_graph.edges_of_type(EdgeType.REVIEW_HAS_DECISION)
        assert len(edges) == 2


# ---------------------------------------------------------------------------
# Test: Timestamps and provenance preserved
# ---------------------------------------------------------------------------

class TestProvenancePreserved:
    """Test that timestamps and provenance are preserved in graph export."""

    def test_thesis_node_has_timestamp(self, full_graph, db_session):
        tid = db_session._test_ids["nvda_thesis_id"]
        data = full_graph.get_node(NodeType.THESIS, tid)
        assert data is not None
        assert data["_ts"] is not None
        assert data["conviction_score"] == 78.0
        assert data["state"] == "strengthening"

    def test_claim_node_has_provenance(self, full_graph, db_session):
        cid = db_session._test_ids["claim_ids"][0]
        data = full_graph.get_node(NodeType.CLAIM, cid)
        assert data is not None
        assert data["claim_type"] == "demand"
        assert data["direction"] == "positive"
        assert data["strength"] == 0.9

    def test_state_history_has_timestamp(self, full_graph):
        states = full_graph.nodes_of_type(NodeType.THESIS_STATE)
        for sid in states:
            data = dict(full_graph.g.nodes[sid])
            assert data["_ts"] is not None
            assert data["state"] is not None

    def test_document_node_has_source_info(self, full_graph, db_session):
        did = db_session._test_ids["doc_ids"][0]
        data = full_graph.get_node(NodeType.DOCUMENT, did)
        assert data["source_type"] == "earnings_transcript"
        assert data["source_tier"] == "tier_1"

    def test_edge_preserves_link_type(self, full_graph):
        edges = full_graph.edges_of_type(EdgeType.CLAIM_LINKED_TO_THESIS)
        link_types = [e[2].get("link_type") for e in edges]
        assert "supports" in link_types
        assert "weakens" in link_types


# ---------------------------------------------------------------------------
# Test: Thesis evolution query
# ---------------------------------------------------------------------------

class TestThesisEvolution:
    """Test thesis evolution queries return correct ordered state history."""

    def test_evolution_returns_ordered(self, full_graph, db_session):
        tid = db_session._test_ids["nvda_thesis_id"]
        evo = thesis_evolution(full_graph, tid)
        assert len(evo) == 3
        # Check ordering
        states = [e["state"] for e in evo]
        assert states == ["forming", "stable", "strengthening"]

    def test_evolution_has_conviction_scores(self, full_graph, db_session):
        tid = db_session._test_ids["nvda_thesis_id"]
        evo = thesis_evolution(full_graph, tid)
        scores = [e["conviction_score"] for e in evo]
        assert scores == [55.0, 65.0, 78.0]

    def test_evolution_by_ticker(self, full_graph):
        result = thesis_evolution_by_ticker(full_graph, "NVDA")
        assert len(result) == 1
        thesis_id = list(result.keys())[0]
        assert len(result[thesis_id]) == 3

    def test_evolution_nonexistent(self, full_graph):
        evo = thesis_evolution(full_graph, 9999)
        assert evo == []


# ---------------------------------------------------------------------------
# Test: Company / theme / thesis linkage queries
# ---------------------------------------------------------------------------

class TestLinkageQueries:
    """Test graph traversal queries work correctly."""

    def test_themes_for_company(self, full_graph):
        themes = themes_for_company(full_graph, "NVDA")
        names = [t["theme_name"] for t in themes]
        assert "AI Acceleration" in names

    def test_claims_for_thesis(self, full_graph, db_session):
        tid = db_session._test_ids["nvda_thesis_id"]
        claims = claims_for_thesis(full_graph, tid)
        assert len(claims) == 3
        link_types = [c["link_type"] for c in claims]
        assert "supports" in link_types
        assert "weakens" in link_types

    def test_thesis_evidence(self, full_graph, db_session):
        tid = db_session._test_ids["nvda_thesis_id"]
        ev = thesis_evidence(full_graph, tid)
        assert ev["total_claims"] == 3
        assert len(ev["supporting_claims"]) == 2
        assert len(ev["weakening_claims"]) == 1

    def test_documents_for_thesis(self, full_graph, db_session):
        tid = db_session._test_ids["nvda_thesis_id"]
        docs = documents_for_thesis(full_graph, tid)
        assert len(docs) >= 1
        titles = [d["title"] for d in docs]
        assert any("NVDA" in t for t in titles)

    def test_company_summary(self, full_graph):
        result = company_summary(full_graph, "NVDA")
        assert result["ticker"] == "NVDA"
        assert result["documents"] == 2
        assert result["claims"] == 3
        assert result["theses"] == 1
        assert result["positions"] == 1

    def test_cross_company_no_shared_themes(self, full_graph):
        # NVDA → AI Acceleration, MSFT → Cloud Growth — no overlap
        shared = cross_company_themes(full_graph, "NVDA", "MSFT")
        assert len(shared) == 0


# ---------------------------------------------------------------------------
# Test: Why own / explainability
# ---------------------------------------------------------------------------

class TestExplainability:
    """Test explainability queries map to real graph objects."""

    def test_why_own_owned(self, full_graph):
        result = why_own(full_graph, "NVDA")
        assert result["is_owned"] is True
        assert len(result["positions"]) == 1
        assert len(result["theses"]) == 1

    def test_why_own_candidate(self, full_graph):
        result = why_own(full_graph, "MSFT")
        assert result["is_owned"] is False
        assert result["is_candidate"] is True

    def test_why_own_not_found(self, full_graph):
        result = why_own(full_graph, "ZZZZ")
        assert result["status"] == "not_found"

    def test_format_why_own(self, full_graph):
        result = why_own(full_graph, "NVDA")
        text = format_why_own(result)
        assert "NVDA" in text
        assert "OWNED" in text

    def test_state_transition(self, full_graph, db_session):
        tid = db_session._test_ids["nvda_thesis_id"]
        result = explain_state_transition(full_graph, tid, "forming", "strengthening")
        assert len(result["state_path"]) == 3
        assert result["state_path"][0]["state"] == "forming"
        assert result["state_path"][-1]["state"] == "strengthening"

    def test_format_thesis_evolution(self, full_graph, db_session):
        tid = db_session._test_ids["nvda_thesis_id"]
        evo = thesis_evolution(full_graph, tid)
        text = format_thesis_evolution(evo, tid)
        assert "forming" in text
        assert "strengthening" in text


# ---------------------------------------------------------------------------
# Test: Visualization export
# ---------------------------------------------------------------------------

class TestVisualization:
    """Test that visualization artifacts are produced."""

    def test_vis_json_structure(self, full_graph):
        data = graph_to_vis_json(full_graph)
        assert "nodes" in data
        assert "edges" in data
        assert len(data["nodes"]) > 0
        assert len(data["edges"]) > 0

    def test_vis_json_node_has_style(self, full_graph):
        data = graph_to_vis_json(full_graph)
        node = data["nodes"][0]
        assert "color" in node
        assert "shape" in node
        assert "label" in node

    def test_export_json_file(self, full_graph):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = export_vis_json(full_graph, os.path.join(tmpdir, "test.json"))
            assert os.path.exists(path)
            with open(path) as f:
                data = json.load(f)
            assert len(data["nodes"]) > 0

    def test_export_html_file(self, full_graph):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = export_html(full_graph, os.path.join(tmpdir, "test.html"))
            assert os.path.exists(path)
            with open(path, encoding="utf-8") as f:
                content = f.read()
            assert "vis-network" in content
            assert "nodesData" in content
            assert len(content) > 1000

    def test_html_contains_node_data(self, full_graph):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = export_html(full_graph, os.path.join(tmpdir, "test.html"))
            with open(path, encoding="utf-8") as f:
                content = f.read()
            # Should contain company tickers
            assert "NVDA" in content


# ---------------------------------------------------------------------------
# Test: Subgraph views
# ---------------------------------------------------------------------------

class TestSubgraphViews:
    """Test company/thesis/theme-centered subgraph extraction."""

    def test_company_view(self, full_graph):
        sub = company_view(full_graph, "NVDA", depth=2)
        assert sub.g.number_of_nodes() > 0
        assert sub.has_node(NodeType.COMPANY, "NVDA")

    def test_company_view_includes_thesis(self, full_graph):
        sub = company_view(full_graph, "NVDA", depth=2)
        theses = sub.nodes_of_type(NodeType.THESIS)
        assert len(theses) >= 1

    def test_thesis_view(self, full_graph, db_session):
        tid = db_session._test_ids["nvda_thesis_id"]
        sub = thesis_view(full_graph, tid, depth=2)
        assert sub.has_node(NodeType.THESIS, tid)
        assert sub.g.number_of_nodes() > 1

    def test_thesis_evolution_view(self, full_graph, db_session):
        tid = db_session._test_ids["nvda_thesis_id"]
        sub = thesis_evolution_view(full_graph, tid)
        states = sub.nodes_of_type(NodeType.THESIS_STATE)
        assert len(states) == 3

    def test_theme_view(self, full_graph, db_session):
        theme_id = db_session._test_ids["theme_ai_id"]
        sub = theme_view(full_graph, theme_id, depth=2)
        assert sub.has_node(NodeType.THEME, theme_id)

    def test_nonexistent_company_view(self, full_graph):
        sub = company_view(full_graph, "ZZZZ")
        assert sub.g.number_of_nodes() == 0


# ---------------------------------------------------------------------------
# Test: Serialization roundtrip
# ---------------------------------------------------------------------------

class TestSerialization:
    """Test JSON serialization and deserialization."""

    def test_to_dict_roundtrip(self, full_graph):
        d = full_graph.to_dict()
        assert "nodes" in d
        assert "edges" in d
        assert "summary" in d

        restored = ConsensusGraph.from_dict(d)
        assert restored.g.number_of_nodes() == full_graph.g.number_of_nodes()
        assert restored.g.number_of_edges() == full_graph.g.number_of_edges()

    def test_to_json_roundtrip(self, full_graph):
        raw = full_graph.to_json()
        restored = ConsensusGraph.from_json(raw)
        assert restored.g.number_of_nodes() == full_graph.g.number_of_nodes()

    def test_export_graph_file(self, full_graph):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = export_graph(full_graph, tmpdir, "test")
            assert os.path.exists(path)
            with open(path) as f:
                data = json.load(f)
            assert data["summary"]["total_nodes"] == full_graph.g.number_of_nodes()


# ---------------------------------------------------------------------------
# Test: Ticker-scoped graph build
# ---------------------------------------------------------------------------

class TestTickerGraph:
    """Test building a graph scoped to a single ticker."""

    def test_ticker_graph_has_company(self, db_session):
        cg = build_ticker_graph(db_session, "NVDA")
        assert cg.has_node(NodeType.COMPANY, "NVDA")

    def test_ticker_graph_has_thesis(self, db_session):
        cg = build_ticker_graph(db_session, "NVDA")
        theses = cg.nodes_of_type(NodeType.THESIS)
        assert len(theses) == 1

    def test_ticker_graph_has_claims(self, db_session):
        cg = build_ticker_graph(db_session, "NVDA")
        claims = cg.nodes_of_type(NodeType.CLAIM)
        assert len(claims) >= 3

    def test_ticker_graph_has_state_history(self, db_session):
        cg = build_ticker_graph(db_session, "NVDA")
        states = cg.nodes_of_type(NodeType.THESIS_STATE)
        assert len(states) == 3

    def test_nonexistent_ticker(self, db_session):
        cg = build_ticker_graph(db_session, "ZZZZ")
        assert cg.g.number_of_nodes() == 0


# ---------------------------------------------------------------------------
# Test: Graph memory unit tests
# ---------------------------------------------------------------------------

class TestConsensusGraphUnit:
    """Unit tests for ConsensusGraph operations."""

    def test_add_node(self):
        cg = ConsensusGraph()
        nid = cg.add_node(NodeType.COMPANY, "TEST", name="Test Corp")
        assert nid == "Company:TEST"
        assert cg.has_node(NodeType.COMPANY, "TEST")

    def test_add_edge(self):
        cg = ConsensusGraph()
        cg.add_node(NodeType.COMPANY, "A")
        cg.add_node(NodeType.THESIS, 1)
        cg.add_edge(
            node_id(NodeType.THESIS, 1),
            node_id(NodeType.COMPANY, "A"),
            EdgeType.THESIS_FOR_COMPANY,
        )
        assert cg.g.number_of_edges() == 1

    def test_nodes_of_type(self):
        cg = ConsensusGraph()
        cg.add_node(NodeType.COMPANY, "A")
        cg.add_node(NodeType.COMPANY, "B")
        cg.add_node(NodeType.THEME, 1)
        assert len(cg.nodes_of_type(NodeType.COMPANY)) == 2
        assert len(cg.nodes_of_type(NodeType.THEME)) == 1

    def test_successors_filtered(self):
        cg = ConsensusGraph()
        cg.add_node(NodeType.THESIS, 1)
        cg.add_node(NodeType.COMPANY, "A")
        cg.add_node(NodeType.THESIS_STATE, 10)
        tid = node_id(NodeType.THESIS, 1)
        cg.add_edge(tid, node_id(NodeType.COMPANY, "A"), EdgeType.THESIS_FOR_COMPANY)
        cg.add_edge(tid, node_id(NodeType.THESIS_STATE, 10), EdgeType.THESIS_HAS_STATE)
        assert len(cg.successors(tid, EdgeType.THESIS_FOR_COMPANY)) == 1
        assert len(cg.successors(tid, EdgeType.THESIS_HAS_STATE)) == 1
        assert len(cg.successors(tid)) == 2

    def test_summary(self):
        cg = ConsensusGraph()
        cg.add_node(NodeType.COMPANY, "A")
        cg.add_node(NodeType.THESIS, 1)
        cg.add_edge(
            node_id(NodeType.THESIS, 1),
            node_id(NodeType.COMPANY, "A"),
            EdgeType.THESIS_FOR_COMPANY,
        )
        s = cg.summary()
        assert s["total_nodes"] == 2
        assert s["total_edges"] == 1
        assert s["node_types"]["Company"] == 1
