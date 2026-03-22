"""Graphiti + Neo4j adapter for the Consensus knowledge graph.

Wraps the async graphiti-core API with sync interfaces for our pipeline.
Manages the Graphiti client lifecycle and provides domain-specific methods
for company relationships, claim ingestion, and cross-ticker queries.

Usage:
    from graphiti_adapter import get_graphiti, ingest_claims_to_graph, search_related_tickers

    # Ingest claims after extraction
    ingest_claims_to_graph(claims, source_ticker, document_title)

    # Find related tickers for propagation
    related = search_related_tickers("NVDA")
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Custom entity and edge types for Graphiti
# ---------------------------------------------------------------------------

class CompanyEntity(BaseModel):
    """A publicly traded company in our investment universe."""
    ticker: Optional[str] = Field(None, description="Stock ticker symbol (e.g., NVDA, AAPL)")
    sector: Optional[str] = Field(None, description="GICS sector")
    industry: Optional[str] = Field(None, description="GICS industry")
    market_cap_bucket: Optional[str] = Field(None, description="mega/large/mid/small")
    themes: Optional[list[str]] = Field(None, description="Investment themes/tags")


class SupplyChainEdge(BaseModel):
    """Supply chain relationship between companies."""
    relationship_type: Optional[str] = Field(None, description="supplier or customer")
    revenue_dependency: Optional[float] = Field(None, description="Revenue dependency weight 0-1")
    description: Optional[str] = Field(None, description="Description of the relationship")


class CompetitorEdge(BaseModel):
    """Competitive relationship between companies."""
    overlap_area: Optional[str] = Field(None, description="Area of competition")
    intensity: Optional[float] = Field(None, description="Competitive intensity 0-1")


class EcosystemEdge(BaseModel):
    """Ecosystem/platform dependency between companies."""
    dependency_type: Optional[str] = Field(None, description="Type of ecosystem dependency")
    strength: Optional[float] = Field(None, description="Dependency strength 0-1")


# Graphiti entity/edge type configs
ENTITY_TYPES = {"Company": CompanyEntity}
EDGE_TYPES = {
    "SupplyChain": SupplyChainEdge,
    "Competitor": CompetitorEdge,
    "Ecosystem": EcosystemEdge,
}
EDGE_TYPE_MAP = {
    ("Company", "Company"): ["SupplyChain", "Competitor", "Ecosystem"],
}

# Group ID for namespacing our data in Neo4j
CONSENSUS_GROUP_ID = "consensus-1"


# ---------------------------------------------------------------------------
# Async event loop helper
# ---------------------------------------------------------------------------

_event_loop = None


def _get_loop():
    """Get or create a persistent event loop for Graphiti async operations."""
    global _event_loop
    if _event_loop is None or _event_loop.is_closed():
        _event_loop = asyncio.new_event_loop()
    return _event_loop


def _run_async(coro):
    """Run an async coroutine from sync code using a persistent event loop."""
    loop = _get_loop()
    return loop.run_until_complete(coro)


# ---------------------------------------------------------------------------
# Graphiti client singleton
# ---------------------------------------------------------------------------

_graphiti_instance = None


def get_graphiti():
    """Get or create the Graphiti client singleton.

    Returns the Graphiti instance connected to Neo4j AuraDB.
    Uses OpenAI as the default LLM/embedder provider.
    """
    global _graphiti_instance
    if _graphiti_instance is not None:
        return _graphiti_instance

    from graphiti_core import Graphiti
    from graphiti_core.driver.neo4j_driver import Neo4jDriver
    from graphiti_core.llm_client.openai_client import OpenAIClient
    from graphiti_core.llm_client.config import LLMConfig

    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USERNAME")
    password = os.getenv("NEO4J_PASSWORD")
    database = os.getenv("NEO4J_DATABASE")

    if not all([uri, user, password]):
        raise RuntimeError(
            "Neo4j credentials not configured. "
            "Set NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD in .env"
        )

    driver = Neo4jDriver(
        uri=uri,
        user=user,
        password=password,
        database=database,
    )

    # Use gpt-4o-mini for extraction (cost-effective for entity extraction)
    llm_client = OpenAIClient(
        config=LLMConfig(
            model=os.getenv("GRAPHITI_LLM_MODEL", "gpt-4o-mini"),
            small_model=os.getenv("GRAPHITI_SMALL_MODEL", "gpt-4o-mini"),
        )
    )

    _graphiti_instance = Graphiti(
        graph_driver=driver,
        llm_client=llm_client,
        store_raw_episode_content=True,
    )

    logger.info("Graphiti client initialized (uri=%s, db=%s)", uri, database)
    return _graphiti_instance


def close_graphiti():
    """Close the Graphiti client and release resources."""
    global _graphiti_instance
    if _graphiti_instance is not None:
        _run_async(_graphiti_instance.close())
        _graphiti_instance = None
        logger.info("Graphiti client closed")


def ensure_indices():
    """Build Graphiti indices and constraints (idempotent)."""
    g = get_graphiti()
    _run_async(g.build_indices_and_constraints())
    logger.info("Graphiti indices verified")


# ---------------------------------------------------------------------------
# Domain operations: Company relationships
# ---------------------------------------------------------------------------

def add_company_relationship(
    source_name: str,
    relationship: str,
    target_name: str,
) -> None:
    """Add a company-to-company relationship triplet to the knowledge graph.

    Uses Graphiti's add_triplet() with proper EntityNode/EntityEdge objects.

    Args:
        source_name: Source company name (e.g., "NVIDIA Corporation")
        relationship: Relationship type (e.g., "supplies_chips_to", "competes_with")
        target_name: Target company name (e.g., "Apple Inc")
    """
    from graphiti_core.nodes import EntityNode
    from graphiti_core.edges import EntityEdge

    g = get_graphiti()

    source_node = EntityNode(
        name=source_name,
        group_id=CONSENSUS_GROUP_ID,
        summary=f"Company: {source_name}",
    )
    target_node = EntityNode(
        name=target_name,
        group_id=CONSENSUS_GROUP_ID,
        summary=f"Company: {target_name}",
    )
    now = datetime.utcnow()
    edge = EntityEdge(
        source_node_uuid=source_node.uuid,
        target_node_uuid=target_node.uuid,
        group_id=CONSENSUS_GROUP_ID,
        name=relationship,
        fact=f"{source_name} {relationship.replace('_', ' ')} {target_name}",
        created_at=now,
        valid_at=now,
        episodes=[],
    )

    _run_async(g.add_triplet(source_node, edge, target_node))
    logger.info("Added triplet: %s -[%s]-> %s", source_name, relationship, target_name)


def add_company_relationships_bulk(
    triplets: list[tuple[str, str, str]],
) -> int:
    """Add multiple company relationships in sequence.

    Args:
        triplets: List of (source_name, relationship, target_name) tuples.

    Returns:
        Count of successfully added triplets.
    """
    count = 0
    for source, rel, target in triplets:
        try:
            add_company_relationship(source, rel, target)
            count += 1
        except Exception as e:
            logger.warning("Failed to add triplet %s->%s->%s: %s", source, rel, target, e)
    logger.info("Added %d/%d relationship triplets", count, len(triplets))
    return count


# ---------------------------------------------------------------------------
# Domain operations: Claim/document ingestion
# ---------------------------------------------------------------------------

def ingest_claims_to_graph(
    claims_text: list[str],
    source_ticker: str,
    document_title: str,
    document_date: Optional[datetime] = None,
) -> dict:
    """Ingest extracted claims into the knowledge graph as an episode.

    This feeds claim text to Graphiti, which uses the LLM to extract entities
    and relationships, then stores them in Neo4j with temporal metadata.

    Args:
        claims_text: List of claim text strings to ingest.
        source_ticker: Primary ticker for the document.
        document_title: Title of the source document.
        document_date: Publication date (defaults to now).

    Returns:
        Dict with counts of extracted entities and edges.
    """
    from graphiti_core.utils.maintenance.graph_data_operations import EpisodeType

    g = get_graphiti()
    ref_time = document_date or datetime.utcnow()

    # Combine claims into a single episode body
    body = f"Source: {source_ticker} — {document_title}\n\n"
    body += "\n".join(f"- {c}" for c in claims_text)

    async def _ingest():
        result = await g.add_episode(
            name=f"{source_ticker}_{document_title[:50]}_{ref_time.strftime('%Y%m%d')}",
            episode_body=body,
            source=EpisodeType.text,
            source_description=f"Extracted claims from {document_title}",
            reference_time=ref_time,
            group_id=CONSENSUS_GROUP_ID,
            entity_types=ENTITY_TYPES,
            edge_types=EDGE_TYPES,
            edge_type_map=EDGE_TYPE_MAP,
        )
        return result

    result = _run_async(_ingest())

    entity_count = len(result.nodes) if result.nodes else 0
    edge_count = len(result.edges) if result.edges else 0

    logger.info(
        "Ingested %s claims for %s: %d entities, %d edges extracted",
        len(claims_text), source_ticker, entity_count, edge_count,
    )

    return {
        "entities_extracted": entity_count,
        "edges_extracted": edge_count,
        "entity_names": [n.name for n in (result.nodes or [])],
        "edge_facts": [e.fact for e in (result.edges or [])],
    }


# ---------------------------------------------------------------------------
# Domain operations: Search and retrieval
# ---------------------------------------------------------------------------

def search_related_tickers(
    query: str,
    focal_ticker: Optional[str] = None,
    limit: int = 10,
) -> list[dict]:
    """Search the knowledge graph for entities/relationships matching a query.

    Args:
        query: Natural language query (e.g., "NVDA suppliers", "semiconductor competition")
        focal_ticker: Optional ticker to center the search around.
        limit: Max results to return.

    Returns:
        List of dicts with edge facts and related entity info.
    """
    g = get_graphiti()

    async def _search():
        # If we have a focal ticker, try to find its node UUID first
        focal_uuid = None
        if focal_ticker:
            focal_uuid = await _find_entity_uuid(g, focal_ticker)

        edges = await g.search(
            query,
            center_node_uuid=focal_uuid,
            group_ids=[CONSENSUS_GROUP_ID],
            num_results=limit,
        )
        return edges  # list[EntityEdge]

    edges = _run_async(_search())

    output = []
    for edge in (edges or []):
        output.append({
            "fact": edge.fact,
            "name": edge.name,
            "source_node_uuid": edge.source_node_uuid,
            "target_node_uuid": edge.target_node_uuid,
            "created_at": str(edge.created_at) if edge.created_at else None,
            "valid_at": str(edge.valid_at) if edge.valid_at else None,
            "expired_at": str(edge.expired_at) if edge.expired_at else None,
        })

    return output


def get_company_context(ticker: str) -> str:
    """Get a formatted knowledge graph context string for a ticker.

    Queries Neo4j for all relationships involving this company and formats
    them as context text for the thesis update LLM.

    Returns:
        Formatted string, or empty string if no graph data found.
    """
    results = search_related_tickers(
        f"relationships and facts about {ticker}",
        focal_ticker=ticker,
        limit=15,
    )

    if not results:
        return ""

    lines = ["## Knowledge graph context"]
    for r in results:
        fact = r.get("fact", "")
        valid = r.get("valid_at", "")
        expired = r.get("expired_at", "")
        temporal = ""
        if valid and valid != "None":
            temporal = f" [since {valid[:10]}]"
        if expired and expired != "None":
            temporal += f" [expired {expired[:10]}]"
        lines.append(f"- {fact}{temporal}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _find_entity_uuid(graphiti, ticker_or_name: str) -> Optional[str]:
    """Try to find the UUID of an entity node by ticker or company name."""
    try:
        edges = await graphiti.search(
            ticker_or_name,
            group_ids=[CONSENSUS_GROUP_ID],
            num_results=1,
        )
        if edges:
            # Return the source node UUID of the most relevant edge
            return edges[0].source_node_uuid
    except Exception as e:
        logger.debug("Could not find entity UUID for %s: %s", ticker_or_name, e)
    return None


# ---------------------------------------------------------------------------
# Direct Neo4j queries (for operations not covered by Graphiti API)
# ---------------------------------------------------------------------------

def run_cypher_query(query: str, params: Optional[dict] = None) -> list[dict]:
    """Run a raw Cypher query against Neo4j (read-only).

    Use this for custom graph traversals that Graphiti's search API
    doesn't cover (e.g., multi-hop supply chain impact analysis).
    """
    g = get_graphiti()

    async def _query():
        records = await g.driver.execute_query(query, params or {})
        return records

    return _run_async(_query())
