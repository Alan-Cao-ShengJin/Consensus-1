"""Thesis update engine: classify claims against a thesis, update conviction + state."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from models import (
    Claim, Thesis, ThesisClaimLink, ThesisStateHistory,
    ThesisState, SourceTier, ValuationProvenance,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic models for structured LLM output
# ---------------------------------------------------------------------------

class ClaimAssessment(BaseModel):
    claim_id: int
    impact: Literal["supports", "weakens", "neutral", "conflicting"]
    rationale: str
    materiality: float = Field(ge=0, le=1)


class ThesisUpdateResponse(BaseModel):
    overall_state_recommendation: Literal[
        "forming", "strengthening", "stable", "weakening",
        "probation", "broken", "achieved",
    ]
    summary_note: str
    claim_assessments: List[ClaimAssessment]


# ---------------------------------------------------------------------------
# Conviction scoring (code-controlled, not LLM)
# ---------------------------------------------------------------------------

SOURCE_TIER_WEIGHTS = {
    SourceTier.TIER_1: 1.0,
    SourceTier.TIER_2: 0.7,
    SourceTier.TIER_3: 0.4,
}


MAX_PER_DOCUMENT_DELTA = 15.0  # cap total absolute move from one document


def compute_claim_delta(
    impact: str,
    materiality: float,
    novelty_type: str,
    confidence: float,
    source_tier_weight: float,
) -> float:
    base = 0.0
    if impact == "supports":
        base = 5.0
    elif impact == "weakens":
        base = -6.0
    elif impact == "conflicting":
        base = -2.0   # mixed evidence is less punitive than outright negative
    elif impact == "neutral":
        base = 0.0

    novelty_mult = {
        "new": 1.25,
        "confirming": 1.0,
        "repetitive": 0.4,
        "conflicting": 1.1,
    }.get(novelty_type, 1.0)

    return base * materiality * novelty_mult * confidence * source_tier_weight


def apply_conviction_update(current_score: float, deltas: list[float]) -> float:
    """Apply deltas with dampening near extremes and per-document cap.

    Uses sigmoid-inspired dampening: as score approaches 0 or 100, the
    effective delta shrinks, preventing instant saturation and ensuring
    conviction can always move back on meaningful counter-evidence.
    """
    raw_total = sum(deltas)

    # Per-document cap: limit total absolute move
    if abs(raw_total) > MAX_PER_DOCUMENT_DELTA:
        raw_total = MAX_PER_DOCUMENT_DELTA if raw_total > 0 else -MAX_PER_DOCUMENT_DELTA

    # Dampening near extremes: reduce effective delta as score approaches bounds
    # The "headroom" is how far we are from the boundary we're moving toward
    if raw_total > 0:
        headroom = 100.0 - current_score
    elif raw_total < 0:
        headroom = current_score
    else:
        return current_score

    # Dampening factor: full effect in the middle, reduced at extremes
    # At score=50, factor ~1.0; at score=90 moving up, factor ~0.4; at score=95, ~0.2
    dampening = min(1.0, headroom / 50.0)
    dampening = max(0.05, dampening)  # floor: always allow at least 5% of delta through

    effective_delta = raw_total * dampening
    new_score = current_score + effective_delta
    return max(0.0, min(100.0, round(new_score, 2)))


# ---------------------------------------------------------------------------
# State transitions (code-controlled guardrails)
# ---------------------------------------------------------------------------

# States grouped by sentiment direction for inertia checks
_BULLISH_STATES = {"strengthening", "stable", "achieved"}
_BEARISH_STATES = {"weakening", "probation", "broken"}

# Minimum score delta magnitude to justify a state flip between bullish/bearish
STATE_FLIP_MIN_DELTA = 3.0


def resolve_state(
    current_state: str,
    recommended_state: str,
    new_score: float,
    score_delta: float = 0.0,
) -> ThesisState:
    """Resolve the new thesis state with inertia against rapid flips.

    Score guardrails always apply (broken <= 15, probation <= 30).
    But for sentiment-direction flips (bullish <-> bearish), we require
    the score delta to exceed STATE_FLIP_MIN_DELTA to avoid oscillation
    from a single contradictory document.
    """
    # Hard score guardrails always take priority
    if new_score <= 15:
        return ThesisState.BROKEN
    if new_score <= 30:
        return ThesisState.PROBATION

    # Determine if this is a sentiment-direction flip
    current_is_bullish = current_state in _BULLISH_STATES or current_state == "forming"
    current_is_bearish = current_state in _BEARISH_STATES
    rec_is_bullish = recommended_state in _BULLISH_STATES
    rec_is_bearish = recommended_state in _BEARISH_STATES

    # Inertia: resist flips between bullish and bearish on small deltas
    if current_is_bullish and rec_is_bearish and abs(score_delta) < STATE_FLIP_MIN_DELTA:
        return ThesisState.STABLE  # hold steady instead of flipping
    if current_is_bearish and rec_is_bullish and abs(score_delta) < STATE_FLIP_MIN_DELTA:
        return ThesisState(current_state)  # stay in current bearish state

    if recommended_state == "broken":
        return ThesisState.BROKEN
    if recommended_state == "probation":
        return ThesisState.PROBATION
    if recommended_state == "weakening":
        return ThesisState.WEAKENING
    if recommended_state == "strengthening":
        return ThesisState.STRENGTHENING
    if recommended_state == "achieved":
        return ThesisState.ACHIEVED
    return ThesisState.STABLE


# ---------------------------------------------------------------------------
# LLM classification
# ---------------------------------------------------------------------------

def classify_claims_against_thesis(
    thesis: Thesis,
    claims: list[Claim],
    memory_context: str = "",
) -> ThesisUpdateResponse:
    """Call the LLM to classify each claim's impact on the thesis."""
    from llm_client import call_openai_json_object
    from prompts import build_thesis_update_messages

    claims_data = [
        {
            "claim_id": c.id,
            "claim_text": c.claim_text_normalized,
            "claim_type": c.claim_type.value,
            "direction": c.direction.value,
            "strength": c.strength,
            "novelty_type": c.novelty_type.value,
        }
        for c in claims
    ]

    messages = build_thesis_update_messages(
        thesis_title=thesis.title,
        company_ticker=thesis.company_ticker,
        current_state=thesis.state.value,
        conviction_score=thesis.conviction_score or 50.0,
        thesis_summary=thesis.summary or "",
        claims_json=json.dumps(claims_data, indent=2),
        memory_context=memory_context,
    )

    raw = call_openai_json_object(messages)
    return ThesisUpdateResponse.model_validate(raw)


def _claim_is_relevant_to_thesis(claim: Claim, thesis: Thesis) -> bool:
    """Basic keyword-based relevance check for stub mode.

    Returns True if the claim text shares meaningful domain terms with the
    thesis title or summary. Generic business/financial terms don't count.
    This prevents unrelated claims (e.g., retail competition) from affecting
    a thesis about cloud computing.

    Deliberately generous: defaults to relevant unless clearly unrelated.
    """
    import re

    def _tokenize(text: str) -> set[str]:
        return {w.lower() for w in re.findall(r"[a-zA-Z]+", text) if len(w) > 3}

    # Generic financial/business terms that don't indicate domain relevance
    generic_terms = {
        "this", "that", "with", "from", "will", "have", "been", "their",
        "than", "more", "also", "about", "into", "over", "said", "were",
        "which", "some", "year", "company", "quarter", "billion", "million",
        "percent", "growth", "revenue", "increased", "decreased", "reported",
        "expects", "expected", "strong", "analyst", "investors", "shares",
        "market", "price", "stock", "fiscal", "annual", "quarterly",
        "spending", "demand", "business", "operating", "income", "margin",
    }

    thesis_text = f"{thesis.title} {thesis.summary or ''} {thesis.company_ticker or ''}"
    thesis_tokens = _tokenize(thesis_text) - generic_terms
    claim_tokens = _tokenize(claim.claim_text_normalized) - generic_terms

    if not thesis_tokens:
        return True  # can't determine thesis domain, assume relevant

    if not claim_tokens:
        return True  # generic claim, let it through

    overlap = thesis_tokens & claim_tokens
    # Require at least 1 domain-specific shared term
    return len(overlap) >= 1


def _build_stub_response(
    claims: list[Claim],
    thesis: Thesis | None = None,
) -> ThesisUpdateResponse:
    """Deterministic fallback when use_llm=False."""
    assessments = []
    for c in claims:
        # Relevance gating: if thesis provided and claim is not relevant, mark neutral
        if thesis and not _claim_is_relevant_to_thesis(c, thesis):
            assessments.append(ClaimAssessment(
                claim_id=c.id,
                impact="neutral",
                rationale=f"Stub: claim not relevant to thesis '{thesis.title}'",
                materiality=0.0,
            ))
            continue

        if c.direction.value == "positive":
            impact = "supports"
        elif c.direction.value == "negative":
            impact = "weakens"
        elif c.direction.value == "mixed":
            impact = "conflicting"
        else:
            impact = "neutral"

        assessments.append(ClaimAssessment(
            claim_id=c.id,
            impact=impact,
            rationale=f"Stub: direction={c.direction.value}",
            materiality=c.strength or 0.5,
        ))

    # Simple recommendation based on majority impact (only relevant claims)
    relevant = [a for a in assessments if a.materiality > 0]
    support_count = sum(1 for a in relevant if a.impact == "supports")
    weaken_count = sum(1 for a in relevant if a.impact in ("weakens", "conflicting"))
    if support_count > weaken_count:
        rec = "strengthening"
    elif weaken_count > support_count:
        rec = "weakening"
    else:
        rec = "stable"

    return ThesisUpdateResponse(
        overall_state_recommendation=rec,
        summary_note="Stub assessment based on claim directions.",
        claim_assessments=assessments,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_assessment(
    response: ThesisUpdateResponse,
    claim_id: int,
) -> Optional[ClaimAssessment]:
    for a in response.claim_assessments:
        if a.claim_id == claim_id:
            return a
    return None


def _source_tier_weight(claim: Claim) -> float:
    """Get source tier weight from the claim's document."""
    if claim.document and claim.document.source_tier:
        return SOURCE_TIER_WEIGHTS.get(claim.document.source_tier, 0.5)
    return 0.5


def _ensure_thesis_claim_link(
    session: Session,
    thesis_id: int,
    claim_id: int,
    link_type: str,
) -> None:
    """Create or update a ThesisClaimLink row."""
    existing = session.scalars(
        select(ThesisClaimLink).where(
            ThesisClaimLink.thesis_id == thesis_id,
            ThesisClaimLink.claim_id == claim_id,
        )
    ).first()
    if existing:
        existing.link_type = link_type
    else:
        session.add(ThesisClaimLink(
            thesis_id=thesis_id,
            claim_id=claim_id,
            link_type=link_type,
        ))


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def update_thesis_from_claims(
    session: Session,
    thesis_id: int,
    claim_ids: list[int],
    use_llm: bool = True,
) -> dict:
    """Update a thesis based on newly ingested claims.

    Returns a dict with before/after state, score, and per-claim assessments.
    """
    thesis = session.get(Thesis, thesis_id)
    if not thesis:
        raise ValueError(f"Thesis {thesis_id} not found")

    claims = session.scalars(
        select(Claim).where(Claim.id.in_(claim_ids))
    ).all()

    if not claims:
        return {"status": "no_claims", "thesis_id": thesis_id}

    before_state = thesis.state
    before_score = thesis.conviction_score or 50.0

    # --- Retrieve temporal memory for context ---
    memory_context = ""
    try:
        from memory_retrieval import retrieve_memory
        snapshot = retrieve_memory(
            session, thesis_id, exclude_claim_ids=claim_ids,
        )
        memory_context = snapshot.to_prompt_text()
    except Exception as e:
        logger.warning("Memory retrieval failed (continuing without): %s", e)

    # --- LLM classification (or stub fallback) ---
    if use_llm:
        try:
            llm_result = classify_claims_against_thesis(
                thesis, claims, memory_context=memory_context,
            )
        except Exception as e:
            logger.error("LLM classification failed, falling back to stub: %s", e)
            llm_result = _build_stub_response(claims, thesis)
    else:
        llm_result = _build_stub_response(claims, thesis)

    # --- Compute conviction deltas (code decides, not LLM) ---
    deltas: list[float] = []
    assessments: list[dict] = []
    for claim in claims:
        assessment = _find_assessment(llm_result, claim.id)
        impact = assessment.impact if assessment else "neutral"
        materiality = assessment.materiality if assessment else 0.5

        stw = _source_tier_weight(claim)
        confidence = claim.confidence or 0.7
        novelty = claim.novelty_type.value

        delta = compute_claim_delta(
            impact=impact,
            materiality=materiality,
            novelty_type=novelty,
            confidence=confidence,
            source_tier_weight=stw,
        )
        deltas.append(delta)
        assessments.append({
            "claim_id": claim.id,
            "impact": impact,
            "materiality": materiality,
            "delta": round(delta, 4),
        })

        # Map impact to link_type for the DB
        link_type_map = {
            "supports": "supports",
            "weakens": "weakens",
            "neutral": "context",
            "conflicting": "weakens",
        }
        _ensure_thesis_claim_link(
            session, thesis.id, claim.id, link_type_map.get(impact, "context")
        )

    new_score = apply_conviction_update(before_score, deltas)
    score_delta = new_score - before_score
    new_state = resolve_state(
        before_state.value,
        llm_result.overall_state_recommendation,
        new_score,
        score_delta=score_delta,
    )

    # --- Apply DB updates ---
    thesis.conviction_score = new_score
    thesis.state = new_state
    thesis.updated_at = datetime.utcnow()

    session.add(ThesisStateHistory(
        thesis_id=thesis.id,
        state=new_state,
        conviction_score=new_score,
        valuation_gap_pct=thesis.valuation_gap_pct,
        base_case_rerating=thesis.base_case_rerating,
        valuation_provenance=(
            ValuationProvenance.HISTORICAL_RECORDED.value
            if thesis.valuation_gap_pct is not None
            else ValuationProvenance.MISSING.value
        ),
        note=llm_result.summary_note,
    ))

    session.flush()

    return {
        "thesis_id": thesis.id,
        "before_state": before_state.value,
        "after_state": new_state.value,
        "before_score": round(before_score, 2),
        "after_score": round(new_score, 2),
        "summary_note": llm_result.summary_note,
        "assessments": assessments,
    }
