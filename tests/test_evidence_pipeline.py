"""Tests for Step 13.1: canonical evidence pipeline hardening.

Proves that:
  1. Event cluster IDs are assigned/persisted at ingestion time
  2. Thesis update consumes persisted cluster state (not silent recomputation)
  3. Contradiction metadata is detected and persisted at ingestion time
  4. Contradiction metadata flows into evidence scoring path
  5. EvidenceAssessment records are persisted for downstream reuse
  6. Fallback recomputation is explicit and visible
  7. Memory retrieval remains deterministic after these changes
"""
from __future__ import annotations

import sys
import os
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import (
    Base, Company, Document, Claim, Thesis, Theme,
    ThesisClaimLink, ClaimCompanyLink, ClaimThemeLink,
    ThesisStateHistory, EvidenceAssessment,
    SourceType, SourceTier, ClaimType, EconomicChannel,
    Direction, NoveltyType, ThesisState,
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_company(session, ticker="NVDA", name="NVIDIA Corp."):
    c = Company(ticker=ticker, name=name)
    session.add(c)
    session.flush()
    return c


def _make_document(session, ticker="NVDA", tier=SourceTier.TIER_1,
                   published_at=None, source_type=SourceType.NEWS):
    doc = Document(
        source_type=source_type,
        source_tier=tier,
        primary_company_ticker=ticker,
        title=f"Test doc for {ticker}",
        raw_text="test content",
        published_at=published_at or datetime.utcnow(),
    )
    session.add(doc)
    session.flush()
    return doc


def _make_claim(session, doc_id, text_norm="Test claim text",
                direction=Direction.POSITIVE, claim_type=ClaimType.DEMAND,
                novelty=NoveltyType.NEW, strength=0.8, confidence=0.9,
                published_at=None, source_excerpt=None,
                event_cluster_id=None, is_contradicted=False,
                contradicts_claim_id=None):
    c = Claim(
        document_id=doc_id,
        claim_text_normalized=text_norm,
        claim_text_short=text_norm[:60],
        claim_type=claim_type,
        economic_channel=EconomicChannel.REVENUE,
        direction=direction,
        strength=strength,
        novelty_type=novelty,
        confidence=confidence,
        published_at=published_at or datetime.utcnow(),
        source_excerpt=source_excerpt,
        event_cluster_id=event_cluster_id,
        is_contradicted=is_contradicted,
        contradicts_claim_id=contradicts_claim_id,
    )
    session.add(c)
    session.flush()
    return c


def _make_thesis(session, ticker="NVDA", title="NVDA AI demand thesis", score=50.0):
    t = Thesis(
        title=title,
        company_ticker=ticker,
        summary="Long NVDA on AI infrastructure demand",
        state=ThesisState.FORMING,
        conviction_score=score,
    )
    session.add(t)
    session.flush()
    return t


# ===========================================================================
# 1. Event Cluster Assignment at Ingestion Time
# ===========================================================================

class TestIngestionEventClustering:
    """Event clusters should be assigned at ingestion, not only at thesis update."""

    def test_similar_claims_get_same_cluster_at_ingestion(self, session):
        """Claims about the same event get clustered during ingestion."""
        _make_company(session)
        now = datetime.utcnow()
        doc = _make_document(session, published_at=now)

        # Create two nearly identical claims (simulating duplicate articles)
        c1 = _make_claim(session, doc.id,
                         text_norm="NVIDIA reports record Q4 revenue of $22.1 billion",
                         published_at=now)
        session.add(ClaimCompanyLink(claim_id=c1.id, company_ticker="NVDA", relation_type="about"))

        c2 = _make_claim(session, doc.id,
                         text_norm="NVIDIA announces record Q4 revenue of $22.1 billion beating estimates",
                         published_at=now + timedelta(hours=1))
        session.add(ClaimCompanyLink(claim_id=c2.id, company_ticker="NVDA", relation_type="about"))
        session.flush()

        # Run ingestion-time clustering
        from document_ingestion_service import _assign_ingestion_event_clusters
        _assign_ingestion_event_clusters(session, [c1.id, c2.id], "NVDA")
        session.flush()

        # Both claims should have event_cluster_id set
        c1_fresh = session.get(Claim, c1.id)
        c2_fresh = session.get(Claim, c2.id)
        assert c1_fresh.event_cluster_id is not None
        assert c2_fresh.event_cluster_id is not None
        # They should share the same cluster
        assert c1_fresh.event_cluster_id == c2_fresh.event_cluster_id

    def test_dissimilar_claims_get_different_clusters(self, session):
        """Unrelated claims get separate clusters."""
        _make_company(session)
        now = datetime.utcnow()
        doc = _make_document(session, published_at=now)

        c1 = _make_claim(session, doc.id,
                         text_norm="NVIDIA reports record Q4 revenue of $22.1 billion",
                         published_at=now)
        session.add(ClaimCompanyLink(claim_id=c1.id, company_ticker="NVDA", relation_type="about"))

        c2 = _make_claim(session, doc.id,
                         text_norm="NVIDIA announces new gaming GPU architecture",
                         published_at=now + timedelta(hours=1))
        session.add(ClaimCompanyLink(claim_id=c2.id, company_ticker="NVDA", relation_type="about"))
        session.flush()

        from document_ingestion_service import _assign_ingestion_event_clusters
        _assign_ingestion_event_clusters(session, [c1.id, c2.id], "NVDA")
        session.flush()

        c1_fresh = session.get(Claim, c1.id)
        c2_fresh = session.get(Claim, c2.id)
        assert c1_fresh.event_cluster_id is not None
        assert c2_fresh.event_cluster_id is not None
        # Different events = different clusters
        assert c1_fresh.event_cluster_id != c2_fresh.event_cluster_id

    def test_cluster_id_persisted_on_claim(self, session):
        """event_cluster_id should be a persisted field, not transient."""
        _make_company(session)
        doc = _make_document(session)
        c = _make_claim(session, doc.id, event_cluster_id="evt_42")
        session.flush()

        # Re-fetch from DB
        c_fresh = session.get(Claim, c.id)
        assert c_fresh.event_cluster_id == "evt_42"


# ===========================================================================
# 2. Thesis Update Consumes Persisted Cluster State
# ===========================================================================

class TestThesisUpdateConsumesPersistedClusters:
    """Thesis update should use persisted event_cluster_id, not recompute from scratch."""

    def test_thesis_update_uses_persisted_cluster_id(self, session):
        """Claims with pre-assigned cluster IDs should not trigger fallback clustering."""
        _make_company(session)
        now = datetime.utcnow()
        doc = _make_document(session, published_at=now)
        thesis = _make_thesis(session)

        # Create claims with pre-assigned cluster IDs (as if set at ingestion)
        c1 = _make_claim(session, doc.id,
                         text_norm="NVIDIA strong AI chip demand for data centers",
                         published_at=now, event_cluster_id="evt_100")
        c2 = _make_claim(session, doc.id,
                         text_norm="NVIDIA strong AI chip demand from cloud providers",
                         published_at=now, event_cluster_id="evt_100")
        session.add(ClaimCompanyLink(claim_id=c1.id, company_ticker="NVDA", relation_type="about"))
        session.add(ClaimCompanyLink(claim_id=c2.id, company_ticker="NVDA", relation_type="about"))
        session.flush()

        from thesis_update_service import update_thesis_from_claims
        result = update_thesis_from_claims(
            session, thesis.id, [c1.id, c2.id], use_llm=False,
        )

        # Assessments should show cluster positions derived from persisted state
        assessments = result["assessments"]
        assert len(assessments) == 2
        # Both should have the fallback flag as False since they had persisted cluster IDs
        for a in assessments:
            assert a["used_fallback_clustering"] is False

    def test_fallback_clustering_is_explicit(self, session):
        """Claims WITHOUT cluster IDs should trigger explicit fallback."""
        _make_company(session)
        now = datetime.utcnow()
        doc = _make_document(session, published_at=now)
        thesis = _make_thesis(session)

        # Claims without event_cluster_id (legacy data)
        c1 = _make_claim(session, doc.id,
                         text_norm="NVIDIA strong AI chip demand for data centers",
                         published_at=now)
        session.add(ClaimCompanyLink(claim_id=c1.id, company_ticker="NVDA", relation_type="about"))
        session.flush()

        from thesis_update_service import update_thesis_from_claims
        result = update_thesis_from_claims(
            session, thesis.id, [c1.id], use_llm=False,
        )

        # Assessment should show fallback clustering was used
        assessments = result["assessments"]
        assert len(assessments) == 1
        assert assessments[0]["used_fallback_clustering"] is True


# ===========================================================================
# 3. Contradiction Detection at Ingestion Time
# ===========================================================================

class TestContradictionDetection:
    """Contradiction metadata should be detected and persisted at ingestion."""

    def test_conflicting_claim_gets_contradiction_metadata(self, session):
        """A claim with opposite direction to a similar prior claim should be flagged."""
        _make_company(session)
        now = datetime.utcnow()
        doc1 = _make_document(session, published_at=now - timedelta(days=1))
        doc2 = _make_document(session, published_at=now)

        # Prior claim: positive demand
        prior = _make_claim(session, doc1.id,
                            text_norm="NVIDIA GPU demand for data center chips is strong and accelerating rapidly",
                            direction=Direction.POSITIVE,
                            published_at=now - timedelta(days=1))
        session.add(ClaimCompanyLink(claim_id=prior.id, company_ticker="NVDA", relation_type="about"))
        session.flush()

        # New claim: negative demand on similar topic (different enough to avoid REPETITIVE)
        new_claim = Claim(
            document_id=doc2.id,
            claim_text_normalized="NVIDIA GPU demand for data center chips is weakening and showing signs of slowdown",
            claim_text_short="GPU demand weakening",
            claim_type=ClaimType.DEMAND,
            economic_channel=EconomicChannel.REVENUE,
            direction=Direction.NEGATIVE,
            strength=0.8,
            novelty_type=NoveltyType.NEW,
            confidence=0.9,
            published_at=now,
        )
        session.add(new_claim)
        session.flush()
        session.add(ClaimCompanyLink(claim_id=new_claim.id, company_ticker="NVDA", relation_type="about"))
        session.flush()

        # Run novelty classification (as ingestion does)
        from novelty_classifier import classify_novelty
        results = classify_novelty(session, [new_claim], company_ticker="NVDA")

        # Apply contradiction metadata (as ingestion does)
        from document_ingestion_service import _apply_contradiction_metadata
        _apply_contradiction_metadata(session, results)
        session.flush()

        # Verify contradiction is persisted
        fresh = session.get(Claim, new_claim.id)
        assert fresh.novelty_type == NoveltyType.CONFLICTING
        assert fresh.is_contradicted is True
        assert fresh.contradicts_claim_id == prior.id

    def test_non_conflicting_claim_no_contradiction_flag(self, session):
        """A confirming claim should not be flagged as contradicted."""
        _make_company(session)
        now = datetime.utcnow()
        doc1 = _make_document(session, published_at=now - timedelta(days=1))
        doc2 = _make_document(session, published_at=now)

        # Prior claim: positive demand
        prior = _make_claim(session, doc1.id,
                            text_norm="NVIDIA GPU demand for data center chips is strong and accelerating rapidly",
                            direction=Direction.POSITIVE,
                            published_at=now - timedelta(days=1))
        session.add(ClaimCompanyLink(claim_id=prior.id, company_ticker="NVDA", relation_type="about"))
        session.flush()

        # New claim: also positive demand (confirming, not contradicting)
        new_claim = Claim(
            document_id=doc2.id,
            claim_text_normalized="NVIDIA GPU demand for data center chips continues to grow with robust momentum",
            claim_text_short="GPU demand growing",
            claim_type=ClaimType.DEMAND,
            economic_channel=EconomicChannel.REVENUE,
            direction=Direction.POSITIVE,
            strength=0.8,
            novelty_type=NoveltyType.NEW,
            confidence=0.9,
            published_at=now,
        )
        session.add(new_claim)
        session.flush()
        session.add(ClaimCompanyLink(claim_id=new_claim.id, company_ticker="NVDA", relation_type="about"))
        session.flush()

        from novelty_classifier import classify_novelty
        results = classify_novelty(session, [new_claim], company_ticker="NVDA")

        from document_ingestion_service import _apply_contradiction_metadata
        _apply_contradiction_metadata(session, results)
        session.flush()

        fresh = session.get(Claim, new_claim.id)
        # Should be confirming, not contradicted
        assert fresh.novelty_type == NoveltyType.CONFIRMING
        assert fresh.is_contradicted is False
        assert fresh.contradicts_claim_id is None

    def test_contradiction_fields_persisted(self, session):
        """is_contradicted and contradicts_claim_id persist through DB round-trip."""
        _make_company(session)
        doc = _make_document(session)

        c = _make_claim(session, doc.id,
                        is_contradicted=True, contradicts_claim_id=42)
        session.flush()

        fresh = session.get(Claim, c.id)
        assert fresh.is_contradicted is True
        assert fresh.contradicts_claim_id == 42


# ===========================================================================
# 4. Contradiction Metadata Flows Into Evidence Scoring
# ===========================================================================

class TestContradictionInEvidenceScoring:
    """Contradiction metadata should be wired into evidence scoring at thesis update."""

    def test_contradicted_claim_metadata_in_assessment(self, session):
        """A contradicted claim's assessment should carry is_contradicted flag."""
        _make_company(session)
        now = datetime.utcnow()
        doc = _make_document(session, published_at=now)
        thesis = _make_thesis(session)

        c = _make_claim(session, doc.id,
                        text_norm="NVIDIA GPU demand decelerating in data centers",
                        direction=Direction.NEGATIVE,
                        is_contradicted=True,
                        contradicts_claim_id=999,
                        event_cluster_id="evt_1",
                        published_at=now)
        session.add(ClaimCompanyLink(claim_id=c.id, company_ticker="NVDA", relation_type="about"))
        session.flush()

        from thesis_update_service import update_thesis_from_claims
        result = update_thesis_from_claims(
            session, thesis.id, [c.id], use_llm=False,
        )

        assessment = result["assessments"][0]
        assert assessment["is_contradicted"] is True

    def test_evidence_score_receives_contradiction_params(self, session):
        """Evidence scoring should receive contradiction parameters from persisted claim state."""
        from evidence_scoring import score_evidence

        # Score with contradiction
        score_with = score_evidence(
            claim_id=1,
            source_tier=SourceTier.TIER_1,
            novelty_type=NoveltyType.CONFLICTING,
            published_at=datetime.utcnow(),
            is_contradicted=True,
            contradiction_claim_ids=[42],
        )
        assert score_with.is_contradicted is True
        assert score_with.contradiction_claim_ids == [42]

        # Score without contradiction
        score_without = score_evidence(
            claim_id=2,
            source_tier=SourceTier.TIER_1,
            novelty_type=NoveltyType.NEW,
            published_at=datetime.utcnow(),
        )
        assert score_without.is_contradicted is False
        assert score_without.contradiction_claim_ids == []


# ===========================================================================
# 5. EvidenceAssessment Persistence
# ===========================================================================

class TestEvidenceAssessmentPersistence:
    """EvidenceAssessment records should be persisted during thesis update."""

    def test_evidence_assessment_created_on_thesis_update(self, session):
        """Thesis update should persist EvidenceAssessment records."""
        _make_company(session)
        now = datetime.utcnow()
        doc = _make_document(session, published_at=now)
        thesis = _make_thesis(session)

        c = _make_claim(session, doc.id,
                        text_norm="NVIDIA strong AI chip demand for data centers",
                        published_at=now, event_cluster_id="evt_1")
        session.add(ClaimCompanyLink(claim_id=c.id, company_ticker="NVDA", relation_type="about"))
        session.flush()

        from thesis_update_service import update_thesis_from_claims
        update_thesis_from_claims(session, thesis.id, [c.id], use_llm=False)

        # Verify EvidenceAssessment was persisted
        ea = session.scalars(
            select(EvidenceAssessment).where(
                EvidenceAssessment.thesis_id == thesis.id,
                EvidenceAssessment.claim_id == c.id,
            )
        ).first()
        assert ea is not None
        assert ea.evidence_weight > 0
        assert ea.source_tier_weight == 1.0  # TIER_1
        assert ea.freshness_factor > 0
        assert ea.novelty_factor > 0
        assert ea.impact in ("supports", "weakens", "neutral", "conflicting")
        assert ea.assessed_at is not None

    def test_evidence_assessment_contains_cluster_state(self, session):
        """EvidenceAssessment should record cluster context."""
        _make_company(session)
        now = datetime.utcnow()
        doc = _make_document(session, published_at=now)
        thesis = _make_thesis(session)

        c = _make_claim(session, doc.id,
                        text_norm="NVIDIA strong AI demand",
                        published_at=now,
                        event_cluster_id="evt_42")
        session.add(ClaimCompanyLink(claim_id=c.id, company_ticker="NVDA", relation_type="about"))
        session.flush()

        from thesis_update_service import update_thesis_from_claims
        update_thesis_from_claims(session, thesis.id, [c.id], use_llm=False)

        ea = session.scalars(
            select(EvidenceAssessment).where(
                EvidenceAssessment.claim_id == c.id,
            )
        ).first()
        assert ea.event_cluster_id == "evt_42"
        assert ea.cluster_position >= 1

    def test_evidence_assessment_contains_contradiction_state(self, session):
        """EvidenceAssessment should record contradiction context."""
        _make_company(session)
        now = datetime.utcnow()
        doc = _make_document(session, published_at=now)
        thesis = _make_thesis(session)

        c = _make_claim(session, doc.id,
                        text_norm="NVIDIA demand decelerating",
                        direction=Direction.NEGATIVE,
                        published_at=now,
                        event_cluster_id="evt_1",
                        is_contradicted=True,
                        contradicts_claim_id=99)
        session.add(ClaimCompanyLink(claim_id=c.id, company_ticker="NVDA", relation_type="about"))
        session.flush()

        from thesis_update_service import update_thesis_from_claims
        update_thesis_from_claims(session, thesis.id, [c.id], use_llm=False)

        ea = session.scalars(
            select(EvidenceAssessment).where(
                EvidenceAssessment.claim_id == c.id,
            )
        ).first()
        assert ea.is_contradicted is True
        assert ea.contradicts_claim_id == 99

    def test_evidence_assessment_upsert_on_rerun(self, session):
        """Re-running thesis update should update, not duplicate, EvidenceAssessment."""
        _make_company(session)
        now = datetime.utcnow()
        doc = _make_document(session, published_at=now)
        thesis = _make_thesis(session)

        c = _make_claim(session, doc.id,
                        text_norm="NVIDIA strong AI demand",
                        published_at=now, event_cluster_id="evt_1")
        session.add(ClaimCompanyLink(claim_id=c.id, company_ticker="NVDA", relation_type="about"))
        session.flush()

        from thesis_update_service import update_thesis_from_claims
        update_thesis_from_claims(session, thesis.id, [c.id], use_llm=False)
        update_thesis_from_claims(session, thesis.id, [c.id], use_llm=False)

        # Should have exactly 1 EvidenceAssessment, not 2
        ea_count = session.scalars(
            select(EvidenceAssessment).where(
                EvidenceAssessment.thesis_id == thesis.id,
                EvidenceAssessment.claim_id == c.id,
            )
        ).all()
        assert len(ea_count) == 1

    def test_evidence_assessment_queryable_by_thesis(self, session):
        """Downstream layers should be able to query all assessments for a thesis."""
        _make_company(session)
        now = datetime.utcnow()
        doc = _make_document(session, published_at=now)
        thesis = _make_thesis(session)

        claims = []
        for i in range(3):
            c = _make_claim(session, doc.id,
                            text_norm=f"Claim about NVIDIA topic {i}",
                            published_at=now, event_cluster_id=f"evt_{i}")
            session.add(ClaimCompanyLink(claim_id=c.id, company_ticker="NVDA", relation_type="about"))
            claims.append(c)
        session.flush()

        from thesis_update_service import update_thesis_from_claims
        update_thesis_from_claims(
            session, thesis.id, [c.id for c in claims], use_llm=False,
        )

        # Query all assessments for this thesis
        all_ea = session.scalars(
            select(EvidenceAssessment).where(
                EvidenceAssessment.thesis_id == thesis.id,
            )
        ).all()
        assert len(all_ea) == 3
        for ea in all_ea:
            assert ea.evidence_weight > 0
            assert ea.delta is not None


# ===========================================================================
# 6. Novelty Classifier Return Value Contract
# ===========================================================================

class TestNoveltyClassifierContract:
    """Novelty classifier now returns 4-tuples with prior claim ID."""

    def test_returns_four_tuple(self, session):
        """classify_novelty should return (claim_id, novelty, sim, prior_id)."""
        _make_company(session)
        doc = _make_document(session)
        c = _make_claim(session, doc.id, text_norm="unique claim about NVIDIA")
        session.add(ClaimCompanyLink(claim_id=c.id, company_ticker="NVDA", relation_type="about"))
        session.flush()

        from novelty_classifier import classify_novelty
        results = classify_novelty(session, [c], company_ticker="NVDA")

        assert len(results) == 1
        assert len(results[0]) == 4  # 4-tuple
        claim_id, novelty, sim, prior_id = results[0]
        assert claim_id == c.id
        assert novelty == NoveltyType.NEW
        assert prior_id is None  # no prior claims

    def test_conflicting_returns_prior_claim_id(self, session):
        """CONFLICTING novelty should return the prior claim ID it conflicts with."""
        _make_company(session)
        now = datetime.utcnow()
        doc1 = _make_document(session, published_at=now - timedelta(days=1))
        doc2 = _make_document(session, published_at=now)

        prior = _make_claim(session, doc1.id,
                            text_norm="NVIDIA GPU demand for data center chips is strong and accelerating rapidly",
                            direction=Direction.POSITIVE,
                            published_at=now - timedelta(days=1))
        session.add(ClaimCompanyLink(claim_id=prior.id, company_ticker="NVDA", relation_type="about"))
        session.flush()

        new_claim = Claim(
            document_id=doc2.id,
            claim_text_normalized="NVIDIA GPU demand for data center chips is weakening and showing signs of slowdown",
            claim_text_short="GPU demand weakening",
            claim_type=ClaimType.DEMAND,
            economic_channel=EconomicChannel.REVENUE,
            direction=Direction.NEGATIVE,
            strength=0.8,
            novelty_type=NoveltyType.NEW,
            confidence=0.9,
            published_at=now,
        )
        session.add(new_claim)
        session.flush()
        session.add(ClaimCompanyLink(claim_id=new_claim.id, company_ticker="NVDA", relation_type="about"))
        session.flush()

        from novelty_classifier import classify_novelty
        results = classify_novelty(session, [new_claim], company_ticker="NVDA")

        claim_id, novelty, sim, prior_id = results[0]
        assert novelty == NoveltyType.CONFLICTING
        assert prior_id == prior.id


# ===========================================================================
# 7. Memory Retrieval Still Deterministic
# ===========================================================================

class TestMemoryRetrievalDeterminism:
    """Memory retrieval should remain deterministic after pipeline changes."""

    def test_retrieval_deterministic_with_new_fields(self, session):
        """retrieve_memory returns same result on repeated calls."""
        _make_company(session)
        now = datetime.utcnow()
        doc = _make_document(session, published_at=now)
        thesis = _make_thesis(session)

        for i in range(5):
            c = _make_claim(session, doc.id,
                            text_norm=f"Claim {i} about NVIDIA AI demand",
                            published_at=now - timedelta(hours=i),
                            event_cluster_id=f"evt_{i}",
                            is_contradicted=(i == 2),
                            contradicts_claim_id=(1 if i == 2 else None))
            session.add(ClaimCompanyLink(claim_id=c.id, company_ticker="NVDA", relation_type="about"))
            session.add(ThesisClaimLink(thesis_id=thesis.id, claim_id=c.id, link_type="supports"))
        session.flush()

        from memory_retrieval import retrieve_memory
        snap1 = retrieve_memory(session, thesis.id)
        snap2 = retrieve_memory(session, thesis.id)

        text1 = snap1.to_prompt_text()
        text2 = snap2.to_prompt_text()
        assert text1 == text2


# ===========================================================================
# 8. EvidenceAssessment Model Schema
# ===========================================================================

class TestEvidenceAssessmentSchema:
    """EvidenceAssessment model should have all required fields."""

    def test_model_has_all_fields(self, session):
        """EvidenceAssessment should have all canonical evidence fields."""
        ea = EvidenceAssessment(
            thesis_id=1,
            claim_id=1,
            source_tier_weight=1.0,
            freshness_factor=0.95,
            novelty_factor=1.0,
            cluster_penalty=1.0,
            evidence_weight=0.95,
            cluster_position=1,
            event_cluster_id="evt_1",
            is_contradicted=False,
            contradicts_claim_id=None,
            impact="supports",
            materiality=0.8,
            delta=3.5,
        )
        assert ea.thesis_id == 1
        assert ea.evidence_weight == 0.95
        assert ea.impact == "supports"
        assert ea.is_contradicted is False

    def test_claim_new_fields_nullable(self, session):
        """New Claim fields should be nullable for backward compat."""
        _make_company(session)
        doc = _make_document(session)
        # Create claim without new fields
        c = Claim(
            document_id=doc.id,
            claim_text_normalized="test",
            claim_text_short="test",
            claim_type=ClaimType.DEMAND,
            economic_channel=EconomicChannel.REVENUE,
            direction=Direction.POSITIVE,
            strength=0.5,
            novelty_type=NoveltyType.NEW,
            confidence=0.8,
            published_at=datetime.utcnow(),
        )
        session.add(c)
        session.flush()

        fresh = session.get(Claim, c.id)
        assert fresh.is_contradicted is False  # default
        assert fresh.contradicts_claim_id is None
        assert fresh.event_cluster_id is None
        assert fresh.source_excerpt is None
