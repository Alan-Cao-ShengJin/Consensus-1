# Historical Proof Run: usefulness_llm_real
Generated: 2026-03-13 09:00 UTC

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
- Claims created: 216
- Thesis updates: 76
- State changes: 31
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
| Total return | +1.50% |
| Annualized return | +3.60% |
| Max drawdown | 0.78% |
| Reviews | 23 |
| Purity | degraded |

## Benchmark Comparison
| Benchmark | Return |
|-----------|--------|
| Portfolio | +1.50% |

## Forward Returns by Action Type
| Action | Count | Avg 5D | Avg 20D | Avg 60D |
|--------|-------|--------|---------|---------|
| hold | 20 | +0.82% | +7.75% | +21.48% |
| initiate | 1 | +6.08% | +0.59% | +55.99% |

## Conviction Bucket Analysis
| Bucket | Actions | Avg Conviction | Avg 5D | Avg 20D | Avg 60D |
|--------|---------|----------------|--------|---------|---------|
| low | 20 | 0 | +0.82% | +7.75% | +21.48% |
| medium | 1 | 50 | +6.08% | +0.59% | +55.99% |
| high | 0 | N/A | N/A | N/A | N/A |

## Best Decisions (by 20D forward return)
| Date | Ticker | Action | Conviction | 5D | 20D | 60D |
|------|--------|--------|------------|-----|------|------|
| 2025-08-14 | INTC | initiate | 50.0 | +6.08% | +0.59% | +55.99% |

## Worst Decisions (by 20D forward return)
| Date | Ticker | Action | Conviction | 5D | 20D | 60D |
|------|--------|--------|------------|-----|------|------|
| 2025-08-14 | INTC | initiate | 50.0 | +6.08% | +0.59% | +55.99% |

## Per-Name Usefulness Summary
| Ticker | Actions | Docs | Claims | Avg 5D | Avg 20D | Avg 60D | Price Cov |
|--------|---------|------|--------|--------|---------|---------|-----------|
| AAPL | 0 | 3 | 6 | — | — | — | 91% |
| AMD | 0 | 6 | 15 | — | — | — | 91% |
| AMZN | 0 | 3 | 9 | — | — | — | 91% |
| AVGO | 0 | 7 | 25 | — | — | — | 91% |
| CRM | 0 | 6 | 15 | — | — | — | 91% |
| CRWD | 0 | 5 | 20 | — | — | — | 91% |
| GOOGL | 0 | 5 | 16 | — | — | — | 91% |
| INTC | 21 | 13 | 32 | +1.08% | +7.35% | +24.13% | 91% |
| META | 0 | 5 | 14 | — | — | — | 91% |
| MSFT | 0 | 4 | 10 | — | — | — | 91% |
| NOW | 0 | 6 | 10 | — | — | — | 91% |
| NVDA | 0 | 4 | 11 | — | — | — | 91% |
| PLTR | 0 | 2 | 6 | — | — | — | 91% |
| QCOM | 0 | 6 | 13 | — | — | — | 91% |
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
- Total actions: 235
- Recommendation changes: 1
- Change rate: 0.043 per review
- Short-hold exits (<30d): 0

### Action Mix
| Action | Count | % |
|--------|-------|---|
| no_action | 214 | 91.1% |
| hold | 20 | 8.5% |
| initiate | 1 | 0.4% |

## Failure Analysis

### Sparse Coverage Tickers
| Ticker | Issues | Docs | Claims | Price Cov |
|--------|--------|------|--------|-----------|
| PLTR | only 2 documents | 2 | 6 | 90.9% |

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
