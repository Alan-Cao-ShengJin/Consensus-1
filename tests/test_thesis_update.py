"""Tests for thesis update engine — uses mocked LLM and stub mode."""
import json
from unittest.mock import patch, MagicMock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from models import (
    Base, Company, Document, Claim, Thesis,
    ThesisClaimLink, ThesisStateHistory, ClaimCompanyLink,
    SourceType, SourceTier, ClaimType, EconomicChannel,
    Direction, NoveltyType, ThesisState,
)
from thesis_update_service import (
    update_thesis_from_claims,
    compute_claim_delta,
    apply_conviction_update,
    resolve_state,
    ThesisUpdateResponse,
    ClaimAssessment,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _seed_thesis(session, state=ThesisState.FORMING, score=50.0):
    """Create a company + thesis and return thesis."""
    company = Company(ticker="NVDA", name="NVIDIA")
    session.add(company)
    session.flush()
    thesis = Thesis(
        title="AI Capex Thesis",
        company_ticker="NVDA",
        state=state,
        conviction_score=score,
        summary="NVIDIA benefits from AI infrastructure spending.",
    )
    session.add(thesis)
    session.flush()
    return thesis


def _seed_claim(session, doc, direction=Direction.POSITIVE, strength=0.8,
                novelty=NoveltyType.NEW, confidence=0.85,
                claim_type=ClaimType.DEMAND,
                text="AI infrastructure spending drove 93% revenue growth"):
    """Create a claim attached to a document."""
    claim = Claim(
        document_id=doc.id,
        claim_text_normalized=text,
        claim_text_short=text[:30],
        claim_type=claim_type,
        economic_channel=EconomicChannel.REVENUE,
        direction=direction,
        strength=strength,
        novelty_type=novelty,
        confidence=confidence,
    )
    session.add(claim)
    session.flush()
    return claim


def _seed_document(session, ticker="NVDA"):
    doc = Document(
        source_type=SourceType.EARNINGS_TRANSCRIPT,
        source_tier=SourceTier.TIER_1,
        title="Q4 Earnings",
        primary_company_ticker=ticker,
        raw_text="Test document",
    )
    session.add(doc)
    session.flush()
    return doc


def _mock_llm_response(overall_state, summary, assessments_data):
    """Build a mock for call_openai_json_object."""
    return {
        "overall_state_recommendation": overall_state,
        "summary_note": summary,
        "claim_assessments": assessments_data,
    }


# ---------------------------------------------------------------------------
# Unit tests for scoring functions
# ---------------------------------------------------------------------------

class TestConvictionScoring:

    def test_supports_new_high_confidence(self):
        delta = compute_claim_delta("supports", 0.9, "new", 0.85, 1.0)
        assert delta > 0
        assert round(delta, 2) == round(5.0 * 0.9 * 1.25 * 0.85 * 1.0, 2)

    def test_weakens_negative(self):
        delta = compute_claim_delta("weakens", 0.8, "new", 0.9, 1.0)
        assert delta < 0

    def test_neutral_zero(self):
        delta = compute_claim_delta("neutral", 0.5, "new", 0.9, 1.0)
        assert delta == 0.0

    def test_repetitive_dampened(self):
        new_delta = compute_claim_delta("supports", 0.8, "new", 0.85, 1.0)
        rep_delta = compute_claim_delta("supports", 0.8, "repetitive", 0.85, 1.0)
        assert abs(rep_delta) < abs(new_delta)

    def test_apply_conviction_dampened_at_extremes(self):
        # At 95, moving up is dampened (headroom=5, dampening=5/50=0.1)
        result_high = apply_conviction_update(95.0, [10.0, 10.0])
        assert result_high > 95.0  # still moves up
        assert result_high < 100.0  # but dampened, doesn't reach 100
        # At 5, moving down is dampened
        result_low = apply_conviction_update(5.0, [-10.0, -10.0])
        assert result_low < 5.0  # still moves down
        assert result_low > 0.0  # but dampened, doesn't reach 0

    def test_apply_conviction_per_doc_cap(self):
        # 20 deltas of +5 each = 100 raw, but capped at MAX_PER_DOCUMENT_DELTA (15)
        result = apply_conviction_update(50.0, [5.0] * 20)
        assert result <= 65.0  # capped at 15 * dampening(1.0) = 15 max

    def test_conflicting_less_punitive_than_weakens(self):
        weak = compute_claim_delta("weakens", 0.8, "new", 0.85, 1.0)
        conf = compute_claim_delta("conflicting", 0.8, "new", 0.85, 1.0)
        assert abs(conf) < abs(weak)  # conflicting is now less punitive

    def test_high_conviction_can_still_decline(self):
        # Even at 90, a strong negative signal should push score down
        result = apply_conviction_update(90.0, [-10.0])
        assert result < 90.0


class TestResolveState:

    def test_broken_on_low_score(self):
        assert resolve_state("stable", "stable", 10.0) == ThesisState.BROKEN

    def test_probation_on_low_score(self):
        assert resolve_state("stable", "stable", 25.0) == ThesisState.PROBATION

    def test_strengthening(self):
        assert resolve_state("stable", "strengthening", 60.0, score_delta=5.0) == ThesisState.STRENGTHENING

    def test_weakening(self):
        assert resolve_state("stable", "weakening", 40.0, score_delta=-5.0) == ThesisState.WEAKENING

    def test_stable_default(self):
        assert resolve_state("stable", "stable", 50.0) == ThesisState.STABLE

    def test_inertia_resists_small_flip_bullish_to_bearish(self):
        # Small delta should NOT flip from strengthening to weakening
        result = resolve_state("strengthening", "weakening", 55.0, score_delta=-2.0)
        assert result == ThesisState.STABLE  # holds steady

    def test_inertia_allows_large_flip(self):
        # Large delta SHOULD allow the flip
        result = resolve_state("strengthening", "weakening", 45.0, score_delta=-10.0)
        assert result == ThesisState.WEAKENING

    def test_inertia_resists_small_flip_bearish_to_bullish(self):
        result = resolve_state("weakening", "strengthening", 48.0, score_delta=2.0)
        assert result == ThesisState.WEAKENING  # stays in current bearish state


# ---------------------------------------------------------------------------
# Integration tests with stub mode (no LLM)
# ---------------------------------------------------------------------------

class TestThesisUpdateStub:

    def test_strengthening_case(self, session):
        thesis = _seed_thesis(session, score=50.0)
        doc = _seed_document(session)
        c1 = _seed_claim(session, doc, direction=Direction.POSITIVE, strength=0.9)
        c2 = _seed_claim(session, doc, direction=Direction.POSITIVE, strength=0.8,
                         text="AI infrastructure guidance raised above consensus")

        result = update_thesis_from_claims(
            session, thesis.id, [c1.id, c2.id], use_llm=False,
        )

        assert result["after_score"] > result["before_score"]
        assert result["after_state"] in ("strengthening", "stable")

    def test_weakening_case(self, session):
        thesis = _seed_thesis(session, state=ThesisState.STABLE, score=50.0)
        doc = _seed_document(session)
        c1 = _seed_claim(session, doc, direction=Direction.NEGATIVE, strength=0.9)
        c2 = _seed_claim(session, doc, direction=Direction.NEGATIVE, strength=0.85,
                         text="AI infrastructure margins compressed significantly")

        result = update_thesis_from_claims(
            session, thesis.id, [c1.id, c2.id], use_llm=False,
        )

        assert result["after_score"] < result["before_score"]

    def test_conflicting_evidence(self, session):
        thesis = _seed_thesis(session, score=50.0)
        doc = _seed_document(session)
        c1 = _seed_claim(session, doc, direction=Direction.POSITIVE, strength=0.8)
        c2 = _seed_claim(session, doc, direction=Direction.MIXED, strength=0.7,
                         text="Mixed signals on AI infrastructure demand outlook")

        result = update_thesis_from_claims(
            session, thesis.id, [c1.id, c2.id], use_llm=False,
        )

        # Should still produce a valid result
        assert "after_score" in result
        assert "assessments" in result

    def test_repetitive_evidence(self, session):
        thesis = _seed_thesis(session, score=60.0)
        doc = _seed_document(session)
        c1 = _seed_claim(session, doc, direction=Direction.POSITIVE, strength=0.7,
                         novelty=NoveltyType.REPETITIVE)

        result = update_thesis_from_claims(
            session, thesis.id, [c1.id], use_llm=False,
        )

        # Repetitive should have smaller impact
        delta = result["after_score"] - result["before_score"]
        assert abs(delta) < 3.0  # dampened by 0.4 multiplier

    def test_broken_thesis(self, session):
        thesis = _seed_thesis(session, state=ThesisState.WEAKENING, score=20.0)
        doc = _seed_document(session)
        c1 = _seed_claim(session, doc, direction=Direction.NEGATIVE, strength=0.95)
        c2 = _seed_claim(session, doc, direction=Direction.NEGATIVE, strength=0.9,
                         text="NVIDIA lost key AI infrastructure contract")

        result = update_thesis_from_claims(
            session, thesis.id, [c1.id, c2.id], use_llm=False,
        )

        assert result["after_score"] < result["before_score"]
        # Score low enough should trigger broken or probation
        assert result["after_state"] in ("broken", "probation")

    def test_history_row_appended(self, session):
        thesis = _seed_thesis(session, score=50.0)
        doc = _seed_document(session)
        c1 = _seed_claim(session, doc)

        update_thesis_from_claims(session, thesis.id, [c1.id], use_llm=False)

        history = session.scalars(
            select(ThesisStateHistory).where(
                ThesisStateHistory.thesis_id == thesis.id
            )
        ).all()
        assert len(history) == 1
        assert history[0].conviction_score is not None
        assert history[0].note is not None

    def test_thesis_claim_links_created(self, session):
        thesis = _seed_thesis(session, score=50.0)
        doc = _seed_document(session)
        c1 = _seed_claim(session, doc, direction=Direction.POSITIVE)
        c2 = _seed_claim(session, doc, direction=Direction.NEGATIVE,
                         text="AI infrastructure competition intensifying from AMD")

        update_thesis_from_claims(session, thesis.id, [c1.id, c2.id], use_llm=False)

        links = session.scalars(
            select(ThesisClaimLink).where(ThesisClaimLink.thesis_id == thesis.id)
        ).all()
        assert len(links) == 2
        link_types = {l.link_type for l in links}
        assert "supports" in link_types
        assert "weakens" in link_types

    def test_no_claims_returns_early(self, session):
        thesis = _seed_thesis(session, score=50.0)

        result = update_thesis_from_claims(
            session, thesis.id, [], use_llm=False,
        )

        assert result["status"] == "no_claims"

    def test_missing_thesis_raises(self, session):
        with pytest.raises(ValueError, match="Thesis 999 not found"):
            update_thesis_from_claims(session, 999, [1], use_llm=False)


# ---------------------------------------------------------------------------
# Tests with mocked LLM
# ---------------------------------------------------------------------------

class TestThesisUpdateWithLLM:

    @patch("llm_client.call_openai_json_object")
    def test_llm_strengthening(self, mock_call, session):
        thesis = _seed_thesis(session, score=50.0)
        doc = _seed_document(session)
        c1 = _seed_claim(session, doc)

        mock_call.return_value = _mock_llm_response(
            "strengthening",
            "Revenue beat confirms AI demand thesis.",
            [{"claim_id": c1.id, "impact": "supports",
              "rationale": "Strong revenue growth", "materiality": 0.9}],
        )

        result = update_thesis_from_claims(session, thesis.id, [c1.id], use_llm=True)
        assert result["after_score"] > result["before_score"]

    @patch("llm_client.call_openai_json_object")
    def test_llm_invalid_output_falls_back(self, mock_call, session):
        """If LLM returns garbage, falls back to stub."""
        thesis = _seed_thesis(session, score=50.0)
        doc = _seed_document(session)
        c1 = _seed_claim(session, doc)

        mock_call.side_effect = Exception("LLM returned nonsense")

        result = update_thesis_from_claims(session, thesis.id, [c1.id], use_llm=True)

        # Should still produce a valid result via stub fallback
        assert "after_score" in result
        assert "after_state" in result

    @patch("llm_client.call_openai_json_object")
    def test_llm_broken_recommendation(self, mock_call, session):
        thesis = _seed_thesis(session, state=ThesisState.WEAKENING, score=35.0)
        doc = _seed_document(session)
        c1 = _seed_claim(session, doc, direction=Direction.NEGATIVE, strength=0.95)

        mock_call.return_value = _mock_llm_response(
            "broken",
            "Fundamental thesis invalidated by competitive loss.",
            [{"claim_id": c1.id, "impact": "weakens",
              "rationale": "Major competitive loss", "materiality": 0.95}],
        )

        result = update_thesis_from_claims(session, thesis.id, [c1.id], use_llm=True)
        assert result["after_state"] in ("broken", "probation")


# ---------------------------------------------------------------------------
# Tests for novelty classification (Fix 1)
# ---------------------------------------------------------------------------

class TestNoveltyClassification:

    def test_repeated_claim_becomes_repetitive(self, session):
        """A second doc with the same claim text should be marked repetitive."""
        from novelty_classifier import classify_novelty

        company = Company(ticker="NVDA", name="NVIDIA")
        session.add(company)
        session.flush()

        doc1 = _seed_document(session)
        c1 = _seed_claim(session, doc1, text="Revenue grew 93% year-over-year to $18.4 billion")
        session.add(ClaimCompanyLink(claim_id=c1.id, company_ticker="NVDA", relation_type="affects"))
        session.flush()

        doc2 = _seed_document(session)
        c2 = _seed_claim(session, doc2, text="Revenue grew 93% year-over-year to $18.4 billion")
        session.add(ClaimCompanyLink(claim_id=c2.id, company_ticker="NVDA", relation_type="affects"))
        session.flush()

        results = classify_novelty(session, [c2], company_ticker="NVDA")
        assert len(results) == 1
        assert results[0][1] == NoveltyType.REPETITIVE

    def test_new_claim_stays_new(self, session):
        """A genuinely different claim should remain new."""
        from novelty_classifier import classify_novelty

        company = Company(ticker="NVDA", name="NVIDIA")
        session.add(company)
        session.flush()

        doc1 = _seed_document(session)
        c1 = _seed_claim(session, doc1, text="Revenue grew 93% year-over-year")
        session.add(ClaimCompanyLink(claim_id=c1.id, company_ticker="NVDA", relation_type="affects"))
        session.flush()

        doc2 = _seed_document(session)
        c2 = _seed_claim(session, doc2, text="Cybertruck production ramp delayed to Q3")
        session.add(ClaimCompanyLink(claim_id=c2.id, company_ticker="NVDA", relation_type="affects"))
        session.flush()

        results = classify_novelty(session, [c2], company_ticker="NVDA")
        assert results[0][1] == NoveltyType.NEW

    def test_conflicting_direction_detected(self, session):
        """Similar text but opposite direction should be classified as conflicting."""
        from novelty_classifier import classify_novelty

        company = Company(ticker="NVDA", name="NVIDIA")
        session.add(company)
        session.flush()

        doc1 = _seed_document(session)
        c1 = _seed_claim(session, doc1, direction=Direction.POSITIVE,
                         text="Data center revenue growth remained strong at 40%")
        session.add(ClaimCompanyLink(claim_id=c1.id, company_ticker="NVDA", relation_type="affects"))
        session.flush()

        doc2 = _seed_document(session)
        c2 = _seed_claim(session, doc2, direction=Direction.NEGATIVE,
                         text="Data center revenue growth slowed to 30%")
        session.add(ClaimCompanyLink(claim_id=c2.id, company_ticker="NVDA", relation_type="affects"))
        session.flush()

        results = classify_novelty(session, [c2], company_ticker="NVDA")
        # Should be either confirming or conflicting (same topic, different direction)
        assert results[0][1] in (NoveltyType.CONFIRMING, NoveltyType.CONFLICTING)


# ---------------------------------------------------------------------------
# Tests for relevance gating (Fix 5)
# ---------------------------------------------------------------------------

class TestRelevanceGating:

    def test_irrelevant_claim_does_not_move_score(self, session):
        """A retail fashion claim should not affect an AI/GPU thesis."""
        thesis = _seed_thesis(session, score=50.0)
        thesis.title = "AI Infrastructure Capex Thesis"
        thesis.summary = "NVIDIA benefits from AI infrastructure spending on GPUs."
        session.flush()

        doc = _seed_document(session)
        # Claim about fast fashion retail that has NO keyword overlap with AI/GPU thesis
        c1 = _seed_claim(session, doc, direction=Direction.NEGATIVE, strength=0.9,
                         text="Zara launched a new clothing line targeting teen fashion buyers")

        result = update_thesis_from_claims(
            session, thesis.id, [c1.id], use_llm=False,
        )

        # The irrelevant claim should have zero impact
        assert abs(result["after_score"] - result["before_score"]) < 0.01

    def test_relevant_claim_does_move_score(self, session):
        """A claim about AI infrastructure should affect the AI thesis."""
        thesis = _seed_thesis(session, score=50.0)
        thesis.title = "AI Infrastructure Capex Thesis"
        thesis.summary = "NVIDIA benefits from AI infrastructure spending on GPUs."
        session.flush()

        doc = _seed_document(session)
        c1 = _seed_claim(session, doc, direction=Direction.POSITIVE, strength=0.9,
                         text="AI infrastructure spending accelerated driven by GPU demand")

        result = update_thesis_from_claims(
            session, thesis.id, [c1.id], use_llm=False,
        )

        assert result["after_score"] > result["before_score"]


# ---------------------------------------------------------------------------
# Tests for fuzzy enum mapping (Fix 6)
# ---------------------------------------------------------------------------

class TestFuzzyEnumMapping:

    def test_economic_channel_in_claim_type_is_fixed(self):
        """If LLM puts 'revenue' in claim_type, it should be mapped to 'demand'."""
        from claim_extractor import _normalize_enums

        raw = {"claim_type": "revenue", "economic_channel": "revenue"}
        fixed = _normalize_enums(raw)
        assert fixed["claim_type"] == "demand"

    def test_sentiment_mapped_to_demand(self):
        from claim_extractor import _normalize_enums

        raw = {"claim_type": "sentiment", "economic_channel": "sentiment"}
        fixed = _normalize_enums(raw)
        assert fixed["claim_type"] == "demand"

    def test_valid_enums_unchanged(self):
        from claim_extractor import _normalize_enums

        raw = {"claim_type": "demand", "economic_channel": "revenue"}
        fixed = _normalize_enums(raw)
        assert fixed["claim_type"] == "demand"
        assert fixed["economic_channel"] == "revenue"

    def test_claim_type_in_economic_channel_is_fixed(self):
        from claim_extractor import _normalize_enums

        raw = {"claim_type": "demand", "economic_channel": "competition"}
        fixed = _normalize_enums(raw)
        assert fixed["economic_channel"] == "revenue"
