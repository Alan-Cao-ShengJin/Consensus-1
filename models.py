from __future__ import annotations

from datetime import datetime, date
from enum import Enum
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ---------- Enums ----------

class SourceType(str, Enum):
    NEWS = "news"
    TEN_K = "10K"
    TEN_Q = "10Q"
    EIGHT_K = "8K"
    EARNINGS_TRANSCRIPT = "earnings_transcript"
    INVESTOR_PRESENTATION = "investor_presentation"
    PRESS_RELEASE = "press_release"
    POLICY_DOCUMENT = "policy_document"
    BROKER_REPORT = "broker_report"


class SourceTier(str, Enum):
    TIER_1 = "tier_1"   # primary source
    TIER_2 = "tier_2"   # reputable secondary
    TIER_3 = "tier_3"   # weaker commentary


class ClaimType(str, Enum):
    DEMAND = "demand"
    PRICING = "pricing"
    MARGIN = "margin"
    CAPACITY = "capacity"
    GUIDANCE = "guidance"
    REGULATION = "regulation"
    COMPETITION = "competition"
    CAPITAL_ALLOCATION = "capital_allocation"
    INVENTORY = "inventory"
    CUSTOMER_BEHAVIOR = "customer_behavior"
    SUPPLY_CHAIN = "supply_chain"


class EconomicChannel(str, Enum):
    REVENUE = "revenue"
    GROSS_MARGIN = "gross_margin"
    OPEX = "opex"
    EARNINGS = "earnings"
    MULTIPLE = "multiple"
    SENTIMENT = "sentiment"
    LIQUIDITY = "liquidity"
    TIMING = "timing"


class Direction(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    MIXED = "mixed"
    NEUTRAL = "neutral"


class NoveltyType(str, Enum):
    NEW = "new"
    CONFIRMING = "confirming"
    CONFLICTING = "conflicting"
    REPETITIVE = "repetitive"


class ThesisState(str, Enum):
    FORMING = "forming"
    STRENGTHENING = "strengthening"
    STABLE = "stable"
    WEAKENING = "weakening"
    BROKEN = "broken"
    ACHIEVED = "achieved"
    PROBATION = "probation"


class ZoneState(str, Enum):
    BUY = "buy"
    HOLD = "hold"
    TRIM = "trim"
    FULL_EXIT = "full_exit"


class PositionStatus(str, Enum):
    ACTIVE = "active"
    CLOSED = "closed"


# ---------- Core Tables ----------

class Company(Base):
    __tablename__ = "companies"

    ticker: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sector: Mapped[Optional[str]] = mapped_column(String(100))
    industry: Mapped[Optional[str]] = mapped_column(String(100))
    subindustry: Mapped[Optional[str]] = mapped_column(String(100))
    country: Mapped[Optional[str]] = mapped_column(String(50))
    market_cap_bucket: Mapped[Optional[str]] = mapped_column(String(50))
    primary_exchange: Mapped[Optional[str]] = mapped_column(String(50))
    status_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    documents = relationship("Document", back_populates="primary_company")
    theses = relationship("Thesis", back_populates="company")


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("url", name="uq_documents_url"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_type: Mapped[SourceType] = mapped_column(SAEnum(SourceType), nullable=False)
    publisher: Mapped[Optional[str]] = mapped_column(String(255))
    source_tier: Mapped[SourceTier] = mapped_column(SAEnum(SourceTier), nullable=False)
    url: Mapped[Optional[str]] = mapped_column(Text)
    title: Mapped[Optional[str]] = mapped_column(Text)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, index=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    primary_company_ticker: Mapped[Optional[str]] = mapped_column(ForeignKey("companies.ticker"))
    document_type: Mapped[Optional[str]] = mapped_column(String(100))
    hash: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    language: Mapped[Optional[str]] = mapped_column(String(20))
    raw_text: Mapped[Optional[str]] = mapped_column(Text)

    primary_company = relationship("Company", back_populates="documents")
    claims = relationship("Claim", back_populates="document", cascade="all, delete-orphan")


class Theme(Base):
    __tablename__ = "themes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    theme_name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    theme_type: Mapped[Optional[str]] = mapped_column(String(100))
    description: Mapped[Optional[str]] = mapped_column(Text)
    status_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class PeerGroup(Base):
    __tablename__ = "peer_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    region: Mapped[Optional[str]] = mapped_column(String(50))
    sector: Mapped[Optional[str]] = mapped_column(String(100))
    multiple_basis: Mapped[Optional[str]] = mapped_column(String(50))
    status_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), nullable=False, index=True)

    claim_text_normalized: Mapped[str] = mapped_column(Text, nullable=False)
    claim_text_short: Mapped[Optional[str]] = mapped_column(Text)

    claim_type: Mapped[ClaimType] = mapped_column(SAEnum(ClaimType), nullable=False)
    economic_channel: Mapped[EconomicChannel] = mapped_column(SAEnum(EconomicChannel), nullable=False)
    direction: Mapped[Direction] = mapped_column(SAEnum(Direction), nullable=False)
    strength: Mapped[Optional[float]] = mapped_column(Float)   # 0-1
    time_horizon: Mapped[Optional[str]] = mapped_column(String(50))
    novelty_type: Mapped[NoveltyType] = mapped_column(SAEnum(NoveltyType), nullable=False)
    confidence: Mapped[Optional[float]] = mapped_column(Float)  # 0-1

    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, index=True)
    valid_from: Mapped[Optional[datetime]] = mapped_column(DateTime)
    valid_to: Mapped[Optional[datetime]] = mapped_column(DateTime)
    is_structural: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_ephemeral: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    document = relationship("Document", back_populates="claims")


class Checkpoint(Base):
    __tablename__ = "checkpoints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    checkpoint_type: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    date_expected: Mapped[Optional[date]] = mapped_column(Date)
    importance: Mapped[Optional[float]] = mapped_column(Float)  # 0-1
    linked_company_ticker: Mapped[Optional[str]] = mapped_column(ForeignKey("companies.ticker"))
    status: Mapped[Optional[str]] = mapped_column(String(50))


class Thesis(Base):
    __tablename__ = "theses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    company_ticker: Mapped[str] = mapped_column(ForeignKey("companies.ticker"), nullable=False, index=True)
    thesis_type: Mapped[Optional[str]] = mapped_column(String(100))
    summary: Mapped[Optional[str]] = mapped_column(Text)
    state: Mapped[ThesisState] = mapped_column(SAEnum(ThesisState), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    start_date: Mapped[Optional[date]] = mapped_column(Date)
    expiry_review_date: Mapped[Optional[date]] = mapped_column(Date)
    expected_horizon_days: Mapped[Optional[int]] = mapped_column(Integer)

    peer_group_current_id: Mapped[Optional[int]] = mapped_column(ForeignKey("peer_groups.id"))
    peer_group_target_id: Mapped[Optional[int]] = mapped_column(ForeignKey("peer_groups.id"))

    base_case_rerating: Mapped[Optional[float]] = mapped_column(Float)
    bull_case_rerating: Mapped[Optional[float]] = mapped_column(Float)
    bear_case_rerating: Mapped[Optional[float]] = mapped_column(Float)

    checkpoint_next_id: Mapped[Optional[int]] = mapped_column(ForeignKey("checkpoints.id"))
    conviction_score: Mapped[Optional[float]] = mapped_column(Float, index=True)  # 0-100
    valuation_gap_pct: Mapped[Optional[float]] = mapped_column(Float)
    downside_risk_score: Mapped[Optional[float]] = mapped_column(Float)
    status_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    company = relationship("Company", back_populates="theses")


class ThesisStateHistory(Base):
    __tablename__ = "thesis_state_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thesis_id: Mapped[int] = mapped_column(ForeignKey("theses.id"), nullable=False, index=True)
    state: Mapped[ThesisState] = mapped_column(SAEnum(ThesisState), nullable=False)
    conviction_score: Mapped[Optional[float]] = mapped_column(Float)
    note: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class PortfolioPosition(Base):
    __tablename__ = "portfolio_positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(ForeignKey("companies.ticker"), nullable=False, index=True)
    thesis_id: Mapped[int] = mapped_column(ForeignKey("theses.id"), nullable=False, index=True)

    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    avg_cost: Mapped[float] = mapped_column(Float, nullable=False)
    current_weight: Mapped[float] = mapped_column(Float, nullable=False)
    target_weight: Mapped[float] = mapped_column(Float, nullable=False)
    conviction_score: Mapped[float] = mapped_column(Float, nullable=False)
    zone_state: Mapped[ZoneState] = mapped_column(SAEnum(ZoneState), nullable=False)

    status: Mapped[PositionStatus] = mapped_column(SAEnum(PositionStatus), default=PositionStatus.ACTIVE, nullable=False)
    probation_flag: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    cooldown_flag: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    hold_through_earnings_allowed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    take_profit_zone_low: Mapped[Optional[float]] = mapped_column(Float)
    hold_zone_low: Mapped[Optional[float]] = mapped_column(Float)
    trim_zone_low: Mapped[Optional[float]] = mapped_column(Float)
    full_exit_zone_low: Mapped[Optional[float]] = mapped_column(Float)


class Candidate(Base):
    __tablename__ = "candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(ForeignKey("companies.ticker"), nullable=False, index=True)
    primary_thesis_id: Mapped[Optional[int]] = mapped_column(ForeignKey("theses.id"))
    conviction_score: Mapped[Optional[float]] = mapped_column(Float)
    buyable_flag: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    zone_state: Mapped[Optional[ZoneState]] = mapped_column(SAEnum(ZoneState))
    watch_reason: Mapped[Optional[str]] = mapped_column(Text)
    last_reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    cooldown_flag: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


# ---------- Link Tables ----------

class ClaimCompanyLink(Base):
    __tablename__ = "claim_company_links"
    __table_args__ = (UniqueConstraint("claim_id", "company_ticker", name="uq_claim_company"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id"), nullable=False, index=True)
    company_ticker: Mapped[str] = mapped_column(ForeignKey("companies.ticker"), nullable=False, index=True)
    relation_type: Mapped[str] = mapped_column(String(50), nullable=False)  # about / affects / peer / supplier / customer


class ClaimThemeLink(Base):
    __tablename__ = "claim_theme_links"
    __table_args__ = (UniqueConstraint("claim_id", "theme_id", name="uq_claim_theme"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id"), nullable=False, index=True)
    theme_id: Mapped[int] = mapped_column(ForeignKey("themes.id"), nullable=False, index=True)


class ThesisClaimLink(Base):
    __tablename__ = "thesis_claim_links"
    __table_args__ = (UniqueConstraint("thesis_id", "claim_id", name="uq_thesis_claim"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thesis_id: Mapped[int] = mapped_column(ForeignKey("theses.id"), nullable=False, index=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id"), nullable=False, index=True)
    link_type: Mapped[str] = mapped_column(String(50), nullable=False)  # supports / weakens / checkpoint / context


class ThesisThemeLink(Base):
    __tablename__ = "thesis_theme_links"
    __table_args__ = (UniqueConstraint("thesis_id", "theme_id", name="uq_thesis_theme"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thesis_id: Mapped[int] = mapped_column(ForeignKey("theses.id"), nullable=False, index=True)
    theme_id: Mapped[int] = mapped_column(ForeignKey("themes.id"), nullable=False, index=True)


class CompanyPeerGroupLink(Base):
    __tablename__ = "company_peer_group_links"
    __table_args__ = (UniqueConstraint("company_ticker", "peer_group_id", name="uq_company_peergroup"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_ticker: Mapped[str] = mapped_column(ForeignKey("companies.ticker"), nullable=False, index=True)
    peer_group_id: Mapped[int] = mapped_column(ForeignKey("peer_groups.id"), nullable=False, index=True)
    role: Mapped[Optional[str]] = mapped_column(String(50))  # current / target / alt