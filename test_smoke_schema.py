"""Smoke test: create one of each core entity and verify relationships."""
import pytest
from datetime import datetime, date

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from models import (
    Base, Company, Document, Claim, Theme, Thesis, Checkpoint, PeerGroup,
    PortfolioPosition, Candidate, ThesisStateHistory,
    ClaimCompanyLink, ClaimThemeLink, ThesisClaimLink, ThesisThemeLink,
    CompanyPeerGroupLink,
    SourceType, SourceTier, ClaimType, EconomicChannel, Direction,
    NoveltyType, ThesisState, ZoneState, PositionStatus,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_full_schema_smoke(session):
    # 1. Company
    company = Company(ticker="NVDA", name="NVIDIA Corp")
    session.add(company)
    session.flush()

    # 2. Document linked to company
    doc = Document(
        source_type=SourceType.EARNINGS_TRANSCRIPT,
        source_tier=SourceTier.TIER_1,
        title="NVDA Q4 2025 Earnings Call",
        published_at=datetime(2025, 2, 26),
        primary_company_ticker="NVDA",
    )
    session.add(doc)
    session.flush()

    # 3. Claim linked to document
    claim = Claim(
        document_id=doc.id,
        claim_text_normalized="Data-center revenue grew 93% YoY",
        claim_text_short="DC rev +93%",
        claim_type=ClaimType.DEMAND,
        economic_channel=EconomicChannel.REVENUE,
        direction=Direction.POSITIVE,
        strength=0.9,
        novelty_type=NoveltyType.NEW,
        confidence=0.95,
        published_at=datetime(2025, 2, 26),
    )
    session.add(claim)
    session.flush()

    # 4. Theme
    theme = Theme(theme_name="AI Capex Cycle")
    session.add(theme)
    session.flush()

    # 5. Checkpoint
    checkpoint = Checkpoint(
        checkpoint_type="earnings",
        name="NVDA Q1 2026 Earnings",
        date_expected=date(2025, 5, 28),
        importance=0.9,
        linked_company_ticker="NVDA",
    )
    session.add(checkpoint)
    session.flush()

    # 6. PeerGroup
    peer_group = PeerGroup(name="US Semis", sector="Semiconductors")
    session.add(peer_group)
    session.flush()

    # 7. Thesis
    thesis = Thesis(
        title="NVDA AI Capex Supercycle",
        company_ticker="NVDA",
        state=ThesisState.FORMING,
        conviction_score=55.0,
        checkpoint_next_id=checkpoint.id,
        peer_group_current_id=peer_group.id,
    )
    session.add(thesis)
    session.flush()

    # 8. ClaimCompanyLink
    session.add(ClaimCompanyLink(
        claim_id=claim.id, company_ticker="NVDA", relation_type="about",
    ))
    session.flush()

    # 9. ClaimThemeLink
    session.add(ClaimThemeLink(claim_id=claim.id, theme_id=theme.id))
    session.flush()

    # 10. ThesisClaimLink
    session.add(ThesisClaimLink(
        thesis_id=thesis.id, claim_id=claim.id, link_type="supports",
    ))
    session.flush()

    # 11. ThesisThemeLink
    session.add(ThesisThemeLink(thesis_id=thesis.id, theme_id=theme.id))
    session.flush()

    # 12. CompanyPeerGroupLink
    session.add(CompanyPeerGroupLink(
        company_ticker="NVDA", peer_group_id=peer_group.id, role="current",
    ))
    session.flush()

    # 13. ThesisStateHistory
    session.add(ThesisStateHistory(
        thesis_id=thesis.id,
        state=ThesisState.FORMING,
        conviction_score=55.0,
        note="Initial thesis creation",
    ))
    session.flush()

    # 14. PortfolioPosition
    position = PortfolioPosition(
        ticker="NVDA",
        thesis_id=thesis.id,
        entry_date=date(2025, 1, 10),
        avg_cost=120.50,
        current_weight=0.05,
        target_weight=0.08,
        conviction_score=55.0,
        zone_state=ZoneState.BUY,
    )
    session.add(position)
    session.flush()

    # 15. Candidate
    candidate = Candidate(
        ticker="NVDA",
        primary_thesis_id=thesis.id,
        conviction_score=55.0,
        buyable_flag=True,
        zone_state=ZoneState.BUY,
    )
    session.add(candidate)
    session.flush()

    session.commit()

    # ---- Verify all inserts ----
    assert session.get(Company, "NVDA") is not None
    assert session.get(Document, doc.id).primary_company_ticker == "NVDA"
    assert session.get(Claim, claim.id).document_id == doc.id
    assert session.get(Theme, theme.id).theme_name == "AI Capex Cycle"
    assert session.get(Checkpoint, checkpoint.id).linked_company_ticker == "NVDA"
    assert session.get(PeerGroup, peer_group.id).name == "US Semis"
    assert session.get(Thesis, thesis.id).company_ticker == "NVDA"

    # Verify relationships
    loaded_doc = session.get(Document, doc.id)
    assert loaded_doc.primary_company.ticker == "NVDA"
    assert len(loaded_doc.claims) == 1

    loaded_thesis = session.get(Thesis, thesis.id)
    assert loaded_thesis.company.ticker == "NVDA"

    # Verify link tables
    assert session.scalar(select(ClaimCompanyLink)).company_ticker == "NVDA"
    assert session.scalar(select(ClaimThemeLink)).theme_id == theme.id
    assert session.scalar(select(ThesisClaimLink)).link_type == "supports"
    assert session.scalar(select(ThesisThemeLink)).theme_id == theme.id
    assert session.scalar(select(CompanyPeerGroupLink)).role == "current"
    assert session.scalar(select(ThesisStateHistory)).thesis_id == thesis.id

    # Verify position and candidate
    assert session.get(PortfolioPosition, position.id).zone_state == ZoneState.BUY
    assert session.get(Candidate, candidate.id).buyable_flag is True
