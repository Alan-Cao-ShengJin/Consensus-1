"""Tests for the intelligence modules: conviction decay, priced-in detection,
market sentiment, and auto-valuation.
"""
import pytest
from datetime import date

from conviction_decay import (
    compute_conviction_decay, apply_conviction_decay,
    ConvictionDecayConfig, DEFAULT_DECAY_CONFIG, DISABLED_DECAY_CONFIG,
)
from priced_in_detector import (
    detect_priced_in, apply_priced_in_dampening,
    PricedInConfig, DEFAULT_PRICED_IN_CONFIG, DISABLED_PRICED_IN_CONFIG,
)
from market_sentiment import (
    compute_market_sentiment, MarketRegime,
    MarketSentimentConfig, DEFAULT_SENTIMENT_CONFIG, DISABLED_SENTIMENT_CONFIG,
)
from auto_valuation import (
    compute_pe_ratio, compute_peg_ratio, compute_ev_to_revenue,
    compute_valuation, FinancialSnapshot, ValuationConfig,
    DEFAULT_VALUATION_CONFIG,
)


# =====================================================================
# Conviction Decay Tests
# =====================================================================

class TestConvictionDecay:
    """Tests for conviction decay engine."""

    def test_disabled_config_no_decay(self):
        decay = compute_conviction_decay(
            current_score=80.0,
            days_since_last_evidence=30,
            price_change_pct=-20.0,
            config=DISABLED_DECAY_CONFIG,
        )
        assert decay == 0.0

    def test_no_decay_with_fresh_evidence(self):
        """No decay when evidence arrived within the staleness window."""
        decay = compute_conviction_decay(
            current_score=80.0,
            days_since_last_evidence=7,
            price_change_pct=None,
        )
        assert decay == 0.0

    def test_decay_when_stale(self):
        """Decay kicks in when no evidence for >14 days."""
        decay = compute_conviction_decay(
            current_score=80.0,
            days_since_last_evidence=30,
            price_change_pct=None,
        )
        assert decay > 0
        assert decay <= 5.0  # max per cycle

    def test_higher_conviction_decays_faster(self):
        """High-conviction positions should decay faster than low ones."""
        decay_high = compute_conviction_decay(
            current_score=90.0,
            days_since_last_evidence=30,
            price_change_pct=None,
        )
        decay_low = compute_conviction_decay(
            current_score=55.0,
            days_since_last_evidence=30,
            price_change_pct=None,
        )
        assert decay_high > decay_low

    def test_no_decay_below_floor(self):
        """Below the floor (40), no decay."""
        decay = compute_conviction_decay(
            current_score=35.0,
            days_since_last_evidence=30,
            price_change_pct=None,
        )
        assert decay == 0.0

    def test_price_divergence_amplifies_decay(self):
        """Price drop amplifies decay for high-conviction positions."""
        decay_no_drop = compute_conviction_decay(
            current_score=80.0,
            days_since_last_evidence=30,
            price_change_pct=0.0,
        )
        decay_with_drop = compute_conviction_decay(
            current_score=80.0,
            days_since_last_evidence=30,
            price_change_pct=-15.0,
        )
        assert decay_with_drop > decay_no_drop

    def test_apply_returns_new_score_and_amount(self):
        new_score, amount = apply_conviction_decay(
            current_score=80.0,
            days_since_last_evidence=30,
            price_change_pct=None,
        )
        assert new_score < 80.0
        assert amount > 0
        assert new_score == round(80.0 - amount, 2)

    def test_decay_does_not_go_below_floor(self):
        """Decay should stop at the floor."""
        new_score, _ = apply_conviction_decay(
            current_score=42.0,
            days_since_last_evidence=365,
            price_change_pct=-30.0,
        )
        assert new_score >= 40.0


# =====================================================================
# Priced-In Detector Tests
# =====================================================================

class TestPricedInDetector:
    """Tests for priced-in detection."""

    def test_disabled_no_signal(self):
        signal = detect_priced_in(
            ticker="AAPL",
            price_change_pct_lookback=30.0,
            positive_claim_count=10,
            negative_claim_count=0,
            neutral_claim_count=0,
            config=DISABLED_PRICED_IN_CONFIG,
        )
        assert not signal.is_priced_in
        assert signal.conviction_dampener == 1.0

    def test_price_runup_detected(self):
        signal = detect_priced_in(
            ticker="NVDA",
            price_change_pct_lookback=25.0,
            positive_claim_count=5,
            negative_claim_count=1,
            neutral_claim_count=1,
        )
        assert signal.price_runup_detected
        assert signal.is_priced_in

    def test_consensus_crowding(self):
        signal = detect_priced_in(
            ticker="TSLA",
            price_change_pct_lookback=5.0,
            positive_claim_count=9,
            negative_claim_count=1,
            neutral_claim_count=0,
        )
        assert signal.consensus_crowded
        assert signal.bullish_claim_ratio >= 0.80

    def test_strong_priced_in_multiple_signals(self):
        """Multiple signals should trigger strong dampening."""
        signal = detect_priced_in(
            ticker="META",
            price_change_pct_lookback=20.0,
            positive_claim_count=9,
            negative_claim_count=1,
            neutral_claim_count=0,
        )
        assert signal.signal_count >= 2
        assert signal.conviction_dampener == 0.25  # strong dampener

    def test_dampening_only_affects_positive_deltas(self):
        from priced_in_detector import PricedInSignal
        signal = PricedInSignal(ticker="X", is_priced_in=True, conviction_dampener=0.5)

        dampened_pos = apply_priced_in_dampening(10.0, signal)
        dampened_neg = apply_priced_in_dampening(-10.0, signal)

        assert dampened_pos == 5.0   # halved
        assert dampened_neg == -10.0  # unchanged


# =====================================================================
# Market Sentiment Tests
# =====================================================================

class TestMarketSentiment:
    """Tests for market sentiment signal."""

    def test_disabled_returns_risk_on(self):
        score = compute_market_sentiment(
            as_of=date(2024, 6, 1),
            vix_level=40.0,
            config=DISABLED_SENTIMENT_CONFIG,
        )
        assert score.regime == MarketRegime.RISK_ON
        assert score.sizing_multiplier == 1.0

    def test_calm_market_is_risk_on(self):
        score = compute_market_sentiment(
            as_of=date(2024, 6, 1),
            vix_level=15.0,
            yield_curve_spread=1.5,
            benchmark_above_sma=True,
        )
        assert score.regime == MarketRegime.RISK_ON
        assert not score.block_initiations

    def test_elevated_vix_is_cautious(self):
        score = compute_market_sentiment(
            as_of=date(2024, 6, 1),
            vix_level=28.0,
            yield_curve_spread=1.0,
            benchmark_above_sma=True,
        )
        assert score.regime in (MarketRegime.CAUTIOUS, MarketRegime.RISK_ON)

    def test_extreme_fear(self):
        score = compute_market_sentiment(
            as_of=date(2024, 6, 1),
            vix_level=40.0,
            yield_curve_spread=-0.5,
            benchmark_above_sma=False,
            dxy_level=110.0,
        )
        assert score.regime == MarketRegime.EXTREME_FEAR
        assert score.block_initiations
        assert score.sizing_multiplier == 0.0

    def test_risk_off_blocks_initiations(self):
        score = compute_market_sentiment(
            as_of=date(2024, 6, 1),
            vix_level=30.0,
            yield_curve_spread=-0.2,
            benchmark_above_sma=False,
        )
        assert score.regime in (MarketRegime.RISK_OFF, MarketRegime.EXTREME_FEAR)
        assert score.block_initiations

    def test_strong_dollar_adds_risk(self):
        calm = compute_market_sentiment(
            as_of=date(2024, 6, 1),
            dxy_level=90.0,
        )
        strong = compute_market_sentiment(
            as_of=date(2024, 6, 1),
            dxy_level=110.0,
        )
        assert strong.risk_score >= calm.risk_score


# =====================================================================
# Auto-Valuation Tests
# =====================================================================

class TestAutoValuation:
    """Tests for auto-valuation engine."""

    def test_pe_ratio(self):
        assert compute_pe_ratio(150.0, 6.0) == 25.0
        assert compute_pe_ratio(150.0, -1.0) is None  # negative EPS

    def test_peg_ratio(self):
        assert compute_peg_ratio(25.0, 25.0) == 1.0
        assert compute_peg_ratio(25.0, 0.0) is None

    def test_ev_to_revenue(self):
        result = compute_ev_to_revenue(
            market_cap=1e12, total_debt=50e9, cash=100e9, ttm_revenue=100e9,
        )
        assert result is not None
        assert abs(result - 9.5) < 0.1  # (1T + 50B - 100B) / 100B = 9.5

    def test_compute_valuation_empty_financials(self):
        result = compute_valuation(
            ticker="AAPL", as_of=date(2024, 6, 1),
            current_price=200.0, financials=[],
        )
        assert result.valuation_gap_pct is None

    def test_compute_valuation_with_data(self):
        financials = [
            FinancialSnapshot(
                period_end=date(2024, 3, 31),
                revenue=100e9, net_income=25e9, eps_diluted=1.5,
                free_cash_flow=20e9, ebitda=35e9,
                total_debt=50e9, cash_and_equivalents=80e9,
                shares_outstanding=15e9,
            ),
            FinancialSnapshot(
                period_end=date(2023, 12, 31),
                revenue=95e9, net_income=23e9, eps_diluted=1.4,
                free_cash_flow=18e9, ebitda=32e9,
            ),
            FinancialSnapshot(
                period_end=date(2023, 9, 30),
                revenue=90e9, net_income=22e9, eps_diluted=1.3,
            ),
            FinancialSnapshot(
                period_end=date(2023, 6, 30),
                revenue=85e9, net_income=20e9, eps_diluted=1.2,
            ),
        ]
        result = compute_valuation(
            ticker="AAPL", as_of=date(2024, 6, 1),
            current_price=200.0, financials=financials,
        )
        assert result.pe_ratio is not None
        assert result.valuation_gap_pct is not None
        assert result.confidence > 0

    def test_disabled_config(self):
        from auto_valuation import DISABLED_VALUATION_CONFIG
        result = compute_valuation(
            ticker="X", as_of=date(2024, 1, 1),
            current_price=100.0,
            financials=[FinancialSnapshot(period_end=date(2024, 1, 1))],
            config=DISABLED_VALUATION_CONFIG,
        )
        assert result.valuation_gap_pct is None
