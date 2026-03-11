from datetime import datetime

from sqlalchemy.orm import Session

from models import Thesis, ThesisClaimLink, ThesisStateHistory, ThesisState, SourceTier


# ---- Conviction scoring ----

SOURCE_TIER_WEIGHTS = {
    SourceTier.TIER_1: 1.0,
    SourceTier.TIER_2: 0.7,
    SourceTier.TIER_3: 0.4,
}


def apply_claim_to_conviction(
    current_score: float,
    novelty_type: str,
    link_type: str,
    source_tier_weight: float,
    confidence: float,
) -> float:
    delta = 0.0

    if link_type == "supports":
        delta += 4.0
    elif link_type == "weakens":
        delta -= 5.0

    if novelty_type == "new":
        delta *= 1.25
    elif novelty_type == "repetitive":
        delta *= 0.4
    elif novelty_type == "conflicting":
        delta *= 1.1

    delta *= source_tier_weight
    delta *= confidence

    new_score = max(0.0, min(100.0, current_score + delta))
    return new_score


# ---- State derivation ----

def derive_thesis_state(
    current_state: ThesisState,
    old_score: float,
    new_score: float,
) -> ThesisState:
    if new_score <= 10.0:
        return ThesisState.BROKEN
    if new_score >= 90.0:
        return ThesisState.ACHIEVED

    diff = new_score - old_score
    if diff > 2.0:
        return ThesisState.STRENGTHENING
    elif diff < -2.0:
        if new_score < 30.0:
            return ThesisState.PROBATION
        return ThesisState.WEAKENING
    else:
        if current_state == ThesisState.FORMING and new_score >= 40.0:
            return ThesisState.STABLE
        return current_state


# ---- Service ----

class ThesisUpdateService:

    def __init__(self, session: Session):
        self.session = session

    def apply_new_claim(
        self,
        thesis_id: int,
        claim_id: int,
        link_type: str,
        novelty_type: str,
        source_tier: SourceTier,
        confidence: float,
    ) -> Thesis:
        thesis = self.session.get(Thesis, thesis_id)
        if thesis is None:
            raise ValueError(f"Thesis {thesis_id} not found")

        old_score = thesis.conviction_score or 50.0
        source_tier_weight = SOURCE_TIER_WEIGHTS.get(source_tier, 0.5)

        new_score = apply_claim_to_conviction(
            current_score=old_score,
            novelty_type=novelty_type,
            link_type=link_type,
            source_tier_weight=source_tier_weight,
            confidence=confidence,
        )

        new_state = derive_thesis_state(thesis.state, old_score, new_score)

        # Record state change
        if new_state != thesis.state or new_score != old_score:
            self.session.add(ThesisStateHistory(
                thesis_id=thesis.id,
                state=new_state,
                conviction_score=new_score,
                note=f"claim {claim_id}: {link_type} ({novelty_type})",
            ))

        thesis.conviction_score = new_score
        thesis.state = new_state
        thesis.updated_at = datetime.utcnow()

        # Link claim to thesis
        self.session.add(ThesisClaimLink(
            thesis_id=thesis.id,
            claim_id=claim_id,
            link_type=link_type,
        ))

        self.session.flush()
        return thesis
