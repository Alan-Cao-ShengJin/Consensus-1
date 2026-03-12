"""Broker abstraction layer: read-only interface for account/market data.

Defines the contract for broker connectivity. Step 12 supports read-only
operations only — no live order placement. Any write methods raise
NotImplementedError to enforce this boundary.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures returned by broker
# ---------------------------------------------------------------------------

@dataclass
class BrokerPosition:
    """A single position as reported by the broker."""
    ticker: str
    shares: float
    market_value: float
    avg_cost: Optional[float] = None
    last_price: Optional[float] = None
    unrealized_pnl: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "shares": round(self.shares, 6),
            "market_value": round(self.market_value, 2),
            "avg_cost": round(self.avg_cost, 4) if self.avg_cost else None,
            "last_price": round(self.last_price, 4) if self.last_price else None,
            "unrealized_pnl": round(self.unrealized_pnl, 2) if self.unrealized_pnl else None,
        }


@dataclass
class BrokerOrder:
    """An open or recent order as reported by the broker."""
    order_id: str
    ticker: str
    side: str  # "buy" or "sell"
    quantity: float
    order_type: str  # "market", "limit", etc.
    status: str  # "open", "filled", "cancelled", "partial"
    filled_quantity: float = 0.0
    limit_price: Optional[float] = None
    fill_price: Optional[float] = None
    submitted_at: Optional[str] = None
    filled_at: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "order_id": self.order_id,
            "ticker": self.ticker,
            "side": self.side,
            "quantity": round(self.quantity, 6),
            "order_type": self.order_type,
            "status": self.status,
            "filled_quantity": round(self.filled_quantity, 6),
            "limit_price": round(self.limit_price, 4) if self.limit_price else None,
            "fill_price": round(self.fill_price, 4) if self.fill_price else None,
            "submitted_at": self.submitted_at,
            "filled_at": self.filled_at,
        }


@dataclass
class BrokerFill:
    """A recent fill/execution as reported by the broker."""
    fill_id: str
    ticker: str
    side: str
    shares: float
    price: float
    notional: float
    filled_at: str
    order_id: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "fill_id": self.fill_id,
            "ticker": self.ticker,
            "side": self.side,
            "shares": round(self.shares, 6),
            "price": round(self.price, 4),
            "notional": round(self.notional, 2),
            "filled_at": self.filled_at,
            "order_id": self.order_id,
        }


@dataclass
class AccountSnapshot:
    """Complete account state from broker at a point in time."""
    snapshot_at: str
    cash: float
    buying_power: float
    total_equity: float
    positions: list[BrokerPosition] = field(default_factory=list)
    open_orders: list[BrokerOrder] = field(default_factory=list)
    recent_fills: list[BrokerFill] = field(default_factory=list)
    broker_name: str = ""
    account_id: str = ""

    @property
    def invested_value(self) -> float:
        return sum(p.market_value for p in self.positions)

    @property
    def position_count(self) -> int:
        return len(self.positions)

    def get_position(self, ticker: str) -> Optional[BrokerPosition]:
        for p in self.positions:
            if p.ticker == ticker:
                return p
        return None

    def get_weights(self) -> dict[str, float]:
        """Position weights as percentages of total equity."""
        if self.total_equity <= 0:
            return {}
        return {
            p.ticker: (p.market_value / self.total_equity) * 100.0
            for p in self.positions
        }

    def to_dict(self) -> dict:
        return {
            "snapshot_at": self.snapshot_at,
            "cash": round(self.cash, 2),
            "buying_power": round(self.buying_power, 2),
            "total_equity": round(self.total_equity, 2),
            "invested_value": round(self.invested_value, 2),
            "position_count": self.position_count,
            "positions": [p.to_dict() for p in self.positions],
            "open_orders": [o.to_dict() for o in self.open_orders],
            "recent_fills": [f.to_dict() for f in self.recent_fills],
            "broker_name": self.broker_name,
            "account_id": self.account_id,
        }


# ---------------------------------------------------------------------------
# Abstract broker interface
# ---------------------------------------------------------------------------

class BrokerInterface(ABC):
    """Abstract broker interface — read-only operations only.

    All concrete adapters must implement the read methods.
    Write methods raise NotImplementedError by default.
    """

    @abstractmethod
    def get_account_snapshot(self) -> AccountSnapshot:
        """Fetch full account state: cash, positions, orders, fills."""

    @abstractmethod
    def get_cash(self) -> float:
        """Fetch available cash / buying power."""

    @abstractmethod
    def get_positions(self) -> list[BrokerPosition]:
        """Fetch current holdings."""

    @abstractmethod
    def get_open_orders(self) -> list[BrokerOrder]:
        """Fetch open/pending orders."""

    @abstractmethod
    def get_recent_fills(self, limit: int = 50) -> list[BrokerFill]:
        """Fetch recent trade fills."""

    @abstractmethod
    def get_reference_price(self, ticker: str) -> Optional[float]:
        """Fetch current/last price for a ticker."""

    @abstractmethod
    def get_reference_prices(self, tickers: list[str]) -> dict[str, float]:
        """Fetch prices for multiple tickers."""

    # -------------------------------------------------------------------
    # Write operations — NOT IMPLEMENTED in Step 12
    # -------------------------------------------------------------------

    def submit_order(self, ticker: str, side: str, quantity: float, **kwargs) -> None:
        """Submit a live order. NOT IMPLEMENTED — raises unconditionally."""
        raise NotImplementedError(
            "Live order submission is not implemented in Step 12. "
            "This boundary exists to protect real capital. "
            "A future step must explicitly enable this."
        )

    def cancel_order(self, order_id: str) -> None:
        """Cancel a live order. NOT IMPLEMENTED — raises unconditionally."""
        raise NotImplementedError(
            "Live order cancellation is not implemented in Step 12."
        )

    def modify_order(self, order_id: str, **kwargs) -> None:
        """Modify a live order. NOT IMPLEMENTED — raises unconditionally."""
        raise NotImplementedError(
            "Live order modification is not implemented in Step 12."
        )
