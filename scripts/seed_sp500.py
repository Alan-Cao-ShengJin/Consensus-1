"""Seed S&P 500 companies with tags and relationships into SQL + Neo4j.

Usage:
    python scripts/seed_sp500.py [--neo4j]

Flags:
    --neo4j   Also sync relationships to Neo4j via Graphiti (requires credentials)
"""
from __future__ import annotations

import io
import logging
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

from db import get_session
from crud import get_or_create_company, get_or_create_theme
from models import (
    Company, CompanyTagLink, CompanyRelationship, RelationshipType, Theme,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Step 1: Fetch S&P 500 from Wikipedia
# ---------------------------------------------------------------------------

def fetch_sp500() -> pd.DataFrame:
    """Fetch current S&P 500 constituents from Wikipedia."""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    r = requests.get(
        "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
        headers=headers,
        timeout=15,
    )
    r.raise_for_status()
    tables = pd.read_html(io.StringIO(r.text))
    df = tables[0]
    logger.info("Fetched %d S&P 500 constituents", len(df))
    return df


# ---------------------------------------------------------------------------
# Step 2: Thematic tags — sector + cross-cutting themes
# ---------------------------------------------------------------------------

# Cross-cutting investment themes and which GICS sectors/sub-industries map to them
THEME_MAPPINGS: dict[str, dict] = {
    # Sector-level tags (every company gets its GICS sector as a tag)
    # These are added automatically from the GICS Sector column.

    # Cross-cutting themes with keyword matching on sub-industry
    "AI": {
        "tickers": {
            "NVDA", "AMD", "AVGO", "MSFT", "GOOGL", "AMZN", "META", "CRM",
            "PLTR", "NOW", "SNOW", "DDOG", "MDB", "NET", "CRWD", "ZS",
            "ORCL", "IBM", "INTC", "MRVL", "MU", "QCOM", "ARM", "SMCI",
            "DELL", "HPE", "ANET",
        },
        "weight_default": 0.6,
        "weight_high": {"NVDA": 0.95, "AMD": 0.8, "MSFT": 0.85, "GOOGL": 0.85,
                        "AMZN": 0.75, "META": 0.8, "PLTR": 0.85, "SNOW": 0.7,
                        "CRM": 0.7, "AVGO": 0.7, "SMCI": 0.85},
    },
    "Cloud Computing": {
        "tickers": {
            "AMZN", "MSFT", "GOOGL", "CRM", "SNOW", "NOW", "DDOG", "NET",
            "MDB", "ORCL", "IBM", "DELL", "HPE", "CRWD", "ZS",
        },
        "weight_default": 0.6,
        "weight_high": {"AMZN": 0.8, "MSFT": 0.85, "GOOGL": 0.75, "CRM": 0.8,
                        "SNOW": 0.85, "NOW": 0.8},
    },
    "Semiconductor": {
        "sub_industries": ["Semiconductors", "Semiconductor Materials & Equipment"],
        "weight_default": 0.85,
        "weight_high": {"NVDA": 0.95, "AMD": 0.9, "INTC": 0.9, "AVGO": 0.9,
                        "QCOM": 0.9, "MU": 0.9, "MRVL": 0.85, "TXN": 0.9,
                        "ADI": 0.85, "NXPI": 0.85, "ON": 0.85, "KLAC": 0.9,
                        "LRCX": 0.9, "AMAT": 0.9},
    },
    "E-Commerce": {
        "tickers": {"AMZN", "EBAY", "ETSY", "SHOP", "MELI"},
        "weight_default": 0.7,
        "weight_high": {"AMZN": 0.85},
    },
    "Digital Advertising": {
        "tickers": {"GOOGL", "META", "TTD", "PINS"},
        "weight_default": 0.7,
        "weight_high": {"GOOGL": 0.8, "META": 0.85},
    },
    "Cybersecurity": {
        "tickers": {"CRWD", "ZS", "PANW", "FTNT", "GEN"},
        "weight_default": 0.8,
        "weight_high": {"CRWD": 0.9, "ZS": 0.9, "PANW": 0.9},
    },
    "EV / Clean Energy": {
        "tickers": {"TSLA", "ENPH", "FSLR", "CEG", "VST", "NEE", "AES"},
        "sub_industries": ["Automobile Manufacturers", "Renewable Electricity"],
        "weight_default": 0.6,
        "weight_high": {"TSLA": 0.85, "ENPH": 0.9, "FSLR": 0.9},
    },
    "Payments / Fintech": {
        "tickers": {"V", "MA", "PYPL", "SQ", "COIN", "FIS", "FISV", "GPN", "AXP"},
        "weight_default": 0.75,
        "weight_high": {"V": 0.9, "MA": 0.9, "PYPL": 0.85},
    },
    "Defense / Aerospace": {
        "tickers": {"LMT", "RTX", "GD", "NOC", "BA", "LHX", "HII"},
        "weight_default": 0.85,
    },
    "Biotech / Pharma": {
        "sub_industries": ["Biotechnology", "Pharmaceuticals", "Life Sciences Tools & Services"],
        "weight_default": 0.75,
        "weight_high": {"LLY": 0.9, "MRNA": 0.9, "ABBV": 0.85, "JNJ": 0.8,
                        "PFE": 0.85, "BMY": 0.85, "GILD": 0.85, "AMGN": 0.85,
                        "REGN": 0.85, "VRTX": 0.9},
    },
    "Consumer Staples": {
        "sectors": ["Consumer Staples"],
        "weight_default": 0.8,
    },
    "Banking": {
        "tickers": {"JPM", "BAC", "WFC", "C", "GS", "MS", "USB", "PNC", "TFC", "SCHW"},
        "weight_default": 0.85,
    },
    "Oil & Gas": {
        "sub_industries": ["Integrated Oil & Gas", "Oil & Gas Exploration & Production",
                           "Oil & Gas Refining & Marketing", "Oil & Gas Storage & Transportation"],
        "weight_default": 0.85,
    },
}


# ---------------------------------------------------------------------------
# Step 3: Key relationships — supply chain, competition, ecosystem
# ---------------------------------------------------------------------------

RELATIONSHIPS: list[tuple[str, str, str, str, float, str]] = [
    # (source, target, type, description, strength, bidirectional)
    # Semiconductor supply chain
    ("TSMC", "NVDA", "supplier", "TSMC manufactures NVIDIA GPUs on advanced process nodes", 0.8, False),
    ("TSMC", "AMD", "supplier", "TSMC manufactures AMD CPUs/GPUs", 0.75, False),
    ("TSMC", "AAPL", "supplier", "TSMC manufactures Apple silicon chips", 0.7, False),
    ("TSMC", "QCOM", "supplier", "TSMC manufactures Qualcomm mobile chips", 0.7, False),
    ("TSMC", "AVGO", "supplier", "TSMC manufactures Broadcom networking chips", 0.6, False),
    ("ASML", "TSMC", "supplier", "ASML supplies EUV lithography to TSMC", 0.7, False),
    ("LRCX", "TSMC", "supplier", "Lam Research supplies etch equipment to TSMC", 0.5, False),
    ("AMAT", "TSMC", "supplier", "Applied Materials supplies deposition equipment to TSMC", 0.5, False),
    ("KLAC", "TSMC", "supplier", "KLA supplies inspection equipment to TSMC", 0.5, False),

    # Cloud / AI supply chain
    ("NVDA", "MSFT", "supplier", "NVIDIA supplies AI GPUs for Azure", 0.7, False),
    ("NVDA", "AMZN", "supplier", "NVIDIA supplies AI GPUs for AWS", 0.65, False),
    ("NVDA", "GOOGL", "supplier", "NVIDIA supplies AI GPUs for Google Cloud", 0.6, False),
    ("NVDA", "META", "supplier", "NVIDIA supplies AI GPUs for Meta AI infrastructure", 0.65, False),
    ("NVDA", "ORCL", "supplier", "NVIDIA supplies AI GPUs for Oracle Cloud", 0.5, False),
    ("AVGO", "AAPL", "supplier", "Broadcom supplies wireless/networking chips to Apple", 0.5, False),

    # Hyperscaler competition
    ("AMZN", "MSFT", "competitor", "AWS vs Azure cloud competition", 0.8, True),
    ("AMZN", "GOOGL", "competitor", "AWS vs Google Cloud competition", 0.6, True),
    ("MSFT", "GOOGL", "competitor", "Azure vs Google Cloud; Office vs Workspace", 0.7, True),

    # Semiconductor competition
    ("NVDA", "AMD", "competitor", "GPU and data center accelerator competition", 0.8, True),
    ("NVDA", "INTC", "competitor", "Data center and AI chip competition", 0.5, True),
    ("AMD", "INTC", "competitor", "CPU market competition", 0.8, True),
    ("AVGO", "MRVL", "competitor", "Networking semiconductor competition", 0.5, True),
    ("QCOM", "INTC", "competitor", "Mobile/PC chip competition", 0.4, True),

    # Payments competition
    ("V", "MA", "competitor", "Global payments network competition", 0.9, True),
    ("PYPL", "SQ", "competitor", "Digital payments competition", 0.6, True),

    # Social media / digital ads competition
    ("META", "GOOGL", "competitor", "Digital advertising competition", 0.7, True),
    ("META", "SNAP", "competitor", "Social media competition", 0.5, True),

    # Cybersecurity competition
    ("CRWD", "PANW", "competitor", "Enterprise cybersecurity competition", 0.7, True),
    ("CRWD", "ZS", "competitor", "Cloud security competition", 0.5, True),

    # Streaming competition
    ("NFLX", "DIS", "competitor", "Streaming entertainment competition", 0.6, True),

    # EV / Auto
    ("TSLA", "GM", "competitor", "EV market competition", 0.5, True),
    ("TSLA", "F", "competitor", "EV market competition", 0.4, True),

    # Ecosystem relationships
    ("AAPL", "MSFT", "ecosystem", "Shared enterprise ecosystem (devices + cloud)", 0.4, True),
    ("AMZN", "AAPL", "ecosystem", "Device + services ecosystem overlap", 0.3, True),
    ("CRM", "MSFT", "competitor", "Enterprise CRM/productivity competition", 0.5, True),
    ("NOW", "CRM", "ecosystem", "Enterprise workflow + CRM ecosystem", 0.4, True),

    # Pharma / biotech
    ("LLY", "NVO", "competitor", "GLP-1 obesity drug competition", 0.7, True),
    ("ABBV", "BMY", "competitor", "Immunology drug competition", 0.5, True),

    # Banking
    ("JPM", "GS", "competitor", "Investment banking competition", 0.6, True),
    ("JPM", "BAC", "competitor", "Retail + investment banking competition", 0.7, True),

    # Retail
    ("AMZN", "WMT", "competitor", "Retail competition", 0.6, True),
    ("AMZN", "COST", "competitor", "E-commerce vs warehouse retail", 0.4, True),
]


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def seed_companies(session, df: pd.DataFrame) -> dict[str, Company]:
    """Create/update Company rows from S&P 500 dataframe."""
    companies = {}
    for _, row in df.iterrows():
        ticker = row["Symbol"].replace(".", "-")  # BRK.B -> BRK-B
        name = row["Security"]
        sector = row.get("GICS Sector", "")
        sub_industry = row.get("GICS Sub-Industry", "")

        co = get_or_create_company(session, ticker, name)
        if sector and not co.sector:
            co.sector = sector
        if sub_industry and not co.subindustry:
            co.subindustry = sub_industry
        companies[ticker] = co

    session.flush()
    logger.info("Seeded %d companies", len(companies))
    return companies


def seed_themes_and_tags(session, df: pd.DataFrame, companies: dict[str, Company]):
    """Create themes and link companies to them with weights."""
    # 1. Sector-level tags (every company gets its GICS sector)
    sector_themes = {}
    for _, row in df.iterrows():
        sector = row.get("GICS Sector", "")
        if sector and sector not in sector_themes:
            theme = get_or_create_theme(session, sector)
            sector_themes[sector] = theme
    session.flush()

    # Link companies to sector tags
    tag_count = 0
    for _, row in df.iterrows():
        ticker = row["Symbol"].replace(".", "-")
        sector = row.get("GICS Sector", "")
        if sector and ticker in companies:
            theme = sector_themes[sector]
            _ensure_tag_link(session, ticker, theme.id, weight=0.8, source="gics_sector")
            tag_count += 1

    # 2. Cross-cutting theme tags
    sub_ind_col = "GICS Sub-Industry"
    ticker_sub_ind = {}
    for _, row in df.iterrows():
        ticker_sub_ind[row["Symbol"].replace(".", "-")] = row.get(sub_ind_col, "")

    for theme_name, config in THEME_MAPPINGS.items():
        theme = get_or_create_theme(session, theme_name)
        session.flush()

        weight_default = config.get("weight_default", 0.5)
        weight_high = config.get("weight_high", {})

        # Match by explicit ticker list
        for ticker in config.get("tickers", set()):
            if ticker in companies:
                w = weight_high.get(ticker, weight_default)
                _ensure_tag_link(session, ticker, theme.id, weight=w, source="manual")
                tag_count += 1

        # Match by sector
        for sector_name in config.get("sectors", []):
            for ticker, co in companies.items():
                if co.sector == sector_name:
                    w = weight_high.get(ticker, weight_default)
                    _ensure_tag_link(session, ticker, theme.id, weight=w, source="gics_sector")
                    tag_count += 1

        # Match by sub-industry
        for sub_ind in config.get("sub_industries", []):
            for ticker, sub in ticker_sub_ind.items():
                if sub_ind.lower() in sub.lower() and ticker in companies:
                    w = weight_high.get(ticker, weight_default)
                    _ensure_tag_link(session, ticker, theme.id, weight=w, source="gics_sub_industry")
                    tag_count += 1

    session.flush()
    logger.info("Created %d company-tag links", tag_count)


def seed_relationships(session, companies: dict[str, Company]):
    """Create CompanyRelationship rows."""
    rel_count = 0
    for src, tgt, rel_type, desc, strength, bidir in RELATIONSHIPS:
        # Skip if companies not in our universe
        if src not in companies or tgt not in companies:
            continue

        try:
            rt = RelationshipType(rel_type)
        except ValueError:
            logger.warning("Unknown relationship type: %s", rel_type)
            continue

        _ensure_relationship(session, src, tgt, rt, desc, strength, bidir == True)
        rel_count += 1

    session.flush()
    logger.info("Created %d company relationships", rel_count)


def sync_to_neo4j(session, companies: dict[str, Company]):
    """Sync relationships to Neo4j via Graphiti."""
    try:
        from graphiti_adapter import add_company_relationships_bulk, ensure_indices, close_graphiti
    except ImportError:
        logger.warning("Graphiti adapter not available, skipping Neo4j sync")
        return

    ensure_indices()

    triplets = []
    for src, tgt, rel_type, desc, strength, bidir in RELATIONSHIPS:
        if src not in companies or tgt not in companies:
            continue
        src_name = companies[src].name or src
        tgt_name = companies[tgt].name or tgt
        triplets.append((src_name, f"{rel_type}: {desc}", tgt_name))

    if triplets:
        count = add_company_relationships_bulk(triplets)
        logger.info("Synced %d/%d relationships to Neo4j", count, len(triplets))

    close_graphiti()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_tag_link(session, ticker: str, theme_id: int, weight: float, source: str):
    """Upsert a CompanyTagLink."""
    from sqlalchemy import select
    existing = session.scalar(
        select(CompanyTagLink).where(
            CompanyTagLink.company_ticker == ticker,
            CompanyTagLink.theme_id == theme_id,
        )
    )
    if existing:
        existing.weight = max(existing.weight, weight)  # keep higher weight
        return
    session.add(CompanyTagLink(
        company_ticker=ticker, theme_id=theme_id,
        weight=weight, source=source,
    ))


def _ensure_relationship(session, src: str, tgt: str, rel_type: RelationshipType,
                          desc: str, strength: float, bidir: bool):
    """Upsert a CompanyRelationship."""
    from sqlalchemy import select
    existing = session.scalar(
        select(CompanyRelationship).where(
            CompanyRelationship.source_ticker == src,
            CompanyRelationship.target_ticker == tgt,
            CompanyRelationship.relationship_type == rel_type,
        )
    )
    if existing:
        existing.strength = strength
        existing.description = desc
        existing.bidirectional = bidir
        return
    session.add(CompanyRelationship(
        source_ticker=src, target_ticker=tgt,
        relationship_type=rel_type, description=desc,
        strength=strength, bidirectional=bidir,
        source="manual",
    ))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    sync_neo4j = "--neo4j" in sys.argv

    logger.info("=== S&P 500 Seeding Script ===")

    # Fetch S&P 500
    df = fetch_sp500()

    # Ensure DB tables exist
    from models import Base
    from db import engine
    Base.metadata.create_all(engine)

    with get_session() as session:
        # Seed companies
        companies = seed_companies(session, df)

        # Seed themes and tag links
        seed_themes_and_tags(session, df, companies)

        # Seed relationships
        seed_relationships(session, companies)

        session.flush()
        logger.info("SQL seeding complete: %d companies", len(companies))

        # Optional: sync to Neo4j
        if sync_neo4j:
            logger.info("Syncing to Neo4j...")
            sync_to_neo4j(session, companies)
            logger.info("Neo4j sync complete")

    logger.info("=== Done ===")


if __name__ == "__main__":
    main()
