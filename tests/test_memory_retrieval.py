"""Tests for the temporal memory retrieval module."""
from __future__ import annotations

import sys
import os
from datetime import datetime, date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import (
    Base, Company, Document, Claim, Thesis, Theme,
    ThesisClaimLink, ThesisThemeLink, ClaimCompanyLink, ClaimThemeLink,
    ThesisStateHistory, Checkpoint,
    SourceType, SourceTier, ClaimType, EconomicChannel,
    Direction, NoveltyType, ThesisState,
)
from memory_retrieval import (
    retrieve_memory, MemorySnapshot, MemoryClaim,
    DEFAULT_THESIS_CLAIMS_LIMIT, DEFAULT_COMPANY_CLAIMS_LIMIT,
    DEFAULT_THEME_CLAIMS_LIMIT, DEFAULT_HISTORY_LIMIT,
    DEFAULT_CHECKPOINT_LIMIT,
)


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


def _make_company(session, ticker="NVDA", name="NVIDIA Corp."):
    c = Company(ticker=ticker, name=name)
    session.add(c)
    session.flush()
    return c


def _make_document(session, ticker="NVDA", source_type=SourceType.NEWS, tier=SourceTier.TIER_1):
    doc = Document(
        source_type=source_type,
        source_tier=tier,
        primary_company_ticker=ticker,
        title=f"Test doc for {ticker}",
        raw_text="test content",
        published_at=datetime.utcnow(),
    )
    session.add(doc)
    session.flush()
    return doc


def _make_claim(
    session,
    doc_id,
    text_short="Test claim",
    direction=Direction.POSITIVE,
    claim_type=ClaimType.DEMAND,
    novelty=NoveltyType.NEW,
    strength=0.8,
    published_at=None,
):
    c = Claim(
        document_id=doc_id,
        claim_text_normalized=f"Full text: {text_short}",
        claim_text_short=text_short,
        claim_type=claim_type,
        economic_channel=EconomicChannel.REVENUE,
        direction=direction,
        strength=strength,
        novelty_type=novelty,
        confidence=0.9,
        published_at=published_at or datetime.utcnow(),
    )
    session.add(c)
    session.flush()
    return c


def _make_thesis(session, ticker="NVDA", title="NVDA AI demand thesis", score=60.0):
    t = Thesis(
        title=title,
        company_ticker=ticker,
        summary="Long NVDA on AI infrastructure demand",
        state=ThesisState.STRENGTHENING,
        conviction_score=score,
    )
    session.add(t)
    session.flush()
    return t


def _make_theme(session, name="AI Infrastructure Spend"):
    t = Theme(theme_name=name)
    session.add(t)
    session.flush()
    return t


# ---------------------------------------------------------------------------
# Basic retrieval tests
# ---------------------------------------------------------------------------

class TestMemoryRetrieval:
    def test_empty_memory(self, session):
        """Thesis with no prior claims returns empty snapshot."""
        _make_company(session)
        thesis = _make_thesis(session)
        session.flush()

        snap = retrieve_memory(session, thesis.id)
        assert snap.thesis_id == thesis.id
        assert snap.total_prior_claims == 0
        assert len(snap.state_history) == 0
        assert len(snap.checkpoints) == 0

    def test_thesis_not_found(self, session):
        with pytest.raises(ValueError, match="Thesis 999 not found"):
            retrieve_memory(session, 999)

    def test_thesis_linked_claims_retrieved(self, session):
        """Claims linked via thesis_claim_links are returned as thesis_claims."""
        _make_company(session)
        doc = _make_document(session)
        thesis = _make_thesis(session)
        c1 = _make_claim(session, doc.id, "AI demand surge")
        c2 = _make_claim(session, doc.id, "GPU supply tight")

        # Link both claims to thesis
        session.add(ThesisClaimLink(thesis_id=thesis.id, claim_id=c1.id, link_type="supports"))
        session.add(ThesisClaimLink(thesis_id=thesis.id, claim_id=c2.id, link_type="weakens"))
        session.flush()

        snap = retrieve_memory(session, thesis.id)
        assert len(snap.thesis_claims) == 2
        assert all(mc.retrieval_source == "thesis_linked" for mc in snap.thesis_claims)
        # Check link types are preserved
        link_types = {mc.thesis_link_type for mc in snap.thesis_claims}
        assert "supports" in link_types
        assert "weakens" in link_types

    def test_company_claims_exclude_thesis_linked(self, session):
        """Company claims don't duplicate thesis-linked claims."""
        _make_company(session)
        doc = _make_document(session)
        thesis = _make_thesis(session)

        c_thesis = _make_claim(session, doc.id, "Thesis-linked claim")
        c_company = _make_claim(session, doc.id, "Company-only claim")

        # Link c_thesis to thesis, both to company
        session.add(ThesisClaimLink(thesis_id=thesis.id, claim_id=c_thesis.id, link_type="supports"))
        session.add(ClaimCompanyLink(claim_id=c_thesis.id, company_ticker="NVDA", relation_type="about"))
        session.add(ClaimCompanyLink(claim_id=c_company.id, company_ticker="NVDA", relation_type="about"))
        session.flush()

        snap = retrieve_memory(session, thesis.id)
        assert len(snap.thesis_claims) == 1
        assert snap.thesis_claims[0].claim_text_short == "Thesis-linked claim"
        assert len(snap.company_claims) == 1
        assert snap.company_claims[0].claim_text_short == "Company-only claim"

    def test_theme_claims_retrieved(self, session):
        """Claims sharing a theme with the thesis are returned."""
        _make_company(session)
        _make_company(session, "AMD", "AMD Inc.")
        doc_nvda = _make_document(session, "NVDA")
        doc_amd = _make_document(session, "AMD")
        thesis = _make_thesis(session)
        theme = _make_theme(session, "AI Infrastructure Spend")

        # Link thesis to theme
        session.add(ThesisThemeLink(thesis_id=thesis.id, theme_id=theme.id))

        # Create a claim for AMD linked to the same theme
        c_amd = _make_claim(session, doc_amd.id, "AMD AI chip ramp")
        session.add(ClaimThemeLink(claim_id=c_amd.id, theme_id=theme.id))
        session.flush()

        snap = retrieve_memory(session, thesis.id)
        assert len(snap.theme_claims) == 1
        assert snap.theme_claims[0].claim_text_short == "AMD AI chip ramp"
        assert snap.theme_claims[0].retrieval_source == "theme"

    def test_theme_claims_exclude_already_fetched(self, session):
        """Theme claims that are already thesis-linked or company-linked are excluded."""
        _make_company(session)
        doc = _make_document(session)
        thesis = _make_thesis(session)
        theme = _make_theme(session)

        c1 = _make_claim(session, doc.id, "Already thesis-linked")
        c2 = _make_claim(session, doc.id, "Theme-only claim")

        session.add(ThesisClaimLink(thesis_id=thesis.id, claim_id=c1.id, link_type="supports"))
        session.add(ThesisThemeLink(thesis_id=thesis.id, theme_id=theme.id))
        session.add(ClaimThemeLink(claim_id=c1.id, theme_id=theme.id))
        session.add(ClaimThemeLink(claim_id=c2.id, theme_id=theme.id))
        session.flush()

        snap = retrieve_memory(session, thesis.id)
        assert len(snap.thesis_claims) == 1
        # c1 should NOT appear in theme_claims since it's already thesis-linked
        theme_ids = {mc.claim_id for mc in snap.theme_claims}
        assert c1.id not in theme_ids
        assert c2.id in theme_ids

    def test_state_history_retrieved(self, session):
        """Recent thesis state history rows are retrieved."""
        _make_company(session)
        thesis = _make_thesis(session)

        for i in range(7):
            session.add(ThesisStateHistory(
                thesis_id=thesis.id,
                state=ThesisState.STRENGTHENING,
                conviction_score=50.0 + i,
                note=f"Update {i}",
                created_at=datetime.utcnow() - timedelta(days=7 - i),
            ))
        session.flush()

        snap = retrieve_memory(session, thesis.id, history_limit=5)
        assert len(snap.state_history) == 5
        # Most recent first
        assert snap.state_history[0].conviction_score > snap.state_history[-1].conviction_score

    def test_checkpoints_retrieved(self, session):
        """Upcoming checkpoints for the company are retrieved."""
        _make_company(session)
        thesis = _make_thesis(session)

        session.add(Checkpoint(
            checkpoint_type="earnings",
            name="NVDA Q4 2025 earnings",
            date_expected=date.today() + timedelta(days=30),
            importance=0.9,
            linked_company_ticker="NVDA",
        ))
        session.add(Checkpoint(
            checkpoint_type="product_launch",
            name="NVDA Blackwell Ultra",
            date_expected=date.today() + timedelta(days=90),
            importance=0.7,
            linked_company_ticker="NVDA",
        ))
        session.flush()

        snap = retrieve_memory(session, thesis.id)
        assert len(snap.checkpoints) == 2
        assert snap.checkpoints[0].name == "NVDA Q4 2025 earnings"  # nearest first


# ---------------------------------------------------------------------------
# Retrieval limits and ordering
# ---------------------------------------------------------------------------

class TestRetrievalLimits:
    def test_thesis_claims_limited(self, session):
        """Only top N thesis claims returned."""
        _make_company(session)
        doc = _make_document(session)
        thesis = _make_thesis(session)

        for i in range(15):
            c = _make_claim(
                session, doc.id, f"Claim {i}",
                published_at=datetime.utcnow() - timedelta(hours=i),
            )
            session.add(ThesisClaimLink(thesis_id=thesis.id, claim_id=c.id, link_type="supports"))
        session.flush()

        snap = retrieve_memory(session, thesis.id, thesis_claims_limit=5)
        assert len(snap.thesis_claims) == 5

    def test_exclude_claim_ids(self, session):
        """New claims being assessed are excluded from memory."""
        _make_company(session)
        doc = _make_document(session)
        thesis = _make_thesis(session)

        c1 = _make_claim(session, doc.id, "Old claim")
        c2 = _make_claim(session, doc.id, "New claim being assessed")
        session.add(ThesisClaimLink(thesis_id=thesis.id, claim_id=c1.id, link_type="supports"))
        session.add(ThesisClaimLink(thesis_id=thesis.id, claim_id=c2.id, link_type="supports"))
        session.flush()

        snap = retrieve_memory(session, thesis.id, exclude_claim_ids=[c2.id])
        assert len(snap.thesis_claims) == 1
        assert snap.thesis_claims[0].claim_id == c1.id


# ---------------------------------------------------------------------------
# Retrieval priority: thesis > company > theme
# ---------------------------------------------------------------------------

class TestRetrievalPriority:
    def test_thesis_claims_prioritized_over_company(self, session):
        """Thesis-linked claims appear in thesis_claims, not company_claims."""
        _make_company(session)
        doc = _make_document(session)
        thesis = _make_thesis(session)

        c1 = _make_claim(session, doc.id, "Thesis claim")
        c2 = _make_claim(session, doc.id, "Company claim")

        session.add(ThesisClaimLink(thesis_id=thesis.id, claim_id=c1.id, link_type="supports"))
        session.add(ClaimCompanyLink(claim_id=c1.id, company_ticker="NVDA", relation_type="about"))
        session.add(ClaimCompanyLink(claim_id=c2.id, company_ticker="NVDA", relation_type="about"))
        session.flush()

        snap = retrieve_memory(session, thesis.id)
        thesis_ids = {mc.claim_id for mc in snap.thesis_claims}
        company_ids = {mc.claim_id for mc in snap.company_claims}
        assert c1.id in thesis_ids
        assert c1.id not in company_ids
        assert c2.id in company_ids

    def test_irrelevant_claims_excluded(self, session):
        """Claims for a different company/theme don't appear."""
        _make_company(session, "NVDA", "NVIDIA")
        _make_company(session, "AAPL", "Apple")
        doc_aapl = _make_document(session, "AAPL")
        thesis = _make_thesis(session, "NVDA")

        c_aapl = _make_claim(session, doc_aapl.id, "Apple revenue up")
        session.add(ClaimCompanyLink(claim_id=c_aapl.id, company_ticker="AAPL", relation_type="about"))
        session.flush()

        snap = retrieve_memory(session, thesis.id)
        assert snap.total_prior_claims == 0


# ---------------------------------------------------------------------------
# Snapshot formatting
# ---------------------------------------------------------------------------

class TestSnapshotFormatting:
    def test_to_prompt_text_empty(self, session):
        """Empty snapshot produces the default message."""
        _make_company(session)
        thesis = _make_thesis(session)
        session.flush()

        snap = retrieve_memory(session, thesis.id)
        text = snap.to_prompt_text()
        assert "No prior memory" in text

    def test_to_prompt_text_with_data(self, session):
        """Populated snapshot produces structured text."""
        _make_company(session)
        doc = _make_document(session)
        thesis = _make_thesis(session)

        c1 = _make_claim(session, doc.id, "AI demand strong")
        session.add(ThesisClaimLink(thesis_id=thesis.id, claim_id=c1.id, link_type="supports"))
        session.add(ThesisStateHistory(
            thesis_id=thesis.id,
            state=ThesisState.STRENGTHENING,
            conviction_score=60.0,
            note="Initial assessment",
        ))
        session.add(Checkpoint(
            checkpoint_type="earnings",
            name="Q4 earnings",
            date_expected=date.today() + timedelta(days=30),
            importance=0.9,
            linked_company_ticker="NVDA",
        ))
        session.flush()

        snap = retrieve_memory(session, thesis.id)
        text = snap.to_prompt_text()
        assert "Recent thesis state history" in text
        assert "Prior claims linked to this thesis" in text
        assert "AI demand strong" in text
        assert "Upcoming checkpoints" in text
        assert "Q4 earnings" in text

    def test_deterministic_output(self, session):
        """Two calls with same data produce identical snapshots."""
        _make_company(session)
        doc = _make_document(session)
        thesis = _make_thesis(session)

        c1 = _make_claim(session, doc.id, "Claim A", published_at=datetime(2025, 1, 1))
        c2 = _make_claim(session, doc.id, "Claim B", published_at=datetime(2025, 1, 2))
        session.add(ThesisClaimLink(thesis_id=thesis.id, claim_id=c1.id, link_type="supports"))
        session.add(ThesisClaimLink(thesis_id=thesis.id, claim_id=c2.id, link_type="weakens"))
        session.flush()

        snap1 = retrieve_memory(session, thesis.id)
        snap2 = retrieve_memory(session, thesis.id)
        assert snap1.to_prompt_text() == snap2.to_prompt_text()


# ---------------------------------------------------------------------------
# Integration: thesis update still works with memory
# ---------------------------------------------------------------------------

class TestThesisUpdateWithMemory:
    def test_update_with_memory_stub_mode(self, session):
        """update_thesis_from_claims works with memory retrieval in stub mode."""
        from thesis_update_service import update_thesis_from_claims

        _make_company(session)
        doc = _make_document(session)
        thesis = _make_thesis(session, score=50.0)

        # Create a prior claim linked to thesis (memory)
        c_old = _make_claim(session, doc.id, "NVDA AI infrastructure demand accelerating")
        session.add(ThesisClaimLink(thesis_id=thesis.id, claim_id=c_old.id, link_type="supports"))
        session.flush()

        # Create new claim that shares domain terms with thesis ("infrastructure")
        c_new = _make_claim(session, doc.id, "NVDA AI infrastructure revenue beat", direction=Direction.POSITIVE)
        session.flush()

        result = update_thesis_from_claims(
            session, thesis.id, [c_new.id], use_llm=False,
        )
        assert result["after_score"] > result["before_score"]
        assert "thesis_id" in result

    def test_update_no_prior_memory(self, session):
        """update_thesis_from_claims works when there's no prior memory."""
        from thesis_update_service import update_thesis_from_claims

        _make_company(session)
        doc = _make_document(session)
        thesis = _make_thesis(session, score=50.0)
        c = _make_claim(session, doc.id, "NVDA AI infrastructure demand strong", direction=Direction.POSITIVE)
        session.flush()

        result = update_thesis_from_claims(
            session, thesis.id, [c.id], use_llm=False,
        )
        assert result["after_score"] > result["before_score"]
