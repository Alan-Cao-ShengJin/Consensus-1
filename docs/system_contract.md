# System Contract v1 — Consensus-1

This document defines the foundational contracts for the evidence/memory layer. Every component that reads or writes claims, evidence, memory, or thesis state must honor these rules.

---

## 1. What Counts as a Document

A **document** is a discrete unit of public information that enters the system through a registered source. It must have:

| Required | Field | Notes |
|----------|-------|-------|
| Yes | `source_type` | One of the defined `SourceType` enum values |
| Yes | `source_tier` | Tier 1 (primary), Tier 2 (reputable secondary), Tier 3 (weaker commentary) |
| Yes | `ingested_at` | UTC timestamp of when the system received it |
| Recommended | `published_at` | When the source published it (used for freshness scoring) |
| Recommended | `url` or `hash` | For deduplication |
| Recommended | `source_key` + `external_id` | For connector-level deduplication |

Documents are **immutable after ingestion**. The system never modifies a document's raw text or metadata after initial persistence.

---

## 2. What Counts as a Claim

A **claim** is a single, typed assertion extracted from a document. Claims are the atomic unit of evidence in the system. Each claim must have:

| Field | Contract |
|-------|----------|
| `claim_text_normalized` | The full claim text, normalized for comparison |
| `claim_text_short` | A human-readable summary (≤100 chars) |
| `claim_type` | One of: demand, pricing, margin, capacity, guidance, regulation, competition, capital_allocation, inventory, customer_behavior, supply_chain |
| `economic_channel` | How this claim affects financials: revenue, gross_margin, opex, earnings, multiple, sentiment, liquidity, timing |
| `direction` | positive, negative, mixed, neutral |
| `strength` | 0.0–1.0, how strong the assertion is |
| `novelty_type` | new, confirming, conflicting, repetitive — classified *after* extraction against prior DB state |
| `confidence` | 0.0–1.0, extraction confidence |
| `document_id` | FK to the source document (provenance) |
| `published_at` | Inherited from document if not set (used for freshness) |

**Claim ownership**: Claims are always extracted by the claim extractor (stub or LLM). The LLM proposes claim content; deterministic code validates, classifies novelty, and scores evidence weight.

---

## 3. What Counts as Evidence

**Evidence** is a claim with a computed evidence score. The evidence score is deterministic and considers:

1. **Source tier weight**: Tier 1 = 1.0, Tier 2 = 0.7, Tier 3 = 0.4
2. **Freshness**: Claims decay over time. A claim from today is worth more than a claim from 6 months ago.
3. **Novelty**: New evidence > confirming > conflicting > repetitive
4. **Duplicate-event penalty**: Multiple articles covering the same real-world event are collapsed. The first article gets full weight; subsequent articles in the same event cluster get a steep penalty.
5. **Contradiction awareness**: If a claim contradicts prior claims on the same topic for the same company, this is tracked and the contradiction metadata is preserved.

Evidence scores are computed in `evidence_scoring.py` and consumed by `thesis_update_service.py`. They are **never** computed by the LLM.

---

## 4. What Memory Is

**Memory** is the bounded, structured prior context retrieved before a thesis update. Memory is not a general-purpose knowledge store — it is specifically scoped to what the thesis update needs.

### Retrieval priority (highest first):
1. **Thesis-linked claims** — claims previously linked to this thesis via `thesis_claim_links`
2. **Same-company claims** — recent claims about the same company (not already thesis-linked)
3. **Same-theme claims** — claims sharing a theme with the thesis (not already fetched)
4. **Checkpoints** — upcoming earnings, product launches, regulatory dates

### Retrieval budget (per thesis update):
| Category | Default limit | Ordering |
|----------|--------------|----------|
| Thesis-linked claims | 10 | Most recent first (by `published_at`) |
| Company claims | 5 | Most recent first |
| Theme claims | 5 | Most recent first |
| State history | 5 | Most recent first |
| Checkpoints | 3 | Nearest date first |

**Total memory budget**: ≤28 items per thesis update. This is a hard ceiling, not a target.

### Determinism guarantee:
For the same DB state and the same thesis ID, `retrieve_memory()` always returns the same snapshot with the same ordering. This is enforced by deterministic SQL ordering (`published_at DESC`, then `id DESC` for tie-breaking).

---

## 5. Company / Theme Linkage Rules

### Company linkage (`claim_company_links`):
- Every claim must be linked to at least one company
- The `relation_type` field specifies: `about` (primary subject), `affects` (secondary impact), `peer`, `supplier`, `customer`
- A claim can link to multiple companies (e.g., "NVDA gaining share from INTC")

### Theme linkage (`claim_theme_links`):
- Themes are created on demand during claim extraction
- A claim can link to zero or more themes
- Theme names are unique and case-sensitive
- Themes are persistent — once created, they accumulate claims over time

### Thesis linkage (`thesis_claim_links`):
- Created when claims are assessed against a thesis
- `link_type`: `supports`, `weakens`, `checkpoint`, `context`
- A claim can support one thesis and weaken another

---

## 6. Thesis State vs. Investability / Recommendation

These are **separate concepts** with a one-way dependency:

| Concept | Owned by | Updated by |
|---------|----------|------------|
| **Thesis state** | `thesis_update_service` | Evidence from claims + conviction scoring |
| **Investability / recommendation** | `portfolio_decision_engine` | Thesis state + valuation + position context |

### Thesis state lifecycle:
```
forming → strengthening → stable → weakening → probation → broken
                                  → achieved
```

### State transition rules:
- Score ≤ 15 → `broken` (hard guardrail, always applies)
- Score ≤ 30 → `probation` (hard guardrail)
- Sentiment-direction flips (bullish ↔ bearish) require `score_delta > 3.0` to prevent oscillation
- LLM recommends a state; deterministic code resolves it with guardrails

### Conviction score (0–100):
- Updated by `compute_claim_delta()` and `apply_conviction_update()`
- Per-document cap: ±15 points maximum per ingestion batch
- Dampened at extremes (sigmoid-inspired): full effect near 50, reduced near 0/100
- Formula: `base × materiality × novelty_mult × confidence × source_tier_weight`

---

## 7. Provenance Requirements

Every claim/evidence must support drilldown to answer:

| Question | Field(s) |
|----------|----------|
| Where did this come from? | `document_id` → `Document.source_type`, `Document.publisher`, `Document.url` |
| When was it published? | `Claim.published_at` (or `Document.published_at`) |
| When was it ingested? | `Document.ingested_at` |
| What source/document generated it? | `Document.source_key`, `Document.external_id`, `Document.source_tier` |
| What text supports it? | `Claim.claim_text_normalized`, `Claim.source_excerpt` (the raw text span from the document) |
| Is this part of a duplicate-event cluster? | `Claim.event_cluster_id` (nullable — set when event clustering detects duplicates) |

### Provenance chain:
```
Document → Claim → Evidence Score → Thesis Update → Portfolio Decision
    ↓          ↓
source_key   claim_text_normalized
external_id  source_excerpt
url          event_cluster_id
hash
```

---

## 8. Deterministic vs. LLM-Owned Responsibilities

| Responsibility | Owner | Rationale |
|---------------|-------|-----------|
| Claim extraction (text → structured claim) | **LLM** | Requires natural language understanding |
| Claim assessment (impact on thesis) | **LLM** | Requires domain interpretation |
| Novelty classification | **Code** | Text similarity + direction comparison against DB |
| Evidence scoring | **Code** | Deterministic formula with defined inputs |
| Conviction score update | **Code** | Arithmetic with caps and dampening |
| State transition resolution | **Code** | Guardrails, inertia rules, score thresholds |
| Memory retrieval | **Code** | SQL queries with bounded limits and deterministic ordering |
| Portfolio decision scoring | **Code** | Rule-based scoring with defined reason codes |
| Deduplication | **Code** | Hash/URL/source_key matching + event clustering |

**The LLM never owns a number that flows into a portfolio decision.** It proposes; code decides.
