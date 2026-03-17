"""Append-only audit log for live trading events.

Writes JSON-lines to artifacts/audit_log.jsonl.
Separate from DB records — a failsafe that works even if the DB is corrupted.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)

AUDIT_LOG_PATH = os.path.join("artifacts", "audit_log.jsonl")


def log_event(event_type: str, details: dict, environment: str = "") -> None:
    """Append an audit event to the log file.

    Args:
        event_type: e.g. "order_submitted", "kill_switch_activated", "circuit_breaker_tripped"
        details: Arbitrary event data
        environment: Optional environment label
    """
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "event_type": event_type,
        "environment": environment,
        "details": details,
    }

    try:
        os.makedirs(os.path.dirname(AUDIT_LOG_PATH), exist_ok=True)
        with open(AUDIT_LOG_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        # Audit logging must never crash the system
        logger.error("Failed to write audit log: %s", e)


def read_recent(n: int = 50) -> list[dict]:
    """Read the most recent N audit events."""
    if not os.path.exists(AUDIT_LOG_PATH):
        return []
    try:
        with open(AUDIT_LOG_PATH, "r") as f:
            lines = f.readlines()
        entries = []
        for line in lines[-n:]:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
        return entries
    except Exception as e:
        logger.error("Failed to read audit log: %s", e)
        return []


def clear_log() -> None:
    """Clear the audit log (use with caution)."""
    if os.path.exists(AUDIT_LOG_PATH):
        os.remove(AUDIT_LOG_PATH)
        logger.warning("Audit log cleared")
