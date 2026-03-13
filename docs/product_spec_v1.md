# Product Spec v1 — Consensus-1

## What This Is

A monitored-universe public-equity intelligence system that continuously ingests public information, converts it into structured claims with durable provenance, stores persistent memory by company and theme, and updates thesis state over time. Later stages drive replayable, explainable portfolio decisions.

## Target User / Operator

A single operator (portfolio manager or research lead) managing a concentrated equity portfolio (~8–15 positions) drawn from a monitored universe of ~45 US-domiciled large-cap names. The operator uses the system to:

- Maintain persistent, structured memory about each company and theme
- Receive thesis-level conviction updates grounded in evidence, not vibes
- Understand *why* a thesis changed, with traceable provenance back to source documents
- Make portfolio decisions supported by deterministic scoring and explainable rules

The system is a decision-support tool, not an autonomous trading agent.

## Monitored Universe

- ~45 US-domiciled public equities (defined in `source_registry.UNIVERSE_TICKERS`)
- Primarily large-cap technology, semiconductors, cloud/SaaS, fintech, healthcare, energy, defense, financials
- Universe is curated manually; additions/removals are operator decisions
- All tickers must have reliable SEC filing coverage and price data

## Core System Outputs

| Output | Description |
|--------|-------------|
| **Structured claims** | Typed, directional, scored evidence extracted from documents with full provenance |
| **Novelty classification** | Each claim classified as new, confirming, conflicting, or repetitive vs. prior memory |
| **Evidence scores** | Deterministic per-claim scores considering source tier, freshness, duplication, and contradiction |
| **Thesis state** | Per-company thesis with state (forming → strengthening → stable → weakening → broken) and conviction score (0–100) |
| **Memory snapshots** | Bounded, prioritized prior context retrieved for each thesis update |
| **Portfolio decisions** | Deterministic recommendations (initiate/add/hold/trim/exit) with reason codes and blocking conditions |
| **Audit trail** | Complete provenance chain: document → claims → evidence scores → thesis update → portfolio decision |

## What "Good" Looks Like for v1

1. **Evidence is trustworthy**: Claims have provenance. Duplicate events don't overcount. Stale evidence is downweighted. Source quality matters.
2. **Memory is bounded and predictable**: Thesis updates retrieve a known budget of prior claims, prioritized by relevance, with deterministic ordering.
3. **Thesis updates are explainable**: Every conviction change traces back to specific claims, their evidence scores, and the scoring formula.
4. **The system is honest about uncertainty**: LLMs interpret; code decides. Scoring, state transitions, and retrieval policy are deterministic.
5. **Replay produces the same result**: Given the same DB state and inputs, the system produces identical outputs.

## Explicit Non-Goals (v1)

- **No live trading execution** — paper mode only
- **No open-ended AI reasoning** — LLMs extract and classify; they don't own scoring or state rules
- **No real-time streaming** — batch/pull-based ingestion on schedules
- **No cross-asset or macro** — single equity universe, no fixed income/commodities/FX
- **No social media / alternative data** — public filings, news, and transcripts only
- **No frontend required for correctness** — the console is observability, not a control plane
- **No multi-user / auth** — single operator system
- **No automated universe expansion** — operator curates the ticker list manually
