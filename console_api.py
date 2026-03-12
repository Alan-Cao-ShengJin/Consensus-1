"""Read-only data access layer for the operator console.

Exposes system state in a UI-friendly format without duplicating
business logic. All functions are read-only — no mutations.

Data sources:
  - SQLAlchemy DB session (documents, claims, theses, positions, reviews)
  - ConsensusGraph (graph queries, subgraph views)
  - Artifact files (execution outputs, run manifests)
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from models import (
    Company, Document, Claim, Theme, Thesis, ThesisStateHistory,
    PortfolioPosition, Candidate, PortfolioReview, PortfolioDecision,
    ClaimCompanyLink, ClaimThemeLink, ThesisClaimLink,
    ExecutionIntentRecord, PaperFillRecord, PaperPortfolioSnapshotRecord,
    ActionType, PositionStatus,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _ser(val):
    """Serialize a value for JSON output."""
    if val is None:
        return None
    if hasattr(val, "value"):
        return val.value
    if isinstance(val, (datetime,)):
        return val.isoformat()
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return val


def _doc_row(doc: Document) -> dict:
    """Serialize a Document to a dict."""
    claim_count = len(doc.claims) if doc.claims else 0
    novelty_counts = {}
    thesis_triggered = False
    for cl in (doc.claims or []):
        nt = _ser(cl.novelty_type) or "unknown"
        novelty_counts[nt] = novelty_counts.get(nt, 0) + 1

    # Check if any claim is linked to a thesis (thesis update triggered)
    # We'll compute this in the caller for efficiency
    return {
        "id": doc.id,
        "timestamp": _ser(doc.published_at or doc.ingested_at),
        "ingested_at": _ser(doc.ingested_at),
        "source_type": _ser(doc.source_type),
        "source_tier": _ser(doc.source_tier),
        "publisher": doc.publisher,
        "ticker": doc.primary_company_ticker,
        "document_type": doc.document_type or _ser(doc.source_type),
        "title": doc.title,
        "url": doc.url,
        "claim_count": claim_count,
        "novelty_counts": novelty_counts,
        "ingestion_status": "OK",
        "claim_extraction_status": "OK" if claim_count > 0 else "NONE",
    }


# ---------------------------------------------------------------------------
# A. Recent documents / live feed
# ---------------------------------------------------------------------------

def get_recent_documents(session: Session, limit: int = 50) -> list[dict]:
    """Return recently ingested documents with claim/thesis status."""
    docs = (
        session.query(Document)
        .order_by(desc(Document.ingested_at))
        .limit(limit)
        .all()
    )

    # Batch-check which documents triggered thesis updates
    doc_ids = [d.id for d in docs]
    thesis_linked_doc_ids = set()
    if doc_ids:
        rows = (
            session.query(Claim.document_id)
            .join(ThesisClaimLink, ThesisClaimLink.claim_id == Claim.id)
            .filter(Claim.document_id.in_(doc_ids))
            .distinct()
            .all()
        )
        thesis_linked_doc_ids = {r[0] for r in rows}

    results = []
    for doc in docs:
        row = _doc_row(doc)
        row["thesis_update_triggered"] = doc.id in thesis_linked_doc_ids
        results.append(row)
    return results


# ---------------------------------------------------------------------------
# B. Document detail with claims
# ---------------------------------------------------------------------------

def get_document_detail(session: Session, doc_id: int) -> Optional[dict]:
    """Return full document detail with extracted claims."""
    doc = session.get(Document, doc_id)
    if not doc:
        return None

    claims = []
    for cl in (doc.claims or []):
        # Get linked companies
        company_links = (
            session.query(ClaimCompanyLink)
            .filter_by(claim_id=cl.id)
            .all()
        )
        linked_tickers = [lk.company_ticker for lk in company_links]

        # Get linked themes
        theme_links = (
            session.query(ClaimThemeLink)
            .filter_by(claim_id=cl.id)
            .all()
        )
        theme_ids = [lk.theme_id for lk in theme_links]
        themes = []
        for tid in theme_ids:
            t = session.get(Theme, tid)
            if t:
                themes.append({"id": t.id, "name": t.theme_name, "type": t.theme_type})

        # Get linked theses
        thesis_links = (
            session.query(ThesisClaimLink)
            .filter_by(claim_id=cl.id)
            .all()
        )
        linked_theses = []
        for tl in thesis_links:
            th = session.get(Thesis, tl.thesis_id)
            if th:
                linked_theses.append({
                    "id": th.id,
                    "title": th.title,
                    "ticker": th.company_ticker,
                    "link_type": tl.link_type,
                })

        claims.append({
            "id": cl.id,
            "text": cl.claim_text_normalized,
            "text_short": cl.claim_text_short,
            "claim_type": _ser(cl.claim_type),
            "economic_channel": _ser(cl.economic_channel),
            "direction": _ser(cl.direction),
            "strength": cl.strength,
            "novelty_type": _ser(cl.novelty_type),
            "confidence": cl.confidence,
            "is_structural": cl.is_structural,
            "published_at": _ser(cl.published_at),
            "linked_tickers": linked_tickers,
            "linked_themes": themes,
            "linked_theses": linked_theses,
        })

    return {
        "document": _doc_row(doc),
        "claims": claims,
    }


# ---------------------------------------------------------------------------
# C. Thesis timeline / evolution
# ---------------------------------------------------------------------------

def get_thesis_detail(session: Session, thesis_id: int) -> Optional[dict]:
    """Return thesis detail with state history."""
    thesis = session.get(Thesis, thesis_id)
    if not thesis:
        return None

    history = (
        session.query(ThesisStateHistory)
        .filter_by(thesis_id=thesis_id)
        .order_by(ThesisStateHistory.created_at)
        .all()
    )

    return {
        "id": thesis.id,
        "title": thesis.title,
        "ticker": thesis.company_ticker,
        "state": _ser(thesis.state),
        "conviction_score": thesis.conviction_score,
        "valuation_gap_pct": thesis.valuation_gap_pct,
        "base_case_rerating": thesis.base_case_rerating,
        "summary": thesis.summary,
        "created_at": _ser(thesis.created_at),
        "updated_at": _ser(thesis.updated_at),
        "history": [
            {
                "id": h.id,
                "state": _ser(h.state),
                "conviction_score": h.conviction_score,
                "valuation_gap_pct": h.valuation_gap_pct,
                "base_case_rerating": h.base_case_rerating,
                "note": h.note,
                "provenance": h.valuation_provenance,
                "created_at": _ser(h.created_at),
            }
            for h in history
        ],
    }


def get_ticker_theses(session: Session, ticker: str) -> list[dict]:
    """Return all theses for a ticker."""
    theses = (
        session.query(Thesis)
        .filter_by(company_ticker=ticker, status_active=True)
        .order_by(desc(Thesis.updated_at))
        .all()
    )
    results = []
    for th in theses:
        detail = get_thesis_detail(session, th.id)
        if detail:
            results.append(detail)
    return results


# ---------------------------------------------------------------------------
# D. Portfolio / decisions
# ---------------------------------------------------------------------------

def get_latest_review(session: Session) -> Optional[dict]:
    """Return the latest portfolio review with decisions."""
    review = (
        session.query(PortfolioReview)
        .order_by(desc(PortfolioReview.created_at))
        .first()
    )
    if not review:
        return None

    decisions = []
    for dec in (review.decisions or []):
        decisions.append({
            "id": dec.id,
            "ticker": dec.ticker,
            "action": _ser(dec.action),
            "action_score": dec.action_score,
            "target_weight_change": dec.target_weight_change,
            "suggested_weight": dec.suggested_weight,
            "reason_codes": json.loads(dec.reason_codes) if dec.reason_codes else [],
            "rationale": dec.rationale,
            "blocking_conditions": json.loads(dec.blocking_conditions) if dec.blocking_conditions else [],
            "was_executed": dec.was_executed,
            "generated_at": _ser(dec.generated_at),
        })

    # Sort: trading actions first, then by action_score
    action_order = {"exit": 0, "trim": 1, "initiate": 2, "add": 3, "probation": 4, "hold": 5, "no_action": 6}
    decisions.sort(key=lambda d: (action_order.get(d["action"], 9), -d["action_score"]))

    return {
        "id": review.id,
        "review_date": _ser(review.review_date),
        "review_type": review.review_type,
        "holdings_reviewed": review.holdings_reviewed,
        "candidates_reviewed": review.candidates_reviewed,
        "turnover_pct": review.turnover_pct,
        "created_at": _ser(review.created_at),
        "decisions": decisions,
    }


def get_portfolio_positions(session: Session) -> list[dict]:
    """Return all active portfolio positions."""
    positions = (
        session.query(PortfolioPosition)
        .filter_by(status=PositionStatus.ACTIVE)
        .order_by(desc(PortfolioPosition.current_weight))
        .all()
    )
    return [
        {
            "id": p.id,
            "ticker": p.ticker,
            "thesis_id": p.thesis_id,
            "entry_date": _ser(p.entry_date),
            "avg_cost": p.avg_cost,
            "current_weight": p.current_weight,
            "target_weight": p.target_weight,
            "conviction_score": p.conviction_score,
            "zone_state": _ser(p.zone_state),
            "probation_flag": p.probation_flag,
        }
        for p in positions
    ]


def get_candidates(session: Session) -> list[dict]:
    """Return all candidates."""
    candidates = (
        session.query(Candidate)
        .order_by(desc(Candidate.conviction_score))
        .all()
    )
    return [
        {
            "id": c.id,
            "ticker": c.ticker,
            "conviction_score": c.conviction_score,
            "buyable_flag": c.buyable_flag,
            "zone_state": _ser(c.zone_state),
            "watch_reason": c.watch_reason,
        }
        for c in candidates
    ]


# ---------------------------------------------------------------------------
# E. Execution / paper trading status
# ---------------------------------------------------------------------------

def get_latest_execution(session: Session) -> Optional[dict]:
    """Return latest execution intents and paper fills."""
    latest_intent = (
        session.query(ExecutionIntentRecord)
        .order_by(desc(ExecutionIntentRecord.generated_at))
        .first()
    )
    if not latest_intent:
        return None

    review_date = latest_intent.review_date

    intents = (
        session.query(ExecutionIntentRecord)
        .filter_by(review_date=review_date)
        .order_by(ExecutionIntentRecord.generated_at)
        .all()
    )

    fills = (
        session.query(PaperFillRecord)
        .filter_by(review_date=review_date)
        .order_by(PaperFillRecord.filled_at)
        .all()
    )

    snapshot = (
        session.query(PaperPortfolioSnapshotRecord)
        .order_by(desc(PaperPortfolioSnapshotRecord.snapshot_at))
        .first()
    )

    return {
        "review_date": review_date,
        "intents": [
            {
                "ticker": i.ticker,
                "side": i.side,
                "action_type": i.action_type,
                "target_weight_before": i.target_weight_before,
                "target_weight_after": i.target_weight_after,
                "notional_delta": i.notional_delta,
                "estimated_shares": i.estimated_shares,
                "is_validated": i.is_validated,
                "is_blocked": i.is_blocked,
                "block_reasons": json.loads(i.block_reasons) if i.block_reasons else [],
            }
            for i in intents
        ],
        "fills": [
            {
                "fill_id": f.fill_id,
                "ticker": f.ticker,
                "side": f.side,
                "action_type": f.action_type,
                "shares": f.shares,
                "fill_price": f.fill_price,
                "notional": f.notional,
                "transaction_cost": f.transaction_cost,
                "filled_at": _ser(f.filled_at),
            }
            for f in fills
        ],
        "snapshot": {
            "snapshot_date": _ser(snapshot.snapshot_date),
            "total_value": snapshot.total_value,
            "cash": snapshot.cash,
            "invested": snapshot.invested,
            "num_positions": snapshot.num_positions,
            "positions": json.loads(snapshot.positions_json) if snapshot.positions_json else {},
            "weights": json.loads(snapshot.weights_json) if snapshot.weights_json else {},
        } if snapshot else None,
    }


# ---------------------------------------------------------------------------
# F. Company summary
# ---------------------------------------------------------------------------

def get_company_overview(session: Session, ticker: str) -> Optional[dict]:
    """Return company overview from DB."""
    company = session.query(Company).filter_by(ticker=ticker).first()
    if not company:
        return None

    doc_count = session.query(func.count(Document.id)).filter_by(
        primary_company_ticker=ticker
    ).scalar() or 0

    claim_count = (
        session.query(func.count(Claim.id))
        .join(Document, Document.id == Claim.document_id)
        .filter(Document.primary_company_ticker == ticker)
        .scalar() or 0
    )

    thesis_count = session.query(func.count(Thesis.id)).filter_by(
        company_ticker=ticker, status_active=True
    ).scalar() or 0

    position = (
        session.query(PortfolioPosition)
        .filter_by(ticker=ticker, status=PositionStatus.ACTIVE)
        .first()
    )

    candidate = session.query(Candidate).filter_by(ticker=ticker).first()

    return {
        "ticker": ticker,
        "name": company.name,
        "sector": company.sector,
        "industry": company.industry,
        "documents": doc_count,
        "claims": claim_count,
        "theses": thesis_count,
        "is_owned": position is not None,
        "current_weight": position.current_weight if position else None,
        "zone_state": _ser(position.zone_state) if position else None,
        "is_candidate": candidate is not None,
    }


# ---------------------------------------------------------------------------
# G. System status overview
# ---------------------------------------------------------------------------

def get_system_status(session: Session) -> dict:
    """Return high-level system status counts."""
    return {
        "companies": session.query(func.count(Company.ticker)).scalar() or 0,
        "documents": session.query(func.count(Document.id)).scalar() or 0,
        "claims": session.query(func.count(Claim.id)).scalar() or 0,
        "theses": session.query(func.count(Thesis.id)).filter_by(status_active=True).scalar() or 0,
        "themes": session.query(func.count(Theme.id)).scalar() or 0,
        "active_positions": (
            session.query(func.count(PortfolioPosition.id))
            .filter_by(status=PositionStatus.ACTIVE)
            .scalar() or 0
        ),
        "candidates": session.query(func.count(Candidate.id)).scalar() or 0,
        "reviews": session.query(func.count(PortfolioReview.id)).scalar() or 0,
        "paper_fills": session.query(func.count(PaperFillRecord.id)).scalar() or 0,
        "latest_document_at": _ser(
            session.query(func.max(Document.ingested_at)).scalar()
        ),
        "latest_review_at": _ser(
            session.query(func.max(PortfolioReview.created_at)).scalar()
        ),
    }


# ---------------------------------------------------------------------------
# H. Event timeline (pipeline stages for a document)
# ---------------------------------------------------------------------------

def get_event_timeline(session: Session, doc_id: int) -> list[dict]:
    """Build a pipeline event timeline for a document."""
    doc = session.get(Document, doc_id)
    if not doc:
        return []

    events = []

    # INGEST
    events.append({
        "stage": "INGEST",
        "ticker": doc.primary_company_ticker or "—",
        "detail": _ser(doc.source_type) or "",
        "status": "OK",
        "timestamp": _ser(doc.ingested_at),
    })

    # CLAIMS
    claims = doc.claims or []
    if claims:
        novelty_counts = {}
        for cl in claims:
            nt = _ser(cl.novelty_type) or "unknown"
            novelty_counts[nt] = novelty_counts.get(nt, 0) + 1
        novelty_str = " ".join(f"{k.upper()}={v}" for k, v in sorted(novelty_counts.items()))
        events.append({
            "stage": "CLAIMS",
            "ticker": doc.primary_company_ticker or "—",
            "detail": f"{len(claims)} extracted",
            "extra": novelty_str,
            "status": "OK",
            "timestamp": _ser(doc.ingested_at),
        })
    else:
        events.append({
            "stage": "CLAIMS",
            "ticker": doc.primary_company_ticker or "—",
            "detail": "0 extracted",
            "status": "NONE",
            "timestamp": _ser(doc.ingested_at),
        })

    # MEMORY (prior claims/themes retrieved for context)
    claim_ids = [cl.id for cl in claims]
    if claim_ids:
        theme_count = (
            session.query(func.count(func.distinct(ClaimThemeLink.theme_id)))
            .filter(ClaimThemeLink.claim_id.in_(claim_ids))
            .scalar() or 0
        )
        events.append({
            "stage": "MEMORY",
            "ticker": doc.primary_company_ticker or "—",
            "detail": f"{len(claims)} claims / {theme_count} themes",
            "status": "OK",
            "timestamp": _ser(doc.ingested_at),
        })

    # THESIS (check for thesis state changes linked to these claims)
    if claim_ids:
        thesis_links = (
            session.query(ThesisClaimLink)
            .filter(ThesisClaimLink.claim_id.in_(claim_ids))
            .all()
        )
        linked_thesis_ids = list({tl.thesis_id for tl in thesis_links})

        for tid in linked_thesis_ids:
            thesis = session.get(Thesis, tid)
            if not thesis:
                continue

            # Get latest state history entry
            latest_history = (
                session.query(ThesisStateHistory)
                .filter_by(thesis_id=tid)
                .order_by(desc(ThesisStateHistory.created_at))
                .limit(2)
                .all()
            )

            if len(latest_history) >= 2:
                prev = latest_history[1]
                curr = latest_history[0]
                state_change = f"{_ser(prev.state)} -> {_ser(curr.state)}"
                score_change = ""
                if prev.conviction_score is not None and curr.conviction_score is not None:
                    score_change = f"{prev.conviction_score:.0f} -> {curr.conviction_score:.0f}"
            else:
                state_change = _ser(thesis.state) or ""
                score_change = f"{thesis.conviction_score:.0f}" if thesis.conviction_score else ""

            events.append({
                "stage": "THESIS",
                "ticker": thesis.company_ticker,
                "detail": state_change,
                "status": "OK",
                "timestamp": _ser(thesis.updated_at),
            })
            if score_change:
                events.append({
                    "stage": "SCORE",
                    "ticker": thesis.company_ticker,
                    "detail": score_change,
                    "status": "OK",
                    "timestamp": _ser(thesis.updated_at),
                })

    return events


# ---------------------------------------------------------------------------
# I. All tickers (for dropdowns / search)
# ---------------------------------------------------------------------------

def get_all_tickers(session: Session) -> list[dict]:
    """Return all companies."""
    companies = session.query(Company).order_by(Company.ticker).all()
    return [
        {"ticker": c.ticker, "name": c.name, "sector": c.sector}
        for c in companies
    ]


# ---------------------------------------------------------------------------
# J. Graph-backed views (pass-through to graph_queries)
# ---------------------------------------------------------------------------

def get_graph_company_view(cg, ticker: str) -> dict:
    """Get graph subgraph data for a company (vis.js format)."""
    from graph_visualizer import graph_to_vis_json, company_view
    sub = company_view(cg, ticker, depth=2)
    vis = graph_to_vis_json(sub)
    vis["summary"] = sub.summary()
    return vis


def get_graph_thesis_view(cg, thesis_id: int) -> dict:
    """Get graph subgraph for a thesis."""
    from graph_visualizer import graph_to_vis_json, thesis_view
    sub = thesis_view(cg, thesis_id, depth=2)
    vis = graph_to_vis_json(sub)
    vis["summary"] = sub.summary()
    return vis


def get_graph_theme_view(cg, theme_id: int) -> dict:
    """Get graph subgraph for a theme."""
    from graph_visualizer import graph_to_vis_json, theme_view
    sub = theme_view(cg, theme_id, depth=2)
    vis = graph_to_vis_json(sub)
    vis["summary"] = sub.summary()
    return vis


def get_graph_full_summary(cg) -> dict:
    """Get full graph stats."""
    return cg.summary()


# ---------------------------------------------------------------------------
# K. Demo subjects / what-changed / narrative export
# ---------------------------------------------------------------------------

def get_demo_subjects(session: Session) -> dict:
    """Return interesting demo subjects for the operator console."""

    # --- latest_thesis_delta ---
    latest_thesis_delta = None
    # Find thesis with most recent history entry that shows a state change
    # by scanning recent history pairs
    recent_histories = (
        session.query(ThesisStateHistory)
        .order_by(desc(ThesisStateHistory.created_at))
        .limit(200)
        .all()
    )
    # Group by thesis_id, keep only first 2 per thesis
    from collections import defaultdict
    by_thesis: dict[int, list] = defaultdict(list)
    for h in recent_histories:
        if len(by_thesis[h.thesis_id]) < 2:
            by_thesis[h.thesis_id].append(h)

    # Find the thesis whose most recent history entry is newest AND shows a change
    for tid in by_thesis:
        entries = by_thesis[tid]
        if len(entries) >= 2:
            curr, prev = entries[0], entries[1]
            if _ser(curr.state) != _ser(prev.state) or curr.conviction_score != prev.conviction_score:
                thesis = session.get(Thesis, tid)
                if thesis:
                    # Find a document_id via claim linked to this thesis
                    doc_id_link = (
                        session.query(Claim.document_id)
                        .join(ThesisClaimLink, ThesisClaimLink.claim_id == Claim.id)
                        .filter(ThesisClaimLink.thesis_id == tid)
                        .order_by(desc(Claim.id))
                        .first()
                    )
                    conv_delta = None
                    if curr.conviction_score is not None and prev.conviction_score is not None:
                        conv_delta = round(curr.conviction_score - prev.conviction_score, 2)
                    latest_thesis_delta = {
                        "thesis_id": tid,
                        "ticker": thesis.company_ticker,
                        "title": thesis.title,
                        "old_state": _ser(prev.state),
                        "new_state": _ser(curr.state),
                        "old_conviction": prev.conviction_score,
                        "new_conviction": curr.conviction_score,
                        "conviction_delta": conv_delta,
                        "document_id": doc_id_link[0] if doc_id_link else None,
                    }
                    break

    # --- latest_actionable ---
    latest_actionable = None
    actionable_dec = (
        session.query(PortfolioDecision)
        .filter(PortfolioDecision.action.notin_([ActionType.NO_ACTION, ActionType.HOLD]))
        .order_by(desc(PortfolioDecision.generated_at))
        .first()
    )
    if actionable_dec:
        latest_actionable = {
            "ticker": actionable_dec.ticker,
            "action": _ser(actionable_dec.action),
            "action_score": actionable_dec.action_score,
            "reason_codes": json.loads(actionable_dec.reason_codes) if actionable_dec.reason_codes else [],
            "review_id": actionable_dec.review_id,
        }

    # --- latest_thesis_trigger ---
    latest_thesis_trigger = None
    trigger_row = (
        session.query(Document.id, Document.primary_company_ticker, Document.title,
                      ThesisClaimLink.thesis_id)
        .join(Claim, Claim.document_id == Document.id)
        .join(ThesisClaimLink, ThesisClaimLink.claim_id == Claim.id)
        .order_by(desc(Document.ingested_at))
        .first()
    )
    if trigger_row:
        thesis_obj = session.get(Thesis, trigger_row[3])
        latest_thesis_trigger = {
            "doc_id": trigger_row[0],
            "ticker": trigger_row[1],
            "title": trigger_row[2],
            "thesis_id": trigger_row[3],
            "thesis_title": thesis_obj.title if thesis_obj else None,
        }

    # --- latest_conviction_change ---
    latest_conviction_change = None
    best_delta = 0.0
    for tid in by_thesis:
        entries = by_thesis[tid]
        if len(entries) >= 2:
            curr, prev = entries[0], entries[1]
            if curr.conviction_score is not None and prev.conviction_score is not None:
                delta = abs(curr.conviction_score - prev.conviction_score)
                if delta > best_delta:
                    best_delta = delta
                    thesis = session.get(Thesis, tid)
                    if thesis:
                        latest_conviction_change = {
                            "thesis_id": tid,
                            "ticker": thesis.company_ticker,
                            "old_conviction": prev.conviction_score,
                            "new_conviction": curr.conviction_score,
                            "delta": round(curr.conviction_score - prev.conviction_score, 2),
                        }

    return {
        "latest_thesis_delta": latest_thesis_delta,
        "latest_actionable": latest_actionable,
        "latest_thesis_trigger": latest_thesis_trigger,
        "latest_conviction_change": latest_conviction_change,
    }


def get_what_changed(session: Session, doc_id: int) -> Optional[dict]:
    """Build a 'what changed' summary for a document."""
    doc = session.get(Document, doc_id)
    if not doc:
        return None

    # --- document ---
    document = {
        "id": doc.id,
        "title": doc.title,
        "ticker": doc.primary_company_ticker,
        "source_type": _ser(doc.source_type),
        "published_at": _ser(doc.published_at),
    }

    # --- new_information (claims) ---
    claims = doc.claims or []
    new_information = [
        {
            "text_short": cl.claim_text_short,
            "claim_type": _ser(cl.claim_type),
            "direction": _ser(cl.direction),
            "strength": cl.strength,
            "novelty_type": _ser(cl.novelty_type),
        }
        for cl in claims
    ]

    # --- retrieved_memory (themes linked to claims) ---
    claim_ids = [cl.id for cl in claims]
    retrieved_memory = []
    if claim_ids:
        theme_rows = (
            session.query(Theme.theme_name)
            .join(ClaimThemeLink, ClaimThemeLink.theme_id == Theme.id)
            .filter(ClaimThemeLink.claim_id.in_(claim_ids))
            .distinct()
            .all()
        )
        retrieved_memory = [r[0] for r in theme_rows]

    # --- thesis_delta ---
    thesis_delta = []
    if claim_ids:
        thesis_links = (
            session.query(ThesisClaimLink)
            .filter(ThesisClaimLink.claim_id.in_(claim_ids))
            .all()
        )
        linked_thesis_ids = list({tl.thesis_id for tl in thesis_links})
        for tid in linked_thesis_ids:
            thesis = session.get(Thesis, tid)
            if not thesis:
                continue
            history = (
                session.query(ThesisStateHistory)
                .filter_by(thesis_id=tid)
                .order_by(desc(ThesisStateHistory.created_at))
                .limit(2)
                .all()
            )
            if len(history) >= 2:
                curr, prev = history[0], history[1]
                conv_delta = None
                if curr.conviction_score is not None and prev.conviction_score is not None:
                    conv_delta = round(curr.conviction_score - prev.conviction_score, 2)
                thesis_delta.append({
                    "thesis_id": tid,
                    "title": thesis.title,
                    "old_state": _ser(prev.state),
                    "new_state": _ser(curr.state),
                    "old_conviction": prev.conviction_score,
                    "new_conviction": curr.conviction_score,
                    "conviction_delta": conv_delta,
                })
            else:
                thesis_delta.append({
                    "thesis_id": tid,
                    "title": thesis.title,
                    "old_state": None,
                    "new_state": _ser(thesis.state),
                    "old_conviction": None,
                    "new_conviction": thesis.conviction_score,
                    "conviction_delta": None,
                })

    # --- recommendation_delta ---
    # Get tickers from claims' linked companies
    recommendation_delta = []
    if claim_ids:
        ticker_rows = (
            session.query(ClaimCompanyLink.company_ticker)
            .filter(ClaimCompanyLink.claim_id.in_(claim_ids))
            .distinct()
            .all()
        )
        tickers = [r[0] for r in ticker_rows]
        if doc.primary_company_ticker and doc.primary_company_ticker not in tickers:
            tickers.append(doc.primary_company_ticker)

        if tickers:
            # Get latest review
            latest_review = (
                session.query(PortfolioReview)
                .order_by(desc(PortfolioReview.created_at))
                .first()
            )
            if latest_review:
                decisions = (
                    session.query(PortfolioDecision)
                    .filter(
                        PortfolioDecision.review_id == latest_review.id,
                        PortfolioDecision.ticker.in_(tickers),
                    )
                    .all()
                )
                for dec in decisions:
                    recommendation_delta.append({
                        "ticker": dec.ticker,
                        "action": _ser(dec.action),
                        "action_score": dec.action_score,
                        "reason_codes": json.loads(dec.reason_codes) if dec.reason_codes else [],
                        "rationale": dec.rationale,
                    })

    # --- why_it_matters ---
    parts = []
    parts.append(f"{len(new_information)} new claims")
    for td in thesis_delta:
        if td["old_state"] and td["new_state"] and td["old_state"] != td["new_state"]:
            parts.append(f"thesis {td['old_state']} -> {td['new_state']}")
        if td["conviction_delta"] is not None:
            parts.append(f"conviction {td['conviction_delta']:+.0f}")
    why_it_matters = ", ".join(parts)

    return {
        "document": document,
        "new_information": new_information,
        "retrieved_memory": retrieved_memory,
        "thesis_delta": thesis_delta,
        "recommendation_delta": recommendation_delta,
        "why_it_matters": why_it_matters,
    }


def get_narrative_export(session: Session, doc_id: int) -> list[dict]:
    """Build a list of narrative pipeline steps for a document."""
    doc = session.get(Document, doc_id)
    if not doc:
        return []

    steps = []

    # Stage INGEST
    ticker = doc.primary_company_ticker or "unknown"
    steps.append({
        "stage": "INGEST",
        "text": f"Document ingested: {doc.title} ({_ser(doc.source_type)}) for {ticker}",
    })

    # Stage CLAIMS
    claims = doc.claims or []
    novelty_counts: dict[str, int] = {}
    for cl in claims:
        nt = _ser(cl.novelty_type) or "unknown"
        novelty_counts[nt] = novelty_counts.get(nt, 0) + 1
    count_str = ", ".join(f"{k}={v}" for k, v in sorted(novelty_counts.items()))
    steps.append({
        "stage": "CLAIMS",
        "text": f"{len(claims)} claims extracted: {count_str}",
    })

    # Stage MEMORY
    claim_ids = [cl.id for cl in claims]
    theme_names = []
    if claim_ids:
        theme_rows = (
            session.query(Theme.theme_name)
            .join(ClaimThemeLink, ClaimThemeLink.theme_id == Theme.id)
            .filter(ClaimThemeLink.claim_id.in_(claim_ids))
            .distinct()
            .all()
        )
        theme_names = [r[0] for r in theme_rows]
    steps.append({
        "stage": "MEMORY",
        "text": f"Retrieved {len(theme_names)} themes: {', '.join(theme_names)}",
    })

    # Stage THESIS
    linked_thesis_ids = []
    if claim_ids:
        thesis_links = (
            session.query(ThesisClaimLink)
            .filter(ThesisClaimLink.claim_id.in_(claim_ids))
            .all()
        )
        linked_thesis_ids = list({tl.thesis_id for tl in thesis_links})
        for tid in linked_thesis_ids:
            thesis = session.get(Thesis, tid)
            if not thesis:
                continue
            history = (
                session.query(ThesisStateHistory)
                .filter_by(thesis_id=tid)
                .order_by(desc(ThesisStateHistory.created_at))
                .limit(2)
                .all()
            )
            if len(history) >= 2:
                curr, prev = history[0], history[1]
                conv_delta = None
                if curr.conviction_score is not None and prev.conviction_score is not None:
                    conv_delta = round(curr.conviction_score - prev.conviction_score, 2)
                steps.append({
                    "stage": "THESIS",
                    "text": (
                        f"Thesis '{thesis.title}' {_ser(prev.state)} -> {_ser(curr.state)}, "
                        f"conviction {prev.conviction_score} -> {curr.conviction_score} ({conv_delta})"
                    ),
                })
            else:
                steps.append({
                    "stage": "THESIS",
                    "text": (
                        f"Thesis '{thesis.title}' {_ser(thesis.state)}, "
                        f"conviction {thesis.conviction_score}"
                    ),
                })

    # Stage RECOMMENDATION
    if claim_ids:
        ticker_rows = (
            session.query(ClaimCompanyLink.company_ticker)
            .filter(ClaimCompanyLink.claim_id.in_(claim_ids))
            .distinct()
            .all()
        )
        tickers = [r[0] for r in ticker_rows]
        if doc.primary_company_ticker and doc.primary_company_ticker not in tickers:
            tickers.append(doc.primary_company_ticker)

        if tickers:
            latest_review = (
                session.query(PortfolioReview)
                .order_by(desc(PortfolioReview.created_at))
                .first()
            )
            if latest_review:
                decisions = (
                    session.query(PortfolioDecision)
                    .filter(
                        PortfolioDecision.review_id == latest_review.id,
                        PortfolioDecision.ticker.in_(tickers),
                    )
                    .all()
                )
                for dec in decisions:
                    steps.append({
                        "stage": "RECOMMENDATION",
                        "text": f"{dec.ticker}: {_ser(dec.action)} (score {dec.action_score}) — {dec.rationale}",
                    })

    # Stage GRAPH
    steps.append({
        "stage": "GRAPH",
        "text": f"Graph evidence: {len(linked_thesis_ids)} linked theses, {len(theme_names)} linked themes",
    })

    return steps
