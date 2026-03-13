# Historical Proof Run Contract

## Purpose

A historical proof run reconstructs the system's thesis state through time from
historical inputs and evaluates whether the resulting decisions would have been
useful against real baselines. This is the strongest form of evaluation: it
proves (or disproves) that the evidence → thesis → decision pipeline produces
actionable output, not just mechanically correct output.

## What Counts as a Valid Historical Proof Run

A valid run must satisfy all of the following:

1. **Clean start**: Thesis state is built from scratch (or from a specified
   initial snapshot), not inherited from current DB state.
2. **Chronological processing**: All documents/claims are processed in
   `published_at` order. No future information is available at any step.
3. **Incremental thesis updates**: Thesis conviction and state evolve through
   the same `update_thesis_from_claims` path used in production.
4. **Decision replay on regenerated state**: Portfolio decisions are made using
   the regenerated thesis state, not pre-existing DB thesis state.
5. **Forward-return measurement**: Each decision's outcome is measured against
   actual subsequent price data over defined horizons (5D, 20D, 60D).
6. **Baseline comparison**: Results are compared against SPY and equal-weight
   universe baselines over the same period.
7. **Reproducibility**: Same config produces identical output on same data.

## Monitored-Universe Assumptions

- Universe: ~45 US-domiciled large-cap tickers defined in `source_registry.UNIVERSE_TICKERS`
- Subset runs: Config supports filtering to a smaller ticker list for faster iteration
- Companies must exist in the `companies` table before processing begins
- Price data must be available for the evaluation window (backfilled from yfinance)

## Supported Historical Source Types

| Source | Backfill Depth | Provider | Availability |
|--------|---------------|----------|-------------|
| Price data (OHLCV) | 2 years | yfinance | Reliable |
| SEC 10-K filings | 3 years | EDGAR full-text search | Reliable |
| SEC 10-Q filings | 1 year | EDGAR full-text search | Reliable |
| SEC 8-K filings | 1 year | EDGAR full-text search | Reliable |
| PR Newswire RSS | 90 days | RSS feed | Limited retention |
| Google News RSS | 7 days | RSS feed | Very limited |
| Finnhub news | 1 year | API (key required) | Disabled by default |
| Earnings transcripts | N/A | Manual upload only | Not automatable |
| Broker reports | N/A | Manual upload only | Not automatable |

### Source Coverage Gaps (Honest Assessment)

- **Earnings transcripts**: Cannot be backfilled automatically. This is the
  highest-value text source. Historical runs without transcripts will have
  weaker thesis evolution.
- **News**: Google RSS retains only ~7 days. Finnhub requires API key and is
  disabled by default. PR Newswire retains ~90 days. News coverage for
  historical periods >90 days ago will be sparse.
- **Broker reports**: Manual-only. Not available for automated backfill.
- **Sector data**: Available via yfinance ticker info but not versioned
  historically. Sector assignments reflect current state, not historical.

## Source Timestamp Precedence Rules

1. **published_at** on the document is the canonical ordering timestamp.
2. If `published_at` is missing, fall back to `ingested_at`.
3. Within the same `published_at`, process documents by `source_tier` (TIER_1
   first) then by `id` (insertion order).
4. Claims inherit `published_at` from their parent document unless they have
   their own timestamp.

## As-of-Date Reconstruction Rules

For any review date `D`:

1. **Documents**: Only documents with `published_at <= D` are considered.
2. **Claims**: Only claims from documents satisfying rule 1.
3. **Thesis state**: Reflects cumulative updates from claims up to date `D`.
4. **Prices**: Latest available price on or before date `D`.
5. **Checkpoints**: Only checkpoints with `created_at <= D` (or `date_expected`
   for forward-looking checkpoints created before `D`).
6. **Novelty classification**: Compares against claims available as-of `D` only.
   This is approximated by processing in chronological order so that only
   prior claims exist in the DB at classification time.
7. **Memory retrieval**: Uses thesis-linked claims that exist as-of `D`.
   Achieved by processing chronologically on a clean DB.

## Limitations and Known Coverage Gaps

### Data Limitations
- No earnings transcript backfill (manual source only)
- News coverage degrades rapidly for periods >90 days ago
- No broker report backfill
- Sector/industry data reflects current assignments, not historical
- yfinance price data may have gaps for some tickers on some dates
- Dividends and splits are handled by yfinance adjusted close but not verified

### Methodological Limitations
- Stub LLM mode: claim extraction uses deterministic stub, not real LLM.
  This means extracted claims are synthetic/formulaic, not realistic.
- Novelty classification uses text similarity, not semantic understanding
- Evidence scoring uses heuristic weights, not learned parameters
- No transaction cost modeling beyond flat basis-point charge
- No market impact or liquidity constraints
- Forward returns assume execution at close price on decision date
- Equal-weight baseline assumes frictionless rebalancing

### Statistical Limitations
- Returns over short windows are not statistically significant
- Small universe (~45 tickers) limits diversification analysis
- No regime tagging (bull/bear market identification)
- Single evaluation period — no walk-forward or cross-validation

## Required Output Tables / Report Sections

A valid proof-run report pack must contain:

### 1. Run Metadata
- Config parameters, date range, universe, source coverage summary

### 2. Data Coverage Summary
- Documents ingested by source type and month
- Claims extracted by type and direction
- Price data coverage (% of ticker-dates with data)
- Thesis state snapshots count

### 3. Decision Summary Table (per review date)
- Review date, ticker, action, conviction, rationale summary
- CSV export: `decisions.csv`

### 4. Forward-Return Analysis (per action)
- Action type, count, avg forward return at 5D/20D/60D
- Breakdown by conviction bucket (low/medium/high)
- CSV export: `action_outcomes.csv`

### 5. Benchmark Comparison
- Portfolio return vs SPY vs equal-weight universe
- Excess return over each baseline
- CSV export: `benchmark.csv`

### 6. Conviction Bucket Summary
- Conviction range, action count, avg forward return
- CSV export: `conviction_buckets.csv`

### 7. Memory Ablation (if run)
- Side-by-side metrics: memory ON vs OFF
- Thesis change counts, state flips, recommendation stability
- Portfolio outcome differences
- CSV export: `memory_comparison.csv`

### 8. Warnings and Gaps
- Missing price data events
- Source coverage gaps by period
- Tickers with insufficient data for evaluation

### 9. Structured Outputs
- `summary.json`: Machine-readable full report
- `report.md`: Human-readable markdown report
- CSV tables as listed above
