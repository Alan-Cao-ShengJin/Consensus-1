"""Deterministic evidence scoring layer.

Computes an evidence_weight for each claim based on:
  1. Source tier (tier_1=1.0, tier_2=0.7, tier_3=0.4)
  2. Freshness (exponential decay from published_at)
  3. Novelty type (new > confirming > conflicting > repetitive)
  4. Duplicate-event penalty (claims in the same event cluster are downweighted)
  5. Contradiction metadata (tracked and propagated)

The output evidence_weight replaces the raw source_tier_weight in conviction
delta calculations, giving thesis updates a more accurate picture of how much
each claim should move the needle.

All scoring is deterministic: same inputs → same output, no LLM involvement.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from models import SourceTier, NoveltyType


# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

SOURCE_TIER_WEIGHTS: dict[SourceTier, float] = {
    SourceTier.TIER_1: 1.0,
    SourceTier.TIER_2: 0.7,
    SourceTier.TIER_3: 0.4,
}

NOVELTY_WEIGHTS: dict[NoveltyType, float] = {
    NoveltyType.NEW: 1.0,
    NoveltyType.CONFIRMING: 0.6,
    NoveltyType.CONFLICTING: 0.8,   # conflicting is informationally significant
    NoveltyType.REPETITIVE: 0.15,
}

# Freshness: half-life in days.  After this many days, freshness factor = 0.5.
FRESHNESS_HALF_LIFE_DAYS: float = 30.0

# Duplicate-event cluster penalties.
# First claim in a cluster gets full weight; subsequent claims are penalized.
# The Nth claim (N >= 2) in a cluster gets weight = CLUSTER_DECAY_BASE ^ (N-1).
CLUSTER_DECAY_BASE: float = 0.3  # 2nd article = 0.3, 3rd = 0.09, etc.

# Floor: no evidence weight below this (prevents total zeroing)
EVIDENCE_WEIGHT_FLOOR: float = 0.02


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class EvidenceScore:
    """Computed evidence score for a single claim."""
    claim_id: int
    source_tier_weight: float
    freshness_factor: float
    novelty_factor: float
    cluster_penalty: float       # 1.0 = no penalty, <1.0 = penalized
    evidence_weight: float       # final composite weight
    is_contradicted: bool        # True if this claim contradicts prior evidence
    contradiction_claim_ids: list[int]  # IDs of contradicting claims


# ---------------------------------------------------------------------------
# Scoring functions
# ---------------------------------------------------------------------------

def compute_freshness(
    published_at: Optional[datetime],
    reference_time: Optional[datetime] = None,
    half_life_days: float = FRESHNESS_HALF_LIFE_DAYS,
) -> float:
    """Exponential decay freshness factor.

    Returns 1.0 for claims published now, 0.5 after half_life_days,
    approaching 0 for very old claims.  Returns 0.5 if published_at is None.
    """
    if published_at is None:
        return 0.5  # unknown date = moderate penalty

    ref = reference_time or datetime.utcnow()
    age_days = max(0.0, (ref - published_at).total_seconds() / 86400.0)

    if half_life_days <= 0:
        return 1.0 if age_days == 0 else 0.0

    return math.pow(0.5, age_days / half_life_days)


def compute_cluster_penalty(
    cluster_position: int,
    decay_base: float = CLUSTER_DECAY_BASE,
) -> float:
    """Penalty for the Nth claim in an event cluster.

    Position 1 (first/only) = 1.0 (no penalty).
    Position 2 = decay_base.
    Position 3 = decay_base^2.
    """
    if cluster_position <= 1:
        return 1.0
    return math.pow(decay_base, cluster_position - 1)


def score_evidence(
    claim_id: int,
    source_tier: SourceTier,
    novelty_type: NoveltyType,
    published_at: Optional[datetime] = None,
    reference_time: Optional[datetime] = None,
    cluster_position: int = 1,
    is_contradicted: bool = False,
    contradiction_claim_ids: Optional[list[int]] = None,
) -> EvidenceScore:
    """Compute a single claim's evidence score.

    All factors are multiplied together to produce the final evidence_weight.
    The weight is floored at EVIDENCE_WEIGHT_FLOOR to prevent total zeroing.
    """
    tier_w = SOURCE_TIER_WEIGHTS.get(source_tier, 0.5)
    fresh = compute_freshness(published_at, reference_time)
    novelty = NOVELTY_WEIGHTS.get(novelty_type, 0.5)
    cluster = compute_cluster_penalty(cluster_position)

    raw_weight = tier_w * fresh * novelty * cluster
    weight = max(EVIDENCE_WEIGHT_FLOOR, round(raw_weight, 6))

    return EvidenceScore(
        claim_id=claim_id,
        source_tier_weight=tier_w,
        freshness_factor=round(fresh, 6),
        novelty_factor=novelty,
        cluster_penalty=round(cluster, 6),
        evidence_weight=weight,
        is_contradicted=is_contradicted,
        contradiction_claim_ids=contradiction_claim_ids or [],
    )


def score_evidence_batch(
    claims_data: list[dict],
    reference_time: Optional[datetime] = None,
) -> list[EvidenceScore]:
    """Score a batch of claims.

    Each dict in claims_data should have:
      - claim_id: int
      - source_tier: SourceTier
      - novelty_type: NoveltyType
      - published_at: Optional[datetime]
      - cluster_position: int (default 1)
      - is_contradicted: bool (default False)
      - contradiction_claim_ids: list[int] (default [])
    """
    return [
        score_evidence(
            claim_id=d["claim_id"],
            source_tier=d["source_tier"],
            novelty_type=d["novelty_type"],
            published_at=d.get("published_at"),
            reference_time=reference_time,
            cluster_position=d.get("cluster_position", 1),
            is_contradicted=d.get("is_contradicted", False),
            contradiction_claim_ids=d.get("contradiction_claim_ids", []),
        )
        for d in claims_data
    ]
