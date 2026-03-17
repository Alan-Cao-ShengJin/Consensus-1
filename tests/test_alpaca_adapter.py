"""Tests for AlpacaBrokerAdapter and broker factory."""
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime

from broker_interface import BrokerInterface, BrokerPosition, BrokerOrder, BrokerFill, AccountSnapshot
from broker_readonly_adapter import create_broker_adapter, MockBrokerAdapter


# ---------------------------------------------------------------------------
# Factory tests
# ---------------------------------------------------------------------------

class TestBrokerFactory:
    def test_mock_mode(self):
        adapter = create_broker_adapter("mock")
        assert isinstance(adapter, MockBrokerAdapter)

    def test_mock_mode_with_kwargs(self):
        adapter = create_broker_adapter("mock", cash=100_000.0)
        assert adapter.get_cash() == 100_000.0

    def test_mock_mode_ignores_broker_kwargs(self):
        """Mock adapter should not crash on alpaca-specific kwargs."""
        adapter = create_broker_adapter("mock", api_key="x", secret_key="y", paper=True)
        assert isinstance(adapter, MockBrokerAdapter)

    def test_file_mode_requires_path(self):
        with pytest.raises(ValueError, match="snapshot_path"):
            create_broker_adapter("file")

    def test_alpaca_mode_requires_keys(self):
        with pytest.raises(ValueError, match="api_key"):
            create_broker_adapter("alpaca")

    def test_alpaca_mode_requires_secret(self):
        with pytest.raises(ValueError, match="api_key"):
            create_broker_adapter("alpaca", api_key="key")

    def test_unknown_mode_raises(self):
        with pytest.raises(ValueError, match="Unknown"):
            create_broker_adapter("unknown_broker")


# ---------------------------------------------------------------------------
# AlpacaBrokerAdapter unit tests (mocked SDK)
# ---------------------------------------------------------------------------

class TestAlpacaAdapter:
    """Test AlpacaBrokerAdapter with mocked Alpaca SDK."""

    @pytest.fixture
    def mock_trading_client(self):
        return MagicMock()

    @pytest.fixture
    def mock_data_client(self):
        return MagicMock()

    @pytest.fixture
    def adapter(self, mock_trading_client, mock_data_client):
        with patch("alpaca_broker_adapter.ALPACA_AVAILABLE", True), \
             patch("alpaca_broker_adapter.TradingClient", return_value=mock_trading_client), \
             patch("alpaca_broker_adapter.StockHistoricalDataClient", return_value=mock_data_client):
            from alpaca_broker_adapter import AlpacaBrokerAdapter
            return AlpacaBrokerAdapter(api_key="test", secret_key="test", paper=True)

    def test_implements_broker_interface(self, adapter):
        assert isinstance(adapter, BrokerInterface)

    def test_get_cash(self, adapter, mock_trading_client):
        mock_account = MagicMock()
        mock_account.cash = "50000.00"
        mock_trading_client.get_account.return_value = mock_account

        cash = adapter.get_cash()
        assert cash == 50000.0

    def test_get_positions(self, adapter, mock_trading_client):
        mock_pos = MagicMock()
        mock_pos.symbol = "AAPL"
        mock_pos.qty = "10"
        mock_pos.market_value = "1500.00"
        mock_pos.avg_entry_price = "150.00"
        mock_pos.current_price = "155.00"
        mock_pos.unrealized_pl = "50.00"
        mock_trading_client.get_all_positions.return_value = [mock_pos]

        positions = adapter.get_positions()
        assert len(positions) == 1
        assert positions[0].ticker == "AAPL"
        assert positions[0].shares == 10.0
        assert positions[0].market_value == 1500.0

    def test_get_open_orders(self, adapter, mock_trading_client):
        mock_order = MagicMock()
        mock_order.id = "order-123"
        mock_order.symbol = "AAPL"
        mock_order.side.value = "buy"
        mock_order.qty = "10"
        mock_order.type.value = "market"
        mock_order.status.value = "new"
        mock_order.filled_qty = "0"
        mock_order.limit_price = None
        mock_order.filled_avg_price = None
        mock_order.submitted_at = datetime(2026, 3, 16, 10, 0, 0)
        mock_order.filled_at = None
        mock_trading_client.get_orders.return_value = [mock_order]

        orders = adapter.get_open_orders()
        assert len(orders) == 1
        assert orders[0].ticker == "AAPL"
        assert orders[0].side == "buy"
        assert orders[0].status == "new"

    def test_submit_order_market(self, adapter, mock_trading_client):
        mock_result = MagicMock()
        mock_result.id = "order-456"
        mock_result.symbol = "AAPL"
        mock_result.side.value = "buy"
        mock_result.qty = "10"
        mock_result.type.value = "market"
        mock_result.status.value = "accepted"
        mock_result.filled_qty = "0"
        mock_result.limit_price = None
        mock_result.filled_avg_price = None
        mock_result.submitted_at = datetime(2026, 3, 16, 10, 0, 0)
        mock_result.filled_at = None
        mock_trading_client.submit_order.return_value = mock_result

        order = adapter.submit_order("AAPL", "buy", 10.0)
        assert isinstance(order, BrokerOrder)
        assert order.order_id == "order-456"
        assert order.ticker == "AAPL"
        mock_trading_client.submit_order.assert_called_once()

    def test_submit_order_limit_requires_price(self, adapter):
        with pytest.raises(ValueError, match="limit_price"):
            adapter.submit_order("AAPL", "buy", 10.0, order_type="limit")

    def test_cancel_order(self, adapter, mock_trading_client):
        adapter.cancel_order("order-789")
        mock_trading_client.cancel_order_by_id.assert_called_once_with("order-789")

    def test_cancel_all_orders(self, adapter, mock_trading_client):
        mock_trading_client.cancel_orders.return_value = [MagicMock(), MagicMock()]
        count = adapter.cancel_all_orders()
        assert count == 2

    def test_is_market_open(self, adapter, mock_trading_client):
        mock_clock = MagicMock()
        mock_clock.is_open = True
        mock_trading_client.get_clock.return_value = mock_clock
        assert adapter.is_market_open() is True

    def test_get_account_snapshot(self, adapter, mock_trading_client):
        mock_account = MagicMock()
        mock_account.cash = "100000"
        mock_account.buying_power = "200000"
        mock_account.equity = "500000"
        mock_account.account_number = "PA-12345"
        mock_trading_client.get_account.return_value = mock_account
        mock_trading_client.get_all_positions.return_value = []
        mock_trading_client.get_orders.return_value = []

        snapshot = adapter.get_account_snapshot()
        assert isinstance(snapshot, AccountSnapshot)
        assert snapshot.cash == 100000.0
        assert snapshot.total_equity == 500000.0
        assert "alpaca_paper" in snapshot.broker_name
