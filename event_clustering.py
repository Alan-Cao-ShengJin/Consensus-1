"""Event-level duplicate clustering for claims.

Problem: 5 near-duplicate news articles about the same earnings beat should not
count as 5 independent pieces of evidence. This module clusters claims about the
same real-world event and assigns each claim a position within its cluster.

Approach:
  1. Group claims by company ticker
  2. Within each company, compare claims in a sliding time window
  3. Claims with high text similarity AND overlapping time window → same event cluster
  4. Assign cluster_position (1 = first/primary, 2+ = duplicates)

This is deliberately simple (no embedding models, no ML). It uses the same
text similarity from novelty_classifier plus a temporal proximity check.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import Claim, ClaimCompanyLink, Document

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Claims within this many hours of each other are candidates for the same event
EVENT_TIME_WINDOW_HOURS: float = 72.0

# Text similarity threshold for same-event detection (lower than novelty's
# REPETITIVE_THRESHOLD because we want to catch paraphrased coverage)
EVENT_SIMILARITY_THRESHOLD: float = 0.50

# Max cluster size — stop adding to a cluster after this many members
MAX_CLUSTER_SIZE: int = 20


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class EventCluster:
    """A group of claims about the same real-world event."""
    cluster_id: str
    company_ticker: str
    anchor_claim_id: int           # first claim in the cluster (position 1)
    member_claim_ids: list[int] = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.member_claim_ids)

    def position_of(self, claim_id: int) -> int:
        """Return 1-based position of a claim in this cluster."""
        if claim_id == self.anchor_claim_id:
            return 1
        try:
            idx = self.member_claim_ids.index(claim_id)
            return idx + 1  # member_claim_ids includes anchor at [0]
        except ValueError:
            return 1


# ---------------------------------------------------------------------------
# Text similarity (reuse from novelty_classifier)
# ---------------------------------------------------------------------------

def _text_similarity(text_a: str, text_b: str) -> float:
    """Combined Jaccard + SequenceMatcher similarity."""
    from novelty_classifier import _text_similarity as _ts
    return _ts(text_a, text_b)


# ---------------------------------------------------------------------------
# Core clustering
# ---------------------------------------------------------------------------

def cluster_claims_for_company(
    claims: list[Claim],
    time_window_hours: float = EVENT_TIME_WINDOW_HOURS,
    similarity_threshold: float = EVENT_SIMILARITY_THRESHOLD,
) -> list[EventCluster]:
    """Cluster a list of claims (assumed same company) by event similarity.

    Claims are sorted by published_at, then each is compared to existing
    cluster anchors. If it matches (time + text), it joins that cluster;
    otherwise, it starts a new cluster.

    Returns a list of EventCluster objects.
    """
    if not claims:
        return []

    # Sort by published_at (None → end)
    sorted_claims = sorted(
        claims,
        key=lambda c: c.published_at or datetime.max,
    )

    clusters: list[EventCluster] = []
    claim_to_cluster: dict[int, EventCluster] = {}
    window = timedelta(hours=time_window_hours)

    for claim in sorted_claims:
        matched_cluster = None

        for cluster in clusters:
            if cluster.size >= MAX_CLUSTER_SIZE:
                continue

            # Find anchor claim in our sorted list
            anchor = next((c for c in sorted_claims if c.id == cluster.anchor_claim_id), None)
            if anchor is None:
                continue

            # Time proximity check
            if claim.published_at and anchor.published_at:
                time_diff = abs((claim.published_at - anchor.published_at).total_seconds())
                if time_diff > window.total_seconds():
                    continue
            elif claim.published_at is None and anchor.published_at is None:
                pass  # both unknown, allow comparison
            else:
                continue  # one has date, other doesn't — skip

            # Text similarity check
            sim = _text_similarity(
                claim.claim_text_normalized,
                anchor.claim_text_normalized,
            )
            if sim >= similarity_threshold:
                matched_cluster = cluster
                break

        if matched_cluster:
            matched_cluster.member_claim_ids.append(claim.id)
            claim_to_cluster[claim.id] = matched_cluster
        else:
            # Start a new cluster
            cluster_id = f"evt_{claim.id}"
            new_cluster = EventCluster(
                cluster_id=cluster_id,
                company_ticker="",  # set by caller
                anchor_claim_id=claim.id,
                member_claim_ids=[claim.id],
            )
            clusters.append(new_cluster)
            claim_to_cluster[claim.id] = new_cluster

    return clusters


def assign_event_clusters(
    session: Session,
    new_claim_ids: list[int],
    company_ticker: str,
    lookback_hours: float = EVENT_TIME_WINDOW_HOURS,
) -> dict[int, int]:
    """Assign event cluster positions to new claims by comparing against
    recent existing claims for the same company.

    Returns a dict of {claim_id: cluster_position} for the new claims.
    Position 1 = no duplicate detected (or first in cluster).
    Position 2+ = duplicate of an earlier claim about the same event.

    Also sets claim.event_cluster_id on the new claims.
    """
    if not new_claim_ids:
        return {}

    # Fetch the new claims
    new_claims = session.scalars(
        select(Claim).where(Claim.id.in_(new_claim_ids))
    ).all()
    if not new_claims:
        return {}

    # Fetch recent prior claims for the same company
    cutoff = datetime.utcnow() - timedelta(hours=lookback_hours)
    prior_claim_ids_q = (
        select(ClaimCompanyLink.claim_id)
        .where(ClaimCompanyLink.company_ticker == company_ticker)
    )
    prior_claims = session.scalars(
        select(Claim)
        .where(
            Claim.id.in_(prior_claim_ids_q),
            ~Claim.id.in_(new_claim_ids),
            Claim.published_at >= cutoff,
        )
        .order_by(Claim.published_at.asc())
    ).all()

    # Combine prior + new for clustering
    all_claims = list(prior_claims) + list(new_claims)
    clusters = cluster_claims_for_company(all_claims)

    # Build result: position of each new claim in its cluster
    positions: dict[int, int] = {}
    for claim in new_claims:
        for cluster in clusters:
            if claim.id in cluster.member_claim_ids:
                pos = cluster.member_claim_ids.index(claim.id) + 1
                positions[claim.id] = pos

                # Set event_cluster_id on the claim if it has the field
                if hasattr(claim, 'event_cluster_id'):
                    cluster.company_ticker = company_ticker
                    claim.event_cluster_id = cluster.cluster_id
                break
        else:
            positions[claim.id] = 1  # no cluster match = independent

    return positions
