"""Pre-trade live-readiness checks.

Before a batch could ever be eligible for live routing, validate:
  - Environment is unambiguous
  - Broker/account sync succeeded recently enough
  - Reconciliation issues are below threshold
  - Approval exists and is current
  - Order intents are consistent with external state
  - No duplicate/open batch ambiguity

In Step 12, these checks only report and block. They do not send orders.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from account_sync import ReconciliationResult
from approval_hardened import ApprovalRecord, HardenedApprovalStatus
from broker_interface import AccountSnapshot
from config import Environment

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Check result
# ---------------------------------------------------------------------------

@dataclass
class ReadinessCheck:
    """Result of a single readiness check."""
    name: str
    passed: bool
    message: str
    severity: str = "error"  # "error" or "warning"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "passed": self.passed,
            "message": self.message,
            "severity": self.severity,
        }


@dataclass
class ReadinessReport:
    """Aggregated result of all pre-trade readiness checks."""
    checked_at: str = ""
    environment: str = ""
    checks: list[ReadinessCheck] = field(default_factory=list)
    all_passed: bool = True
    error_count: int = 0
    warning_count: int = 0

    def __post_init__(self):
        if not self.checked_at:
            self.checked_at = datetime.utcnow().isoformat()

    def add(self, check: ReadinessCheck):
        self.checks.append(check)
        if not check.passed:
            if check.severity == "error":
                self.all_passed = False
                self.error_count += 1
            else:
                self.warning_count += 1

    def to_dict(self) -> dict:
        return {
            "checked_at": self.checked_at,
            "environment": self.environment,
            "all_passed": self.all_passed,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "checks": [c.to_dict() for c in self.checks],
        }


# ---------------------------------------------------------------------------
# Default thresholds
# ---------------------------------------------------------------------------

MAX_SYNC_AGE_MINUTES = 60
MAX_UNRESOLVED_MISMATCHES = 0
MAX_CASH_MISMATCH_DOLLARS = 100.0


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_environment(environment: str) -> ReadinessCheck:
    """Environment must be live_readonly or live."""
    if environment in (Environment.LIVE_READONLY, Environment.LIVE):
        return ReadinessCheck(
            name="environment",
            passed=True,
            message=f"Environment is {environment}",
        )
    elif environment in (Environment.DEMO, Environment.PAPER):
        return ReadinessCheck(
            name="environment",
            passed=False,
            message=f"Environment is {environment} — not live. "
                    f"Broker sync results may not reflect real account state.",
        )
    elif environment == Environment.LIVE_DISABLED:
        return ReadinessCheck(
            name="environment",
            passed=False,
            message="Environment is live_disabled — broker operations are blocked",
        )
    else:
        return ReadinessCheck(
            name="environment",
            passed=False,
            message=f"Unknown environment: {environment}",
        )


def check_sync_freshness(
    reconciliation: Optional[ReconciliationResult],
    max_age_minutes: int = MAX_SYNC_AGE_MINUTES,
) -> ReadinessCheck:
    """Broker sync must have succeeded recently enough."""
    if reconciliation is None:
        return ReadinessCheck(
            name="sync_freshness",
            passed=False,
            message="No reconciliation result available — sync has not been performed",
        )

    try:
        recon_time = datetime.fromisoformat(reconciliation.reconciled_at)
        age = datetime.utcnow() - recon_time
        if age > timedelta(minutes=max_age_minutes):
            return ReadinessCheck(
                name="sync_freshness",
                passed=False,
                message=f"Sync is {age.total_seconds()/60:.0f} min old, "
                        f"max allowed is {max_age_minutes} min",
            )
        return ReadinessCheck(
            name="sync_freshness",
            passed=True,
            message=f"Sync is {age.total_seconds()/60:.0f} min old (within {max_age_minutes} min window)",
        )
    except (ValueError, TypeError) as e:
        return ReadinessCheck(
            name="sync_freshness",
            passed=False,
            message=f"Cannot parse reconciliation timestamp: {e}",
        )


def check_reconciliation_clean(
    reconciliation: Optional[ReconciliationResult],
    max_unresolved: int = MAX_UNRESOLVED_MISMATCHES,
    max_cash_diff: float = MAX_CASH_MISMATCH_DOLLARS,
) -> ReadinessCheck:
    """Reconciliation issues must be below allowed threshold."""
    if reconciliation is None:
        return ReadinessCheck(
            name="reconciliation_clean",
            passed=False,
            message="No reconciliation result available",
        )

    issues = []
    if reconciliation.unresolved_count > max_unresolved:
        issues.append(
            f"{reconciliation.unresolved_count} unresolved differences "
            f"(max allowed: {max_unresolved})"
        )
    if reconciliation.cash_diff is not None and abs(reconciliation.cash_diff) > max_cash_diff:
        issues.append(
            f"Cash mismatch ${reconciliation.cash_diff:.2f} "
            f"exceeds ${max_cash_diff:.2f} threshold"
        )

    if issues:
        return ReadinessCheck(
            name="reconciliation_clean",
            passed=False,
            message="; ".join(issues),
        )
    return ReadinessCheck(
        name="reconciliation_clean",
        passed=True,
        message="Reconciliation is clean",
    )


def check_approval_current(
    approval: Optional[ApprovalRecord],
) -> ReadinessCheck:
    """Approval must exist and be in APPROVED state (not expired)."""
    if approval is None:
        return ReadinessCheck(
            name="approval_current",
            passed=False,
            message="No approval record found",
        )

    if approval.is_expired:
        return ReadinessCheck(
            name="approval_current",
            passed=False,
            message=f"Approval expired at {approval.expires_at}",
        )

    if approval.status == HardenedApprovalStatus.REJECTED:
        return ReadinessCheck(
            name="approval_current",
            passed=False,
            message=f"Approval was rejected: {approval.rejection_reason or 'no reason'}",
        )

    if approval.status == HardenedApprovalStatus.PENDING:
        return ReadinessCheck(
            name="approval_current",
            passed=False,
            message="Approval is still pending",
        )

    if approval.status == HardenedApprovalStatus.APPROVED:
        return ReadinessCheck(
            name="approval_current",
            passed=True,
            message=f"Approved by {approval.approver_id or 'unknown'} "
                    f"at {approval.updated_at}",
        )

    return ReadinessCheck(
        name="approval_current",
        passed=False,
        message=f"Unknown approval status: {approval.status}",
    )


def check_intents_consistent(
    reconciliation: Optional[ReconciliationResult],
) -> ReadinessCheck:
    """Order intents must be consistent with external account state."""
    if reconciliation is None:
        return ReadinessCheck(
            name="intents_consistent",
            passed=False,
            message="No reconciliation result to check intents against",
        )

    infeasible = [ic for ic in reconciliation.intent_checks if not ic.feasible]
    conflicts = reconciliation.order_conflicts

    issues = []
    if infeasible:
        tickers = ", ".join(ic.ticker for ic in infeasible)
        issues.append(f"{len(infeasible)} infeasible intents: {tickers}")
    if conflicts:
        tickers = ", ".join(c.ticker for c in conflicts)
        issues.append(f"{len(conflicts)} order conflicts: {tickers}")

    if issues:
        return ReadinessCheck(
            name="intents_consistent",
            passed=False,
            message="; ".join(issues),
        )
    return ReadinessCheck(
        name="intents_consistent",
        passed=True,
        message="All intents consistent with external state",
    )


def check_no_duplicate_batch(
    batch_id: Optional[str],
    prior_batch_ids: Optional[list[str]] = None,
) -> ReadinessCheck:
    """No unresolved duplicate/open batch ambiguity."""
    if not batch_id:
        return ReadinessCheck(
            name="no_duplicate_batch",
            passed=False,
            message="No batch_id provided",
        )
    if prior_batch_ids and batch_id in prior_batch_ids:
        return ReadinessCheck(
            name="no_duplicate_batch",
            passed=False,
            message=f"Batch {batch_id} already exists in prior batches",
        )
    return ReadinessCheck(
        name="no_duplicate_batch",
        passed=True,
        message=f"Batch {batch_id} is unique",
    )


def check_no_live_order_path(environment: str) -> ReadinessCheck:
    """Verify live order path status.

    For LIVE environment, this check PASSES (live orders are intentional).
    For all other environments, live order path must be blocked.
    """
    if environment == Environment.LIVE:
        return ReadinessCheck(
            name="live_order_path",
            passed=True,
            message="Live order path is ENABLED — real money at risk",
            severity="warning",
        )
    blocked = {Environment.DEMO, Environment.PAPER, Environment.LIVE_READONLY, Environment.LIVE_DISABLED}
    if environment in blocked:
        return ReadinessCheck(
            name="live_order_path",
            passed=True,
            message=f"Live order path is blocked in {environment} mode",
        )
    return ReadinessCheck(
        name="live_order_path",
        passed=False,
        message=f"Environment {environment} has unknown live order status — DANGEROUS",
    )


def check_kill_switch() -> ReadinessCheck:
    """Kill switch must not be active."""
    import kill_switch
    if kill_switch.is_active():
        reason = kill_switch.get_reason()
        return ReadinessCheck(
            name="kill_switch",
            passed=False,
            message=f"Kill switch is ACTIVE: {reason}",
        )
    return ReadinessCheck(
        name="kill_switch",
        passed=True,
        message="Kill switch is not active",
    )


def check_market_open(broker=None) -> ReadinessCheck:
    """Market must be open for live trading."""
    import market_hours
    is_open = market_hours.is_market_open(broker)
    if not is_open:
        next_open = market_hours.next_market_open(broker)
        return ReadinessCheck(
            name="market_hours",
            passed=False,
            message=f"Market is closed (next open: {next_open or 'unknown'})",
        )
    return ReadinessCheck(
        name="market_hours",
        passed=True,
        message="Market is open",
    )


# ---------------------------------------------------------------------------
# Full readiness assessment
# ---------------------------------------------------------------------------

def run_readiness_checks(
    environment: str,
    reconciliation: Optional[ReconciliationResult] = None,
    approval: Optional[ApprovalRecord] = None,
    batch_id: Optional[str] = None,
    prior_batch_ids: Optional[list[str]] = None,
    broker=None,
    max_sync_age_minutes: int = MAX_SYNC_AGE_MINUTES,
    max_unresolved: int = MAX_UNRESOLVED_MISMATCHES,
    max_cash_diff: float = MAX_CASH_MISMATCH_DOLLARS,
) -> ReadinessReport:
    """Run all pre-trade readiness checks.

    Returns ReadinessReport with per-check results and overall pass/fail.
    """
    report = ReadinessReport(environment=environment)

    report.add(check_environment(environment))
    report.add(check_no_live_order_path(environment))
    report.add(check_kill_switch())
    report.add(check_sync_freshness(reconciliation, max_sync_age_minutes))
    report.add(check_reconciliation_clean(reconciliation, max_unresolved, max_cash_diff))
    report.add(check_approval_current(approval))
    report.add(check_intents_consistent(reconciliation))
    report.add(check_no_duplicate_batch(batch_id, prior_batch_ids))

    # Live-specific checks
    if environment == Environment.LIVE:
        report.add(check_market_open(broker))

    logger.info(
        "Readiness checks: %s (%d errors, %d warnings)",
        "PASS" if report.all_passed else "FAIL",
        report.error_count,
        report.warning_count,
    )
    return report


# ---------------------------------------------------------------------------
# Text formatting
# ---------------------------------------------------------------------------

def format_readiness_text(report: ReadinessReport) -> str:
    """Format readiness report as human-readable text."""
    lines = []
    lines.append("=" * 60)
    lines.append("LIVE-READINESS CHECK REPORT")
    lines.append("=" * 60)
    lines.append(f"Checked at: {report.checked_at}")
    lines.append(f"Environment: {report.environment}")
    lines.append("")

    verdict = "PASS" if report.all_passed else "FAIL"
    lines.append(f"Overall: {verdict}")
    lines.append(f"Errors: {report.error_count}  Warnings: {report.warning_count}")
    lines.append("")

    for c in report.checks:
        status = "PASS" if c.passed else c.severity.upper()
        lines.append(f"  [{status}] {c.name}: {c.message}")

    lines.append("")
    lines.append("=" * 60)
    return "\n".join(lines)
