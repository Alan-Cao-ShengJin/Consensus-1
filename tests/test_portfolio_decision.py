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
    PROBATION_MAX_REVIEWS, COOLDOWN_DAYS,
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
    )


def _candidate(
    ticker="AMD", conviction=65.0,
    thesis_state=ThesisState.STRENGTHENING,
    zone=ZoneState.BUY,
    has_checkpoint=True, novel_7d=2, confirming_7d=1,
    cooldown=False, cooldown_until=None,
    valuation_gap=15.0, base_case=1.3,
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

    def test_bad_valuation_blocks_initiation(self):
        c = _candidate(zone=ZoneState.HOLD, valuation_gap=-3.0)
        d = evaluate_candidate(c, None, TODAY)
        assert d.action == ActionType.NO_ACTION

    def test_no_checkpoint_blocks_initiation(self):
        c = _candidate(has_checkpoint=False)
        d = evaluate_candidate(c, None, TODAY)
        assert d.action == ActionType.NO_ACTION
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
# 7. Probation blocks adds
# ---------------------------------------------------------------------------

class TestProbation:

    def test_probation_blocks_adds(self):
        h = _holding(
            conviction=33.0, probation=True, probation_reviews=0,
            valuation_gap=15.0,  # would be BUY
        )
        d = evaluate_holding(h, TODAY)
        assert d.action == ActionType.PROBATION
        assert ReasonCode.PROBATION_ACTIVE in d.reason_codes

    def test_low_conviction_enters_probation(self):
        h = _holding(conviction=33.0, thesis_state=ThesisState.WEAKENING)
        d = evaluate_holding(h, TODAY)
        assert d.action == ActionType.PROBATION
        assert ReasonCode.CONVICTION_LOW in d.reason_codes


# ---------------------------------------------------------------------------
# 8. Probation expiry triggers exit after two reviews
# ---------------------------------------------------------------------------

class TestProbationExpiry:

    def test_probation_expired_forces_exit(self):
        h = _holding(
            conviction=30.0, probation=True,
            probation_reviews=PROBATION_MAX_REVIEWS,
        )
        d = evaluate_holding(h, TODAY)
        assert d.action == ActionType.EXIT
        assert ReasonCode.PROBATION_EXPIRED in d.reason_codes

    def test_probation_not_yet_expired(self):
        h = _holding(
            conviction=33.0, probation=True,
            probation_reviews=1,
        )
        d = evaluate_holding(h, TODAY)
        assert d.action == ActionType.PROBATION
        assert d.action != ActionType.EXIT


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

        # WEAK should be probation
        weak_d = next(d for d in result.decisions if d.ticker == "WEAK")
        assert weak_d.action == ActionType.PROBATION

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

    def test_exit_sets_cooldown_on_position(self, session):
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
        assert refreshed.status == PositionStatus.CLOSED
        assert refreshed.cooldown_flag is True
        assert refreshed.cooldown_until is not None
        assert refreshed.exit_date == TODAY

    def test_probation_entry_sets_flags(self, session):
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

        run_portfolio_review(session, as_of=TODAY, persist=True)

        refreshed = session.get(PortfolioPosition, pos.id)
        assert refreshed.probation_flag is True
        assert refreshed.probation_start_date == TODAY
        assert refreshed.probation_reviews_count == 0


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
