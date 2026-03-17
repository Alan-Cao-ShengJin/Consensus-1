"""Read-only broker adapters.

Provides concrete implementations of BrokerInterface:
  - MockBrokerAdapter: deterministic mock for testing/demo
  - FileBrokerAdapter: loads account state from a JSON file (scaffold)

No adapter can place live orders. Write methods raise NotImplementedError
via the base class.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Optional

from broker_interface import (
    BrokerInterface,
    AccountSnapshot,
    BrokerPosition,
    BrokerOrder,
    BrokerFill,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Mock broker adapter
# ---------------------------------------------------------------------------

class MockBrokerAdapter(BrokerInterface):
    """Deterministic mock broker for testing and demo mode.

    Provides configurable positions, cash, orders, fills, and prices.
    No external dependencies. Fully deterministic.
    """

    def __init__(
        self,
        cash: float = 500_000.0,
        buying_power: float = 500_000.0,
        positions: Optional[list[BrokerPosition]] = None,
        open_orders: Optional[list[BrokerOrder]] = None,
        recent_fills: Optional[list[BrokerFill]] = None,
        prices: Optional[dict[str, float]] = None,
        broker_name: str = "mock",
        account_id: str = "MOCK-001",
    ):
        self._cash = cash
        self._buying_power = buying_power
        self._positions = positions or []
        self._open_orders = open_orders or []
        self._recent_fills = recent_fills or []
        self._prices = prices or {}
        self._broker_name = broker_name
        self._account_id = account_id

    @property
    def total_equity(self) -> float:
        invested = sum(p.market_value for p in self._positions)
        return self._cash + invested

    def get_account_snapshot(self) -> AccountSnapshot:
        return AccountSnapshot(
            snapshot_at=datetime.utcnow().isoformat(),
            cash=self._cash,
            buying_power=self._buying_power,
            total_equity=self.total_equity,
            positions=list(self._positions),
            open_orders=list(self._open_orders),
            recent_fills=list(self._recent_fills),
            broker_name=self._broker_name,
            account_id=self._account_id,
        )

    def get_cash(self) -> float:
        return self._cash

    def get_positions(self) -> list[BrokerPosition]:
        return list(self._positions)

    def get_open_orders(self) -> list[BrokerOrder]:
        return list(self._open_orders)

    def get_recent_fills(self, limit: int = 50) -> list[BrokerFill]:
        return list(self._recent_fills[:limit])

    def get_reference_price(self, ticker: str) -> Optional[float]:
        return self._prices.get(ticker)

    def get_reference_prices(self, tickers: list[str]) -> dict[str, float]:
        return {t: self._prices[t] for t in tickers if t in self._prices}


# ---------------------------------------------------------------------------
# File-based broker adapter (scaffold for future API adapters)
# ---------------------------------------------------------------------------

class FileBrokerAdapter(BrokerInterface):
    """Loads account state from a JSON file.

    Useful for replaying known broker states or testing reconciliation
    against saved snapshots. The JSON schema matches AccountSnapshot.to_dict().
    """

    def __init__(self, snapshot_path: str):
        if not os.path.exists(snapshot_path):
            raise FileNotFoundError(f"Broker snapshot file not found: {snapshot_path}")
        with open(snapshot_path, "r") as f:
            data = json.load(f)
        self._snapshot = _parse_account_snapshot(data)
        logger.info("Loaded broker snapshot from %s", snapshot_path)

    def get_account_snapshot(self) -> AccountSnapshot:
        return self._snapshot

    def get_cash(self) -> float:
        return self._snapshot.cash

    def get_positions(self) -> list[BrokerPosition]:
        return list(self._snapshot.positions)

    def get_open_orders(self) -> list[BrokerOrder]:
        return list(self._snapshot.open_orders)

    def get_recent_fills(self, limit: int = 50) -> list[BrokerFill]:
        return list(self._snapshot.recent_fills[:limit])

    def get_reference_price(self, ticker: str) -> Optional[float]:
        pos = self._snapshot.get_position(ticker)
        if pos and pos.last_price:
            return pos.last_price
        return None

    def get_reference_prices(self, tickers: list[str]) -> dict[str, float]:
        prices = {}
        for t in tickers:
            p = self.get_reference_price(t)
            if p is not None:
                prices[t] = p
        return prices


# ---------------------------------------------------------------------------
# JSON parsing helper
# ---------------------------------------------------------------------------

def _parse_account_snapshot(data: dict) -> AccountSnapshot:
    """Parse an AccountSnapshot from a JSON dict."""
    positions = [
        BrokerPosition(
            ticker=p["ticker"],
            shares=p["shares"],
            market_value=p["market_value"],
            avg_cost=p.get("avg_cost"),
            last_price=p.get("last_price"),
            unrealized_pnl=p.get("unrealized_pnl"),
        )
        for p in data.get("positions", [])
    ]
    open_orders = [
        BrokerOrder(
            order_id=o["order_id"],
            ticker=o["ticker"],
            side=o["side"],
            quantity=o["quantity"],
            order_type=o["order_type"],
            status=o["status"],
            filled_quantity=o.get("filled_quantity", 0.0),
            limit_price=o.get("limit_price"),
            fill_price=o.get("fill_price"),
            submitted_at=o.get("submitted_at"),
            filled_at=o.get("filled_at"),
        )
        for o in data.get("open_orders", [])
    ]
    recent_fills = [
        BrokerFill(
            fill_id=f["fill_id"],
            ticker=f["ticker"],
            side=f["side"],
            shares=f["shares"],
            price=f["price"],
            notional=f["notional"],
            filled_at=f["filled_at"],
            order_id=f.get("order_id"),
        )
        for f in data.get("recent_fills", [])
    ]
    return AccountSnapshot(
        snapshot_at=data.get("snapshot_at", datetime.utcnow().isoformat()),
        cash=data["cash"],
        buying_power=data.get("buying_power", data["cash"]),
        total_equity=data.get("total_equity", data["cash"] + sum(p.market_value for p in positions)),
        positions=positions,
        open_orders=open_orders,
        recent_fills=recent_fills,
        broker_name=data.get("broker_name", "file"),
        account_id=data.get("account_id", ""),
    )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_broker_adapter(
    mode: str = "mock",
    snapshot_path: Optional[str] = None,
    **kwargs,
) -> BrokerInterface:
    """Create a broker adapter by mode.

    Args:
        mode: "mock", "file", or "alpaca"
        snapshot_path: Required for "file" mode
        **kwargs: Passed to adapter constructor.
            For "alpaca": api_key, secret_key, paper (bool)
    """
    if mode == "mock":
        # Filter out broker-specific kwargs that MockBrokerAdapter doesn't accept
        mock_kwargs = {k: v for k, v in kwargs.items()
                       if k in ("cash", "buying_power", "positions", "open_orders",
                                "recent_fills", "prices", "broker_name", "account_id")}
        return MockBrokerAdapter(**mock_kwargs)
    elif mode == "file":
        if not snapshot_path:
            raise ValueError("snapshot_path required for file broker adapter")
        return FileBrokerAdapter(snapshot_path)
    elif mode == "alpaca":
        from alpaca_broker_adapter import AlpacaBrokerAdapter
        api_key = kwargs.get("api_key", "")
        secret_key = kwargs.get("secret_key", "")
        paper = kwargs.get("paper", True)
        if not api_key or not secret_key:
            raise ValueError("api_key and secret_key required for alpaca broker adapter")
        return AlpacaBrokerAdapter(api_key=api_key, secret_key=secret_key, paper=paper)
    else:
        raise ValueError(f"Unknown broker adapter mode: {mode}")
