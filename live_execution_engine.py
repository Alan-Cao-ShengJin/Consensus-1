"""Live execution engine: submit real orders via broker adapter.

Mirrors paper_execution_engine.py structure (sells first, then buys)
but routes through a real broker with safety checks at every step.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from broker_interface import BrokerInterface, BrokerOrder
from execution_wrapper import OrderIntent
from execution_policy import ExecutionPolicyConfig, DEFAULT_POLICY
from models import ActionType
from order_state_machine import LiveOrder, OrderStatus, update_from_broker
import kill_switch
import circuit_breakers
import market_hours

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Execution summary
# ---------------------------------------------------------------------------

@dataclass
class LiveExecutionSummary:
    """Summary of one live execution run."""
    execution_date: date
    review_date: Optional[str]
    intents_received: int
    intents_approved: int
    intents_blocked: int
    orders_submitted: int
    orders_filled: int
    orders_failed: int
    total_buy_notional: float
    total_sell_notional: float
    orders: list[LiveOrder] = field(default_factory=list)
    blocked_intents: list[OrderIntent] = field(default_factory=list)
    safety_checks: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "execution_date": self.execution_date.isoformat(),
            "review_date": self.review_date,
            "intents_received": self.intents_received,
            "intents_approved": self.intents_approved,
            "intents_blocked": self.intents_blocked,
            "orders_submitted": self.orders_submitted,
            "orders_filled": self.orders_filled,
            "orders_failed": self.orders_failed,
            "total_buy_notional": round(self.total_buy_notional, 2),
            "total_sell_notional": round(self.total_sell_notional, 2),
            "orders": [o.to_dict() for o in self.orders],
            "blocked_intents": [oi.to_dict() for oi in self.blocked_intents],
            "safety_checks": self.safety_checks,
            "errors": self.errors,
        }


# ---------------------------------------------------------------------------
# Pre-execution safety checks
# ---------------------------------------------------------------------------

def _run_safety_checks(
    broker: BrokerInterface,
    breaker_config: Optional[circuit_breakers.CircuitBreakerConfig] = None,
) -> tuple[bool, dict]:
    """Run all safety checks before executing orders.

    Returns:
        (safe_to_proceed, check_results_dict)
    """
    results = {}
    safe = True

    # Kill switch
    if kill_switch.is_active():
        reason = kill_switch.get_reason()
        results["kill_switch"] = {"passed": False, "reason": reason}
        logger.critical("KILL SWITCH IS ACTIVE: %s — aborting execution", reason)
        return False, results
    results["kill_switch"] = {"passed": True}

    # Market hours
    market_open = market_hours.is_market_open(broker)
    results["market_hours"] = {"passed": market_open, "is_open": market_open}
    if not market_open:
        logger.warning("Market is closed — aborting execution")
        safe = False

    # Circuit breakers (best effort — need account data)
    try:
        account = broker.get_account_snapshot()
        current_equity = account.total_equity
        # Use total_equity as both high-water mark and SOD value if no history
        # In production, these should be loaded from persistent storage
        high_water = float(os.environ.get("CONSENSUS_HIGH_WATER_MARK", str(current_equity)))
        sod_value = float(os.environ.get("CONSENSUS_SOD_VALUE", str(current_equity)))
        today_pnl = current_equity - sod_value

        positions = [
            {"ticker": p.ticker, "weight_pct": (p.market_value / current_equity * 100.0) if current_equity > 0 else 0}
            for p in account.positions
        ]

        tripped, messages = circuit_breakers.run_all_checks(
            current_equity=current_equity,
            high_water_mark=high_water,
            today_pnl=today_pnl,
            portfolio_value_sod=sod_value,
            positions=positions,
            config=breaker_config,
        )
        results["circuit_breakers"] = {"passed": not tripped, "messages": messages}
        if tripped:
            logger.critical("CIRCUIT BREAKER TRIPPED — activating kill switch")
            kill_switch.activate(f"Circuit breaker: {'; '.join(messages)}")
            kill_switch.cancel_all_open(broker)
            safe = False
    except Exception as e:
        results["circuit_breakers"] = {"passed": True, "error": str(e)}
        logger.warning("Circuit breaker check failed (proceeding): %s", e)

    return safe, results


# ---------------------------------------------------------------------------
# Submit a single order
# ---------------------------------------------------------------------------

def _submit_intent(
    broker: BrokerInterface,
    intent: OrderIntent,
    execution_date: date,
) -> LiveOrder:
    """Convert an OrderIntent to a LiveOrder and submit to broker."""
    order = LiveOrder(
        ticker=intent.ticker,
        side=intent.side,
        quantity=abs(intent.estimated_shares) if intent.estimated_shares else 0.0,
        order_type="market",
        action_type=intent.action_type.value if isinstance(intent.action_type, ActionType) else str(intent.action_type),
        intent_id=f"{intent.ticker}_{intent.review_date}",
    )

    # For exits, we may need to look up actual position size
    if intent.action_type == ActionType.EXIT and order.quantity == 0:
        try:
            positions = broker.get_positions()
            for pos in positions:
                if pos.ticker == intent.ticker:
                    order.quantity = pos.shares
                    break
        except Exception as e:
            logger.error("Failed to get position for EXIT %s: %s", intent.ticker, e)

    if order.quantity <= 0:
        order.error_message = "Zero or negative quantity"
        order.transition(OrderStatus.SUBMITTED)
        order.transition(OrderStatus.REJECTED, "zero quantity")
        return order

    # Safety check: kill switch could have been tripped mid-batch
    if kill_switch.is_active():
        order.error_message = "Kill switch activated mid-batch"
        order.transition(OrderStatus.SUBMITTED)
        order.transition(OrderStatus.CANCELED, "kill switch")
        return order

    # Submit to broker
    try:
        order.transition(OrderStatus.SUBMITTED)
        broker_order: BrokerOrder = broker.submit_order(
            ticker=intent.ticker,
            side=intent.side,
            quantity=order.quantity,
            order_type=order.order_type,
            time_in_force=order.time_in_force,
            limit_price=order.limit_price,
        )
        update_from_broker(order, broker_order)

    except Exception as e:
        order.error_message = str(e)
        order.transition(OrderStatus.REJECTED, f"broker error: {e}")
        logger.error("Order submission failed for %s: %s", intent.ticker, e)

    return order


# ---------------------------------------------------------------------------
# Main execution function
# ---------------------------------------------------------------------------

def live_execute(
    broker: BrokerInterface,
    approved_intents: list[OrderIntent],
    blocked_intents: list[OrderIntent],
    execution_date: date,
    config: ExecutionPolicyConfig = DEFAULT_POLICY,
    breaker_config: Optional[circuit_breakers.CircuitBreakerConfig] = None,
) -> LiveExecutionSummary:
    """Execute validated order intents via live broker.

    Args:
        broker: Live broker adapter (Alpaca or similar)
        approved_intents: Intents that passed guardrails
        blocked_intents: Intents that failed guardrails (recorded only)
        execution_date: Date of execution
        config: Execution policy for sizing
        breaker_config: Circuit breaker thresholds
    """
    review_date = approved_intents[0].review_date if approved_intents else None

    # Run safety checks
    safe, check_results = _run_safety_checks(broker, breaker_config)

    if not safe:
        logger.warning("Safety checks failed — returning without executing")
        return LiveExecutionSummary(
            execution_date=execution_date,
            review_date=review_date,
            intents_received=len(approved_intents) + len(blocked_intents),
            intents_approved=len(approved_intents),
            intents_blocked=len(blocked_intents),
            orders_submitted=0,
            orders_filled=0,
            orders_failed=0,
            total_buy_notional=0.0,
            total_sell_notional=0.0,
            blocked_intents=blocked_intents,
            safety_checks=check_results,
            errors=["Safety checks failed — no orders submitted"],
        )

    # Order execution: sells first, then buys (to free capital)
    sells = [oi for oi in approved_intents if oi.side == "sell"]
    buys = [oi for oi in approved_intents if oi.side == "buy"]
    ordered = sells + buys

    orders: list[LiveOrder] = []
    total_buy = 0.0
    total_sell = 0.0
    errors: list[str] = []

    for intent in ordered:
        order = _submit_intent(broker, intent, execution_date)
        orders.append(order)

        if order.is_filled:
            if order.side == "buy":
                total_buy += order.notional
            else:
                total_sell += order.notional
        elif order.status == OrderStatus.SUBMITTED:
            # Market order — may fill asynchronously
            # For market orders, treat submitted as effectively filled
            if order.order_type == "market" and order.quantity > 0:
                logger.info("Market order for %s submitted (broker_id=%s), "
                            "will reconcile fill later",
                            order.ticker, order.broker_order_id)
        elif order.status in (OrderStatus.REJECTED, OrderStatus.CANCELED):
            errors.append(f"{order.ticker}: {order.error_message}")

    filled = sum(1 for o in orders if o.is_filled)
    failed = sum(1 for o in orders if o.status in (OrderStatus.REJECTED, OrderStatus.CANCELED))
    submitted = sum(1 for o in orders if o.status == OrderStatus.SUBMITTED)

    logger.info(
        "Live execution complete: %d submitted, %d filled, %d failed out of %d intents",
        submitted + filled, filled, failed, len(approved_intents),
    )

    return LiveExecutionSummary(
        execution_date=execution_date,
        review_date=review_date,
        intents_received=len(approved_intents) + len(blocked_intents),
        intents_approved=len(approved_intents),
        intents_blocked=len(blocked_intents),
        orders_submitted=submitted + filled,
        orders_filled=filled,
        orders_failed=failed,
        total_buy_notional=total_buy,
        total_sell_notional=total_sell,
        orders=orders,
        blocked_intents=blocked_intents,
        safety_checks=check_results,
        errors=errors,
    )


# ---------------------------------------------------------------------------
# Export artifacts
# ---------------------------------------------------------------------------

def export_live_execution_artifacts(
    summary: LiveExecutionSummary,
    output_dir: str = "execution_outputs",
) -> str:
    """Export live execution artifacts to JSON files."""
    os.makedirs(output_dir, exist_ok=True)
    date_str = summary.execution_date.isoformat()

    with open(os.path.join(output_dir, f"{date_str}_live_execution_summary.json"), "w") as f:
        json.dump(summary.to_dict(), f, indent=2)

    return output_dir


def format_live_execution_text(summary: LiveExecutionSummary) -> str:
    """Format live execution summary as human-readable text."""
    lines = []
    lines.append("=" * 60)
    lines.append("LIVE EXECUTION SUMMARY")
    lines.append("=" * 60)
    lines.append(f"  Execution date:    {summary.execution_date}")
    lines.append(f"  Review date:       {summary.review_date}")
    lines.append(f"  Intents received:  {summary.intents_received}")
    lines.append(f"  Intents approved:  {summary.intents_approved}")
    lines.append(f"  Intents blocked:   {summary.intents_blocked}")
    lines.append(f"  Orders submitted:  {summary.orders_submitted}")
    lines.append(f"  Orders filled:     {summary.orders_filled}")
    lines.append(f"  Orders failed:     {summary.orders_failed}")
    lines.append(f"  Total buy:         ${summary.total_buy_notional:,.2f}")
    lines.append(f"  Total sell:        ${summary.total_sell_notional:,.2f}")
    lines.append("")

    if summary.orders:
        lines.append("ORDERS:")
        for o in summary.orders:
            price_str = f"@ ${o.filled_avg_price:,.2f}" if o.filled_avg_price else ""
            lines.append(
                f"  {o.action_type:10s} {o.ticker:6s} "
                f"{o.side:4s} {o.quantity:8.2f} shares {price_str} "
                f"[{o.status.value}]"
            )
        lines.append("")

    if summary.errors:
        lines.append("ERRORS:")
        for err in summary.errors:
            lines.append(f"  {err}")
        lines.append("")

    if summary.safety_checks:
        lines.append("SAFETY CHECKS:")
        for check, result in summary.safety_checks.items():
            passed = result.get("passed", "?")
            lines.append(f"  {check}: {'PASS' if passed else 'FAIL'}")

    return "\n".join(lines)
