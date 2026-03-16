# Historical Proof Run: usefulness_run
Generated: 2026-03-15 10:04 UTC

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
- Claims created: 325
- Thesis updates: 106
- State changes: 34
- State flips: 9

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
| Total return | +18.38% |
| Annualized return | +49.18% |
| Max drawdown | 6.66% |
| Reviews | 23 |
| Purity | degraded |

## Benchmark Comparison
| Benchmark | Return |
|-----------|--------|
| Portfolio | +18.38% |
| SPY | +7.09% |
| Excess vs SPY | +11.29% |
| Equal-weight | +28.21% |
| Excess vs EW | -9.82% |

## Forward Returns by Action Type
| Action | Count | Avg 5D | Avg 20D | Avg 60D |
|--------|-------|--------|---------|---------|
| add | 14 | +1.27% | +0.71% | +9.69% |
| exit | 3 | +3.88% | +2.85% | +21.54% |
| hold | 183 | +1.21% | +6.02% | +18.52% |
| initiate | 13 | -1.10% | +6.76% | +13.24% |

## Conviction Bucket Analysis
| Bucket | Actions | Avg Conviction | Avg 5D | Avg 20D | Avg 60D |
|--------|---------|----------------|--------|---------|---------|
| low | 0 | N/A | N/A | N/A | N/A |
| medium | 101 | 60 | +1.24% | +6.57% | +21.41% |
| high | 112 | 70 | +0.99% | +4.80% | +12.23% |

## Best Decisions (by 20D forward return)
| Date | Ticker | Action | Conviction | 5D | 20D | 60D |
|------|--------|--------|------------|-----|------|------|
| 2024-08-28 | PLTR | initiate | 60.6 | +3.69% | +20.06% | +47.76% |
| 2024-08-07 | AMD | exit | 54.4 | +6.30% | +16.97% | +32.82% |
| 2024-09-04 | TSLA | add | 62.4 | -1.43% | +15.89% | +13.48% |
| 2024-11-20 | PLTR | add | 62.2 | +4.07% | +14.12% | — |
| 2024-09-11 | TSLA | add | 62.4 | -0.59% | +13.10% | +40.81% |
| 2024-08-07 | QCOM | initiate | 50.0 | +4.34% | +11.41% | +8.75% |
| 2024-11-20 | AMZN | add | 69.4 | -0.70% | +10.92% | — |
| 2024-09-04 | META | initiate | 67.9 | -1.55% | +9.97% | +10.72% |
| 2024-09-04 | CRM | initiate | 64.7 | -0.78% | +9.36% | +19.18% |
| 2024-07-31 | NVDA | initiate | 68.8 | -14.16% | +8.74% | +3.75% |

## Worst Decisions (by 20D forward return)
| Date | Ticker | Action | Conviction | 5D | 20D | 60D |
|------|--------|--------|------------|-----|------|------|
| 2024-08-21 | NVDA | add | 68.8 | -1.59% | -15.88% | +7.40% |
| 2024-08-21 | AVGO | add | 67.0 | -3.72% | -10.60% | +8.87% |
| 2024-08-21 | CRWD | exit | 66.7 | -2.69% | -9.32% | +13.52% |
| 2024-08-14 | NVDA | add | 68.8 | +10.09% | -8.54% | +14.17% |
| 2024-08-21 | QCOM | add | 61.3 | -2.71% | -6.72% | -1.39% |
| 2024-08-14 | AVGO | add | 67.0 | +6.35% | -3.11% | +15.47% |
| 2024-08-21 | MSFT | add | 64.5 | -2.51% | -2.34% | -1.41% |
| 2024-08-14 | GOOGL | initiate | 61.6 | +3.93% | -1.88% | +1.92% |
| 2024-08-28 | QCOM | add | 61.3 | +2.01% | -1.33% | -0.41% |
| 2024-09-11 | MSFT | add | 67.2 | +1.96% | -0.56% | -0.12% |

## Per-Name Usefulness Summary
| Ticker | Actions | Docs | Claims | Avg 5D | Avg 20D | Avg 60D | Price Cov |
|--------|---------|------|--------|--------|---------|---------|-----------|
| AAPL | 0 | 7 | 17 | — | — | — | 97% |
| AMD | 2 | 8 | 25 | -0.20% | +12.61% | +23.29% | 97% |
| AMZN | 21 | 4 | 11 | +0.60% | +4.21% | +12.66% | 97% |
| AVGO | 23 | 9 | 35 | +2.04% | +7.51% | +13.79% | 97% |
| CRM | 18 | 8 | 25 | +1.13% | +5.83% | +21.20% | 97% |
| CRWD | 2 | 9 | 27 | +0.72% | -2.64% | +19.25% | 97% |
| GOOGL | 21 | 11 | 25 | +0.30% | +2.69% | +7.72% | 97% |
| INTC | 2 | 10 | 30 | +4.99% | +3.30% | +18.62% | 97% |
| META | 18 | 6 | 17 | +0.33% | +3.48% | +4.86% | 97% |
| MSFT | 22 | 7 | 17 | -0.15% | +0.90% | +1.43% | 97% |
| NOW | 0 | 5 | 24 | — | — | — | 97% |
| NVDA | 23 | 7 | 18 | +0.20% | +2.89% | +11.20% | 97% |
| PLTR | 19 | 6 | 14 | +3.38% | +17.70% | +68.20% | 97% |
| QCOM | 22 | 7 | 22 | +0.70% | -0.35% | -3.00% | 97% |
| TSLA | 20 | 7 | 18 | +2.59% | +14.13% | +47.01% | 97% |

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
- Recommendation changes: 46
- Change rate: 2.000 per review
- Short-hold exits (<30d): 3

### Action Mix
| Action | Count | % |
|--------|-------|---|
| hold | 183 | 53.4% |
| no_action | 130 | 37.9% |
| add | 14 | 4.1% |
| initiate | 13 | 3.8% |
| exit | 3 | 0.9% |

## Failure Analysis

### Action Types with Negative Forward Returns
- initiate actions have negative avg 5D return (-1.10%)

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
| 2024-08-07 | AMD | 54 | initiate | no | +6.30% | +16.97% | +32.82% | YES |
| 2024-08-21 | CRWD | 67 | initiate | no | -2.69% | -9.32% | +13.52% | YES |
| 2024-08-14 | INTC | 61 | initiate | no | +8.03% | +0.90% | +18.27% | YES |

## Enhanced Failure Analysis

### Premature Exits (stock recovered after exit)
- **AMD** exited 2024-08-07 at conviction 54.4, recovered +32.82% over 60D
- **CRWD** exited 2024-08-21 at conviction 66.7, recovered +13.52% over 60D
- **INTC** exited 2024-08-14 at conviction 60.5, recovered +18.27% over 60D

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
