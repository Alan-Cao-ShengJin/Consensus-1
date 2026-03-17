"""Simple alerting: Slack webhook + console fallback.

Sends notifications for critical events like kill switch activation,
circuit breaker trips, order rejections, and reconciliation mismatches.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class AlertSeverity:
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


def send_alert(
    message: str,
    severity: str = AlertSeverity.WARNING,
    webhook_url: Optional[str] = None,
    context: Optional[dict] = None,
) -> bool:
    """Send an alert via Slack webhook or log fallback.

    Args:
        message: Alert message text
        severity: info, warning, or critical
        webhook_url: Slack incoming webhook URL (if None, logs to console)
        context: Optional additional context dict

    Returns:
        True if alert was delivered successfully
    """
    timestamp = datetime.utcnow().isoformat()
    icon = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}.get(severity, "📢")

    # Always log to console
    log_fn = {
        AlertSeverity.INFO: logger.info,
        AlertSeverity.WARNING: logger.warning,
        AlertSeverity.CRITICAL: logger.critical,
    }.get(severity, logger.warning)
    log_fn("ALERT [%s]: %s", severity.upper(), message)

    # Try Slack webhook
    if webhook_url:
        try:
            import requests
            payload = {
                "text": f"{icon} *[{severity.upper()}]* {message}",
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"{icon} *[{severity.upper()}]* {message}\n_{timestamp}_",
                        },
                    },
                ],
            }
            if context:
                context_text = "\n".join(f"• {k}: {v}" for k, v in context.items())
                payload["blocks"].append({
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"```{context_text}```"},
                })

            resp = requests.post(webhook_url, json=payload, timeout=10)
            if resp.status_code == 200:
                return True
            else:
                logger.warning("Slack webhook returned %d: %s", resp.status_code, resp.text)
        except ImportError:
            logger.warning("requests library not available for Slack alerts")
        except Exception as e:
            logger.warning("Failed to send Slack alert: %s", e)

    return True  # Console logging always succeeds


def alert_kill_switch(reason: str, webhook_url: Optional[str] = None) -> None:
    """Alert that the kill switch has been activated."""
    send_alert(
        f"KILL SWITCH ACTIVATED: {reason}",
        severity=AlertSeverity.CRITICAL,
        webhook_url=webhook_url,
        context={"reason": reason},
    )


def alert_circuit_breaker(messages: list[str], webhook_url: Optional[str] = None) -> None:
    """Alert that a circuit breaker has tripped."""
    send_alert(
        f"CIRCUIT BREAKER TRIPPED: {'; '.join(messages)}",
        severity=AlertSeverity.CRITICAL,
        webhook_url=webhook_url,
        context={"breakers": "; ".join(messages)},
    )


def alert_order_failure(ticker: str, error: str, webhook_url: Optional[str] = None) -> None:
    """Alert that an order submission failed."""
    send_alert(
        f"Order failed for {ticker}: {error}",
        severity=AlertSeverity.WARNING,
        webhook_url=webhook_url,
        context={"ticker": ticker, "error": error},
    )


def alert_reconciliation_mismatch(
    mismatches: list[str],
    webhook_url: Optional[str] = None,
) -> None:
    """Alert about reconciliation mismatches."""
    send_alert(
        f"Reconciliation mismatches: {len(mismatches)} issues found",
        severity=AlertSeverity.WARNING,
        webhook_url=webhook_url,
        context={"mismatches": "; ".join(mismatches[:5])},
    )
