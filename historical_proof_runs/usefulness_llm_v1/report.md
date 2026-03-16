# Historical Proof Run: usefulness_llm_v1
Generated: 2026-03-13 05:47 UTC

## Run Configuration
- **Mode**: usefulness_run
- **Backfill window**: 2025-06-01 to 2026-01-01
- **Eval window**: 2025-07-31 to 2026-01-01
- **Cadence**: 7 days
- **Initial cash**: $1,000,000
- **Universe**: 15 tickers
- **Extractor**: real_llm
- **Memory**: enabled
- **Benchmark**: SPY

## Regeneration Summary
- Documents processed: 80
- Claims created: 205
- Thesis updates: 76
- State changes: 25
- State flips: 0

### Data Coverage
- Tickers with price data: 15/15
- Total price rows: 1500
- Total documents: 80
  - 10K: 3
  - 10Q: 16
  - 8K: 61

## Key Metrics
| Metric | Value |
|--------|-------|
| Total return | +0.00% |
| Annualized return | +0.00% |
| Max drawdown | 0.00% |
| Reviews | 23 |
| Purity | strict |

## Benchmark Comparison
| Benchmark | Return |
|-----------|--------|
| Portfolio | +0.00% |

## Conviction Bucket Analysis
| Bucket | Actions | Avg Conviction | Avg 5D | Avg 20D | Avg 60D |
|--------|---------|----------------|--------|---------|---------|
| low | 0 | N/A | N/A | N/A | N/A |
| medium | 0 | N/A | N/A | N/A | N/A |
| high | 0 | N/A | N/A | N/A | N/A |

## Per-Name Usefulness Summary
| Ticker | Actions | Docs | Claims | Avg 5D | Avg 20D | Avg 60D | Price Cov |
|--------|---------|------|--------|--------|---------|---------|-----------|
| AAPL | 0 | 3 | 7 | — | — | — | 91% |
| AMD | 0 | 6 | 19 | — | — | — | 91% |
| AMZN | 0 | 3 | 8 | — | — | — | 91% |
| AVGO | 0 | 7 | 25 | — | — | — | 91% |
| CRM | 0 | 6 | 15 | — | — | — | 91% |
| CRWD | 0 | 5 | 19 | — | — | — | 91% |
| GOOGL | 0 | 5 | 10 | — | — | — | 91% |
| INTC | 0 | 13 | 28 | — | — | — | 91% |
| META | 0 | 5 | 11 | — | — | — | 91% |
| MSFT | 0 | 4 | 10 | — | — | — | 91% |
| NOW | 0 | 6 | 10 | — | — | — | 91% |
| NVDA | 0 | 4 | 12 | — | — | — | 91% |
| PLTR | 0 | 2 | 6 | — | — | — | 91% |
| QCOM | 0 | 6 | 11 | — | — | — | 91% |
| TSLA | 0 | 5 | 14 | — | — | — | 91% |

## Source Coverage Diagnostics
- **Extractor mode**: real_llm
- **Benchmark available**: yes
- **Tickers with prices**: 15
- **Tickers without prices**: 0
- **Total price rows**: 1500

### Documents by Source Type
| Source Type | Count |
|------------|-------|
| 10K | 3 |
| 10Q | 16 |
| 8K | 61 |

### Source Gaps
- **ALL**: No documents ingested in 2025-06
- **ALL**: No documents ingested in 2025-07
- **ALL**: No documents ingested in 2026-01

## Decision Summary
- Total actions: 0
- Recommendation changes: 0
- Change rate: 0.000 per review
- Short-hold exits (<30d): 0

## Failure Analysis

### Sparse Coverage Tickers
| Ticker | Issues | Docs | Claims | Price Cov |
|--------|--------|------|--------|-----------|
| PLTR | only 2 documents | 2 | 6 | 90.9% |

## Warnings
- No action outcomes generated — check data availability

## Limitations
- Returns are not statistically significant over short replay windows
- No earnings transcript backfill (manual source only)
- News coverage degrades rapidly for periods >90 days ago
- Equal-weight baseline assumes no transaction costs
- Forward returns assume execution at close price on decision date
- No sector-level attribution (sector data not versioned historically)

## Artifact Index
| File | Description |
|------|-------------|
| manifest.json | Run manifest with metadata and degraded flags |
| summary.json | Machine-readable full report |
| report.md | This report |
| decisions.csv | Per-review-date decisions |
| action_outcomes.csv | Per-action forward returns |
| best_decisions.csv | Top decisions by forward return |
| worst_decisions.csv | Bottom decisions by forward return |
| per_name_summary.csv | Per-ticker usefulness summary |
| coverage_diagnostics.csv | Source coverage by ticker |
| coverage_by_month.csv | Source coverage by month |
| benchmark.csv | Benchmark comparison |
| conviction_buckets.csv | Conviction bucket summary |
