"""Tests for thesis update engine — uses mocked LLM and stub mode."""
import json
from unittest.mock import patch, MagicMock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from models import (
    Base, Company, Document, Claim, Thesis,
    ThesisClaimLink, ThesisStateHistory,
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
                claim_type=ClaimType.DEMAND, text="Revenue grew 93% YoY"):
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

    def test_apply_conviction_clamped(self):
        assert apply_conviction_update(95.0, [10.0, 10.0]) == 100.0
        assert apply_conviction_update(5.0, [-10.0, -10.0]) == 0.0


class TestResolveState:

    def test_broken_on_low_score(self):
        assert resolve_state("stable", "stable", 10.0) == ThesisState.BROKEN

    def test_probation_on_low_score(self):
        assert resolve_state("stable", "stable", 25.0) == ThesisState.PROBATION

    def test_strengthening(self):
        assert resolve_state("stable", "strengthening", 60.0) == ThesisState.STRENGTHENING

    def test_weakening(self):
        assert resolve_state("stable", "weakening", 40.0) == ThesisState.WEAKENING

    def test_stable_default(self):
        assert resolve_state("stable", "stable", 50.0) == ThesisState.STABLE


# ---------------------------------------------------------------------------
# Integration tests with stub mode (no LLM)
# ---------------------------------------------------------------------------

class TestThesisUpdateStub:

    def test_strengthening_case(self, session):
        thesis = _seed_thesis(session, score=50.0)
        doc = _seed_document(session)
        c1 = _seed_claim(session, doc, direction=Direction.POSITIVE, strength=0.9)
        c2 = _seed_claim(session, doc, direction=Direction.POSITIVE, strength=0.8,
                         text="Guidance raised above consensus")

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
                         text="Margins compressed significantly")

        result = update_thesis_from_claims(
            session, thesis.id, [c1.id, c2.id], use_llm=False,
        )

        assert result["after_score"] < result["before_score"]

    def test_conflicting_evidence(self, session):
        thesis = _seed_thesis(session, score=50.0)
        doc = _seed_document(session)
        c1 = _seed_claim(session, doc, direction=Direction.POSITIVE, strength=0.8)
        c2 = _seed_claim(session, doc, direction=Direction.MIXED, strength=0.7,
                         text="Mixed signals on demand outlook")

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
                         text="Company lost key contract")

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
                         text="Competition intensifying")

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
