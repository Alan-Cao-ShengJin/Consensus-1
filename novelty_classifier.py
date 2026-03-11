"""Post-extraction novelty classification against existing DB claims.

Compares newly extracted claims against prior claims for the same company
to reclassify novelty_type as: new, confirming, repetitive, or conflicting.
The LLM extractor has no prior context, so novelty must be determined here.
"""
from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import Claim, ClaimCompanyLink, NoveltyType

logger = logging.getLogger(__name__)

# Thresholds for text similarity (0-1 scale)
REPETITIVE_THRESHOLD = 0.70   # very similar text = repetitive
CONFIRMING_THRESHOLD = 0.45   # moderately similar = confirming
# Below confirming threshold = new (unless direction conflicts)


def _tokenize(text: str) -> set[str]:
    """Simple whitespace + lowercase tokenizer, drop short tokens."""
    return {w.lower() for w in re.findall(r"[a-zA-Z0-9%$]+", text) if len(w) > 2}


def _jaccard_similarity(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _text_similarity(text_a: str, text_b: str) -> float:
    """Combined similarity: average of Jaccard token overlap and SequenceMatcher ratio."""
    jaccard = _jaccard_similarity(_tokenize(text_a), _tokenize(text_b))
    seq_ratio = SequenceMatcher(None, text_a.lower(), text_b.lower()).ratio()
    return (jaccard + seq_ratio) / 2.0


def classify_novelty(
    session: Session,
    new_claims: list[Claim],
    company_ticker: str | None = None,
) -> list[tuple[int, NoveltyType, float]]:
    """Classify novelty of new claims against existing DB claims.

    Args:
        session: DB session
        new_claims: List of newly ingested Claim objects (already in DB)
        company_ticker: Optional ticker to scope prior claim lookup

    Returns:
        List of (claim_id, new_novelty_type, best_similarity_score) tuples.
        Also updates the claim.novelty_type in-place.
    """
    if not new_claims:
        return []

    new_claim_ids = {c.id for c in new_claims}

    # Fetch prior claims for the same company (exclude the new batch)
    if company_ticker:
        prior_claim_ids_q = (
            select(ClaimCompanyLink.claim_id)
            .where(ClaimCompanyLink.company_ticker == company_ticker)
        )
        prior_claims = session.scalars(
            select(Claim)
            .where(
                Claim.id.in_(prior_claim_ids_q),
                ~Claim.id.in_(new_claim_ids),
            )
        ).all()
    else:
        prior_claims = session.scalars(
            select(Claim).where(~Claim.id.in_(new_claim_ids))
        ).all()

    if not prior_claims:
        # No prior claims = everything is genuinely new
        return [(c.id, NoveltyType.NEW, 0.0) for c in new_claims]

    results = []
    for new_claim in new_claims:
        best_sim = 0.0
        best_prior = None

        for prior in prior_claims:
            sim = _text_similarity(
                new_claim.claim_text_normalized,
                prior.claim_text_normalized,
            )
            if sim > best_sim:
                best_sim = sim
                best_prior = prior

        # Classify based on similarity and direction agreement
        if best_sim >= REPETITIVE_THRESHOLD:
            novelty = NoveltyType.REPETITIVE
        elif best_sim >= CONFIRMING_THRESHOLD:
            # Check if directions agree or conflict
            if best_prior and new_claim.direction != best_prior.direction:
                novelty = NoveltyType.CONFLICTING
            else:
                novelty = NoveltyType.CONFIRMING
        else:
            novelty = NoveltyType.NEW

        # Update in-place
        if new_claim.novelty_type != novelty:
            logger.info(
                "Claim %d novelty: %s -> %s (sim=%.2f vs claim %s)",
                new_claim.id, new_claim.novelty_type.value, novelty.value,
                best_sim, best_prior.id if best_prior else "N/A",
            )
            new_claim.novelty_type = novelty

        results.append((new_claim.id, novelty, round(best_sim, 3)))

    return results
