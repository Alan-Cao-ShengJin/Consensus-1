# Historical Proof Run: usefulness_run
Generated: 2026-03-15 05:41 UTC

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
- Claims created: 312
- Thesis updates: 103
- State changes: 34
- State flips: 12

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
| Total return | +8.84% |
| Annualized return | +22.23% |
| Max drawdown | 6.25% |
| Reviews | 23 |
| Purity | degraded |

## Benchmark Comparison
| Benchmark | Return |
|-----------|--------|
| Portfolio | +8.84% |
| SPY | +7.09% |
| Excess vs SPY | +1.75% |
| Equal-weight | +28.21% |
| Excess vs EW | -19.37% |

## Forward Returns by Action Type
| Action | Count | Avg 5D | Avg 20D | Avg 60D |
|--------|-------|--------|---------|---------|
| add | 9 | +1.09% | +4.42% | -7.18% |
| exit | 8 | +2.75% | +8.36% | +19.64% |
| hold | 170 | +0.83% | +3.83% | +10.62% |
| initiate | 17 | -0.77% | +4.15% | +8.35% |
| trim | 4 | +1.01% | N/A | N/A |

## Conviction Bucket Analysis
| Bucket | Actions | Avg Conviction | Avg 5D | Avg 20D | Avg 60D |
|--------|---------|----------------|--------|---------|---------|
| low | 3 | 38 | +0.20% | N/A | N/A |
| medium | 122 | 56 | +0.89% | +4.26% | +10.20% |
| high | 83 | 69 | +0.64% | +3.74% | +9.49% |

## Best Decisions (by 20D forward return)
| Date | Ticker | Action | Conviction | 5D | 20D | 60D |
|------|--------|--------|------------|-----|------|------|
| 2024-08-07 | NVDA | exit | 50.0 | +10.22% | +29.71% | +26.31% |
| 2024-08-07 | AVGO | exit | 71.8 | +9.06% | +18.43% | +30.05% |
| 2024-08-07 | AMD | exit | 55.5 | +6.30% | +16.97% | +32.82% |
| 2024-09-18 | AMD | add | 64.7 | +5.71% | +16.53% | -9.03% |
| 2024-08-07 | QCOM | initiate | 50.0 | +4.34% | +11.41% | +8.75% |
| 2024-11-20 | AMZN | add | 64.4 | -0.70% | +10.92% | — |
| 2024-09-04 | META | initiate | 65.7 | -1.55% | +9.97% | +10.72% |
| 2024-09-18 | CRWD | initiate | 71.2 | +9.74% | +9.69% | +26.07% |
| 2024-07-31 | NVDA | initiate | 50.0 | -14.16% | +8.74% | +3.75% |
| 2024-07-31 | AMD | initiate | 57.8 | -6.69% | +8.25% | +13.75% |

## Worst Decisions (by 20D forward return)
| Date | Ticker | Action | Conviction | 5D | 20D | 60D |
|------|--------|--------|------------|-----|------|------|
| 2024-08-21 | CRWD | exit | 69.4 | -2.69% | -9.32% | +13.52% |
| 2024-08-28 | NVDA | initiate | 66.2 | -4.97% | -7.97% | +12.69% |
| 2024-10-02 | AMD | add | 64.7 | +7.00% | -3.56% | -14.14% |
| 2024-09-25 | AMD | add | 64.7 | +1.27% | -3.32% | -14.61% |
| 2024-10-09 | AMD | add | 64.7 | -3.36% | -2.79% | -18.96% |
| 2024-08-14 | QCOM | exit | 54.6 | +4.25% | -2.34% | +2.22% |
| 2024-09-11 | QCOM | exit | 56.9 | +0.03% | -0.47% | +2.61% |
| 2024-08-14 | AAPL | initiate | 56.0 | +1.88% | +0.47% | +2.63% |
| 2024-08-21 | TSLA | initiate | 51.5 | -4.51% | +1.30% | -1.15% |
| 2024-09-04 | QCOM | initiate | 56.9 | -2.26% | +1.50% | +0.48% |

## Per-Name Usefulness Summary
| Ticker | Actions | Docs | Claims | Avg 5D | Avg 20D | Avg 60D | Price Cov |
|--------|---------|------|--------|--------|---------|---------|-----------|
| AAPL | 21 | 7 | 18 | +0.70% | +2.21% | +5.18% | 97% |
| AMD | 20 | 8 | 28 | +0.38% | -0.30% | -5.94% | 97% |
| AMZN | 21 | 4 | 11 | +0.60% | +4.21% | +12.66% | 97% |
| AVGO | 21 | 9 | 36 | +2.11% | +9.11% | +14.03% | 97% |
| CRM | 0 | 8 | 18 | — | — | — | 97% |
| CRWD | 4 | 9 | 28 | +2.27% | +2.49% | +23.63% | 97% |
| GOOGL | 22 | 11 | 24 | +0.39% | +2.74% | +7.54% | 97% |
| INTC | 0 | 10 | 27 | — | — | — | 97% |
| META | 18 | 6 | 18 | +0.33% | +3.48% | +4.86% | 97% |
| MSFT | 22 | 7 | 17 | -0.15% | +0.90% | +1.43% | 97% |
| NOW | 0 | 5 | 21 | — | — | — | 97% |
| NVDA | 21 | 7 | 13 | -0.20% | +4.57% | +11.26% | 97% |
| PLTR | 0 | 6 | 14 | — | — | — | 97% |
| QCOM | 18 | 7 | 17 | +0.93% | -0.05% | -2.88% | 97% |
| TSLA | 20 | 7 | 22 | +2.59% | +14.13% | +47.01% | 97% |

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
- Recommendation changes: 52
- Change rate: 2.261 per review
- Short-hold exits (<30d): 7

### Action Mix
| Action | Count | % |
|--------|-------|---|
| hold | 170 | 49.6% |
| no_action | 135 | 39.4% |
| initiate | 17 | 5.0% |
| add | 9 | 2.6% |
| exit | 8 | 2.3% |
| trim | 4 | 1.2% |

## Failure Analysis

### Action Types with Negative Forward Returns
- initiate actions have negative avg 5D return (-0.77%)

### Non-Differentiating Conviction Buckets
- Conviction buckets do not meaningfully differentiate outcomes (spread: 0.52%)

## Probation/Exit Diagnostics

### Summary
| Metric | Value |
|--------|-------|
| Total probations | 0 |
| Probation -> exit | 0 |
| Probation resolved (improvement) | 0 |
| Probation false alarms | 0 |
| Total exits | 8 |
| Premature exits (20D recovery >5%) | 4 |
| Premature exits (60D recovery >10%) | 5 |
| Avg forward 20D after exit | +8.36% |

### Exit Events
| Date | Ticker | Conviction | Prior Action | Probation? | 5D | 20D | 60D | Premature? |
|------|--------|------------|--------------|------------|-----|------|------|------------|
| 2024-08-07 | AMD | 55 | initiate | no | +6.30% | +16.97% | +32.82% | YES |
| 2024-12-25 | AMD | 70 | trim | no | -3.05% | - | - |  |
| 2024-08-07 | AVGO | 72 | initiate | no | +9.06% | +18.43% | +30.05% | YES |
| 2024-08-21 | CRWD | 69 | initiate | no | -2.69% | -9.32% | +13.52% | YES |
| 2024-09-25 | CRWD | 71 | initiate | no | -2.09% | +5.53% | +29.95% | YES |
| 2024-08-07 | NVDA | 50 | initiate | no | +10.22% | +29.71% | +26.31% | YES |
| 2024-08-14 | QCOM | 55 | initiate | no | +4.25% | -2.34% | +2.22% |  |
| 2024-09-11 | QCOM | 57 | initiate | no | +0.03% | -0.47% | +2.61% |  |

## Enhanced Failure Analysis

### Premature Exits (stock recovered after exit)
- **AMD** exited 2024-08-07 at conviction 55.5, recovered +32.82% over 60D
- **AVGO** exited 2024-08-07 at conviction 71.8, recovered +30.05% over 60D
- **CRWD** exited 2024-08-21 at conviction 69.4, recovered +13.52% over 60D
- **CRWD** exited 2024-09-25 at conviction 71.2, recovered +29.95% over 60D
- **NVDA** exited 2024-08-07 at conviction 50.0, recovered +26.31% over 60D

### Repeatedly Negative Tickers
- **AMD**: 8 actions with >5% loss at 20D
- **AVGO**: 2 actions with >5% loss at 20D
- **META**: 2 actions with >5% loss at 20D
- **NVDA**: 3 actions with >5% loss at 20D
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
