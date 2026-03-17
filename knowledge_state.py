"""Unified knowledge state layer: prior context reads + cross-ticker propagation.

This module is the single interface for:
  1. **Read path** — "what do we already know about ticker X?" (delegates to prior_context.py)
  2. **Write path** — "propagate this claim's impact to related tickers"

Propagation happens via two channels:
  - **Direct relationships** (CompanyRelationship): TSMC supply issue → NVDA
  - **Tag overlap** (CompanyTagLink via Theme): "tech tariff" → all companies tagged "tech"

Derived signals are written to the DerivedSignal table and become part of
"what we already know" for target tickers on their next thesis update.

The graph (NetworkX ConsensusGraph) is used for fast traversal; SQL is the
source of truth.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models import (
    Claim,
    ClaimCompanyLink,
    ClaimThemeLink,
    Company,
    CompanyRelationship,
    CompanyTagLink,
    DerivedSignal,
    Direction,
    RelationshipType,
    Theme,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Attenuation matrices
# ---------------------------------------------------------------------------

# Direct relationship attenuation: how much of the signal survives propagation.
#
# KEY INSIGHT: Signal value depends on WHO is the source.
# Relationships are stored as: source_ticker --[type]--> target_ticker
#   e.g., NVDA --[supplier]--> MSFT  ("NVDA supplies GPUs to MSFT")
#
# When the SOURCE (NVDA) reports news, the signal flows to the TARGET (MSFT).
# But when MSFT reports capex news, it flows back to NVDA (if bidirectional or
# via the reverse lookup).
#
# FORWARD attenuation (source reports, target receives):
#   - Supplier→Customer: WEAK. Supplier's strong revenue is lagging — customers
#     already spent the money. Exception: supply disruptions DO hurt customers.
#   - Customer→Supplier: STRONG. Customer capex = forward demand signal for supplier.
#
# REVERSE attenuation (target reports, source receives via bidirectional lookup):
#   Same logic applies based on who's reporting.
#
# We handle this by splitting attenuation based on propagation direction:
#   "forward" = source_ticker is the reporter, signal goes to target_ticker
#   "reverse" = target_ticker is the reporter, signal goes to source_ticker

# Forward: when source_ticker reports, what does target_ticker feel?
FORWARD_ATTENUATION = {
    #                    Supplier reports → Customer feels:
    #                    (NVDA reports → MSFT feels)
    RelationshipType.SUPPLIER: {"positive": 0.15, "negative": 0.50, "mixed": 0.15, "neutral": 0.0},
    #                    Customer reports → Supplier feels:
    #                    (MSFT reports → NVDA feels)
    RelationshipType.CUSTOMER: {"positive": 0.55, "negative": 0.55, "mixed": 0.35, "neutral": 0.0},
    RelationshipType.COMPETITOR: {"positive": 0.30, "negative": 0.25, "mixed": 0.15, "neutral": 0.0},
    RelationshipType.ECOSYSTEM: {"positive": 0.25, "negative": 0.25, "mixed": 0.15, "neutral": 0.0},
}

# Reverse: when target_ticker reports, what does source_ticker feel?
# This is the inverse role: if NVDA--[supplier]-->MSFT, and MSFT reports,
# NVDA is the supplier receiving a customer's signal.
REVERSE_ATTENUATION = {
    #                    Customer (MSFT) reports → Supplier (NVDA) feels:
    RelationshipType.SUPPLIER: {"positive": 0.55, "negative": 0.55, "mixed": 0.35, "neutral": 0.0},
    #                    Supplier reports → Customer feels:
    RelationshipType.CUSTOMER: {"positive": 0.15, "negative": 0.50, "mixed": 0.15, "neutral": 0.0},
    RelationshipType.COMPETITOR: {"positive": 0.30, "negative": 0.25, "mixed": 0.15, "neutral": 0.0},
    RelationshipType.ECOSYSTEM: {"positive": 0.25, "negative": 0.25, "mixed": 0.15, "neutral": 0.0},
}

# Tag-based propagation: weaker than direct, scaled by tag weight on both sides.
TAG_BASE_ATTENUATION = 0.20  # base factor, multiplied by source_weight * target_weight

# Minimum claim strength to propagate (don't propagate noise)
MIN_PROPAGATION_STRENGTH = 0.5

# Minimum attenuation to create a derived signal (skip negligible impacts)
MIN_DERIVED_STRENGTH = 0.05


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ImpactedTicker:
    """A ticker impacted by cross-ticker propagation."""
    ticker: str
    propagation_type: str           # "direct" or "tag"
    relationship_type: str          # supplier/customer/competitor/ecosystem or tag name
    attenuation_factor: float       # 0-1
    derived_direction: Direction
    derived_strength: float         # original strength * attenuation
    rationale: str


# ---------------------------------------------------------------------------
# Read path: what do we already know?
# ---------------------------------------------------------------------------

def get_prior_context(
    session: Session,
    claims: list[Claim],
    ticker: str,
    thesis_id: Optional[int] = None,
    reference_date: Optional[datetime] = None,
) -> str:
    """Get prior expectation context for a ticker.

    Combines three context sources:
      1. SQL prior context (arithmetic: consensus, guidance, same-type comparisons)
      2. SQL derived signals (cross-ticker propagated impacts)
      3. Graphiti knowledge graph (relationship facts from Neo4j)
    """
    from prior_context import build_prior_context

    # 1. Core prior context (consensus, guidance, same-type priors)
    ctx = build_prior_context(session, claims, ticker, thesis_id=thesis_id,
                              reference_date=reference_date)

    # 2. Unconsumed derived signals from cross-ticker propagation (SQL)
    derived_ctx = _format_derived_signals(session, ticker)
    if derived_ctx:
        ctx = ctx + "\n\n" + derived_ctx if ctx else derived_ctx

    # 3. Knowledge graph context from Graphiti/Neo4j
    graph_ctx = _get_graphiti_context(ticker)
    if graph_ctx:
        ctx = ctx + "\n\n" + graph_ctx if ctx else graph_ctx

    # 4. Graph-powered contradiction detection: find conflicting signals
    #    from connected companies (e.g., NVDA says "demand incredible" but
    #    TSMC says "capacity utilization declining")
    contradiction_ctx = _detect_neighbor_contradictions(session, claims, ticker)
    if contradiction_ctx:
        ctx = ctx + "\n\n" + contradiction_ctx if ctx else contradiction_ctx

    return ctx


def _get_graphiti_context(ticker: str) -> str:
    """Query Graphiti/Neo4j for relationship facts about this ticker.

    Returns formatted context string, or empty string if Graphiti is
    not configured or no data found.
    """
    try:
        from graphiti_adapter import get_company_context
        return get_company_context(ticker)
    except Exception as e:
        logger.debug("Graphiti context unavailable for %s: %s", ticker, e)
        return ""


def _format_derived_signals(session: Session, ticker: str) -> str:
    """Format unconsumed derived signals for this ticker as context text."""
    stmt = (
        select(DerivedSignal)
        .where(
            DerivedSignal.target_ticker == ticker,
            DerivedSignal.consumed == False,  # noqa: E712
        )
        .order_by(DerivedSignal.created_at.desc())
        .limit(10)
    )
    signals = list(session.scalars(stmt).all())
    if not signals:
        return ""

    lines = ["## Cross-ticker signals (unconsumed)"]
    for s in signals:
        direction = s.derived_direction.value if hasattr(s.derived_direction, "value") else str(s.derived_direction)
        lines.append(
            f"- [{s.source_ticker} → {s.target_ticker}] "
            f"{s.propagation_type}/{s.relationship_type}: "
            f"dir={direction}, strength={s.derived_strength:.2f} — {s.rationale or 'no rationale'}"
        )
    return "\n".join(lines)


def _detect_neighbor_contradictions(
    session: Session,
    new_claims: list[Claim],
    ticker: str,
) -> str:
    """Detect contradictions between new claims and recent claims from connected companies.

    Uses the CompanyRelationship graph to find neighbors, then compares claim
    directions. If NVDA says "demand is incredible" (positive) but connected
    TSMC recently said "capacity utilization declining" (negative), that's a
    red flag the LLM should weigh.

    Returns formatted context string, or empty string if no contradictions.
    """
    if not new_claims:
        return ""

    # Get 1-hop neighbors from CompanyRelationship
    stmt = select(CompanyRelationship).where(
        (CompanyRelationship.source_ticker == ticker) |
        (
            (CompanyRelationship.target_ticker == ticker) &
            (CompanyRelationship.bidirectional == True)  # noqa: E712
        )
    )
    relationships = list(session.scalars(stmt).all())
    if not relationships:
        return ""

    # Map neighbor ticker → relationship description
    neighbor_info: dict[str, str] = {}
    for rel in relationships:
        if rel.source_ticker == ticker:
            neighbor_info[rel.target_ticker] = f"{rel.relationship_type.value} ({rel.description or ''})"
        else:
            neighbor_info[rel.source_ticker] = f"{rel.relationship_type.value} ({rel.description or ''})"

    if not neighbor_info:
        return ""

    # Determine the dominant direction of new claims
    pos = sum(1 for c in new_claims if hasattr(c.direction, 'value') and c.direction.value == "positive")
    neg = sum(1 for c in new_claims if hasattr(c.direction, 'value') and c.direction.value == "negative")
    if pos == neg == 0:
        return ""
    new_direction = "positive" if pos > neg else "negative" if neg > pos else "mixed"

    # Query recent strong claims from neighbors (last 30 days)
    from datetime import timedelta
    cutoff = datetime.utcnow() - timedelta(days=30)
    neighbor_tickers = list(neighbor_info.keys())

    neighbor_claims_stmt = (
        select(Claim, ClaimCompanyLink.company_ticker)
        .join(ClaimCompanyLink, ClaimCompanyLink.claim_id == Claim.id)
        .where(
            ClaimCompanyLink.company_ticker.in_(neighbor_tickers),
            Claim.published_at >= cutoff,
            Claim.strength >= 0.5,
        )
        .order_by(Claim.published_at.desc())
        .limit(50)
    )
    rows = session.execute(neighbor_claims_stmt).all()

    if not rows:
        return ""

    # Find contradictions: neighbor claims with opposite direction
    contradictions = []
    for claim, neighbor_ticker in rows:
        claim_dir = claim.direction.value if hasattr(claim.direction, 'value') else str(claim.direction)
        # Contradiction: our claims are positive but neighbor's are negative (or vice versa)
        is_contradiction = (
            (new_direction == "positive" and claim_dir == "negative") or
            (new_direction == "negative" and claim_dir == "positive")
        )
        if is_contradiction and (claim.strength or 0) >= 0.5:
            contradictions.append({
                "neighbor": neighbor_ticker,
                "relationship": neighbor_info.get(neighbor_ticker, "related"),
                "claim_text": claim.claim_text_short or claim.claim_text_normalized or "",
                "direction": claim_dir,
                "strength": claim.strength or 0,
                "date": claim.published_at,
            })

    if not contradictions:
        return ""

    # Format top contradictions (max 5)
    contradictions.sort(key=lambda x: x["strength"], reverse=True)
    lines = [
        f"## Contradictory signals from connected companies",
        f"New {ticker} claims are predominantly {new_direction}, but connected companies show conflicting signals:",
    ]
    for c in contradictions[:5]:
        date_str = c["date"].strftime("%Y-%m-%d") if c["date"] else "?"
        lines.append(
            f"- **{c['neighbor']}** ({c['relationship']}): "
            f"\"{c['claim_text'][:120]}\" — {c['direction']}, "
            f"strength={c['strength']:.1f} [{date_str}]"
        )
    lines.append(
        "\nWeigh these contradictions when assessing conviction. "
        "Supply chain or customer signals that conflict with the company's "
        "own narrative may indicate risk not yet priced in."
    )
    return "\n".join(lines)


def mark_signals_consumed(session: Session, ticker: str) -> int:
    """Mark all unconsumed derived signals for this ticker as consumed.

    Called after thesis update has incorporated the signals.
    Returns count of signals consumed.
    """
    stmt = (
        select(DerivedSignal)
        .where(
            DerivedSignal.target_ticker == ticker,
            DerivedSignal.consumed == False,  # noqa: E712
        )
    )
    signals = list(session.scalars(stmt).all())
    now = datetime.utcnow()
    for s in signals:
        s.consumed = True
        s.consumed_at = now
    return len(signals)


# ---------------------------------------------------------------------------
# Write path: propagate signals to related tickers
# ---------------------------------------------------------------------------

def propagate_claims(
    session: Session,
    claims: list[Claim],
    source_ticker: str,
) -> list[DerivedSignal]:
    """Propagate claims from source_ticker to related tickers.

    Two propagation channels:
      1. Direct relationships (CompanyRelationship table)
      2. Tag overlap (CompanyTagLink via shared Theme tags)

    Returns list of DerivedSignal rows created (already added to session).
    """
    if not claims:
        return []

    # Filter: only propagate claims with meaningful strength.
    # Novelty filter: "confirming" claims still propagate — a claim that confirms
    # NVDA's trend is still news for MSFT. Only skip "repetitive" (pure duplicate)
    # and "neutral" novelty.
    strong_claims = [
        c for c in claims
        if (c.strength or 0) >= MIN_PROPAGATION_STRENGTH
        and c.novelty_type.value not in ("repetitive",)
    ]
    if not strong_claims:
        return []

    # Get affected tickers from claims (to avoid double-propagation)
    claim_ids = [c.id for c in strong_claims]
    directly_mentioned = _get_directly_mentioned_tickers(session, claim_ids)

    signals: list[DerivedSignal] = []
    # Track which target tickers have been reached — ONLY the strongest
    # signal per target survives. This prevents NVDA → AMD being counted
    # 3 times via direct + tag + graph channels.
    reached_targets: dict[str, DerivedSignal] = {}

    # Channel 1: Direct relationships (1-hop SQL) — highest priority
    direct_signals = _propagate_direct(session, strong_claims, source_ticker, directly_mentioned)
    for sig in direct_signals:
        existing = reached_targets.get(sig.target_ticker)
        if not existing or sig.derived_strength > existing.derived_strength:
            reached_targets[sig.target_ticker] = sig

    # Channel 2: Tag-based propagation — only if target not already reached
    already_reached = directly_mentioned | {source_ticker} | set(reached_targets.keys())
    tag_signals = _propagate_tags(session, strong_claims, source_ticker, already_reached)
    for sig in tag_signals:
        if sig.target_ticker not in reached_targets:
            reached_targets[sig.target_ticker] = sig

    # Channel 3: Multi-hop graph traversal (2nd-degree impacts)
    # Only finds targets NOT already reached by Channel 1 or 2.
    hop2_signals = _propagate_via_graph(
        session, strong_claims, source_ticker, directly_mentioned,
        list(reached_targets.values()),
    )
    for sig in hop2_signals:
        if sig.target_ticker not in reached_targets:
            reached_targets[sig.target_ticker] = sig

    # Deduplicated signal list — exactly ONE signal per target ticker
    signals = list(reached_targets.values())

    # Count by channel for logging
    n_direct = sum(1 for s in signals if s.propagation_type == "direct")
    n_tag = sum(1 for s in signals if s.propagation_type == "tag")
    n_graph = sum(1 for s in signals if s.propagation_type == "graph_2hop")

    # Persist SQL derived signals
    for s in signals:
        session.add(s)

    if signals:
        logger.info(
            "Propagated %d signals from %s (%d direct, %d tag, %d graph-2hop)",
            len(signals), source_ticker, n_direct, n_tag, n_graph,
        )

    # Channel 3: Ingest claims into Graphiti/Neo4j for relationship discovery
    _ingest_to_graphiti(claims, source_ticker)

    return signals


def _ingest_to_graphiti(claims: list[Claim], source_ticker: str) -> None:
    """Best-effort ingestion of claims into Graphiti knowledge graph.

    Non-blocking: failures are logged but don't affect SQL propagation.
    """
    try:
        from graphiti_adapter import ingest_claims_to_graph
        claim_texts = [
            c.claim_text_normalized or c.claim_text_short or ""
            for c in claims if c.claim_text_normalized or c.claim_text_short
        ]
        if not claim_texts:
            return
        doc = claims[0].document
        title = doc.title if doc else f"{source_ticker} claims"
        pub_date = claims[0].published_at or datetime.utcnow()
        result = ingest_claims_to_graph(claim_texts, source_ticker, title, pub_date)
        logger.info(
            "Graphiti ingested %s: %d entities, %d edges",
            source_ticker, result["entities_extracted"], result["edges_extracted"],
        )
    except Exception as e:
        logger.debug("Graphiti ingestion skipped for %s: %s", source_ticker, e)


def _get_directly_mentioned_tickers(session: Session, claim_ids: list[int]) -> set[str]:
    """Get tickers that are directly mentioned in these claims (via ClaimCompanyLink)."""
    if not claim_ids:
        return set()
    stmt = select(ClaimCompanyLink.company_ticker).where(
        ClaimCompanyLink.claim_id.in_(claim_ids)
    )
    return set(session.scalars(stmt).all())


# ---------------------------------------------------------------------------
# Channel 1: Direct relationship propagation
# ---------------------------------------------------------------------------

def _propagate_direct(
    session: Session,
    claims: list[Claim],
    source_ticker: str,
    skip_tickers: set[str],
) -> list[DerivedSignal]:
    """Propagate via CompanyRelationship edges.

    IMPORTANT: Aggregates all claims into ONE signal per target ticker per
    relationship. 18 claims from one NVDA earnings report produce ONE derived
    signal for MSFT, not 18 — because they're all from the same event.

    The aggregated signal uses:
      - Direction: majority vote (positive if more positive claims than negative)
      - Strength: attenuated average of top-3 claims (not sum of all)
    """
    # Find all relationships where source_ticker is involved
    stmt = select(CompanyRelationship).where(
        (CompanyRelationship.source_ticker == source_ticker) |
        (
            (CompanyRelationship.target_ticker == source_ticker) &
            (CompanyRelationship.bidirectional == True)  # noqa: E712
        )
    )
    relationships = list(session.scalars(stmt).all())
    if not relationships:
        return []

    signals = []
    for rel in relationships:
        # Determine target ticker and propagation direction
        if rel.source_ticker == source_ticker:
            target = rel.target_ticker
            is_forward = True
        else:
            target = rel.source_ticker
            is_forward = False

        if target in skip_tickers:
            continue

        signal = _create_aggregated_signal(claims, source_ticker, target, rel, is_forward)
        if signal:
            signals.append(signal)

    return signals


def _create_aggregated_signal(
    claims: list[Claim],
    source_ticker: str,
    target_ticker: str,
    rel: CompanyRelationship,
    is_forward: bool = True,
) -> Optional[DerivedSignal]:
    """Create ONE aggregated signal from all claims for a single relationship.

    Instead of creating 18 signals (one per claim), we aggregate:
      - Direction: majority vote across claims
      - Strength: average of top-3 strongest claims, then attenuated
      - Rationale: summary of the claim batch

    This prevents a single earnings report from creating outsized conviction
    swings through sheer volume of claims.
    """
    rel_type = rel.relationship_type

    # Pick attenuation table based on propagation direction
    att_table = FORWARD_ATTENUATION if is_forward else REVERSE_ATTENUATION
    attenuation_map = att_table.get(rel_type, {})

    # Tally direction votes and collect strengths per direction
    direction_strengths: dict[str, list[float]] = {}
    for claim in claims:
        direction = claim.direction.value if hasattr(claim.direction, "value") else str(claim.direction)
        strength = claim.strength or 0.5
        direction_strengths.setdefault(direction, []).append(strength)

    # Find dominant direction (by count, then by total strength as tiebreaker)
    best_dir = max(
        direction_strengths.keys(),
        key=lambda d: (len(direction_strengths[d]), sum(direction_strengths[d])),
    )

    base_attenuation = attenuation_map.get(best_dir, 0.0)
    if base_attenuation == 0.0:
        return None

    # Aggregate strength: average of top-3 claims in the dominant direction
    top_strengths = sorted(direction_strengths[best_dir], reverse=True)[:3]
    avg_strength = sum(top_strengths) / len(top_strengths)

    # Scale by relationship strength
    attenuation = base_attenuation * rel.strength
    derived_strength = avg_strength * attenuation

    if derived_strength < MIN_DERIVED_STRENGTH:
        return None

    # Determine derived direction
    if rel_type == RelationshipType.COMPETITOR:
        derived_dir = _flip_direction(Direction(best_dir))
    else:
        derived_dir = Direction(best_dir)

    # Use the strongest claim's ID as the representative source
    representative_claim = max(claims, key=lambda c: c.strength or 0)

    direction_label = "forward" if is_forward else "reverse"
    total_claims = len(claims)
    dominant_count = len(direction_strengths[best_dir])
    rationale = (
        f"{source_ticker} batch ({total_claims} claims, {dominant_count} {best_dir}) "
        f"propagated {direction_label} via {rel_type.value} to {target_ticker} "
        f"(top3_avg={avg_strength:.2f}, rel_str={rel.strength:.2f}, att={attenuation:.3f})"
    )

    return DerivedSignal(
        source_claim_id=representative_claim.id,
        source_ticker=source_ticker,
        target_ticker=target_ticker,
        propagation_type="direct",
        relationship_type=rel_type.value,
        attenuation_factor=round(attenuation, 4),
        derived_direction=derived_dir,
        derived_strength=round(derived_strength, 4),
        rationale=rationale,
    )


# ---------------------------------------------------------------------------
# Channel 2: Tag-based propagation
# ---------------------------------------------------------------------------

def _propagate_tags(
    session: Session,
    claims: list[Claim],
    source_ticker: str,
    skip_tickers: set[str],
) -> list[DerivedSignal]:
    """Propagate via shared thematic tags (CompanyTagLink + ClaimThemeLink)."""
    # Get claim IDs and their theme links
    claim_ids = [c.id for c in claims]
    claim_theme_stmt = select(ClaimThemeLink).where(ClaimThemeLink.claim_id.in_(claim_ids))
    claim_theme_links = list(session.scalars(claim_theme_stmt).all())

    if not claim_theme_links:
        return []

    # Map claim_id -> theme_ids
    claim_themes: dict[int, set[int]] = {}
    for link in claim_theme_links:
        claim_themes.setdefault(link.claim_id, set()).add(link.theme_id)

    # Get all unique theme IDs
    all_theme_ids = set()
    for tids in claim_themes.values():
        all_theme_ids.update(tids)

    if not all_theme_ids:
        return []

    # Get source company's tag weights for these themes
    source_tag_stmt = select(CompanyTagLink).where(
        CompanyTagLink.company_ticker == source_ticker,
        CompanyTagLink.theme_id.in_(all_theme_ids),
    )
    source_tags = {t.theme_id: t.weight for t in session.scalars(source_tag_stmt).all()}

    # Find other companies with these tags
    target_tag_stmt = select(CompanyTagLink).where(
        CompanyTagLink.theme_id.in_(all_theme_ids),
        CompanyTagLink.company_ticker != source_ticker,
    )
    target_tags_raw = list(session.scalars(target_tag_stmt).all())

    # Group by (company, theme)
    target_tags: dict[str, dict[int, float]] = {}
    for t in target_tags_raw:
        target_tags.setdefault(t.company_ticker, {})[t.theme_id] = t.weight

    # Get theme names for rationale
    theme_names: dict[int, str] = {}
    if all_theme_ids:
        for theme in session.scalars(select(Theme).where(Theme.id.in_(all_theme_ids))).all():
            theme_names[theme.id] = theme.theme_name

    # Aggregate: ONE signal per target ticker (not per claim×target)
    # For each target, find the best overlapping tag and aggregate claim strengths
    signals = []

    for target_ticker, target_theme_weights in target_tags.items():
        if target_ticker in skip_tickers:
            continue

        # Find best overlapping tag across all claims
        best_attenuation = 0.0
        best_tag_name = ""
        for claim in claims:
            c_themes = claim_themes.get(claim.id, set())
            for theme_id in c_themes:
                if theme_id not in target_theme_weights:
                    continue
                source_w = source_tags.get(theme_id, 0.0)
                target_w = target_theme_weights[theme_id]
                attenuation = TAG_BASE_ATTENUATION * source_w * target_w
                if attenuation > best_attenuation:
                    best_attenuation = attenuation
                    best_tag_name = theme_names.get(theme_id, f"theme_{theme_id}")

        if best_attenuation < 0.01:
            continue

        # Aggregate claim strengths: top-3 average like direct propagation
        claim_strengths = sorted(
            [(c.strength or 0.5) for c in claims if claim_themes.get(c.id, set())],
            reverse=True,
        )[:3]
        if not claim_strengths:
            continue
        avg_strength = sum(claim_strengths) / len(claim_strengths)

        derived_strength = avg_strength * best_attenuation
        if derived_strength < MIN_DERIVED_STRENGTH:
            continue

        # Direction: majority vote
        dir_counts: dict[str, int] = {}
        for c in claims:
            d = c.direction.value if hasattr(c.direction, "value") else str(c.direction)
            dir_counts[d] = dir_counts.get(d, 0) + 1
        best_dir = max(dir_counts, key=lambda d: dir_counts[d])

        representative_claim = max(claims, key=lambda c: c.strength or 0)

        signals.append(DerivedSignal(
            source_claim_id=representative_claim.id,
            source_ticker=source_ticker,
            target_ticker=target_ticker,
            propagation_type="tag",
            relationship_type=best_tag_name,
            attenuation_factor=round(best_attenuation, 4),
            derived_direction=Direction(best_dir),
            derived_strength=round(derived_strength, 4),
            rationale=(
                f"{source_ticker} batch ({len(claims)} claims) propagated "
                f"via shared tag '{best_tag_name}' to {target_ticker} "
                f"(top3_avg={avg_strength:.2f}, att={best_attenuation:.3f})"
            ),
        ))

    return signals


# ---------------------------------------------------------------------------
# Channel 3: Multi-hop graph propagation (2nd-degree impacts)
# ---------------------------------------------------------------------------

# Attenuation per hop — 2nd-degree signals are much weaker
HOP2_ATTENUATION_DECAY = 0.35  # each hop multiplies by this (so 2-hop = 0.35^2 ≈ 0.12)
MIN_GRAPH_HOP_STRENGTH = 0.03  # minimum derived strength to create 2nd-hop signal


def _propagate_via_graph(
    session: Session,
    claims: list[Claim],
    source_ticker: str,
    skip_tickers: set[str],
    existing_signals: list[DerivedSignal],
) -> list[DerivedSignal]:
    """Propagate via NetworkX graph multi-hop traversal (2nd-degree impacts).

    Finds tickers reachable in 2 hops that were NOT already reached by
    Channel 1 (direct) or Channel 2 (tags). This catches indirect supply
    chain impacts: TSMC issue → NVDA (hop 1, already via direct) → META
    (hop 2, only reachable via graph).

    The graph is built on-demand from SQL — lightweight because we only
    need the company relationship subgraph, not the full document graph.
    """
    # Skip tickers already covered by Channel 1 + 2
    already_covered = skip_tickers | {source_ticker}
    for sig in existing_signals:
        already_covered.add(sig.target_ticker)

    try:
        from graph_sync import build_full_graph
        graph = build_full_graph(session)
    except Exception as e:
        logger.debug("Graph build failed for multi-hop propagation: %s", e)
        return []

    # Use the existing BFS traversal function
    impacts = find_impacted_tickers_via_graph(graph, source_ticker, max_hops=2)
    if not impacts:
        return []

    # Filter to only 2nd-hop tickers (those not already reached by direct/tag)
    # and only tickers that actually have an active thesis
    from models import Thesis
    active_tickers = set(session.scalars(
        select(Thesis.company_ticker).where(Thesis.status_active == True)  # noqa: E712
    ).all())

    novel_impacts = [
        imp for imp in impacts
        if imp["ticker"] not in already_covered
        and imp["ticker"] in active_tickers
        and imp["total_attenuation"] >= MIN_GRAPH_HOP_STRENGTH
    ]

    if not novel_impacts:
        return []

    # Aggregate claim direction (majority vote) and strength (top-3 average)
    claim_strengths = sorted(
        [(c.strength or 0.5) for c in claims], reverse=True
    )[:3]
    avg_strength = sum(claim_strengths) / len(claim_strengths) if claim_strengths else 0.5

    dir_counts: dict[str, int] = {}
    for c in claims:
        d = c.direction.value if hasattr(c.direction, "value") else str(c.direction)
        dir_counts[d] = dir_counts.get(d, 0) + 1
    majority_dir = max(dir_counts, key=lambda d: dir_counts[d])

    # For competitor edges in the path, flip direction
    representative_claim = max(claims, key=lambda c: c.strength or 0)

    signals = []
    for imp in novel_impacts[:20]:  # cap at 20 2nd-hop targets to prevent explosion
        path_str = " → ".join(imp["path"]) if imp["path"] else "indirect"
        graph_attenuation = imp["total_attenuation"]
        derived_strength = avg_strength * graph_attenuation

        if derived_strength < MIN_GRAPH_HOP_STRENGTH:
            continue

        # Check if any edge in the path is a competitor edge (flip direction)
        has_competitor_edge = any("COMPETES" in edge for edge in imp["path"])
        final_dir = Direction(majority_dir)
        if has_competitor_edge:
            final_dir = _flip_direction(final_dir)

        signals.append(DerivedSignal(
            source_claim_id=representative_claim.id,
            source_ticker=source_ticker,
            target_ticker=imp["ticker"],
            propagation_type="graph_2hop",
            relationship_type=path_str,
            attenuation_factor=round(graph_attenuation, 4),
            derived_direction=final_dir,
            derived_strength=round(derived_strength, 4),
            rationale=(
                f"{source_ticker} → {imp['ticker']} via graph ({path_str}): "
                f"top3_avg={avg_strength:.2f}, graph_att={graph_attenuation:.3f}"
            ),
        ))

    if signals:
        logger.info(
            "Graph 2-hop: %d new targets from %s (e.g., %s)",
            len(signals), source_ticker,
            ", ".join(s.target_ticker for s in signals[:5]),
        )

    return signals


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _flip_direction(direction: Direction) -> Direction:
    """Flip direction for competitor propagation."""
    flip_map = {
        Direction.POSITIVE: Direction.NEGATIVE,
        Direction.NEGATIVE: Direction.POSITIVE,
        Direction.MIXED: Direction.MIXED,
        Direction.NEUTRAL: Direction.NEUTRAL,
    }
    return flip_map.get(direction, direction)


# ---------------------------------------------------------------------------
# Cascade: consume derived signals and update target ticker convictions
# ---------------------------------------------------------------------------

def run_cascade_updates(
    session: Session,
    source_ticker: str,
    use_llm: bool = True,
) -> list[dict]:
    """Trigger thesis updates for all tickers that received derived signals.

    After NVDA's thesis update propagated 77 signals to MSFT/AMZN/AMD/etc,
    this function picks up those unconsumed signals and runs thesis updates
    for each target ticker that has an active thesis.

    The derived signals are injected as context (via get_prior_context's
    _format_derived_signals), and the conviction score adjusts based on
    the aggregate signal direction and strength.

    Returns list of {ticker, before_score, after_score, signals_consumed} dicts.
    """
    from models import Thesis

    # Find all tickers with unconsumed signals from this propagation
    stmt = (
        select(DerivedSignal.target_ticker)
        .where(
            DerivedSignal.source_ticker == source_ticker,
            DerivedSignal.consumed == False,  # noqa: E712
        )
        .distinct()
    )
    target_tickers = list(session.scalars(stmt).all())

    if not target_tickers:
        logger.info("No unconsumed derived signals from %s to cascade", source_ticker)
        return []

    logger.info(
        "Cascading updates to %d tickers from %s: %s",
        len(target_tickers), source_ticker, target_tickers,
    )

    results = []
    for ticker in target_tickers:
        # Find active thesis for this ticker
        thesis = session.scalars(
            select(Thesis).where(
                Thesis.company_ticker == ticker,
                Thesis.status_active == True,  # noqa: E712
            ).order_by(Thesis.updated_at.desc()).limit(1)
        ).first()

        if not thesis:
            # No active thesis — just consume the signals so they don't pile up
            consumed = mark_signals_consumed(session, ticker)
            logger.info("No active thesis for %s — consumed %d signals without update", ticker, consumed)
            results.append({
                "ticker": ticker,
                "status": "no_thesis",
                "signals_consumed": consumed,
            })
            continue

        # Count signals before consuming
        signal_count = session.scalar(
            select(func.count(DerivedSignal.id)).where(
                DerivedSignal.target_ticker == ticker,
                DerivedSignal.consumed == False,  # noqa: E712
            )
        )

        # Aggregate the signal direction/strength for a synthetic claim update
        result = _apply_derived_signals_to_thesis(session, thesis, use_llm=use_llm)
        result["ticker"] = ticker
        result["signals_consumed"] = signal_count
        results.append(result)

    session.flush()
    return results


def _apply_derived_signals_to_thesis(
    session: Session,
    thesis,
    use_llm: bool = True,
) -> dict:
    """Apply unconsumed derived signals to a thesis's conviction score.

    Instead of running full LLM classification (which needs actual claim text),
    we compute a conviction delta directly from the aggregate signal strength
    and direction, then adjust the thesis score.

    This is faster and cheaper than full LLM re-evaluation, and appropriate
    because derived signals are already attenuated — they represent indirect
    evidence, not primary claims.
    """
    from models import Thesis, ThesisState, ThesisStateHistory

    ticker = thesis.company_ticker
    before_score = thesis.conviction_score or 50.0
    before_state = thesis.state

    # Fetch unconsumed signals for this ticker
    signals = list(session.scalars(
        select(DerivedSignal).where(
            DerivedSignal.target_ticker == ticker,
            DerivedSignal.consumed == False,  # noqa: E712
        )
    ).all())

    if not signals:
        return {"before_score": before_score, "after_score": before_score, "status": "no_signals"}

    # Dedup: keep only the strongest signal per (source_ticker, target_ticker) pair.
    # This prevents double-counting if a prior propagation bug created duplicates,
    # or if signals from the same source arrived via different channels.
    best_per_source: dict[str, DerivedSignal] = {}
    for sig in signals:
        key = sig.source_ticker
        existing = best_per_source.get(key)
        if not existing or (sig.derived_strength or 0) > (existing.derived_strength or 0):
            best_per_source[key] = sig
    deduped_signals = list(best_per_source.values())

    # Aggregate: sum signed strengths from distinct sources, capped per-source
    CONVICTION_SCALE = 10.0
    MAX_PER_SOURCE_DELTA = 3.0    # any single source can move conviction ±3 pts max
    MAX_TOTAL_CASCADE_DELTA = 5.0  # all sources combined can move ±5 pts max

    total_delta = 0.0
    for sig in deduped_signals:
        direction = sig.derived_direction
        strength = sig.derived_strength or 0.0
        if hasattr(direction, 'value'):
            direction = direction.value

        if direction == "positive":
            source_delta = strength * CONVICTION_SCALE
        elif direction == "negative":
            source_delta = -strength * CONVICTION_SCALE
        else:
            continue  # mixed/neutral contribute nothing

        # Cap per-source contribution
        source_delta = max(-MAX_PER_SOURCE_DELTA, min(MAX_PER_SOURCE_DELTA, source_delta))
        total_delta += source_delta

    # Diminishing returns: sqrt scaling for large aggregate deltas
    raw_delta = total_delta
    if abs(raw_delta) > 3.0:
        sign = 1 if raw_delta > 0 else -1
        raw_delta = sign * (3.0 + (abs(raw_delta) - 3.0) ** 0.7)
    capped_delta = max(-MAX_TOTAL_CASCADE_DELTA, min(MAX_TOTAL_CASCADE_DELTA, raw_delta))

    new_score = max(0.0, min(100.0, before_score + capped_delta))

    # State transition
    new_state = _resolve_state(new_score, before_state)

    # Apply
    thesis.conviction_score = round(new_score, 2)
    thesis.state = new_state

    # Record history
    source_tickers = set(s.source_ticker for s in deduped_signals)
    session.add(ThesisStateHistory(
        thesis_id=thesis.id,
        state=new_state,
        conviction_score=round(new_score, 2),
        note=(
            f"Cascade from {', '.join(sorted(source_tickers))}: "
            f"{len(deduped_signals)} sources ({len(signals)} raw signals deduped), "
            f"{before_score:.1f} -> {new_score:.1f} ({capped_delta:+.2f})"
        ),
    ))

    # Mark ALL signals consumed (including duplicates)
    consumed = mark_signals_consumed(session, ticker)

    logger.info(
        "Cascade update %s: %.1f -> %.1f (%+.2f from %d sources, %d raw signals via %s)",
        ticker, before_score, new_score, capped_delta,
        len(deduped_signals), len(signals),
        ', '.join(sorted(source_tickers)),
    )

    return {
        "before_score": round(before_score, 2),
        "after_score": round(new_score, 2),
        "before_state": before_state.value,
        "after_state": new_state.value,
        "delta": round(capped_delta, 2),
        "num_signals": len(signals),
        "status": "updated",
    }


def _resolve_state(score: float, current_state) -> "ThesisState":
    """Resolve thesis state from conviction score."""
    from models import ThesisState

    if score >= 75:
        return ThesisState.CONFIRMED
    elif score >= 60:
        return ThesisState.STRENGTHENING
    elif score >= 40:
        return ThesisState.FORMING
    elif score >= 25:
        return ThesisState.WEAKENING
    else:
        return ThesisState.INVALIDATED


# ---------------------------------------------------------------------------
# Graph-based queries (for multi-hop traversal)
# ---------------------------------------------------------------------------

def find_impacted_tickers_via_graph(
    graph,
    source_ticker: str,
    max_hops: int = 2,
) -> list[dict]:
    """Use the NetworkX graph for multi-hop impact discovery.

    This is a read-only graph query — no DB writes. Returns a list of
    {ticker, path, total_attenuation} dicts for tickers reachable within
    max_hops from source_ticker.

    Designed for future use when the graph is richer. Currently propagation
    uses direct SQL queries (propagate_claims above).
    """
    from graph_memory import NodeType, EdgeType, node_id as nid

    start = nid(NodeType.COMPANY, source_ticker)
    if start not in graph.g:
        return []

    relationship_edges = {
        EdgeType.COMPANY_SUPPLIES.value,
        EdgeType.COMPANY_CUSTOMER_OF.value,
        EdgeType.COMPANY_COMPETES_WITH.value,
        EdgeType.COMPANY_ECOSYSTEM.value,
        EdgeType.COMPANY_HAS_TAG.value,
    }

    visited: set[str] = {start}
    results: list[dict] = []
    frontier = [(start, [], 1.0)]

    for _hop in range(max_hops):
        next_frontier = []
        for current, path, cumulative_att in frontier:
            for _, neighbor, data in graph.g.out_edges(current, data=True):
                edge_type = data.get("_edge_type", "")
                if edge_type not in relationship_edges:
                    continue
                if neighbor in visited:
                    continue

                visited.add(neighbor)
                node_data = graph.g.nodes.get(neighbor, {})
                node_type = node_data.get("_type", "")

                # If it's a company node, record it
                if node_type == NodeType.COMPANY.value:
                    weight = data.get("weight", data.get("strength", 0.5))
                    new_att = cumulative_att * weight
                    new_path = path + [edge_type]
                    results.append({
                        "ticker": node_data.get("_key", neighbor),
                        "path": new_path,
                        "total_attenuation": round(new_att, 4),
                    })
                    next_frontier.append((neighbor, new_path, new_att))
                else:
                    # Intermediate node (e.g., Theme tag) — continue traversal
                    next_frontier.append((neighbor, path + [edge_type], cumulative_att))

        frontier = next_frontier

    # Sort by attenuation (strongest impact first)
    results.sort(key=lambda x: x["total_attenuation"], reverse=True)
    return results
