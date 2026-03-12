"""Flask web server for the operator console.

Serves:
  - Single-page console UI (static/console.html)
  - REST API endpoints for system state (read-only)
  - Graph subgraph data (vis.js format)

All endpoints are read-only. No mutations.
"""
from __future__ import annotations

import json
import logging
import os
from contextlib import contextmanager
from datetime import datetime
from typing import Optional

from flask import Flask, jsonify, request, send_from_directory

import db as db_module
from db import get_session
from console_api import (
    get_recent_documents,
    get_document_detail,
    get_thesis_detail,
    get_ticker_theses,
    get_latest_review,
    get_portfolio_positions,
    get_candidates,
    get_latest_execution,
    get_company_overview,
    get_system_status,
    get_event_timeline,
    get_all_tickers,
    get_graph_company_view,
    get_graph_thesis_view,
    get_graph_theme_view,
    get_graph_full_summary,
    get_demo_subjects,
    get_what_changed,
    get_narrative_export,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_console_app(
    graph=None,
    demo_mode: bool = False,
) -> Flask:
    """Create the Flask console app.

    Args:
        graph: Optional ConsensusGraph instance for graph views.
        demo_mode: If True, seeds in-memory demo fixtures and shows DEMO badge.
    """
    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
    app = Flask(__name__, static_folder=static_dir)
    app.config["DEMO_MODE"] = demo_mode
    app.config["GRAPH"] = graph
    app.config["DEMO_FIXTURES_LOADED"] = False
    app.config["STARTUP_WARNINGS"] = []
    app.config["STARTED_AT"] = datetime.utcnow().isoformat()

    # --- Demo mode: swap DB session to in-memory with fixtures ---
    if demo_mode:
        try:
            from demo_fixtures import create_demo_session_factory
            _engine, DemoSessionFactory = create_demo_session_factory()

            @contextmanager
            def demo_get_session():
                session = DemoSessionFactory()
                try:
                    yield session
                    session.commit()
                except Exception:
                    session.rollback()
                    raise
                finally:
                    session.close()

            db_module.get_session = demo_get_session
            app.config["DEMO_FIXTURES_LOADED"] = True
            logger.info("Demo fixtures loaded into in-memory database.")
        except Exception as e:
            warning = f"Failed to load demo fixtures: {e}"
            app.config["STARTUP_WARNINGS"].append(warning)
            logger.warning(warning)

    # -----------------------------------------------------------------------
    # Static / SPA
    # -----------------------------------------------------------------------

    @app.route("/")
    def index():
        return send_from_directory(static_dir, "console.html")

    @app.route("/static/<path:path>")
    def static_files(path):
        return send_from_directory(static_dir, path)

    # -----------------------------------------------------------------------
    # API: System status
    # -----------------------------------------------------------------------

    @app.route("/api/status")
    def api_status():
        with db_module.get_session() as session:
            status = get_system_status(session)
            status["demo_mode"] = app.config["DEMO_MODE"]
            status["graph_loaded"] = app.config["GRAPH"] is not None
            if app.config["GRAPH"]:
                status["graph_summary"] = get_graph_full_summary(app.config["GRAPH"])
            return jsonify(status)

    # -----------------------------------------------------------------------
    # API: Health / debug
    # -----------------------------------------------------------------------

    @app.route("/api/health")
    def api_health():
        with db_module.get_session() as session:
            status = get_system_status(session)
            return jsonify({
                "mode": "demo" if app.config["DEMO_MODE"] else "real",
                "demo_fixtures_loaded": app.config["DEMO_FIXTURES_LOADED"],
                "started_at": app.config["STARTED_AT"],
                "graph_loaded": app.config["GRAPH"] is not None,
                "startup_warnings": app.config["STARTUP_WARNINGS"],
                "counts": {
                    "companies": status.get("companies", 0),
                    "documents": status.get("documents", 0),
                    "claims": status.get("claims", 0),
                    "theses": status.get("theses", 0),
                    "themes": status.get("themes", 0),
                    "active_positions": status.get("active_positions", 0),
                    "candidates": status.get("candidates", 0),
                    "reviews": status.get("reviews", 0),
                },
                "api_reachable": True,
            })

    # -----------------------------------------------------------------------
    # API: Documents
    # -----------------------------------------------------------------------

    @app.route("/api/documents/recent")
    def api_recent_documents():
        limit = request.args.get("limit", 50, type=int)
        with db_module.get_session() as session:
            docs = get_recent_documents(session, limit=min(limit, 200))
            return jsonify(docs)

    @app.route("/api/documents/<int:doc_id>")
    def api_document_detail(doc_id):
        with db_module.get_session() as session:
            detail = get_document_detail(session, doc_id)
            if not detail:
                return jsonify({"error": "Document not found"}), 404
            return jsonify(detail)

    @app.route("/api/documents/<int:doc_id>/timeline")
    def api_document_timeline(doc_id):
        with db_module.get_session() as session:
            timeline = get_event_timeline(session, doc_id)
            if not timeline:
                return jsonify({"error": "Document not found"}), 404
            return jsonify(timeline)

    # -----------------------------------------------------------------------
    # API: Theses
    # -----------------------------------------------------------------------

    @app.route("/api/theses/<int:thesis_id>")
    def api_thesis_detail(thesis_id):
        with db_module.get_session() as session:
            detail = get_thesis_detail(session, thesis_id)
            if not detail:
                return jsonify({"error": "Thesis not found"}), 404
            return jsonify(detail)

    @app.route("/api/tickers/<ticker>/theses")
    def api_ticker_theses(ticker):
        with db_module.get_session() as session:
            theses = get_ticker_theses(session, ticker.upper())
            return jsonify(theses)

    # -----------------------------------------------------------------------
    # API: Portfolio
    # -----------------------------------------------------------------------

    @app.route("/api/reviews/latest")
    def api_latest_review():
        with db_module.get_session() as session:
            review = get_latest_review(session)
            if not review:
                return jsonify({"error": "No reviews found"}), 404
            return jsonify(review)

    @app.route("/api/positions")
    def api_positions():
        with db_module.get_session() as session:
            return jsonify(get_portfolio_positions(session))

    @app.route("/api/candidates")
    def api_candidates():
        with db_module.get_session() as session:
            return jsonify(get_candidates(session))

    # -----------------------------------------------------------------------
    # API: Execution
    # -----------------------------------------------------------------------

    @app.route("/api/execution/latest")
    def api_latest_execution():
        with db_module.get_session() as session:
            execution = get_latest_execution(session)
            if not execution:
                return jsonify({"error": "No execution data"}), 404
            return jsonify(execution)

    # -----------------------------------------------------------------------
    # API: Companies
    # -----------------------------------------------------------------------

    @app.route("/api/tickers")
    def api_tickers():
        with db_module.get_session() as session:
            return jsonify(get_all_tickers(session))

    @app.route("/api/tickers/<ticker>/overview")
    def api_company_overview(ticker):
        with db_module.get_session() as session:
            overview = get_company_overview(session, ticker.upper())
            if not overview:
                return jsonify({"error": "Company not found"}), 404
            return jsonify(overview)

    # -----------------------------------------------------------------------
    # API: Graph
    # -----------------------------------------------------------------------

    @app.route("/api/graph/company/<ticker>")
    def api_graph_company(ticker):
        cg = app.config.get("GRAPH")
        if not cg:
            return jsonify({"error": "Graph not loaded"}), 503
        data = get_graph_company_view(cg, ticker.upper())
        return jsonify(data)

    @app.route("/api/graph/thesis/<int:thesis_id>")
    def api_graph_thesis(thesis_id):
        cg = app.config.get("GRAPH")
        if not cg:
            return jsonify({"error": "Graph not loaded"}), 503
        data = get_graph_thesis_view(cg, thesis_id)
        return jsonify(data)

    @app.route("/api/graph/theme/<int:theme_id>")
    def api_graph_theme(theme_id):
        cg = app.config.get("GRAPH")
        if not cg:
            return jsonify({"error": "Graph not loaded"}), 503
        data = get_graph_theme_view(cg, theme_id)
        return jsonify(data)

    # -----------------------------------------------------------------------
    # API: Demo helpers
    # -----------------------------------------------------------------------

    @app.route("/api/demo/subjects")
    def api_demo_subjects():
        with db_module.get_session() as session:
            subjects = get_demo_subjects(session)
            return jsonify(subjects)

    @app.route("/api/documents/<int:doc_id>/what-changed")
    def api_what_changed(doc_id):
        with db_module.get_session() as session:
            result = get_what_changed(session, doc_id)
            if not result:
                return jsonify({"error": "Document not found"}), 404
            return jsonify(result)

    @app.route("/api/documents/<int:doc_id>/narrative")
    def api_narrative(doc_id):
        with db_module.get_session() as session:
            result = get_narrative_export(session, doc_id)
            if not result:
                return jsonify({"error": "Document not found"}), 404
            return jsonify(result)

    return app
