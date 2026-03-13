"""Replay API: serves historical proof-pack artifacts for the replay UI.

Flask blueprint that reads CSVs, JSONs, and optionally regen DBs from
proof-pack directories to power the replay and diagnostics UI.

All endpoints are read-only.
"""
from __future__ import annotations

import csv
import json
import logging
import os
from datetime import date, datetime, timedelta
from typing import Optional

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

replay_bp = Blueprint("replay", __name__)

# Base directory — set via set_base_dir() or PROOF_RUNS_DIR env
_BASE_DIR: Optional[str] = None


def get_base_dir() -> str:
    if _BASE_DIR:
        return _BASE_DIR
    return os.environ.get("PROOF_RUNS_DIR", "historical_proof_runs")


def set_base_dir(d: str):
    global _BASE_DIR
    _BASE_DIR = d


def _run_path(run_id: str) -> str:
    """Path-traversal-safe run directory."""
    safe_id = os.path.basename(run_id)
    return os.path.join(get_base_dir(), safe_id)


def _load_csv(run_id: str, filename: str) -> list[dict]:
    path = os.path.join(_run_path(run_id), filename)
    if not os.path.exists(path):
        return []
    # Some CSVs contain em-dash or other non-UTF-8 chars from rationale text
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        return list(csv.DictReader(f))


def _load_json(run_id: str, filename: str) -> dict:
    path = os.path.join(_run_path(run_id), filename)
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _find_regen_db(run_id: str) -> Optional[str]:
    """Find regen DB file for a run."""
    run_dir = _run_path(run_id)
    if os.path.isdir(run_dir):
        for f in os.listdir(run_dir):
            if f.endswith("_regen.db"):
                return os.path.join(run_dir, f)
    # Some runs have regen.db at parent level
    parent = get_base_dir()
    candidate = os.path.join(parent, f"{os.path.basename(run_id)}_regen.db")
    if os.path.exists(candidate):
        return candidate
    return None


# -----------------------------------------------------------------------
# Routes: Run listing & overview
# -----------------------------------------------------------------------

@replay_bp.route("/api/replay/runs")
def list_runs():
    """List all available proof-pack runs with manifest metadata."""
    base = get_base_dir()
    if not os.path.exists(base):
        return jsonify([])

    runs = []
    for name in sorted(os.listdir(base)):
        run_dir = os.path.join(base, name)
        if not os.path.isdir(run_dir):
            continue
        manifest_path = os.path.join(run_dir, "manifest.json")
        if not os.path.exists(manifest_path):
            continue
        try:
            with open(manifest_path) as f:
                m = json.load(f)
            runs.append({
                "run_id": name,
                "mode": m.get("mode"),
                "extractor_mode": m.get("extractor_mode"),
                "date_range": m.get("date_range"),
                "universe_size": m.get("universe_size"),
                "degraded_flags": m.get("degraded_flags", []),
                "exit_policy": m.get("exit_policy", "baseline"),
                "generated_at": m.get("generated_at"),
                "has_regen_db": _find_regen_db(name) is not None,
            })
        except Exception:
            continue
    return jsonify(runs)


@replay_bp.route("/api/replay/runs/<run_id>")
def get_run(run_id):
    """Full run overview: manifest + summary metrics + available artifacts."""
    manifest = _load_json(run_id, "manifest.json")
    if not manifest:
        return jsonify({"error": "Run not found"}), 404

    summary = _load_json(run_id, "summary.json")
    eval_data = summary.get("evaluation", {}) or {}

    run_dir = _run_path(run_id)
    available = [
        f for f in [
            "decisions.csv", "action_outcomes.csv", "best_decisions.csv",
            "worst_decisions.csv", "per_name_summary.csv", "benchmark.csv",
            "conviction_buckets.csv", "coverage_diagnostics.csv",
            "portfolio_timeline.csv", "portfolio_trades.csv",
            "probation_events.csv", "exit_events.csv",
            "memory_comparison.csv", "policy_comparison.csv",
        ]
        if os.path.exists(os.path.join(run_dir, f))
    ]

    return jsonify({
        "manifest": manifest,
        "metrics": eval_data.get("metrics"),
        "benchmark": eval_data.get("benchmark"),
        "diagnostics": eval_data.get("diagnostics"),
        "failure_analysis": eval_data.get("failure_analysis"),
        "regeneration": summary.get("regeneration", {}),
        "available_artifacts": available,
        "has_regen_db": _find_regen_db(run_id) is not None,
    })


# -----------------------------------------------------------------------
# Routes: Artifact data
# -----------------------------------------------------------------------

@replay_bp.route("/api/replay/runs/<run_id>/decisions")
def get_decisions(run_id):
    return jsonify(_load_csv(run_id, "decisions.csv"))


@replay_bp.route("/api/replay/runs/<run_id>/outcomes")
def get_outcomes(run_id):
    return jsonify(_load_csv(run_id, "action_outcomes.csv"))


@replay_bp.route("/api/replay/runs/<run_id>/best-worst")
def get_best_worst(run_id):
    return jsonify({
        "best": _load_csv(run_id, "best_decisions.csv"),
        "worst": _load_csv(run_id, "worst_decisions.csv"),
    })


@replay_bp.route("/api/replay/runs/<run_id>/per-name")
def get_per_name(run_id):
    return jsonify(_load_csv(run_id, "per_name_summary.csv"))


@replay_bp.route("/api/replay/runs/<run_id>/benchmark")
def get_benchmark(run_id):
    return jsonify(_load_csv(run_id, "benchmark.csv"))


@replay_bp.route("/api/replay/runs/<run_id>/conviction-buckets")
def get_conviction_buckets(run_id):
    return jsonify(_load_csv(run_id, "conviction_buckets.csv"))


@replay_bp.route("/api/replay/runs/<run_id>/coverage")
def get_coverage(run_id):
    return jsonify({
        "by_ticker": _load_csv(run_id, "coverage_diagnostics.csv"),
        "by_month": _load_csv(run_id, "coverage_by_month.csv"),
    })


@replay_bp.route("/api/replay/runs/<run_id>/timeline")
def get_timeline(run_id):
    return jsonify(_load_csv(run_id, "portfolio_timeline.csv"))


@replay_bp.route("/api/replay/runs/<run_id>/trades")
def get_trades(run_id):
    return jsonify(_load_csv(run_id, "portfolio_trades.csv"))


@replay_bp.route("/api/replay/runs/<run_id>/failures")
def get_failures(run_id):
    summary = _load_json(run_id, "summary.json")
    return jsonify({
        "probation_events": _load_csv(run_id, "probation_events.csv"),
        "exit_events": _load_csv(run_id, "exit_events.csv"),
        "worst_decisions": _load_csv(run_id, "worst_decisions.csv"),
        "failure_analysis": (summary.get("evaluation", {}) or {}).get("failure_analysis", {}),
    })


# -----------------------------------------------------------------------
# Routes: Evidence drilldown (requires regen DB)
# -----------------------------------------------------------------------

@replay_bp.route("/api/replay/runs/<run_id>/evidence/<review_date>/<ticker>")
def get_evidence(run_id, review_date, ticker):
    """Evidence → thesis → action drilldown for a specific decision."""
    # Decision + outcome from CSVs
    decisions = _load_csv(run_id, "decisions.csv")
    decision = next(
        (d for d in decisions
         if d.get("review_date") == review_date and d.get("ticker") == ticker),
        None,
    )

    outcomes = _load_csv(run_id, "action_outcomes.csv")
    outcome = next(
        (o for o in outcomes
         if o.get("review_date") == review_date and o.get("ticker") == ticker),
        None,
    )

    evidence = _query_evidence_from_regen_db(run_id, review_date, ticker)

    return jsonify({
        "decision": decision,
        "outcome": outcome,
        "evidence": evidence,
    })


def _query_evidence_from_regen_db(
    run_id: str, review_date_str: str, ticker: str,
) -> dict:
    """Query regen DB for the evidence chain leading to a decision."""
    db_path = _find_regen_db(run_id)
    if not db_path or not os.path.exists(db_path):
        return {"available": False, "reason": "Regen DB not found"}

    try:
        from sqlalchemy import create_engine, func
        from sqlalchemy.orm import Session as SASession
        from models import (
            Base, Document, Claim, Thesis, ThesisStateHistory,
        )

        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        session = SASession(engine)

        try:
            rd = date.fromisoformat(review_date_str)
            rd_dt = datetime(rd.year, rd.month, rd.day, 23, 59, 59)
            window_start = rd_dt - timedelta(days=30)

            # Find active thesis for ticker
            thesis = session.query(Thesis).filter(
                Thesis.company_ticker == ticker,
                Thesis.status_active == True,
            ).first()

            if not thesis:
                return {"available": True, "thesis": None, "claims": [], "state_history": []}

            # Thesis state history (conviction trajectory, last 10 entries)
            history_rows = (
                session.query(ThesisStateHistory)
                .filter(
                    ThesisStateHistory.thesis_id == thesis.id,
                    ThesisStateHistory.created_at <= rd_dt,
                )
                .order_by(ThesisStateHistory.created_at.desc())
                .limit(10)
                .all()
            )
            state_history = []
            for h in reversed(history_rows):
                state_history.append({
                    "date": h.created_at.isoformat() if h.created_at else None,
                    "state": h.state.value if hasattr(h.state, "value") else str(h.state),
                    "conviction_score": h.conviction_score,
                    "note": h.note,
                })

            # Recent claims (30-day window before review date)
            claims_query = (
                session.query(Claim)
                .join(Document, Claim.document_id == Document.id)
                .filter(
                    Document.primary_company_ticker == ticker,
                    Document.published_at >= window_start,
                    Document.published_at <= rd_dt,
                )
                .order_by(Document.published_at.desc())
                .limit(20)
            )

            claims_data = []
            for c in claims_query.all():
                claim_dict = {
                    "claim_id": c.id,
                    "text": c.claim_text_short or c.claim_text_normalized or "",
                    "source_excerpt": (c.source_excerpt or "")[:300],
                    "direction": c.direction.value if hasattr(c.direction, "value") else str(c.direction) if c.direction else None,
                    "strength": c.strength,
                    "novelty": c.novelty_type.value if hasattr(c.novelty_type, "value") else str(c.novelty_type) if c.novelty_type else None,
                    "claim_type": c.claim_type.value if hasattr(c.claim_type, "value") else str(c.claim_type) if c.claim_type else None,
                    "published_at": c.published_at.isoformat() if c.published_at else None,
                }

                # Evidence assessment if available
                try:
                    from models import EvidenceAssessment
                    ea = session.query(EvidenceAssessment).filter(
                        EvidenceAssessment.thesis_id == thesis.id,
                        EvidenceAssessment.claim_id == c.id,
                    ).first()
                    if ea:
                        claim_dict["evidence_weight"] = ea.evidence_weight
                        claim_dict["impact"] = ea.impact
                        claim_dict["delta"] = ea.delta
                        claim_dict["freshness_factor"] = ea.freshness_factor
                except Exception:
                    pass  # Table may not exist in older regen DBs

                claims_data.append(claim_dict)

            # Source mix in window
            doc_sources = (
                session.query(
                    Document.source_type,
                    func.count(Document.id),
                )
                .filter(
                    Document.primary_company_ticker == ticker,
                    Document.published_at >= window_start,
                    Document.published_at <= rd_dt,
                )
                .group_by(Document.source_type)
                .all()
            )
            source_mix = {
                str(st.value if hasattr(st, "value") else st): count
                for st, count in doc_sources
            }

            return {
                "available": True,
                "thesis": {
                    "id": thesis.id,
                    "title": thesis.title,
                    "state": thesis.state.value if hasattr(thesis.state, "value") else str(thesis.state),
                    "conviction_score": thesis.conviction_score,
                    "summary": (thesis.summary or "")[:500],
                },
                "state_history": state_history,
                "claims": claims_data,
                "source_mix": source_mix,
                "evidence_window": f"{(rd - timedelta(days=30)).isoformat()} to {review_date_str}",
            }

        finally:
            session.close()
            engine.dispose()

    except Exception as e:
        logger.warning("Evidence query failed for %s/%s/%s: %s", run_id, review_date_str, ticker, e)
        return {"available": False, "reason": str(e)}


# -----------------------------------------------------------------------
# Routes: Comparison
# -----------------------------------------------------------------------

@replay_bp.route("/api/replay/compare")
def compare_runs():
    """Compare two runs side-by-side."""
    run1 = request.args.get("run1")
    run2 = request.args.get("run2")
    if not run1 or not run2:
        return jsonify({"error": "Provide run1 and run2 query params"}), 400

    s1 = _load_json(run1, "summary.json")
    s2 = _load_json(run2, "summary.json")
    m1 = _load_json(run1, "manifest.json")
    m2 = _load_json(run2, "manifest.json")

    if not s1 or not s2:
        return jsonify({"error": "One or both runs not found"}), 404

    def _extract(summary, manifest):
        e = summary.get("evaluation", {}) or {}
        m = e.get("metrics", {}) or {}
        b = e.get("benchmark", {}) or {}
        d = e.get("diagnostics", {}) or {}
        fa = e.get("failure_analysis", {}) or {}
        return {
            "total_return_pct": m.get("total_return_pct"),
            "annualized_return_pct": m.get("annualized_return_pct"),
            "max_drawdown_pct": m.get("max_drawdown_pct"),
            "total_review_dates": m.get("total_review_dates"),
            "benchmark_return_pct": b.get("benchmark_return_pct"),
            "excess_return_pct": b.get("excess_return_pct"),
            "equal_weight_return_pct": b.get("equal_weight_return_pct"),
            "action_counts": d.get("action_counts", {}),
            "degraded_flags": fa.get("degraded_flags", []),
            "exit_policy": manifest.get("exit_policy", "baseline"),
            "extractor_mode": manifest.get("extractor_mode"),
            "memory_enabled": manifest.get("memory_enabled"),
        }

    pn1 = {r["ticker"]: r for r in _load_csv(run1, "per_name_summary.csv")}
    pn2 = {r["ticker"]: r for r in _load_csv(run2, "per_name_summary.csv")}

    return jsonify({
        "run1": {"run_id": run1, "manifest": m1, "metrics": _extract(s1, m1)},
        "run2": {"run_id": run2, "manifest": m2, "metrics": _extract(s2, m2)},
        "per_name": {"run1": pn1, "run2": pn2},
    })
