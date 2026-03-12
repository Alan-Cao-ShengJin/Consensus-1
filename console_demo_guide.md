# Consensus Operator Console — Demo Guide

## Quick Launch

```bash
# Real state mode (default)
python scripts/run_console.py

# Demo mode (DEMO badge shown)
python scripts/run_console.py --demo

# Demo mode, skip graph, custom port
python scripts/run_console.py --demo --no-graph --port 8080

# Pre-focus on best demo subject
python scripts/run_console.py --demo --focus latest-thesis-delta

# Disable auto-refresh during presentation
python scripts/run_console.py --demo --no-auto-refresh
```

Open: `http://127.0.0.1:5000`


## DEMO vs REAL Mode

| Mode | Flag | UI Indicator |
|------|------|-------------|
| Real | (default) | No badge — shows live state |
| Demo | `--demo` | Purple DEMO pill in top bar |

Both modes are read-only. Demo mode simply adds a visible badge so the audience knows.


## The 3–5 Minute Walkthrough

Press **G** to open the guided demo ribbon, or click **Guide** in the nav bar.

### Step 1: Feed (30 sec)

> "This is the live information feed. Every document that enters the system — earnings filings, analyst reports, press releases — appears here with its claim count and novelty breakdown."

- Point to the status cards: companies, documents, claims, theses
- Show a document with **THESIS: YES** — this one triggered a thesis update
- **Click that document** to drill in

### Step 2: Claims (45 sec)

> "The system extracted N claims from this document. Each claim has a type, economic channel, direction, and novelty classification."

- The left panel shows extracted claims
- Click a claim with novelty type **NEW** to show impact
- Point out the right panel: linked theses, themes, affected tickers
- Show the **supports/weakens** link type badge

> "This claim supports the existing AI dominance thesis for NVDA."

- Click **Thesis →** to follow the link

### Step 3: Thesis (60 sec)

> "Here's the thesis evolution. Watch the state timeline — the thesis moved from FORMING to STRENGTHENING after these claims came in."

- Point to the conviction bar and delta: +22
- Show the state evolution table with highlighted row for the state change
- Point out before/after conviction scores

> "Conviction went from 50 to 72 based on confirmed data center demand."

- Click **Portfolio →** to see the recommendation

### Step 4: Portfolio (45 sec)

> "The portfolio decision engine saw this thesis strengthening and recommended ADD with a score of 75."

- Show active positions with weight, conviction, zone
- Show the decisions table: action, score, weight change, reason codes
- Point to **THESIS_STRENGTHENING** and **VALUATION_ATTRACTIVE** reason badges
- Show execution status: YES = executed

### Step 5: Graph (30 sec)

> "The graph shows the full evidence chain — from the company node through documents, claims, themes, and theses."

- The graph auto-loads for the selected ticker
- Point out the node types: Company, Thesis, Claim, Theme, Document
- Hover over edges to show relationship labels

### Step 6: Timeline (30 sec)

> "Finally, the event timeline shows every pipeline stage this document went through."

- Show the vertical timeline: INGEST → CLAIMS → MEMORY → THESIS → SCORE → RECOMMENDATION → GRAPH
- Point to the narrative export at the bottom — copyable summary of the full flow

### Closing (15 sec)

> "Everything you just saw is grounded in real persisted objects. No fake summaries, no decorative AI thoughts. The console reads system state; it never mutates it."

Switch back to Feed. Point to the **What Changed** card that appeared when you selected the document.

> "This card answers: what came in, what the system remembered, how the thesis changed, and what action was recommended. Glass box, not black box."


## Quick-Pick Demo Subjects

Use the **Quick** buttons in the top bar:

| Button | Selects |
|--------|---------|
| **Latest Trigger** | Most recent document that triggered a thesis update |
| **Thesis Delta** | Most recent thesis with a state change |
| **Actionable** | Most recent non-HOLD recommendation |

These select real objects from current state. No curation needed.


## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| 1–6 | Switch to Feed / Claims / Thesis / Portfolio / Graph / Timeline |
| G | Toggle guided demo ribbon |


## What Changed Card

When you select a document, the **What Changed** card appears in the Feed view. It shows:

- **New Information**: Claims extracted from the document
- **Retrieved Memory**: Themes linked to those claims
- **Thesis Delta**: Before/after state and conviction for linked theses
- **Recommendation Delta**: Portfolio decisions for affected tickers
- **Why It Matters**: One-line summary

Each section has cross-link buttons to jump to the relevant view.


## Narrative Export

In the Timeline view, a **Demo Narrative** panel appears with a copyable text summary of the full pipeline flow. Use this to prep talking points or paste into notes.


## Tips for a Smooth Demo

1. **Pre-select a subject** with Quick buttons before the audience arrives
2. **Open the guide ribbon** so you remember the flow
3. **Disable auto-refresh** with `--no-auto-refresh` to prevent table flicker
4. **Use keyboard shortcuts** (1–6) for fast tab switching during the walkthrough
5. **Click the What Changed card buttons** to naturally flow between views
6. **End on the Feed** to show the card — it's the most visually compelling panel
