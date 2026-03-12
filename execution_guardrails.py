"""Execution guardrails: strict pre-trade validation layer.

Every order intent must pass all guardrails before execution.
If any guardrail fails, the intent is blocked with a recorded reason.
Guardrails never silently fix — they block and report.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from models import ActionType
from execution_wrapper import OrderIntent, ExecutionBatch, NON_TRADING_ACTIONS
from execution_policy import ExecutionPolicyConfig, DEFAULT_POLICY

logger = logging.getLogger(__name__)


@dataclass
class GuardrailResult:
    """Result of validating one order intent."""
    ticker: str
    passed: bool
    violations: list[str] = field(default_factory=list)


@dataclass
class BatchValidationResult:
    """Result of validating a full execution batch."""
    all_passed: bool = True
    intent_results: list[GuardrailResult] = field(default_factory=list)
    blocked_intents: list[OrderIntent] = field(default_factory=list)
    approved_intents: list[OrderIntent] = field(default_factory=list)
    batch_violations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "all_passed": self.all_passed,
            "approved_count": len(self.approved_intents),
            "blocked_count": len(self.blocked_intents),
            "batch_violations": self.batch_violations,
            "intent_results": [
                {"ticker": r.ticker, "passed": r.passed, "violations": r.violations}
                for r in self.intent_results
            ],
        }


# ---------------------------------------------------------------------------
# Individual guardrail checks
# ---------------------------------------------------------------------------

def _check_no_trade_for_non_trading(intent: OrderIntent) -> Optional[str]:
    """No order should exist for HOLD / PROBATION / NO_ACTION."""
    if intent.action_type in NON_TRADING_ACTIONS:
        return f"Order generated for non-trading action {intent.action_type.value}"
    return None


def _check_no_duplicate_conflicting(
    intent: OrderIntent,
    all_intents: list[OrderIntent],
) -> Optional[str]:
    """No duplicate conflicting orders for the same ticker."""
    same_ticker = [oi for oi in all_intents if oi.ticker == intent.ticker and oi is not intent]
    for other in same_ticker:
        if intent.side != other.side:
            return (
                f"Conflicting orders for {intent.ticker}: "
                f"{intent.side} ({intent.action_type.value}) vs "
                f"{other.side} ({other.action_type.value})"
            )
    return None


def _check_no_negative_target_weight(intent: OrderIntent) -> Optional[str]:
    """Target weight must not be negative."""
    if intent.target_weight_after < -0.001:
        return f"Negative target weight: {intent.target_weight_after:.4f}%"
    return None


def _check_max_position_weight(
    intent: OrderIntent,
    config: ExecutionPolicyConfig,
) -> Optional[str]:
    """Target weight must not exceed configured cap."""
    if intent.target_weight_after > config.max_single_position_weight_pct + 0.001:
        return (
            f"Target weight {intent.target_weight_after:.2f}% exceeds "
            f"max {config.max_single_position_weight_pct:.2f}%"
        )
    return None


def _check_reference_price_exists(intent: OrderIntent) -> Optional[str]:
    """Every order must have a reference price."""
    if intent.reference_price is None or intent.reference_price <= 0:
        return "No reference price available"
    return None


def _check_not_blocked_recommendation(intent: OrderIntent) -> Optional[str]:
    """Blocked recommendations should not produce intents (defense in depth)."""
    if intent.is_blocked:
        return f"Intent already marked as blocked: {intent.block_reasons}"
    return None


def _check_funded_pair_exists(
    intent: OrderIntent,
    all_intents: list[OrderIntent],
) -> Optional[str]:
    """If intent has a linked_funding_ticker, the corresponding sell must exist."""
    if intent.linked_funding_ticker is None:
        return None
    funding_intents = [
        oi for oi in all_intents
        if oi.ticker == intent.linked_funding_ticker
        and oi.side == "sell"
    ]
    if not funding_intents:
        return (
            f"Funded by {intent.linked_funding_ticker} but no sell order "
            f"for that ticker in batch"
        )
    return None


# ---------------------------------------------------------------------------
# Batch-level guardrails
# ---------------------------------------------------------------------------

def _check_gross_exposure(
    intents: list[OrderIntent],
    current_weights: dict[str, float],
    config: ExecutionPolicyConfig,
) -> Optional[str]:
    """Total gross exposure after all intents must not exceed max."""
    projected = dict(current_weights)
    for intent in intents:
        projected[intent.ticker] = intent.target_weight_after

    total_exposure = sum(w for w in projected.values() if w > 0)
    if total_exposure > config.max_gross_exposure_pct + 0.01:
        return (
            f"Total gross exposure {total_exposure:.2f}% exceeds "
            f"max {config.max_gross_exposure_pct:.2f}%"
        )
    return None


def _check_turnover_cap(
    intents: list[OrderIntent],
    portfolio_value: float,
    config: ExecutionPolicyConfig,
) -> Optional[str]:
    """Total turnover must not exceed weekly cap."""
    total_turnover_pct = sum(
        abs(oi.target_weight_after - oi.current_weight) for oi in intents
    )
    if total_turnover_pct > config.max_weekly_turnover_pct + 0.01:
        return (
            f"Total turnover {total_turnover_pct:.2f}% exceeds "
            f"weekly cap {config.max_weekly_turnover_pct:.2f}%"
        )
    return None


# ---------------------------------------------------------------------------
# Cooldown / probation check
# ---------------------------------------------------------------------------

def _check_cooldown_probation(
    intent: OrderIntent,
    cooldown_tickers: set[str],
    probation_tickers: set[str],
) -> Optional[str]:
    """No buy orders for tickers on cooldown or probation."""
    if intent.side != "buy":
        return None
    if intent.ticker in cooldown_tickers:
        return f"{intent.ticker} is on cooldown — buy blocked"
    if intent.ticker in probation_tickers and intent.action_type == ActionType.ADD:
        return f"{intent.ticker} is on probation — add blocked"
    return None


# ---------------------------------------------------------------------------
# Main validation entry point
# ---------------------------------------------------------------------------

def validate_execution_batch(
    batch: ExecutionBatch,
    current_weights: dict[str, float],
    config: ExecutionPolicyConfig = DEFAULT_POLICY,
    cooldown_tickers: Optional[set[str]] = None,
    probation_tickers: Optional[set[str]] = None,
) -> BatchValidationResult:
    """Validate all order intents in a batch against guardrails.

    Each intent is checked individually, then batch-level checks run.
    Failed intents are blocked with recorded reasons.
    """
    cooldown_tickers = cooldown_tickers or set()
    probation_tickers = probation_tickers or set()

    result = BatchValidationResult()
    intents = batch.order_intents

    # Per-intent validation
    for intent in intents:
        gr = GuardrailResult(ticker=intent.ticker, passed=True)
        violations = []

        checks = [
            _check_no_trade_for_non_trading(intent),
            _check_no_duplicate_conflicting(intent, intents),
            _check_no_negative_target_weight(intent),
            _check_max_position_weight(intent, config),
            _check_reference_price_exists(intent),
            _check_not_blocked_recommendation(intent),
            _check_funded_pair_exists(intent, intents),
            _check_cooldown_probation(intent, cooldown_tickers, probation_tickers),
        ]

        for violation in checks:
            if violation is not None:
                violations.append(violation)

        if violations:
            gr.passed = False
            gr.violations = violations
            intent.is_blocked = True
            intent.block_reasons = violations
            intent.is_validated = False
            result.blocked_intents.append(intent)
            result.all_passed = False
        else:
            intent.is_validated = True
            intent.is_blocked = False
            result.approved_intents.append(intent)

        result.intent_results.append(gr)

    # Batch-level validation (only on approved intents)
    batch_checks = [
        _check_gross_exposure(result.approved_intents, current_weights, config),
        _check_turnover_cap(result.approved_intents, batch.portfolio_value, config),
    ]

    for violation in batch_checks:
        if violation is not None:
            result.batch_violations.append(violation)
            result.all_passed = False

    return result
