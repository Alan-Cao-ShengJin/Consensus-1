"""Order state machine: track order lifecycle for live trading.

States: CREATED -> SUBMITTED -> PARTIAL_FILL -> FILLED
                             -> CANCELED
                             -> REJECTED
                             -> EXPIRED
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class OrderStatus(str, Enum):
    CREATED = "created"
    SUBMITTED = "submitted"
    PARTIAL_FILL = "partial_fill"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"
    EXPIRED = "expired"


# Valid state transitions
VALID_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.CREATED: {OrderStatus.SUBMITTED, OrderStatus.CANCELED},
    OrderStatus.SUBMITTED: {
        OrderStatus.PARTIAL_FILL,
        OrderStatus.FILLED,
        OrderStatus.CANCELED,
        OrderStatus.REJECTED,
        OrderStatus.EXPIRED,
    },
    OrderStatus.PARTIAL_FILL: {
        OrderStatus.FILLED,
        OrderStatus.CANCELED,
        OrderStatus.EXPIRED,
    },
    # Terminal states — no transitions out
    OrderStatus.FILLED: set(),
    OrderStatus.CANCELED: set(),
    OrderStatus.REJECTED: set(),
    OrderStatus.EXPIRED: set(),
}

TERMINAL_STATES = {
    OrderStatus.FILLED,
    OrderStatus.CANCELED,
    OrderStatus.REJECTED,
    OrderStatus.EXPIRED,
}


@dataclass
class LiveOrder:
    """Tracks the full lifecycle of a live order."""
    order_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    broker_order_id: Optional[str] = None
    ticker: str = ""
    side: str = ""           # "buy" or "sell"
    quantity: float = 0.0
    order_type: str = "market"
    limit_price: Optional[float] = None
    time_in_force: str = "day"
    status: OrderStatus = OrderStatus.CREATED
    filled_quantity: float = 0.0
    filled_avg_price: Optional[float] = None
    intent_id: Optional[str] = None   # back-reference to OrderIntent
    action_type: str = ""              # initiate/add/trim/exit
    error_message: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    submitted_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    filled_at: Optional[datetime] = None
    state_history: list[dict] = field(default_factory=list)

    def transition(self, new_status: OrderStatus, reason: str = "") -> bool:
        """Attempt a state transition. Returns True if successful."""
        valid_next = VALID_TRANSITIONS.get(self.status, set())
        if new_status not in valid_next:
            logger.error(
                "Invalid transition for order %s (%s): %s -> %s",
                self.order_id, self.ticker, self.status.value, new_status.value,
            )
            return False

        old_status = self.status
        self.status = new_status
        self.updated_at = datetime.utcnow()

        if new_status == OrderStatus.SUBMITTED:
            self.submitted_at = self.updated_at
        elif new_status == OrderStatus.FILLED:
            self.filled_at = self.updated_at

        self.state_history.append({
            "from": old_status.value,
            "to": new_status.value,
            "at": self.updated_at.isoformat(),
            "reason": reason,
        })

        logger.info(
            "Order %s (%s %s %s): %s -> %s%s",
            self.order_id[:8], self.side, self.ticker, self.action_type,
            old_status.value, new_status.value,
            f" ({reason})" if reason else "",
        )
        return True

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATES

    @property
    def is_filled(self) -> bool:
        return self.status == OrderStatus.FILLED

    @property
    def notional(self) -> float:
        if self.filled_avg_price and self.filled_quantity:
            return self.filled_quantity * self.filled_avg_price
        return 0.0

    def to_dict(self) -> dict:
        return {
            "order_id": self.order_id,
            "broker_order_id": self.broker_order_id,
            "ticker": self.ticker,
            "side": self.side,
            "action_type": self.action_type,
            "quantity": round(self.quantity, 4),
            "order_type": self.order_type,
            "limit_price": round(self.limit_price, 4) if self.limit_price else None,
            "status": self.status.value,
            "filled_quantity": round(self.filled_quantity, 4),
            "filled_avg_price": round(self.filled_avg_price, 4) if self.filled_avg_price else None,
            "notional": round(self.notional, 2),
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat(),
            "submitted_at": self.submitted_at.isoformat() if self.submitted_at else None,
            "filled_at": self.filled_at.isoformat() if self.filled_at else None,
            "state_history": self.state_history,
        }


def update_from_broker(order: LiveOrder, broker_order) -> None:
    """Update a LiveOrder from a BrokerOrder response.

    Args:
        order: The LiveOrder to update
        broker_order: BrokerOrder from the broker adapter
    """
    order.broker_order_id = broker_order.order_id
    order.filled_quantity = broker_order.filled_quantity
    if broker_order.fill_price:
        order.filled_avg_price = broker_order.fill_price

    # Map broker status string to OrderStatus
    status_map = {
        "new": OrderStatus.SUBMITTED,
        "accepted": OrderStatus.SUBMITTED,
        "partially_filled": OrderStatus.PARTIAL_FILL,
        "filled": OrderStatus.FILLED,
        "canceled": OrderStatus.CANCELED,
        "cancelled": OrderStatus.CANCELED,
        "expired": OrderStatus.EXPIRED,
        "rejected": OrderStatus.REJECTED,
        "pending_new": OrderStatus.SUBMITTED,
        "pending_cancel": OrderStatus.SUBMITTED,
    }

    broker_status = broker_order.status.lower() if isinstance(broker_order.status, str) else broker_order.status
    new_status = status_map.get(broker_status)

    if new_status and new_status != order.status:
        order.transition(new_status, f"broker status: {broker_status}")
