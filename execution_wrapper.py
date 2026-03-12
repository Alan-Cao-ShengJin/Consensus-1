"""Execution wrapper: convert portfolio review recommendations into explicit order intents.

This is the boundary between recommendation and execution. Recommendations are
advisory; order intents are structured, validated instructions that can be
paper-executed or (in a future step) sent to a real broker.

Key principle: generating order intents does NOT mutate any live portfolio state.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from models import ActionType
from portfolio_decision_engine import (
    TickerDecision, PortfolioReviewResult, ReasonCode,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Order intent side
# ---------------------------------------------------------------------------

class OrderSide:
    BUY = "buy"
    SELL = "sell"


# ---------------------------------------------------------------------------
# Non-trading actions (no order intent generated)
# ---------------------------------------------------------------------------

NON_TRADING_ACTIONS = frozenset({
    ActionType.HOLD,
    ActionType.PROBATION,
    ActionType.NO_ACTION,
})


# ---------------------------------------------------------------------------
# Order intent
# ---------------------------------------------------------------------------

@dataclass
class OrderIntent:
    """A structured, auditable instruction derived from a recommendation.

    This is NOT an execution record. It describes what SHOULD happen if
    validated and approved. Paper or live execution consumes these.
    """
    ticker: str
    side: str                                  # buy / sell
    action_type: ActionType                    # INITIATE / ADD / TRIM / EXIT
    target_weight_before: float                # current weight %
    target_weight_after: float                 # desired weight % after execution
    current_weight: float                      # same as target_weight_before
    notional_delta: float                      # estimated $ change (positive=buy)
    estimated_shares: Optional[float] = None   # if reference price available
    reference_price: Optional[float] = None    # price used for estimation
    reason_codes: list[str] = field(default_factory=list)
    linked_funding_ticker: Optional[str] = None
    generated_at: datetime = field(default_factory=datetime.utcnow)
    review_date: Optional[str] = None          # ISO date of source review
    review_id: Optional[int] = None
    dry_run: bool = False
    paper_trade: bool = True
    # Validation state (set by guardrails)
    is_validated: bool = False
    is_blocked: bool = False
    block_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "side": self.side,
            "action_type": self.action_type.value,
            "target_weight_before": round(self.target_weight_before, 4),
            "target_weight_after": round(self.target_weight_after, 4),
            "current_weight": round(self.current_weight, 4),
            "notional_delta": round(self.notional_delta, 2),
            "estimated_shares": round(self.estimated_shares, 4) if self.estimated_shares else None,
            "reference_price": round(self.reference_price, 4) if self.reference_price else None,
            "reason_codes": self.reason_codes,
            "linked_funding_ticker": self.linked_funding_ticker,
            "generated_at": self.generated_at.isoformat(),
            "review_date": self.review_date,
            "review_id": self.review_id,
            "dry_run": self.dry_run,
            "paper_trade": self.paper_trade,
            "is_validated": self.is_validated,
            "is_blocked": self.is_blocked,
            "block_reasons": self.block_reasons,
        }


# ---------------------------------------------------------------------------
# Conversion: TickerDecision -> OrderIntent
# ---------------------------------------------------------------------------

def decision_to_order_intent(
    decision: TickerDecision,
    current_weight: float,
    portfolio_value: float,
    reference_price: Optional[float] = None,
    review_date: Optional[str] = None,
    review_id: Optional[int] = None,
    dry_run: bool = False,
    paper_trade: bool = True,
) -> Optional[OrderIntent]:
    """Convert a single TickerDecision into an OrderIntent.

    Returns None for non-trading actions (HOLD, PROBATION, NO_ACTION)
    and for blocked recommendations.
    """
    if decision.action in NON_TRADING_ACTIONS:
        return None

    if decision.decision_stage == "blocked":
        return None

    # Determine side
    if decision.action in (ActionType.INITIATE, ActionType.ADD):
        side = OrderSide.BUY
    elif decision.action in (ActionType.TRIM, ActionType.EXIT):
        side = OrderSide.SELL
    else:
        return None

    # Compute target weight after
    if decision.action == ActionType.EXIT:
        target_weight_after = 0.0
    elif decision.suggested_weight is not None:
        target_weight_after = decision.suggested_weight
    elif decision.target_weight_change is not None:
        target_weight_after = current_weight + decision.target_weight_change
    else:
        target_weight_after = current_weight

    # Compute notional delta
    weight_delta = target_weight_after - current_weight
    notional_delta = (weight_delta / 100.0) * portfolio_value

    # Estimate shares if price available
    estimated_shares = None
    if reference_price and reference_price > 0:
        estimated_shares = abs(notional_delta) / reference_price
        if side == OrderSide.SELL:
            estimated_shares = -estimated_shares

    return OrderIntent(
        ticker=decision.ticker,
        side=side,
        action_type=decision.action,
        target_weight_before=current_weight,
        target_weight_after=target_weight_after,
        current_weight=current_weight,
        notional_delta=notional_delta,
        estimated_shares=estimated_shares,
        reference_price=reference_price,
        reason_codes=[r.value if isinstance(r, ReasonCode) else str(r) for r in decision.reason_codes],
        linked_funding_ticker=decision.funded_by_ticker,
        generated_at=decision.generated_at,
        review_date=review_date,
        review_id=review_id,
        dry_run=dry_run,
        paper_trade=paper_trade,
    )


# ---------------------------------------------------------------------------
# Batch conversion: PortfolioReviewResult -> list of OrderIntents
# ---------------------------------------------------------------------------

@dataclass
class ExecutionBatch:
    """A batch of order intents from one review cycle."""
    review_date: str
    review_id: Optional[int]
    generated_at: datetime
    order_intents: list[OrderIntent] = field(default_factory=list)
    skipped_non_trading: list[str] = field(default_factory=list)  # tickers skipped
    skipped_blocked: list[str] = field(default_factory=list)
    portfolio_value: float = 0.0
    dry_run: bool = False
    paper_trade: bool = True

    def to_dict(self) -> dict:
        return {
            "review_date": self.review_date,
            "review_id": self.review_id,
            "generated_at": self.generated_at.isoformat(),
            "portfolio_value": round(self.portfolio_value, 2),
            "dry_run": self.dry_run,
            "paper_trade": self.paper_trade,
            "order_intent_count": len(self.order_intents),
            "skipped_non_trading": self.skipped_non_trading,
            "skipped_blocked": self.skipped_blocked,
            "order_intents": [oi.to_dict() for oi in self.order_intents],
        }


def build_execution_batch(
    review_result: PortfolioReviewResult,
    current_weights: dict[str, float],
    portfolio_value: float,
    reference_prices: dict[str, float],
    review_id: Optional[int] = None,
    dry_run: bool = False,
    paper_trade: bool = True,
) -> ExecutionBatch:
    """Convert a full review result into an execution batch of order intents.

    Args:
        review_result: Output of the decision engine.
        current_weights: {ticker: weight_%} for all current holdings.
        portfolio_value: Total portfolio value in $.
        reference_prices: {ticker: price} for share estimation.
        review_id: Optional DB review ID for audit linkage.
        dry_run: If True, intents are informational only.
        paper_trade: If True, intents target paper execution.
    """
    review_date_str = review_result.review_date.isoformat()
    batch = ExecutionBatch(
        review_date=review_date_str,
        review_id=review_id,
        generated_at=datetime.utcnow(),
        portfolio_value=portfolio_value,
        dry_run=dry_run,
        paper_trade=paper_trade,
    )

    for decision in review_result.decisions:
        if decision.action in NON_TRADING_ACTIONS:
            batch.skipped_non_trading.append(decision.ticker)
            continue

        if decision.decision_stage == "blocked":
            batch.skipped_blocked.append(decision.ticker)
            continue

        weight = current_weights.get(decision.ticker, 0.0)
        price = reference_prices.get(decision.ticker)

        intent = decision_to_order_intent(
            decision=decision,
            current_weight=weight,
            portfolio_value=portfolio_value,
            reference_price=price,
            review_date=review_date_str,
            review_id=review_id,
            dry_run=dry_run,
            paper_trade=paper_trade,
        )
        if intent is not None:
            batch.order_intents.append(intent)

    return batch
