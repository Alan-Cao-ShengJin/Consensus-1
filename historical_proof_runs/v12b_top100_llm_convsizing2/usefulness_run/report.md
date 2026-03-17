# Historical Proof Run: usefulness_run
Generated: 2026-03-16 05:30 UTC

## Run Configuration
- **Mode**: usefulness_run
- **Backfill window**: 2024-06-01 to 2025-01-01
- **Eval window**: 2024-07-31 to 2025-01-01
- **Cadence**: 7 days
- **Initial cash**: $1,000,000
- **Universe**: 15 tickers
- **Extractor**: real_llm
- **Memory**: enabled
- **Benchmark**: SPY

## Regeneration Summary
- Documents processed: 111
- Claims created: 368
- Thesis updates: 100
- State changes: 30
- State flips: 7

### Data Coverage
- Tickers with price data: 15/15
- Total price rows: 2205
- Total documents: 111
  - 10K: 4
  - 10Q: 28
  - 8K: 79

## Key Metrics
| Metric | Value |
|--------|-------|
| Total return | +22.86% |
| Annualized return | +62.91% |
| Max drawdown | 7.39% |
| Reviews | 23 |
| Purity | degraded |

## Benchmark Comparison
| Benchmark | Return |
|-----------|--------|
| Portfolio | +22.86% |
| SPY | +7.09% |
| Excess vs SPY | +15.77% |
| Equal-weight | +28.21% |
| Excess vs EW | -5.34% |

## Forward Returns by Action Type
| Action | Count | Avg 5D | Avg 20D | Avg 60D |
|--------|-------|--------|---------|---------|
| add | 12 | +1.00% | -0.08% | +6.03% |
| exit | 3 | +3.88% | +2.85% | +21.54% |
| hold | 184 | +1.25% | +6.08% | +18.99% |
| initiate | 13 | -1.67% | +6.46% | +12.77% |

## Conviction Bucket Analysis
| Bucket | Actions | Avg Conviction | Avg 5D | Avg 20D | Avg 60D |
|--------|---------|----------------|--------|---------|---------|
| low | 1 | 0 | +10.09% | -8.54% | +14.17% |
| medium | 73 | 59 | +2.00% | +10.39% | +34.44% |
| high | 138 | 73 | +0.53% | +3.24% | +7.99% |

## Best Decisions (by 20D forward return)
| Date | Ticker | Action | Conviction | 5D | 20D | 60D |
|------|--------|--------|------------|-----|------|------|
| 2024-11-27 | TSLA | add | 60.4 | +7.27% | +44.15% | — |
| 2024-08-28 | PLTR | initiate | 55.7 | +3.69% | +20.06% | +47.76% |
| 2024-08-07 | AMD | exit | 56.0 | +6.30% | +16.97% | +32.82% |
| 2024-08-07 | QCOM | initiate | 50.0 | +4.34% | +11.41% | +8.75% |
| 2024-09-04 | META | initiate | 65.2 | -1.55% | +9.97% | +10.72% |
| 2024-09-04 | CRM | initiate | 61.9 | -0.78% | +9.36% | +19.18% |
| 2024-07-31 | NVDA | initiate | 71.3 | -14.16% | +8.74% | +3.75% |
| 2024-07-31 | AMD | initiate | 58.3 | -6.69% | +8.25% | +13.75% |
| 2024-11-13 | TSLA | add | 60.4 | +2.57% | +6.41% | — |
| 2024-08-07 | INTC | initiate | 63.1 | +1.95% | +5.69% | +18.96% |

## Worst Decisions (by 20D forward return)
| Date | Ticker | Action | Conviction | 5D | 20D | 60D |
|------|--------|--------|------------|-----|------|------|
| 2024-08-21 | NVDA | add | 71.3 | -1.59% | -15.88% | +7.40% |
| 2024-08-21 | AVGO | add | 74.6 | -3.72% | -10.60% | +8.87% |
| 2024-08-21 | CRWD | exit | 74.7 | -2.69% | -9.32% | +13.52% |
| 2024-08-28 | NVDA | add | 74.3 | -4.97% | -7.97% | +12.69% |
| 2024-08-21 | QCOM | add | 67.2 | -2.71% | -6.72% | -1.39% |
| 2024-09-18 | MSFT | add | 66.7 | +0.63% | -3.74% | -3.67% |
| 2024-08-14 | AVGO | add | 74.6 | +6.35% | -3.11% | +15.47% |
| 2024-09-18 | AMZN | add | 61.4 | +4.00% | -1.99% | +8.68% |
| 2024-08-14 | GOOGL | initiate | 77.3 | +3.93% | -1.88% | +1.92% |
| 2024-08-28 | QCOM | add | 67.2 | +2.01% | -1.33% | -0.41% |

## Per-Name Usefulness Summary
| Ticker | Actions | Docs | Claims | Avg 5D | Avg 20D | Avg 60D | Price Cov |
|--------|---------|------|--------|--------|---------|---------|-----------|
| AAPL | 0 | 7 | 21 | — | — | — | 97% |
| AMD | 2 | 8 | 36 | -0.20% | +12.61% | +23.29% | 97% |
| AMZN | 20 | 4 | 12 | +0.38% | +4.25% | +12.80% | 97% |
| AVGO | 23 | 9 | 32 | +2.04% | +7.51% | +13.79% | 97% |
| CRM | 18 | 8 | 21 | +1.13% | +5.83% | +21.20% | 97% |
| CRWD | 2 | 9 | 31 | +0.72% | -2.64% | +19.25% | 97% |
| GOOGL | 21 | 11 | 33 | +0.30% | +2.69% | +7.72% | 97% |
| INTC | 2 | 10 | 43 | +4.99% | +3.30% | +18.62% | 97% |
| META | 18 | 6 | 18 | +0.33% | +3.48% | +4.86% | 97% |
| MSFT | 22 | 7 | 24 | -0.15% | +0.90% | +1.43% | 97% |
| NOW | 0 | 5 | 23 | — | — | — | 97% |
| NVDA | 23 | 7 | 20 | +0.20% | +2.89% | +11.20% | 97% |
| PLTR | 19 | 6 | 14 | +3.38% | +17.70% | +68.20% | 97% |
| QCOM | 22 | 7 | 25 | +0.70% | -0.35% | -3.00% | 97% |
| TSLA | 20 | 7 | 15 | +2.59% | +14.13% | +47.01% | 97% |

## Source Coverage Diagnostics
- **Extractor mode**: real_llm
- **Benchmark available**: yes
- **Tickers with prices**: 15
- **Tickers without prices**: 0
- **Total price rows**: 2205

### Documents by Source Type
| Source Type | Count |
|------------|-------|
| 10K | 4 |
| 10Q | 28 |
| 8K | 79 |

### Source Gaps
- **ALL**: No documents ingested in 2025-01

## Decision Summary
- Total actions: 343
- Recommendation changes: 40
- Change rate: 1.739 per review
- Short-hold exits (<30d): 3

### Action Mix
| Action | Count | % |
|--------|-------|---|
| hold | 184 | 53.6% |
| no_action | 131 | 38.2% |
| initiate | 13 | 3.8% |
| add | 12 | 3.5% |
| exit | 3 | 0.9% |

## Failure Analysis

### Action Types with Negative Forward Returns
- add actions have negative avg 20D return (-0.08%)
- initiate actions have negative avg 5D return (-1.67%)

### Repeated Bad Recommendations
- NVDA had 2 initiate/add actions followed by >5% loss at 20D

## Probation/Exit Diagnostics

### Summary
| Metric | Value |
|--------|-------|
| Total probations | 0 |
| Probation -> exit | 0 |
| Probation resolved (improvement) | 0 |
| Probation false alarms | 0 |
| Total exits | 3 |
| Premature exits (20D recovery >5%) | 1 |
| Premature exits (60D recovery >10%) | 3 |
| Avg forward 20D after exit | +2.85% |

### Exit Events
| Date | Ticker | Conviction | Prior Action | Probation? | 5D | 20D | 60D | Premature? |
|------|--------|------------|--------------|------------|-----|------|------|------------|
| 2024-08-07 | AMD | 56 | initiate | no | +6.30% | +16.97% | +32.82% | YES |
| 2024-08-21 | CRWD | 75 | initiate | no | -2.69% | -9.32% | +13.52% | YES |
| 2024-08-14 | INTC | 63 | initiate | no | +8.03% | +0.90% | +18.27% | YES |

## Enhanced Failure Analysis

### Premature Exits (stock recovered after exit)
- **AMD** exited 2024-08-07 at conviction 56.0, recovered +32.82% over 60D
- **CRWD** exited 2024-08-21 at conviction 74.7, recovered +13.52% over 60D
- **INTC** exited 2024-08-14 at conviction 63.1, recovered +18.27% over 60D

### Repeatedly Negative Tickers
- **AVGO**: 3 actions with >5% loss at 20D
- **CRM**: 2 actions with >5% loss at 20D
- **META**: 2 actions with >5% loss at 20D
- **NVDA**: 5 actions with >5% loss at 20D
- **QCOM**: 2 actions with >5% loss at 20D
- **TSLA**: 2 actions with >5% loss at 20D

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
