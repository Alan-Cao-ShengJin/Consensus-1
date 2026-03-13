# Graphiti Assessment

## Direct Answer

Graphiti would not materially improve returns at this stage.  The system's
primary bottleneck is **evidence quality and coverage** (earnings transcripts,
broker reports, timely news), not knowledge-graph retrieval.  Current evidence
scoring already uses structural features (novelty, contradiction, freshness,
source tier) that a graph could surface, but these are computed deterministically
during thesis updates and persisted as `EvidenceAssessment` rows — adding a
graph layer would not change the underlying conviction math.

Graphiti's main value proposition — relationship-aware retrieval across entities
and temporal knowledge — would help **explainability and relationship surfacing**
(e.g., "which supply-chain claims affected NVDA's thesis?"), but this is a
presentation concern, not a return-driver.  The current `ThesisClaimLink` +
`EvidenceAssessment` + `ThesisStateHistory` chain already provides full
evidence-to-decision traceability, as demonstrated by the replay UI's evidence
drilldown.

## Should It Be Prioritized?

**Not now.**  Prioritize later, or not at all, unless:

1. The evidence base grows large enough (>10K claims per ticker) that
   retrieval quality degrades without graph-based indexing.
2. Cross-company relationship reasoning becomes a return driver (e.g.,
   supply-chain contagion, peer-group thesis transfer).
3. An investor or user specifically needs a "show me how TSMC affects NVDA"
   type of query interface.

None of these conditions hold today.

## Where It Would Help (Later)

| Capability | Current System | With Graphiti | Impact |
|-----------|---------------|---------------|--------|
| Evidence retrieval | Chronological + thesis-linked | Relationship-aware + temporal | Marginal (small claim corpus) |
| Cross-company signals | Manual peer-group setup | Automatic relationship discovery | Useful once coverage is broad |
| Explainability | ThesisClaimLink + EvidenceAssessment | Graph traversal visualization | Nice for demos, not for returns |
| Deduplication | event_cluster_id + text similarity | Entity-resolved event clustering | Marginal improvement |
| Temporal reasoning | ThesisStateHistory + as-of-date filtering | Native temporal graph queries | Already solved differently |

## Where It Would Not Help

- **Conviction calculation**: This is a weighted sum of evidence assessments.
  A graph doesn't change the math.
- **Exit/probation decisions**: These are threshold-based on conviction + policy
  parameters.  Graph structure is irrelevant.
- **Forward-return analysis**: This is a data measurement, not a retrieval problem.
- **Portfolio construction**: Position sizing and turnover caps are rule-based.

## Recommendation

Focus current engineering effort on:

1. **Real evidence quality** — earnings transcripts, Finnhub news, broker reports
2. **Conviction calibration** — are high-conviction decisions actually better?
3. **Policy tuning** — use multi-window + policy comparison to find stable parameters
4. **Coverage breadth** — more source types matter more than fancier retrieval

Revisit Graphiti when the corpus exceeds ~5K claims per ticker or when
cross-company reasoning becomes a demonstrated return driver in backtest data.
