"""Sync relational DB state into the ConsensusGraph.

Deterministic path: relational objects → graph nodes/edges → exported artifact.

Supports:
  - Full rebuild from DB
  - Incremental sync for a single ticker
  - Export to JSON artifact
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, date
from typing import Optional

from sqlalchemy.orm import Session

from graph_memory import (
    ConsensusGraph, NodeType, EdgeType, node_id,
)
from models import (
    Company, Document, Claim, Theme, Thesis, Checkpoint,
    ThesisStateHistory, PeerGroup, PortfolioPosition, Candidate,
    PortfolioReview, PortfolioDecision,
    ClaimCompanyLink, ClaimThemeLink, ThesisClaimLink,
    ThesisThemeLink, CompanyPeerGroupLink,
    CompanyTagLink, CompanyRelationship, RelationshipType,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Full rebuild
# ---------------------------------------------------------------------------

def build_full_graph(session: Session) -> ConsensusGraph:
    """Build the complete graph from the current DB state."""
    cg = ConsensusGraph()
    cg._built_at = datetime.utcnow().isoformat()

    _sync_companies(session, cg)
    _sync_themes(session, cg)
    _sync_peer_groups(session, cg)
    _sync_documents(session, cg)
    _sync_claims(session, cg)
    _sync_checkpoints(session, cg)
    _sync_theses(session, cg)
    _sync_thesis_state_history(session, cg)
    _sync_positions(session, cg)
    _sync_candidates(session, cg)
    _sync_reviews(session, cg)

    # Link tables → edges
    _sync_claim_company_links(session, cg)
    _sync_claim_theme_links(session, cg)
    _sync_thesis_claim_links(session, cg)
    _sync_thesis_theme_links(session, cg)
    _sync_company_peer_group_links(session, cg)
    _sync_company_tag_links(session, cg)
    _sync_company_relationships(session, cg)

    # Best-effort sync to Neo4j/Graphiti (non-blocking)
    _sync_to_neo4j(session)

    summary = cg.summary()
    logger.info(
        "Graph built: %d nodes, %d edges",
        summary["total_nodes"], summary["total_edges"],
    )
    return cg


def build_ticker_graph(session: Session, ticker: str) -> ConsensusGraph:
    """Build a subgraph centered on a single ticker."""
    cg = ConsensusGraph()
    cg._built_at = datetime.utcnow().isoformat()

    company = session.query(Company).filter_by(ticker=ticker).first()
    if not company:
        logger.warning("Company %s not found", ticker)
        return cg

    # Company node
    _add_company_node(cg, company)

    # Themes (all — needed for cross-links)
    for theme in session.query(Theme).all():
        _add_theme_node(cg, theme)

    # Peer groups
    for pg in session.query(PeerGroup).all():
        _add_peer_group_node(cg, pg)

    # Documents for this ticker
    docs = session.query(Document).filter_by(primary_company_ticker=ticker).all()
    for doc in docs:
        _add_document_node(cg, doc)
        cg.add_edge(
            node_id(NodeType.DOCUMENT, doc.id),
            node_id(NodeType.COMPANY, ticker),
            EdgeType.DOCUMENT_ABOUT_COMPANY,
        )

    # Claims from those documents
    doc_ids = [d.id for d in docs]
    if doc_ids:
        claims = session.query(Claim).filter(Claim.document_id.in_(doc_ids)).all()
        for claim in claims:
            _add_claim_node(cg, claim)
            cg.add_edge(
                node_id(NodeType.DOCUMENT, claim.document_id),
                node_id(NodeType.CLAIM, claim.id),
                EdgeType.DOCUMENT_HAS_CLAIM,
            )

        claim_ids = [c.id for c in claims]

        # Claim-company links
        for link in session.query(ClaimCompanyLink).filter(
            ClaimCompanyLink.claim_id.in_(claim_ids)
        ).all():
            if not cg.has_node(NodeType.COMPANY, link.company_ticker):
                co = session.query(Company).filter_by(ticker=link.company_ticker).first()
                if co:
                    _add_company_node(cg, co)
            if cg.has_node(NodeType.COMPANY, link.company_ticker):
                cg.add_edge(
                    node_id(NodeType.CLAIM, link.claim_id),
                    node_id(NodeType.COMPANY, link.company_ticker),
                    EdgeType.CLAIM_ABOUT_COMPANY,
                    relation_type=link.relation_type,
                )

        # Claim-theme links
        for link in session.query(ClaimThemeLink).filter(
            ClaimThemeLink.claim_id.in_(claim_ids)
        ).all():
            if cg.has_node(NodeType.THEME, link.theme_id):
                cg.add_edge(
                    node_id(NodeType.CLAIM, link.claim_id),
                    node_id(NodeType.THEME, link.theme_id),
                    EdgeType.CLAIM_SUPPORTS_THEME,
                )

    # Theses for this ticker
    theses = session.query(Thesis).filter_by(company_ticker=ticker).all()
    for thesis in theses:
        _add_thesis_node(cg, thesis)
        cg.add_edge(
            node_id(NodeType.THESIS, thesis.id),
            node_id(NodeType.COMPANY, ticker),
            EdgeType.THESIS_FOR_COMPANY,
        )
        if thesis.checkpoint_next_id:
            cp = session.get(Checkpoint, thesis.checkpoint_next_id)
            if cp:
                _add_checkpoint_node(cg, cp)
                cg.add_edge(
                    node_id(NodeType.THESIS, thesis.id),
                    node_id(NodeType.CHECKPOINT, cp.id),
                    EdgeType.THESIS_HAS_CHECKPOINT,
                )

        # Thesis state history
        for sh in session.query(ThesisStateHistory).filter_by(thesis_id=thesis.id).order_by(
            ThesisStateHistory.created_at
        ).all():
            _add_state_history_node(cg, sh)
            cg.add_edge(
                node_id(NodeType.THESIS, thesis.id),
                node_id(NodeType.THESIS_STATE, sh.id),
                EdgeType.THESIS_HAS_STATE,
            )

        # Thesis-claim links
        for link in session.query(ThesisClaimLink).filter_by(thesis_id=thesis.id).all():
            if cg.has_node(NodeType.CLAIM, link.claim_id):
                cg.add_edge(
                    node_id(NodeType.CLAIM, link.claim_id),
                    node_id(NodeType.THESIS, thesis.id),
                    EdgeType.CLAIM_LINKED_TO_THESIS,
                    link_type=link.link_type,
                )

        # Thesis-theme links
        for link in session.query(ThesisThemeLink).filter_by(thesis_id=thesis.id).all():
            if cg.has_node(NodeType.THEME, link.theme_id):
                cg.add_edge(
                    node_id(NodeType.THESIS, thesis.id),
                    node_id(NodeType.THEME, link.theme_id),
                    EdgeType.THESIS_LINKED_TO_THEME,
                )

    # Positions
    for pos in session.query(PortfolioPosition).filter_by(ticker=ticker).all():
        _add_position_node(cg, pos)
        cg.add_edge(
            node_id(NodeType.PORTFOLIO_POSITION, pos.id),
            node_id(NodeType.COMPANY, ticker),
            EdgeType.POSITION_FOR_COMPANY,
        )
        if cg.has_node(NodeType.THESIS, pos.thesis_id):
            cg.add_edge(
                node_id(NodeType.PORTFOLIO_POSITION, pos.id),
                node_id(NodeType.THESIS, pos.thesis_id),
                EdgeType.POSITION_LINKED_TO_THESIS,
            )

    # Candidates
    for cand in session.query(Candidate).filter_by(ticker=ticker).all():
        _add_candidate_node(cg, cand)
        cg.add_edge(
            node_id(NodeType.CANDIDATE, cand.id),
            node_id(NodeType.COMPANY, ticker),
            EdgeType.CANDIDATE_FOR_COMPANY,
        )
        if cand.primary_thesis_id and cg.has_node(NodeType.THESIS, cand.primary_thesis_id):
            cg.add_edge(
                node_id(NodeType.CANDIDATE, cand.id),
                node_id(NodeType.THESIS, cand.primary_thesis_id),
                EdgeType.CANDIDATE_LINKED_TO_THESIS,
            )

    # Peer group links
    for link in session.query(CompanyPeerGroupLink).filter_by(company_ticker=ticker).all():
        if cg.has_node(NodeType.PEER_GROUP, link.peer_group_id):
            cg.add_edge(
                node_id(NodeType.COMPANY, ticker),
                node_id(NodeType.PEER_GROUP, link.peer_group_id),
                EdgeType.COMPANY_IN_PEERGROUP,
                role=link.role,
            )

    logger.info("Ticker graph for %s: %d nodes, %d edges",
                ticker, cg.g.number_of_nodes(), cg.g.number_of_edges())
    return cg


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_graph(cg: ConsensusGraph, output_dir: str, prefix: str = "graph") -> str:
    """Export graph JSON to output_dir. Returns path to JSON file."""
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"{prefix}.json")
    with open(path, "w") as f:
        f.write(cg.to_json())
    logger.info("Graph exported to %s", path)
    return path


# ---------------------------------------------------------------------------
# Internal: node builders
# ---------------------------------------------------------------------------

def _add_company_node(cg: ConsensusGraph, co: Company):
    cg.add_node(
        NodeType.COMPANY, co.ticker,
        name=co.name,
        sector=co.sector,
        industry=co.industry,
        country=co.country,
        market_cap_bucket=co.market_cap_bucket,
    )


def _add_theme_node(cg: ConsensusGraph, t: Theme):
    cg.add_node(
        NodeType.THEME, t.id,
        theme_name=t.theme_name,
        theme_type=t.theme_type,
        description=t.description,
    )


def _add_peer_group_node(cg: ConsensusGraph, pg: PeerGroup):
    cg.add_node(
        NodeType.PEER_GROUP, pg.id,
        name=pg.name,
        sector=pg.sector,
        region=pg.region,
    )


def _add_document_node(cg: ConsensusGraph, doc: Document):
    cg.add_node(
        NodeType.DOCUMENT, doc.id,
        ts=str(doc.published_at) if doc.published_at else str(doc.ingested_at),
        title=doc.title,
        source_type=str(doc.source_type.value) if doc.source_type else None,
        source_tier=str(doc.source_tier.value) if doc.source_tier else None,
        url=doc.url,
        published_at=str(doc.published_at) if doc.published_at else None,
    )


def _add_claim_node(cg: ConsensusGraph, cl: Claim):
    cg.add_node(
        NodeType.CLAIM, cl.id,
        ts=str(cl.published_at) if cl.published_at else None,
        claim_text_short=cl.claim_text_short,
        claim_type=str(cl.claim_type.value) if cl.claim_type else None,
        direction=str(cl.direction.value) if cl.direction else None,
        strength=cl.strength,
        novelty_type=str(cl.novelty_type.value) if cl.novelty_type else None,
        is_structural=cl.is_structural,
    )


def _add_checkpoint_node(cg: ConsensusGraph, cp: Checkpoint):
    cg.add_node(
        NodeType.CHECKPOINT, cp.id,
        ts=str(cp.created_at) if cp.created_at else None,
        name=cp.name,
        checkpoint_type=cp.checkpoint_type,
        date_expected=str(cp.date_expected) if cp.date_expected else None,
        importance=cp.importance,
        status=cp.status,
    )


def _add_thesis_node(cg: ConsensusGraph, th: Thesis):
    cg.add_node(
        NodeType.THESIS, th.id,
        ts=str(th.updated_at),
        title=th.title,
        company_ticker=th.company_ticker,
        state=str(th.state.value) if th.state else None,
        conviction_score=th.conviction_score,
        valuation_gap_pct=th.valuation_gap_pct,
        base_case_rerating=th.base_case_rerating,
        created_at=str(th.created_at),
    )


def _add_state_history_node(cg: ConsensusGraph, sh: ThesisStateHistory):
    cg.add_node(
        NodeType.THESIS_STATE, sh.id,
        ts=str(sh.created_at),
        thesis_id=sh.thesis_id,
        state=str(sh.state.value) if sh.state else None,
        conviction_score=sh.conviction_score,
        valuation_gap_pct=sh.valuation_gap_pct,
        note=sh.note,
        valuation_provenance=sh.valuation_provenance,
    )


def _add_position_node(cg: ConsensusGraph, pos: PortfolioPosition):
    cg.add_node(
        NodeType.PORTFOLIO_POSITION, pos.id,
        ts=str(pos.entry_date),
        ticker=pos.ticker,
        current_weight=pos.current_weight,
        conviction_score=pos.conviction_score,
        zone_state=str(pos.zone_state.value) if pos.zone_state else None,
        status=str(pos.status.value) if pos.status else None,
        probation_flag=pos.probation_flag,
    )


def _add_candidate_node(cg: ConsensusGraph, cand: Candidate):
    cg.add_node(
        NodeType.CANDIDATE, cand.id,
        ts=str(cand.created_at) if cand.created_at else None,
        ticker=cand.ticker,
        conviction_score=cand.conviction_score,
        buyable_flag=cand.buyable_flag,
        watch_reason=cand.watch_reason,
    )


def _add_review_node(cg: ConsensusGraph, rev: PortfolioReview):
    cg.add_node(
        NodeType.PORTFOLIO_REVIEW, rev.id,
        ts=str(rev.created_at),
        review_date=str(rev.review_date),
        review_type=rev.review_type,
        holdings_reviewed=rev.holdings_reviewed,
        candidates_reviewed=rev.candidates_reviewed,
        turnover_pct=rev.turnover_pct,
    )


def _add_decision_node(cg: ConsensusGraph, dec: PortfolioDecision):
    cg.add_node(
        NodeType.PORTFOLIO_DECISION, dec.id,
        ts=str(dec.generated_at),
        ticker=dec.ticker,
        action=str(dec.action.value) if dec.action else None,
        action_score=dec.action_score,
        rationale=dec.rationale,
        target_weight_change=dec.target_weight_change,
    )


# ---------------------------------------------------------------------------
# Internal: bulk sync helpers (full rebuild)
# ---------------------------------------------------------------------------

def _sync_companies(session: Session, cg: ConsensusGraph):
    for co in session.query(Company).all():
        _add_company_node(cg, co)


def _sync_themes(session: Session, cg: ConsensusGraph):
    for t in session.query(Theme).all():
        _add_theme_node(cg, t)


def _sync_peer_groups(session: Session, cg: ConsensusGraph):
    for pg in session.query(PeerGroup).all():
        _add_peer_group_node(cg, pg)


def _sync_documents(session: Session, cg: ConsensusGraph):
    for doc in session.query(Document).all():
        _add_document_node(cg, doc)
        if doc.primary_company_ticker:
            cg.add_edge(
                node_id(NodeType.DOCUMENT, doc.id),
                node_id(NodeType.COMPANY, doc.primary_company_ticker),
                EdgeType.DOCUMENT_ABOUT_COMPANY,
            )


def _sync_claims(session: Session, cg: ConsensusGraph):
    for cl in session.query(Claim).all():
        _add_claim_node(cg, cl)
        cg.add_edge(
            node_id(NodeType.DOCUMENT, cl.document_id),
            node_id(NodeType.CLAIM, cl.id),
            EdgeType.DOCUMENT_HAS_CLAIM,
        )


def _sync_checkpoints(session: Session, cg: ConsensusGraph):
    for cp in session.query(Checkpoint).all():
        _add_checkpoint_node(cg, cp)


def _sync_theses(session: Session, cg: ConsensusGraph):
    for th in session.query(Thesis).all():
        _add_thesis_node(cg, th)
        cg.add_edge(
            node_id(NodeType.THESIS, th.id),
            node_id(NodeType.COMPANY, th.company_ticker),
            EdgeType.THESIS_FOR_COMPANY,
        )
        if th.checkpoint_next_id and cg.has_node(NodeType.CHECKPOINT, th.checkpoint_next_id):
            cg.add_edge(
                node_id(NodeType.THESIS, th.id),
                node_id(NodeType.CHECKPOINT, th.checkpoint_next_id),
                EdgeType.THESIS_HAS_CHECKPOINT,
            )
        if th.peer_group_target_id and cg.has_node(NodeType.PEER_GROUP, th.peer_group_target_id):
            cg.add_edge(
                node_id(NodeType.THESIS, th.id),
                node_id(NodeType.PEER_GROUP, th.peer_group_target_id),
                EdgeType.THESIS_TARGETS_PEERGROUP,
            )


def _sync_thesis_state_history(session: Session, cg: ConsensusGraph):
    for sh in session.query(ThesisStateHistory).all():
        _add_state_history_node(cg, sh)
        cg.add_edge(
            node_id(NodeType.THESIS, sh.thesis_id),
            node_id(NodeType.THESIS_STATE, sh.id),
            EdgeType.THESIS_HAS_STATE,
        )


def _sync_positions(session: Session, cg: ConsensusGraph):
    for pos in session.query(PortfolioPosition).all():
        _add_position_node(cg, pos)
        cg.add_edge(
            node_id(NodeType.PORTFOLIO_POSITION, pos.id),
            node_id(NodeType.COMPANY, pos.ticker),
            EdgeType.POSITION_FOR_COMPANY,
        )
        if cg.has_node(NodeType.THESIS, pos.thesis_id):
            cg.add_edge(
                node_id(NodeType.PORTFOLIO_POSITION, pos.id),
                node_id(NodeType.THESIS, pos.thesis_id),
                EdgeType.POSITION_LINKED_TO_THESIS,
            )


def _sync_candidates(session: Session, cg: ConsensusGraph):
    for cand in session.query(Candidate).all():
        _add_candidate_node(cg, cand)
        cg.add_edge(
            node_id(NodeType.CANDIDATE, cand.id),
            node_id(NodeType.COMPANY, cand.ticker),
            EdgeType.CANDIDATE_FOR_COMPANY,
        )
        if cand.primary_thesis_id and cg.has_node(NodeType.THESIS, cand.primary_thesis_id):
            cg.add_edge(
                node_id(NodeType.CANDIDATE, cand.id),
                node_id(NodeType.THESIS, cand.primary_thesis_id),
                EdgeType.CANDIDATE_LINKED_TO_THESIS,
            )


def _sync_reviews(session: Session, cg: ConsensusGraph):
    for rev in session.query(PortfolioReview).all():
        _add_review_node(cg, rev)
        for dec in (rev.decisions or []):
            _add_decision_node(cg, dec)
            cg.add_edge(
                node_id(NodeType.PORTFOLIO_REVIEW, rev.id),
                node_id(NodeType.PORTFOLIO_DECISION, dec.id),
                EdgeType.REVIEW_HAS_DECISION,
            )
            cg.add_edge(
                node_id(NodeType.PORTFOLIO_DECISION, dec.id),
                node_id(NodeType.COMPANY, dec.ticker),
                EdgeType.DECISION_FOR_COMPANY,
            )


def _sync_claim_company_links(session: Session, cg: ConsensusGraph):
    for link in session.query(ClaimCompanyLink).all():
        src = node_id(NodeType.CLAIM, link.claim_id)
        dst = node_id(NodeType.COMPANY, link.company_ticker)
        if src in cg.g and dst in cg.g:
            cg.add_edge(src, dst, EdgeType.CLAIM_ABOUT_COMPANY,
                        relation_type=link.relation_type)


def _sync_claim_theme_links(session: Session, cg: ConsensusGraph):
    for link in session.query(ClaimThemeLink).all():
        src = node_id(NodeType.CLAIM, link.claim_id)
        dst = node_id(NodeType.THEME, link.theme_id)
        if src in cg.g and dst in cg.g:
            cg.add_edge(src, dst, EdgeType.CLAIM_SUPPORTS_THEME)


def _sync_thesis_claim_links(session: Session, cg: ConsensusGraph):
    for link in session.query(ThesisClaimLink).all():
        src = node_id(NodeType.CLAIM, link.claim_id)
        dst = node_id(NodeType.THESIS, link.thesis_id)
        if src in cg.g and dst in cg.g:
            cg.add_edge(src, dst, EdgeType.CLAIM_LINKED_TO_THESIS,
                        link_type=link.link_type)


def _sync_thesis_theme_links(session: Session, cg: ConsensusGraph):
    for link in session.query(ThesisThemeLink).all():
        src = node_id(NodeType.THESIS, link.thesis_id)
        dst = node_id(NodeType.THEME, link.theme_id)
        if src in cg.g and dst in cg.g:
            cg.add_edge(src, dst, EdgeType.THESIS_LINKED_TO_THEME)


def _sync_company_peer_group_links(session: Session, cg: ConsensusGraph):
    for link in session.query(CompanyPeerGroupLink).all():
        src = node_id(NodeType.COMPANY, link.company_ticker)
        dst = node_id(NodeType.PEER_GROUP, link.peer_group_id)
        if src in cg.g and dst in cg.g:
            cg.add_edge(src, dst, EdgeType.COMPANY_IN_PEERGROUP,
                        role=link.role)


def _sync_company_tag_links(session: Session, cg: ConsensusGraph):
    for link in session.query(CompanyTagLink).all():
        src = node_id(NodeType.COMPANY, link.company_ticker)
        dst = node_id(NodeType.THEME, link.theme_id)
        if src in cg.g and dst in cg.g:
            cg.add_edge(src, dst, EdgeType.COMPANY_HAS_TAG,
                        weight=link.weight, source=link.source)


_REL_TYPE_TO_EDGE = {
    RelationshipType.SUPPLIER: EdgeType.COMPANY_SUPPLIES,
    RelationshipType.CUSTOMER: EdgeType.COMPANY_CUSTOMER_OF,
    RelationshipType.COMPETITOR: EdgeType.COMPANY_COMPETES_WITH,
    RelationshipType.ECOSYSTEM: EdgeType.COMPANY_ECOSYSTEM,
}


def _sync_company_relationships(session: Session, cg: ConsensusGraph):
    for rel in session.query(CompanyRelationship).all():
        src = node_id(NodeType.COMPANY, rel.source_ticker)
        dst = node_id(NodeType.COMPANY, rel.target_ticker)
        edge_type = _REL_TYPE_TO_EDGE.get(rel.relationship_type)
        if not edge_type:
            continue
        if src in cg.g and dst in cg.g:
            cg.add_edge(src, dst, edge_type,
                        strength=rel.strength,
                        description=rel.description)
            if rel.bidirectional:
                cg.add_edge(dst, src, edge_type,
                            strength=rel.strength,
                            description=rel.description)


# ---------------------------------------------------------------------------
# Neo4j / Graphiti sync (best-effort)
# ---------------------------------------------------------------------------

def _sync_to_neo4j(session: Session):
    """Sync company relationships from SQL to Neo4j via Graphiti.

    Best-effort: if Graphiti is not configured, logs and continues.
    """
    try:
        from graphiti_adapter import add_company_relationships_bulk
    except Exception:
        logger.debug("Graphiti adapter not available, skipping Neo4j sync")
        return

    # Sync company relationships as triplets
    rels = session.query(CompanyRelationship).all()
    if not rels:
        return

    # Build company name lookup
    companies = {c.ticker: c.name for c in session.query(Company).all()}

    triplets = []
    for rel in rels:
        src_name = companies.get(rel.source_ticker, rel.source_ticker)
        tgt_name = companies.get(rel.target_ticker, rel.target_ticker)
        rel_name = rel.relationship_type.value  # supplier, customer, competitor, ecosystem
        triplets.append((src_name, rel_name, tgt_name))

    if triplets:
        try:
            count = add_company_relationships_bulk(triplets)
            logger.info("Synced %d/%d relationships to Neo4j", count, len(triplets))
        except Exception as e:
            logger.warning("Neo4j sync failed (non-critical): %s", e)
