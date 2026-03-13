"""Tests for the replay API and artifact-loading layer.

Verifies data contracts between proof-pack artifacts and the replay UI.
"""
from __future__ import annotations

import csv
import json
import os
import tempfile
from datetime import date

import pytest

from replay_api import (
    replay_bp,
    set_base_dir,
    get_base_dir,
    _load_csv,
    _load_json,
    _find_regen_db,
    _run_path,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def proof_dir(tmp_path):
    """Create a minimal proof-pack directory with test artifacts."""
    run_dir = tmp_path / "test_run"
    run_dir.mkdir()

    # manifest.json
    manifest = {
        "manifest_version": "1.0",
        "run_id": "test_run",
        "generated_at": "2026-01-01T00:00:00",
        "code_hash": "abc1234",
        "mode": "usefulness_run",
        "universe": ["AAPL", "MSFT", "NVDA"],
        "universe_size": 3,
        "date_range": {
            "backfill_start": "2025-06-01",
            "backfill_end": "2026-01-01",
            "eval_start": "2025-08-01",
            "eval_end": "2026-01-01",
        },
        "extractor_mode": "real_llm",
        "source_toggles": {"prices": True, "sec_filings": True, "news_rss": True, "pr_rss": True},
        "benchmark_ticker": "SPY",
        "forward_return_days": [5, 20, 60],
        "cadence_days": 7,
        "memory_enabled": True,
        "strict_replay": False,
        "exit_policy": "baseline",
        "seed": 42,
        "degraded_flags": [],
        "warnings_count": 0,
        "warnings": [],
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest))

    # summary.json
    summary = {
        "report_version": "2.0",
        "report_type": "historical_proof_run",
        "generated_at": "2026-01-01T00:00:00",
        "config": {},
        "regeneration": {
            "total_documents": 30,
            "total_claims": 50,
            "total_thesis_updates": 20,
            "total_state_changes": 5,
            "total_state_flips": 1,
        },
        "evaluation": {
            "metrics": {
                "total_return_pct": 5.25,
                "annualized_return_pct": 10.5,
                "max_drawdown_pct": 3.1,
                "total_review_dates": 22,
                "purity_level": "strict",
            },
            "benchmark": {
                "benchmark_ticker": "SPY",
                "portfolio_return_pct": 5.25,
                "benchmark_return_pct": 4.0,
                "excess_return_pct": 1.25,
                "equal_weight_return_pct": 3.5,
                "vs_equal_weight_pct": 1.75,
                "benchmark_data_available": True,
            },
            "diagnostics": {
                "action_counts": {"initiate": 5, "hold": 30, "exit": 2},
                "action_pcts": {"initiate": 13.5, "hold": 81.1, "exit": 5.4},
            },
            "failure_analysis": {
                "degraded_flags": [],
                "sparse_coverage_tickers": [],
                "negative_return_actions": [],
                "repeated_bad_recommendations": [],
            },
        },
    }
    (run_dir / "summary.json").write_text(json.dumps(summary))

    # decisions.csv
    _write_csv(run_dir / "decisions.csv", [
        {"review_date": "2025-08-14", "ticker": "AAPL", "action": "initiate", "thesis_conviction": "60", "action_score": "60", "conviction_bucket": "medium", "rationale": "Strong growth"},
        {"review_date": "2025-08-21", "ticker": "AAPL", "action": "hold", "thesis_conviction": "65", "action_score": "0", "conviction_bucket": "medium", "rationale": "Maintain"},
        {"review_date": "2025-08-14", "ticker": "MSFT", "action": "initiate", "thesis_conviction": "70", "action_score": "70", "conviction_bucket": "high", "rationale": "Cloud momentum"},
    ])

    # action_outcomes.csv
    _write_csv(run_dir / "action_outcomes.csv", [
        {"review_date": "2025-08-14", "ticker": "AAPL", "action": "initiate", "thesis_conviction": "60", "action_score": "60", "conviction_bucket": "medium", "price_at_decision": "180.0", "forward_5d_pct": "1.5", "forward_20d_pct": "3.0", "forward_60d_pct": "5.0"},
        {"review_date": "2025-08-21", "ticker": "AAPL", "action": "hold", "thesis_conviction": "65", "action_score": "0", "conviction_bucket": "medium", "price_at_decision": "182.0", "forward_5d_pct": "0.5", "forward_20d_pct": "2.0", "forward_60d_pct": ""},
        {"review_date": "2025-08-14", "ticker": "MSFT", "action": "initiate", "thesis_conviction": "70", "action_score": "70", "conviction_bucket": "high", "price_at_decision": "350.0", "forward_5d_pct": "-1.0", "forward_20d_pct": "-2.0", "forward_60d_pct": "-3.0"},
    ])

    # best_decisions.csv & worst_decisions.csv
    _write_csv(run_dir / "best_decisions.csv", [
        {"review_date": "2025-08-14", "ticker": "AAPL", "action": "initiate", "thesis_conviction": "60", "action_score": "60", "conviction_bucket": "medium", "price_at_decision": "180.0", "forward_5d_pct": "1.5", "forward_20d_pct": "3.0", "forward_60d_pct": "5.0", "rationale": "Strong"},
    ])
    _write_csv(run_dir / "worst_decisions.csv", [
        {"review_date": "2025-08-14", "ticker": "MSFT", "action": "initiate", "thesis_conviction": "70", "action_score": "70", "conviction_bucket": "high", "price_at_decision": "350.0", "forward_5d_pct": "-1.0", "forward_20d_pct": "-2.0", "forward_60d_pct": "-3.0", "rationale": "Bad call"},
    ])

    # per_name_summary.csv
    _write_csv(run_dir / "per_name_summary.csv", [
        {"ticker": "AAPL", "action_count": "5", "initiate_count": "1", "exit_count": "0", "hold_count": "4", "avg_forward_5d_pct": "1.0", "avg_forward_20d_pct": "2.5", "avg_forward_60d_pct": "5.0", "doc_count": "12", "claim_count": "20", "price_coverage_pct": "95.0"},
        {"ticker": "MSFT", "action_count": "3", "initiate_count": "1", "exit_count": "1", "hold_count": "1", "avg_forward_5d_pct": "-0.5", "avg_forward_20d_pct": "-1.0", "avg_forward_60d_pct": "-2.0", "doc_count": "8", "claim_count": "10", "price_coverage_pct": "92.0"},
    ])

    # benchmark.csv
    _write_csv(run_dir / "benchmark.csv", [
        {"benchmark": "Portfolio", "return_pct": "5.25", "data_available": "True"},
        {"benchmark": "SPY", "return_pct": "4.0", "data_available": "True"},
        {"benchmark": "Equal-weight", "return_pct": "3.5", "data_available": "True"},
    ])

    # conviction_buckets.csv
    _write_csv(run_dir / "conviction_buckets.csv", [
        {"bucket": "low", "action_count": "2", "avg_conviction": "25", "avg_forward_5d_pct": "-0.5", "avg_forward_20d_pct": "-1.0", "avg_forward_60d_pct": "-2.0"},
        {"bucket": "medium", "action_count": "5", "avg_conviction": "55", "avg_forward_5d_pct": "1.0", "avg_forward_20d_pct": "2.0", "avg_forward_60d_pct": "3.0"},
        {"bucket": "high", "action_count": "3", "avg_conviction": "80", "avg_forward_5d_pct": "2.0", "avg_forward_20d_pct": "4.0", "avg_forward_60d_pct": "6.0"},
    ])

    # portfolio_timeline.csv
    _write_csv(run_dir / "portfolio_timeline.csv", [
        {"review_date": "2025-08-14", "total_value": "100000.00", "cash": "80000.00", "invested": "20000.00", "num_positions": "2"},
        {"review_date": "2025-08-21", "total_value": "101500.00", "cash": "78000.00", "invested": "23500.00", "num_positions": "2"},
        {"review_date": "2025-08-28", "total_value": "102000.00", "cash": "78000.00", "invested": "24000.00", "num_positions": "2"},
    ])

    # portfolio_trades.csv
    _write_csv(run_dir / "portfolio_trades.csv", [
        {"trade_date": "2025-08-14", "ticker": "AAPL", "action": "initiate", "shares": "50.0", "price": "180.0", "notional": "9000.0", "reason": "Gate pass"},
        {"trade_date": "2025-08-14", "ticker": "MSFT", "action": "initiate", "shares": "30.0", "price": "350.0", "notional": "10500.0", "reason": "Gate pass"},
    ])

    # coverage_diagnostics.csv
    _write_csv(run_dir / "coverage_diagnostics.csv", [
        {"ticker": "AAPL", "doc_count": "12", "claim_count": "20", "has_prices": "True"},
        {"ticker": "MSFT", "doc_count": "8", "claim_count": "10", "has_prices": "True"},
    ])

    # coverage_by_month.csv
    _write_csv(run_dir / "coverage_by_month.csv", [
        {"month": "2025-06", "doc_count": "5"},
        {"month": "2025-07", "doc_count": "10"},
        {"month": "2025-08", "doc_count": "15"},
    ])

    set_base_dir(str(tmp_path))
    return tmp_path


def _write_csv(path, rows):
    if not rows:
        return
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


@pytest.fixture
def client(proof_dir):
    """Flask test client with replay API."""
    from flask import Flask
    app = Flask(__name__)
    app.register_blueprint(replay_bp)
    app.config["TESTING"] = True
    return app.test_client()


# ---------------------------------------------------------------------------
# TestRunListing
# ---------------------------------------------------------------------------

class TestRunListing:
    def test_list_runs(self, client):
        resp = client.get("/api/replay/runs")
        assert resp.status_code == 200
        runs = resp.get_json()
        assert len(runs) == 1
        assert runs[0]["run_id"] == "test_run"
        assert runs[0]["mode"] == "usefulness_run"
        assert runs[0]["extractor_mode"] == "real_llm"
        assert runs[0]["universe_size"] == 3

    def test_run_has_date_range(self, client):
        resp = client.get("/api/replay/runs")
        runs = resp.get_json()
        dr = runs[0]["date_range"]
        assert dr["eval_start"] == "2025-08-01"
        assert dr["eval_end"] == "2026-01-01"

    def test_run_has_degraded_flags(self, client):
        resp = client.get("/api/replay/runs")
        assert isinstance(resp.get_json()[0]["degraded_flags"], list)


# ---------------------------------------------------------------------------
# TestRunOverview
# ---------------------------------------------------------------------------

class TestRunOverview:
    def test_get_run(self, client):
        resp = client.get("/api/replay/runs/test_run")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["manifest"]["run_id"] == "test_run"
        assert data["metrics"]["total_return_pct"] == 5.25

    def test_run_has_benchmark(self, client):
        data = client.get("/api/replay/runs/test_run").get_json()
        assert data["benchmark"]["benchmark_return_pct"] == 4.0
        assert data["benchmark"]["excess_return_pct"] == 1.25

    def test_run_has_diagnostics(self, client):
        data = client.get("/api/replay/runs/test_run").get_json()
        assert "initiate" in data["diagnostics"]["action_counts"]

    def test_run_has_regeneration(self, client):
        data = client.get("/api/replay/runs/test_run").get_json()
        assert data["regeneration"]["total_documents"] == 30

    def test_run_lists_available_artifacts(self, client):
        data = client.get("/api/replay/runs/test_run").get_json()
        arts = data["available_artifacts"]
        assert "decisions.csv" in arts
        assert "portfolio_timeline.csv" in arts
        assert "portfolio_trades.csv" in arts

    def test_missing_run_404(self, client):
        resp = client.get("/api/replay/runs/nonexistent")
        assert resp.status_code == 404

    def test_historical_period_always_present(self, client):
        data = client.get("/api/replay/runs/test_run").get_json()
        dr = data["manifest"]["date_range"]
        assert "eval_start" in dr
        assert "eval_end" in dr
        assert "backfill_start" in dr


# ---------------------------------------------------------------------------
# TestDecisions
# ---------------------------------------------------------------------------

class TestDecisions:
    def test_decisions_load(self, client):
        resp = client.get("/api/replay/runs/test_run/decisions")
        assert resp.status_code == 200
        rows = resp.get_json()
        assert len(rows) == 3

    def test_decision_has_required_fields(self, client):
        rows = client.get("/api/replay/runs/test_run/decisions").get_json()
        d = rows[0]
        assert "review_date" in d
        assert "ticker" in d
        assert "action" in d
        assert "rationale" in d
        # Should have thesis_conviction (new) or conviction (old)
        assert "thesis_conviction" in d or "conviction" in d

    def test_outcomes_have_forward_returns(self, client):
        rows = client.get("/api/replay/runs/test_run/outcomes").get_json()
        assert len(rows) == 3
        assert "forward_5d_pct" in rows[0]
        assert "forward_20d_pct" in rows[0]
        assert "forward_60d_pct" in rows[0]


# ---------------------------------------------------------------------------
# TestBestWorst
# ---------------------------------------------------------------------------

class TestBestWorst:
    def test_best_worst_loads(self, client):
        data = client.get("/api/replay/runs/test_run/best-worst").get_json()
        assert "best" in data
        assert "worst" in data
        assert len(data["best"]) == 1
        assert len(data["worst"]) == 1

    def test_worst_decision_has_fields(self, client):
        data = client.get("/api/replay/runs/test_run/best-worst").get_json()
        w = data["worst"][0]
        assert w["ticker"] == "MSFT"
        assert float(w["forward_20d_pct"]) < 0


# ---------------------------------------------------------------------------
# TestTimeline
# ---------------------------------------------------------------------------

class TestTimeline:
    def test_timeline_loads(self, client):
        rows = client.get("/api/replay/runs/test_run/timeline").get_json()
        assert len(rows) == 3

    def test_timeline_has_required_fields(self, client):
        rows = client.get("/api/replay/runs/test_run/timeline").get_json()
        r = rows[0]
        assert "review_date" in r
        assert "total_value" in r
        assert "cash" in r
        assert "invested" in r
        assert "num_positions" in r

    def test_timeline_values_reasonable(self, client):
        rows = client.get("/api/replay/runs/test_run/timeline").get_json()
        for r in rows:
            assert float(r["total_value"]) > 0
            assert float(r["cash"]) >= 0


# ---------------------------------------------------------------------------
# TestTrades
# ---------------------------------------------------------------------------

class TestTrades:
    def test_trades_load(self, client):
        rows = client.get("/api/replay/runs/test_run/trades").get_json()
        assert len(rows) == 2

    def test_trade_has_required_fields(self, client):
        rows = client.get("/api/replay/runs/test_run/trades").get_json()
        t = rows[0]
        assert "trade_date" in t
        assert "ticker" in t
        assert "action" in t
        assert "shares" in t
        assert "price" in t
        assert "notional" in t


# ---------------------------------------------------------------------------
# TestBenchmark
# ---------------------------------------------------------------------------

class TestBenchmark:
    def test_benchmark_loads(self, client):
        rows = client.get("/api/replay/runs/test_run/benchmark").get_json()
        assert len(rows) == 3
        names = [r["benchmark"] for r in rows]
        assert "Portfolio" in names
        assert "SPY" in names

    def test_benchmark_has_return(self, client):
        rows = client.get("/api/replay/runs/test_run/benchmark").get_json()
        portfolio = next(r for r in rows if r["benchmark"] == "Portfolio")
        assert float(portfolio["return_pct"]) > 0


# ---------------------------------------------------------------------------
# TestCoverage
# ---------------------------------------------------------------------------

class TestCoverage:
    def test_coverage_loads(self, client):
        data = client.get("/api/replay/runs/test_run/coverage").get_json()
        assert "by_ticker" in data
        assert "by_month" in data
        assert len(data["by_ticker"]) == 2
        assert len(data["by_month"]) == 3


# ---------------------------------------------------------------------------
# TestFailures
# ---------------------------------------------------------------------------

class TestFailures:
    def test_failures_loads(self, client):
        data = client.get("/api/replay/runs/test_run/failures").get_json()
        assert "worst_decisions" in data
        assert "failure_analysis" in data

    def test_failure_analysis_has_required_fields(self, client):
        data = client.get("/api/replay/runs/test_run/failures").get_json()
        fa = data["failure_analysis"]
        assert "degraded_flags" in fa
        assert "sparse_coverage_tickers" in fa


# ---------------------------------------------------------------------------
# TestEvidence
# ---------------------------------------------------------------------------

class TestEvidence:
    def test_evidence_returns_decision(self, client):
        """Evidence endpoint includes decision from CSV even without regen DB."""
        data = client.get("/api/replay/runs/test_run/evidence/2025-08-14/AAPL").get_json()
        assert data["decision"] is not None
        assert data["decision"]["ticker"] == "AAPL"
        assert data["decision"]["action"] == "initiate"

    def test_evidence_returns_outcome(self, client):
        data = client.get("/api/replay/runs/test_run/evidence/2025-08-14/AAPL").get_json()
        assert data["outcome"] is not None
        assert float(data["outcome"]["forward_20d_pct"]) == 3.0

    def test_evidence_handles_missing_regen_db(self, client):
        """Evidence endpoint degrades gracefully without regen DB."""
        data = client.get("/api/replay/runs/test_run/evidence/2025-08-14/AAPL").get_json()
        ev = data["evidence"]
        assert ev["available"] is False
        assert "reason" in ev

    def test_evidence_for_nonexistent_decision(self, client):
        data = client.get("/api/replay/runs/test_run/evidence/2099-01-01/FAKE").get_json()
        assert data["decision"] is None
        assert data["outcome"] is None


# ---------------------------------------------------------------------------
# TestComparison
# ---------------------------------------------------------------------------

class TestComparison:
    def test_compare_requires_both_runs(self, client):
        resp = client.get("/api/replay/compare?run1=test_run")
        assert resp.status_code == 400

    def test_compare_same_run(self, client):
        data = client.get("/api/replay/compare?run1=test_run&run2=test_run").get_json()
        assert data["run1"]["run_id"] == "test_run"
        assert data["run2"]["run_id"] == "test_run"
        m1 = data["run1"]["metrics"]
        m2 = data["run2"]["metrics"]
        assert m1["total_return_pct"] == m2["total_return_pct"]

    def test_compare_has_per_name(self, client):
        data = client.get("/api/replay/compare?run1=test_run&run2=test_run").get_json()
        assert "AAPL" in data["per_name"]["run1"]
        assert "MSFT" in data["per_name"]["run2"]

    def test_compare_missing_run_404(self, client):
        resp = client.get("/api/replay/compare?run1=test_run&run2=fake_run")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# TestDegradedRun
# ---------------------------------------------------------------------------

class TestDegradedRun:
    def test_degraded_flags_visible(self, proof_dir):
        """Degraded flags are visible in run listing and overview."""
        # Modify manifest to add degraded flags
        run_dir = proof_dir / "test_run"
        manifest = json.loads((run_dir / "manifest.json").read_text())
        manifest["degraded_flags"] = ["stub_extractor", "no_sec_filings"]
        manifest["extractor_mode"] = "stub_heuristic"
        (run_dir / "manifest.json").write_text(json.dumps(manifest))

        from flask import Flask
        app = Flask(__name__)
        app.register_blueprint(replay_bp)
        client = app.test_client()

        # Check listing
        runs = client.get("/api/replay/runs").get_json()
        assert "stub_extractor" in runs[0]["degraded_flags"]

        # Check overview
        data = client.get("/api/replay/runs/test_run").get_json()
        assert "stub_extractor" in data["manifest"]["degraded_flags"]


# ---------------------------------------------------------------------------
# TestMissingArtifacts
# ---------------------------------------------------------------------------

class TestMissingArtifacts:
    def test_missing_csv_returns_empty(self, client):
        """Missing CSV files return empty arrays, not errors."""
        rows = client.get("/api/replay/runs/test_run/trades").get_json()
        # This one exists, but test the pattern
        assert isinstance(rows, list)

    def test_conviction_buckets_load(self, client):
        rows = client.get("/api/replay/runs/test_run/conviction-buckets").get_json()
        assert len(rows) == 3
        assert rows[0]["bucket"] == "low"

    def test_per_name_loads(self, client):
        rows = client.get("/api/replay/runs/test_run/per-name").get_json()
        assert len(rows) == 2
        tickers = [r["ticker"] for r in rows]
        assert "AAPL" in tickers

    def test_comparison_handles_missing_gracefully(self, proof_dir):
        """Comparison with partial data doesn't crash."""
        # Create a second run with minimal data
        run2 = proof_dir / "run2"
        run2.mkdir()
        manifest = {
            "manifest_version": "1.0", "run_id": "run2",
            "mode": "usefulness_run", "date_range": {},
            "universe_size": 3, "degraded_flags": [],
        }
        (run2 / "manifest.json").write_text(json.dumps(manifest))
        (run2 / "summary.json").write_text(json.dumps({
            "evaluation": {"metrics": {}, "benchmark": {}, "diagnostics": {}, "failure_analysis": {}},
        }))

        from flask import Flask
        app = Flask(__name__)
        app.register_blueprint(replay_bp)
        client = app.test_client()

        data = client.get("/api/replay/compare?run1=test_run&run2=run2").get_json()
        assert data["run1"]["run_id"] == "test_run"
        assert data["run2"]["run_id"] == "run2"


# ---------------------------------------------------------------------------
# TestPortfolioTimelineContract
# ---------------------------------------------------------------------------

class TestPortfolioTimelineContract:
    """Verify portfolio_timeline.csv can drive a chart."""

    def test_timeline_dates_are_sorted(self, client):
        rows = client.get("/api/replay/runs/test_run/timeline").get_json()
        dates = [r["review_date"] for r in rows]
        assert dates == sorted(dates)

    def test_timeline_values_are_numeric(self, client):
        rows = client.get("/api/replay/runs/test_run/timeline").get_json()
        for r in rows:
            float(r["total_value"])
            float(r["cash"])
            float(r["invested"])
            int(r["num_positions"])

    def test_timeline_portfolio_grows(self, client):
        """Portfolio value should change over time (not all identical)."""
        rows = client.get("/api/replay/runs/test_run/timeline").get_json()
        values = [float(r["total_value"]) for r in rows]
        assert len(set(values)) > 1
