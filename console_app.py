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
from datetime import datetime
from typing import Optional

from flask import Flask, jsonify, request, send_from_directory

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
        demo_mode: If True, UI shows DEMO badge.
    """
    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
    app = Flask(__name__, static_folder=static_dir)
    app.config["DEMO_MODE"] = demo_mode
    app.config["GRAPH"] = graph

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
        with get_session() as session:
            status = get_system_status(session)
            status["demo_mode"] = app.config["DEMO_MODE"]
            status["graph_loaded"] = app.config["GRAPH"] is not None
            if app.config["GRAPH"]:
                status["graph_summary"] = get_graph_full_summary(app.config["GRAPH"])
            return jsonify(status)

    # -----------------------------------------------------------------------
    # API: Documents
    # -----------------------------------------------------------------------

    @app.route("/api/documents/recent")
    def api_recent_documents():
        limit = request.args.get("limit", 50, type=int)
        with get_session() as session:
            docs = get_recent_documents(session, limit=min(limit, 200))
            return jsonify(docs)

    @app.route("/api/documents/<int:doc_id>")
    def api_document_detail(doc_id):
        with get_session() as session:
            detail = get_document_detail(session, doc_id)
            if not detail:
                return jsonify({"error": "Document not found"}), 404
            return jsonify(detail)

    @app.route("/api/documents/<int:doc_id>/timeline")
    def api_document_timeline(doc_id):
        with get_session() as session:
            timeline = get_event_timeline(session, doc_id)
            if not timeline:
                return jsonify({"error": "Document not found"}), 404
            return jsonify(timeline)

    # -----------------------------------------------------------------------
    # API: Theses
    # -----------------------------------------------------------------------

    @app.route("/api/theses/<int:thesis_id>")
    def api_thesis_detail(thesis_id):
        with get_session() as session:
            detail = get_thesis_detail(session, thesis_id)
            if not detail:
                return jsonify({"error": "Thesis not found"}), 404
            return jsonify(detail)

    @app.route("/api/tickers/<ticker>/theses")
    def api_ticker_theses(ticker):
        with get_session() as session:
            theses = get_ticker_theses(session, ticker.upper())
            return jsonify(theses)

    # -----------------------------------------------------------------------
    # API: Portfolio
    # -----------------------------------------------------------------------

    @app.route("/api/reviews/latest")
    def api_latest_review():
        with get_session() as session:
            review = get_latest_review(session)
            if not review:
                return jsonify({"error": "No reviews found"}), 404
            return jsonify(review)

    @app.route("/api/positions")
    def api_positions():
        with get_session() as session:
            return jsonify(get_portfolio_positions(session))

    @app.route("/api/candidates")
    def api_candidates():
        with get_session() as session:
            return jsonify(get_candidates(session))

    # -----------------------------------------------------------------------
    # API: Execution
    # -----------------------------------------------------------------------

    @app.route("/api/execution/latest")
    def api_latest_execution():
        with get_session() as session:
            execution = get_latest_execution(session)
            if not execution:
                return jsonify({"error": "No execution data"}), 404
            return jsonify(execution)

    # -----------------------------------------------------------------------
    # API: Companies
    # -----------------------------------------------------------------------

    @app.route("/api/tickers")
    def api_tickers():
        with get_session() as session:
            return jsonify(get_all_tickers(session))

    @app.route("/api/tickers/<ticker>/overview")
    def api_company_overview(ticker):
        with get_session() as session:
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

    return app
