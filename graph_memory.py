"""Graph-native memory layer for the Consensus system.

Mirrors the relational DB into a NetworkX directed graph.
Each node corresponds to a real system object (Company, Document, Claim, Theme,
Thesis, Checkpoint, ThesisStateHistory, PortfolioPosition, Candidate).
Each edge corresponds to a real relationship or link-table row.

This is a *layer on top of* the relational core — it does not replace it.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, date
from enum import Enum
from typing import Any, Optional

import networkx as nx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Node types
# ---------------------------------------------------------------------------

class NodeType(str, Enum):
    COMPANY = "Company"
    DOCUMENT = "Document"
    CLAIM = "Claim"
    THEME = "Theme"
    THESIS = "Thesis"
    CHECKPOINT = "Checkpoint"
    THESIS_STATE = "ThesisStateHistory"
    PORTFOLIO_POSITION = "PortfolioPosition"
    CANDIDATE = "Candidate"
    PEER_GROUP = "PeerGroup"
    PORTFOLIO_REVIEW = "PortfolioReview"
    PORTFOLIO_DECISION = "PortfolioDecision"


# ---------------------------------------------------------------------------
# Edge types
# ---------------------------------------------------------------------------

class EdgeType(str, Enum):
    # Document / Claim
    DOCUMENT_HAS_CLAIM = "DOCUMENT_HAS_CLAIM"
    CLAIM_ABOUT_COMPANY = "CLAIM_ABOUT_COMPANY"
    CLAIM_SUPPORTS_THEME = "CLAIM_SUPPORTS_THEME"
    CLAIM_LINKED_TO_THESIS = "CLAIM_LINKED_TO_THESIS"

    # Thesis
    THESIS_FOR_COMPANY = "THESIS_FOR_COMPANY"
    THESIS_HAS_CHECKPOINT = "THESIS_HAS_CHECKPOINT"
    THESIS_HAS_STATE = "THESIS_HAS_STATE"
    THESIS_LINKED_TO_THEME = "THESIS_LINKED_TO_THEME"

    # Document provenance
    DOCUMENT_ABOUT_COMPANY = "DOCUMENT_ABOUT_COMPANY"

    # Portfolio
    POSITION_LINKED_TO_THESIS = "POSITION_LINKED_TO_THESIS"
    POSITION_FOR_COMPANY = "POSITION_FOR_COMPANY"
    CANDIDATE_LINKED_TO_THESIS = "CANDIDATE_LINKED_TO_THESIS"
    CANDIDATE_FOR_COMPANY = "CANDIDATE_FOR_COMPANY"

    # Peer groups
    COMPANY_IN_PEERGROUP = "COMPANY_IN_PEERGROUP"
    THESIS_TARGETS_PEERGROUP = "THESIS_TARGETS_PEERGROUP"

    # Review / decision
    REVIEW_HAS_DECISION = "REVIEW_HAS_DECISION"
    DECISION_FOR_COMPANY = "DECISION_FOR_COMPANY"


# ---------------------------------------------------------------------------
# Helper: stable node IDs
# ---------------------------------------------------------------------------

def node_id(node_type: NodeType, key: Any) -> str:
    """Produce a deterministic node identifier."""
    return f"{node_type.value}:{key}"


# ---------------------------------------------------------------------------
# ConsensusGraph
# ---------------------------------------------------------------------------

class ConsensusGraph:
    """In-memory directed graph mirroring Consensus relational state.

    Uses NetworkX DiGraph.  Every node carries:
        _type   – NodeType value
        _key    – original primary-key / identifier
        _ts     – timestamp of creation / last update (ISO string or None)
        ...     – additional metadata fields

    Every edge carries:
        _edge_type – EdgeType value
        ...        – additional metadata (link_type, relation_type, etc.)
    """

    def __init__(self):
        self.g: nx.DiGraph = nx.DiGraph()
        self._built_at: Optional[str] = None

    # ------------------------------------------------------------------
    # Node helpers
    # ------------------------------------------------------------------

    def add_node(
        self,
        ntype: NodeType,
        key: Any,
        *,
        ts: Optional[str] = None,
        **attrs,
    ) -> str:
        nid = node_id(ntype, key)
        self.g.add_node(nid, _type=ntype.value, _key=str(key), _ts=ts, **attrs)
        return nid

    def add_edge(
        self,
        src: str,
        dst: str,
        etype: EdgeType,
        **attrs,
    ):
        self.g.add_edge(src, dst, _edge_type=etype.value, **attrs)

    def has_node(self, ntype: NodeType, key: Any) -> bool:
        return node_id(ntype, key) in self.g

    def get_node(self, ntype: NodeType, key: Any) -> Optional[dict]:
        nid = node_id(ntype, key)
        if nid in self.g:
            return dict(self.g.nodes[nid])
        return None

    def nodes_of_type(self, ntype: NodeType) -> list[str]:
        return [n for n, d in self.g.nodes(data=True) if d.get("_type") == ntype.value]

    def edges_of_type(self, etype: EdgeType) -> list[tuple[str, str, dict]]:
        return [
            (u, v, d) for u, v, d in self.g.edges(data=True)
            if d.get("_edge_type") == etype.value
        ]

    # ------------------------------------------------------------------
    # Neighbor queries
    # ------------------------------------------------------------------

    def successors(self, nid: str, etype: Optional[EdgeType] = None) -> list[str]:
        """Nodes reachable via outgoing edges, optionally filtered by edge type."""
        results = []
        for _, dst, d in self.g.out_edges(nid, data=True):
            if etype is None or d.get("_edge_type") == etype.value:
                results.append(dst)
        return results

    def predecessors(self, nid: str, etype: Optional[EdgeType] = None) -> list[str]:
        """Nodes with incoming edges to nid, optionally filtered."""
        results = []
        for src, _, d in self.g.in_edges(nid, data=True):
            if etype is None or d.get("_edge_type") == etype.value:
                results.append(src)
        return results

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def summary(self) -> dict:
        """Return a quick summary of graph contents."""
        type_counts: dict[str, int] = {}
        for _, d in self.g.nodes(data=True):
            t = d.get("_type", "unknown")
            type_counts[t] = type_counts.get(t, 0) + 1

        edge_counts: dict[str, int] = {}
        for _, _, d in self.g.edges(data=True):
            t = d.get("_edge_type", "unknown")
            edge_counts[t] = edge_counts.get(t, 0) + 1

        return {
            "total_nodes": self.g.number_of_nodes(),
            "total_edges": self.g.number_of_edges(),
            "node_types": type_counts,
            "edge_types": edge_counts,
            "built_at": self._built_at,
        }

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Export the full graph as a JSON-serializable dict."""
        nodes = []
        for nid, d in self.g.nodes(data=True):
            node = {"id": nid}
            node.update(_sanitize(d))
            nodes.append(node)

        edges = []
        for u, v, d in self.g.edges(data=True):
            edge = {"source": u, "target": v}
            edge.update(_sanitize(d))
            edges.append(edge)

        return {
            "nodes": nodes,
            "edges": edges,
            "summary": self.summary(),
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    @classmethod
    def from_dict(cls, data: dict) -> ConsensusGraph:
        """Reconstruct a graph from exported dict."""
        cg = cls()
        for n in data.get("nodes", []):
            nid = n.pop("id")
            cg.g.add_node(nid, **n)
        for e in data.get("edges", []):
            src = e.pop("source")
            dst = e.pop("target")
            cg.g.add_edge(src, dst, **e)
        cg._built_at = data.get("summary", {}).get("built_at")
        return cg

    @classmethod
    def from_json(cls, raw: str) -> ConsensusGraph:
        return cls.from_dict(json.loads(raw))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sanitize(d: dict) -> dict:
    """Make all values JSON-serializable."""
    out = {}
    for k, v in d.items():
        if isinstance(v, (datetime, date)):
            out[k] = v.isoformat()
        elif isinstance(v, Enum):
            out[k] = v.value
        elif v is None or isinstance(v, (str, int, float, bool)):
            out[k] = v
        else:
            out[k] = str(v)
    return out
