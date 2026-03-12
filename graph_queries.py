"""Graph query helpers for explainability and memory inspection.

Each function takes a ConsensusGraph and returns structured data
tied to real graph objects — no invented summaries.
"""
from __future__ import annotations

import logging
from typing import Optional

from graph_memory import ConsensusGraph, NodeType, EdgeType, node_id

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Claims linked to a thesis
# ---------------------------------------------------------------------------

def claims_for_thesis(cg: ConsensusGraph, thesis_id: int) -> list[dict]:
    """Return all claims linked to a thesis, with link type and claim metadata."""
    tid = node_id(NodeType.THESIS, thesis_id)
    if tid not in cg.g:
        return []

    results = []
    for src in cg.predecessors(tid, EdgeType.CLAIM_LINKED_TO_THESIS):
        claim_data = dict(cg.g.nodes[src])
        edge_data = cg.g.edges[src, tid]
        results.append({
            "claim_id": claim_data.get("_key"),
            "claim_text_short": claim_data.get("claim_text_short"),
            "claim_type": claim_data.get("claim_type"),
            "direction": claim_data.get("direction"),
            "strength": claim_data.get("strength"),
            "novelty_type": claim_data.get("novelty_type"),
            "link_type": edge_data.get("link_type"),
            "published_at": claim_data.get("_ts"),
        })
    return sorted(results, key=lambda x: x.get("published_at") or "", reverse=True)


# ---------------------------------------------------------------------------
# 2. Thesis evolution over time
# ---------------------------------------------------------------------------

def thesis_evolution(cg: ConsensusGraph, thesis_id: int) -> list[dict]:
    """Return ordered state history for a thesis."""
    tid = node_id(NodeType.THESIS, thesis_id)
    if tid not in cg.g:
        return []

    states = []
    for dst in cg.successors(tid, EdgeType.THESIS_HAS_STATE):
        d = dict(cg.g.nodes[dst])
        states.append({
            "state_history_id": d.get("_key"),
            "state": d.get("state"),
            "conviction_score": d.get("conviction_score"),
            "valuation_gap_pct": d.get("valuation_gap_pct"),
            "note": d.get("note"),
            "created_at": d.get("_ts"),
        })
    return sorted(states, key=lambda x: x.get("created_at") or "")


def thesis_evolution_by_ticker(cg: ConsensusGraph, ticker: str) -> dict[int, list[dict]]:
    """Return thesis evolution for all theses of a company."""
    cid = node_id(NodeType.COMPANY, ticker)
    if cid not in cg.g:
        return {}

    result = {}
    for src in cg.predecessors(cid, EdgeType.THESIS_FOR_COMPANY):
        thesis_data = dict(cg.g.nodes[src])
        tid = int(thesis_data["_key"])
        result[tid] = thesis_evolution(cg, tid)
    return result


# ---------------------------------------------------------------------------
# 3. Themes connected to a company
# ---------------------------------------------------------------------------

def themes_for_company(cg: ConsensusGraph, ticker: str) -> list[dict]:
    """Return all themes connected to a company via theses or claims."""
    cid = node_id(NodeType.COMPANY, ticker)
    if cid not in cg.g:
        return []

    theme_ids = set()

    # Via theses
    for thesis_nid in cg.predecessors(cid, EdgeType.THESIS_FOR_COMPANY):
        for theme_nid in cg.successors(thesis_nid, EdgeType.THESIS_LINKED_TO_THEME):
            theme_ids.add(theme_nid)

    # Via claims
    for claim_nid in cg.predecessors(cid, EdgeType.CLAIM_ABOUT_COMPANY):
        for theme_nid in cg.successors(claim_nid, EdgeType.CLAIM_SUPPORTS_THEME):
            theme_ids.add(theme_nid)

    results = []
    for tid in theme_ids:
        d = dict(cg.g.nodes[tid])
        results.append({
            "theme_id": d.get("_key"),
            "theme_name": d.get("theme_name"),
            "theme_type": d.get("theme_type"),
            "description": d.get("description"),
        })
    return results


# ---------------------------------------------------------------------------
# 4. Cross-company thematic linkages
# ---------------------------------------------------------------------------

def companies_sharing_theme(cg: ConsensusGraph, theme_id: int) -> list[dict]:
    """Return all companies connected to a theme."""
    tnid = node_id(NodeType.THEME, theme_id)
    if tnid not in cg.g:
        return []

    tickers = set()

    # Via thesis-theme links
    for thesis_nid in cg.predecessors(tnid, EdgeType.THESIS_LINKED_TO_THEME):
        thesis_data = dict(cg.g.nodes[thesis_nid])
        t = thesis_data.get("company_ticker")
        if t:
            tickers.add(t)

    # Via claim-theme links
    for claim_nid in cg.predecessors(tnid, EdgeType.CLAIM_SUPPORTS_THEME):
        for co_nid in cg.successors(claim_nid, EdgeType.CLAIM_ABOUT_COMPANY):
            co_data = dict(cg.g.nodes[co_nid])
            tickers.add(co_data["_key"])

    results = []
    for ticker in sorted(tickers):
        nid = node_id(NodeType.COMPANY, ticker)
        if nid in cg.g:
            d = dict(cg.g.nodes[nid])
            results.append({
                "ticker": ticker,
                "name": d.get("name"),
                "sector": d.get("sector"),
            })
    return results


def cross_company_themes(cg: ConsensusGraph, ticker_a: str, ticker_b: str) -> list[dict]:
    """Return themes shared between two companies."""
    themes_a = {t["theme_id"] for t in themes_for_company(cg, ticker_a)}
    themes_b = {t["theme_id"] for t in themes_for_company(cg, ticker_b)}
    shared = themes_a & themes_b

    results = []
    for tid_str in sorted(shared):
        nid = node_id(NodeType.THEME, tid_str)
        if nid in cg.g:
            d = dict(cg.g.nodes[nid])
            results.append({
                "theme_id": tid_str,
                "theme_name": d.get("theme_name"),
                "theme_type": d.get("theme_type"),
            })
    return results


# ---------------------------------------------------------------------------
# 5. Checkpoint-linked evidence
# ---------------------------------------------------------------------------

def checkpoint_evidence(cg: ConsensusGraph, thesis_id: int) -> list[dict]:
    """Return claims linked to a thesis with link_type='checkpoint'."""
    all_claims = claims_for_thesis(cg, thesis_id)
    return [c for c in all_claims if c.get("link_type") == "checkpoint"]


# ---------------------------------------------------------------------------
# 6. Why do we own / watch a stock?
# ---------------------------------------------------------------------------

def why_own(cg: ConsensusGraph, ticker: str) -> dict:
    """Explain why a stock is in the portfolio."""
    cid = node_id(NodeType.COMPANY, ticker)
    if cid not in cg.g:
        return {"ticker": ticker, "status": "not_found"}

    # Find positions
    positions = []
    for pos_nid in cg.predecessors(cid, EdgeType.POSITION_FOR_COMPANY):
        pd = dict(cg.g.nodes[pos_nid])
        positions.append({
            "position_id": pd.get("_key"),
            "current_weight": pd.get("current_weight"),
            "conviction_score": pd.get("conviction_score"),
            "zone_state": pd.get("zone_state"),
            "status": pd.get("status"),
        })

    # Find candidates
    candidates = []
    for cand_nid in cg.predecessors(cid, EdgeType.CANDIDATE_FOR_COMPANY):
        cd = dict(cg.g.nodes[cand_nid])
        candidates.append({
            "candidate_id": cd.get("_key"),
            "conviction_score": cd.get("conviction_score"),
            "buyable_flag": cd.get("buyable_flag"),
            "watch_reason": cd.get("watch_reason"),
        })

    # Find theses
    theses = []
    for thesis_nid in cg.predecessors(cid, EdgeType.THESIS_FOR_COMPANY):
        td = dict(cg.g.nodes[thesis_nid])
        theses.append({
            "thesis_id": td.get("_key"),
            "title": td.get("title"),
            "state": td.get("state"),
            "conviction_score": td.get("conviction_score"),
        })

    # Recent claims
    recent_claims = []
    for claim_nid in cg.predecessors(cid, EdgeType.CLAIM_ABOUT_COMPANY):
        cd = dict(cg.g.nodes[claim_nid])
        recent_claims.append({
            "claim_id": cd.get("_key"),
            "claim_text_short": cd.get("claim_text_short"),
            "direction": cd.get("direction"),
            "published_at": cd.get("_ts"),
        })
    recent_claims = sorted(recent_claims, key=lambda x: x.get("published_at") or "", reverse=True)[:10]

    is_owned = any(p.get("status") == "active" for p in positions)
    is_candidate = len(candidates) > 0

    return {
        "ticker": ticker,
        "is_owned": is_owned,
        "is_candidate": is_candidate,
        "positions": positions,
        "candidates": candidates,
        "theses": theses,
        "recent_claims": recent_claims,
    }


# ---------------------------------------------------------------------------
# 7. What evidence supports a thesis?
# ---------------------------------------------------------------------------

def thesis_evidence(cg: ConsensusGraph, thesis_id: int) -> dict:
    """Return all evidence supporting / weakening a thesis."""
    tid = node_id(NodeType.THESIS, thesis_id)
    if tid not in cg.g:
        return {"thesis_id": thesis_id, "status": "not_found"}

    thesis_data = dict(cg.g.nodes[tid])
    all_claims = claims_for_thesis(cg, thesis_id)

    supporting = [c for c in all_claims if c.get("link_type") == "supports"]
    weakening = [c for c in all_claims if c.get("link_type") == "weakens"]
    checkpoint = [c for c in all_claims if c.get("link_type") == "checkpoint"]
    context = [c for c in all_claims if c.get("link_type") == "context"]

    return {
        "thesis_id": thesis_id,
        "title": thesis_data.get("title"),
        "state": thesis_data.get("state"),
        "conviction_score": thesis_data.get("conviction_score"),
        "supporting_claims": supporting,
        "weakening_claims": weakening,
        "checkpoint_claims": checkpoint,
        "context_claims": context,
        "total_claims": len(all_claims),
    }


# ---------------------------------------------------------------------------
# 8. Documents that influenced a thesis
# ---------------------------------------------------------------------------

def documents_for_thesis(cg: ConsensusGraph, thesis_id: int) -> list[dict]:
    """Return documents whose claims are linked to this thesis."""
    claims = claims_for_thesis(cg, thesis_id)
    doc_ids = set()
    results = []

    for claim in claims:
        claim_nid = node_id(NodeType.CLAIM, claim["claim_id"])
        for doc_nid in cg.predecessors(claim_nid, EdgeType.DOCUMENT_HAS_CLAIM):
            if doc_nid not in doc_ids:
                doc_ids.add(doc_nid)
                d = dict(cg.g.nodes[doc_nid])
                results.append({
                    "document_id": d.get("_key"),
                    "title": d.get("title"),
                    "source_type": d.get("source_type"),
                    "source_tier": d.get("source_tier"),
                    "published_at": d.get("published_at"),
                    "url": d.get("url"),
                })

    return sorted(results, key=lambda x: x.get("published_at") or "", reverse=True)


# ---------------------------------------------------------------------------
# 9. State transition explainer
# ---------------------------------------------------------------------------

def explain_state_transition(
    cg: ConsensusGraph,
    thesis_id: int,
    from_state: Optional[str] = None,
    to_state: Optional[str] = None,
) -> dict:
    """Explain how a thesis went from one state to another."""
    evolution = thesis_evolution(cg, thesis_id)
    if not evolution:
        return {"thesis_id": thesis_id, "status": "no_history"}

    # Find the transition window
    transition_entries = []
    if from_state and to_state:
        found_from = False
        for entry in evolution:
            if entry["state"] == from_state:
                found_from = True
            if found_from:
                transition_entries.append(entry)
            if entry["state"] == to_state and found_from:
                break
    else:
        transition_entries = evolution

    # Get claims around this thesis
    all_claims = claims_for_thesis(cg, thesis_id)

    return {
        "thesis_id": thesis_id,
        "from_state": from_state,
        "to_state": to_state,
        "state_path": transition_entries,
        "linked_claims": all_claims[:20],
    }


# ---------------------------------------------------------------------------
# 10. Graph-wide stats for a company
# ---------------------------------------------------------------------------

def company_summary(cg: ConsensusGraph, ticker: str) -> dict:
    """Full graph-derived summary for a company."""
    cid = node_id(NodeType.COMPANY, ticker)
    if cid not in cg.g:
        return {"ticker": ticker, "status": "not_found"}

    co_data = dict(cg.g.nodes[cid])

    n_docs = len(cg.predecessors(cid, EdgeType.DOCUMENT_ABOUT_COMPANY))
    n_claims = len(cg.predecessors(cid, EdgeType.CLAIM_ABOUT_COMPANY))
    n_theses = len(cg.predecessors(cid, EdgeType.THESIS_FOR_COMPANY))
    n_positions = len(cg.predecessors(cid, EdgeType.POSITION_FOR_COMPANY))
    n_candidates = len(cg.predecessors(cid, EdgeType.CANDIDATE_FOR_COMPANY))
    themes = themes_for_company(cg, ticker)

    return {
        "ticker": ticker,
        "name": co_data.get("name"),
        "sector": co_data.get("sector"),
        "industry": co_data.get("industry"),
        "documents": n_docs,
        "claims": n_claims,
        "theses": n_theses,
        "positions": n_positions,
        "candidates": n_candidates,
        "themes": themes,
    }


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def format_why_own(result: dict) -> str:
    """Format why_own result as readable text."""
    lines = [f"=== Why {result['ticker']}? ==="]

    if result.get("status") == "not_found":
        lines.append("  Company not found in graph.")
        return "\n".join(lines)

    status = "OWNED" if result["is_owned"] else ("CANDIDATE" if result["is_candidate"] else "NOT IN PORTFOLIO")
    lines.append(f"  Status: {status}")

    if result["theses"]:
        lines.append("\n  Theses:")
        for t in result["theses"]:
            lines.append(f"    [{t['state']}] {t['title']} (conviction={t['conviction_score']})")

    if result["positions"]:
        lines.append("\n  Positions:")
        for p in result["positions"]:
            lines.append(f"    weight={p['current_weight']}% zone={p['zone_state']} status={p['status']}")

    if result["recent_claims"]:
        lines.append(f"\n  Recent claims ({len(result['recent_claims'])}):")
        for c in result["recent_claims"][:5]:
            lines.append(f"    [{c['direction']}] {c['claim_text_short']}")

    return "\n".join(lines)


def format_thesis_evolution(evolution: list[dict], thesis_id: int) -> str:
    """Format thesis evolution as readable text."""
    if not evolution:
        return f"No state history for thesis {thesis_id}"

    lines = [f"=== Thesis {thesis_id} Evolution ==="]
    for e in evolution:
        lines.append(
            f"  {e['created_at']}  state={e['state']}  "
            f"conviction={e['conviction_score']}  note={e.get('note', '')}"
        )
    return "\n".join(lines)
