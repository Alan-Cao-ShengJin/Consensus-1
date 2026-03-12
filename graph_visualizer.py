"""Visual knowledge graph artifact generation.

Produces:
  1. JSON suitable for frontend graph rendering (D3, vis.js, Cytoscape)
  2. Standalone HTML visualization using vis.js (no server required)

Supports views:
  - Full graph
  - Company-centered
  - Thesis-centered
  - Theme-centered
  - Thesis evolution timeline
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

from graph_memory import ConsensusGraph, NodeType, EdgeType, node_id

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Color / shape scheme
# ---------------------------------------------------------------------------

NODE_STYLES = {
    "Company":            {"color": "#4A90D9", "shape": "diamond", "size": 30},
    "Document":           {"color": "#7B8D8E", "shape": "square",  "size": 12},
    "Claim":              {"color": "#F5A623", "shape": "dot",     "size": 10},
    "Theme":              {"color": "#9B59B6", "shape": "triangle", "size": 22},
    "Thesis":             {"color": "#2ECC71", "shape": "star",    "size": 25},
    "Checkpoint":         {"color": "#E74C3C", "shape": "diamond", "size": 15},
    "ThesisStateHistory": {"color": "#1ABC9C", "shape": "dot",     "size": 10},
    "PortfolioPosition":  {"color": "#3498DB", "shape": "square",  "size": 18},
    "Candidate":          {"color": "#E67E22", "shape": "square",  "size": 16},
    "PeerGroup":          {"color": "#95A5A6", "shape": "triangle", "size": 18},
    "PortfolioReview":    {"color": "#34495E", "shape": "square",  "size": 14},
    "PortfolioDecision":  {"color": "#8E44AD", "shape": "dot",     "size": 12},
}

EDGE_COLORS = {
    "DOCUMENT_HAS_CLAIM":       "#7B8D8E",
    "CLAIM_ABOUT_COMPANY":      "#F5A623",
    "CLAIM_SUPPORTS_THEME":     "#9B59B6",
    "CLAIM_LINKED_TO_THESIS":   "#2ECC71",
    "THESIS_FOR_COMPANY":       "#4A90D9",
    "THESIS_HAS_CHECKPOINT":    "#E74C3C",
    "THESIS_HAS_STATE":         "#1ABC9C",
    "THESIS_LINKED_TO_THEME":   "#9B59B6",
    "DOCUMENT_ABOUT_COMPANY":   "#7B8D8E",
    "POSITION_LINKED_TO_THESIS": "#3498DB",
    "POSITION_FOR_COMPANY":     "#3498DB",
    "CANDIDATE_LINKED_TO_THESIS": "#E67E22",
    "CANDIDATE_FOR_COMPANY":    "#E67E22",
    "COMPANY_IN_PEERGROUP":     "#95A5A6",
    "THESIS_TARGETS_PEERGROUP": "#95A5A6",
    "REVIEW_HAS_DECISION":      "#34495E",
    "DECISION_FOR_COMPANY":     "#8E44AD",
}


# ---------------------------------------------------------------------------
# JSON export (for frontend rendering)
# ---------------------------------------------------------------------------

def graph_to_vis_json(cg: ConsensusGraph) -> dict:
    """Export graph as vis.js-compatible JSON with styling."""
    nodes = []
    for nid, data in cg.g.nodes(data=True):
        ntype = data.get("_type", "unknown")
        style = NODE_STYLES.get(ntype, {"color": "#ccc", "shape": "dot", "size": 10})
        label = _node_label(nid, data)
        nodes.append({
            "id": nid,
            "label": label,
            "group": ntype,
            "color": style["color"],
            "shape": style["shape"],
            "size": style["size"],
            "title": _node_tooltip(data),
        })

    edges = []
    for i, (u, v, data) in enumerate(cg.g.edges(data=True)):
        etype = data.get("_edge_type", "unknown")
        edges.append({
            "id": f"e{i}",
            "from": u,
            "to": v,
            "label": etype.replace("_", " ").title() if len(etype) < 30 else "",
            "color": EDGE_COLORS.get(etype, "#999"),
            "arrows": "to",
            "title": etype,
        })

    return {"nodes": nodes, "edges": edges}


def export_vis_json(cg: ConsensusGraph, output_path: str) -> str:
    """Write vis.js JSON to file."""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    data = graph_to_vis_json(cg)
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    logger.info("Vis JSON exported to %s", output_path)
    return output_path


# ---------------------------------------------------------------------------
# Standalone HTML
# ---------------------------------------------------------------------------

def export_html(cg: ConsensusGraph, output_path: str, title: str = "Consensus Knowledge Graph") -> str:
    """Generate a standalone HTML file with an interactive vis.js graph."""
    vis_data = graph_to_vis_json(cg)
    nodes_json = json.dumps(vis_data["nodes"], default=str)
    edges_json = json.dumps(vis_data["edges"], default=str)

    # Build legend
    legend_items = []
    seen_types = set()
    for n in vis_data["nodes"]:
        g = n["group"]
        if g not in seen_types:
            seen_types.add(g)
            style = NODE_STYLES.get(g, {"color": "#ccc"})
            legend_items.append(
                f'<span style="color:{style["color"]};font-weight:bold;">&#9679;</span> {g}'
            )
    legend_html = " &nbsp;&middot;&nbsp; ".join(legend_items)

    html = _HTML_TEMPLATE.replace("{{TITLE}}", title)
    html = html.replace("{{NODES_JSON}}", nodes_json)
    html = html.replace("{{EDGES_JSON}}", edges_json)
    html = html.replace("{{LEGEND}}", legend_html)
    html = html.replace("{{NODE_COUNT}}", str(len(vis_data["nodes"])))
    html = html.replace("{{EDGE_COUNT}}", str(len(vis_data["edges"])))

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    logger.info("HTML visualization exported to %s", output_path)
    return output_path


# ---------------------------------------------------------------------------
# Subgraph views
# ---------------------------------------------------------------------------

def company_view(cg: ConsensusGraph, ticker: str, depth: int = 2) -> ConsensusGraph:
    """Extract a subgraph centered on a company, up to `depth` hops."""
    center = node_id(NodeType.COMPANY, ticker)
    if center not in cg.g:
        return ConsensusGraph()

    # BFS in undirected view
    visited = set()
    frontier = {center}
    for _ in range(depth):
        next_frontier = set()
        for n in frontier:
            if n not in visited:
                visited.add(n)
                next_frontier.update(cg.g.successors(n))
                next_frontier.update(cg.g.predecessors(n))
        frontier = next_frontier - visited
    visited.update(frontier)

    return _subgraph(cg, visited)


def thesis_view(cg: ConsensusGraph, thesis_id: int, depth: int = 2) -> ConsensusGraph:
    """Extract a subgraph centered on a thesis."""
    center = node_id(NodeType.THESIS, thesis_id)
    if center not in cg.g:
        return ConsensusGraph()

    visited = set()
    frontier = {center}
    for _ in range(depth):
        next_frontier = set()
        for n in frontier:
            if n not in visited:
                visited.add(n)
                next_frontier.update(cg.g.successors(n))
                next_frontier.update(cg.g.predecessors(n))
        frontier = next_frontier - visited
    visited.update(frontier)

    return _subgraph(cg, visited)


def theme_view(cg: ConsensusGraph, theme_id: int, depth: int = 2) -> ConsensusGraph:
    """Extract a subgraph centered on a theme."""
    center = node_id(NodeType.THEME, theme_id)
    if center not in cg.g:
        return ConsensusGraph()

    visited = set()
    frontier = {center}
    for _ in range(depth):
        next_frontier = set()
        for n in frontier:
            if n not in visited:
                visited.add(n)
                next_frontier.update(cg.g.successors(n))
                next_frontier.update(cg.g.predecessors(n))
        frontier = next_frontier - visited
    visited.update(frontier)

    return _subgraph(cg, visited)


def thesis_evolution_view(cg: ConsensusGraph, thesis_id: int) -> ConsensusGraph:
    """Extract thesis + its state history nodes + company."""
    tid = node_id(NodeType.THESIS, thesis_id)
    if tid not in cg.g:
        return ConsensusGraph()

    nodes = {tid}
    # State history
    for dst in cg.successors(tid, EdgeType.THESIS_HAS_STATE):
        nodes.add(dst)
    # Company
    for dst in cg.successors(tid, EdgeType.THESIS_FOR_COMPANY):
        nodes.add(dst)
    # Claims
    for src in cg.predecessors(tid, EdgeType.CLAIM_LINKED_TO_THESIS):
        nodes.add(src)
    # Checkpoint
    for dst in cg.successors(tid, EdgeType.THESIS_HAS_CHECKPOINT):
        nodes.add(dst)

    return _subgraph(cg, nodes)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _subgraph(cg: ConsensusGraph, nodes: set[str]) -> ConsensusGraph:
    """Create a new ConsensusGraph from a subset of nodes."""
    sub = ConsensusGraph()
    sub._built_at = cg._built_at
    sg = cg.g.subgraph(nodes)
    sub.g = sg.copy()
    return sub


def _node_label(nid: str, data: dict) -> str:
    ntype = data.get("_type", "")
    if ntype == "Company":
        return data.get("_key", nid)
    elif ntype == "Thesis":
        title = data.get("title", "")
        return title[:30] + "..." if len(title) > 30 else title
    elif ntype == "Theme":
        return data.get("theme_name", nid)[:25]
    elif ntype == "Document":
        title = data.get("title", "doc")
        return title[:25] + "..." if len(str(title)) > 25 else str(title)
    elif ntype == "Claim":
        txt = data.get("claim_text_short", "claim")
        return str(txt)[:20] + "..." if len(str(txt)) > 20 else str(txt or "claim")
    elif ntype == "Checkpoint":
        return data.get("name", "checkpoint")[:20]
    elif ntype == "ThesisStateHistory":
        return f"{data.get('state', '?')} ({data.get('conviction_score', '?')})"
    elif ntype == "PeerGroup":
        return data.get("name", "peer")[:20]
    elif ntype == "PortfolioPosition":
        return f"Pos:{data.get('ticker', '?')}"
    elif ntype == "Candidate":
        return f"Cand:{data.get('ticker', '?')}"
    elif ntype == "PortfolioDecision":
        return f"{data.get('action', '?')} {data.get('ticker', '?')}"
    else:
        return nid[:20]


def _node_tooltip(data: dict) -> str:
    parts = []
    for k, v in data.items():
        if k.startswith("_") or v is None:
            continue
        parts.append(f"{k}: {v}")
    return "\n".join(parts[:10])


# ---------------------------------------------------------------------------
# HTML template (vis.js via CDN)
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{TITLE}}</title>
<script src="https://unpkg.com/vis-network@9.1.6/standalone/umd/vis-network.min.js"></script>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         background: #0a0a0f; color: #e0e0e0; }
  #header { padding: 16px 24px; background: #12121a; border-bottom: 1px solid #2a2a3a;
            display: flex; justify-content: space-between; align-items: center; }
  #header h1 { font-size: 18px; font-weight: 600; color: #fff; }
  #stats { font-size: 13px; color: #888; }
  #legend { padding: 8px 24px; background: #12121a; font-size: 12px; color: #aaa;
            border-bottom: 1px solid #2a2a3a; }
  #graph { width: 100%; height: calc(100vh - 90px); }
  #search-box { padding: 4px 8px; background: #1a1a2e; border: 1px solid #333;
                color: #fff; border-radius: 4px; font-size: 13px; width: 200px; }
</style>
</head>
<body>
<div id="header">
  <h1>{{TITLE}}</h1>
  <div style="display:flex;align-items:center;gap:12px;">
    <input id="search-box" type="text" placeholder="Search nodes..." />
    <span id="stats">{{NODE_COUNT}} nodes &middot; {{EDGE_COUNT}} edges</span>
  </div>
</div>
<div id="legend">{{LEGEND}}</div>
<div id="graph"></div>
<script>
var nodesData = {{NODES_JSON}};
var edgesData = {{EDGES_JSON}};

var nodes = new vis.DataSet(nodesData);
var edges = new vis.DataSet(edgesData);
var container = document.getElementById('graph');
var data = { nodes: nodes, edges: edges };
var options = {
  physics: {
    solver: 'forceAtlas2Based',
    forceAtlas2Based: { gravitationalConstant: -40, centralGravity: 0.005,
                        springLength: 120, springConstant: 0.04 },
    stabilization: { iterations: 200 }
  },
  interaction: { hover: true, tooltipDelay: 100, navigationButtons: true },
  edges: { smooth: { type: 'continuous' }, font: { size: 9, color: '#666' } },
  nodes: { font: { color: '#eee', size: 11 }, borderWidth: 1, borderWidthSelected: 3 }
};
var network = new vis.Network(container, data, options);

document.getElementById('search-box').addEventListener('input', function(e) {
  var q = e.target.value.toLowerCase();
  if (!q) { nodes.forEach(function(n) { nodes.update({id: n.id, hidden: false}); }); return; }
  nodes.forEach(function(n) {
    var match = n.label.toLowerCase().includes(q) || n.id.toLowerCase().includes(q);
    nodes.update({id: n.id, hidden: !match, opacity: match ? 1 : 0.1});
  });
});
</script>
</body>
</html>"""
