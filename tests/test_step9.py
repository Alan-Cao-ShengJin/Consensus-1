"""Tests for Step 9: execution wrapper, guardrails, and paper execution.

All tests are deterministic, no live broker, no DB required.
"""
from __future__ import annotations

import json
import os
import pytest
from datetime import date, datetime
from unittest.mock import patch

from models import ActionType
from portfolio_decision_engine import (
    TickerDecision, PortfolioReviewResult, ReasonCode,
    PRIORITY_FORCED_EXIT, PRIORITY_STRONG_EXIT, PRIORITY_DEFENSIVE,
    PRIORITY_GROWTH, PRIORITY_NEUTRAL,
)
from execution_wrapper import (
    OrderIntent, ExecutionBatch, OrderSide, NON_TRADING_ACTIONS,
    decision_to_order_intent, build_execution_batch,
)
from execution_policy import (
    ExecutionPolicyConfig, DEFAULT_POLICY,
    compute_target_weight, compute_notional_delta, compute_estimated_shares,
    compute_transaction_cost, validate_funded_pairing,
)
from execution_guardrails import (
    validate_execution_batch, BatchValidationResult,
)
from paper_execution_engine import (
    PaperPortfolio, PaperFill, PaperExecutionSummary,
    paper_execute, format_execution_text, export_execution_artifacts,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def make_decision(
    ticker: str,
    action: ActionType,
    score: float = 50.0,
    priority: int = PRIORITY_GROWTH,
    weight_change: float = None,
    suggested_weight: float = None,
    reason_codes: list = None,
    funded_by: str = None,
    stage: str = "recommendation",
) -> TickerDecision:
    return TickerDecision(
        ticker=ticker,
        action=action,
        action_score=score,
        recommendation_priority=priority,
        target_weight_change=weight_change,
        suggested_weight=suggested_weight,
        reason_codes=reason_codes or [ReasonCode.VALUATION_ATTRACTIVE],
        rationale=f"Test: {action.value} {ticker}",
        funded_by_ticker=funded_by,
        decision_stage=stage,
    )


def make_review(decisions: list[TickerDecision], review_date=None) -> PortfolioReviewResult:
    return PortfolioReviewResult(
        review_date=review_date or date(2025, 10, 1),
        decisions=decisions,
    )


# =========================================================================
# 1. Recommendations convert into correct order intents
# =========================================================================

class TestOrderIntentConversion:
    """Recommendations convert into correct order intents."""

    def test_initiate_produces_buy_intent(self):
        d = make_decision("AAPL", ActionType.INITIATE, weight_change=3.0, suggested_weight=3.0)
        oi = decision_to_order_intent(d, current_weight=0.0, portfolio_value=1_000_000, reference_price=150.0)
        assert oi is not None
        assert oi.side == OrderSide.BUY
        assert oi.action_type == ActionType.INITIATE
        assert oi.target_weight_after == 3.0
        assert oi.notional_delta == 30_000.0
        assert oi.estimated_shares is not None
        assert oi.estimated_shares > 0

    def test_add_produces_buy_intent(self):
        d = make_decision("MSFT", ActionType.ADD, weight_change=1.5, suggested_weight=6.5)
        oi = decision_to_order_intent(d, current_weight=5.0, portfolio_value=1_000_000, reference_price=300.0)
        assert oi is not None
        assert oi.side == OrderSide.BUY
        assert oi.action_type == ActionType.ADD
        assert oi.target_weight_after == 6.5

    def test_trim_produces_sell_intent(self):
        d = make_decision("GOOG", ActionType.TRIM, weight_change=-2.0, suggested_weight=4.0, priority=PRIORITY_DEFENSIVE)
        oi = decision_to_order_intent(d, current_weight=6.0, portfolio_value=1_000_000, reference_price=140.0)
        assert oi is not None
        assert oi.side == OrderSide.SELL
        assert oi.action_type == ActionType.TRIM
        assert oi.target_weight_after == 4.0
        assert oi.notional_delta < 0

    def test_exit_produces_sell_to_zero(self):
        d = make_decision("TSLA", ActionType.EXIT, weight_change=-5.0, suggested_weight=0.0, priority=PRIORITY_FORCED_EXIT)
        oi = decision_to_order_intent(d, current_weight=5.0, portfolio_value=1_000_000, reference_price=250.0)
        assert oi is not None
        assert oi.side == OrderSide.SELL
        assert oi.action_type == ActionType.EXIT
        assert oi.target_weight_after == 0.0

    def test_estimated_shares_computed_from_price(self):
        d = make_decision("AAPL", ActionType.INITIATE, weight_change=3.0, suggested_weight=3.0)
        oi = decision_to_order_intent(d, current_weight=0.0, portfolio_value=1_000_000, reference_price=150.0)
        # 3% of $1M = $30K, $30K / $150 = 200 shares
        assert abs(oi.estimated_shares - 200.0) < 0.01

    def test_no_reference_price_still_creates_intent(self):
        d = make_decision("AAPL", ActionType.INITIATE, weight_change=3.0, suggested_weight=3.0)
        oi = decision_to_order_intent(d, current_weight=0.0, portfolio_value=1_000_000, reference_price=None)
        assert oi is not None
        assert oi.estimated_shares is None
        assert oi.reference_price is None

    def test_funded_pairing_linked(self):
        d = make_decision("NEWCO", ActionType.INITIATE, weight_change=3.0, suggested_weight=3.0, funded_by="WEAK")
        oi = decision_to_order_intent(d, current_weight=0.0, portfolio_value=1_000_000, reference_price=85.0)
        assert oi is not None
        assert oi.linked_funding_ticker == "WEAK"


# =========================================================================
# 2. HOLD / PROBATION / NO_ACTION do not generate orders
# =========================================================================

class TestNonTradingActions:
    """HOLD / PROBATION / NO_ACTION do not generate order intents."""

    @pytest.mark.parametrize("action", [ActionType.HOLD, ActionType.PROBATION, ActionType.NO_ACTION])
    def test_non_trading_returns_none(self, action):
        d = make_decision("AAPL", action, priority=PRIORITY_NEUTRAL)
        oi = decision_to_order_intent(d, current_weight=5.0, portfolio_value=1_000_000, reference_price=150.0)
        assert oi is None

    def test_blocked_recommendation_returns_none(self):
        d = make_decision("AAPL", ActionType.INITIATE, stage="blocked")
        oi = decision_to_order_intent(d, current_weight=0.0, portfolio_value=1_000_000, reference_price=150.0)
        assert oi is None


# =========================================================================
# 3. Batch conversion skips non-trading and blocked
# =========================================================================

class TestBatchConversion:
    """build_execution_batch correctly splits trading vs non-trading."""

    def test_batch_separates_trading_and_non_trading(self):
        decisions = [
            make_decision("BUY1", ActionType.INITIATE, weight_change=3.0, suggested_weight=3.0),
            make_decision("HOLD1", ActionType.HOLD),
            make_decision("EXIT1", ActionType.EXIT, weight_change=-5.0, suggested_weight=0.0),
            make_decision("PROB1", ActionType.PROBATION),
            make_decision("BLKD", ActionType.INITIATE, stage="blocked"),
        ]
        review = make_review(decisions)
        batch = build_execution_batch(
            review, {"EXIT1": 5.0}, 1_000_000, {"BUY1": 100.0, "EXIT1": 200.0},
        )
        assert len(batch.order_intents) == 2  # BUY1 + EXIT1
        assert "HOLD1" in batch.skipped_non_trading
        assert "PROB1" in batch.skipped_non_trading
        assert "BLKD" in batch.skipped_blocked


# =========================================================================
# 4. Funded pairings generate coherent linked intents
# =========================================================================

class TestFundedPairings:
    """Funded pairings create coherent linked order intents."""

    def test_funded_initiation_links_to_funding_exit(self):
        decisions = [
            make_decision("WEAK", ActionType.EXIT, weight_change=-4.0, suggested_weight=0.0, priority=PRIORITY_STRONG_EXIT),
            make_decision("NEWCO", ActionType.INITIATE, weight_change=3.0, suggested_weight=3.0, funded_by="WEAK"),
        ]
        review = make_review(decisions)
        batch = build_execution_batch(
            review, {"WEAK": 4.0}, 1_000_000, {"WEAK": 50.0, "NEWCO": 85.0},
        )
        assert len(batch.order_intents) == 2
        newco_intent = next(oi for oi in batch.order_intents if oi.ticker == "NEWCO")
        assert newco_intent.linked_funding_ticker == "WEAK"

    def test_funded_pairing_validation_coherent(self):
        ok, msg = validate_funded_pairing("NEWCO", 30_000, "WEAK", -40_000)
        assert ok

    def test_funded_pairing_validation_imbalanced(self):
        ok, msg = validate_funded_pairing("NEWCO", 50_000, "WEAK", -10_000)
        assert not ok
        assert "imbalanced" in msg


# =========================================================================
# 5. Guardrails block invalid or conflicting orders
# =========================================================================

class TestGuardrails:
    """Guardrails block invalid or conflicting order intents."""

    def _make_batch_with_intents(self, intents: list[OrderIntent], pv=1_000_000) -> ExecutionBatch:
        return ExecutionBatch(
            review_date="2025-10-01",
            review_id=None,
            generated_at=datetime.utcnow(),
            order_intents=intents,
            portfolio_value=pv,
        )

    def test_negative_target_weight_blocked(self):
        oi = OrderIntent(
            ticker="BAD", side="sell", action_type=ActionType.TRIM,
            target_weight_before=2.0, target_weight_after=-1.0, current_weight=2.0,
            notional_delta=-30_000, reference_price=100.0,
        )
        batch = self._make_batch_with_intents([oi])
        result = validate_execution_batch(batch, {"BAD": 2.0})
        assert not result.all_passed
        assert len(result.blocked_intents) == 1
        assert any("Negative" in v for v in result.intent_results[0].violations)

    def test_exceeds_max_position_weight_blocked(self):
        oi = OrderIntent(
            ticker="BIG", side="buy", action_type=ActionType.ADD,
            target_weight_before=8.0, target_weight_after=15.0, current_weight=8.0,
            notional_delta=70_000, reference_price=100.0,
        )
        batch = self._make_batch_with_intents([oi])
        result = validate_execution_batch(batch, {"BIG": 8.0})
        assert not result.all_passed
        assert any("exceeds max" in v for v in result.intent_results[0].violations)

    def test_no_reference_price_blocked(self):
        oi = OrderIntent(
            ticker="NOPR", side="buy", action_type=ActionType.INITIATE,
            target_weight_before=0.0, target_weight_after=3.0, current_weight=0.0,
            notional_delta=30_000, reference_price=None,
        )
        batch = self._make_batch_with_intents([oi])
        result = validate_execution_batch(batch, {})
        assert not result.all_passed
        assert any("reference price" in v for v in result.intent_results[0].violations)

    def test_conflicting_orders_blocked(self):
        oi_buy = OrderIntent(
            ticker="CONF", side="buy", action_type=ActionType.ADD,
            target_weight_before=5.0, target_weight_after=7.0, current_weight=5.0,
            notional_delta=20_000, reference_price=100.0,
        )
        oi_sell = OrderIntent(
            ticker="CONF", side="sell", action_type=ActionType.TRIM,
            target_weight_before=5.0, target_weight_after=3.0, current_weight=5.0,
            notional_delta=-20_000, reference_price=100.0,
        )
        batch = self._make_batch_with_intents([oi_buy, oi_sell])
        result = validate_execution_batch(batch, {"CONF": 5.0})
        assert not result.all_passed
        # At least one should be flagged as conflicting
        all_violations = [v for gr in result.intent_results for v in gr.violations]
        assert any("Conflicting" in v for v in all_violations)

    def test_cooldown_blocks_buy(self):
        oi = OrderIntent(
            ticker="COOL", side="buy", action_type=ActionType.INITIATE,
            target_weight_before=0.0, target_weight_after=3.0, current_weight=0.0,
            notional_delta=30_000, reference_price=100.0,
        )
        batch = self._make_batch_with_intents([oi])
        result = validate_execution_batch(batch, {}, cooldown_tickers={"COOL"})
        assert not result.all_passed
        assert any("cooldown" in v for v in result.intent_results[0].violations)

    def test_probation_blocks_add(self):
        oi = OrderIntent(
            ticker="PROB", side="buy", action_type=ActionType.ADD,
            target_weight_before=3.0, target_weight_after=4.5, current_weight=3.0,
            notional_delta=15_000, reference_price=100.0,
        )
        batch = self._make_batch_with_intents([oi])
        result = validate_execution_batch(batch, {"PROB": 3.0}, probation_tickers={"PROB"})
        assert not result.all_passed
        assert any("probation" in v for v in result.intent_results[0].violations)

    def test_valid_intent_passes(self):
        oi = OrderIntent(
            ticker="GOOD", side="buy", action_type=ActionType.INITIATE,
            target_weight_before=0.0, target_weight_after=3.0, current_weight=0.0,
            notional_delta=30_000, reference_price=100.0,
        )
        batch = self._make_batch_with_intents([oi])
        result = validate_execution_batch(batch, {})
        assert result.all_passed
        assert len(result.approved_intents) == 1
        assert oi.is_validated

    def test_funded_pair_missing_sell_blocked(self):
        oi = OrderIntent(
            ticker="NEWCO", side="buy", action_type=ActionType.INITIATE,
            target_weight_before=0.0, target_weight_after=3.0, current_weight=0.0,
            notional_delta=30_000, reference_price=100.0,
            linked_funding_ticker="WEAK",
        )
        batch = self._make_batch_with_intents([oi])
        result = validate_execution_batch(batch, {})
        assert not result.all_passed
        assert any("no sell order" in v for v in result.intent_results[0].violations)

    def test_gross_exposure_violation(self):
        # Create intents that would exceed 100% exposure
        intents = []
        for i in range(12):
            intents.append(OrderIntent(
                ticker=f"T{i}", side="buy", action_type=ActionType.INITIATE,
                target_weight_before=0.0, target_weight_after=9.0, current_weight=0.0,
                notional_delta=90_000, reference_price=100.0,
            ))
        batch = self._make_batch_with_intents(intents)
        result = validate_execution_batch(batch, {})
        # Batch-level check should catch this
        assert len(result.batch_violations) > 0
        assert any("gross exposure" in v for v in result.batch_violations)

    def test_turnover_cap_violation(self):
        config = ExecutionPolicyConfig(max_weekly_turnover_pct=5.0)
        oi = OrderIntent(
            ticker="BIG", side="buy", action_type=ActionType.INITIATE,
            target_weight_before=0.0, target_weight_after=8.0, current_weight=0.0,
            notional_delta=80_000, reference_price=100.0,
        )
        batch = self._make_batch_with_intents([oi])
        result = validate_execution_batch(batch, {}, config=config)
        assert any("turnover" in v.lower() for v in result.batch_violations)


# =========================================================================
# 6. Blocked recommendations do not produce executable intents
# =========================================================================

class TestBlockedRecommendations:
    """Blocked recommendations must not produce executable intents."""

    def test_blocked_stage_skipped_in_batch(self):
        decisions = [
            make_decision("BLKD", ActionType.INITIATE, weight_change=3.0, suggested_weight=3.0, stage="blocked"),
            make_decision("OK", ActionType.INITIATE, weight_change=3.0, suggested_weight=3.0),
        ]
        review = make_review(decisions)
        batch = build_execution_batch(review, {}, 1_000_000, {"OK": 100.0, "BLKD": 100.0})
        assert len(batch.order_intents) == 1
        assert batch.order_intents[0].ticker == "OK"
        assert "BLKD" in batch.skipped_blocked


# =========================================================================
# 7. Paper fills update only paper portfolio state
# =========================================================================

class TestPaperExecution:
    """Paper execution updates only paper portfolio, not live state."""

    def test_paper_buy_creates_position(self):
        pp = PaperPortfolio(initial_cash=100_000)
        fill = pp.execute_buy("AAPL", 100, 150.0, "initiate", date(2025, 10, 1))
        assert fill is not None
        assert "AAPL" in pp.positions
        assert pp.positions["AAPL"].shares == 100
        assert pp.cash < 100_000

    def test_paper_sell_removes_position(self):
        pp = PaperPortfolio(initial_cash=100_000)
        pp.execute_buy("AAPL", 100, 150.0, "initiate", date(2025, 10, 1))
        fill = pp.execute_sell("AAPL", 100, 155.0, "exit", date(2025, 10, 8))
        assert fill is not None
        assert "AAPL" not in pp.positions

    def test_paper_sell_partial(self):
        pp = PaperPortfolio(initial_cash=100_000)
        pp.execute_buy("AAPL", 100, 150.0, "initiate", date(2025, 10, 1))
        fill = pp.execute_sell("AAPL", 50, 155.0, "trim", date(2025, 10, 8))
        assert fill is not None
        assert pp.positions["AAPL"].shares == 50

    def test_paper_portfolio_tracks_realized_pnl(self):
        pp = PaperPortfolio(initial_cash=100_000)
        pp.execute_buy("AAPL", 100, 150.0, "initiate", date(2025, 10, 1))
        pp.execute_sell("AAPL", 100, 160.0, "exit", date(2025, 10, 8))
        # PnL = (160 - 150) * 100 = 1000
        assert abs(pp.realized_pnl - 1000.0) < 0.01

    def test_paper_execute_sells_first_buys_second(self):
        pp = PaperPortfolio(initial_cash=50_000)
        # Pre-seed a position
        pp.execute_buy("WEAK", 100, 50.0, "seed", date(2025, 9, 1))

        sell_intent = OrderIntent(
            ticker="WEAK", side="sell", action_type=ActionType.EXIT,
            target_weight_before=10.0, target_weight_after=0.0, current_weight=10.0,
            notional_delta=-5_000, estimated_shares=-100.0, reference_price=50.0,
        )
        buy_intent = OrderIntent(
            ticker="NEWCO", side="buy", action_type=ActionType.INITIATE,
            target_weight_before=0.0, target_weight_after=3.0, current_weight=0.0,
            notional_delta=1_500, estimated_shares=15.0, reference_price=100.0,
        )

        summary = paper_execute(
            portfolio=pp,
            approved_intents=[buy_intent, sell_intent],
            blocked_intents=[],
            execution_date=date(2025, 10, 1),
            fill_prices={"WEAK": 50.0, "NEWCO": 100.0},
        )

        assert summary.fills_executed == 2
        # Sell should have happened first
        assert summary.fills[0].side == "sell"
        assert summary.fills[1].side == "buy"
        assert "WEAK" not in pp.positions
        assert "NEWCO" in pp.positions


# =========================================================================
# 8. Generating intents does not mutate live portfolio state
# =========================================================================

class TestNoLiveStateMutation:
    """Generating order intents must not mutate live portfolio state."""

    def test_build_batch_is_pure(self):
        """build_execution_batch has no side effects on input data."""
        decisions = [
            make_decision("AAPL", ActionType.INITIATE, weight_change=3.0, suggested_weight=3.0),
            make_decision("MSFT", ActionType.HOLD),
        ]
        review = make_review(decisions)
        weights_before = {"AAPL": 0.0, "MSFT": 5.0}
        weights_copy = dict(weights_before)

        batch = build_execution_batch(review, weights_before, 1_000_000, {"AAPL": 150.0})

        # Input weights unchanged
        assert weights_before == weights_copy
        # Review decisions unchanged
        assert len(review.decisions) == 2
        assert review.decisions[0].action == ActionType.INITIATE

    def test_guardrail_validation_does_not_mutate_portfolio_value(self):
        """Guardrail validation only marks intents, doesn't change portfolio."""
        oi = OrderIntent(
            ticker="AAPL", side="buy", action_type=ActionType.INITIATE,
            target_weight_before=0.0, target_weight_after=3.0, current_weight=0.0,
            notional_delta=30_000, reference_price=150.0,
        )
        batch = ExecutionBatch(
            review_date="2025-10-01", review_id=None,
            generated_at=datetime.utcnow(), order_intents=[oi],
            portfolio_value=1_000_000,
        )
        result = validate_execution_batch(batch, {})
        # Batch portfolio value unchanged
        assert batch.portfolio_value == 1_000_000


# =========================================================================
# 9. Transaction cost applied correctly in paper mode
# =========================================================================

class TestTransactionCost:
    """Transaction costs are applied correctly in paper execution."""

    def test_buy_deducts_cost(self):
        pp = PaperPortfolio(initial_cash=100_000, transaction_cost_bps=10.0)
        fill = pp.execute_buy("AAPL", 100, 150.0, "initiate", date(2025, 10, 1))
        # Notional = 100 * 150 = 15,000. Cost = 15,000 * 10/10000 = 15.
        assert fill.transaction_cost == 15.0
        assert pp.cash == 100_000 - 15_000 - 15.0

    def test_sell_deducts_cost(self):
        pp = PaperPortfolio(initial_cash=100_000, transaction_cost_bps=10.0)
        pp.execute_buy("AAPL", 100, 150.0, "initiate", date(2025, 10, 1))
        cash_after_buy = pp.cash
        fill = pp.execute_sell("AAPL", 100, 160.0, "exit", date(2025, 10, 8))
        # Sell notional = 100 * 160 = 16,000. Cost = 16,000 * 10/10000 = 16.
        assert fill.transaction_cost == 16.0
        assert pp.cash == cash_after_buy + 16_000 - 16.0

    def test_compute_transaction_cost_function(self):
        assert compute_transaction_cost(10_000, 10.0) == 10.0
        assert compute_transaction_cost(10_000, 50.0) == 50.0
        assert compute_transaction_cost(0, 10.0) == 0.0


# =========================================================================
# 10. Execution summaries reconcile with intents and fills
# =========================================================================

class TestExecutionSummary:
    """Execution summaries are consistent with intents and fills."""

    def test_summary_counts_match(self):
        pp = PaperPortfolio(initial_cash=100_000)
        pp.execute_buy("WEAK", 50, 40.0, "seed", date(2025, 9, 1))

        sell_intent = OrderIntent(
            ticker="WEAK", side="sell", action_type=ActionType.EXIT,
            target_weight_before=2.0, target_weight_after=0.0, current_weight=2.0,
            notional_delta=-2_000, estimated_shares=-50.0, reference_price=40.0,
        )
        buy_intent = OrderIntent(
            ticker="NEWCO", side="buy", action_type=ActionType.INITIATE,
            target_weight_before=0.0, target_weight_after=3.0, current_weight=0.0,
            notional_delta=3_000, estimated_shares=30.0, reference_price=100.0,
        )
        blocked = OrderIntent(
            ticker="BLKD", side="buy", action_type=ActionType.INITIATE,
            target_weight_before=0.0, target_weight_after=3.0, current_weight=0.0,
            notional_delta=3_000, reference_price=None,
            is_blocked=True, block_reasons=["No reference price"],
        )

        summary = paper_execute(
            portfolio=pp,
            approved_intents=[sell_intent, buy_intent],
            blocked_intents=[blocked],
            execution_date=date(2025, 10, 1),
            fill_prices={"WEAK": 40.0, "NEWCO": 100.0},
        )

        assert summary.intents_received == 3  # 2 approved + 1 blocked
        assert summary.intents_approved == 2
        assert summary.intents_blocked == 1
        assert summary.fills_executed == 2
        assert summary.total_sell_notional > 0
        assert summary.total_buy_notional > 0
        assert summary.portfolio_snapshot is not None

    def test_summary_serializes_to_dict(self):
        pp = PaperPortfolio(initial_cash=100_000)
        summary = paper_execute(
            portfolio=pp, approved_intents=[], blocked_intents=[],
            execution_date=date(2025, 10, 1), fill_prices={},
        )
        d = summary.to_dict()
        assert "execution_date" in d
        assert "fills" in d
        assert d["fills_executed"] == 0


# =========================================================================
# 11. Execution policy sizing rules
# =========================================================================

class TestExecutionPolicy:
    """Execution policy computes correct target weights."""

    def test_exit_always_zero(self):
        assert compute_target_weight(ActionType.EXIT, 5.0, None, None) == 0.0

    def test_hold_unchanged(self):
        assert compute_target_weight(ActionType.HOLD, 5.0, None, None) == 5.0

    def test_initiate_uses_suggested(self):
        assert compute_target_weight(ActionType.INITIATE, 0.0, 4.0, 3.0) == 4.0

    def test_initiate_clamps_to_max(self):
        config = ExecutionPolicyConfig(max_single_position_weight_pct=5.0, max_initiation_weight_pct=5.0)
        assert compute_target_weight(ActionType.INITIATE, 0.0, 12.0, None, config) == 5.0

    def test_add_respects_max(self):
        config = ExecutionPolicyConfig(max_single_position_weight_pct=10.0)
        assert compute_target_weight(ActionType.ADD, 9.0, None, 3.0, config) == 10.0

    def test_trim_respects_floor(self):
        config = ExecutionPolicyConfig(trim_floor_weight_pct=1.0)
        assert compute_target_weight(ActionType.TRIM, 2.0, None, -3.0, config) == 1.0

    def test_notional_delta_calculation(self):
        assert compute_notional_delta(5.0, 8.0, 1_000_000) == 30_000.0
        assert compute_notional_delta(5.0, 3.0, 1_000_000) == -20_000.0

    def test_estimated_shares_calculation(self):
        assert compute_estimated_shares(30_000, 150.0) == 200.0
        assert compute_estimated_shares(-20_000, 100.0) == -200.0
        assert compute_estimated_shares(30_000, None) is None
        assert compute_estimated_shares(30_000, 0) is None


# =========================================================================
# 12. Paper portfolio snapshot
# =========================================================================

class TestPaperPortfolioSnapshot:
    """Paper portfolio snapshots capture correct state."""

    def test_snapshot_after_trades(self):
        pp = PaperPortfolio(initial_cash=100_000)
        pp.execute_buy("AAPL", 100, 150.0, "initiate", date(2025, 10, 1))
        snap = pp.take_snapshot(date(2025, 10, 1), {"AAPL": 155.0})
        assert snap.num_positions == 1
        assert "AAPL" in snap.positions
        assert snap.total_value > 100_000  # price went up
        assert snap.cash < 100_000

    def test_snapshot_to_dict(self):
        pp = PaperPortfolio(initial_cash=100_000)
        snap = pp.take_snapshot(date(2025, 10, 1), {})
        d = snap.to_dict()
        assert d["total_value"] == 100_000
        assert d["num_positions"] == 0


# =========================================================================
# 13. File export
# =========================================================================

class TestFileExport:
    """Execution artifacts export to JSON files."""

    def test_export_creates_files(self, tmp_path):
        pp = PaperPortfolio(initial_cash=100_000)
        summary = paper_execute(
            portfolio=pp, approved_intents=[], blocked_intents=[],
            execution_date=date(2025, 10, 1), fill_prices={},
        )
        batch = ExecutionBatch(
            review_date="2025-10-01", review_id=None,
            generated_at=datetime.utcnow(), order_intents=[],
            portfolio_value=100_000,
        )
        out_dir = str(tmp_path / "test_output")
        export_execution_artifacts(summary, batch, output_dir=out_dir)

        assert os.path.exists(os.path.join(out_dir, "2025-10-01_order_intents.json"))
        assert os.path.exists(os.path.join(out_dir, "2025-10-01_paper_fills.json"))
        assert os.path.exists(os.path.join(out_dir, "2025-10-01_execution_summary.json"))
        assert os.path.exists(os.path.join(out_dir, "2025-10-01_portfolio_snapshot.json"))


# =========================================================================
# 14. Format text output
# =========================================================================

class TestFormatText:
    """Text formatting produces readable output."""

    def test_format_includes_key_sections(self):
        pp = PaperPortfolio(initial_cash=100_000)
        pp.execute_buy("AAPL", 100, 150.0, "initiate", date(2025, 10, 1))
        summary = paper_execute(
            portfolio=pp, approved_intents=[], blocked_intents=[],
            execution_date=date(2025, 10, 1), fill_prices={"AAPL": 150.0},
        )
        text = format_execution_text(summary)
        assert "PAPER EXECUTION SUMMARY" in text
        assert "PORTFOLIO AFTER EXECUTION" in text


# =========================================================================
# 15. End-to-end pipeline: review -> intents -> validate -> paper-execute
# =========================================================================

class TestEndToEnd:
    """Full pipeline from review to paper execution."""

    def test_full_pipeline(self):
        # Build review
        decisions = [
            make_decision("EXIT1", ActionType.EXIT, weight_change=-5.0, suggested_weight=0.0, priority=PRIORITY_FORCED_EXIT),
            make_decision("TRIM1", ActionType.TRIM, weight_change=-2.0, suggested_weight=4.0, priority=PRIORITY_DEFENSIVE),
            make_decision("ADD1", ActionType.ADD, weight_change=1.5, suggested_weight=6.5),
            make_decision("INIT1", ActionType.INITIATE, weight_change=3.0, suggested_weight=3.0),
            make_decision("HOLD1", ActionType.HOLD, priority=PRIORITY_NEUTRAL),
        ]
        review = make_review(decisions)
        weights = {"EXIT1": 5.0, "TRIM1": 6.0, "ADD1": 5.0}
        prices = {"EXIT1": 50.0, "TRIM1": 120.0, "ADD1": 200.0, "INIT1": 85.0}

        # Step 1: Build batch
        batch = build_execution_batch(review, weights, 1_000_000, prices)
        assert len(batch.order_intents) == 4  # EXIT, TRIM, ADD, INIT
        assert "HOLD1" in batch.skipped_non_trading

        # Step 2: Validate
        validation = validate_execution_batch(batch, weights)
        assert validation.all_passed
        assert len(validation.approved_intents) == 4

        # Step 3: Paper execute
        pp = PaperPortfolio(initial_cash=1_000_000)
        # Seed existing positions
        for ticker, weight in weights.items():
            notional = (weight / 100.0) * 1_000_000
            pp.execute_buy(ticker, notional / prices[ticker], prices[ticker], "seed", date(2025, 9, 1))
        pp.cash = 1_000_000 - sum((w / 100.0) * 1_000_000 for w in weights.values())

        summary = paper_execute(
            portfolio=pp,
            approved_intents=validation.approved_intents,
            blocked_intents=validation.blocked_intents,
            execution_date=date(2025, 10, 1),
            fill_prices=prices,
        )

        assert summary.fills_executed == 4
        assert "EXIT1" not in pp.positions  # exited
        assert "INIT1" in pp.positions       # initiated
        assert summary.portfolio_snapshot is not None
        assert summary.total_transaction_cost > 0
