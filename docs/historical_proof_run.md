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
- Review date, ticker, action, thesis_conviction, action_score, rationale summary
- `thesis_conviction`: raw thesis conviction (0-100), meaningful for ALL actions including hold
- `action_score`: decision-engine urgency score (0 for holds, 50-100 for active actions)
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
  source toggles, exit_policy, degraded flags, warnings

### 15. Probation/Exit Diagnostics
- Full deterioration path tracking: prior action, conviction trajectory, forward returns
- Premature exit detection: exit followed by >5% recovery at 20D or >10% at 60D
- False alarm probation: probation where stock subsequently rose (positive 20D forward return)
- CSV exports: `probation_events.csv`, `exit_events.csv`

### 16. Enhanced Failure Analysis
- Premature exits with forward recovery data
- Correct warning counts (exit that avoided further decline)
- False alarm counts (probation on recovering stock)
- Repeated negative tickers

## Exit Policy Variants

The system supports bounded exit-policy variants for empirical comparison.
All variants are defined in `exit_policy.py`.

| Policy | Exit ≤ | Probation ≤ | Max Reviews | Special |
|--------|--------|-------------|-------------|---------|
| **baseline** | 25 | 35 | 2 | — |
| **patient** | 20 | 35 | 3 | Higher bar to exit, more review cycles |
| **graduated** | 25 | 35 | 2 | Sharp drop ≥15pts → immediate exit |

- **baseline**: Current default. Exit when conviction ≤25, probation when ≤35, max 2 reviews.
- **patient**: More tolerant. Exit only at ≤20, allows 3 probation reviews before forced exit.
- **graduated**: Same thresholds as baseline, but a sharp single-period conviction drop (≥15 points) triggers immediate exit regardless of absolute level.

Pass `--policy baseline|patient|graduated` to any runner that accepts it.

### Conviction Fields

- `thesis_conviction`: The raw thesis conviction score (0-100). Meaningful for ALL action types including hold. **Use this for analysis.**
- `action_score`: The decision-engine urgency/priority score. 0 for holds, 50-100 for active actions. Use only for priority/urgency analysis.

The old `conviction` field in CSVs has been replaced by these two fields. `thesis_conviction` is the one to use for conviction-vs-return analysis, conviction trajectory tracking, and deterioration diagnostics.

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

### Daily vs Weekly Cadence

The system supports daily (`--cadence 1`) and weekly (`--cadence 7`) review cadences.
Daily cadence evaluates every business day; weekly is the default.

```bash
# Daily cadence proof run
python scripts/run_historical_proof.py --usefulness-run --cadence 1

# Weekly cadence (default)
python scripts/run_historical_proof.py --usefulness-run --cadence 7

# Daily with real LLM
python scripts/run_historical_proof.py --usefulness-run --cadence 1 --use-llm
```

**Cadence trade-offs:**
- Daily produces ~5× more review dates and decisions
- Daily may generate higher turnover and more short-hold exits
- Probation windows compress at daily cadence (2 reviews = 2 days vs 2 weeks)
- The weekly turnover cap (20%) applies per-review regardless of cadence

### Cadence Comparison

Compare daily vs weekly cadence on the same regeneration DB. Runs both cadences
and produces a side-by-side `cadence_comparison.csv`.

```bash
# Compare daily vs weekly (requires existing regen DB)
python scripts/run_cadence_comparison.py --regen-db historical_proof_runs/usefulness_llm_v7_regen.db

# With real LLM
python scripts/run_cadence_comparison.py --regen-db historical_proof_runs/usefulness_llm_v7_regen.db --use-llm

# Custom tickers
python scripts/run_cadence_comparison.py --regen-db historical_proof_runs/usefulness_llm_v7_regen.db --tickers AAPL,NVDA
```

Output: `cadence_comparison.csv` with metrics: total_return, annualized_return,
max_drawdown, review_dates, trades, turnover, recommendation_changes, short_hold_exits.

### Replay UI

Launch the standalone replay server to browse proof packs interactively:

```bash
python replay_server.py --run-dir historical_proof_runs --port 5001
# Then open http://localhost:5001
```

The UI provides:
- **Timeline tab**: Review dates with event markers for portfolio changes; click markers for drilldown
- **Decisions tab**: Per-ticker decisions with prior/new weight columns; "Changes only" filter
- **Weight Changes tab**: Summary cards (initiations, exits, adds/trims, turnover) and full change event table
- **Composition tab**: Date-selectable portfolio view with weight bars; weight history heatmap across all dates
- **Causality drilldown panel**: Click any event to see the 5-step chain: Evidence → Conviction → Action → Weight → Outcome

### Policy Comparison

Compare exit policy variants on the same universe and window. Shared backfill
and regeneration, per-policy evaluation only.

```bash
# Compare all 3 policies (default)
python scripts/run_policy_comparison.py

# With real LLM
python scripts/run_policy_comparison.py --use-llm

# Custom tickers and policies
python scripts/run_policy_comparison.py --tickers AAPL,NVDA --policies baseline,graduated
```

Output: `historical_proof_runs/<run_id>/policy_comparison.csv`, per-policy
proof packs, and `comparison_report.md`.

### Multi-Window Runs

Run the same config across multiple date windows to surface instability.

```bash
# Default 3 windows
python scripts/run_multi_window.py

# With real LLM
python scripts/run_multi_window.py --use-llm

# Custom windows
python scripts/run_multi_window.py --windows "2025-01-01:2025-07-01,2025-04-01:2025-10-01"

# Custom tickers
python scripts/run_multi_window.py --tickers AAPL,NVDA,MSFT
```

Output: `window_summary.csv`, `multi_window_report.md`, `multi_window_summary.json`.

Warnings are generated for:
- Return sign changes across windows (positive in one, negative in another)
- Fewer than 3 windows (small sample)

### What Conclusions Should / Shouldn't Be Drawn

**Can conclude:**
- Whether conviction-vs-return correlation holds across windows and policies
- Whether a policy variant reduces premature exits or false alarms
- Whether results are stable across time windows or suspiciously fragile

**Cannot conclude (with stub extractor):**
- Absolute return numbers are meaningful (stub claims are synthetic)
- One policy is "better" from a single window (need multiple windows + real LLM)
- Any result generalizes beyond the test universe

### Expected Output

```
historical_proof_runs/usefulness_run/
├── manifest.json              # Run manifest with metadata + degraded flags
├── summary.json               # Machine-readable full report
├── report.md                  # Human-readable markdown report
├── decisions.csv              # Per-review-date decisions (thesis_conviction + action_score)
├── action_outcomes.csv        # Per-action forward returns
├── best_decisions.csv         # Top 10 best decisions by forward return
├── worst_decisions.csv        # Top 10 worst decisions by forward return
├── per_name_summary.csv       # Per-ticker usefulness summary
├── coverage_diagnostics.csv   # Source coverage by ticker
├── coverage_by_month.csv      # Source coverage by month
├── benchmark.csv              # Benchmark comparison
├── conviction_buckets.csv     # Conviction bucket summary
├── portfolio_timeline.csv     # Portfolio NAV, cash, positions per review date
├── portfolio_trades.csv       # All executed shadow trades
├── portfolio_composition.csv  # Per-position weights at each review date
├── portfolio_changes.csv      # Meaningful weight-change events (excludes holds)
├── probation_events.csv       # Probation event details + forward returns
├── exit_events.csv            # Exit event details + forward returns
├── memory_comparison.csv      # (only with --memory-ablation)
├── policy_comparison.csv      # (only with run_policy_comparison.py)
├── cadence_comparison.csv     # (only with run_cadence_comparison.py)
└── window_summary.csv         # (only with run_multi_window.py)
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
