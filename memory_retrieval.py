"""Temporal memory retrieval: build a compact memory snapshot for thesis updates.

Retrieval policy (v1 contract):
  Priority 1: Thesis-linked claims (via thesis_claim_links)        — limit 10
  Priority 2: Same-company claims (via claim_company_links)        — limit 5
  Priority 3: Same-theme claims (via claim_theme_links)            — limit 5
  Priority 4: Upcoming checkpoints                                 — limit 3
  Also: State history                                              — limit 5

  Total memory budget: ≤28 items per thesis update (hard ceiling).

Determinism guarantee:
  All queries use ORDER BY published_at DESC NULLS LAST, id DESC for
  tie-breaking. For the same DB state and thesis_id, retrieve_memory()
  always returns identical results.

Exclusion rules:
  - Claims in the "new batch" (exclude_claim_ids) are never retrieved
  - Claims already fetched at a higher priority level are excluded from lower levels
  - This prevents double-counting in the memory snapshot
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import (
    Checkpoint,
    Claim,
    ClaimCompanyLink,
    ClaimThemeLink,
    Document,
    Thesis,
    ThesisClaimLink,
    ThesisStateHistory,
    ThesisThemeLink,
)


# ---------------------------------------------------------------------------
# Snapshot data structures
# ---------------------------------------------------------------------------

@dataclass
class MemoryClaim:
    """A single claim in the memory snapshot."""
    claim_id: int
    claim_text_short: str
    claim_type: str
    direction: str
    strength: float
    novelty_type: str
    source_tier: str
    published_at: Optional[datetime]
    retrieval_source: str  # "thesis_linked", "company", "theme"
    thesis_link_type: Optional[str] = None  # "supports", "weakens", etc.


@dataclass
class StateHistoryEntry:
    """One row from thesis_state_history."""
    state: str
    conviction_score: Optional[float]
    note: Optional[str]
    created_at: datetime


@dataclass
class CheckpointEntry:
    """An upcoming checkpoint for the thesis company."""
    name: str
    checkpoint_type: str
    date_expected: Optional[date]
    importance: Optional[float]


@dataclass
class MemorySnapshot:
    """Complete memory context for a thesis update."""
    thesis_id: int
    company_ticker: str
    thesis_title: str
    current_state: str
    current_conviction: float

    state_history: list[StateHistoryEntry] = field(default_factory=list)
    thesis_claims: list[MemoryClaim] = field(default_factory=list)
    company_claims: list[MemoryClaim] = field(default_factory=list)
    theme_claims: list[MemoryClaim] = field(default_factory=list)
    checkpoints: list[CheckpointEntry] = field(default_factory=list)

    @property
    def total_prior_claims(self) -> int:
        return len(self.thesis_claims) + len(self.company_claims) + len(self.theme_claims)

    def retrieval_policy_summary(self) -> dict:
        """Return a machine-readable summary of what was retrieved and why.

        Useful for console/audit display to explain why certain memory was pulled in.
        """
        return {
            "thesis_id": self.thesis_id,
            "company_ticker": self.company_ticker,
            "total_items": self.total_prior_claims + len(self.state_history) + len(self.checkpoints),
            "thesis_claims_count": len(self.thesis_claims),
            "company_claims_count": len(self.company_claims),
            "theme_claims_count": len(self.theme_claims),
            "state_history_count": len(self.state_history),
            "checkpoints_count": len(self.checkpoints),
            "policy": "priority: thesis_linked > company > theme; ordered by published_at DESC, id DESC",
        }

    def to_prompt_text(self) -> str:
        """Format the snapshot as structured text for inclusion in the LLM prompt."""
        lines: list[str] = []

        # State history
        if self.state_history:
            lines.append("## Recent thesis state history")
            for h in self.state_history:
                ts = h.created_at.strftime("%Y-%m-%d %H:%M") if h.created_at else "?"
                score_str = f"{h.conviction_score:.1f}" if h.conviction_score is not None else "?"
                note_str = f" — {h.note}" if h.note else ""
                lines.append(f"- [{ts}] state={h.state}, conviction={score_str}{note_str}")

        # Thesis-linked claims
        if self.thesis_claims:
            lines.append("\n## Prior claims linked to this thesis")
            for c in self.thesis_claims:
                lines.append(_format_memory_claim(c))

        # Company claims
        if self.company_claims:
            lines.append("\n## Other recent claims for {ticker}".format(
                ticker=self.company_ticker))
            for c in self.company_claims:
                lines.append(_format_memory_claim(c))

        # Theme claims
        if self.theme_claims:
            lines.append("\n## Related theme claims")
            for c in self.theme_claims:
                lines.append(_format_memory_claim(c))

        # Checkpoints
        if self.checkpoints:
            lines.append("\n## Upcoming checkpoints")
            for cp in self.checkpoints:
                dt = str(cp.date_expected) if cp.date_expected else "TBD"
                imp = f"{cp.importance:.1f}" if cp.importance is not None else "?"
                lines.append(f"- {cp.name} ({cp.checkpoint_type}), expected={dt}, importance={imp}")

        if not lines:
            return "(No prior memory available for this thesis.)"

        return "\n".join(lines)


def _format_memory_claim(c: MemoryClaim) -> str:
    """Format one MemoryClaim as a bullet line."""
    ts = c.published_at.strftime("%Y-%m-%d") if c.published_at else "?"
    link_str = f", link={c.thesis_link_type}" if c.thesis_link_type else ""
    return (
        f"- [{ts}] \"{c.claim_text_short}\" "
        f"type={c.claim_type}, dir={c.direction}, "
        f"strength={c.strength:.2f}, novelty={c.novelty_type}, "
        f"tier={c.source_tier}{link_str}"
    )


# ---------------------------------------------------------------------------
# Default retrieval limits
# ---------------------------------------------------------------------------

DEFAULT_THESIS_CLAIMS_LIMIT = 10
DEFAULT_COMPANY_CLAIMS_LIMIT = 5
DEFAULT_THEME_CLAIMS_LIMIT = 5
DEFAULT_HISTORY_LIMIT = 5
DEFAULT_CHECKPOINT_LIMIT = 3


# ---------------------------------------------------------------------------
# Core retrieval function
# ---------------------------------------------------------------------------

def retrieve_memory(
    session: Session,
    thesis_id: int,
    *,
    thesis_claims_limit: int = DEFAULT_THESIS_CLAIMS_LIMIT,
    company_claims_limit: int = DEFAULT_COMPANY_CLAIMS_LIMIT,
    theme_claims_limit: int = DEFAULT_THEME_CLAIMS_LIMIT,
    history_limit: int = DEFAULT_HISTORY_LIMIT,
    checkpoint_limit: int = DEFAULT_CHECKPOINT_LIMIT,
    exclude_claim_ids: list[int] | None = None,
) -> MemorySnapshot:
    """Build a MemorySnapshot for a thesis.

    Args:
        session: SQLAlchemy session.
        thesis_id: The thesis to retrieve memory for.
        thesis_claims_limit: Max thesis-linked claims to return.
        company_claims_limit: Max same-company claims (not already thesis-linked).
        theme_claims_limit: Max same-theme claims (not already fetched).
        history_limit: Max thesis state history rows.
        checkpoint_limit: Max upcoming checkpoints.
        exclude_claim_ids: Claim IDs to exclude (e.g., the new claims being assessed).

    Returns:
        MemorySnapshot with bounded, prioritized prior context.
    """
    thesis = session.get(Thesis, thesis_id)
    if not thesis:
        raise ValueError(f"Thesis {thesis_id} not found")

    exclude = set(exclude_claim_ids or [])

    # 1. State history (most recent first)
    state_history = _fetch_state_history(session, thesis_id, history_limit)

    # 2. Thesis-linked claims (priority 1)
    thesis_claims, thesis_claim_ids = _fetch_thesis_claims(
        session, thesis_id, thesis_claims_limit, exclude
    )
    seen_ids = exclude | thesis_claim_ids

    # 3. Same-company claims (priority 2)
    company_claims, company_claim_ids = _fetch_company_claims(
        session, thesis.company_ticker, company_claims_limit, seen_ids
    )
    seen_ids |= company_claim_ids

    # 4. Theme-linked claims (priority 3)
    theme_claims = _fetch_theme_claims(
        session, thesis_id, theme_claims_limit, seen_ids
    )

    # 5. Upcoming checkpoints
    checkpoints = _fetch_checkpoints(
        session, thesis.company_ticker, checkpoint_limit
    )

    return MemorySnapshot(
        thesis_id=thesis.id,
        company_ticker=thesis.company_ticker,
        thesis_title=thesis.title,
        current_state=thesis.state.value,
        current_conviction=thesis.conviction_score or 50.0,
        state_history=state_history,
        thesis_claims=thesis_claims,
        company_claims=company_claims,
        theme_claims=theme_claims,
        checkpoints=checkpoints,
    )


# ---------------------------------------------------------------------------
# Private fetch helpers
# ---------------------------------------------------------------------------

def _fetch_state_history(
    session: Session,
    thesis_id: int,
    limit: int,
) -> list[StateHistoryEntry]:
    rows = session.scalars(
        select(ThesisStateHistory)
        .where(ThesisStateHistory.thesis_id == thesis_id)
        .order_by(ThesisStateHistory.created_at.desc(), ThesisStateHistory.id.desc())
        .limit(limit)
    ).all()
    return [
        StateHistoryEntry(
            state=r.state.value,
            conviction_score=r.conviction_score,
            note=r.note,
            created_at=r.created_at,
        )
        for r in rows
    ]


def _fetch_thesis_claims(
    session: Session,
    thesis_id: int,
    limit: int,
    exclude: set[int],
) -> tuple[list[MemoryClaim], set[int]]:
    """Fetch claims directly linked to the thesis."""
    stmt = (
        select(Claim, ThesisClaimLink.link_type, Document.source_tier)
        .join(ThesisClaimLink, ThesisClaimLink.claim_id == Claim.id)
        .join(Document, Document.id == Claim.document_id)
        .where(ThesisClaimLink.thesis_id == thesis_id)
    )
    if exclude:
        stmt = stmt.where(Claim.id.notin_(exclude))
    stmt = stmt.order_by(Claim.published_at.desc().nulls_last(), Claim.id.desc()).limit(limit)

    rows = session.execute(stmt).all()
    claims = []
    ids = set()
    for claim, link_type, source_tier in rows:
        ids.add(claim.id)
        claims.append(_to_memory_claim(
            claim, source_tier, "thesis_linked", thesis_link_type=link_type
        ))
    return claims, ids


def _fetch_company_claims(
    session: Session,
    company_ticker: str,
    limit: int,
    exclude: set[int],
) -> tuple[list[MemoryClaim], set[int]]:
    """Fetch claims linked to the same company (not already thesis-linked)."""
    stmt = (
        select(Claim, Document.source_tier)
        .join(ClaimCompanyLink, ClaimCompanyLink.claim_id == Claim.id)
        .join(Document, Document.id == Claim.document_id)
        .where(ClaimCompanyLink.company_ticker == company_ticker)
    )
    if exclude:
        stmt = stmt.where(Claim.id.notin_(exclude))
    stmt = stmt.order_by(Claim.published_at.desc().nulls_last(), Claim.id.desc()).limit(limit)

    rows = session.execute(stmt).all()
    claims = []
    ids = set()
    for claim, source_tier in rows:
        ids.add(claim.id)
        claims.append(_to_memory_claim(claim, source_tier, "company"))
    return claims, ids


def _fetch_theme_claims(
    session: Session,
    thesis_id: int,
    limit: int,
    exclude: set[int],
) -> list[MemoryClaim]:
    """Fetch claims sharing themes with the thesis (not already fetched)."""
    # First get the thesis's theme IDs
    theme_ids = session.scalars(
        select(ThesisThemeLink.theme_id)
        .where(ThesisThemeLink.thesis_id == thesis_id)
    ).all()

    if not theme_ids:
        return []

    stmt = (
        select(Claim, Document.source_tier)
        .join(ClaimThemeLink, ClaimThemeLink.claim_id == Claim.id)
        .join(Document, Document.id == Claim.document_id)
        .where(ClaimThemeLink.theme_id.in_(theme_ids))
    )
    if exclude:
        stmt = stmt.where(Claim.id.notin_(exclude))
    stmt = (
        stmt.group_by(Claim.id, Document.source_tier)
        .order_by(Claim.published_at.desc().nulls_last(), Claim.id.desc())
        .limit(limit)
    )

    rows = session.execute(stmt).all()
    return [_to_memory_claim(claim, source_tier, "theme") for claim, source_tier in rows]


def _fetch_checkpoints(
    session: Session,
    company_ticker: str,
    limit: int,
) -> list[CheckpointEntry]:
    """Fetch upcoming checkpoints for the company."""
    stmt = (
        select(Checkpoint)
        .where(Checkpoint.linked_company_ticker == company_ticker)
        .order_by(Checkpoint.date_expected.asc().nulls_last(), Checkpoint.id.asc())
        .limit(limit)
    )
    rows = session.scalars(stmt).all()
    return [
        CheckpointEntry(
            name=r.name,
            checkpoint_type=r.checkpoint_type,
            date_expected=r.date_expected,
            importance=r.importance,
        )
        for r in rows
    ]


def _to_memory_claim(
    claim: Claim,
    source_tier,
    retrieval_source: str,
    thesis_link_type: str | None = None,
) -> MemoryClaim:
    """Convert a Claim ORM object to a MemoryClaim dataclass."""
    tier_str = source_tier.value if hasattr(source_tier, "value") else str(source_tier)
    return MemoryClaim(
        claim_id=claim.id,
        claim_text_short=claim.claim_text_short or claim.claim_text_normalized[:60],
        claim_type=claim.claim_type.value,
        direction=claim.direction.value,
        strength=claim.strength or 0.5,
        novelty_type=claim.novelty_type.value,
        source_tier=tier_str,
        published_at=claim.published_at,
        retrieval_source=retrieval_source,
        thesis_link_type=thesis_link_type,
    )
