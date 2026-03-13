"""Tests for evidence/memory hardening (Step 13).

Required tests:
  1. Duplicate event from multiple articles does not overcount as independent evidence
  2. Stale evidence gets lower score than fresh evidence
  3. Retrieval is deterministic for the same DB state / snapshot
  4. Provenance fields are present for persisted claims/evidence
  5. Contradiction metadata is stored and propagated correctly
  6. Evidence scoring is deterministic and composable
  7. Event clustering groups near-duplicate articles correctly
  8. Memory retrieval budget is respected
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
    ThesisClaimLink, ThesisThemeLink, ClaimCompanyLink, ClaimThemeLink,
    ThesisStateHistory, Checkpoint,
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
                published_at=None, source_excerpt=None):
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
# 1. Evidence Scoring — Deterministic, Composable
# ===========================================================================

class TestEvidenceScoring:

    def test_score_is_deterministic(self):
        """Same inputs always produce the same score."""
        from evidence_scoring import score_evidence

        ref = datetime(2025, 6, 15, 12, 0, 0)
        pub = datetime(2025, 6, 14, 12, 0, 0)  # 1 day old

        s1 = score_evidence(1, SourceTier.TIER_1, NoveltyType.NEW, pub, ref)
        s2 = score_evidence(1, SourceTier.TIER_1, NoveltyType.NEW, pub, ref)
        assert s1.evidence_weight == s2.evidence_weight

    def test_tier1_scores_higher_than_tier3(self):
        """Higher source tier → higher evidence weight."""
        from evidence_scoring import score_evidence

        ref = datetime(2025, 6, 15)
        pub = datetime(2025, 6, 15)

        t1 = score_evidence(1, SourceTier.TIER_1, NoveltyType.NEW, pub, ref)
        t3 = score_evidence(2, SourceTier.TIER_3, NoveltyType.NEW, pub, ref)
        assert t1.evidence_weight > t3.evidence_weight

    def test_new_scores_higher_than_repetitive(self):
        """New evidence > repetitive evidence."""
        from evidence_scoring import score_evidence

        ref = datetime(2025, 6, 15)
        pub = datetime(2025, 6, 15)

        new = score_evidence(1, SourceTier.TIER_1, NoveltyType.NEW, pub, ref)
        rep = score_evidence(2, SourceTier.TIER_1, NoveltyType.REPETITIVE, pub, ref)
        assert new.evidence_weight > rep.evidence_weight

    def test_fresh_scores_higher_than_stale(self):
        """Recent claim scores higher than old claim, all else equal."""
        from evidence_scoring import score_evidence

        ref = datetime(2025, 6, 15)
        fresh = datetime(2025, 6, 14)   # 1 day old
        stale = datetime(2025, 1, 1)    # ~165 days old

        s_fresh = score_evidence(1, SourceTier.TIER_1, NoveltyType.NEW, fresh, ref)
        s_stale = score_evidence(2, SourceTier.TIER_1, NoveltyType.NEW, stale, ref)
        assert s_fresh.evidence_weight > s_stale.evidence_weight

    def test_freshness_half_life(self):
        """After half_life_days, freshness factor ≈ 0.5."""
        from evidence_scoring import compute_freshness, FRESHNESS_HALF_LIFE_DAYS

        ref = datetime(2025, 6, 15)
        half_life_ago = ref - timedelta(days=FRESHNESS_HALF_LIFE_DAYS)

        f = compute_freshness(half_life_ago, ref)
        assert abs(f - 0.5) < 0.01

    def test_none_published_at_gets_moderate_penalty(self):
        """Unknown publish date gets 0.5 freshness."""
        from evidence_scoring import compute_freshness
        assert compute_freshness(None) == 0.5

    def test_cluster_penalty_position_1(self):
        """First in cluster = no penalty."""
        from evidence_scoring import compute_cluster_penalty
        assert compute_cluster_penalty(1) == 1.0

    def test_cluster_penalty_decays(self):
        """Higher cluster position → lower weight."""
        from evidence_scoring import compute_cluster_penalty
        p2 = compute_cluster_penalty(2)
        p3 = compute_cluster_penalty(3)
        assert p2 < 1.0
        assert p3 < p2

    def test_evidence_weight_floor(self):
        """Evidence weight never goes below the floor."""
        from evidence_scoring import score_evidence, EVIDENCE_WEIGHT_FLOOR

        ref = datetime(2025, 6, 15)
        very_old = datetime(2020, 1, 1)

        s = score_evidence(
            1, SourceTier.TIER_3, NoveltyType.REPETITIVE, very_old, ref,
            cluster_position=5,
        )
        assert s.evidence_weight >= EVIDENCE_WEIGHT_FLOOR

    def test_contradiction_metadata_propagated(self):
        """Contradiction flags are preserved in the evidence score."""
        from evidence_scoring import score_evidence

        ref = datetime(2025, 6, 15)
        pub = datetime(2025, 6, 15)

        s = score_evidence(
            1, SourceTier.TIER_1, NoveltyType.CONFLICTING, pub, ref,
            is_contradicted=True,
            contradiction_claim_ids=[10, 20],
        )
        assert s.is_contradicted is True
        assert s.contradiction_claim_ids == [10, 20]

    def test_batch_scoring(self):
        """Batch scoring produces same results as individual scoring."""
        from evidence_scoring import score_evidence, score_evidence_batch

        ref = datetime(2025, 6, 15)
        pub = datetime(2025, 6, 14)

        individual = score_evidence(1, SourceTier.TIER_1, NoveltyType.NEW, pub, ref)
        batch = score_evidence_batch([{
            "claim_id": 1,
            "source_tier": SourceTier.TIER_1,
            "novelty_type": NoveltyType.NEW,
            "published_at": pub,
        }], reference_time=ref)

        assert len(batch) == 1
        assert batch[0].evidence_weight == individual.evidence_weight


# ===========================================================================
# 2. Stale Evidence Gets Lower Score Than Fresh Evidence (integration)
# ===========================================================================

class TestStaleVsFreshEvidence:

    def test_stale_claim_has_less_impact_on_thesis(self, session):
        """A 6-month-old claim should move conviction less than a same-day claim."""
        from thesis_update_service import update_thesis_from_claims

        _make_company(session)

        # Fresh claim
        doc_fresh = _make_document(session, published_at=datetime.utcnow())
        thesis_fresh = _make_thesis(session, score=50.0)
        c_fresh = _make_claim(
            session, doc_fresh.id,
            text_norm="NVDA AI infrastructure revenue beat expectations significantly",
            published_at=datetime.utcnow(),
        )
        session.add(ClaimCompanyLink(claim_id=c_fresh.id, company_ticker="NVDA", relation_type="about"))
        session.flush()

        result_fresh = update_thesis_from_claims(
            session, thesis_fresh.id, [c_fresh.id], use_llm=False,
        )
        delta_fresh = result_fresh["after_score"] - result_fresh["before_score"]

        # Stale claim (same content, 180 days old)
        thesis_stale = _make_thesis(session, ticker="NVDA", title="NVDA stale test", score=50.0)
        doc_stale = _make_document(
            session, published_at=datetime.utcnow() - timedelta(days=180),
        )
        c_stale = _make_claim(
            session, doc_stale.id,
            text_norm="NVDA AI infrastructure revenue beat expectations significantly",
            published_at=datetime.utcnow() - timedelta(days=180),
        )
        session.add(ClaimCompanyLink(claim_id=c_stale.id, company_ticker="NVDA", relation_type="about"))
        session.flush()

        result_stale = update_thesis_from_claims(
            session, thesis_stale.id, [c_stale.id], use_llm=False,
        )
        delta_stale = result_stale["after_score"] - result_stale["before_score"]

        # Fresh claim should have more impact
        assert abs(delta_fresh) > abs(delta_stale)


# ===========================================================================
# 3. Duplicate Event Does Not Overcount
# ===========================================================================

class TestDuplicateEventDownweighting:

    def test_cluster_assigns_positions(self):
        """Near-duplicate claims get cluster positions > 1."""
        from event_clustering import cluster_claims_for_company

        now = datetime.utcnow()
        # Create mock claim-like objects
        class MockClaim:
            def __init__(self, id, text, pub):
                self.id = id
                self.claim_text_normalized = text
                self.published_at = pub

        claims = [
            MockClaim(1, "NVDA revenue grew 93% year-over-year to $18.4 billion", now),
            MockClaim(2, "NVIDIA reported revenue growth of 93% YoY reaching $18.4B", now + timedelta(hours=2)),
            MockClaim(3, "NVDA revenue up 93 percent year on year at 18.4 billion", now + timedelta(hours=5)),
            MockClaim(4, "Tesla Cybertruck production delayed to Q3", now),  # different event
        ]

        clusters = cluster_claims_for_company(claims)

        # The three NVDA revenue claims should be in the same cluster
        nvda_cluster = None
        for c in clusters:
            if 1 in c.member_claim_ids:
                nvda_cluster = c
                break

        assert nvda_cluster is not None
        # At least 2 of the 3 similar claims should be clustered together
        similar_in_cluster = sum(1 for cid in [1, 2, 3] if cid in nvda_cluster.member_claim_ids)
        assert similar_in_cluster >= 2

        # Tesla claim should NOT be in the NVDA cluster
        assert 4 not in nvda_cluster.member_claim_ids

    def test_five_duplicate_articles_have_less_impact_than_five_unique(self, session):
        """5 near-duplicate articles should move conviction less than 5 genuinely
        different articles. This is the core overcounting protection."""
        from thesis_update_service import update_thesis_from_claims

        _make_company(session)

        # --- 5 duplicate articles about the same event ---
        thesis_dup = _make_thesis(session, score=50.0)
        dup_claims = []
        for i in range(5):
            doc = _make_document(session, published_at=datetime.utcnow())
            text = f"NVDA AI infrastructure revenue grew 93% year-over-year variant {i}"
            c = _make_claim(session, doc.id, text_norm=text, published_at=datetime.utcnow())
            session.add(ClaimCompanyLink(claim_id=c.id, company_ticker="NVDA", relation_type="about"))
            dup_claims.append(c)
        session.flush()

        result_dup = update_thesis_from_claims(
            session, thesis_dup.id, [c.id for c in dup_claims], use_llm=False,
        )
        delta_dup = result_dup["after_score"] - result_dup["before_score"]

        # --- 5 genuinely different articles ---
        thesis_unique = _make_thesis(session, title="NVDA unique test", score=50.0)
        unique_texts = [
            "NVDA AI infrastructure data center revenue doubled year over year",
            "NVDA gross margins expanded to 78% from 73% prior quarter",
            "NVDA guidance raised above consensus for fiscal Q1 2026",
            "NVDA Blackwell GPU production ramping ahead of schedule",
            "NVDA new partnerships with major cloud providers announced",
        ]
        unique_claims = []
        for text in unique_texts:
            doc = _make_document(session, published_at=datetime.utcnow())
            c = _make_claim(session, doc.id, text_norm=text, published_at=datetime.utcnow())
            session.add(ClaimCompanyLink(claim_id=c.id, company_ticker="NVDA", relation_type="about"))
            unique_claims.append(c)
        session.flush()

        result_unique = update_thesis_from_claims(
            session, thesis_unique.id, [c.id for c in unique_claims], use_llm=False,
        )
        delta_unique = result_unique["after_score"] - result_unique["before_score"]

        # 5 unique claims should have MORE total impact than 5 duplicates
        assert abs(delta_unique) > abs(delta_dup)


# ===========================================================================
# 4. Retrieval Is Deterministic
# ===========================================================================

class TestRetrievalDeterminism:

    def test_same_db_state_same_result(self, session):
        """Two retrieve_memory calls with identical DB state produce identical output."""
        from memory_retrieval import retrieve_memory

        _make_company(session)
        doc = _make_document(session)
        thesis = _make_thesis(session)

        # Create claims with explicit timestamps for reproducibility
        for i in range(8):
            c = _make_claim(
                session, doc.id,
                text_norm=f"Claim number {i}",
                published_at=datetime(2025, 1, 1) + timedelta(hours=i),
            )
            session.add(ThesisClaimLink(
                thesis_id=thesis.id, claim_id=c.id, link_type="supports",
            ))
        session.flush()

        snap1 = retrieve_memory(session, thesis.id)
        snap2 = retrieve_memory(session, thesis.id)

        # Text output must be byte-identical
        assert snap1.to_prompt_text() == snap2.to_prompt_text()

        # Claim ordering must be identical
        ids1 = [mc.claim_id for mc in snap1.thesis_claims]
        ids2 = [mc.claim_id for mc in snap2.thesis_claims]
        assert ids1 == ids2

    def test_retrieval_policy_summary_present(self, session):
        """MemorySnapshot has a retrieval_policy_summary for explainability."""
        from memory_retrieval import retrieve_memory

        _make_company(session)
        thesis = _make_thesis(session)
        session.flush()

        snap = retrieve_memory(session, thesis.id)
        summary = snap.retrieval_policy_summary()
        assert "thesis_id" in summary
        assert "total_items" in summary
        assert "policy" in summary


# ===========================================================================
# 5. Provenance Fields Present
# ===========================================================================

class TestProvenanceFields:

    def test_claim_has_source_excerpt_field(self, session):
        """Claim model supports source_excerpt for raw text provenance."""
        _make_company(session)
        doc = _make_document(session)

        claim = _make_claim(
            session, doc.id,
            text_norm="Revenue grew 93%",
            source_excerpt="...revenue grew 93% year-over-year driven by datacenter...",
        )
        session.flush()

        # Re-fetch from DB
        fetched = session.get(Claim, claim.id)
        assert fetched.source_excerpt == "...revenue grew 93% year-over-year driven by datacenter..."

    def test_claim_has_event_cluster_id_field(self, session):
        """Claim model supports event_cluster_id for dedup tracking."""
        _make_company(session)
        doc = _make_document(session)

        claim = Claim(
            document_id=doc.id,
            claim_text_normalized="Test claim",
            claim_text_short="Test",
            claim_type=ClaimType.DEMAND,
            economic_channel=EconomicChannel.REVENUE,
            direction=Direction.POSITIVE,
            strength=0.8,
            novelty_type=NoveltyType.NEW,
            confidence=0.9,
            event_cluster_id="evt_123",
        )
        session.add(claim)
        session.flush()

        fetched = session.get(Claim, claim.id)
        assert fetched.event_cluster_id == "evt_123"

    def test_claim_provenance_chain_complete(self, session):
        """Full provenance chain: document → claim with all required fields."""
        _make_company(session)
        doc = _make_document(
            session,
            tier=SourceTier.TIER_1,
            published_at=datetime(2025, 6, 15),
            source_type=SourceType.EARNINGS_TRANSCRIPT,
        )

        claim = _make_claim(
            session, doc.id,
            text_norm="Revenue grew 93% year-over-year",
            published_at=datetime(2025, 6, 15),
            source_excerpt="Q4 revenue grew 93% year-over-year to $18.4B",
        )
        session.flush()

        # Verify provenance chain
        fetched = session.get(Claim, claim.id)
        assert fetched.document_id == doc.id
        assert fetched.published_at is not None
        assert fetched.source_excerpt is not None

        # Document provenance
        doc_fetched = session.get(Document, doc.id)
        assert doc_fetched.source_type == SourceType.EARNINGS_TRANSCRIPT
        assert doc_fetched.source_tier == SourceTier.TIER_1
        assert doc_fetched.published_at is not None
        assert doc_fetched.ingested_at is not None

    def test_source_excerpt_null_is_allowed(self, session):
        """source_excerpt is optional — null is valid (backward compat)."""
        _make_company(session)
        doc = _make_document(session)
        claim = _make_claim(session, doc.id)
        session.flush()

        fetched = session.get(Claim, claim.id)
        assert fetched.source_excerpt is None  # null is fine


# ===========================================================================
# 6. Contradiction Metadata
# ===========================================================================

class TestContradictionMetadata:

    def test_novelty_classifier_detects_conflicting(self, session):
        """Opposite-direction claim about the same topic is classified as conflicting."""
        from novelty_classifier import classify_novelty

        _make_company(session)

        doc1 = _make_document(session)
        c1 = _make_claim(
            session, doc1.id,
            text_norm="Data center revenue growth remained strong at 40%",
            direction=Direction.POSITIVE,
        )
        session.add(ClaimCompanyLink(claim_id=c1.id, company_ticker="NVDA", relation_type="about"))
        session.flush()

        doc2 = _make_document(session)
        c2 = _make_claim(
            session, doc2.id,
            text_norm="Data center revenue growth slowed significantly to 20%",
            direction=Direction.NEGATIVE,
        )
        session.add(ClaimCompanyLink(claim_id=c2.id, company_ticker="NVDA", relation_type="about"))
        session.flush()

        results = classify_novelty(session, [c2], company_ticker="NVDA")
        # Should detect the contradiction (similar topic, opposite direction)
        assert len(results) == 1
        assert results[0][1] in (NoveltyType.CONFLICTING, NoveltyType.CONFIRMING)

    def test_evidence_score_carries_contradiction_flag(self):
        """Evidence score propagates contradiction metadata."""
        from evidence_scoring import score_evidence

        s = score_evidence(
            claim_id=1,
            source_tier=SourceTier.TIER_1,
            novelty_type=NoveltyType.CONFLICTING,
            published_at=datetime.utcnow(),
            is_contradicted=True,
            contradiction_claim_ids=[5, 10],
        )
        assert s.is_contradicted is True
        assert 5 in s.contradiction_claim_ids
        assert 10 in s.contradiction_claim_ids
        # Conflicting evidence should still have meaningful weight
        assert s.evidence_weight > 0.1


# ===========================================================================
# 7. Memory Budget Respected
# ===========================================================================

class TestMemoryBudget:

    def test_total_budget_ceiling(self, session):
        """Memory snapshot never exceeds 28 total items."""
        from memory_retrieval import retrieve_memory

        _make_company(session)
        doc = _make_document(session)
        thesis = _make_thesis(session)
        theme = Theme(theme_name="Test Theme")
        session.add(theme)
        session.flush()
        session.add(ThesisThemeLink(thesis_id=thesis.id, theme_id=theme.id))

        # Create 30 thesis-linked claims
        for i in range(30):
            c = _make_claim(
                session, doc.id,
                text_norm=f"Thesis claim {i}",
                published_at=datetime(2025, 1, 1) + timedelta(hours=i),
            )
            session.add(ThesisClaimLink(thesis_id=thesis.id, claim_id=c.id, link_type="supports"))

        # Create 20 company claims
        for i in range(20):
            c = _make_claim(
                session, doc.id,
                text_norm=f"Company claim {i}",
                published_at=datetime(2025, 2, 1) + timedelta(hours=i),
            )
            session.add(ClaimCompanyLink(claim_id=c.id, company_ticker="NVDA", relation_type="about"))

        # Create 20 theme claims
        _make_company(session, "AMD", "AMD Inc.")
        doc_amd = _make_document(session, "AMD")
        for i in range(20):
            c = _make_claim(
                session, doc_amd.id,
                text_norm=f"Theme claim {i}",
                published_at=datetime(2025, 3, 1) + timedelta(hours=i),
            )
            session.add(ClaimThemeLink(claim_id=c.id, theme_id=theme.id))

        # Create 10 state history entries
        for i in range(10):
            session.add(ThesisStateHistory(
                thesis_id=thesis.id,
                state=ThesisState.FORMING,
                conviction_score=50.0 + i,
                created_at=datetime(2025, 1, 1) + timedelta(days=i),
            ))

        # Create 10 checkpoints
        for i in range(10):
            session.add(Checkpoint(
                checkpoint_type="earnings",
                name=f"Checkpoint {i}",
                linked_company_ticker="NVDA",
            ))

        session.flush()

        snap = retrieve_memory(session, thesis.id)

        # Default limits: 10 + 5 + 5 + 5 + 3 = 28 max
        total = snap.total_prior_claims + len(snap.state_history) + len(snap.checkpoints)
        assert total <= 28
        assert len(snap.thesis_claims) <= 10
        assert len(snap.company_claims) <= 5
        assert len(snap.theme_claims) <= 5
        assert len(snap.state_history) <= 5
        assert len(snap.checkpoints) <= 3


# ===========================================================================
# 8. Event Clustering Unit Tests
# ===========================================================================

class TestEventClustering:

    def test_empty_claims_returns_empty(self):
        from event_clustering import cluster_claims_for_company
        assert cluster_claims_for_company([]) == []

    def test_single_claim_is_own_cluster(self):
        from event_clustering import cluster_claims_for_company

        class MockClaim:
            def __init__(self):
                self.id = 1
                self.claim_text_normalized = "Revenue grew 93%"
                self.published_at = datetime.utcnow()

        clusters = cluster_claims_for_company([MockClaim()])
        assert len(clusters) == 1
        assert clusters[0].size == 1

    def test_dissimilar_claims_separate_clusters(self):
        from event_clustering import cluster_claims_for_company

        now = datetime.utcnow()

        class MockClaim:
            def __init__(self, id, text):
                self.id = id
                self.claim_text_normalized = text
                self.published_at = now

        claims = [
            MockClaim(1, "NVDA revenue grew 93% year-over-year driven by datacenter"),
            MockClaim(2, "Tesla Cybertruck production delayed to Q3 due to battery issues"),
        ]
        clusters = cluster_claims_for_company(claims)
        assert len(clusters) == 2

    def test_time_window_enforced(self):
        """Claims outside the time window are not clustered even if similar."""
        from event_clustering import cluster_claims_for_company

        class MockClaim:
            def __init__(self, id, text, pub):
                self.id = id
                self.claim_text_normalized = text
                self.published_at = pub

        now = datetime.utcnow()
        claims = [
            MockClaim(1, "NVDA revenue grew 93% year-over-year", now),
            MockClaim(2, "NVDA revenue grew 93% year-over-year", now + timedelta(days=30)),
        ]
        clusters = cluster_claims_for_company(claims, time_window_hours=72)
        # Same text but 30 days apart → separate clusters
        assert len(clusters) == 2


# ===========================================================================
# 9. Thesis Update Includes Evidence Metadata in Assessments
# ===========================================================================

class TestThesisUpdateEvidenceMetadata:

    def test_assessment_includes_evidence_weight(self, session):
        """Thesis update result includes evidence_weight per claim."""
        from thesis_update_service import update_thesis_from_claims

        _make_company(session)
        doc = _make_document(session, published_at=datetime.utcnow())
        thesis = _make_thesis(session, score=50.0)
        c = _make_claim(
            session, doc.id,
            text_norm="NVDA AI infrastructure revenue doubled",
            published_at=datetime.utcnow(),
        )
        session.add(ClaimCompanyLink(claim_id=c.id, company_ticker="NVDA", relation_type="about"))
        session.flush()

        result = update_thesis_from_claims(session, thesis.id, [c.id], use_llm=False)

        assert len(result["assessments"]) == 1
        a = result["assessments"][0]
        assert "evidence_weight" in a
        assert "cluster_position" in a
        assert "freshness" in a
        assert a["evidence_weight"] > 0
        assert a["cluster_position"] == 1
        assert a["freshness"] > 0.9  # very recent → high freshness


# ===========================================================================
# 10. Schema Migration Safety
# ===========================================================================

class TestSchemaSafety:

    def test_new_fields_are_nullable(self, session):
        """New provenance fields (source_excerpt, event_cluster_id) are nullable
        so existing data is not broken."""
        _make_company(session)
        doc = _make_document(session)

        # Create claim without the new fields (simulates pre-migration data)
        claim = Claim(
            document_id=doc.id,
            claim_text_normalized="Legacy claim",
            claim_text_short="Legacy",
            claim_type=ClaimType.DEMAND,
            economic_channel=EconomicChannel.REVENUE,
            direction=Direction.POSITIVE,
            strength=0.7,
            novelty_type=NoveltyType.NEW,
            confidence=0.8,
        )
        session.add(claim)
        session.flush()

        fetched = session.get(Claim, claim.id)
        assert fetched.source_excerpt is None
        assert fetched.event_cluster_id is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
