"""Tests for live execution engine, order state machine, and safety layers."""
import os
import json
import pytest
from unittest.mock import MagicMock, patch
from datetime import date, datetime

from order_state_machine import LiveOrder, OrderStatus, update_from_broker
from circuit_breakers import (
    check_max_drawdown, check_daily_loss, check_concentration,
    run_all_checks, CircuitBreakerConfig,
)
import kill_switch
import market_hours


# ===========================================================================
# Order State Machine
# ===========================================================================

class TestOrderStateMachine:
    def test_initial_state(self):
        order = LiveOrder(ticker="AAPL", side="buy", quantity=10)
        assert order.status == OrderStatus.CREATED
        assert not order.is_terminal

    def test_valid_transition_created_to_submitted(self):
        order = LiveOrder(ticker="AAPL", side="buy", quantity=10)
        assert order.transition(OrderStatus.SUBMITTED) is True
        assert order.status == OrderStatus.SUBMITTED
        assert order.submitted_at is not None

    def test_valid_transition_submitted_to_filled(self):
        order = LiveOrder(ticker="AAPL", side="buy", quantity=10)
        order.transition(OrderStatus.SUBMITTED)
        assert order.transition(OrderStatus.FILLED) is True
        assert order.status == OrderStatus.FILLED
        assert order.is_terminal
        assert order.is_filled

    def test_valid_transition_submitted_to_canceled(self):
        order = LiveOrder(ticker="AAPL", side="buy", quantity=10)
        order.transition(OrderStatus.SUBMITTED)
        assert order.transition(OrderStatus.CANCELED) is True
        assert order.is_terminal

    def test_valid_transition_submitted_to_rejected(self):
        order = LiveOrder(ticker="AAPL", side="buy", quantity=10)
        order.transition(OrderStatus.SUBMITTED)
        assert order.transition(OrderStatus.REJECTED) is True
        assert order.is_terminal

    def test_valid_transition_partial_to_filled(self):
        order = LiveOrder(ticker="AAPL", side="buy", quantity=10)
        order.transition(OrderStatus.SUBMITTED)
        order.transition(OrderStatus.PARTIAL_FILL)
        assert order.transition(OrderStatus.FILLED) is True

    def test_invalid_transition_created_to_filled(self):
        order = LiveOrder(ticker="AAPL", side="buy", quantity=10)
        assert order.transition(OrderStatus.FILLED) is False
        assert order.status == OrderStatus.CREATED

    def test_invalid_transition_from_terminal(self):
        order = LiveOrder(ticker="AAPL", side="buy", quantity=10)
        order.transition(OrderStatus.SUBMITTED)
        order.transition(OrderStatus.FILLED)
        assert order.transition(OrderStatus.SUBMITTED) is False
        assert order.status == OrderStatus.FILLED

    def test_state_history_tracked(self):
        order = LiveOrder(ticker="AAPL", side="buy", quantity=10)
        order.transition(OrderStatus.SUBMITTED, "initial submit")
        order.transition(OrderStatus.FILLED, "market fill")
        assert len(order.state_history) == 2
        assert order.state_history[0]["from"] == "created"
        assert order.state_history[0]["to"] == "submitted"
        assert order.state_history[1]["reason"] == "market fill"

    def test_notional_property(self):
        order = LiveOrder(ticker="AAPL", side="buy", quantity=10)
        order.filled_quantity = 10
        order.filled_avg_price = 150.0
        assert order.notional == 1500.0

    def test_update_from_broker(self):
        order = LiveOrder(ticker="AAPL", side="buy", quantity=10)
        order.transition(OrderStatus.SUBMITTED)

        broker_order = MagicMock()
        broker_order.order_id = "broker-123"
        broker_order.filled_quantity = 10
        broker_order.fill_price = 155.0
        broker_order.status = "filled"

        update_from_broker(order, broker_order)
        assert order.broker_order_id == "broker-123"
        assert order.filled_quantity == 10
        assert order.filled_avg_price == 155.0
        assert order.status == OrderStatus.FILLED

    def test_to_dict(self):
        order = LiveOrder(ticker="AAPL", side="buy", quantity=10, action_type="initiate")
        d = order.to_dict()
        assert d["ticker"] == "AAPL"
        assert d["side"] == "buy"
        assert d["status"] == "created"


# ===========================================================================
# Circuit Breakers
# ===========================================================================

class TestCircuitBreakers:
    def test_drawdown_within_limit(self):
        tripped, msg = check_max_drawdown(95_000, 100_000, threshold_pct=15.0)
        assert tripped is False

    def test_drawdown_exceeds_limit(self):
        tripped, msg = check_max_drawdown(80_000, 100_000, threshold_pct=15.0)
        assert tripped is True
        assert "20.0%" in msg

    def test_drawdown_zero_hwm(self):
        tripped, msg = check_max_drawdown(80_000, 0, threshold_pct=15.0)
        assert tripped is False

    def test_daily_loss_within_limit(self):
        tripped, msg = check_daily_loss(-2_000, 100_000, threshold_pct=3.0)
        assert tripped is False

    def test_daily_loss_exceeds_limit(self):
        tripped, msg = check_daily_loss(-4_000, 100_000, threshold_pct=3.0)
        assert tripped is True

    def test_daily_loss_positive_pnl(self):
        tripped, msg = check_daily_loss(5_000, 100_000, threshold_pct=3.0)
        assert tripped is False

    def test_concentration_within_limit(self):
        positions = [
            {"ticker": "AAPL", "weight_pct": 8.0},
            {"ticker": "MSFT", "weight_pct": 6.0},
        ]
        tripped, over = check_concentration(positions, max_weight_pct=12.0)
        assert tripped is False
        assert len(over) == 0

    def test_concentration_exceeds_limit(self):
        positions = [
            {"ticker": "AAPL", "weight_pct": 15.0},
            {"ticker": "MSFT", "weight_pct": 6.0},
        ]
        tripped, over = check_concentration(positions, max_weight_pct=12.0)
        assert tripped is True
        assert "AAPL" in over

    def test_run_all_checks_clean(self):
        tripped, messages = run_all_checks(
            current_equity=95_000,
            high_water_mark=100_000,
            today_pnl=-1_000,
            portfolio_value_sod=100_000,
        )
        assert tripped is False

    def test_run_all_checks_tripped(self):
        tripped, messages = run_all_checks(
            current_equity=80_000,
            high_water_mark=100_000,
            today_pnl=-5_000,
            portfolio_value_sod=100_000,
        )
        assert tripped is True

    def test_disabled_config(self):
        config = CircuitBreakerConfig(enabled=False)
        tripped, messages = run_all_checks(
            current_equity=50_000,
            high_water_mark=100_000,
            today_pnl=-10_000,
            portfolio_value_sod=100_000,
            config=config,
        )
        assert tripped is False


# ===========================================================================
# Kill Switch
# ===========================================================================

class TestKillSwitch:
    @pytest.fixture(autouse=True)
    def clean_kill_switch(self, tmp_path, monkeypatch):
        """Use temp directory for kill switch file."""
        ks_path = str(tmp_path / "KILL_SWITCH")
        monkeypatch.setattr(kill_switch, "KILL_SWITCH_FILE", ks_path)
        monkeypatch.delenv("CONSENSUS_KILL_SWITCH", raising=False)
        yield

    def test_not_active_by_default(self):
        assert kill_switch.is_active() is False

    def test_activate_deactivate(self):
        kill_switch.activate("test reason")
        assert kill_switch.is_active() is True
        assert kill_switch.get_reason() == "test reason"

        kill_switch.deactivate()
        assert kill_switch.is_active() is False

    def test_env_var_activation(self, monkeypatch):
        monkeypatch.setenv("CONSENSUS_KILL_SWITCH", "1")
        assert kill_switch.is_active() is True

    def test_cancel_all_open(self):
        broker = MagicMock()
        broker.cancel_all_orders.return_value = 3
        count = kill_switch.cancel_all_open(broker)
        assert count == 3

    def test_cancel_all_open_fallback(self):
        """Falls back to individual cancel if cancel_all_orders not available."""
        broker = MagicMock(spec=["get_open_orders", "cancel_order"])
        order1 = MagicMock()
        order1.order_id = "o1"
        order2 = MagicMock()
        order2.order_id = "o2"
        broker.get_open_orders.return_value = [order1, order2]
        count = kill_switch.cancel_all_open(broker)
        assert count == 2


# ===========================================================================
# Market Hours
# ===========================================================================

class TestMarketHours:
    def test_broker_clock_used(self):
        broker = MagicMock()
        broker.is_market_open.return_value = True
        assert market_hours.is_market_open(broker) is True

    def test_broker_clock_failure_falls_back(self):
        broker = MagicMock()
        broker.is_market_open.side_effect = Exception("API down")
        # Should not raise, falls back to time check
        result = market_hours.is_market_open(broker)
        assert isinstance(result, bool)

    def test_no_broker_falls_back(self):
        result = market_hours.is_market_open(None)
        assert isinstance(result, bool)


# ===========================================================================
# Live Execution Engine
# ===========================================================================

class TestLiveExecutionEngine:
    @pytest.fixture
    def mock_broker(self):
        broker = MagicMock()
        broker.is_market_open.return_value = True
        broker.get_account_snapshot.return_value = MagicMock(
            total_equity=100_000,
            cash=50_000,
            positions=[],
        )
        broker.submit_order.return_value = MagicMock(
            id="broker-order-1",
            symbol="AAPL",
            side=MagicMock(value="buy"),
            qty="10",
            type=MagicMock(value="market"),
            status=MagicMock(value="filled"),
            filled_qty="10",
            limit_price=None,
            filled_avg_price="150.0",
            submitted_at=datetime.utcnow(),
            filled_at=datetime.utcnow(),
        )
        return broker

    @pytest.fixture
    def mock_intent(self):
        from execution_wrapper import OrderIntent
        from models import ActionType
        intent = MagicMock(spec=OrderIntent)
        intent.ticker = "AAPL"
        intent.side = "buy"
        intent.action_type = ActionType.INITIATE
        intent.estimated_shares = 10.0
        intent.notional_delta = 1500.0
        intent.review_date = "2026-03-16"
        intent.to_dict.return_value = {"ticker": "AAPL"}
        return intent

    def test_sells_before_buys(self, mock_broker, tmp_path, monkeypatch):
        """Verify sell orders execute before buy orders."""
        monkeypatch.setattr(kill_switch, "KILL_SWITCH_FILE", str(tmp_path / "KS"))
        monkeypatch.delenv("CONSENSUS_KILL_SWITCH", raising=False)

        from live_execution_engine import live_execute
        from models import ActionType

        sell_intent = MagicMock()
        sell_intent.ticker = "MSFT"
        sell_intent.side = "sell"
        sell_intent.action_type = ActionType.EXIT
        sell_intent.estimated_shares = 5.0
        sell_intent.review_date = "2026-03-16"
        sell_intent.to_dict.return_value = {}

        buy_intent = MagicMock()
        buy_intent.ticker = "AAPL"
        buy_intent.side = "buy"
        buy_intent.action_type = ActionType.INITIATE
        buy_intent.estimated_shares = 10.0
        buy_intent.review_date = "2026-03-16"
        buy_intent.to_dict.return_value = {}

        # Track order of submissions
        submission_order = []
        def track_submit(ticker, **kwargs):
            submission_order.append(ticker)
            result = MagicMock()
            result.id = f"order-{ticker}"
            result.symbol = ticker
            result.side = MagicMock(value=kwargs.get("side", "buy"))
            result.qty = "10"
            result.type = MagicMock(value="market")
            result.status = MagicMock(value="filled")
            result.filled_qty = "10"
            result.filled_avg_price = "150"
            result.limit_price = None
            result.submitted_at = datetime.utcnow()
            result.filled_at = datetime.utcnow()
            return result

        mock_broker.submit_order.side_effect = track_submit

        summary = live_execute(
            broker=mock_broker,
            approved_intents=[buy_intent, sell_intent],
            blocked_intents=[],
            execution_date=date(2026, 3, 16),
        )

        # MSFT (sell) should come before AAPL (buy)
        assert submission_order[0] == "MSFT"
        assert submission_order[1] == "AAPL"

    def test_kill_switch_blocks_execution(self, mock_broker, tmp_path, monkeypatch):
        monkeypatch.setattr(kill_switch, "KILL_SWITCH_FILE", str(tmp_path / "KS"))
        monkeypatch.delenv("CONSENSUS_KILL_SWITCH", raising=False)

        kill_switch.activate("test block")

        from live_execution_engine import live_execute
        summary = live_execute(
            broker=mock_broker,
            approved_intents=[MagicMock(side="buy", ticker="AAPL",
                                        review_date="2026-03-16",
                                        to_dict=lambda: {})],
            blocked_intents=[],
            execution_date=date(2026, 3, 16),
        )

        assert summary.orders_submitted == 0
        assert "Safety checks failed" in summary.errors[0]

        kill_switch.deactivate()

    def test_market_closed_blocks_execution(self, mock_broker, tmp_path, monkeypatch):
        monkeypatch.setattr(kill_switch, "KILL_SWITCH_FILE", str(tmp_path / "KS"))
        monkeypatch.delenv("CONSENSUS_KILL_SWITCH", raising=False)
        mock_broker.is_market_open.return_value = False

        from live_execution_engine import live_execute
        summary = live_execute(
            broker=mock_broker,
            approved_intents=[MagicMock(side="buy", ticker="AAPL",
                                        review_date="2026-03-16",
                                        to_dict=lambda: {})],
            blocked_intents=[],
            execution_date=date(2026, 3, 16),
        )

        assert summary.orders_submitted == 0
