# Step 10.5: Graph-Native Memory Layer & Visual Knowledge Graph

## What This Step Adds

A graph layer on top of the existing relational core that mirrors system state into a NetworkX directed graph. This improves:

- **Explainability** — "Why do we own NVDA?" answered by traversing real graph objects
- **Retrieval power** — Multi-hop queries across companies, claims, themes, theses
- **Inspectability** — Visual knowledge graph artifact for demos and auditing
- **Marketability** — Interactive HTML visualization of the system's memory

This does NOT replace the relational DB. It is a mirrored layer.

## New Files

| File | Purpose |
|------|---------|
| `graph_memory.py` | Core graph model: NodeType, EdgeType, ConsensusGraph (NetworkX wrapper) |
| `graph_sync.py` | Build/refresh graph from DB: full rebuild, ticker-scoped, export |
| `graph_queries.py` | Explainability queries: why_own, thesis_evidence, evolution, themes |
| `graph_visualizer.py` | HTML/JSON visual artifact generation using vis.js |
| `scripts/build_graph.py` | CLI: build and export graph |
| `scripts/query_graph.py` | CLI: query graph for explainability |
| `tests/test_step10_5.py` | 60+ deterministic tests |


## Objects Represented

### Node Types

| Node Type | Source Object | Key |
|-----------|--------------|-----|
| Company | `companies` table | `ticker` |
| Document | `documents` table | `id` |
| Claim | `claims` table | `id` |
| Theme | `themes` table | `id` |
| Thesis | `theses` table | `id` |
| Checkpoint | `checkpoints` table | `id` |
| ThesisStateHistory | `thesis_state_history` table | `id` |
| PortfolioPosition | `portfolio_positions` table | `id` |
| Candidate | `candidates` table | `id` |
| PeerGroup | `peer_groups` table | `id` |
| PortfolioReview | `portfolio_reviews` table | `id` |
| PortfolioDecision | `portfolio_decisions` table | `id` |

### Edge Types

| Edge Type | From → To | Source |
|-----------|-----------|--------|
| DOCUMENT_HAS_CLAIM | Document → Claim | `claims.document_id` FK |
| DOCUMENT_ABOUT_COMPANY | Document → Company | `documents.primary_company_ticker` FK |
| CLAIM_ABOUT_COMPANY | Claim → Company | `claim_company_links` table |
| CLAIM_SUPPORTS_THEME | Claim → Theme | `claim_theme_links` table |
| CLAIM_LINKED_TO_THESIS | Claim → Thesis | `thesis_claim_links` table |
| THESIS_FOR_COMPANY | Thesis → Company | `theses.company_ticker` FK |
| THESIS_HAS_CHECKPOINT | Thesis → Checkpoint | `theses.checkpoint_next_id` FK |
| THESIS_HAS_STATE | Thesis → ThesisStateHistory | `thesis_state_history.thesis_id` FK |
| THESIS_LINKED_TO_THEME | Thesis → Theme | `thesis_theme_links` table |
| THESIS_TARGETS_PEERGROUP | Thesis → PeerGroup | `theses.peer_group_target_id` FK |
| POSITION_FOR_COMPANY | Position → Company | `portfolio_positions.ticker` FK |
| POSITION_LINKED_TO_THESIS | Position → Thesis | `portfolio_positions.thesis_id` FK |
| CANDIDATE_FOR_COMPANY | Candidate → Company | `candidates.ticker` FK |
| CANDIDATE_LINKED_TO_THESIS | Candidate → Thesis | `candidates.primary_thesis_id` FK |
| COMPANY_IN_PEERGROUP | Company → PeerGroup | `company_peer_group_links` table |
| REVIEW_HAS_DECISION | Review → Decision | `portfolio_decisions.review_id` FK |
| DECISION_FOR_COMPANY | Decision → Company | `portfolio_decisions.ticker` FK |

Every edge maps to a real FK or link-table row. No inferred or fabricated edges.


## How It Syncs from Relational State

### Deterministic sync path

```
relational objects → graph nodes/edges → exported artifact
```

### Full rebuild

```python
from graph_sync import build_full_graph
from db import get_session

with get_session() as session:
    cg = build_full_graph(session)
```

Queries all tables, creates nodes with metadata, creates edges from FKs and link tables.

### Ticker-scoped build

```python
from graph_sync import build_ticker_graph

with get_session() as session:
    cg = build_ticker_graph(session, "NVDA")
```

Builds only the subgraph relevant to one company: its documents, claims, theses, state history, positions, candidates, and connected themes/checkpoints.

### Export

```python
from graph_sync import export_graph
export_graph(cg, "artifacts/graph/2025-03-01", "full_graph")
```


## Queries and Views Supported

### Explainability queries (`graph_queries.py`)

| Query | Function | What it returns |
|-------|----------|----------------|
| Why do we own X? | `why_own(cg, ticker)` | Positions, candidates, theses, recent claims |
| What evidence supports thesis? | `thesis_evidence(cg, thesis_id)` | Supporting, weakening, checkpoint, context claims |
| How did thesis evolve? | `thesis_evolution(cg, thesis_id)` | Ordered state history with conviction scores |
| What themes connect to X? | `themes_for_company(cg, ticker)` | All themes via theses + claims |
| Which companies share a theme? | `companies_sharing_theme(cg, theme_id)` | Companies linked via thesis-theme or claim-theme |
| Shared themes between X and Y? | `cross_company_themes(cg, a, b)` | Intersection of theme sets |
| Documents driving a thesis? | `documents_for_thesis(cg, thesis_id)` | Documents with claims linked to thesis |
| State transition explanation | `explain_state_transition(cg, id, from, to)` | Path + linked claims |
| Company summary | `company_summary(cg, ticker)` | Counts: docs, claims, theses, positions, themes |

### Subgraph views (`graph_visualizer.py`)

| View | Function |
|------|----------|
| Company-centered | `company_view(cg, ticker, depth=2)` |
| Thesis-centered | `thesis_view(cg, thesis_id, depth=2)` |
| Theme-centered | `theme_view(cg, theme_id, depth=2)` |
| Thesis evolution timeline | `thesis_evolution_view(cg, thesis_id)` |


## What Is Visualized

### Standalone HTML artifact

Uses vis.js (loaded from CDN) to render an interactive force-directed graph:

- Nodes colored and shaped by type (Company=blue diamond, Thesis=green star, etc.)
- Edges colored by type
- Hover tooltips with metadata
- Search/filter box
- Legend showing all node types
- Node/edge counts in header

### Export formats

| Format | File | Use case |
|--------|------|----------|
| Graph JSON | `graph.json` | Serialized ConsensusGraph for programmatic use |
| Vis.js JSON | `vis_graph.json` | Frontend rendering with any vis.js-compatible app |
| Standalone HTML | `graph.html` | Open in browser, no server needed |


## CLI Usage

### Build graph

```bash
# Full graph rebuild
python scripts/build_graph.py --full

# Single ticker
python scripts/build_graph.py --ticker NVDA

# With HTML visualization
python scripts/build_graph.py --full --export-html

# Custom output directory
python scripts/build_graph.py --full --output-dir artifacts/graph/custom

# Thesis-centered view
python scripts/build_graph.py --thesis-id 12 --export-html
```

### Query graph

```bash
# Why do we own a stock?
python scripts/query_graph.py --why-own NVDA

# Thesis evolution
python scripts/query_graph.py --thesis-evolution NVDA

# Thesis evidence
python scripts/query_graph.py --thesis-evidence 12

# Company summary
python scripts/query_graph.py --company-summary NVDA

# Themes
python scripts/query_graph.py --themes NVDA

# Cross-company themes
python scripts/query_graph.py --cross-themes NVDA MSFT

# State transition
python scripts/query_graph.py --state-transition 12 --from-state stable --to-state weakening

# JSON output
python scripts/query_graph.py --why-own NVDA --json
```


## Artifact Output

```
artifacts/
  graph/
    2025-03-01/
      full_graph.json          # Complete graph export
      full_graph.html          # Interactive HTML visualization
      ticker_NVDA.json         # Ticker-scoped graph
      ticker_NVDA.html         # Ticker-scoped HTML
```


## What This Improves

### Operationally
- Audit trail traversal: trace any thesis back through claims to source documents
- State history inspection: see exactly how and when a thesis evolved
- Cross-company analysis: identify shared thematic exposures across the portfolio

### Commercially
- Visual knowledge graph is immediately demo-able in a browser
- "Why do we own X?" is a concrete, explainable output
- Graph representation makes the system's memory tangible and inspectable


## Graph Backend

Uses **NetworkX** (already installed, v3.3):
- In-memory directed graph
- No external infrastructure required
- Deterministic build from DB state
- Full JSON serialization/deserialization
- Subgraph extraction for focused views

### On Graphiti

Graphiti integration is **not included** in this step. The system gets a real, useful graph layer faster with NetworkX + vis.js. Graphiti can be added later as an optional backend if:
- The graph needs to be persisted in a dedicated graph DB
- Temporal graph queries become important at scale
- The team wants Graphiti-specific features (episodic memory, entity resolution)

The current architecture is modular: `ConsensusGraph` wraps NetworkX and can be extended to delegate to other backends without changing the query or visualization layer.


## Hard Constraints Maintained

- Relational core is untouched
- Thesis update engine is unchanged
- Replay / execution / orchestration unaffected
- No fabricated edges — every edge traces to a real FK or link-table row
- No toy "AI agent" demo — connected to real system objects
- No giant frontend app — single HTML file with vis.js CDN
