"""Tests for price momentum guards.

Tests cover:
  1. Pure computation functions (SMA, drawdown, regime)
  2. Integration with decision engine (guard blocking logic)
  3. Backward compatibility (disabled config = no change)
"""
import pytest
from datetime import date, timedelta

from price_momentum import (
    compute_sma,
    is_above_sma,
    compute_drawdown_from_cost,
    compute_drawdown_from_peak,
    compute_distance_from_high,
    compute_market_regime,
    compute_holding_signals,
    compute_candidate_signals,
    MomentumGuardConfig,
    MomentumSignals,
    DISABLED_MOMENTUM_CONFIG,
    ENABLED_MOMENTUM_CONFIG,
)
from portfolio_decision_engine import (
    evaluate_holding,
    evaluate_candidate,
    HoldingSnapshot,
    CandidateSnapshot,
    DecisionInput,
    run_decision_engine,
    ReasonCode,
    DISABLED_MOMENTUM_CONFIG as ENGINE_DISABLED,
)
from models import ActionType, ThesisState, ZoneState


# ---------------------------------------------------------------------------
# Helper: generate price series
# ---------------------------------------------------------------------------

def _make_prices(
    start: date,
    values: list[float],
) -> list[tuple[date, float]]:
    """Create a price series from start date with given values."""
    return [(start + timedelta(days=i), v) for i, v in enumerate(values)]


# ---------------------------------------------------------------------------
# Pure function tests
# ---------------------------------------------------------------------------

class TestComputeSMA:
    def test_basic_sma(self):
        prices = _make_prices(date(2024, 1, 1), [10, 20, 30, 40, 50])
        sma = compute_sma(prices, date(2024, 1, 5), period=3)
        assert sma == pytest.approx(40.0)  # (30+40+50)/3

    def test_insufficient_data(self):
        prices = _make_prices(date(2024, 1, 1), [10, 20])
        assert compute_sma(prices, date(2024, 1, 2), period=5) is None

    def test_as_of_filter(self):
        prices = _make_prices(date(2024, 1, 1), [10, 20, 30, 40, 50])
        # Only first 3 prices visible
        sma = compute_sma(prices, date(2024, 1, 3), period=3)
        assert sma == pytest.approx(20.0)  # (10+20+30)/3

    def test_empty_prices(self):
        assert compute_sma([], date(2024, 1, 1), period=5) is None


class TestIsAboveSMA:
    def test_above(self):
        # Last price 50, SMA of last 3 = (30+40+50)/3 = 40
        prices = _make_prices(date(2024, 1, 1), [10, 20, 30, 40, 50])
        assert is_above_sma(prices, date(2024, 1, 5), period=3) is True

    def test_below(self):
        # Last price 10, SMA of last 3 = (30+20+10)/3 = 20
        prices = _make_prices(date(2024, 1, 1), [50, 40, 30, 20, 10])
        assert is_above_sma(prices, date(2024, 1, 5), period=3) is False

    def test_insufficient_data(self):
        prices = _make_prices(date(2024, 1, 1), [10])
        assert is_above_sma(prices, date(2024, 1, 1), period=5) is None


class TestDrawdownFromCost:
    def test_underwater(self):
        dd = compute_drawdown_from_cost(85.0, 100.0)
        assert dd == pytest.approx(-15.0)

    def test_above_cost(self):
        dd = compute_drawdown_from_cost(110.0, 100.0)
        assert dd == pytest.approx(10.0)

    def test_no_price(self):
        assert compute_drawdown_from_cost(None, 100.0) is None

    def test_zero_cost(self):
        assert compute_drawdown_from_cost(50.0, 0.0) is None


class TestDrawdownFromPeak:
    def test_basic_drawdown(self):
        # Peak at 100, current at 80 = -20%
        prices = _make_prices(date(2024, 1, 1), [80, 90, 100, 95, 80])
        dd = compute_drawdown_from_peak(prices, date(2024, 1, 5), lookback_days=10)
        assert dd == pytest.approx(-20.0)

    def test_at_peak(self):
        prices = _make_prices(date(2024, 1, 1), [80, 90, 100])
        dd = compute_drawdown_from_peak(prices, date(2024, 1, 3), lookback_days=10)
        assert dd == pytest.approx(0.0)

    def test_lookback_window(self):
        # Peak of 200 is outside 3-day window; within window peak is 100
        prices = _make_prices(date(2024, 1, 1), [200, 90, 100, 95, 80])
        dd = compute_drawdown_from_peak(prices, date(2024, 1, 5), lookback_days=3)
        # Window: days 3,4,5 = [100, 95, 80], peak=100, current=80
        assert dd == pytest.approx(-20.0)

    def test_empty(self):
        assert compute_drawdown_from_peak([], date(2024, 1, 1), lookback_days=10) is None


class TestMarketRegime:
    def test_bullish(self):
        # Ascending prices, last > SMA
        prices = _make_prices(date(2024, 1, 1), list(range(1, 60)))
        assert compute_market_regime(prices, date(2024, 2, 28), sma_period=50) is True

    def test_bearish(self):
        # Descending prices, last < SMA
        prices = _make_prices(date(2024, 1, 1), list(range(60, 0, -1)))
        assert compute_market_regime(prices, date(2024, 2, 28), sma_period=50) is False


# ---------------------------------------------------------------------------
# Holding signals aggregation
# ---------------------------------------------------------------------------

class TestComputeHoldingSignals:
    def test_disabled_config_returns_empty(self):
        signals = compute_holding_signals(
            [], date(2024, 1, 1), 100.0, 100.0, DISABLED_MOMENTUM_CONFIG,
        )
        assert signals.price_above_sma is None
        assert signals.drawdown_from_cost_pct is None

    def test_enabled_computes_all(self):
        prices = _make_prices(date(2024, 1, 1), list(range(80, 110)))
        signals = compute_holding_signals(
            prices, date(2024, 1, 30), 109.0, 100.0, ENABLED_MOMENTUM_CONFIG,
        )
        assert signals.price_above_sma is not None
        assert signals.drawdown_from_cost_pct is not None
        assert signals.drawdown_from_peak_pct is not None


# ---------------------------------------------------------------------------
# Decision engine integration tests
# ---------------------------------------------------------------------------

def _make_holding(
    ticker: str = "TEST",
    conviction: float = 60.0,
    avg_cost: float = 100.0,
    current_price: float = 100.0,
    current_weight: float = 5.0,
    thesis_state: ThesisState = ThesisState.STABLE,
    zone: ZoneState = ZoneState.BUY,
    momentum: MomentumSignals = None,
    valuation_gap_pct: float = 15.0,  # default to BUY zone (>= 10%)
) -> HoldingSnapshot:
    return HoldingSnapshot(
        ticker=ticker,
        position_id=1,
        thesis_id=1,
        thesis_state=thesis_state,
        conviction_score=conviction,
        current_weight=current_weight,
        target_weight=current_weight,
        avg_cost=avg_cost,
        current_price=current_price,
        valuation_gap_pct=valuation_gap_pct,
        zone_state=zone,
        momentum=momentum or MomentumSignals(),
    )


class TestStopLossGuard:
    def test_stop_loss_trim(self):
        """Position 20% underwater triggers TRIM."""
        momentum = MomentumSignals(drawdown_from_cost_pct=-21.0)
        holding = _make_holding(momentum=momentum, current_price=79.0)
        decision = evaluate_holding(
            holding, date(2024, 6, 1), momentum_config=ENABLED_MOMENTUM_CONFIG,
        )
        assert decision.action == ActionType.TRIM
        assert ReasonCode.STOP_LOSS_TRIGGERED in decision.reason_codes

    def test_stop_loss_exit(self):
        """Position 35% underwater triggers EXIT."""
        momentum = MomentumSignals(drawdown_from_cost_pct=-36.0)
        holding = _make_holding(momentum=momentum, current_price=64.0)
        decision = evaluate_holding(
            holding, date(2024, 6, 1), momentum_config=ENABLED_MOMENTUM_CONFIG,
        )
        assert decision.action == ActionType.EXIT
        assert ReasonCode.STOP_LOSS_TRIGGERED in decision.reason_codes

    def test_no_stop_loss_when_disabled(self):
        """Disabled config doesn't trigger stop-loss."""
        momentum = MomentumSignals(drawdown_from_cost_pct=-40.0)
        holding = _make_holding(momentum=momentum, current_price=60.0)
        decision = evaluate_holding(
            holding, date(2024, 6, 1), momentum_config=DISABLED_MOMENTUM_CONFIG,
        )
        # Without momentum guards, this holding would ADD (BUY zone, good conviction)
        assert decision.action != ActionType.EXIT or ReasonCode.STOP_LOSS_TRIGGERED not in decision.reason_codes


class TestTrailingStopGuard:
    def test_trailing_stop_exit(self):
        """25% below 90-day peak triggers EXIT."""
        momentum = MomentumSignals(drawdown_from_peak_pct=-26.0, peak_price=135.0)
        holding = _make_holding(momentum=momentum, current_price=100.0, avg_cost=90.0)
        decision = evaluate_holding(
            holding, date(2024, 6, 1), momentum_config=ENABLED_MOMENTUM_CONFIG,
        )
        assert decision.action == ActionType.EXIT
        assert ReasonCode.TRAILING_STOP_TRIGGERED in decision.reason_codes

    def test_no_trailing_stop_above_threshold(self):
        """15% below peak does NOT trigger trailing stop (threshold is -25%)."""
        momentum = MomentumSignals(drawdown_from_peak_pct=-15.0, peak_price=118.0)
        holding = _make_holding(momentum=momentum, current_price=100.0, avg_cost=90.0)
        decision = evaluate_holding(
            holding, date(2024, 6, 1), momentum_config=ENABLED_MOMENTUM_CONFIG,
        )
        assert decision.action != ActionType.EXIT or ReasonCode.TRAILING_STOP_TRIGGERED not in decision.reason_codes


class TestSMAGuard:
    def test_sma_blocks_add(self):
        """Price below SMA blocks ADD even with BUY zone and high conviction."""
        momentum = MomentumSignals(
            price_above_sma=False,
            drawdown_from_cost_pct=5.0,  # above cost, would normally ADD
        )
        holding = _make_holding(
            conviction=70.0,
            avg_cost=95.0,
            current_price=100.0,
            thesis_state=ThesisState.STRENGTHENING,
            zone=ZoneState.BUY,
            momentum=momentum,
        )
        decision = evaluate_holding(
            holding, date(2024, 6, 1), momentum_config=ENABLED_MOMENTUM_CONFIG,
        )
        # Should be HOLD, not ADD
        assert decision.action == ActionType.HOLD
        assert ReasonCode.MOMENTUM_BELOW_SMA in decision.reason_codes

    def test_sma_allows_add_when_above(self):
        """Price above SMA allows ADD."""
        momentum = MomentumSignals(
            price_above_sma=True,
            drawdown_from_cost_pct=5.0,
        )
        holding = _make_holding(
            conviction=70.0,
            avg_cost=95.0,
            current_price=100.0,
            thesis_state=ThesisState.STRENGTHENING,
            zone=ZoneState.BUY,
            momentum=momentum,
        )
        decision = evaluate_holding(
            holding, date(2024, 6, 1), momentum_config=ENABLED_MOMENTUM_CONFIG,
        )
        assert decision.action == ActionType.ADD


class TestUnderwaterAddBlock:
    def test_deeply_underwater_blocks_add(self):
        """Position >20% underwater blocks ADD (with stop-loss disabled to isolate)."""
        # Use custom config: stop-loss disabled, underwater guard enabled
        config = MomentumGuardConfig(
            enabled=True,
            stop_loss_enabled=False,  # disable so it doesn't fire first
            trailing_stop_enabled=False,
            sma_guard_enabled=False,
            underwater_guard_enabled=True,
            underwater_block_pct=-20.0,
            regime_guard_enabled=False,
        )
        momentum = MomentumSignals(
            drawdown_from_cost_pct=-22.0,  # deeply underwater
        )
        holding = _make_holding(
            conviction=70.0,
            avg_cost=100.0,
            current_price=78.0,
            thesis_state=ThesisState.STABLE,
            zone=ZoneState.BUY,
            momentum=momentum,
        )
        decision = evaluate_holding(
            holding, date(2024, 6, 1), momentum_config=config,
        )
        assert decision.action == ActionType.HOLD
        assert ReasonCode.UNDERWATER_ADD_BLOCKED in decision.reason_codes


class TestMarketRegimeGuard:
    def test_bearish_regime_blocks_initiation(self):
        """Bearish market regime blocks new initiations."""
        momentum = MomentumSignals(market_regime_bullish=False)
        candidate = CandidateSnapshot(
            ticker="NEW",
            thesis_id=1,
            thesis_state=ThesisState.STRENGTHENING,
            conviction_score=70.0,
            zone_state=ZoneState.BUY,
            has_checkpoint_ahead=True,
            days_to_checkpoint=30,
            novel_claim_count_7d=5,
            momentum=momentum,
        )
        decision = evaluate_candidate(
            candidate, None, date(2024, 6, 1),
            relaxed_gates=True,
            momentum_config=ENABLED_MOMENTUM_CONFIG,
        )
        assert decision.action == ActionType.NO_ACTION
        assert ReasonCode.MARKET_REGIME_BEARISH in decision.reason_codes

    def test_bullish_regime_allows_initiation(self):
        """Bullish market regime allows initiations."""
        momentum = MomentumSignals(market_regime_bullish=True)
        candidate = CandidateSnapshot(
            ticker="NEW",
            thesis_id=1,
            thesis_state=ThesisState.STRENGTHENING,
            conviction_score=70.0,
            zone_state=ZoneState.BUY,
            has_checkpoint_ahead=True,
            days_to_checkpoint=30,
            novel_claim_count_7d=5,
            momentum=momentum,
        )
        decision = evaluate_candidate(
            candidate, None, date(2024, 6, 1),
            relaxed_gates=True,
            momentum_config=ENABLED_MOMENTUM_CONFIG,
        )
        assert decision.action == ActionType.INITIATE


class TestBackwardCompatibility:
    def test_disabled_config_no_change(self):
        """With disabled config, decisions are identical to no-momentum baseline."""
        holding = _make_holding(
            conviction=70.0,
            avg_cost=95.0,
            current_price=100.0,
            thesis_state=ThesisState.STRENGTHENING,
            zone=ZoneState.BUY,
        )
        d1 = evaluate_holding(holding, date(2024, 6, 1))
        d2 = evaluate_holding(
            holding, date(2024, 6, 1),
            momentum_config=DISABLED_MOMENTUM_CONFIG,
        )
        assert d1.action == d2.action
        assert d1.action_score == d2.action_score


# ---------------------------------------------------------------------------
# Distance from high / overbought tests
# ---------------------------------------------------------------------------

class TestDistanceFromHigh:
    def test_at_high(self):
        prices = _make_prices(date(2024, 1, 1), [80, 90, 100, 95, 100])
        dist = compute_distance_from_high(prices, date(2024, 1, 5), lookback_days=10)
        assert dist == pytest.approx(0.0)

    def test_below_high(self):
        prices = _make_prices(date(2024, 1, 1), [80, 100, 95, 90, 80])
        dist = compute_distance_from_high(prices, date(2024, 1, 5), lookback_days=10)
        assert dist == pytest.approx(-20.0)

    def test_near_high(self):
        prices = _make_prices(date(2024, 1, 1), [80, 100, 95, 90, 97])
        dist = compute_distance_from_high(prices, date(2024, 1, 5), lookback_days=10)
        assert dist == pytest.approx(-3.0)

    def test_empty(self):
        assert compute_distance_from_high([], date(2024, 1, 1), lookback_days=10) is None


class TestOverboughtGuard:
    def test_overbought_blocks_add(self):
        """Price near 90-day high blocks ADD even with BUY zone."""
        momentum = MomentumSignals(
            is_overbought=True,
            distance_from_high_pct=-2.0,  # within 5% of high
            drawdown_from_cost_pct=5.0,
        )
        holding = _make_holding(
            conviction=70.0,
            avg_cost=95.0,
            current_price=100.0,
            thesis_state=ThesisState.STRENGTHENING,
            zone=ZoneState.BUY,
            momentum=momentum,
        )
        decision = evaluate_holding(
            holding, date(2024, 6, 1), momentum_config=ENABLED_MOMENTUM_CONFIG,
        )
        assert decision.action == ActionType.HOLD
        assert ReasonCode.OVERBOUGHT_ADD_BLOCKED in decision.reason_codes

    def test_not_overbought_allows_add(self):
        """Price far from high allows ADD."""
        momentum = MomentumSignals(
            is_overbought=False,
            distance_from_high_pct=-15.0,  # 15% below high
            price_above_sma=True,
            drawdown_from_cost_pct=5.0,
        )
        holding = _make_holding(
            conviction=70.0,
            avg_cost=95.0,
            current_price=100.0,
            thesis_state=ThesisState.STRENGTHENING,
            zone=ZoneState.BUY,
            momentum=momentum,
        )
        decision = evaluate_holding(
            holding, date(2024, 6, 1), momentum_config=ENABLED_MOMENTUM_CONFIG,
        )
        assert decision.action == ActionType.ADD

    def test_overbought_blocks_initiation(self):
        """Price near 90-day high blocks INITIATE."""
        momentum = MomentumSignals(
            market_regime_bullish=True,
            is_overbought=True,
            distance_from_high_pct=-3.0,
        )
        candidate = CandidateSnapshot(
            ticker="NEW",
            thesis_id=1,
            thesis_state=ThesisState.STRENGTHENING,
            conviction_score=70.0,
            zone_state=ZoneState.BUY,
            has_checkpoint_ahead=True,
            days_to_checkpoint=30,
            novel_claim_count_7d=5,
            momentum=momentum,
        )
        decision = evaluate_candidate(
            candidate, None, date(2024, 6, 1),
            relaxed_gates=True,
            momentum_config=ENABLED_MOMENTUM_CONFIG,
        )
        assert decision.action == ActionType.NO_ACTION
        assert ReasonCode.OVERBOUGHT_INITIATE_BLOCKED in decision.reason_codes

    def test_not_overbought_allows_initiation(self):
        """Price far from high allows INITIATE."""
        momentum = MomentumSignals(
            market_regime_bullish=True,
            is_overbought=False,
            distance_from_high_pct=-15.0,
        )
        candidate = CandidateSnapshot(
            ticker="NEW",
            thesis_id=1,
            thesis_state=ThesisState.STRENGTHENING,
            conviction_score=70.0,
            zone_state=ZoneState.BUY,
            has_checkpoint_ahead=True,
            days_to_checkpoint=30,
            novel_claim_count_7d=5,
            momentum=momentum,
        )
        decision = evaluate_candidate(
            candidate, None, date(2024, 6, 1),
            relaxed_gates=True,
            momentum_config=ENABLED_MOMENTUM_CONFIG,
        )
        assert decision.action == ActionType.INITIATE
