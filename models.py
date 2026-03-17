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
    THIRTEEN_F = "13f"


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


class ActionType(str, Enum):
    INITIATE = "initiate"
    ADD = "add"
    HOLD = "hold"
    TRIM = "trim"
    PROBATION = "probation"
    EXIT = "exit"
    NO_ACTION = "no_action"


class ValuationProvenance(str, Enum):
    """How a valuation-state value was obtained for ThesisStateHistory."""
    HISTORICAL_RECORDED = "historical_recorded"            # captured at thesis update time
    BACKFILLED_FROM_THESIS_SNAPSHOT = "backfilled_from_thesis_snapshot"  # from dated thesis state
    MISSING = "missing"                                     # no defensible source


class RelationshipType(str, Enum):
    """Types of direct company-to-company relationships."""
    SUPPLIER = "supplier"         # source supplies to target
    CUSTOMER = "customer"         # source is a customer of target
    COMPETITOR = "competitor"     # bidirectional competitive relationship
    ECOSYSTEM = "ecosystem"       # same ecosystem / platform dependency


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
    beta: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    documents = relationship("Document", back_populates="primary_company")
    theses = relationship("Thesis", back_populates="company")


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("url", name="uq_documents_url"),
        UniqueConstraint("source_key", "external_id", name="uq_source_external"),
    )

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
    source_key: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(255), index=True)

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

    # Provenance hardening (Step 13)
    source_excerpt: Mapped[Optional[str]] = mapped_column(Text)        # raw text span from document
    event_cluster_id: Mapped[Optional[str]] = mapped_column(String(100), index=True)  # event dedup cluster

    # Contradiction tracking (Step 13.1)
    is_contradicted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    contradicts_claim_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)  # claim this contradicts

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
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class Price(Base):
    __tablename__ = "prices"
    __table_args__ = (UniqueConstraint("ticker", "date", name="uq_price_ticker_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(ForeignKey("companies.ticker"), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    open: Mapped[Optional[float]] = mapped_column(Float)
    high: Mapped[Optional[float]] = mapped_column(Float)
    low: Mapped[Optional[float]] = mapped_column(Float)
    close: Mapped[Optional[float]] = mapped_column(Float)
    adj_close: Mapped[Optional[float]] = mapped_column(Float)
    volume: Mapped[Optional[int]] = mapped_column(Integer)
    source: Mapped[Optional[str]] = mapped_column(String(50))


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
    valuation_gap_pct: Mapped[Optional[float]] = mapped_column(Float)
    base_case_rerating: Mapped[Optional[float]] = mapped_column(Float)
    valuation_provenance: Mapped[Optional[str]] = mapped_column(String(50))
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
    probation_start_date: Mapped[Optional[date]] = mapped_column(Date)
    probation_reviews_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cooldown_flag: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    cooldown_until: Mapped[Optional[date]] = mapped_column(Date)
    hold_through_earnings_allowed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    exit_date: Mapped[Optional[date]] = mapped_column(Date)
    exit_reason: Mapped[Optional[str]] = mapped_column(String(100))

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
    cooldown_until: Mapped[Optional[date]] = mapped_column(Date)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class PortfolioReview(Base):
    __tablename__ = "portfolio_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    review_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    review_type: Mapped[str] = mapped_column(String(50), nullable=False)  # weekly / immediate / ad_hoc
    holdings_reviewed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    candidates_reviewed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    turnover_pct: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    decisions = relationship("PortfolioDecision", back_populates="review", cascade="all, delete-orphan")


class PortfolioDecision(Base):
    __tablename__ = "portfolio_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    review_id: Mapped[int] = mapped_column(ForeignKey("portfolio_reviews.id"), nullable=False, index=True)
    ticker: Mapped[str] = mapped_column(ForeignKey("companies.ticker"), nullable=False, index=True)
    action: Mapped[ActionType] = mapped_column(SAEnum(ActionType), nullable=False)
    action_score: Mapped[float] = mapped_column(Float, nullable=False)
    target_weight_change: Mapped[Optional[float]] = mapped_column(Float)
    suggested_weight: Mapped[Optional[float]] = mapped_column(Float)
    reason_codes: Mapped[Optional[str]] = mapped_column(Text)  # JSON list of reason codes
    rationale: Mapped[Optional[str]] = mapped_column(Text)
    blocking_conditions: Mapped[Optional[str]] = mapped_column(Text)  # JSON list
    required_followup: Mapped[Optional[str]] = mapped_column(Text)
    was_executed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    review = relationship("PortfolioReview", back_populates="decisions")


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


class CompanyTagLink(Base):
    """Links a company to a thematic tag with a relevance weight.

    Weight indicates how central the tag is to this company's business.
    E.g., NVDA + "AI" = 0.9, META + "AI" = 0.7, WMT + "AI" = 0.2.
    """
    __tablename__ = "company_tag_links"
    __table_args__ = (UniqueConstraint("company_ticker", "theme_id", name="uq_company_tag"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_ticker: Mapped[str] = mapped_column(ForeignKey("companies.ticker"), nullable=False, index=True)
    theme_id: Mapped[int] = mapped_column(ForeignKey("themes.id"), nullable=False, index=True)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)  # 0-1 relevance
    source: Mapped[Optional[str]] = mapped_column(String(50))  # manual / llm_extracted / fmp


class CompanyRelationship(Base):
    """Direct company-to-company relationship (supplier, customer, competitor, ecosystem)."""
    __tablename__ = "company_relationships"
    __table_args__ = (
        UniqueConstraint("source_ticker", "target_ticker", "relationship_type", name="uq_company_rel"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_ticker: Mapped[str] = mapped_column(ForeignKey("companies.ticker"), nullable=False, index=True)
    target_ticker: Mapped[str] = mapped_column(ForeignKey("companies.ticker"), nullable=False, index=True)
    relationship_type: Mapped[RelationshipType] = mapped_column(SAEnum(RelationshipType), nullable=False)
    strength: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)  # 0-1 dependency weight
    description: Mapped[Optional[str]] = mapped_column(Text)  # "TSMC manufactures NVDA GPUs on 4nm"
    bidirectional: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source: Mapped[Optional[str]] = mapped_column(String(50))  # manual / 10k_extracted / fmp_peers


class DerivedSignal(Base):
    """Cross-ticker propagated impact from a source claim.

    When a claim about ticker A is scored, signals propagate to related tickers
    via tag overlap or direct relationships. These signals become part of
    "what we already know" for the target ticker's next thesis update.
    """
    __tablename__ = "derived_signals"
    __table_args__ = (
        UniqueConstraint("source_claim_id", "target_ticker", name="uq_derived_signal"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id"), nullable=False, index=True)
    source_ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    target_ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    # How the signal was propagated
    propagation_type: Mapped[str] = mapped_column(String(20), nullable=False)  # direct / tag
    relationship_type: Mapped[Optional[str]] = mapped_column(String(30))  # supplier/customer/competitor/ecosystem or tag name
    attenuation_factor: Mapped[float] = mapped_column(Float, nullable=False)  # 0-1, how much signal survives

    # Derived impact
    derived_direction: Mapped[Direction] = mapped_column(SAEnum(Direction), nullable=False)
    derived_strength: Mapped[float] = mapped_column(Float, nullable=False)  # original strength * attenuation
    rationale: Mapped[Optional[str]] = mapped_column(Text)  # why this propagation matters

    # Lifecycle
    consumed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    consumed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


# ---------- Step 13.1: Evidence Assessment (persisted evidence state) ----------

class EvidenceAssessment(Base):
    """Persisted evidence state for a claim assessed against a thesis.

    Captures the enriched evidence metadata used when a claim contributed to
    a thesis update.  Downstream layers (replay, console, explainability) can
    query this table instead of recomputing evidence scores from scratch.
    """
    __tablename__ = "evidence_assessments"
    __table_args__ = (
        UniqueConstraint("thesis_id", "claim_id", name="uq_evidence_assessment"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thesis_id: Mapped[int] = mapped_column(ForeignKey("theses.id"), nullable=False, index=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id"), nullable=False, index=True)

    # Evidence scoring inputs
    source_tier_weight: Mapped[float] = mapped_column(Float, nullable=False)
    freshness_factor: Mapped[float] = mapped_column(Float, nullable=False)
    novelty_factor: Mapped[float] = mapped_column(Float, nullable=False)
    cluster_penalty: Mapped[float] = mapped_column(Float, nullable=False)
    evidence_weight: Mapped[float] = mapped_column(Float, nullable=False)

    # Cluster / contradiction context
    cluster_position: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    event_cluster_id: Mapped[Optional[str]] = mapped_column(String(100))
    is_contradicted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    contradicts_claim_id: Mapped[Optional[int]] = mapped_column(Integer)

    # LLM/stub assessment
    impact: Mapped[str] = mapped_column(String(20), nullable=False)  # supports/weakens/neutral/conflicting
    materiality: Mapped[float] = mapped_column(Float, nullable=False)
    delta: Mapped[float] = mapped_column(Float, nullable=False)

    assessed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


# ---------- Step 8.2: Claim Impact Profiling ----------

class ClaimOutcome(Base):
    """Realized market impact of a claim: forward returns after publication.

    Built from (claim, ticker, price_data) to measure what actually happened
    after a claim hit the market. Used to learn which claim types are predictive.
    """
    __tablename__ = "claim_outcomes"
    __table_args__ = (
        UniqueConstraint("claim_id", "ticker", name="uq_claim_outcome"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id"), nullable=False, index=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    published_date: Mapped[date] = mapped_column(Date, nullable=False)
    price_at_claim: Mapped[float] = mapped_column(Float, nullable=False)
    forward_5d_pct: Mapped[Optional[float]] = mapped_column(Float)
    forward_20d_pct: Mapped[Optional[float]] = mapped_column(Float)
    claim_type: Mapped[Optional[str]] = mapped_column(String(50))
    direction: Mapped[Optional[str]] = mapped_column(String(20))
    computed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


# ---------- Earnings Estimates ----------

class EarningsEstimate(Base):
    """Consensus analyst estimates for a ticker/fiscal period.

    Stored BEFORE earnings release so the system can compare actuals vs
    expectations. One row per ticker per fiscal period.
    """
    __tablename__ = "earnings_estimates"
    __table_args__ = (
        UniqueConstraint("ticker", "fiscal_date", name="uq_earnings_estimate"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    fiscal_date: Mapped[date] = mapped_column(Date, nullable=False)
    fiscal_period: Mapped[Optional[str]] = mapped_column(String(10))  # "Q1 2026", "FY2025"

    # Consensus estimates (pre-earnings)
    estimated_revenue: Mapped[Optional[float]] = mapped_column(Float)
    estimated_eps: Mapped[Optional[float]] = mapped_column(Float)
    estimated_ebitda: Mapped[Optional[float]] = mapped_column(Float)
    estimated_net_income: Mapped[Optional[float]] = mapped_column(Float)
    revenue_low: Mapped[Optional[float]] = mapped_column(Float)
    revenue_high: Mapped[Optional[float]] = mapped_column(Float)
    eps_low: Mapped[Optional[float]] = mapped_column(Float)
    eps_high: Mapped[Optional[float]] = mapped_column(Float)
    num_analysts: Mapped[Optional[int]] = mapped_column(Integer)

    # Actuals (filled after earnings release)
    actual_revenue: Mapped[Optional[float]] = mapped_column(Float)
    actual_eps: Mapped[Optional[float]] = mapped_column(Float)

    # Computed surprise
    revenue_surprise_pct: Mapped[Optional[float]] = mapped_column(Float)
    eps_surprise_pct: Mapped[Optional[float]] = mapped_column(Float)
    surprise_bucket: Mapped[Optional[str]] = mapped_column(String(20))  # big_miss, small_miss, inline, small_beat, big_beat

    # Earnings date
    earnings_date: Mapped[Optional[date]] = mapped_column(Date)

    # Metadata
    source: Mapped[Optional[str]] = mapped_column(String(30))  # "fmp", "alphavantage", "manual"
    fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, onupdate=datetime.utcnow)


# ---------- Step 9: Execution Artifacts ----------

class ExecutionIntentRecord(Base):
    """Persisted order intent for audit trail."""
    __tablename__ = "execution_intents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(10), nullable=False)  # buy / sell
    action_type: Mapped[str] = mapped_column(String(20), nullable=False)  # initiate / add / trim / exit
    target_weight_before: Mapped[float] = mapped_column(Float, nullable=False)
    target_weight_after: Mapped[float] = mapped_column(Float, nullable=False)
    notional_delta: Mapped[float] = mapped_column(Float, nullable=False)
    estimated_shares: Mapped[Optional[float]] = mapped_column(Float)
    reference_price: Mapped[Optional[float]] = mapped_column(Float)
    reason_codes: Mapped[Optional[str]] = mapped_column(Text)  # JSON list
    linked_funding_ticker: Mapped[Optional[str]] = mapped_column(String(20))
    review_date: Mapped[Optional[str]] = mapped_column(String(20))
    review_id: Mapped[Optional[int]] = mapped_column(Integer)
    is_validated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    block_reasons: Mapped[Optional[str]] = mapped_column(Text)  # JSON list
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    paper_trade: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class PaperFillRecord(Base):
    """Persisted paper fill for audit trail."""
    __tablename__ = "paper_fills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fill_id: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    action_type: Mapped[str] = mapped_column(String(20), nullable=False)
    shares: Mapped[float] = mapped_column(Float, nullable=False)
    fill_price: Mapped[float] = mapped_column(Float, nullable=False)
    notional: Mapped[float] = mapped_column(Float, nullable=False)
    transaction_cost: Mapped[float] = mapped_column(Float, nullable=False)
    review_date: Mapped[Optional[str]] = mapped_column(String(20))
    filled_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class PaperPortfolioSnapshotRecord(Base):
    """Persisted paper portfolio snapshot for audit trail."""
    __tablename__ = "paper_portfolio_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    total_value: Mapped[float] = mapped_column(Float, nullable=False)
    cash: Mapped[float] = mapped_column(Float, nullable=False)
    invested: Mapped[float] = mapped_column(Float, nullable=False)
    num_positions: Mapped[int] = mapped_column(Integer, nullable=False)
    positions_json: Mapped[Optional[str]] = mapped_column(Text)  # JSON {ticker: market_value}
    weights_json: Mapped[Optional[str]] = mapped_column(Text)    # JSON {ticker: weight_pct}
    snapshot_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class LiveOrderRecord(Base):
    """Persisted live order for audit trail."""
    __tablename__ = "live_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    broker_order_id: Mapped[Optional[str]] = mapped_column(String(50), index=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    action_type: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    order_type: Mapped[str] = mapped_column(String(20), nullable=False)
    limit_price: Mapped[Optional[float]] = mapped_column(Float)
    time_in_force: Mapped[str] = mapped_column(String(10), default="day", nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    filled_quantity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    filled_avg_price: Mapped[Optional[float]] = mapped_column(Float)
    intent_id: Mapped[Optional[str]] = mapped_column(String(100))
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    state_history_json: Mapped[Optional[str]] = mapped_column(Text)  # JSON list
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    filled_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class LiveFillRecord(Base):
    """Persisted live fill for audit trail."""
    __tablename__ = "live_fills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fill_id: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    order_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    broker_order_id: Mapped[Optional[str]] = mapped_column(String(50))
    ticker: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    shares: Mapped[float] = mapped_column(Float, nullable=False)
    fill_price: Mapped[float] = mapped_column(Float, nullable=False)
    notional: Mapped[float] = mapped_column(Float, nullable=False)
    filled_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)