"""Kill switch: emergency halt for all live trading.

When active, the live execution engine refuses all order submissions
and cancels all open orders. Can be activated manually (file/env var)
or automatically by circuit breakers.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

KILL_SWITCH_FILE = os.path.join("artifacts", "KILL_SWITCH")
KILL_SWITCH_ENV = "CONSENSUS_KILL_SWITCH"


def is_active() -> bool:
    """Check if the kill switch is engaged."""
    if os.environ.get(KILL_SWITCH_ENV, "").strip() == "1":
        return True
    return os.path.exists(KILL_SWITCH_FILE)


def get_reason() -> Optional[str]:
    """Read the kill switch reason, if any."""
    if os.path.exists(KILL_SWITCH_FILE):
        try:
            with open(KILL_SWITCH_FILE, "r") as f:
                data = json.load(f)
            return data.get("reason", "unknown")
        except Exception:
            return "kill switch file exists (unparseable)"
    if os.environ.get(KILL_SWITCH_ENV, "").strip() == "1":
        return "CONSENSUS_KILL_SWITCH env var set to 1"
    return None


def activate(reason: str) -> None:
    """Engage the kill switch. Creates the kill switch file."""
    os.makedirs(os.path.dirname(KILL_SWITCH_FILE), exist_ok=True)
    payload = {
        "activated_at": datetime.utcnow().isoformat(),
        "reason": reason,
    }
    with open(KILL_SWITCH_FILE, "w") as f:
        json.dump(payload, f, indent=2)
    logger.critical("KILL SWITCH ACTIVATED: %s", reason)


def deactivate() -> None:
    """Disengage the kill switch. Removes the kill switch file."""
    if os.path.exists(KILL_SWITCH_FILE):
        os.remove(KILL_SWITCH_FILE)
        logger.warning("Kill switch deactivated")
    else:
        logger.info("Kill switch was not active")


def cancel_all_open(broker) -> int:
    """Cancel all open orders via broker. Returns count cancelled."""
    try:
        if hasattr(broker, "cancel_all_orders"):
            count = broker.cancel_all_orders()
        else:
            orders = broker.get_open_orders()
            count = 0
            for order in orders:
                try:
                    broker.cancel_order(order.order_id)
                    count += 1
                except Exception as e:
                    logger.error("Failed to cancel order %s: %s", order.order_id, e)
        logger.warning("Cancelled %d open orders via kill switch", count)
        return count
    except Exception as e:
        logger.error("Failed to cancel open orders: %s", e)
        return 0
