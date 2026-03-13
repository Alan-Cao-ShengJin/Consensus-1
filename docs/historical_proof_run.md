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

### 10. Best/Worst Decision Analysis
- Top 10 best decisions by 20D forward return
- Top 10 worst decisions by 20D forward return
- Per-decision: date, ticker, action, conviction, forward returns, rationale
- CSV exports: `best_decisions.csv`, `worst_decisions.csv`

### 11. Per-Name Usefulness Summary
- Per-ticker action counts, document counts, claim counts
- Per-ticker average forward returns
- Price coverage percentage
- CSV export: `per_name_summary.csv`

### 12. Coverage Diagnostics
- Documents by ticker, source type, and month
- Claims by ticker
- Source gaps and empty periods
- Extractor mode (real vs stub)
- CSV exports: `coverage_diagnostics.csv`, `coverage_by_month.csv`

### 13. Failure Analysis
- Sparse coverage tickers
- Action types with negative average forward returns
- Non-differentiating conviction buckets
- Repeated bad recommendations
- Low evidence periods
- Degraded/stub run flags

### 14. Run Manifest
- `manifest.json`: run_id, code_hash, universe, date range, extractor mode,
  source toggles, degraded flags, warnings

## Usefulness Run Mode

The `--usefulness-run` flag enables a bounded real usefulness testing mode
designed for inspectable results on a narrow universe.

### Default Proof Universe

The default usefulness-run universe is 15 liquid US large-cap tech names
(defined in `proof_universe.py`):

**Semiconductors (5)**: NVDA, AMD, AVGO, QCOM, INTC
**Hyperscalers (4)**: MSFT, GOOGL, AMZN, META
**Enterprise SW (4)**: CRM, PLTR, NOW, CRWD
**Adjacent tech (2)**: AAPL, TSLA

Rationale: dense public information flow, interpretable decision counts,
reliable price data and SEC filing coverage.

Override with `--tickers` for custom universe.

### Commands

```bash
# Default narrow-universe usefulness run (stub extractor)
python scripts/run_historical_proof.py --usefulness-run

# With real LLM extraction (requires OPENAI_API_KEY)
python scripts/run_historical_proof.py --usefulness-run --use-llm

# Memory ablation usefulness run
python scripts/run_historical_proof.py --usefulness-run --memory-ablation

# Custom tickers
python scripts/run_historical_proof.py --usefulness-run --tickers AAPL,MSFT,NVDA

# Custom date range
python scripts/run_historical_proof.py --usefulness-run --start 2024-03-01 --end 2024-12-01

# Full options
python scripts/run_historical_proof.py --usefulness-run --use-llm --start 2024-06-01 --end 2025-01-01 --cadence 7 --run-id my_usefulness_test
```

### Expected Output

```
historical_proof_runs/usefulness_run/
├── manifest.json              # Run manifest with metadata + degraded flags
├── summary.json               # Machine-readable full report
├── report.md                  # Human-readable markdown report
├── decisions.csv              # Per-review-date decisions
├── action_outcomes.csv        # Per-action forward returns
├── best_decisions.csv         # Top 10 best decisions by forward return
├── worst_decisions.csv        # Top 10 worst decisions by forward return
├── per_name_summary.csv       # Per-ticker usefulness summary
├── coverage_diagnostics.csv   # Source coverage by ticker
├── coverage_by_month.csv      # Source coverage by month
├── benchmark.csv              # Benchmark comparison
├── conviction_buckets.csv     # Conviction bucket summary
└── memory_comparison.csv      # (only with --memory-ablation)
```

### Degraded Run Warnings

When running with stub extraction, the CLI and report prominently warn:
- `DEGRADED: Running usefulness test with stub extractor`
- Source toggles that are disabled
- Universe size warnings if too large

These warnings appear in:
- CLI stdout at run start
- `manifest.json` degraded_flags
- `report.md` Degraded Run Warnings section
- Failure Analysis section
