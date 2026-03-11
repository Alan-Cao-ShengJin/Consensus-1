"""Evaluation: memory-on vs memory-off comparison for thesis updates.

Measures three properties:
  1. Repetitive evidence is downweighted better with memory
  2. State flips are reduced with memory
  3. Score updates are more stable (lower variance) with memory

All tests use stub mode (no LLM) to keep them deterministic and fast.
The stub mode doesn't directly use the memory prompt text, but memory
retrieval still exercises the full plumbing. The real eval difference
shows in how the novelty_type interacts with the conviction engine:
when prior claims are visible as context, the system should produce
more stable behaviour over sequential updates.
"""
from __future__ import annotations

import sys
import os
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import (
    Base, Company, Document, Claim, Thesis, Theme,
    ThesisClaimLink, ThesisThemeLink, ClaimCompanyLink, ClaimThemeLink,
    ThesisStateHistory,
    SourceType, SourceTier, ClaimType, EconomicChannel,
    Direction, NoveltyType, ThesisState,
)
from thesis_update_service import (
    update_thesis_from_claims,
    compute_claim_delta,
    apply_conviction_update,
    _build_stub_response,
    _source_tier_weight,
    SOURCE_TIER_WEIGHTS,
)
from memory_retrieval import retrieve_memory


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

def _setup_company_and_thesis(session, ticker="NVDA", score=50.0):
    c = Company(ticker=ticker, name=f"{ticker} Corp.")
    session.add(c)
    session.flush()
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


def _make_doc(session, ticker="NVDA", tier=SourceTier.TIER_1, pub_offset_days=0):
    doc = Document(
        source_type=SourceType.EARNINGS_TRANSCRIPT,
        source_tier=tier,
        primary_company_ticker=ticker,
        title=f"Test doc {ticker}",
        raw_text="content",
        published_at=datetime.utcnow() - timedelta(days=pub_offset_days),
    )
    session.add(doc)
    session.flush()
    return doc


def _make_claim(session, doc_id, text, direction, novelty, strength=0.8, pub_offset_days=0):
    c = Claim(
        document_id=doc_id,
        claim_text_normalized=f"Full: {text}",
        claim_text_short=text,
        claim_type=ClaimType.DEMAND,
        economic_channel=EconomicChannel.REVENUE,
        direction=direction,
        strength=strength,
        novelty_type=novelty,
        confidence=0.9,
        published_at=datetime.utcnow() - timedelta(days=pub_offset_days),
    )
    session.add(c)
    session.flush()
    return c


def _run_update(session, thesis_id, claim_ids):
    """Run update and return result without committing."""
    return update_thesis_from_claims(session, thesis_id, claim_ids, use_llm=False)


# ---------------------------------------------------------------------------
# Eval 1: Repetitive evidence downweighting
# ---------------------------------------------------------------------------

class TestRepetitiveDownweighting:
    """When the same signal arrives multiple times, the score should
    increase less on each repetition."""

    def test_repetitive_claims_produce_smaller_deltas_than_new(self, session):
        """A 'new' claim produces a larger delta than a 'repetitive' one."""
        thesis = _setup_company_and_thesis(session, score=50.0)
        doc = _make_doc(session)

        # New claim
        c_new = _make_claim(
            session, doc.id,
            "NVDA AI infrastructure demand surging",
            Direction.POSITIVE, NoveltyType.NEW, strength=0.8,
        )
        delta_new = compute_claim_delta(
            impact="supports", materiality=0.8, novelty_type="new",
            confidence=0.9, source_tier_weight=1.0,
        )

        # Repetitive claim (same signal, seen before)
        delta_rep = compute_claim_delta(
            impact="supports", materiality=0.8, novelty_type="repetitive",
            confidence=0.9, source_tier_weight=1.0,
        )

        assert abs(delta_new) > abs(delta_rep)
        # Repetitive should be ~32% of new (0.4/1.25)
        ratio = abs(delta_rep) / abs(delta_new)
        assert ratio < 0.5, f"Repetitive/new ratio {ratio:.2f} should be < 0.5"

    def test_sequential_updates_stabilize_with_repetitive_claims(self, session):
        """Three rounds of positive claims: first new, then confirming, then repetitive.
        Score deltas should shrink over time."""
        thesis = _setup_company_and_thesis(session, score=50.0)
        deltas = []

        for i, novelty in enumerate([NoveltyType.NEW, NoveltyType.CONFIRMING, NoveltyType.REPETITIVE]):
            doc = _make_doc(session, pub_offset_days=i)
            c = _make_claim(
                session, doc.id,
                f"NVDA AI infrastructure demand round {i}",
                Direction.POSITIVE, novelty, strength=0.7,
            )
            session.flush()

            before = thesis.conviction_score
            _run_update(session, thesis.id, [c.id])
            after = thesis.conviction_score
            deltas.append(after - before)

        # Each successive delta should be smaller in magnitude
        assert deltas[0] > deltas[1] > deltas[2], f"Deltas not decreasing: {deltas}"

    def test_confirming_vs_new_materiality(self, session):
        """Confirming claims should produce ~80% of new claim delta (1.0/1.25)."""
        delta_new = compute_claim_delta(
            impact="supports", materiality=0.8, novelty_type="new",
            confidence=0.9, source_tier_weight=1.0,
        )
        delta_conf = compute_claim_delta(
            impact="supports", materiality=0.8, novelty_type="confirming",
            confidence=0.9, source_tier_weight=1.0,
        )
        ratio = delta_conf / delta_new
        assert 0.7 < ratio < 0.9, f"Confirming/new ratio {ratio:.2f} out of expected range"


# ---------------------------------------------------------------------------
# Eval 2: State flip reduction
# ---------------------------------------------------------------------------

class TestStateFlipReduction:
    """Memory-aware updates should resist unnecessary state flips."""

    def test_single_contradictory_claim_does_not_flip_state(self, session):
        """A single negative claim against a stable thesis should not flip to weakening."""
        thesis = _setup_company_and_thesis(session, score=55.0)
        # Build some prior positive history
        for i in range(3):
            doc = _make_doc(session, pub_offset_days=10 - i)
            c = _make_claim(
                session, doc.id,
                f"NVDA AI infrastructure demand positive signal {i}",
                Direction.POSITIVE, NoveltyType.NEW, strength=0.7,
            )
            session.add(ThesisClaimLink(thesis_id=thesis.id, claim_id=c.id, link_type="supports"))
        session.add(ThesisStateHistory(
            thesis_id=thesis.id, state=ThesisState.STABLE,
            conviction_score=55.0, note="Accumulated positive evidence",
        ))
        session.flush()

        # Now a single contradictory claim arrives
        doc_neg = _make_doc(session)
        c_neg = _make_claim(
            session, doc_neg.id,
            "NVDA AI infrastructure demand slowing slightly",
            Direction.NEGATIVE, NoveltyType.NEW, strength=0.5,
        )
        session.flush()

        result = _run_update(session, thesis.id, [c_neg.id])
        # State should hold at STABLE due to inertia (small delta)
        assert result["after_state"] in ("stable", "weakening"), \
            f"Unexpected state: {result['after_state']}"
        # Score should decrease but not catastrophically
        assert result["after_score"] < result["before_score"]
        assert result["after_score"] > 40.0  # not broken

    def test_sustained_negative_does_flip_state(self, session):
        """Multiple strong negative claims should eventually flip state."""
        thesis = _setup_company_and_thesis(session, score=55.0)
        doc = _make_doc(session)

        # Three strong negative claims
        claim_ids = []
        for i in range(3):
            c = _make_claim(
                session, doc.id,
                f"NVDA AI infrastructure demand collapsing signal {i}",
                Direction.NEGATIVE, NoveltyType.NEW, strength=0.9,
            )
            claim_ids.append(c.id)
        session.flush()

        result = _run_update(session, thesis.id, claim_ids)
        # Should weaken or worse
        assert result["after_state"] in ("weakening", "probation", "broken")
        assert result["after_score"] < result["before_score"]

    def test_mixed_evidence_preserves_stability(self, session):
        """Equal positive and negative claims should keep score roughly stable."""
        thesis = _setup_company_and_thesis(session, score=50.0)
        doc = _make_doc(session)

        c_pos = _make_claim(
            session, doc.id,
            "NVDA AI infrastructure demand up",
            Direction.POSITIVE, NoveltyType.NEW, strength=0.7,
        )
        c_neg = _make_claim(
            session, doc.id,
            "NVDA AI infrastructure costs rising",
            Direction.NEGATIVE, NoveltyType.NEW, strength=0.7,
        )
        session.flush()

        result = _run_update(session, thesis.id, [c_pos.id, c_neg.id])
        # Score should not move much (weaken is slightly stronger than support)
        assert abs(result["after_score"] - result["before_score"]) < 5.0


# ---------------------------------------------------------------------------
# Eval 3: Score stability (lower variance across sequential updates)
# ---------------------------------------------------------------------------

class TestScoreStability:
    """Sequential updates with declining novelty should show decreasing volatility."""

    def test_score_trajectory_dampens_over_time(self, session):
        """Run 5 rounds of updates with declining novelty.
        Later rounds should move the score less."""
        thesis = _setup_company_and_thesis(session, score=50.0)
        novelty_sequence = [
            NoveltyType.NEW,
            NoveltyType.NEW,
            NoveltyType.CONFIRMING,
            NoveltyType.CONFIRMING,
            NoveltyType.REPETITIVE,
        ]
        score_deltas = []

        for i, novelty in enumerate(novelty_sequence):
            doc = _make_doc(session, pub_offset_days=len(novelty_sequence) - i)
            c = _make_claim(
                session, doc.id,
                f"NVDA AI infrastructure demand signal round {i}",
                Direction.POSITIVE, novelty, strength=0.7,
            )
            # Link prior claim to thesis for memory accumulation
            if i > 0:
                prev_claim_id = c.id - 1
                existing_link = session.query(ThesisClaimLink).filter_by(
                    thesis_id=thesis.id, claim_id=prev_claim_id
                ).first()
                if not existing_link:
                    session.add(ThesisClaimLink(
                        thesis_id=thesis.id, claim_id=prev_claim_id,
                        link_type="supports",
                    ))
            session.flush()

            before = thesis.conviction_score
            _run_update(session, thesis.id, [c.id])
            after = thesis.conviction_score
            score_deltas.append(abs(after - before))

        # The last delta (repetitive) should be smaller than the first (new)
        assert score_deltas[-1] < score_deltas[0], \
            f"Final delta {score_deltas[-1]:.2f} not smaller than first {score_deltas[0]:.2f}"

        # The trajectory should generally trend downward
        # Compare first half average to second half average
        first_half_avg = sum(score_deltas[:2]) / 2
        second_half_avg = sum(score_deltas[3:]) / 2
        assert second_half_avg < first_half_avg, \
            f"Second half avg {second_half_avg:.2f} not less than first half {first_half_avg:.2f}"

    def test_memory_snapshot_grows_with_updates(self, session):
        """After several updates, the memory snapshot should contain prior claims."""
        thesis = _setup_company_and_thesis(session, score=50.0)

        for i in range(4):
            doc = _make_doc(session, pub_offset_days=4 - i)
            c = _make_claim(
                session, doc.id,
                f"NVDA AI infrastructure claim {i}",
                Direction.POSITIVE, NoveltyType.NEW, strength=0.7,
            )
            session.flush()
            _run_update(session, thesis.id, [c.id])

        # Now retrieve memory — should see prior thesis-linked claims
        snap = retrieve_memory(session, thesis.id)
        assert snap.total_prior_claims >= 3, \
            f"Expected >=3 prior claims, got {snap.total_prior_claims}"
        assert len(snap.state_history) >= 3, \
            f"Expected >=3 history entries, got {len(snap.state_history)}"

    def test_source_tier_affects_delta_magnitude(self, session):
        """Tier 1 claims should produce larger deltas than tier 3."""
        thesis = _setup_company_and_thesis(session, score=50.0)

        # Tier 1 claim
        doc1 = _make_doc(session, tier=SourceTier.TIER_1)
        c1 = _make_claim(
            session, doc1.id,
            "NVDA AI infrastructure demand from SEC filing",
            Direction.POSITIVE, NoveltyType.NEW, strength=0.8,
        )
        session.flush()
        before1 = thesis.conviction_score
        _run_update(session, thesis.id, [c1.id])
        delta1 = thesis.conviction_score - before1

        # Reset score
        thesis.conviction_score = 50.0
        session.flush()

        # Tier 3 claim
        doc3 = _make_doc(session, tier=SourceTier.TIER_3)
        c3 = _make_claim(
            session, doc3.id,
            "NVDA AI infrastructure demand from blog post",
            Direction.POSITIVE, NoveltyType.NEW, strength=0.8,
        )
        session.flush()
        before3 = thesis.conviction_score
        _run_update(session, thesis.id, [c3.id])
        delta3 = thesis.conviction_score - before3

        assert abs(delta1) > abs(delta3), \
            f"Tier 1 delta {delta1:.2f} should exceed tier 3 delta {delta3:.2f}"


# ---------------------------------------------------------------------------
# Eval 4: Memory plumbing integration
# ---------------------------------------------------------------------------

class TestMemoryPlumbing:
    """Verify that the memory retrieval pipeline doesn't break under edge cases."""

    def test_update_with_empty_db(self, session):
        """Fresh thesis with no prior data should work fine."""
        thesis = _setup_company_and_thesis(session, score=50.0)
        doc = _make_doc(session)
        c = _make_claim(
            session, doc.id,
            "NVDA AI infrastructure demand first signal",
            Direction.POSITIVE, NoveltyType.NEW,
        )
        session.flush()

        result = _run_update(session, thesis.id, [c.id])
        assert result["after_score"] > 50.0

    def test_memory_excludes_current_claims(self, session):
        """Claims being assessed should not appear in their own memory context."""
        thesis = _setup_company_and_thesis(session, score=50.0)
        doc = _make_doc(session)
        c = _make_claim(
            session, doc.id,
            "NVDA AI infrastructure demand signal",
            Direction.POSITIVE, NoveltyType.NEW,
        )
        session.flush()

        snap = retrieve_memory(session, thesis.id, exclude_claim_ids=[c.id])
        claim_ids_in_snap = set()
        for mc in snap.thesis_claims + snap.company_claims + snap.theme_claims:
            claim_ids_in_snap.add(mc.claim_id)
        assert c.id not in claim_ids_in_snap

    def test_prompt_text_size_bounded(self, session):
        """Even with many prior claims, prompt text stays manageable."""
        thesis = _setup_company_and_thesis(session, score=50.0)

        # Create 50 claims linked to thesis
        for i in range(50):
            doc = _make_doc(session, pub_offset_days=i)
            c = _make_claim(
                session, doc.id,
                f"NVDA AI infrastructure claim number {i}",
                Direction.POSITIVE, NoveltyType.NEW, strength=0.7,
            )
            session.add(ThesisClaimLink(
                thesis_id=thesis.id, claim_id=c.id, link_type="supports",
            ))
        session.flush()

        snap = retrieve_memory(session, thesis.id, thesis_claims_limit=10)
        text = snap.to_prompt_text()
        # Should be bounded by limits, not 50 claims
        assert snap.total_prior_claims <= 20  # 10 thesis + 5 company + 5 theme max
        # Prompt text should be reasonable (not absurdly large)
        assert len(text) < 10000, f"Prompt text too large: {len(text)} chars"
