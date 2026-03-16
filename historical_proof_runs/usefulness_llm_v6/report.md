# Historical Proof Run: usefulness_llm_v6
Generated: 2026-03-13 10:51 UTC

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
- Claims created: 207
- Thesis updates: 77
- State changes: 26
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
| Total return | +4.08% |
| Annualized return | +9.94% |
| Max drawdown | 4.88% |
| Reviews | 23 |
| Purity | degraded |

## Benchmark Comparison
| Benchmark | Return |
|-----------|--------|
| Portfolio | +4.08% |

## Forward Returns by Action Type
| Action | Count | Avg 5D | Avg 20D | Avg 60D |
|--------|-------|--------|---------|---------|
| hold | 220 | +0.66% | +2.88% | +7.02% |
| initiate | 15 | +2.39% | +1.51% | +14.19% |

## Conviction Bucket Analysis
| Bucket | Actions | Avg Conviction | Avg 5D | Avg 20D | Avg 60D |
|--------|---------|----------------|--------|---------|---------|
| low | 220 | 0 | +0.66% | +2.88% | +7.02% |
| medium | 15 | 50 | +2.39% | +1.51% | +14.19% |
| high | 0 | N/A | N/A | N/A | N/A |

## Best Decisions (by 20D forward return)
| Date | Ticker | Action | Conviction | 5D | 20D | 60D |
|------|--------|--------|------------|-----|------|------|
| 2025-09-11 | TSLA | initiate | 50.0 | +14.32% | +24.58% | +20.72% |
| 2025-09-04 | AVGO | initiate | 50.0 | +9.99% | +11.04% | +18.64% |
| 2025-09-04 | GOOGL | initiate | 50.0 | +3.25% | +6.48% | +22.24% |
| 2025-08-28 | QCOM | initiate | 50.0 | -1.26% | +3.36% | +17.38% |
| 2025-10-02 | NOW | initiate | 50.0 | -0.64% | +2.81% | -9.67% |
| 2025-09-04 | CRM | initiate | 50.3 | +3.30% | +0.95% | +7.29% |
| 2025-10-02 | MSFT | initiate | 50.0 | +1.60% | +0.93% | -5.45% |
| 2025-08-28 | CRWD | initiate | 50.1 | -6.45% | +0.79% | +19.84% |
| 2025-08-14 | INTC | initiate | 50.0 | +6.08% | +0.59% | +55.99% |
| 2025-10-30 | AMZN | initiate | 50.0 | +11.87% | -0.08% | +4.13% |

## Worst Decisions (by 20D forward return)
| Date | Ticker | Action | Conviction | 5D | 20D | 60D |
|------|--------|--------|------------|-----|------|------|
| 2025-10-30 | META | initiate | 50.0 | -5.87% | -11.43% | -1.09% |
| 2025-08-28 | AMD | initiate | 50.0 | -3.71% | -5.59% | +54.03% |
| 2025-08-28 | NVDA | initiate | 50.0 | -5.21% | -5.48% | +6.29% |
| 2025-11-06 | PLTR | initiate | 50.1 | +9.09% | -5.30% | +1.54% |
| 2025-10-30 | AAPL | initiate | 50.0 | -0.50% | -0.95% | +0.97% |
| 2025-10-30 | AMZN | initiate | 50.0 | +11.87% | -0.08% | +4.13% |
| 2025-08-14 | INTC | initiate | 50.0 | +6.08% | +0.59% | +55.99% |
| 2025-08-28 | CRWD | initiate | 50.1 | -6.45% | +0.79% | +19.84% |
| 2025-10-02 | MSFT | initiate | 50.0 | +1.60% | +0.93% | -5.45% |
| 2025-09-04 | CRM | initiate | 50.3 | +3.30% | +0.95% | +7.29% |

## Per-Name Usefulness Summary
| Ticker | Actions | Docs | Claims | Avg 5D | Avg 20D | Avg 60D | Price Cov |
|--------|---------|------|--------|--------|---------|---------|-----------|
| AAPL | 10 | 3 | 8 | +0.45% | +0.59% | +0.92% | 91% |
| AMD | 19 | 6 | 15 | +1.28% | +7.92% | +21.45% | 91% |
| AMZN | 10 | 3 | 14 | +1.63% | -0.43% | -0.45% | 91% |
| AVGO | 18 | 7 | 25 | +0.42% | +1.47% | +4.65% | 91% |
| CRM | 18 | 6 | 15 | +0.83% | +1.66% | +2.22% | 91% |
| CRWD | 19 | 5 | 18 | +0.16% | +1.89% | +6.14% | 91% |
| GOOGL | 18 | 5 | 14 | +1.69% | +5.59% | +21.04% | 91% |
| INTC | 21 | 13 | 17 | +1.08% | +7.35% | +24.13% | 91% |
| META | 10 | 5 | 14 | +0.38% | +1.57% | +2.82% | 91% |
| MSFT | 14 | 4 | 11 | +0.42% | -1.17% | -5.78% | 91% |
| NOW | 14 | 6 | 12 | -0.41% | -4.12% | -12.64% | 91% |
| NVDA | 19 | 4 | 8 | +0.26% | +0.93% | +2.65% | 91% |
| PLTR | 9 | 2 | 6 | +1.78% | +4.75% | +1.54% | 91% |
| QCOM | 19 | 6 | 13 | -0.02% | +2.26% | +4.50% | 91% |
| TSLA | 17 | 5 | 17 | +2.06% | +5.19% | +4.68% | 91% |

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
- Recommendation changes: 15
- Change rate: 0.652 per review
- Short-hold exits (<30d): 0

### Action Mix
| Action | Count | % |
|--------|-------|---|
| hold | 220 | 93.6% |
| initiate | 15 | 6.4% |

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
