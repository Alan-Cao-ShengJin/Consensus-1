"""Step 12 tests: live-readiness layer.

Tests:
  - Broker interface read-only contract
  - Mock and file adapters
  - Account sync / reconciliation
  - Approval hardening (state machine, expiry, identity)
  - Live-readiness checks
  - Environment separation
  - No live order path
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from broker_interface import (
    BrokerInterface,
    BrokerPosition,
    BrokerOrder,
    BrokerFill,
    AccountSnapshot,
)
from broker_readonly_adapter import (
    MockBrokerAdapter,
    FileBrokerAdapter,
    create_broker_adapter,
)
from account_sync import (
    InternalState,
    InternalPosition,
    ReconciliationResult,
    reconcile,
    run_account_sync,
    export_reconciliation,
    format_reconciliation_text,
)
from approval_hardened import (
    HardenedApprovalStatus,
    ApprovalRecord,
    create_approval,
    approve,
    reject,
    check_and_expire,
    save_approval,
    load_approval,
    approve_batch_hardened,
    reject_batch_hardened,
)
from live_readiness_checks import (
    check_environment,
    check_sync_freshness,
    check_reconciliation_clean,
    check_approval_current,
    check_intents_consistent,
    check_no_duplicate_batch,
    check_no_live_order_path,
    run_readiness_checks,
    format_readiness_text,
    ReadinessReport,
)
from config import Environment, SystemConfig, get_default_config


# ===================================================================
# Broker Interface
# ===================================================================

class TestBrokerInterface(unittest.TestCase):
    """Broker interface read-only contract."""

    def test_write_methods_raise(self):
        """All write methods raise NotImplementedError."""
        adapter = MockBrokerAdapter()
        with self.assertRaises(NotImplementedError):
            adapter.submit_order("AAPL", "buy", 100)
        with self.assertRaises(NotImplementedError):
            adapter.cancel_order("order-1")
        with self.assertRaises(NotImplementedError):
            adapter.modify_order("order-1", quantity=200)

    def test_submit_order_error_message(self):
        adapter = MockBrokerAdapter()
        try:
            adapter.submit_order("AAPL", "buy", 100)
        except NotImplementedError as e:
            self.assertIn("Step 12", str(e))
            self.assertIn("not implemented", str(e).lower())


class TestMockBrokerAdapter(unittest.TestCase):
    """MockBrokerAdapter tests."""

    def setUp(self):
        self.positions = [
            BrokerPosition(ticker="AAPL", shares=100, market_value=15000, last_price=150.0),
            BrokerPosition(ticker="MSFT", shares=50, market_value=20000, last_price=400.0),
        ]
        self.adapter = MockBrokerAdapter(
            cash=500_000,
            positions=self.positions,
            prices={"AAPL": 150.0, "MSFT": 400.0, "GOOG": 2800.0},
        )

    def test_get_cash(self):
        self.assertEqual(self.adapter.get_cash(), 500_000)

    def test_get_positions(self):
        positions = self.adapter.get_positions()
        self.assertEqual(len(positions), 2)
        tickers = {p.ticker for p in positions}
        self.assertEqual(tickers, {"AAPL", "MSFT"})

    def test_get_account_snapshot(self):
        snap = self.adapter.get_account_snapshot()
        self.assertIsInstance(snap, AccountSnapshot)
        self.assertEqual(snap.cash, 500_000)
        self.assertEqual(snap.position_count, 2)
        self.assertEqual(snap.total_equity, 500_000 + 15000 + 20000)

    def test_get_reference_price(self):
        self.assertEqual(self.adapter.get_reference_price("AAPL"), 150.0)
        self.assertIsNone(self.adapter.get_reference_price("UNKNOWN"))

    def test_get_reference_prices(self):
        prices = self.adapter.get_reference_prices(["AAPL", "GOOG", "UNKNOWN"])
        self.assertEqual(prices, {"AAPL": 150.0, "GOOG": 2800.0})

    def test_get_open_orders_empty(self):
        self.assertEqual(self.adapter.get_open_orders(), [])

    def test_get_recent_fills_empty(self):
        self.assertEqual(self.adapter.get_recent_fills(), [])

    def test_total_equity(self):
        self.assertEqual(self.adapter.total_equity, 535_000)

    def test_snapshot_weights(self):
        snap = self.adapter.get_account_snapshot()
        weights = snap.get_weights()
        self.assertIn("AAPL", weights)
        self.assertIn("MSFT", weights)
        self.assertAlmostEqual(weights["AAPL"], (15000 / 535_000) * 100, places=2)

    def test_with_open_orders(self):
        orders = [
            BrokerOrder(
                order_id="ord-1", ticker="GOOG", side="buy",
                quantity=10, order_type="limit", status="open",
                limit_price=2700.0,
            ),
        ]
        adapter = MockBrokerAdapter(open_orders=orders)
        self.assertEqual(len(adapter.get_open_orders()), 1)

    def test_with_recent_fills(self):
        fills = [
            BrokerFill(
                fill_id="fill-1", ticker="AAPL", side="buy",
                shares=50, price=149.0, notional=7450.0,
                filled_at=datetime.utcnow().isoformat(),
            ),
        ]
        adapter = MockBrokerAdapter(recent_fills=fills)
        self.assertEqual(len(adapter.get_recent_fills()), 1)


class TestFileBrokerAdapter(unittest.TestCase):
    """FileBrokerAdapter tests."""

    def test_load_from_json(self):
        data = {
            "cash": 100_000,
            "total_equity": 200_000,
            "positions": [
                {"ticker": "AAPL", "shares": 50, "market_value": 100_000, "last_price": 2000.0},
            ],
            "open_orders": [],
            "recent_fills": [],
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            path = f.name

        try:
            adapter = FileBrokerAdapter(path)
            snap = adapter.get_account_snapshot()
            self.assertEqual(snap.cash, 100_000)
            self.assertEqual(len(snap.positions), 1)
            self.assertEqual(snap.positions[0].ticker, "AAPL")
            self.assertEqual(adapter.get_reference_price("AAPL"), 2000.0)
        finally:
            os.unlink(path)

    def test_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            FileBrokerAdapter("/nonexistent/path.json")


class TestCreateBrokerAdapter(unittest.TestCase):
    """Factory tests."""

    def test_create_mock(self):
        adapter = create_broker_adapter(mode="mock", cash=100)
        self.assertIsInstance(adapter, MockBrokerAdapter)
        self.assertEqual(adapter.get_cash(), 100)

    def test_create_unknown_raises(self):
        with self.assertRaises(ValueError):
            create_broker_adapter(mode="unknown")

    def test_create_file_without_path_raises(self):
        with self.assertRaises(ValueError):
            create_broker_adapter(mode="file")


# ===================================================================
# Account Snapshot serialization
# ===================================================================

class TestAccountSnapshot(unittest.TestCase):
    """AccountSnapshot data structure tests."""

    def test_to_dict_roundtrip(self):
        snap = AccountSnapshot(
            snapshot_at="2025-01-01T00:00:00",
            cash=500_000, buying_power=500_000, total_equity=600_000,
            positions=[BrokerPosition(ticker="AAPL", shares=100, market_value=100_000)],
            broker_name="test", account_id="ACC-1",
        )
        d = snap.to_dict()
        self.assertEqual(d["cash"], 500_000)
        self.assertEqual(len(d["positions"]), 1)
        self.assertEqual(d["positions"][0]["ticker"], "AAPL")

    def test_invested_value(self):
        snap = AccountSnapshot(
            snapshot_at="now", cash=100, buying_power=100, total_equity=300,
            positions=[
                BrokerPosition(ticker="A", shares=10, market_value=100),
                BrokerPosition(ticker="B", shares=20, market_value=100),
            ],
        )
        self.assertEqual(snap.invested_value, 200)

    def test_get_position(self):
        snap = AccountSnapshot(
            snapshot_at="now", cash=0, buying_power=0, total_equity=100,
            positions=[BrokerPosition(ticker="X", shares=5, market_value=100)],
        )
        self.assertIsNotNone(snap.get_position("X"))
        self.assertIsNone(snap.get_position("Y"))


# ===================================================================
# Reconciliation
# ===================================================================

class TestReconciliation(unittest.TestCase):
    """Account sync reconciliation tests."""

    def _make_internal(self, cash=500_000, positions=None):
        positions = positions or [
            InternalPosition(ticker="AAPL", shares=100, market_value=15000, weight=3.0),
            InternalPosition(ticker="MSFT", shares=50, market_value=20000, weight=4.0),
        ]
        return InternalState(cash=cash, total_value=cash + sum(p.market_value for p in positions), positions=positions)

    def _make_snapshot(self, cash=500_000, positions=None):
        positions = positions or [
            BrokerPosition(ticker="AAPL", shares=100, market_value=15000),
            BrokerPosition(ticker="MSFT", shares=50, market_value=20000),
        ]
        equity = cash + sum(p.market_value for p in positions)
        return AccountSnapshot(
            snapshot_at=datetime.utcnow().isoformat(),
            cash=cash, buying_power=cash, total_equity=equity,
            positions=positions,
        )

    def test_fully_matched(self):
        result = reconcile(self._make_snapshot(), self._make_internal())
        self.assertTrue(result.all_matched)
        self.assertTrue(result.cash_matched)
        self.assertEqual(result.matched_count, 2)
        self.assertEqual(result.mismatch_count, 0)
        self.assertEqual(result.unresolved_count, 0)

    def test_cash_mismatch(self):
        result = reconcile(
            self._make_snapshot(cash=490_000),
            self._make_internal(cash=500_000),
        )
        self.assertFalse(result.cash_matched)
        self.assertAlmostEqual(result.cash_diff, -10_000, places=2)

    def test_share_mismatch(self):
        broker_snap = self._make_snapshot(positions=[
            BrokerPosition(ticker="AAPL", shares=110, market_value=16500),  # 10 more shares
            BrokerPosition(ticker="MSFT", shares=50, market_value=20000),
        ])
        result = reconcile(broker_snap, self._make_internal())
        self.assertFalse(result.all_matched)
        self.assertEqual(result.mismatch_count, 1)
        aapl_diff = next(d for d in result.position_diffs if d.ticker == "AAPL")
        self.assertEqual(aapl_diff.status, "mismatch")
        self.assertAlmostEqual(aapl_diff.shares_diff, 10.0)

    def test_missing_broker_position(self):
        broker_snap = self._make_snapshot(positions=[
            BrokerPosition(ticker="AAPL", shares=100, market_value=15000),
            # MSFT missing
        ])
        result = reconcile(broker_snap, self._make_internal())
        self.assertFalse(result.all_matched)
        self.assertEqual(result.missing_broker_count, 1)
        msft_diff = next(d for d in result.position_diffs if d.ticker == "MSFT")
        self.assertEqual(msft_diff.status, "missing_broker")

    def test_missing_internal_position(self):
        broker_snap = self._make_snapshot(positions=[
            BrokerPosition(ticker="AAPL", shares=100, market_value=15000),
            BrokerPosition(ticker="MSFT", shares=50, market_value=20000),
            BrokerPosition(ticker="GOOG", shares=10, market_value=30000),  # Extra
        ])
        result = reconcile(broker_snap, self._make_internal())
        self.assertEqual(result.missing_internal_count, 1)
        goog_diff = next(d for d in result.position_diffs if d.ticker == "GOOG")
        self.assertEqual(goog_diff.status, "missing_internal")

    def test_reconciliation_to_dict(self):
        result = reconcile(self._make_snapshot(), self._make_internal())
        d = result.to_dict()
        self.assertIn("cash", d)
        self.assertIn("positions", d)
        self.assertIn("all_matched", d)
        self.assertTrue(d["all_matched"])

    def test_format_text(self):
        result = reconcile(self._make_snapshot(), self._make_internal())
        text = format_reconciliation_text(result)
        self.assertIn("ACCOUNT RECONCILIATION", text)
        self.assertIn("ALL MATCHED", text)

    def test_export_artifacts(self):
        snap = self._make_snapshot()
        result = reconcile(snap, self._make_internal())
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = export_reconciliation(result, snap, tmpdir)
            self.assertIn("account_snapshot", paths)
            self.assertIn("reconciliation_report", paths)
            self.assertTrue(os.path.exists(paths["account_snapshot"]))
            self.assertTrue(os.path.exists(paths["reconciliation_report"]))


class TestReconciliationWithIntents(unittest.TestCase):
    """Reconciliation-aware intent review tests."""

    def _make_intent(self, ticker, side, notional_delta=None, estimated_shares=None, action_type=""):
        """Minimal intent-like object for reconciliation."""
        class FakeIntent:
            pass
        intent = FakeIntent()
        intent.ticker = ticker
        intent.side = side
        intent.notional_delta = notional_delta
        intent.estimated_shares = estimated_shares
        intent.action_type = action_type
        return intent

    def test_sell_intent_no_broker_position(self):
        """Trim intent but broker shows no position."""
        broker_snap = AccountSnapshot(
            snapshot_at=datetime.utcnow().isoformat(),
            cash=500_000, buying_power=500_000, total_equity=500_000,
            positions=[],  # No positions at broker
        )
        internal = InternalState(
            cash=400_000, total_value=500_000,
            positions=[InternalPosition(ticker="AAPL", shares=100, market_value=100_000, weight=20.0)],
        )
        intents = [self._make_intent("AAPL", "sell", estimated_shares=50, action_type="TRIM")]

        result = reconcile(broker_snap, internal, order_intents=intents)
        infeasible = [ic for ic in result.intent_checks if not ic.feasible]
        self.assertEqual(len(infeasible), 1)
        self.assertIn("no position to sell", infeasible[0].issues[0].lower())

    def test_buy_intent_insufficient_cash(self):
        """Buy intent but broker cash is insufficient."""
        broker_snap = AccountSnapshot(
            snapshot_at=datetime.utcnow().isoformat(),
            cash=1_000, buying_power=1_000, total_equity=1_000,
            positions=[],
        )
        internal = InternalState(cash=1_000, total_value=1_000, positions=[])
        intents = [self._make_intent("AAPL", "buy", notional_delta=50_000, action_type="INITIATE")]

        result = reconcile(broker_snap, internal, order_intents=intents)
        infeasible = [ic for ic in result.intent_checks if not ic.feasible]
        self.assertEqual(len(infeasible), 1)
        self.assertIn("cash", infeasible[0].issues[0].lower())

    def test_open_order_conflict(self):
        """Existing open order conflicts with new intent."""
        broker_snap = AccountSnapshot(
            snapshot_at=datetime.utcnow().isoformat(),
            cash=500_000, buying_power=500_000, total_equity=500_000,
            positions=[],
            open_orders=[
                BrokerOrder(
                    order_id="ord-1", ticker="AAPL", side="buy",
                    quantity=100, order_type="limit", status="open",
                ),
            ],
        )
        internal = InternalState(cash=500_000, total_value=500_000, positions=[])
        intents = [self._make_intent("AAPL", "sell", action_type="EXIT")]

        result = reconcile(broker_snap, internal, order_intents=intents)
        self.assertEqual(len(result.order_conflicts), 1)
        self.assertEqual(result.order_conflicts[0].conflict_type, "side_mismatch")

    def test_internal_broker_divergence_noted(self):
        """Internal/broker share mismatch noted in intent feasibility."""
        broker_snap = AccountSnapshot(
            snapshot_at=datetime.utcnow().isoformat(),
            cash=500_000, buying_power=500_000, total_equity=600_000,
            positions=[BrokerPosition(ticker="AAPL", shares=80, market_value=100_000)],
        )
        internal = InternalState(
            cash=500_000, total_value=600_000,
            positions=[InternalPosition(ticker="AAPL", shares=100, market_value=100_000, weight=16.7)],
        )
        intents = [self._make_intent("AAPL", "sell", estimated_shares=20, action_type="TRIM")]

        result = reconcile(broker_snap, internal, order_intents=intents)
        aapl_check = next(ic for ic in result.intent_checks if ic.ticker == "AAPL")
        self.assertTrue(any("mismatch" in issue.lower() for issue in aapl_check.issues))


# ===================================================================
# Approval Hardening
# ===================================================================

class TestApprovalStateMachine(unittest.TestCase):
    """Approval state machine tests."""

    def test_create_pending(self):
        record = create_approval("batch-1", run_id="run-1", environment="live_readonly")
        self.assertEqual(record.status, HardenedApprovalStatus.PENDING)
        self.assertEqual(record.batch_id, "batch-1")
        self.assertIsNotNone(record.expires_at)
        self.assertFalse(record.is_terminal)

    def test_approve_from_pending(self):
        record = create_approval("batch-1")
        approve(record, approver_id="user@example.com", approver_name="Test User")
        self.assertEqual(record.status, HardenedApprovalStatus.APPROVED)
        self.assertTrue(record.is_approved)
        self.assertTrue(record.is_terminal)
        self.assertEqual(record.approver_id, "user@example.com")
        self.assertEqual(record.approver_name, "Test User")

    def test_reject_from_pending(self):
        record = create_approval("batch-1")
        reject(record, approver_id="admin", reason="Risk too high")
        self.assertEqual(record.status, HardenedApprovalStatus.REJECTED)
        self.assertEqual(record.rejection_reason, "Risk too high")
        self.assertTrue(record.is_terminal)

    def test_cannot_approve_rejected(self):
        record = create_approval("batch-1")
        reject(record, approver_id="admin", reason="No")
        with self.assertRaises(ValueError):
            approve(record, approver_id="other")

    def test_cannot_reject_approved(self):
        record = create_approval("batch-1")
        approve(record, approver_id="admin")
        with self.assertRaises(ValueError):
            reject(record, approver_id="other", reason="Too late")

    def test_expiry(self):
        record = create_approval("batch-1", expiry_hours=0)
        # Manually set expires_at to the past
        record.expires_at = (datetime.utcnow() - timedelta(hours=1)).isoformat()
        self.assertTrue(record.is_expired)
        check_and_expire(record)
        self.assertEqual(record.status, HardenedApprovalStatus.EXPIRED)

    def test_approve_expired_raises(self):
        record = create_approval("batch-1")
        record.expires_at = (datetime.utcnow() - timedelta(hours=1)).isoformat()
        with self.assertRaises(ValueError) as ctx:
            approve(record, approver_id="admin")
        self.assertIn("expired", str(ctx.exception).lower())

    def test_serialization_roundtrip(self):
        record = create_approval("batch-1", run_id="run-1", environment="live_readonly")
        approve(record, approver_id="admin", approver_name="Admin User")
        d = record.to_dict()
        loaded = ApprovalRecord.from_dict(d)
        self.assertEqual(loaded.batch_id, "batch-1")
        self.assertEqual(loaded.status, HardenedApprovalStatus.APPROVED)
        self.assertEqual(loaded.approver_id, "admin")


class TestApprovalPersistence(unittest.TestCase):
    """File-based approval persistence tests."""

    def test_save_and_load(self):
        record = create_approval("batch-1")
        with tempfile.TemporaryDirectory() as tmpdir:
            save_approval(record, tmpdir)
            loaded = load_approval(tmpdir)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.batch_id, "batch-1")
            self.assertEqual(loaded.status, HardenedApprovalStatus.PENDING)

    def test_load_nonexistent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertIsNone(load_approval(tmpdir))

    def test_approve_batch_hardened(self):
        record = create_approval("batch-1")
        with tempfile.TemporaryDirectory() as tmpdir:
            save_approval(record, tmpdir)
            result = approve_batch_hardened(tmpdir, "batch-1", approver_id="admin")
            self.assertEqual(result.status, HardenedApprovalStatus.APPROVED)
            # Verify persisted
            reloaded = load_approval(tmpdir)
            self.assertEqual(reloaded.status, HardenedApprovalStatus.APPROVED)

    def test_approve_batch_wrong_id(self):
        record = create_approval("batch-1")
        with tempfile.TemporaryDirectory() as tmpdir:
            save_approval(record, tmpdir)
            with self.assertRaises(ValueError):
                approve_batch_hardened(tmpdir, "wrong-id", approver_id="admin")

    def test_reject_batch_hardened(self):
        record = create_approval("batch-1")
        with tempfile.TemporaryDirectory() as tmpdir:
            save_approval(record, tmpdir)
            result = reject_batch_hardened(
                tmpdir, "batch-1", approver_id="admin", reason="Too risky"
            )
            self.assertEqual(result.status, HardenedApprovalStatus.REJECTED)
            self.assertEqual(result.rejection_reason, "Too risky")


# ===================================================================
# Live-Readiness Checks
# ===================================================================

class TestReadinessChecks(unittest.TestCase):
    """Individual readiness check tests."""

    def test_environment_live_readonly_passes(self):
        c = check_environment(Environment.LIVE_READONLY)
        self.assertTrue(c.passed)

    def test_environment_demo_fails(self):
        c = check_environment(Environment.DEMO)
        self.assertFalse(c.passed)

    def test_environment_paper_fails(self):
        c = check_environment(Environment.PAPER)
        self.assertFalse(c.passed)

    def test_environment_live_disabled_fails(self):
        c = check_environment(Environment.LIVE_DISABLED)
        self.assertFalse(c.passed)

    def test_sync_freshness_none_fails(self):
        c = check_sync_freshness(None)
        self.assertFalse(c.passed)

    def test_sync_freshness_recent_passes(self):
        recon = ReconciliationResult(reconciled_at=datetime.utcnow().isoformat())
        c = check_sync_freshness(recon)
        self.assertTrue(c.passed)

    def test_sync_freshness_stale_fails(self):
        old_time = (datetime.utcnow() - timedelta(hours=2)).isoformat()
        recon = ReconciliationResult(reconciled_at=old_time)
        c = check_sync_freshness(recon, max_age_minutes=60)
        self.assertFalse(c.passed)

    def test_reconciliation_clean_passes(self):
        recon = ReconciliationResult(
            reconciled_at=datetime.utcnow().isoformat(),
            all_matched=True, unresolved_count=0, cash_diff=0.0,
        )
        c = check_reconciliation_clean(recon)
        self.assertTrue(c.passed)

    def test_reconciliation_unresolved_fails(self):
        recon = ReconciliationResult(
            reconciled_at=datetime.utcnow().isoformat(),
            unresolved_count=3, cash_diff=0.0,
        )
        c = check_reconciliation_clean(recon)
        self.assertFalse(c.passed)

    def test_reconciliation_cash_mismatch_fails(self):
        recon = ReconciliationResult(
            reconciled_at=datetime.utcnow().isoformat(),
            unresolved_count=0, cash_diff=500.0,
        )
        c = check_reconciliation_clean(recon, max_cash_diff=100.0)
        self.assertFalse(c.passed)

    def test_approval_current_approved_passes(self):
        record = create_approval("batch-1")
        approve(record, approver_id="admin")
        c = check_approval_current(record)
        self.assertTrue(c.passed)

    def test_approval_current_pending_fails(self):
        record = create_approval("batch-1")
        c = check_approval_current(record)
        self.assertFalse(c.passed)

    def test_approval_current_rejected_fails(self):
        record = create_approval("batch-1")
        reject(record, approver_id="admin", reason="No")
        c = check_approval_current(record)
        self.assertFalse(c.passed)

    def test_approval_current_expired_fails(self):
        record = create_approval("batch-1")
        record.expires_at = (datetime.utcnow() - timedelta(hours=1)).isoformat()
        check_and_expire(record)
        c = check_approval_current(record)
        self.assertFalse(c.passed)

    def test_approval_current_none_fails(self):
        c = check_approval_current(None)
        self.assertFalse(c.passed)

    def test_intents_consistent_no_recon(self):
        c = check_intents_consistent(None)
        self.assertFalse(c.passed)

    def test_intents_consistent_clean(self):
        recon = ReconciliationResult(reconciled_at=datetime.utcnow().isoformat())
        c = check_intents_consistent(recon)
        self.assertTrue(c.passed)

    def test_no_duplicate_batch_passes(self):
        c = check_no_duplicate_batch("batch-new", prior_batch_ids=["batch-old"])
        self.assertTrue(c.passed)

    def test_no_duplicate_batch_fails(self):
        c = check_no_duplicate_batch("batch-1", prior_batch_ids=["batch-1"])
        self.assertFalse(c.passed)

    def test_no_duplicate_batch_no_id(self):
        c = check_no_duplicate_batch(None)
        self.assertFalse(c.passed)

    def test_no_live_order_path_readonly(self):
        c = check_no_live_order_path(Environment.LIVE_READONLY)
        self.assertTrue(c.passed)

    def test_no_live_order_path_demo(self):
        c = check_no_live_order_path(Environment.DEMO)
        self.assertTrue(c.passed)


class TestReadinessReport(unittest.TestCase):
    """Full readiness assessment tests."""

    def test_all_pass_scenario(self):
        recon = ReconciliationResult(
            reconciled_at=datetime.utcnow().isoformat(),
            all_matched=True, unresolved_count=0, cash_diff=0.0,
        )
        approval = create_approval("batch-1")
        approve(approval, approver_id="admin")

        report = run_readiness_checks(
            environment=Environment.LIVE_READONLY,
            reconciliation=recon,
            approval=approval,
            batch_id="batch-new",
        )
        self.assertTrue(report.all_passed)
        self.assertEqual(report.error_count, 0)

    def test_multiple_failures(self):
        report = run_readiness_checks(
            environment=Environment.DEMO,
            reconciliation=None,
            approval=None,
        )
        self.assertFalse(report.all_passed)
        self.assertGreater(report.error_count, 0)

    def test_report_to_dict(self):
        report = run_readiness_checks(
            environment=Environment.LIVE_READONLY,
        )
        d = report.to_dict()
        self.assertIn("checks", d)
        self.assertIn("all_passed", d)
        self.assertIn("error_count", d)

    def test_format_text(self):
        report = run_readiness_checks(environment=Environment.LIVE_READONLY)
        text = format_readiness_text(report)
        self.assertIn("LIVE-READINESS", text)
        self.assertIn("FAIL", text)  # Missing recon, approval etc.

    def test_live_disabled_blocks(self):
        report = run_readiness_checks(environment=Environment.LIVE_DISABLED)
        env_check = next(c for c in report.checks if c.name == "environment")
        self.assertFalse(env_check.passed)


# ===================================================================
# Environment / Config
# ===================================================================

class TestEnvironmentConfig(unittest.TestCase):
    """Environment configuration tests."""

    def test_live_readonly_valid(self):
        config = SystemConfig(environment=Environment.LIVE_READONLY)
        self.assertEqual(config.environment, "live_readonly")

    def test_live_disabled_valid(self):
        config = SystemConfig(environment=Environment.LIVE_DISABLED)
        self.assertEqual(config.environment, "live_disabled")

    def test_live_still_raises(self):
        with self.assertRaises(ValueError):
            SystemConfig(environment=Environment.LIVE)

    def test_live_readonly_default_config(self):
        config = get_default_config(Environment.LIVE_READONLY)
        self.assertEqual(config.environment, "live_readonly")
        self.assertTrue(config.require_approval)
        self.assertFalse(config.paper_execute)

    def test_live_disabled_default_config(self):
        config = get_default_config(Environment.LIVE_DISABLED)
        self.assertEqual(config.environment, "live_disabled")
        self.assertTrue(config.require_approval)
        self.assertTrue(config.dry_run)

    def test_demo_still_works(self):
        config = get_default_config(Environment.DEMO)
        self.assertEqual(config.environment, "demo")

    def test_paper_still_works(self):
        config = get_default_config(Environment.PAPER)
        self.assertEqual(config.environment, "paper")

    def test_environment_separation(self):
        """Paper and live_readonly produce different configs."""
        paper = get_default_config(Environment.PAPER)
        live_ro = get_default_config(Environment.LIVE_READONLY)
        self.assertNotEqual(paper.environment, live_ro.environment)
        self.assertNotEqual(paper.require_approval, live_ro.require_approval)

    def test_all_valid_environments(self):
        self.assertIn("live_readonly", Environment.VALID)
        self.assertIn("live_disabled", Environment.VALID)
        self.assertIn("demo", Environment.VALID)
        self.assertIn("paper", Environment.VALID)
        self.assertIn("live", Environment.VALID)


# ===================================================================
# Integration: Full account sync flow
# ===================================================================

class TestAccountSyncFlow(unittest.TestCase):
    """Integration test: broker -> sync -> reconcile -> export."""

    def test_full_sync_flow(self):
        adapter = MockBrokerAdapter(
            cash=500_000,
            positions=[
                BrokerPosition(ticker="AAPL", shares=100, market_value=15000),
                BrokerPosition(ticker="MSFT", shares=50, market_value=20000),
            ],
            prices={"AAPL": 150, "MSFT": 400},
        )
        internal = InternalState(
            cash=500_000, total_value=535_000,
            positions=[
                InternalPosition(ticker="AAPL", shares=100, market_value=15000, weight=2.8),
                InternalPosition(ticker="MSFT", shares=50, market_value=20000, weight=3.7),
            ],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_account_sync(
                broker=adapter,
                internal_state=internal,
                output_dir=tmpdir,
            )
            self.assertTrue(result.all_matched)
            # Check artifacts exist
            self.assertTrue(os.path.exists(os.path.join(tmpdir, "account_snapshot.json")))
            self.assertTrue(os.path.exists(os.path.join(tmpdir, "reconciliation_report.json")))

    def test_sync_with_mismatches(self):
        adapter = MockBrokerAdapter(
            cash=480_000,  # Different cash
            positions=[
                BrokerPosition(ticker="AAPL", shares=110, market_value=16500),  # Different shares
            ],
        )
        internal = InternalState(
            cash=500_000, total_value=515_000,
            positions=[
                InternalPosition(ticker="AAPL", shares=100, market_value=15000, weight=2.9),
                InternalPosition(ticker="GOOG", shares=20, market_value=60000, weight=11.7),  # Missing at broker
            ],
        )
        result = run_account_sync(broker=adapter, internal_state=internal)
        self.assertFalse(result.all_matched)
        self.assertFalse(result.cash_matched)
        self.assertEqual(result.mismatch_count, 1)  # AAPL shares differ
        self.assertEqual(result.missing_broker_count, 1)  # GOOG


# ===================================================================
# No live order path (defense in depth)
# ===================================================================

class TestNoLiveOrderPath(unittest.TestCase):
    """Verify no code path can place live orders."""

    def test_mock_adapter_blocks_orders(self):
        adapter = MockBrokerAdapter()
        with self.assertRaises(NotImplementedError):
            adapter.submit_order("AAPL", "buy", 100)

    def test_file_adapter_blocks_orders(self):
        data = {"cash": 100, "total_equity": 100, "positions": [], "open_orders": [], "recent_fills": []}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            path = f.name
        try:
            adapter = FileBrokerAdapter(path)
            with self.assertRaises(NotImplementedError):
                adapter.submit_order("AAPL", "buy", 100)
            with self.assertRaises(NotImplementedError):
                adapter.cancel_order("ord-1")
            with self.assertRaises(NotImplementedError):
                adapter.modify_order("ord-1")
        finally:
            os.unlink(path)

    def test_live_readonly_never_mutates(self):
        """Live-readonly adapter cannot modify broker state."""
        adapter = MockBrokerAdapter(cash=100_000)
        initial_cash = adapter.get_cash()
        # Read operations don't change state
        adapter.get_account_snapshot()
        adapter.get_positions()
        adapter.get_open_orders()
        adapter.get_recent_fills()
        self.assertEqual(adapter.get_cash(), initial_cash)


if __name__ == "__main__":
    unittest.main()
