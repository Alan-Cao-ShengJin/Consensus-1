"""Deterministic demo fixtures for the operator console.

Seeds an in-memory SQLite database with realistic sample data so that
`--demo` mode has something to display even when the real DB is empty.

All data is synthetic but structurally valid — every visible value maps
to a real persisted object, maintaining the glass-box constraint.
"""
from __future__ import annotations

import json
from datetime import datetime, date, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from models import (
    Base, Company, Document, Claim, Theme, Thesis, ThesisStateHistory,
    PortfolioPosition, Candidate, PortfolioReview, PortfolioDecision,
    ClaimCompanyLink, ClaimThemeLink, ThesisClaimLink,
    SourceType, SourceTier, ClaimType, EconomicChannel, Direction,
    NoveltyType, ThesisState, ZoneState, PositionStatus, ActionType,
)


def create_demo_session_factory():
    """Create an in-memory SQLite engine + session factory with demo data seeded.

    Returns (engine, SessionFactory) so the caller can swap get_session.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionFactory = sessionmaker(bind=engine)

    session = SessionFactory()
    seed_demo_fixtures(session)
    session.commit()
    session.close()

    return engine, SessionFactory


def seed_demo_fixtures(session: Session) -> None:
    """Seed deterministic demo data into the given session."""

    # ---- Companies ----
    session.add(Company(ticker="NVDA", name="NVIDIA Corp", sector="Technology",
                        industry="Semiconductors", market_cap_bucket="mega"))
    session.add(Company(ticker="MSFT", name="Microsoft Corp", sector="Technology",
                        industry="Software", market_cap_bucket="mega"))
    session.add(Company(ticker="TSLA", name="Tesla Inc", sector="Consumer Discretionary",
                        industry="Automobiles", market_cap_bucket="mega"))
    session.flush()

    # ---- Themes ----
    t1 = Theme(id=1, theme_name="AI Accelerators", theme_type="secular",
               description="GPU/AI chip demand cycle", status_active=True)
    t2 = Theme(id=2, theme_name="Cloud Infrastructure", theme_type="secular",
               description="Hyperscaler capex and cloud adoption", status_active=True)
    t3 = Theme(id=3, theme_name="EV Adoption", theme_type="cyclical",
               description="Electric vehicle penetration rates", status_active=True)
    session.add_all([t1, t2, t3])
    session.flush()

    # ---- Base dates ----
    now = datetime.utcnow()
    d1_pub = now - timedelta(hours=6)
    d2_pub = now - timedelta(hours=3)
    d3_pub = now - timedelta(hours=1)
    d4_pub = now - timedelta(minutes=30)
    d5_pub = now - timedelta(minutes=10)

    # ---- Documents ----
    docs = [
        Document(id=1, source_type=SourceType.EIGHT_K, source_tier=SourceTier.TIER_1,
                 title="NVIDIA Q4 2025 8-K Filing", publisher="SEC",
                 published_at=d1_pub, ingested_at=d1_pub + timedelta(minutes=5),
                 primary_company_ticker="NVDA", document_type="8K"),
        Document(id=2, source_type=SourceType.EARNINGS_TRANSCRIPT, source_tier=SourceTier.TIER_1,
                 title="NVIDIA Q4 2025 Earnings Call Transcript", publisher="NVDA IR",
                 published_at=d2_pub, ingested_at=d2_pub + timedelta(minutes=3),
                 primary_company_ticker="NVDA", document_type="earnings_transcript"),
        Document(id=3, source_type=SourceType.BROKER_REPORT, source_tier=SourceTier.TIER_2,
                 title="Morgan Stanley: NVDA Raises Price Target to $180", publisher="Morgan Stanley",
                 published_at=d3_pub, ingested_at=d3_pub + timedelta(minutes=2),
                 primary_company_ticker="NVDA", document_type="broker_report"),
        Document(id=4, source_type=SourceType.PRESS_RELEASE, source_tier=SourceTier.TIER_1,
                 title="Microsoft Azure AI Revenue Surpasses $10B Run Rate", publisher="MSFT IR",
                 published_at=d4_pub, ingested_at=d4_pub + timedelta(minutes=1),
                 primary_company_ticker="MSFT", document_type="press_release"),
        Document(id=5, source_type=SourceType.NEWS, source_tier=SourceTier.TIER_3,
                 title="Tesla Q1 Deliveries Miss Estimates by 8%", publisher="Reuters",
                 published_at=d5_pub, ingested_at=d5_pub + timedelta(seconds=30),
                 primary_company_ticker="TSLA", document_type="news"),
    ]
    session.add_all(docs)
    session.flush()

    # ---- Claims ----
    claims = [
        # Doc 1 claims (NVDA 8-K)
        Claim(id=1, document_id=1,
              claim_text_normalized="Data center revenue grew 40% YoY driven by AI training demand",
              claim_text_short="DC revenue +40% YoY",
              claim_type=ClaimType.DEMAND, economic_channel=EconomicChannel.REVENUE,
              direction=Direction.POSITIVE, strength=0.85,
              novelty_type=NoveltyType.NEW, confidence=0.9,
              published_at=d1_pub),
        Claim(id=2, document_id=1,
              claim_text_normalized="Gross margin expanded to 76% on favorable product mix",
              claim_text_short="Gross margin 76%",
              claim_type=ClaimType.MARGIN, economic_channel=EconomicChannel.GROSS_MARGIN,
              direction=Direction.POSITIVE, strength=0.7,
              novelty_type=NoveltyType.CONFIRMING, confidence=0.85,
              published_at=d1_pub),

        # Doc 2 claims (NVDA earnings call)
        Claim(id=3, document_id=2,
              claim_text_normalized="Management guided next quarter revenue $28B vs consensus $26B",
              claim_text_short="Revenue guide $28B vs $26B consensus",
              claim_type=ClaimType.GUIDANCE, economic_channel=EconomicChannel.REVENUE,
              direction=Direction.POSITIVE, strength=0.9,
              novelty_type=NoveltyType.NEW, confidence=0.95,
              published_at=d2_pub),
        Claim(id=4, document_id=2,
              claim_text_normalized="Blackwell GPU capacity constrained through mid-2026",
              claim_text_short="Blackwell supply-constrained through mid-2026",
              claim_type=ClaimType.CAPACITY, economic_channel=EconomicChannel.REVENUE,
              direction=Direction.POSITIVE, strength=0.8,
              novelty_type=NoveltyType.NEW, confidence=0.88,
              published_at=d2_pub),

        # Doc 3 claims (broker report)
        Claim(id=5, document_id=3,
              claim_text_normalized="Morgan Stanley raises NVDA PT to $180 citing AI spending cycle",
              claim_text_short="MS raises PT to $180",
              claim_type=ClaimType.DEMAND, economic_channel=EconomicChannel.MULTIPLE,
              direction=Direction.POSITIVE, strength=0.6,
              novelty_type=NoveltyType.CONFIRMING, confidence=0.7,
              published_at=d3_pub),

        # Doc 4 claims (MSFT)
        Claim(id=6, document_id=4,
              claim_text_normalized="Azure AI services revenue crossed $10B annualized run rate",
              claim_text_short="Azure AI $10B run rate",
              claim_type=ClaimType.DEMAND, economic_channel=EconomicChannel.REVENUE,
              direction=Direction.POSITIVE, strength=0.75,
              novelty_type=NoveltyType.NEW, confidence=0.92,
              published_at=d4_pub),
        Claim(id=7, document_id=4,
              claim_text_normalized="Cloud capex increasing 20% to support AI workloads",
              claim_text_short="Cloud capex +20% for AI",
              claim_type=ClaimType.CAPITAL_ALLOCATION, economic_channel=EconomicChannel.OPEX,
              direction=Direction.MIXED, strength=0.65,
              novelty_type=NoveltyType.NEW, confidence=0.85,
              published_at=d4_pub),

        # Doc 5 claims (TSLA)
        Claim(id=8, document_id=5,
              claim_text_normalized="Tesla Q1 deliveries 410K units vs 445K expected, down 8% vs estimate",
              claim_text_short="Q1 deliveries miss by 8%",
              claim_type=ClaimType.DEMAND, economic_channel=EconomicChannel.REVENUE,
              direction=Direction.NEGATIVE, strength=0.8,
              novelty_type=NoveltyType.NEW, confidence=0.95,
              published_at=d5_pub),
        Claim(id=9, document_id=5,
              claim_text_normalized="Pricing pressure intensifying in China EV market",
              claim_text_short="China EV pricing pressure",
              claim_type=ClaimType.PRICING, economic_channel=EconomicChannel.GROSS_MARGIN,
              direction=Direction.NEGATIVE, strength=0.7,
              novelty_type=NoveltyType.CONFIRMING, confidence=0.8,
              published_at=d5_pub),
    ]
    session.add_all(claims)
    session.flush()

    # ---- Claim-Company links ----
    company_links = [
        ClaimCompanyLink(claim_id=1, company_ticker="NVDA", relation_type="about"),
        ClaimCompanyLink(claim_id=2, company_ticker="NVDA", relation_type="about"),
        ClaimCompanyLink(claim_id=3, company_ticker="NVDA", relation_type="about"),
        ClaimCompanyLink(claim_id=4, company_ticker="NVDA", relation_type="about"),
        ClaimCompanyLink(claim_id=5, company_ticker="NVDA", relation_type="about"),
        ClaimCompanyLink(claim_id=6, company_ticker="MSFT", relation_type="about"),
        ClaimCompanyLink(claim_id=7, company_ticker="MSFT", relation_type="about"),
        ClaimCompanyLink(claim_id=8, company_ticker="TSLA", relation_type="about"),
        ClaimCompanyLink(claim_id=9, company_ticker="TSLA", relation_type="about"),
    ]
    session.add_all(company_links)
    session.flush()

    # ---- Claim-Theme links ----
    theme_links = [
        ClaimThemeLink(claim_id=1, theme_id=1),  # DC revenue -> AI Accelerators
        ClaimThemeLink(claim_id=3, theme_id=1),  # guidance -> AI Accelerators
        ClaimThemeLink(claim_id=4, theme_id=1),  # Blackwell -> AI Accelerators
        ClaimThemeLink(claim_id=5, theme_id=1),  # MS PT -> AI Accelerators
        ClaimThemeLink(claim_id=6, theme_id=2),  # Azure AI -> Cloud Infrastructure
        ClaimThemeLink(claim_id=7, theme_id=2),  # Cloud capex -> Cloud Infrastructure
        ClaimThemeLink(claim_id=8, theme_id=3),  # TSLA deliveries -> EV Adoption
        ClaimThemeLink(claim_id=9, theme_id=3),  # China pricing -> EV Adoption
    ]
    session.add_all(theme_links)
    session.flush()

    # ---- Theses ----
    thesis_base = now - timedelta(days=45)
    theses = [
        Thesis(id=1, title="NVIDIA AI dominance thesis",
               company_ticker="NVDA", thesis_type="growth",
               summary="GPU monopoly in AI training creates durable revenue growth",
               state=ThesisState.STRENGTHENING,
               conviction_score=72.0, valuation_gap_pct=15.0,
               base_case_rerating=25.0, status_active=True,
               created_at=thesis_base, updated_at=now - timedelta(hours=2)),
        Thesis(id=2, title="Microsoft cloud AI monetization",
               company_ticker="MSFT", thesis_type="growth",
               summary="Azure AI services driving next growth leg",
               state=ThesisState.FORMING,
               conviction_score=48.0, valuation_gap_pct=8.0,
               base_case_rerating=12.0, status_active=True,
               created_at=thesis_base + timedelta(days=10), updated_at=now - timedelta(minutes=25)),
        Thesis(id=3, title="Tesla delivery deceleration risk",
               company_ticker="TSLA", thesis_type="risk",
               summary="Demand weakness and pricing pressure eroding margins",
               state=ThesisState.WEAKENING,
               conviction_score=35.0, valuation_gap_pct=-10.0,
               base_case_rerating=-15.0, status_active=True,
               created_at=thesis_base + timedelta(days=20), updated_at=now - timedelta(minutes=8)),
    ]
    session.add_all(theses)
    session.flush()

    # ---- Thesis-Claim links ----
    tcl = [
        ThesisClaimLink(thesis_id=1, claim_id=1, link_type="supports"),
        ThesisClaimLink(thesis_id=1, claim_id=2, link_type="supports"),
        ThesisClaimLink(thesis_id=1, claim_id=3, link_type="supports"),
        ThesisClaimLink(thesis_id=1, claim_id=4, link_type="supports"),
        ThesisClaimLink(thesis_id=1, claim_id=5, link_type="supports"),
        ThesisClaimLink(thesis_id=2, claim_id=6, link_type="supports"),
        ThesisClaimLink(thesis_id=2, claim_id=7, link_type="context"),
        ThesisClaimLink(thesis_id=3, claim_id=8, link_type="weakens"),
        ThesisClaimLink(thesis_id=3, claim_id=9, link_type="weakens"),
    ]
    session.add_all(tcl)
    session.flush()

    # ---- Thesis State History ----
    history = [
        # NVDA: forming -> strengthening
        ThesisStateHistory(id=1, thesis_id=1, state=ThesisState.FORMING,
                          conviction_score=50.0, valuation_gap_pct=20.0,
                          note="Initial thesis formation",
                          created_at=thesis_base),
        ThesisStateHistory(id=2, thesis_id=1, state=ThesisState.STRENGTHENING,
                          conviction_score=72.0, valuation_gap_pct=15.0,
                          note="Q4 earnings confirmed DC demand",
                          created_at=now - timedelta(hours=2)),
        # MSFT: forming (single entry)
        ThesisStateHistory(id=3, thesis_id=2, state=ThesisState.FORMING,
                          conviction_score=48.0, valuation_gap_pct=8.0,
                          note="Azure AI revenue milestone",
                          created_at=now - timedelta(minutes=25)),
        # TSLA: stable -> weakening
        ThesisStateHistory(id=4, thesis_id=3, state=ThesisState.STABLE,
                          conviction_score=52.0, valuation_gap_pct=-5.0,
                          note="Holding steady pre-deliveries",
                          created_at=thesis_base + timedelta(days=20)),
        ThesisStateHistory(id=5, thesis_id=3, state=ThesisState.WEAKENING,
                          conviction_score=35.0, valuation_gap_pct=-10.0,
                          note="Q1 delivery miss triggers downgrade",
                          created_at=now - timedelta(minutes=8)),
    ]
    session.add_all(history)
    session.flush()

    # ---- Portfolio Positions ----
    session.add(PortfolioPosition(
        id=1, ticker="NVDA", thesis_id=1,
        entry_date=date.today() - timedelta(days=30), avg_cost=450.0,
        current_weight=8.0, target_weight=10.0,
        conviction_score=72.0, zone_state=ZoneState.BUY,
        status=PositionStatus.ACTIVE,
    ))
    session.add(PortfolioPosition(
        id=2, ticker="TSLA", thesis_id=3,
        entry_date=date.today() - timedelta(days=60), avg_cost=280.0,
        current_weight=5.0, target_weight=3.0,
        conviction_score=35.0, zone_state=ZoneState.TRIM,
        status=PositionStatus.ACTIVE,
    ))
    session.flush()

    # ---- Candidates ----
    session.add(Candidate(
        id=1, ticker="MSFT", primary_thesis_id=2,
        conviction_score=48.0, buyable_flag=True,
        zone_state=ZoneState.HOLD, watch_reason="Cloud AI thesis forming — watching for conviction threshold",
    ))
    session.flush()

    # ---- Portfolio Review + Decisions ----
    review = PortfolioReview(
        id=1, review_date=date.today(), review_type="weekly",
        holdings_reviewed=2, candidates_reviewed=1, turnover_pct=3.5,
        summary="NVDA add on thesis strengthening; TSLA trim on delivery miss; MSFT watchlist hold",
        created_at=now - timedelta(hours=1),
    )
    session.add(review)
    session.flush()

    decisions = [
        PortfolioDecision(
            id=1, review_id=1, ticker="NVDA",
            action=ActionType.ADD, action_score=75.0,
            target_weight_change=2.0, suggested_weight=10.0,
            reason_codes=json.dumps(["THESIS_STRENGTHENING", "VALUATION_ATTRACTIVE"]),
            rationale="Conviction increased on Q4 results; DC demand confirmed",
            was_executed=True,
            generated_at=now - timedelta(hours=1),
        ),
        PortfolioDecision(
            id=2, review_id=1, ticker="TSLA",
            action=ActionType.TRIM, action_score=62.0,
            target_weight_change=-2.0, suggested_weight=3.0,
            reason_codes=json.dumps(["THESIS_WEAKENING", "DELIVERY_MISS"]),
            rationale="Delivery miss and pricing pressure; reduce exposure",
            was_executed=True,
            generated_at=now - timedelta(hours=1),
        ),
        PortfolioDecision(
            id=3, review_id=1, ticker="MSFT",
            action=ActionType.NO_ACTION, action_score=10.0,
            reason_codes=json.dumps([]),
            rationale="Watchlist — thesis not yet at conviction threshold",
            was_executed=False,
            generated_at=now - timedelta(hours=1),
        ),
    ]
    session.add_all(decisions)
    session.flush()
