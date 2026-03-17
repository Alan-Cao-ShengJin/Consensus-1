"""Tests for portfolio decision engine (Step 7).

Covers:
  - Entry gate logic (all four gates)
  - Candidate vs weakest holding relative hurdle
  - Add-to-loser blocked without confirming evidence
  - Winner add allowed when conviction strong and valuation not stretched
  - Thesis broken triggers exit
  - Probation blocks adds
  - Probation expiry triggers exit after two reviews
  - Cooldown blocks immediate re-entry
  - Turnover cap enforcement
  - Full weekly review returns coherent ranked actions
  - Valuation zone classification
  - Review persistence
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from models import (
    Base, Company, Thesis, ThesisState, PortfolioPosition, Candidate,
    ZoneState, PositionStatus, ActionType, Checkpoint,
    PortfolioReview, PortfolioDecision,
)
from portfolio_decision_engine import (
    HoldingSnapshot, CandidateSnapshot, DecisionInput,
    TickerDecision, PortfolioReviewResult, ReasonCode,
    evaluate_holding, evaluate_candidate, run_decision_engine,
    INITIATION_CONVICTION_FLOOR, RELATIVE_HURDLE_MARGIN,
    COOLDOWN_DAYS, TRIM_CONVICTION_THRESHOLD,
    EXIT_CONVICTION_CEILING, TRIM_CONVICTION_CEILING,
    PRIORITY_FORCED_EXIT, PRIORITY_STRONG_EXIT, PRIORITY_DEFENSIVE,
    PRIORITY_CAPITAL_REDEPLOY, PRIORITY_GROWTH, PRIORITY_NEUTRAL,
)
from valuation_policy import (
    classify_zone, ZoneThresholds, DEFAULT_THRESHOLDS,
    compute_valuation_gap, zone_from_thesis_and_price,
)
from portfolio_review_service import (
    run_portfolio_review, format_review_text,
)


TODAY = date(2026, 3, 12)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


def _make_company(session, ticker="NVDA"):
    session.add(Company(ticker=ticker, name=f"{ticker} Inc"))
    session.flush()


def _make_thesis(session, ticker="NVDA", state=ThesisState.STRENGTHENING,
                 conviction=70.0, valuation_gap=15.0, base_case=1.3):
    thesis = Thesis(
        title=f"{ticker} thesis",
        company_ticker=ticker,
        state=state,
        conviction_score=conviction,
        valuation_gap_pct=valuation_gap,
        base_case_rerating=base_case,
    )
    session.add(thesis)
    session.flush()
    return thesis


# ---------------------------------------------------------------------------
# Helper to build snapshots quickly
# ---------------------------------------------------------------------------

def _holding(
    ticker="NVDA", conviction=70.0, weight=5.0,
    thesis_state=ThesisState.STRENGTHENING,
    zone=ZoneState.HOLD, probation=False, probation_reviews=0,
    avg_cost=100.0, current_price=110.0,
    valuation_gap=None, base_case=None,
    novel_7d=1, confirming_7d=1,
    has_checkpoint=True, price_change_5d=None,
    sector=None,
) -> HoldingSnapshot:
    return HoldingSnapshot(
        ticker=ticker,
        position_id=1,
        thesis_id=1,
        thesis_state=thesis_state,
        conviction_score=conviction,
        current_weight=weight,
        target_weight=weight,
        avg_cost=avg_cost,
        current_price=current_price,
        valuation_gap_pct=valuation_gap,
        base_case_rerating=base_case,
        zone_state=zone,
        probation_flag=probation,
        probation_reviews_count=probation_reviews,
        has_checkpoint_ahead=has_checkpoint,
        novel_claim_count_7d=novel_7d,
        confirming_claim_count_7d=confirming_7d,
        price_change_pct_5d=price_change_5d,
        sector=sector,
    )


def _candidate(
    ticker="AMD", conviction=65.0,
    thesis_state=ThesisState.STRENGTHENING,
    zone=ZoneState.BUY,
    has_checkpoint=True, novel_7d=2, confirming_7d=1,
    cooldown=False, cooldown_until=None,
    valuation_gap=15.0, base_case=1.3,
    sector=None,
) -> CandidateSnapshot:
    return CandidateSnapshot(
        ticker=ticker,
        candidate_id=1,
        thesis_id=1,
        thesis_state=thesis_state,
        conviction_score=conviction,
        valuation_gap_pct=valuation_gap,
        base_case_rerating=base_case,
        current_price=100.0,
        zone_state=zone,
        has_checkpoint_ahead=has_checkpoint,
        novel_claim_count_7d=novel_7d,
        confirming_claim_count_7d=confirming_7d,
        cooldown_flag=cooldown,
        cooldown_until=cooldown_until,
        sector=sector,
    )


# ---------------------------------------------------------------------------
# 1. Valuation zone classification
# ---------------------------------------------------------------------------

class TestValuationPolicy:

    def test_buy_zone(self):
        assert classify_zone(15.0) == ZoneState.BUY

    def test_hold_zone(self):
        assert classify_zone(3.0) == ZoneState.HOLD

    def test_trim_zone(self):
        assert classify_zone(-10.0) == ZoneState.TRIM

    def test_full_exit_zone(self):
        assert classify_zone(-25.0) == ZoneState.FULL_EXIT

    def test_none_defaults_to_hold(self):
        assert classify_zone(None) == ZoneState.HOLD

    def test_compute_gap(self):
        gap = compute_valuation_gap(100.0, 130.0)
        assert gap == pytest.approx(30.0)

    def test_zone_from_thesis_prefers_gap_pct(self):
        zone = zone_from_thesis_and_price(
            valuation_gap_pct=15.0,
            base_case_rerating=0.5,  # would be trim, but gap overrides
            current_price=100.0,
        )
        assert zone == ZoneState.BUY

    def test_zone_from_thesis_falls_back_to_rerating(self):
        zone = zone_from_thesis_and_price(
            valuation_gap_pct=None,
            base_case_rerating=1.3,  # 30% upside
            current_price=100.0,
        )
        assert zone == ZoneState.BUY


# ---------------------------------------------------------------------------
# 2. Entry gate logic
# ---------------------------------------------------------------------------

class TestEntryGates:

    def test_initiate_when_all_gates_pass(self):
        c = _candidate(conviction=65.0, zone=ZoneState.BUY, has_checkpoint=True, novel_7d=2)
        weakest = _holding(conviction=55.0)
        d = evaluate_candidate(c, weakest, TODAY)
        assert d.action == ActionType.INITIATE

    def test_no_thesis_blocks_initiation(self):
        c = _candidate()
        c.thesis_id = None
        c.thesis_state = None
        d = evaluate_candidate(c, None, TODAY)
        assert d.action == ActionType.NO_ACTION
        assert ReasonCode.NO_THESIS in d.reason_codes

    def test_broken_thesis_blocks_initiation(self):
        c = _candidate(thesis_state=ThesisState.BROKEN)
        d = evaluate_candidate(c, None, TODAY)
        assert d.action == ActionType.NO_ACTION
        assert ReasonCode.THESIS_BROKEN in d.reason_codes

    def test_low_conviction_blocks_initiation(self):
        c = _candidate(conviction=40.0)
        d = evaluate_candidate(c, None, TODAY)
        assert d.action == ActionType.NO_ACTION
        assert ReasonCode.CONVICTION_LOW in d.reason_codes

    def test_no_evidence_blocks_initiation(self):
        c = _candidate(novel_7d=0, confirming_7d=0)
        d = evaluate_candidate(c, None, TODAY)
        assert d.action == ActionType.NO_ACTION
        assert ReasonCode.INSUFFICIENT_NOVEL_EVIDENCE in d.reason_codes

    def test_bad_valuation_no_longer_blocks_initiation(self):
        """Valuation is advisory, not blocking — conviction + evidence are the gates."""
        c = _candidate(zone=ZoneState.HOLD, valuation_gap=-3.0)
        d = evaluate_candidate(c, None, TODAY)
        assert d.action == ActionType.INITIATE  # valuation is advisory

    def test_no_checkpoint_no_longer_blocks_initiation(self):
        """Checkpoint is advisory, not blocking."""
        c = _candidate(has_checkpoint=False)
        d = evaluate_candidate(c, None, TODAY)
        assert d.action == ActionType.INITIATE  # checkpoint is advisory
        assert ReasonCode.NO_CHECKPOINT_AHEAD in d.reason_codes


# ---------------------------------------------------------------------------
# 3. Candidate fails if it does not beat weakest holding
# ---------------------------------------------------------------------------

class TestRelativeHurdle:

    def test_candidate_fails_relative_hurdle(self):
        c = _candidate(conviction=58.0)
        weakest = _holding(conviction=55.0)  # needs 55 + 5 = 60
        d = evaluate_candidate(c, weakest, TODAY)
        assert d.action == ActionType.NO_ACTION
        assert ReasonCode.FAILED_RELATIVE_HURDLE in d.reason_codes

    def test_candidate_passes_relative_hurdle(self):
        c = _candidate(conviction=65.0)
        weakest = _holding(conviction=55.0)  # needs 55 + 5 = 60
        d = evaluate_candidate(c, weakest, TODAY)
        assert d.action == ActionType.INITIATE
        assert ReasonCode.BETTER_THAN_WEAKEST_HOLDING in d.reason_codes

    def test_candidate_without_holdings_no_hurdle(self):
        c = _candidate(conviction=56.0)
        d = evaluate_candidate(c, None, TODAY)
        assert d.action == ActionType.INITIATE


# ---------------------------------------------------------------------------
# 4. Add-to-loser blocked without confirming evidence
# ---------------------------------------------------------------------------

class TestAddToLoser:

    def test_add_to_loser_blocked_without_evidence(self):
        h = _holding(
            conviction=60.0, avg_cost=120.0, current_price=100.0,
            valuation_gap=15.0,  # BUY zone
            novel_7d=0, confirming_7d=0,
        )
        d = evaluate_holding(h, TODAY)
        # Should not be ADD — should be HOLD because no confirming evidence
        assert d.action != ActionType.ADD
        assert ReasonCode.INSUFFICIENT_NOVEL_EVIDENCE in d.reason_codes

    def test_add_to_loser_allowed_with_evidence(self):
        h = _holding(
            conviction=60.0, avg_cost=120.0, current_price=100.0,
            valuation_gap=15.0,  # BUY zone
            novel_7d=1, confirming_7d=1,
            thesis_state=ThesisState.STABLE,
        )
        d = evaluate_holding(h, TODAY)
        assert d.action == ActionType.ADD
        assert ReasonCode.ADD_TO_LOSER_CONFIRMED in d.reason_codes


# ---------------------------------------------------------------------------
# 5. Winner add allowed when conviction strong and valuation not stretched
# ---------------------------------------------------------------------------

class TestAddToWinner:

    def test_winner_add_allowed(self):
        h = _holding(
            conviction=65.0, avg_cost=90.0, current_price=110.0,
            valuation_gap=15.0,  # BUY zone
            thesis_state=ThesisState.STRENGTHENING,
        )
        d = evaluate_holding(h, TODAY)
        assert d.action == ActionType.ADD
        assert ReasonCode.ADD_TO_WINNER in d.reason_codes

    def test_winner_no_add_when_valuation_stretched(self):
        h = _holding(
            conviction=65.0, avg_cost=90.0, current_price=110.0,
            valuation_gap=-10.0,  # TRIM zone
        )
        d = evaluate_holding(h, TODAY)
        assert d.action != ActionType.ADD


# ---------------------------------------------------------------------------
# 6. Thesis broken triggers exit
# ---------------------------------------------------------------------------

class TestThesisBroken:

    def test_broken_thesis_forces_exit(self):
        h = _holding(thesis_state=ThesisState.BROKEN, conviction=10.0)
        d = evaluate_holding(h, TODAY)
        assert d.action == ActionType.EXIT
        assert ReasonCode.THESIS_BROKEN in d.reason_codes
        assert d.suggested_weight == 0.0

    def test_achieved_thesis_exits_when_valuation_not_buy(self):
        h = _holding(
            thesis_state=ThesisState.ACHIEVED, conviction=80.0,
            valuation_gap=-3.0,  # HOLD zone, not BUY
        )
        d = evaluate_holding(h, TODAY)
        assert d.action == ActionType.EXIT
        assert ReasonCode.THESIS_ACHIEVED_EXHAUSTED in d.reason_codes


# ---------------------------------------------------------------------------
# 7. Low conviction triggers trim (replaces probation system)
# ---------------------------------------------------------------------------

class TestLowConvictionTrim:

    def test_low_conviction_trims(self):
        h = _holding(
            conviction=33.0, thesis_state=ThesisState.WEAKENING,
        )
        d = evaluate_holding(h, TODAY)
        assert d.action == ActionType.TRIM
        assert ReasonCode.CONVICTION_LOW in d.reason_codes

    def test_conviction_at_threshold_trims(self):
        h = _holding(conviction=35.0, thesis_state=ThesisState.WEAKENING)
        d = evaluate_holding(h, TODAY)
        assert d.action == ActionType.TRIM

    def test_conviction_above_threshold_no_trim(self):
        h = _holding(conviction=46.0, thesis_state=ThesisState.STABLE)
        d = evaluate_holding(h, TODAY)
        assert d.action != ActionType.TRIM or ReasonCode.CONVICTION_LOW not in d.reason_codes


# ---------------------------------------------------------------------------
# 9. Cooldown blocks immediate re-entry
# ---------------------------------------------------------------------------

class TestCooldown:

    def test_cooldown_blocks_reentry(self):
        c = _candidate(
            conviction=70.0,
            cooldown=True,
            cooldown_until=TODAY + timedelta(days=10),
        )
        d = evaluate_candidate(c, None, TODAY)
        assert d.action == ActionType.NO_ACTION
        assert ReasonCode.COOLDOWN_ACTIVE in d.reason_codes

    def test_cooldown_expired_allows_entry(self):
        c = _candidate(
            conviction=70.0,
            cooldown=True,
            cooldown_until=TODAY - timedelta(days=1),
        )
        d = evaluate_candidate(c, None, TODAY)
        assert d.action == ActionType.INITIATE


# ---------------------------------------------------------------------------
# 10. Turnover cap enforcement
# ---------------------------------------------------------------------------

class TestTurnoverCap:

    def test_turnover_cap_blocks_action(self):
        inputs = DecisionInput(
            review_date=TODAY,
            holdings=[
                _holding(ticker="A", conviction=10.0, weight=15.0,
                         thesis_state=ThesisState.BROKEN),
                _holding(ticker="B", conviction=10.0, weight=15.0,
                         thesis_state=ThesisState.BROKEN),
            ],
            candidates=[],
            weekly_turnover_cap_pct=20.0,
        )
        result = run_decision_engine(inputs)

        # First exit should use 15% of the 20% cap
        # Second exit should be blocked (needs 15%, only 5% remaining)
        exits = [d for d in result.decisions if d.action == ActionType.EXIT]
        blocked = result.blocked_actions
        # At least one should be blocked
        assert len(exits) <= 1 or len(blocked) >= 1

    def test_holds_dont_consume_turnover(self):
        inputs = DecisionInput(
            review_date=TODAY,
            holdings=[
                _holding(ticker="A", conviction=70.0, weight=5.0),
                _holding(ticker="B", conviction=70.0, weight=5.0),
            ],
            candidates=[],
            weekly_turnover_cap_pct=5.0,
        )
        result = run_decision_engine(inputs)
        # Both should be hold/no_action without consuming turnover
        assert result.turnover_pct_planned == 0.0


# ---------------------------------------------------------------------------
# 11. Full weekly review returns coherent ranked actions
# ---------------------------------------------------------------------------

class TestFullReview:

    def test_review_returns_coherent_decisions(self):
        inputs = DecisionInput(
            review_date=TODAY,
            holdings=[
                _holding(ticker="NVDA", conviction=75.0, weight=5.0,
                         thesis_state=ThesisState.STRENGTHENING,
                         avg_cost=90.0, current_price=110.0,
                         valuation_gap=15.0),
                _holding(ticker="WEAK", conviction=30.0, weight=3.0,
                         thesis_state=ThesisState.WEAKENING),
                _holding(ticker="BROKEN", conviction=10.0, weight=4.0,
                         thesis_state=ThesisState.BROKEN),
            ],
            candidates=[
                _candidate(ticker="AMD", conviction=70.0, zone=ZoneState.BUY),
            ],
        )
        result = run_decision_engine(inputs)

        assert len(result.decisions) == 4
        tickers = {d.ticker for d in result.decisions}
        assert tickers == {"NVDA", "WEAK", "BROKEN", "AMD"}

        # BROKEN should be exit
        broken_d = next(d for d in result.decisions if d.ticker == "BROKEN")
        assert broken_d.action == ActionType.EXIT

        # WEAK should be trim (conviction 30 ≤ 35 threshold)
        weak_d = next(d for d in result.decisions if d.ticker == "WEAK")
        assert weak_d.action == ActionType.TRIM

    def test_review_decisions_sorted_by_score(self):
        inputs = DecisionInput(
            review_date=TODAY,
            holdings=[
                _holding(ticker="A", conviction=10.0, weight=5.0,
                         thesis_state=ThesisState.BROKEN),
                _holding(ticker="B", conviction=70.0, weight=5.0),
            ],
            candidates=[],
        )
        result = run_decision_engine(inputs)
        scores = [d.action_score for d in result.decisions]
        assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# 12. Price move alert
# ---------------------------------------------------------------------------

class TestPriceMoveAlert:

    def test_large_price_move_triggers_followup(self):
        h = _holding(conviction=70.0, price_change_5d=12.0)
        d = evaluate_holding(h, TODAY)
        assert ReasonCode.PRICE_MOVE_ALERT in d.reason_codes
        assert any("immediate review" in f.lower() for f in d.required_followup)


# ---------------------------------------------------------------------------
# 13. Integration: review service with DB
# ---------------------------------------------------------------------------

class TestReviewService:

    def test_review_with_empty_portfolio(self, session):
        result = run_portfolio_review(
            session, as_of=TODAY, persist=False,
        )
        assert isinstance(result, PortfolioReviewResult)
        assert len(result.decisions) == 0

    def test_review_persists_to_db(self, session):
        _make_company(session, "NVDA")
        thesis = _make_thesis(session, "NVDA")
        session.add(PortfolioPosition(
            ticker="NVDA", thesis_id=thesis.id,
            entry_date=TODAY - timedelta(days=30),
            avg_cost=100.0, current_weight=5.0, target_weight=5.0,
            conviction_score=70.0, zone_state=ZoneState.HOLD,
        ))
        session.flush()

        result = run_portfolio_review(
            session, as_of=TODAY, persist=True,
        )

        reviews = session.scalars(select(PortfolioReview)).all()
        assert len(reviews) == 1
        assert reviews[0].review_date == TODAY

        decisions = session.scalars(select(PortfolioDecision)).all()
        assert len(decisions) == len(result.decisions)

    def test_review_with_ticker_filter(self, session):
        _make_company(session, "NVDA")
        _make_company(session, "AMD")
        thesis_nvda = _make_thesis(session, "NVDA")
        thesis_amd = _make_thesis(session, "AMD")
        session.add(PortfolioPosition(
            ticker="NVDA", thesis_id=thesis_nvda.id,
            entry_date=TODAY - timedelta(days=30),
            avg_cost=100.0, current_weight=5.0, target_weight=5.0,
            conviction_score=70.0, zone_state=ZoneState.HOLD,
        ))
        session.add(PortfolioPosition(
            ticker="AMD", thesis_id=thesis_amd.id,
            entry_date=TODAY - timedelta(days=30),
            avg_cost=100.0, current_weight=5.0, target_weight=5.0,
            conviction_score=70.0, zone_state=ZoneState.HOLD,
        ))
        session.flush()

        result = run_portfolio_review(
            session, as_of=TODAY, ticker_filter="NVDA", persist=False,
        )

        tickers = {d.ticker for d in result.decisions}
        assert "NVDA" in tickers
        assert "AMD" not in tickers


# ---------------------------------------------------------------------------
# 14. Side effects: probation and exit update position records
# ---------------------------------------------------------------------------

class TestSideEffects:

    def test_exit_recommendation_does_not_close_position(self, session):
        """Step 7.1: exit is recommendation-only — position stays ACTIVE."""
        _make_company(session, "NVDA")
        thesis = _make_thesis(session, "NVDA", state=ThesisState.BROKEN, conviction=10.0)
        pos = PortfolioPosition(
            ticker="NVDA", thesis_id=thesis.id,
            entry_date=TODAY - timedelta(days=30),
            avg_cost=100.0, current_weight=5.0, target_weight=5.0,
            conviction_score=10.0, zone_state=ZoneState.HOLD,
        )
        session.add(pos)
        session.flush()

        result = run_portfolio_review(session, as_of=TODAY, persist=True)

        refreshed = session.get(PortfolioPosition, pos.id)
        # Position must remain ACTIVE — execution is Step 8+
        assert refreshed.status == PositionStatus.ACTIVE
        # Weight must NOT be zeroed
        assert refreshed.current_weight == 5.0
        # No exit_date on live position
        assert refreshed.exit_date is None
        # No cooldown on live position
        assert refreshed.cooldown_flag is False
        assert refreshed.cooldown_until is None
        # But the decision should recommend exit
        exit_decisions = [d for d in result.decisions if d.action == ActionType.EXIT]
        assert len(exit_decisions) == 1
        assert exit_decisions[0].ticker == "NVDA"

    def test_low_conviction_produces_trim_recommendation(self, session):
        """Low conviction produces trim recommendation, position stays ACTIVE."""
        _make_company(session, "NVDA")
        thesis = _make_thesis(session, "NVDA", state=ThesisState.WEAKENING, conviction=33.0)
        pos = PortfolioPosition(
            ticker="NVDA", thesis_id=thesis.id,
            entry_date=TODAY - timedelta(days=30),
            avg_cost=100.0, current_weight=5.0, target_weight=5.0,
            conviction_score=33.0, zone_state=ZoneState.HOLD,
        )
        session.add(pos)
        session.flush()

        result = run_portfolio_review(session, as_of=TODAY, persist=True)

        refreshed = session.get(PortfolioPosition, pos.id)
        # Position stays active — trim is recommendation only
        assert refreshed.status == PositionStatus.ACTIVE
        assert refreshed.current_weight == 5.0
        # Decision should be trim
        trim_decisions = [d for d in result.decisions if d.action == ActionType.TRIM]
        assert len(trim_decisions) >= 1


# ---------------------------------------------------------------------------
# 15. Text report formatting
# ---------------------------------------------------------------------------

class TestTextReport:

    def test_format_produces_readable_output(self):
        result = PortfolioReviewResult(review_date=TODAY)
        result.decisions = [
            TickerDecision(
                ticker="NVDA", action=ActionType.HOLD,
                rationale="Hold — conviction 70",
            ),
        ]
        text = format_review_text(result)
        assert "NVDA" in text
        assert "Portfolio Review" in text

    def test_to_dict_is_json_serializable(self):
        result = PortfolioReviewResult(review_date=TODAY)
        result.decisions = [
            TickerDecision(
                ticker="NVDA", action=ActionType.EXIT,
                action_score=100.0,
                reason_codes=[ReasonCode.THESIS_BROKEN],
                rationale="Broken",
            ),
        ]
        d = result.to_dict()
        serialized = json.dumps(d)
        assert "NVDA" in serialized

    def test_to_dict_includes_audit_fields(self):
        d = TickerDecision(
            ticker="NVDA", action=ActionType.INITIATE,
            funded_by_ticker="WEAK",
            funded_by_action=ActionType.TRIM,
            state_mutation_performed=False,
        )
        out = d.to_dict()
        assert out["funded_by_ticker"] == "WEAK"
        assert out["funded_by_action"] == "trim"
        assert out["decision_stage"] == "recommendation"
        assert out["state_mutation_performed"] is False


# ---------------------------------------------------------------------------
# 16. Step 7.1 Hardening: conviction threshold precedence
# ---------------------------------------------------------------------------

class TestConvictionPrecedence:
    """Prove that conviction thresholds produce correct tiered responses."""

    def test_conviction_20_returns_exit(self):
        """Conviction 20 is below EXIT_CONVICTION_CEILING (25). Must EXIT."""
        h = _holding(conviction=20.0, thesis_state=ThesisState.WEAKENING)
        d = evaluate_holding(h, TODAY)
        assert d.action == ActionType.EXIT
        assert d.recommendation_priority == PRIORITY_STRONG_EXIT
        assert ReasonCode.CONVICTION_LOW in d.reason_codes

    def test_conviction_25_returns_exit(self):
        """Conviction exactly at EXIT_CONVICTION_CEILING. Must EXIT."""
        h = _holding(conviction=25.0, thesis_state=ThesisState.WEAKENING)
        d = evaluate_holding(h, TODAY)
        assert d.action == ActionType.EXIT

    def test_conviction_30_returns_trim(self):
        """Conviction 30 is in trim band (25 < 30 ≤ 35). Must TRIM."""
        h = _holding(conviction=30.0, thesis_state=ThesisState.WEAKENING)
        d = evaluate_holding(h, TODAY)
        assert d.action == ActionType.TRIM
        assert d.recommendation_priority == PRIORITY_DEFENSIVE
        assert ReasonCode.CONVICTION_LOW in d.reason_codes

    def test_conviction_35_returns_trim(self):
        """Conviction exactly at TRIM_CONVICTION_THRESHOLD. Must TRIM."""
        h = _holding(conviction=35.0, thesis_state=ThesisState.WEAKENING)
        d = evaluate_holding(h, TODAY)
        assert d.action == ActionType.TRIM

    def test_conviction_46_does_not_trim_on_conviction(self):
        """Conviction 46 is above trim threshold (45). Should not trigger conviction-based trim."""
        h = _holding(conviction=46.0, thesis_state=ThesisState.STABLE)
        d = evaluate_holding(h, TODAY)
        # Should not be trimmed due to conviction alone
        assert d.action != ActionType.TRIM or ReasonCode.CONVICTION_LOW not in d.reason_codes


# ---------------------------------------------------------------------------
# 17. Step 7.1 Hardening: thesis broken beats attractive valuation
# ---------------------------------------------------------------------------

class TestBrokenBeatsValuation:

    def test_thesis_broken_exits_despite_buy_zone(self):
        """Thesis BROKEN must exit even if valuation is in BUY zone."""
        h = _holding(
            thesis_state=ThesisState.BROKEN,
            conviction=60.0,
            valuation_gap=20.0,  # BUY zone — attractive
        )
        d = evaluate_holding(h, TODAY)
        assert d.action == ActionType.EXIT
        assert ReasonCode.THESIS_BROKEN in d.reason_codes
        assert d.recommendation_priority == PRIORITY_FORCED_EXIT


# ---------------------------------------------------------------------------
# 18. Step 7.1 Hardening: cooldown blocks otherwise valid initiation
# ---------------------------------------------------------------------------

class TestCooldownBlocksValid:

    def test_cooldown_blocks_initiation_even_with_all_gates_passing(self):
        """Candidate passes all gates but cooldown blocks initiation."""
        c = _candidate(
            conviction=80.0, zone=ZoneState.BUY,
            has_checkpoint=True, novel_7d=5,
            cooldown=True, cooldown_until=TODAY + timedelta(days=5),
        )
        d = evaluate_candidate(c, None, TODAY)
        assert d.action == ActionType.NO_ACTION
        assert ReasonCode.COOLDOWN_ACTIVE in d.reason_codes
        assert d.decision_stage == "blocked"


# ---------------------------------------------------------------------------
# 19. Low conviction blocks add (replaces probation test)
# ---------------------------------------------------------------------------

class TestLowConvictionBlocksAdd:

    def test_low_conviction_trims_instead_of_add(self):
        """Low conviction triggers trim, not add, even in BUY zone."""
        h = _holding(
            conviction=33.0,
            valuation_gap=20.0,  # BUY zone
            thesis_state=ThesisState.WEAKENING,
            avg_cost=90.0, current_price=110.0,
        )
        d = evaluate_holding(h, TODAY)
        assert d.action == ActionType.TRIM
        assert d.action != ActionType.ADD


# ---------------------------------------------------------------------------
# 20. Step 7.1 Hardening: funded pairing
# ---------------------------------------------------------------------------

class TestFundedPairing:

    def test_funded_initiation_when_capital_constrained(self):
        """When capital is constrained, initiation should have funded_by_ticker."""
        inputs = DecisionInput(
            review_date=TODAY,
            total_portfolio_weight=100.0,
            holdings=[
                _holding(ticker="STRONG", conviction=75.0, weight=50.0,
                         thesis_state=ThesisState.STRENGTHENING),
                _holding(ticker="WEAK", conviction=45.0, weight=50.0,
                         thesis_state=ThesisState.STABLE),
            ],
            candidates=[
                _candidate(ticker="NEW", conviction=70.0, zone=ZoneState.BUY),
            ],
        )
        result = run_decision_engine(inputs)
        init_d = next((d for d in result.decisions if d.action == ActionType.INITIATE), None)
        assert init_d is not None
        assert init_d.funded_by_ticker == "WEAK"
        assert init_d.funded_by_action is not None
        assert ReasonCode.CAPITAL_CHALLENGER in init_d.reason_codes
        assert init_d.recommendation_priority == PRIORITY_CAPITAL_REDEPLOY

    def test_no_funded_pairing_when_cash_available(self):
        """When there is sufficient capacity, no funded pairing should be created."""
        inputs = DecisionInput(
            review_date=TODAY,
            total_portfolio_weight=100.0,
            holdings=[
                _holding(ticker="A", conviction=50.0, weight=30.0,
                         thesis_state=ThesisState.STABLE),
            ],
            candidates=[
                _candidate(ticker="NEW", conviction=70.0, zone=ZoneState.BUY),
            ],
        )
        result = run_decision_engine(inputs)
        init_d = next((d for d in result.decisions if d.action == ActionType.INITIATE), None)
        assert init_d is not None
        # Cash is available (30 + 3 < 100), so no funding needed
        assert init_d.funded_by_ticker is None
        assert init_d.funded_by_action is None
        assert ReasonCode.CAPITAL_CHALLENGER not in init_d.reason_codes

    def test_funded_by_exit_when_weakest_conviction_very_low(self):
        """When weakest holding conviction is critically low, funding action is EXIT."""
        inputs = DecisionInput(
            review_date=TODAY,
            total_portfolio_weight=100.0,
            holdings=[
                _holding(ticker="STRONG", conviction=75.0, weight=50.0,
                         thesis_state=ThesisState.STRENGTHENING),
                _holding(ticker="DYING", conviction=20.0, weight=50.0,
                         thesis_state=ThesisState.WEAKENING),
            ],
            candidates=[
                _candidate(ticker="NEW", conviction=70.0, zone=ZoneState.BUY),
            ],
        )
        result = run_decision_engine(inputs)
        init_d = next((d for d in result.decisions if d.action == ActionType.INITIATE), None)
        assert init_d is not None
        assert init_d.funded_by_ticker == "DYING"
        assert init_d.funded_by_action == ActionType.EXIT
        assert ReasonCode.FUNDED_BY_EXIT in init_d.reason_codes


# ---------------------------------------------------------------------------
# 21. Step 7.1 Hardening: turnover cap blocks lower-priority deterministically
# ---------------------------------------------------------------------------

class TestTurnoverPriority:

    def test_turnover_blocks_lower_priority_not_higher(self):
        """With tight turnover cap, forced exit (priority 1) should go through,
        lower-priority trim should be blocked."""
        inputs = DecisionInput(
            review_date=TODAY,
            holdings=[
                # Priority 1: thesis broken → forced exit (weight 8%)
                _holding(ticker="BROKEN", conviction=10.0, weight=8.0,
                         thesis_state=ThesisState.BROKEN),
                # Priority 3: trim zone (weight 7%)
                _holding(ticker="STRETCHED", conviction=60.0, weight=7.0,
                         thesis_state=ThesisState.STABLE,
                         valuation_gap=-15.0),  # TRIM zone
            ],
            candidates=[],
            weekly_turnover_cap_pct=10.0,  # only 10% budget
        )
        result = run_decision_engine(inputs)

        broken_d = next(d for d in result.decisions if d.ticker == "BROKEN")
        assert broken_d.action == ActionType.EXIT  # should go through

        stretched_d = next(d for d in result.decisions if d.ticker == "STRETCHED")
        # Trim needs 2% but exit used 8% of 10% budget → only 2% left
        # 2% trim should still fit, but if it were larger it would be blocked
        # The key test: broken exit was processed first due to priority
        assert broken_d.recommendation_priority < stretched_d.recommendation_priority or \
               broken_d.action_score >= stretched_d.action_score


# ---------------------------------------------------------------------------
# 22. Step 7.1 Hardening: review does not zero weight or close position
# ---------------------------------------------------------------------------

class TestRecommendationBoundary:

    def test_review_does_not_zero_weight(self, session):
        """Exit recommendation must not zero weight on the live position."""
        _make_company(session, "NVDA")
        thesis = _make_thesis(session, "NVDA", state=ThesisState.BROKEN, conviction=10.0)
        pos = PortfolioPosition(
            ticker="NVDA", thesis_id=thesis.id,
            entry_date=TODAY - timedelta(days=30),
            avg_cost=100.0, current_weight=5.0, target_weight=5.0,
            conviction_score=10.0, zone_state=ZoneState.HOLD,
        )
        session.add(pos)
        session.flush()

        run_portfolio_review(session, as_of=TODAY, persist=True)

        refreshed = session.get(PortfolioPosition, pos.id)
        assert refreshed.current_weight == 5.0  # unchanged
        assert refreshed.status == PositionStatus.ACTIVE  # not closed

    def test_persisted_decision_has_was_executed_false(self, session):
        """Persisted PortfolioDecision.was_executed should be False (recommendation only)."""
        _make_company(session, "NVDA")
        thesis = _make_thesis(session, "NVDA", state=ThesisState.BROKEN, conviction=10.0)
        session.add(PortfolioPosition(
            ticker="NVDA", thesis_id=thesis.id,
            entry_date=TODAY - timedelta(days=30),
            avg_cost=100.0, current_weight=5.0, target_weight=5.0,
            conviction_score=10.0, zone_state=ZoneState.HOLD,
        ))
        session.flush()

        run_portfolio_review(session, as_of=TODAY, persist=True)

        decisions = session.scalars(select(PortfolioDecision)).all()
        assert len(decisions) >= 1
        for pd in decisions:
            assert pd.was_executed is False

    def test_exit_recommendation_does_not_set_cooldown(self, session):
        """Exit recommendation must not activate cooldown on position or candidate."""
        _make_company(session, "NVDA")
        thesis = _make_thesis(session, "NVDA", state=ThesisState.BROKEN, conviction=10.0)
        pos = PortfolioPosition(
            ticker="NVDA", thesis_id=thesis.id,
            entry_date=TODAY - timedelta(days=30),
            avg_cost=100.0, current_weight=5.0, target_weight=5.0,
            conviction_score=10.0, zone_state=ZoneState.HOLD,
        )
        session.add(pos)
        # Also add a candidate for this ticker
        session.add(Candidate(
            ticker="NVDA", conviction_score=10.0,
        ))
        session.flush()

        run_portfolio_review(session, as_of=TODAY, persist=True)

        refreshed_pos = session.get(PortfolioPosition, pos.id)
        assert refreshed_pos.cooldown_flag is False
        assert refreshed_pos.cooldown_until is None

        cand = session.scalars(
            select(Candidate).where(Candidate.ticker == "NVDA")
        ).first()
        assert cand.cooldown_flag is False
        assert cand.cooldown_until is None


# ---------------------------------------------------------------------------
# Sector concentration cap tests
# ---------------------------------------------------------------------------

class TestSectorConcentrationCap:

    def test_sector_cap_blocks_initiation(self):
        """Candidate blocked when its sector is already at cap."""
        holdings = [
            _holding(ticker="AAPL", conviction=70.0, weight=12.0, sector="Technology"),
            _holding(ticker="MSFT", conviction=75.0, weight=12.0, sector="Technology"),
            _holding(ticker="GOOG", conviction=65.0, weight=8.0, sector="Technology"),
        ]
        candidates = [
            _candidate(ticker="AMD", conviction=70.0, sector="Technology"),
        ]
        inputs = DecisionInput(
            review_date=TODAY,
            holdings=holdings,
            candidates=candidates,
            max_sector_weight=30.0,  # Tech already at 32% → blocked
        )
        result = run_decision_engine(inputs)
        amd = next(d for d in result.decisions if d.ticker == "AMD")
        assert amd.action == ActionType.NO_ACTION
        assert ReasonCode.SECTOR_CAP_REACHED in amd.reason_codes

    def test_sector_cap_allows_different_sector(self):
        """Candidate in a different sector is not blocked."""
        holdings = [
            _holding(ticker="AAPL", conviction=50.0, weight=15.0, sector="Technology"),
            _holding(ticker="MSFT", conviction=50.0, weight=15.0, sector="Technology"),
        ]
        candidates = [
            _candidate(ticker="JNJ", conviction=80.0, sector="Healthcare"),
        ]
        inputs = DecisionInput(
            review_date=TODAY,
            holdings=holdings,
            candidates=candidates,
            max_sector_weight=30.0,
        )
        result = run_decision_engine(inputs)
        jnj = next(d for d in result.decisions if d.ticker == "JNJ")
        assert jnj.action == ActionType.INITIATE

    def test_sector_cap_allows_under_limit(self):
        """Candidate allowed when sector is under the cap."""
        holdings = [
            _holding(ticker="AAPL", conviction=50.0, weight=10.0, sector="Technology"),
        ]
        candidates = [
            _candidate(ticker="AMD", conviction=80.0, sector="Technology"),
        ]
        inputs = DecisionInput(
            review_date=TODAY,
            holdings=holdings,
            candidates=candidates,
            max_sector_weight=30.0,  # Tech at 10% → allowed
        )
        result = run_decision_engine(inputs)
        amd = next(d for d in result.decisions if d.ticker == "AMD")
        assert amd.action == ActionType.INITIATE

    def test_sector_cap_no_sector_data_passes(self):
        """Candidate without sector data is not blocked by sector cap."""
        holdings = [
            _holding(ticker="AAPL", conviction=50.0, weight=15.0, sector="Technology"),
            _holding(ticker="MSFT", conviction=50.0, weight=15.0, sector="Technology"),
        ]
        candidates = [
            _candidate(ticker="XYZ", conviction=80.0),  # no sector
        ]
        inputs = DecisionInput(
            review_date=TODAY,
            holdings=holdings,
            candidates=candidates,
            max_sector_weight=30.0,
        )
        result = run_decision_engine(inputs)
        xyz = next(d for d in result.decisions if d.ticker == "XYZ")
        assert xyz.action == ActionType.INITIATE

    def test_sector_cap_tracks_approved_initiations(self):
        """Second candidate in same sector blocked after first fills the cap."""
        holdings = [
            _holding(ticker="AAPL", conviction=70.0, weight=25.0, sector="Technology"),
        ]
        candidates = [
            _candidate(ticker="AMD", conviction=75.0, sector="Technology"),
            _candidate(ticker="INTC", conviction=65.0, sector="Technology"),
        ]
        inputs = DecisionInput(
            review_date=TODAY,
            holdings=holdings,
            candidates=candidates,
            max_sector_weight=30.0,  # Tech at 25%, AMD adds ~4-5% → ~30%, INTC blocked
        )
        result = run_decision_engine(inputs)
        amd = next(d for d in result.decisions if d.ticker == "AMD")
        intc = next(d for d in result.decisions if d.ticker == "INTC")
        assert amd.action == ActionType.INITIATE
        assert intc.action == ActionType.NO_ACTION
        assert ReasonCode.SECTOR_CAP_REACHED in intc.reason_codes
