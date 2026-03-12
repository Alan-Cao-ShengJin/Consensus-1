# Step 12.5: Operator Console & Live Observability

## What This Step Adds

A read-only operator console that makes the entire Consensus pipeline visually legible. Every panel is backed by real persisted objects — no fake summaries, no decorative AI thoughts.

Core principle: glass box, not black box. The console reads system state; it never mutates it.


## New Files

| File | Purpose |
|------|---------|
| `console_api.py` | Read-only data access layer — queries DB + graph, returns dicts |
| `console_app.py` | Flask web server with REST API endpoints |
| `static/console.html` | Single-page operator console with terminal/mission-control aesthetic |
| `scripts/run_console.py` | CLI launcher with `--demo`, `--no-graph`, `--port` options |
| `tests/test_step12_5.py` | 67 deterministic tests |
| `step12_5_notes.md` | This document |


## Console Views / Panels

### A. Live Information Feed (Tab 1)

Shows recently ingested documents in time order.

For each document:
- Timestamp, source ticker, document type, title
- Source tier (TIER_1 / TIER_2 / TIER_3)
- Claim count and novelty breakdown (NEW / CONFIRMING / CONFLICTING / REPETITIVE)
- Whether a thesis update was triggered
- Ingestion status

Data source: `Document` + `Claim` + `ThesisClaimLink` tables.

### B. Claim Extraction + Memory View (Tab 2)

Split-pane view. Left: claims extracted from a selected document. Right: linked theses, themes, and impact classification.

For each claim:
- Claim text, type, economic channel, direction, strength
- Novelty classification
- Linked tickers, themes, and theses (with link_type: supports/weakens/checkpoint)
- Full claim text and confidence score

Data source: `Claim` + `ClaimCompanyLink` + `ClaimThemeLink` + `ThesisClaimLink`.

### C. Thesis Evolution View (Tab 3)

Split-pane. Left: all theses for a selected ticker. Right: thesis detail with state timeline.

For each thesis:
- Current state, conviction score, valuation gap, base case rerating
- Summary text
- Full state evolution timeline showing state transitions and conviction deltas
- Before/after highlighting on state changes

Data source: `Thesis` + `ThesisStateHistory`.

### D. Portfolio Decision View (Tab 4)

Split-pane. Left: active positions and candidates. Right: latest review decisions.

Shows:
- Positions: ticker, weight, target, conviction, zone, probation flag
- Candidates: ticker, conviction, zone, buyable flag, watch reason
- Decisions: action (INITIATE/ADD/HOLD/TRIM/EXIT), action score, weight change, reason codes, execution status

Data source: `PortfolioPosition` + `Candidate` + `PortfolioReview` + `PortfolioDecision`.

### E. Graph / Explainability View (Tab 5)

Interactive vis.js graph centered on a selected company/ticker.

Displays nodes:
- Company, Document, Claim, Theme, Thesis, Checkpoint, ThesisStateHistory, Position, Candidate

Edges:
- All graph layer relationships (THESIS_FOR_COMPANY, CLAIM_ABOUT_COMPANY, etc.)

Uses Step 10.5 graph layer directly via `graph_visualizer.company_view()`.

Data source: `ConsensusGraph` (built from DB via `graph_sync.build_full_graph()`).

### F. Event Timeline (Tab 6)

Pipeline trace for a selected document, showing the processing stages:

```
INGEST  NVDA  8K               OK
CLAIMS  NVDA  14 extracted     NEW=4 CONF=6 REP=4
MEMORY  NVDA  14 claims / 3 themes
THESIS  NVDA  STABLE -> STRENGTHENING
SCORE   NVDA  61 -> 68
```

Data source: `Document` + `Claim` + `ClaimThemeLink` + `ThesisClaimLink` + `ThesisStateHistory`.


## API Endpoints

| Endpoint | Method | Returns |
|----------|--------|---------|
| `GET /` | GET | Console SPA (static/console.html) |
| `GET /api/status` | GET | System status counts, demo mode flag, graph status |
| `GET /api/documents/recent` | GET | Recent documents with claim/thesis status |
| `GET /api/documents/<id>` | GET | Document detail with claims, linked theses/themes |
| `GET /api/documents/<id>/timeline` | GET | Pipeline event timeline for a document |
| `GET /api/theses/<id>` | GET | Thesis detail with state history |
| `GET /api/tickers/<ticker>/theses` | GET | All theses for a ticker |
| `GET /api/reviews/latest` | GET | Latest portfolio review with decisions |
| `GET /api/positions` | GET | Active portfolio positions |
| `GET /api/candidates` | GET | All candidates |
| `GET /api/execution/latest` | GET | Latest execution intents and paper fills |
| `GET /api/tickers` | GET | All companies (for search) |
| `GET /api/tickers/<ticker>/overview` | GET | Company overview with counts |
| `GET /api/graph/company/<ticker>` | GET | Graph subgraph for a company (vis.js format) |
| `GET /api/graph/thesis/<id>` | GET | Graph subgraph for a thesis |
| `GET /api/graph/theme/<id>` | GET | Graph subgraph for a theme |

All endpoints are GET-only. POST/PUT/DELETE return 405 Method Not Allowed.


## CLI Usage

```bash
# Launch console (default: http://127.0.0.1:5000)
python scripts/run_console.py

# Custom port
python scripts/run_console.py --port 8080

# Demo mode (shows DEMO badge)
python scripts/run_console.py --demo

# Skip graph loading (faster startup, no graph tab)
python scripts/run_console.py --no-graph

# Bind to all interfaces
python scripts/run_console.py --host 0.0.0.0

# Debug mode with auto-reload
python scripts/run_console.py --debug

# Verbose logging
python scripts/run_console.py -v
```


## Demo Mode vs Real State Mode

| Mode | How selected | Data source | UI indicator |
|------|-------------|-------------|--------------|
| Real | Default | Live DB (consensus.db) | No badge |
| Demo | `--demo` flag | Same DB | Purple DEMO pill in top bar |

Demo mode reads from the same database. It is clearly labeled in the UI. The distinction is informational — the console is always read-only regardless of mode.


## Visual Design

- Dark background (#0a0a0f) with monospace typography
- Green / amber / white / red status colors
- Compact tables with hover highlighting
- Live badges: OK / WARN / BLOCK / FAIL
- Conviction bars with color coding (green > 60, amber > 40, red < 40)
- Split-pane layouts for drill-down views
- Keyboard shortcuts: 1-6 for tab switching
- Auto-refresh every 30 seconds
- UTC clock in top bar


## Drill-Down Workflow

1. See a new document in the **Feed** tab
2. Click it → auto-switches to **Claims** tab
3. See extracted claims, novelty types, strength scores
4. Click a claim → see linked theses, themes, and impact in the right panel
5. Click a thesis link → auto-switches to **Thesis** tab
6. See conviction timeline, state transitions, before/after deltas
7. Click "View in Graph" → see evidence graph with vis.js
8. Switch to **Timeline** tab → see pipeline stages for that document

This drill-down path is the primary demo flow.


## Data Sources Per Panel

| Panel | Primary table(s) | Graph layer? |
|-------|-----------------|--------------|
| Feed | Document, Claim, ThesisClaimLink | No |
| Claims | Claim, ClaimCompanyLink, ClaimThemeLink, ThesisClaimLink | No |
| Thesis | Thesis, ThesisStateHistory | No |
| Portfolio | PortfolioPosition, Candidate, PortfolioReview, PortfolioDecision | No |
| Graph | — | Yes (ConsensusGraph) |
| Timeline | Document, Claim, ClaimThemeLink, ThesisClaimLink, ThesisStateHistory | No |
| Status | All tables (counts) | Optional |


## Demo-Polish Pass (Step 12.5b)

### What Was Added

1. **"What Changed" summary card** — appears in Feed view when a document is selected. Shows new information, retrieved memory, thesis delta, recommendation delta, and a "why it matters" summary. All data sourced from real persisted objects.

2. **Guided Demo ribbon** — collapsible step indicator (Feed → Claims → Thesis → Portfolio → Graph → Timeline) toggled with "Guide" button or G key. Tracks current step with active/done highlighting.

3. **Demo subject quick-picker** — three buttons in the top bar: Latest Trigger, Thesis Delta, Actionable. Auto-selects the best demo subject from current state.

4. **Cross-linking between views** — every panel has navigation buttons to the next relevant view. Claims → Thesis → Portfolio → Graph → Timeline → Feed. Thesis links are clickable. Tickers are clickable.

5. **Enhanced event timeline** — vertical dot/line connector visualization. Colored stage dots. Timestamps and drill-down context.

6. **Narrative export** — copyable text summary of the full pipeline flow for a document, shown in the Timeline view.

7. **CLI improvements** — `--focus latest-thesis-delta|latest-actionable|latest-trigger`, `--no-auto-refresh` flags.

8. **Visual polish** — selected row highlighting, better spacing, stronger delta presentation (green/red conviction badges), cleaner empty states.

### New API Endpoints

| Endpoint | Method | Returns |
|----------|--------|---------|
| `GET /api/demo/subjects` | GET | Best demo subjects (latest trigger, thesis delta, actionable, conviction change) |
| `GET /api/documents/<id>/what-changed` | GET | What Changed summary card data |
| `GET /api/documents/<id>/narrative` | GET | Narrative pipeline steps |

### New Files

| File | Purpose |
|------|---------|
| `console_demo_guide.md` | 3–5 minute walkthrough guide with talk track |


## What Passed

All 94 Step 12.5 tests pass deterministically:

- Recent documents: returns docs, claim counts, novelty counts, thesis trigger flag
- Document detail: claims present, linked tickers/themes/theses, claim fields correct
- Thesis detail: returns thesis, has history, ordered timeline, conviction scores
- Ticker theses: returns theses for known ticker, empty for unknown
- Portfolio review: latest review, sorted decisions, reason codes, no-review case
- Positions and candidates: correct data returned
- Company overview: correct counts, owned/candidate flags
- System status: correct counts, empty DB case
- Event timeline: INGEST, CLAIMS, MEMORY, THESIS stages present
- All tickers: sorted, complete
- Graph integration: summary, empty view, view with data
- Flask routes: all endpoints return correct status codes
- Read-only enforcement: POST/PUT/DELETE return 405, data unchanged after reads
- Serialization: None, enum, datetime, date, string handling
- Demo subjects: all keys present, correct thesis delta/actionable/trigger/conviction
- What Changed: document field, claims, themes, thesis delta, recommendation delta, why_it_matters
- Narrative export: all stages present, ingest has title, claims has count, recommendation stage
- Demo polish routes: all endpoints return correct status, demo/real mode labeled


## Hard Constraints Maintained

- Console is read-only — no mutations to system state
- No POST/PUT/DELETE endpoints
- No fake AI summaries or decorative chain-of-thought
- Every visible value maps to a real persisted object
- Demo mode is clearly labeled
- No new business logic — data access only
- No weakened guardrails
- Decision engine unchanged
- Existing tests unaffected
