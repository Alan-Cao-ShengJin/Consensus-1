"""Tests for portfolio weights, composition, changes, and cadence features.

Verifies:
- Daily cadence produces daily review dates
- Portfolio composition CSV includes weight columns
- Portfolio changes CSV includes meaningful events with weights
- Replay API returns weight-change drilldown fields
- ActionOutcome carries weight data
- Missing data handled gracefully
"""
from __future__ import annotations

import csv
import json
import os
from datetime import date, timedelta

import pytest

from replay_api import replay_bp, set_base_dir, _load_csv
from replay_engine import generate_review_dates


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _write_csv(path, rows):
    if not rows:
        return
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def weight_proof_dir(tmp_path):
    """Create a proof-pack with weight/composition artifacts."""
    run_dir = tmp_path / "weight_run"
    run_dir.mkdir()

    manifest = {
        "manifest_version": "1.0",
        "run_id": "weight_run",
        "generated_at": "2026-01-01T00:00:00",
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
        "cadence_days": 7,
        "degraded_flags": [],
        "warnings_count": 0,
        "warnings": [],
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest))

    summary = {
        "report_version": "2.0",
        "evaluation": {
            "metrics": {"total_return_pct": 3.5, "total_review_dates": 4},
            "benchmark": {},
            "diagnostics": {"action_counts": {"initiate": 2, "hold": 3, "exit": 1}},
            "failure_analysis": {},
        },
    }
    (run_dir / "summary.json").write_text(json.dumps(summary))

    # decisions.csv with weight columns
    _write_csv(run_dir / "decisions.csv", [
        {"review_date": "2025-08-07", "ticker": "AAPL", "action": "initiate",
         "thesis_conviction": "60", "action_score": "60", "conviction_bucket": "medium",
         "prior_weight": "0.0", "new_weight": "3.0", "weight_change": "3.0",
         "suggested_weight": "3.0", "rationale": "New position"},
        {"review_date": "2025-08-14", "ticker": "AAPL", "action": "hold",
         "thesis_conviction": "65", "action_score": "0", "conviction_bucket": "medium",
         "prior_weight": "3.0", "new_weight": "3.0", "weight_change": "0.0",
         "suggested_weight": "", "rationale": "Maintain"},
        {"review_date": "2025-08-14", "ticker": "MSFT", "action": "initiate",
         "thesis_conviction": "70", "action_score": "70", "conviction_bucket": "high",
         "prior_weight": "0.0", "new_weight": "3.0", "weight_change": "3.0",
         "suggested_weight": "3.0", "rationale": "Cloud growth"},
        {"review_date": "2025-08-21", "ticker": "MSFT", "action": "exit",
         "thesis_conviction": "25", "action_score": "80", "conviction_bucket": "low",
         "prior_weight": "3.2", "new_weight": "0.0", "weight_change": "-3.2",
         "suggested_weight": "0.0", "rationale": "Thesis broken"},
    ])

    # action_outcomes.csv with weight columns
    _write_csv(run_dir / "action_outcomes.csv", [
        {"review_date": "2025-08-07", "ticker": "AAPL", "action": "initiate",
         "thesis_conviction": "60", "action_score": "60", "conviction_bucket": "medium",
         "prior_weight": "0.0", "new_weight": "3.0", "weight_change": "3.0",
         "price_at_decision": "180.0", "forward_5d_pct": "1.5", "forward_20d_pct": "3.0", "forward_60d_pct": "5.0"},
        {"review_date": "2025-08-14", "ticker": "MSFT", "action": "initiate",
         "thesis_conviction": "70", "action_score": "70", "conviction_bucket": "high",
         "prior_weight": "0.0", "new_weight": "3.0", "weight_change": "3.0",
         "price_at_decision": "350.0", "forward_5d_pct": "-1.0", "forward_20d_pct": "-2.0", "forward_60d_pct": "-3.0"},
        {"review_date": "2025-08-21", "ticker": "MSFT", "action": "exit",
         "thesis_conviction": "25", "action_score": "80", "conviction_bucket": "low",
         "prior_weight": "3.2", "new_weight": "0.0", "weight_change": "-3.2",
         "price_at_decision": "340.0", "forward_5d_pct": "2.0", "forward_20d_pct": "5.0", "forward_60d_pct": "8.0"},
    ])

    # portfolio_composition.csv
    _write_csv(run_dir / "portfolio_composition.csv", [
        {"review_date": "2025-08-07", "ticker": "AAPL", "weight_pct": "3.0",
         "market_value": "30000.0", "portfolio_total": "1000000.0",
         "cash": "970000.0", "cash_weight_pct": "97.0", "num_positions": "1"},
        {"review_date": "2025-08-14", "ticker": "AAPL", "weight_pct": "3.1",
         "market_value": "31500.0", "portfolio_total": "1015000.0",
         "cash": "948500.0", "cash_weight_pct": "93.4", "num_positions": "2"},
        {"review_date": "2025-08-14", "ticker": "MSFT", "weight_pct": "3.5",
         "market_value": "35000.0", "portfolio_total": "1015000.0",
         "cash": "948500.0", "cash_weight_pct": "93.4", "num_positions": "2"},
        {"review_date": "2025-08-21", "ticker": "AAPL", "weight_pct": "3.2",
         "market_value": "32000.0", "portfolio_total": "1005000.0",
         "cash": "973000.0", "cash_weight_pct": "96.8", "num_positions": "1"},
    ])

    # portfolio_changes.csv
    _write_csv(run_dir / "portfolio_changes.csv", [
        {"review_date": "2025-08-07", "ticker": "AAPL", "event_type": "initiate",
         "prior_weight": "0.0", "new_weight": "3.0", "delta_weight": "3.0",
         "conviction_before": "0.0", "conviction_after": "60.0",
         "rationale_summary": "New position", "forward_5d_pct": "1.5",
         "forward_20d_pct": "3.0", "forward_60d_pct": "5.0"},
        {"review_date": "2025-08-14", "ticker": "MSFT", "event_type": "initiate",
         "prior_weight": "0.0", "new_weight": "3.0", "delta_weight": "3.0",
         "conviction_before": "0.0", "conviction_after": "70.0",
         "rationale_summary": "Cloud growth", "forward_5d_pct": "-1.0",
         "forward_20d_pct": "-2.0", "forward_60d_pct": "-3.0"},
        {"review_date": "2025-08-21", "ticker": "MSFT", "event_type": "exit",
         "prior_weight": "3.2", "new_weight": "0.0", "delta_weight": "-3.2",
         "conviction_before": "70.0", "conviction_after": "25.0",
         "rationale_summary": "Thesis broken", "forward_5d_pct": "2.0",
         "forward_20d_pct": "5.0", "forward_60d_pct": "8.0"},
    ])

    # portfolio_timeline.csv
    _write_csv(run_dir / "portfolio_timeline.csv", [
        {"review_date": "2025-08-07", "total_value": "1000000.0", "cash": "970000.0",
         "invested": "30000.0", "num_positions": "1", "cash_weight_pct": "97.0",
         "top_holding": "AAPL", "top_holding_weight": "3.0"},
        {"review_date": "2025-08-14", "total_value": "1015000.0", "cash": "948500.0",
         "invested": "66500.0", "num_positions": "2", "cash_weight_pct": "93.4",
         "top_holding": "MSFT", "top_holding_weight": "3.5"},
        {"review_date": "2025-08-21", "total_value": "1005000.0", "cash": "973000.0",
         "invested": "32000.0", "num_positions": "1", "cash_weight_pct": "96.8",
         "top_holding": "AAPL", "top_holding_weight": "3.2"},
    ])

    set_base_dir(str(tmp_path))
    return tmp_path


@pytest.fixture
def app(weight_proof_dir):
    """Create Flask test app."""
    from flask import Flask
    app = Flask(__name__)
    app.register_blueprint(replay_bp)
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# Test: Daily cadence generates daily review dates
# ---------------------------------------------------------------------------

class TestDailyCadence:
    def test_daily_cadence_produces_daily_dates(self):
        start = date(2025, 1, 6)  # Monday
        end = date(2025, 1, 12)   # Sunday
        dates = generate_review_dates(start, end, cadence_days=1)
        assert len(dates) == 7
        # Every consecutive day
        for i in range(1, len(dates)):
            assert (dates[i] - dates[i-1]).days == 1

    def test_weekly_cadence_produces_weekly_dates(self):
        start = date(2025, 1, 6)
        end = date(2025, 2, 3)
        dates = generate_review_dates(start, end, cadence_days=7)
        assert len(dates) == 5
        for i in range(1, len(dates)):
            assert (dates[i] - dates[i-1]).days == 7

    def test_cadence_1_vs_7_more_dates(self):
        start = date(2025, 1, 1)
        end = date(2025, 3, 31)
        daily = generate_review_dates(start, end, cadence_days=1)
        weekly = generate_review_dates(start, end, cadence_days=7)
        assert len(daily) > len(weekly)
        assert len(daily) == 90  # 90 days
        assert len(weekly) == 13  # ceil(90/7)


# ---------------------------------------------------------------------------
# Test: Portfolio composition CSV has weight columns
# ---------------------------------------------------------------------------

class TestPortfolioComposition:
    def test_composition_loads(self, weight_proof_dir):
        rows = _load_csv("weight_run", "portfolio_composition.csv")
        assert len(rows) == 4

    def test_composition_has_weight_fields(self, weight_proof_dir):
        rows = _load_csv("weight_run", "portfolio_composition.csv")
        for r in rows:
            assert "weight_pct" in r
            assert "market_value" in r
            assert "portfolio_total" in r
            assert "cash_weight_pct" in r
            assert "num_positions" in r

    def test_composition_weights_reasonable(self, weight_proof_dir):
        rows = _load_csv("weight_run", "portfolio_composition.csv")
        for r in rows:
            wt = float(r["weight_pct"])
            assert 0 <= wt <= 100, f"Weight {wt} out of range"

    def test_composition_api(self, client):
        resp = client.get("/api/replay/runs/weight_run/composition")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 4

    def test_composition_at_date(self, client):
        resp = client.get("/api/replay/runs/weight_run/composition/2025-08-14")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["review_date"] == "2025-08-14"
        assert len(data["positions"]) == 2  # AAPL + MSFT


# ---------------------------------------------------------------------------
# Test: Portfolio changes CSV
# ---------------------------------------------------------------------------

class TestPortfolioChanges:
    def test_changes_loads(self, weight_proof_dir):
        rows = _load_csv("weight_run", "portfolio_changes.csv")
        assert len(rows) == 3  # 2 initiates + 1 exit

    def test_changes_excludes_holds(self, weight_proof_dir):
        rows = _load_csv("weight_run", "portfolio_changes.csv")
        for r in rows:
            assert r["event_type"] != "hold"

    def test_changes_has_weight_delta(self, weight_proof_dir):
        rows = _load_csv("weight_run", "portfolio_changes.csv")
        for r in rows:
            assert "delta_weight" in r
            assert "prior_weight" in r
            assert "new_weight" in r
            assert "conviction_before" in r
            assert "conviction_after" in r

    def test_changes_api(self, client):
        resp = client.get("/api/replay/runs/weight_run/changes")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 3

    def test_initiate_has_positive_delta(self, weight_proof_dir):
        rows = _load_csv("weight_run", "portfolio_changes.csv")
        inits = [r for r in rows if r["event_type"] == "initiate"]
        for r in inits:
            assert float(r["delta_weight"]) > 0

    def test_exit_has_negative_delta(self, weight_proof_dir):
        rows = _load_csv("weight_run", "portfolio_changes.csv")
        exits = [r for r in rows if r["event_type"] == "exit"]
        for r in exits:
            assert float(r["delta_weight"]) < 0


# ---------------------------------------------------------------------------
# Test: Decisions CSV includes weight columns
# ---------------------------------------------------------------------------

class TestDecisionWeights:
    def test_decisions_have_weight_fields(self, weight_proof_dir):
        rows = _load_csv("weight_run", "decisions.csv")
        for r in rows:
            assert "prior_weight" in r
            assert "new_weight" in r
            assert "weight_change" in r

    def test_hold_has_zero_weight_change(self, weight_proof_dir):
        rows = _load_csv("weight_run", "decisions.csv")
        holds = [r for r in rows if r["action"] == "hold"]
        for r in holds:
            assert float(r["weight_change"]) == 0.0

    def test_outcomes_have_weight_fields(self, weight_proof_dir):
        rows = _load_csv("weight_run", "action_outcomes.csv")
        for r in rows:
            assert "prior_weight" in r
            assert "new_weight" in r
            assert "weight_change" in r


# ---------------------------------------------------------------------------
# Test: Drilldown API returns weight context
# ---------------------------------------------------------------------------

class TestDrilldown:
    def test_drilldown_returns_decision_with_weights(self, client):
        resp = client.get("/api/replay/runs/weight_run/drilldown/2025-08-07/AAPL")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["decision"] is not None
        assert data["decision"]["prior_weight"] == "0.0"
        assert data["decision"]["new_weight"] == "3.0"

    def test_drilldown_returns_change_event(self, client):
        resp = client.get("/api/replay/runs/weight_run/drilldown/2025-08-21/MSFT")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["change"] is not None
        assert data["change"]["event_type"] == "exit"
        assert float(data["change"]["delta_weight"]) < 0

    def test_drilldown_includes_portfolio_composition(self, client):
        resp = client.get("/api/replay/runs/weight_run/drilldown/2025-08-14/MSFT")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "portfolio_at_date" in data
        assert len(data["portfolio_at_date"]) == 2  # AAPL + MSFT

    def test_drilldown_nonexistent(self, client):
        resp = client.get("/api/replay/runs/weight_run/drilldown/2025-01-01/XYZ")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["decision"] is None


# ---------------------------------------------------------------------------
# Test: Timeline CSV includes new fields
# ---------------------------------------------------------------------------

class TestTimelineEnriched:
    def test_timeline_has_cash_weight(self, weight_proof_dir):
        rows = _load_csv("weight_run", "portfolio_timeline.csv")
        for r in rows:
            assert "cash_weight_pct" in r
            wt = float(r["cash_weight_pct"])
            assert 0 <= wt <= 100

    def test_timeline_has_top_holding(self, weight_proof_dir):
        rows = _load_csv("weight_run", "portfolio_timeline.csv")
        for r in rows:
            assert "top_holding" in r
            assert "top_holding_weight" in r


# ---------------------------------------------------------------------------
# Test: ActionOutcome weight fields
# ---------------------------------------------------------------------------

class TestActionOutcomeWeights:
    def test_action_outcome_has_weight_fields(self):
        from historical_evaluation import ActionOutcome
        ao = ActionOutcome(
            review_date=date(2025, 1, 1),
            ticker="AAPL",
            action="initiate",
            thesis_conviction=60.0,
            action_score=60.0,
            conviction_bucket="medium",
            rationale="test",
            prior_weight=0.0,
            new_weight=3.0,
            weight_change=3.0,
        )
        d = ao.to_dict()
        assert d["prior_weight"] == 0.0
        assert d["new_weight"] == 3.0
        assert d["weight_change"] == 3.0


# ---------------------------------------------------------------------------
# Test: Missing artifacts handled gracefully
# ---------------------------------------------------------------------------

class TestMissingArtifacts:
    def test_missing_composition_returns_empty(self, weight_proof_dir):
        # Remove the file
        os.remove(weight_proof_dir / "weight_run" / "portfolio_composition.csv")
        rows = _load_csv("weight_run", "portfolio_composition.csv")
        assert rows == []

    def test_missing_changes_returns_empty(self, weight_proof_dir):
        os.remove(weight_proof_dir / "weight_run" / "portfolio_changes.csv")
        rows = _load_csv("weight_run", "portfolio_changes.csv")
        assert rows == []

    def test_drilldown_without_changes(self, client, weight_proof_dir):
        os.remove(weight_proof_dir / "weight_run" / "portfolio_changes.csv")
        resp = client.get("/api/replay/runs/weight_run/drilldown/2025-08-07/AAPL")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["change"] is None
        assert data["decision"] is not None
