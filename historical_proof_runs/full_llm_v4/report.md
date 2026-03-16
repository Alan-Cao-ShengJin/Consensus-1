# Historical Proof Run: full_llm_v4
Generated: 2026-03-14 04:40 UTC

## Run Configuration
- **Mode**: usefulness_run
- **Backfill window**: 2025-06-01 to 2026-03-01
- **Eval window**: 2025-09-01 to 2026-03-01
- **Cadence**: 7 days
- **Initial cash**: $1,000,000
- **Universe**: 5 tickers
- **Extractor**: real_llm
- **Memory**: enabled
- **Benchmark**: SPY

## Regeneration Summary
- Documents processed: 68
- Claims created: 344
- Thesis updates: 63
- State changes: 9
- State flips: 1

### Data Coverage
- Tickers with price data: 5/5
- Total price rows: 890
- Total documents: 68
  - 10K: 5
  - 10Q: 25
  - 8K: 38

## Key Metrics
| Metric | Value |
|--------|-------|
| Total return | -13.59% |
| Annualized return | -26.26% |
| Max drawdown | 16.31% |
| Reviews | 26 |
| Purity | degraded |

## Benchmark Comparison
| Benchmark | Return |
|-----------|--------|
| Portfolio | -13.59% |
| SPY | +7.76% |
| Excess vs SPY | -21.34% |
| Equal-weight | +1.74% |
| Excess vs EW | -15.33% |

## Forward Returns by Action Type
| Action | Count | Avg 5D | Avg 20D | Avg 60D |
|--------|-------|--------|---------|---------|
| add | 51 | -0.52% | -0.79% | -2.13% |
| hold | 74 | -0.67% | -0.25% | +0.10% |
| initiate | 5 | -1.67% | +2.31% | +16.05% |

## Conviction Bucket Analysis
| Bucket | Actions | Avg Conviction | Avg 5D | Avg 20D | Avg 60D |
|--------|---------|----------------|--------|---------|---------|
| low | 0 | N/A | N/A | N/A | N/A |
| medium | 18 | 53 | -0.69% | -1.21% | -1.92% |
| high | 112 | 80 | -0.64% | -0.22% | +0.41% |

## Best Decisions (by 20D forward return)
| Date | Ticker | Action | Conviction | 5D | 20D | 60D |
|------|--------|--------|------------|-----|------|------|
| 2025-10-06 | AMD | add | 75.1 | +5.49% | +24.16% | +7.00% |
| 2025-10-13 | AMD | add | 75.1 | +7.70% | +18.34% | -2.61% |
| 2025-10-13 | AAPL | add | 56.8 | +1.87% | +9.17% | +12.47% |
| 2025-09-15 | AAPL | add | 56.8 | +3.72% | +9.01% | +15.20% |
| 2025-12-15 | AMD | add | 85.1 | +2.82% | +7.65% | -0.13% |
| 2025-10-13 | NVDA | add | 66.8 | -2.71% | +7.52% | -7.06% |
| 2025-09-08 | AAPL | add | 56.8 | -1.60% | +7.39% | +12.86% |
| 2026-01-19 | META | add | 80.4 | +6.21% | +6.64% | — |
| 2025-09-01 | AAPL | initiate | 56.8 | +3.25% | +5.76% | +16.47% |
| 2025-09-15 | NVDA | add | 66.8 | -0.61% | +5.55% | +6.99% |

## Worst Decisions (by 20D forward return)
| Date | Ticker | Action | Conviction | 5D | 20D | 60D |
|------|--------|--------|------------|-----|------|------|
| 2025-11-03 | AMD | add | 81.6 | -10.06% | -21.52% | -13.93% |
| 2026-01-26 | AMD | add | 87.2 | -5.80% | -17.50% | — |
| 2025-11-03 | NVDA | add | 66.8 | -9.05% | -13.53% | -8.71% |
| 2025-11-10 | AMD | add | 83.6 | +1.16% | -10.84% | -16.73% |
| 2025-11-17 | AMD | add | 83.6 | -15.28% | -9.38% | -3.61% |
| 2025-11-03 | MSFT | add | 85.1 | -3.91% | -8.52% | -8.36% |
| 2026-02-09 | AMD | add | 90.4 | -4.02% | -7.31% | — |
| 2026-01-05 | AAPL | add | 85.8 | -2.95% | -7.19% | — |
| 2025-11-03 | META | add | 81.9 | -2.51% | -6.82% | +2.07% |
| 2026-02-02 | MSFT | add | 90.7 | -5.25% | -5.96% | — |

## Per-Name Usefulness Summary
| Ticker | Actions | Docs | Claims | Avg 5D | Avg 20D | Avg 60D | Price Cov |
|--------|---------|------|--------|--------|---------|---------|-----------|
| AAPL | 26 | 14 | 63 | -0.03% | +0.87% | +2.77% | 96% |
| AMD | 26 | 17 | 88 | -0.74% | +2.33% | +9.86% | 96% |
| META | 26 | 13 | 69 | -0.60% | -1.83% | -5.48% | 96% |
| MSFT | 26 | 12 | 60 | -1.15% | -3.16% | -8.18% | 96% |
| NVDA | 26 | 12 | 64 | -0.72% | -0.05% | +0.77% | 96% |

## Source Coverage Diagnostics
- **Extractor mode**: real_llm
- **Benchmark available**: yes
- **Tickers with prices**: 5
- **Tickers without prices**: 0
- **Total price rows**: 890

### Documents by Source Type
| Source Type | Count |
|------------|-------|
| 10K | 5 |
| 10Q | 25 |
| 8K | 38 |

### Source Gaps
- **ALL**: No documents ingested in 2025-06
- **ALL**: No documents ingested in 2026-03

## Decision Summary
- Total actions: 130
- Recommendation changes: 45
- Change rate: 1.731 per review
- Short-hold exits (<30d): 0

### Action Mix
| Action | Count | % |
|--------|-------|---|
| hold | 74 | 56.9% |
| add | 51 | 39.2% |
| initiate | 5 | 3.8% |

## Failure Analysis

### Action Types with Negative Forward Returns
- add actions have negative avg 20D return (-0.79%)
- hold actions have negative avg 20D return (-0.25%)
- initiate actions have negative avg 5D return (-1.67%)

### Non-Differentiating Conviction Buckets
- Conviction buckets do not meaningfully differentiate outcomes (spread: 0.99%)

### Repeated Bad Recommendations
- AMD had 6 initiate/add actions followed by >5% loss at 20D
- MSFT had 2 initiate/add actions followed by >5% loss at 20D

### Low Evidence Periods
- Only 1 document(s) in 2025-09

## Probation/Exit Diagnostics

### Summary
| Metric | Value |
|--------|-------|
| Total probations | 0 |
| Probation -> exit | 0 |
| Probation resolved (improvement) | 0 |
| Probation false alarms | 0 |
| Total exits | 0 |
| Premature exits (20D recovery >5%) | 0 |
| Premature exits (60D recovery >10%) | 0 |

## Enhanced Failure Analysis

### Repeatedly Negative Tickers
- **AAPL**: 2 actions with >5% loss at 20D
- **AMD**: 8 actions with >5% loss at 20D
- **META**: 8 actions with >5% loss at 20D
- **MSFT**: 6 actions with >5% loss at 20D
- **NVDA**: 3 actions with >5% loss at 20D

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
| probation_events.csv | Probation event diagnostics |
| exit_events.csv | Exit event diagnostics |
