# Historical Proof Run: usefulness_run
Generated: 2026-03-15 07:03 UTC

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
- Claims created: 309
- Thesis updates: 103
- State changes: 38
- State flips: 13

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
| Total return | +14.86% |
| Annualized return | +38.88% |
| Max drawdown | 6.61% |
| Reviews | 23 |
| Purity | degraded |

## Benchmark Comparison
| Benchmark | Return |
|-----------|--------|
| Portfolio | +14.86% |
| SPY | +7.09% |
| Excess vs SPY | +7.77% |
| Equal-weight | +28.21% |
| Excess vs EW | -13.34% |

## Forward Returns by Action Type
| Action | Count | Avg 5D | Avg 20D | Avg 60D |
|--------|-------|--------|---------|---------|
| add | 29 | +1.61% | +4.61% | +8.09% |
| exit | 3 | +3.88% | +2.85% | +21.54% |
| hold | 168 | +1.15% | +5.76% | +19.52% |
| initiate | 13 | -1.10% | +6.76% | +13.24% |

## Conviction Bucket Analysis
| Bucket | Actions | Avg Conviction | Avg 5D | Avg 20D | Avg 60D |
|--------|---------|----------------|--------|---------|---------|
| low | 0 | N/A | N/A | N/A | N/A |
| medium | 83 | 58 | +1.10% | +4.42% | +15.84% |
| high | 130 | 69 | +1.11% | +6.53% | +19.15% |

## Best Decisions (by 20D forward return)
| Date | Ticker | Action | Conviction | 5D | 20D | 60D |
|------|--------|--------|------------|-----|------|------|
| 2024-11-27 | TSLA | add | 66.5 | +7.27% | +44.15% | — |
| 2024-10-02 | NVDA | add | 68.0 | +7.46% | +20.82% | +16.32% |
| 2024-08-28 | PLTR | initiate | 65.2 | +3.69% | +20.06% | +47.76% |
| 2024-08-07 | AMD | exit | 55.0 | +6.30% | +16.97% | +32.82% |
| 2024-09-04 | TSLA | add | 61.1 | -1.43% | +15.89% | +13.48% |
| 2024-11-20 | PLTR | add | 65.3 | +4.07% | +14.12% | — |
| 2024-09-11 | TSLA | add | 61.1 | -0.59% | +13.10% | +40.81% |
| 2024-08-07 | QCOM | initiate | 50.0 | +4.34% | +11.41% | +8.75% |
| 2024-11-20 | AMZN | add | 67.5 | -0.70% | +10.92% | — |
| 2024-09-04 | META | initiate | 65.7 | -1.55% | +9.97% | +10.72% |

## Worst Decisions (by 20D forward return)
| Date | Ticker | Action | Conviction | 5D | 20D | 60D |
|------|--------|--------|------------|-----|------|------|
| 2024-08-21 | AVGO | add | 72.7 | -3.72% | -10.60% | +8.87% |
| 2024-08-21 | CRWD | exit | 68.8 | -2.69% | -9.32% | +13.52% |
| 2024-08-28 | NVDA | add | 65.3 | -4.97% | -7.97% | +12.69% |
| 2024-08-21 | QCOM | add | 60.6 | -2.71% | -6.72% | -1.39% |
| 2024-09-18 | MSFT | add | 70.8 | +0.63% | -3.74% | -3.67% |
| 2024-10-16 | QCOM | add | 61.1 | -1.44% | -3.25% | -7.07% |
| 2024-08-14 | AVGO | add | 72.7 | +6.35% | -3.11% | +15.47% |
| 2024-09-25 | MSFT | add | 70.8 | -0.42% | -3.09% | -3.30% |
| 2024-08-21 | MSFT | add | 67.9 | -2.51% | -2.34% | -1.41% |
| 2024-08-14 | GOOGL | initiate | 60.6 | +3.93% | -1.88% | +1.92% |

## Per-Name Usefulness Summary
| Ticker | Actions | Docs | Claims | Avg 5D | Avg 20D | Avg 60D | Price Cov |
|--------|---------|------|--------|--------|---------|---------|-----------|
| AAPL | 0 | 7 | 18 | — | — | — | 97% |
| AMD | 2 | 8 | 25 | -0.20% | +12.61% | +23.29% | 97% |
| AMZN | 21 | 4 | 11 | +0.60% | +4.21% | +12.66% | 97% |
| AVGO | 23 | 9 | 37 | +2.04% | +7.51% | +13.79% | 97% |
| CRM | 18 | 8 | 20 | +1.13% | +5.83% | +21.20% | 97% |
| CRWD | 2 | 9 | 23 | +0.72% | -2.64% | +19.25% | 97% |
| GOOGL | 21 | 11 | 28 | +0.30% | +2.69% | +7.72% | 97% |
| INTC | 2 | 10 | 29 | +4.99% | +3.30% | +18.62% | 97% |
| META | 18 | 6 | 16 | +0.33% | +3.48% | +4.86% | 97% |
| MSFT | 22 | 7 | 15 | -0.15% | +0.90% | +1.43% | 97% |
| NOW | 0 | 5 | 18 | — | — | — | 97% |
| NVDA | 23 | 7 | 17 | +0.20% | +2.89% | +11.20% | 97% |
| PLTR | 19 | 6 | 15 | +3.38% | +17.70% | +68.20% | 97% |
| QCOM | 22 | 7 | 19 | +0.70% | -0.35% | -3.00% | 97% |
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
- Recommendation changes: 62
- Change rate: 2.696 per review
- Short-hold exits (<30d): 3

### Action Mix
| Action | Count | % |
|--------|-------|---|
| hold | 168 | 49.0% |
| no_action | 130 | 37.9% |
| add | 29 | 8.5% |
| initiate | 13 | 3.8% |
| exit | 3 | 0.9% |

## Failure Analysis

### Action Types with Negative Forward Returns
- initiate actions have negative avg 5D return (-1.10%)

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
| 2024-08-07 | AMD | 55 | initiate | no | +6.30% | +16.97% | +32.82% | YES |
| 2024-08-21 | CRWD | 69 | initiate | no | -2.69% | -9.32% | +13.52% | YES |
| 2024-08-14 | INTC | 49 | initiate | no | +8.03% | +0.90% | +18.27% | YES |

## Enhanced Failure Analysis

### Premature Exits (stock recovered after exit)
- **AMD** exited 2024-08-07 at conviction 55.0, recovered +32.82% over 60D
- **CRWD** exited 2024-08-21 at conviction 68.8, recovered +13.52% over 60D
- **INTC** exited 2024-08-14 at conviction 49.0, recovered +18.27% over 60D

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
