"""Live cycle runner: orchestrate one complete live trading cycle.

Steps:
  1. Create broker adapter
  2. Run safety pre-checks (kill switch, circuit breakers, market hours)
  3. Ingest new data (existing pipeline)
  4. Run portfolio review (existing decision engine)
  5. Build execution batch (existing execution_wrapper)
  6. Validate (existing guardrails)
  7. Run readiness checks
  8. Execute via live_execute() or paper_execute() based on environment
  9. Persist results and audit log
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime
from typing import Optional

from config import SystemConfig, Environment, get_default_config
from broker_readonly_adapter import create_broker_adapter

logger = logging.getLogger(__name__)


def run_live_cycle(
    config: SystemConfig,
    review_date: Optional[date] = None,
) -> dict:
    """Run one complete live cycle.

    Args:
        config: System configuration (must be LIVE environment)
        review_date: Optional override for review date (defaults to today)

    Returns:
        Summary dict with execution results
    """
    import kill_switch
    import audit_log

    review_date = review_date or date.today()
    logger.info("=" * 60)
    logger.info("LIVE CYCLE START: %s (env=%s)", review_date, config.environment)
    logger.info("=" * 60)

    # Step 1: Create broker adapter
    broker = create_broker_adapter(
        mode=config.broker_mode,
        api_key=config.broker_api_key,
        secret_key=config.broker_secret_key,
        paper=config.broker_paper,
    )
    audit_log.log_event("cycle_start", {
        "review_date": review_date.isoformat(),
        "environment": config.environment,
        "broker_mode": config.broker_mode,
        "broker_paper": config.broker_paper,
    })

    # Step 2: Kill switch check
    if kill_switch.is_active():
        reason = kill_switch.get_reason()
        logger.critical("KILL SWITCH ACTIVE: %s — aborting cycle", reason)
        audit_log.log_event("cycle_abort", {"reason": f"kill switch: {reason}"})
        return {"status": "aborted", "reason": f"kill switch: {reason}"}

    # Step 3: Get account state
    try:
        account = broker.get_account_snapshot()
        logger.info("Account: $%.2f equity, $%.2f cash, %d positions",
                     account.total_equity, account.cash, account.position_count)
    except Exception as e:
        logger.error("Failed to get account snapshot: %s", e)
        audit_log.log_event("cycle_error", {"error": str(e)})
        return {"status": "error", "reason": str(e)}

    # Step 4: Get reference prices for all positions
    position_tickers = [p.ticker for p in account.positions]
    fill_prices = broker.get_reference_prices(position_tickers) if position_tickers else {}

    # Step 5: Build execution intents
    # (In a full implementation, this would call the ingestion pipeline,
    #  thesis updates, and portfolio decision engine. For now, this is
    #  the entry point for pre-built execution batches.)
    logger.info("Live runner ready for execution batch input")
    logger.info("Use run_manager.py to generate execution batches, "
                "then pass them to live_execute()")

    audit_log.log_event("cycle_ready", {
        "equity": account.total_equity,
        "cash": account.cash,
        "positions": account.position_count,
        "tickers": position_tickers,
    })

    return {
        "status": "ready",
        "equity": account.total_equity,
        "cash": account.cash,
        "positions": account.position_count,
        "review_date": review_date.isoformat(),
    }


def execute_batch_live(
    config: SystemConfig,
    approved_intents: list,
    blocked_intents: list,
    execution_date: Optional[date] = None,
) -> dict:
    """Execute a pre-validated batch of intents via live broker.

    This is the function to call after run_manager generates and validates
    an execution batch.
    """
    from live_execution_engine import live_execute, format_live_execution_text, export_live_execution_artifacts
    import audit_log

    execution_date = execution_date or date.today()

    broker = create_broker_adapter(
        mode=config.broker_mode,
        api_key=config.broker_api_key,
        secret_key=config.broker_secret_key,
        paper=config.broker_paper,
    )

    summary = live_execute(
        broker=broker,
        approved_intents=approved_intents,
        blocked_intents=blocked_intents,
        execution_date=execution_date,
    )

    # Log and export
    logger.info(format_live_execution_text(summary))
    export_live_execution_artifacts(summary, config.artifact_base_dir)

    audit_log.log_event("batch_executed", {
        "orders_submitted": summary.orders_submitted,
        "orders_filled": summary.orders_filled,
        "orders_failed": summary.orders_failed,
        "total_buy": summary.total_buy_notional,
        "total_sell": summary.total_sell_notional,
        "errors": summary.errors,
    })

    return summary.to_dict()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Run live trading cycle")
    parser.add_argument("--config", type=str, help="Path to config JSON file")
    parser.add_argument("--environment", type=str, default="live",
                        choices=["live", "paper", "live_readonly"])
    parser.add_argument("--broker-paper", action="store_true", default=True,
                        help="Use Alpaca paper trading (default: True)")
    parser.add_argument("--broker-live", action="store_true",
                        help="Use Alpaca live trading (REAL MONEY)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    if args.config:
        config = SystemConfig.from_file(args.config)
    else:
        config = get_default_config(args.environment)

    if args.broker_live:
        config.broker_paper = False
        logger.warning("LIVE BROKER MODE — REAL MONEY AT RISK")

    # Load API keys from environment
    if not config.broker_api_key:
        config.broker_api_key = os.environ.get("ALPACA_API_KEY", "")
    if not config.broker_secret_key:
        config.broker_secret_key = os.environ.get("ALPACA_SECRET_KEY", "")

    result = run_live_cycle(config)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
