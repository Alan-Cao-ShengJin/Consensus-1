"""Tests for earnings surprise bucketing and conviction impact."""
import pytest
from earnings_surprise import (
    SurpriseBucket,
    SurpriseThresholds,
    DEFAULT_THRESHOLDS,
    BUCKET_DIRECTION,
    BUCKET_STRENGTH,
    compute_surprise_pct,
    classify_bucket,
    compute_revenue_surprise,
    compute_eps_surprise,
    compute_earnings_surprise,
    EarningsSurprise,
)


class TestSurprisePct:
    def test_beat(self):
        # Actual $70B vs estimate $68B = +2.94%
        assert round(compute_surprise_pct(70e9, 68e9), 2) == 2.94

    def test_miss(self):
        # Actual $65B vs estimate $68B = -4.41%
        assert round(compute_surprise_pct(65e9, 68e9), 2) == -4.41

    def test_inline(self):
        # Actual == estimate = 0%
        assert compute_surprise_pct(68e9, 68e9) == 0.0

    def test_zero_estimate(self):
        assert compute_surprise_pct(5.0, 0.0) == 0.0


class TestClassifyBucket:
    """Test bucket classification with default revenue thresholds."""
    T = DEFAULT_THRESHOLDS

    def test_big_miss(self):
        # -8% revenue surprise
        assert classify_bucket(-8.0, self.T.revenue_big_miss, self.T.revenue_small_miss,
                               self.T.revenue_small_beat, self.T.revenue_big_beat) == SurpriseBucket.BIG_MISS

    def test_small_miss(self):
        # -3% revenue surprise
        assert classify_bucket(-3.0, self.T.revenue_big_miss, self.T.revenue_small_miss,
                               self.T.revenue_small_beat, self.T.revenue_big_beat) == SurpriseBucket.SMALL_MISS

    def test_inline_negative(self):
        # -1% = within noise band
        assert classify_bucket(-1.0, self.T.revenue_big_miss, self.T.revenue_small_miss,
                               self.T.revenue_small_beat, self.T.revenue_big_beat) == SurpriseBucket.INLINE

    def test_inline_positive(self):
        # +1% = within noise band
        assert classify_bucket(1.0, self.T.revenue_big_miss, self.T.revenue_small_miss,
                               self.T.revenue_small_beat, self.T.revenue_big_beat) == SurpriseBucket.INLINE

    def test_small_beat(self):
        # +3% revenue surprise
        assert classify_bucket(3.0, self.T.revenue_big_miss, self.T.revenue_small_miss,
                               self.T.revenue_small_beat, self.T.revenue_big_beat) == SurpriseBucket.SMALL_BEAT

    def test_big_beat(self):
        # +7% revenue surprise
        assert classify_bucket(7.0, self.T.revenue_big_miss, self.T.revenue_small_miss,
                               self.T.revenue_small_beat, self.T.revenue_big_beat) == SurpriseBucket.BIG_BEAT

    def test_boundary_big_miss(self):
        # Exactly -5% = big miss (<=)
        assert classify_bucket(-5.0, self.T.revenue_big_miss, self.T.revenue_small_miss,
                               self.T.revenue_small_beat, self.T.revenue_big_beat) == SurpriseBucket.BIG_MISS

    def test_boundary_small_beat(self):
        # Exactly +2% = small beat (>=)
        assert classify_bucket(2.0, self.T.revenue_big_miss, self.T.revenue_small_miss,
                               self.T.revenue_small_beat, self.T.revenue_big_beat) == SurpriseBucket.SMALL_BEAT


class TestRevenueSurprise:
    def test_costco_beat(self):
        # Costco: actual $68.24B vs estimate $62.5B = big beat
        r = compute_revenue_surprise(68.24e9, 62.5e9)
        assert r.bucket == SurpriseBucket.BIG_BEAT
        assert r.direction == "positive"
        assert r.strength == 0.9
        assert r.surprise_pct > 5.0

    def test_costco_miss(self):
        # Hypothetical: actual $59B vs estimate $62.5B = big miss
        r = compute_revenue_surprise(59e9, 62.5e9)
        assert r.bucket == SurpriseBucket.BIG_MISS
        assert r.direction == "negative"
        assert r.strength == 0.95

    def test_costco_inline(self):
        # Actual $63B vs estimate $62.5B = +0.8% = inline
        r = compute_revenue_surprise(63e9, 62.5e9)
        assert r.bucket == SurpriseBucket.INLINE
        assert r.direction == "neutral"
        assert r.strength == 0.2


class TestEpsSurprise:
    def test_eps_big_beat(self):
        # Actual $4.58 vs estimate $3.80 = +20.5% = big beat
        e = compute_eps_surprise(4.58, 3.80)
        assert e.bucket == SurpriseBucket.BIG_BEAT
        assert e.direction == "positive"

    def test_eps_small_miss(self):
        # Actual $4.00 vs estimate $4.20 = -4.76% = small miss
        e = compute_eps_surprise(4.00, 4.20)
        assert e.bucket == SurpriseBucket.SMALL_MISS
        assert e.direction == "negative"

    def test_eps_inline(self):
        # Actual $4.21 vs estimate $4.20 = +0.24% = inline
        e = compute_eps_surprise(4.21, 4.20)
        assert e.bucket == SurpriseBucket.INLINE
        assert e.direction == "neutral"

    def test_eps_wider_thresholds(self):
        # EPS thresholds are wider: -7% is small miss for EPS but big miss for revenue
        e = compute_eps_surprise(4.58, 4.93)  # -7.1%
        assert e.bucket == SurpriseBucket.SMALL_MISS

        r = compute_revenue_surprise(64.5e9, 69.4e9)  # -7.1%
        assert r.bucket == SurpriseBucket.BIG_MISS


class TestCompositeEarningsSurprise:
    def test_both_beat(self):
        s = compute_earnings_surprise(
            "COST",
            actual_revenue=70e9, estimated_revenue=68e9,
            actual_eps=4.58, estimated_eps=4.20,
        )
        assert s is not None
        assert s.composite_bucket == SurpriseBucket.SMALL_BEAT  # revenue +2.9% = small beat (conservative)
        assert s.composite_direction == "positive"

    def test_revenue_miss_eps_beat(self):
        # Revenue miss but EPS beat — composite takes the worse one
        s = compute_earnings_surprise(
            "COST",
            actual_revenue=60e9, estimated_revenue=68e9,  # -11.8% big miss
            actual_eps=5.00, estimated_eps=4.20,  # +19% big beat
        )
        assert s is not None
        assert s.composite_bucket == SurpriseBucket.BIG_MISS
        assert s.composite_direction == "negative"

    def test_revenue_only(self):
        s = compute_earnings_surprise(
            "COST", actual_revenue=70e9, estimated_revenue=68e9,
        )
        assert s is not None
        assert s.revenue is not None
        assert s.eps is None
        assert s.composite_bucket == SurpriseBucket.SMALL_BEAT

    def test_no_estimates(self):
        s = compute_earnings_surprise("COST")
        assert s is None

    def test_zero_estimate_skipped(self):
        s = compute_earnings_surprise(
            "COST", actual_revenue=70e9, estimated_revenue=0,
            actual_eps=4.58, estimated_eps=0,
        )
        assert s is None


class TestPromptContext:
    def test_format_with_both_metrics(self):
        s = compute_earnings_surprise(
            "COST",
            actual_revenue=68.24e9, estimated_revenue=67e9,
            actual_eps=4.58, estimated_eps=4.20,
            num_analysts=23,
            fiscal_period="Q2 FY2026",
        )
        ctx = s.to_prompt_context()
        assert "COST" in ctx
        assert "Q2 FY2026" in ctx
        assert "Revenue estimate" in ctx
        assert "EPS estimate" in ctx
        assert "$4.20" in ctx
        assert "$4.58" in ctx
        assert "ABOVE estimate = positive" in ctx

    def test_format_empty_when_no_surprise(self):
        s = compute_earnings_surprise("COST")
        assert s is None


class TestBucketMappings:
    def test_all_buckets_have_direction(self):
        for bucket in [SurpriseBucket.BIG_MISS, SurpriseBucket.SMALL_MISS,
                       SurpriseBucket.INLINE, SurpriseBucket.SMALL_BEAT,
                       SurpriseBucket.BIG_BEAT]:
            assert bucket in BUCKET_DIRECTION
            assert bucket in BUCKET_STRENGTH

    def test_direction_values(self):
        assert BUCKET_DIRECTION[SurpriseBucket.BIG_MISS] == "negative"
        assert BUCKET_DIRECTION[SurpriseBucket.SMALL_MISS] == "negative"
        assert BUCKET_DIRECTION[SurpriseBucket.INLINE] == "neutral"
        assert BUCKET_DIRECTION[SurpriseBucket.SMALL_BEAT] == "positive"
        assert BUCKET_DIRECTION[SurpriseBucket.BIG_BEAT] == "positive"

    def test_strength_ordering(self):
        # Big miss > small miss, big beat > small beat, inline is weakest
        assert BUCKET_STRENGTH[SurpriseBucket.BIG_MISS] > BUCKET_STRENGTH[SurpriseBucket.SMALL_MISS]
        assert BUCKET_STRENGTH[SurpriseBucket.BIG_BEAT] > BUCKET_STRENGTH[SurpriseBucket.SMALL_BEAT]
        assert BUCKET_STRENGTH[SurpriseBucket.INLINE] < BUCKET_STRENGTH[SurpriseBucket.SMALL_MISS]


class TestCustomThresholds:
    def test_tighter_thresholds(self):
        # Tighter thresholds for a stable utility company
        tight = SurpriseThresholds(
            revenue_big_miss=-3.0, revenue_small_miss=-1.0,
            revenue_small_beat=1.0, revenue_big_beat=3.0,
            eps_big_miss=-5.0, eps_small_miss=-2.0,
            eps_small_beat=2.0, eps_big_beat=5.0,
        )
        # 2.5% surprise is now a small beat under default but big beat under tight
        r_default = compute_revenue_surprise(70.25e9, 68.5e9)  # ~2.6%
        r_tight = compute_revenue_surprise(70.25e9, 68.5e9, thresholds=tight)
        assert r_default.bucket == SurpriseBucket.SMALL_BEAT
        assert r_tight.bucket == SurpriseBucket.SMALL_BEAT  # still small beat (< 3%)

        # 3.5% is small beat default, big beat under tight
        r2 = compute_revenue_surprise(70.9e9, 68.5e9, thresholds=tight)  # ~3.5%
        assert r2.bucket == SurpriseBucket.BIG_BEAT
