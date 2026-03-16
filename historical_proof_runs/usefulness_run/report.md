# Historical Proof Run: usefulness_run
Generated: 2026-03-14 20:20 UTC

## Run Configuration
- **Mode**: usefulness_run
- **Backfill window**: 2024-06-01 to 2025-01-01
- **Eval window**: 2024-07-31 to 2025-01-01
- **Cadence**: 7 days
- **Initial cash**: $1,000,000
- **Universe**: 15 tickers
- **Extractor**: stub_heuristic
- **Memory**: enabled
- **Benchmark**: SPY

## Degraded Run Warnings
- **DEGRADED: Running usefulness test with stub extractor. Results reflect heuristic claim extraction, not real LLM analysis. Pass --use-llm for real extraction.**

## Regeneration Summary
- Documents processed: 111
- Claims created: 115
- Thesis updates: 111
- State changes: 15
- State flips: 0

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
| Total return | +10.54% |
| Annualized return | +26.82% |
| Max drawdown | 7.92% |
| Reviews | 23 |
| Purity | degraded |

## Benchmark Comparison
| Benchmark | Return |
|-----------|--------|
| Portfolio | +10.54% |
| SPY | +7.09% |
| Excess vs SPY | +3.45% |
| Equal-weight | +28.21% |
| Excess vs EW | -17.66% |

## Forward Returns by Action Type
| Action | Count | Avg 5D | Avg 20D | Avg 60D |
|--------|-------|--------|---------|---------|
| add | 44 | +0.89% | +3.26% | +6.41% |
| exit | 14 | +2.85% | +10.11% | +16.97% |
| hold | 243 | +1.03% | +4.42% | +15.99% |
| initiate | 29 | -1.13% | +2.75% | +10.81% |
| trim | 8 | +4.03% | +7.13% | +18.47% |

## Conviction Bucket Analysis
| Bucket | Actions | Avg Conviction | Avg 5D | Avg 20D | Avg 60D |
|--------|---------|----------------|--------|---------|---------|
| low | 0 | N/A | N/A | N/A | N/A |
| medium | 338 | 50 | +0.97% | +4.42% | +14.24% |
| high | 0 | N/A | N/A | N/A | N/A |

## Best Decisions (by 20D forward return)
| Date | Ticker | Action | Conviction | 5D | 20D | 60D |
|------|--------|--------|------------|-----|------|------|
| 2024-11-27 | TSLA | add | 50.0 | +7.27% | +44.15% | — |
| 2024-12-04 | AVGO | add | 50.0 | +4.91% | +40.90% | — |
| 2024-08-07 | NVDA | exit | 50.0 | +10.22% | +29.71% | +26.31% |
| 2024-07-31 | PLTR | initiate | 50.0 | -10.41% | +20.19% | +37.00% |
| 2024-08-28 | PLTR | add | 50.0 | +3.69% | +20.06% | +47.76% |
| 2024-08-07 | AVGO | exit | 50.0 | +9.06% | +18.43% | +30.05% |
| 2024-09-04 | INTC | trim | 50.0 | -1.85% | +17.40% | +19.40% |
| 2024-08-07 | CRWD | exit | 50.0 | +3.76% | +16.98% | +26.69% |
| 2024-08-07 | AMD | exit | 50.0 | +6.30% | +16.97% | +32.82% |
| 2024-09-04 | TSLA | add | 50.0 | -1.43% | +15.89% | +13.48% |

## Worst Decisions (by 20D forward return)
| Date | Ticker | Action | Conviction | 5D | 20D | 60D |
|------|--------|--------|------------|-----|------|------|
| 2024-07-31 | INTC | initiate | 50.0 | -34.58% | -31.28% | -21.73% |
| 2024-11-20 | INTC | add | 50.0 | +3.58% | -16.03% | — |
| 2024-08-21 | NVDA | add | 50.0 | -1.59% | -15.88% | +7.40% |
| 2024-10-02 | TSLA | add | 50.0 | -3.29% | -12.47% | +38.61% |
| 2024-08-21 | INTC | trim | 50.0 | -5.98% | -11.35% | +6.35% |
| 2024-08-21 | AMD | add | 50.0 | -4.96% | -9.49% | -1.17% |
| 2024-08-21 | CRWD | exit | 50.0 | -2.69% | -9.32% | +13.52% |
| 2024-08-14 | NVDA | initiate | 50.0 | +10.09% | -8.54% | +14.17% |
| 2024-08-28 | NVDA | add | 50.0 | -4.97% | -7.97% | +12.69% |
| 2024-08-21 | QCOM | add | 50.0 | -2.71% | -6.72% | -1.39% |

## Per-Name Usefulness Summary
| Ticker | Actions | Docs | Claims | Avg 5D | Avg 20D | Avg 60D | Price Cov |
|--------|---------|------|--------|--------|---------|---------|-----------|
| AAPL | 22 | 7 | 8 | +0.85% | +2.56% | +5.40% | 97% |
| AMD | 22 | 8 | 8 | +0.59% | -0.88% | -3.94% | 97% |
| AMZN | 22 | 4 | 4 | +0.69% | +4.32% | +12.80% | 97% |
| AVGO | 23 | 9 | 9 | +2.04% | +7.51% | +13.79% | 97% |
| CRM | 22 | 8 | 8 | +1.29% | +4.60% | +19.27% | 97% |
| CRWD | 23 | 9 | 9 | +1.45% | +6.21% | +20.99% | 97% |
| GOOGL | 23 | 11 | 11 | +0.04% | +2.47% | +6.75% | 97% |
| INTC | 23 | 10 | 11 | +0.31% | -0.77% | +3.95% | 97% |
| META | 23 | 6 | 6 | +0.45% | +3.23% | +8.08% | 97% |
| MSFT | 23 | 7 | 7 | -0.39% | +0.94% | +1.50% | 97% |
| NOW | 22 | 5 | 5 | +1.31% | +4.70% | +15.85% | 97% |
| NVDA | 23 | 7 | 7 | +0.20% | +2.89% | +11.20% | 97% |
| PLTR | 23 | 6 | 6 | +2.80% | +16.29% | +60.77% | 97% |
| QCOM | 23 | 7 | 9 | +0.09% | -0.57% | -3.17% | 97% |
| TSLA | 21 | 7 | 7 | +2.99% | +13.60% | +44.02% | 97% |

## Source Coverage Diagnostics
- **Extractor mode**: stub_heuristic
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
- Recommendation changes: 109
- Change rate: 4.739 per review
- Short-hold exits (<30d): 12

### Action Mix
| Action | Count | % |
|--------|-------|---|
| hold | 243 | 70.8% |
| add | 44 | 12.8% |
| initiate | 29 | 8.5% |
| exit | 14 | 4.1% |
| trim | 8 | 2.3% |
| no_action | 5 | 1.5% |

## Failure Analysis

### Degraded Run Flags
- Stub extraction: claims are heuristic, not LLM-generated

### Action Types with Negative Forward Returns
- initiate actions have negative avg 5D return (-1.13%)

### Repeated Bad Recommendations
- INTC had 2 initiate/add actions followed by >5% loss at 20D
- NVDA had 3 initiate/add actions followed by >5% loss at 20D

## Probation/Exit Diagnostics

### Summary
| Metric | Value |
|--------|-------|
| Total probations | 0 |
| Probation -> exit | 0 |
| Probation resolved (improvement) | 0 |
| Probation false alarms | 0 |
| Total exits | 14 |
| Premature exits (20D recovery >5%) | 8 |
| Premature exits (60D recovery >10%) | 8 |
| Avg forward 20D after exit | +10.11% |

### Exit Events
| Date | Ticker | Conviction | Prior Action | Probation? | 5D | 20D | 60D | Premature? |
|------|--------|------------|--------------|------------|-----|------|------|------------|
| 2024-08-07 | AMD | 50 | initiate | no | +6.30% | +16.97% | +32.82% | YES |
| 2024-12-25 | AMD | 50 | trim | no | -3.05% | - | - |  |
| 2024-08-07 | AVGO | 50 | initiate | no | +9.06% | +18.43% | +30.05% | YES |
| 2024-08-07 | CRWD | 50 | initiate | no | +3.76% | +16.98% | +26.69% | YES |
| 2024-08-21 | CRWD | 50 | initiate | no | -2.69% | -9.32% | +13.52% | YES |
| 2024-09-04 | CRWD | 50 | initiate | no | -4.91% | +11.27% | +16.89% | YES |
| 2024-09-18 | CRWD | 50 | initiate | no | +9.74% | +9.69% | +26.07% | YES |
| 2024-10-02 | CRWD | 50 | initiate | no | +2.40% | +10.09% | +23.45% | YES |
| 2024-10-02 | INTC | 50 | initiate | no | -0.04% | +0.04% | +7.41% |  |
| 2024-10-16 | INTC | 50 | initiate | no | +2.38% | +4.53% | -8.83% |  |
| 2024-12-18 | INTC | 50 | hold | no | +4.66% | - | - |  |
| 2024-08-07 | NVDA | 50 | initiate | no | +10.22% | +29.71% | +26.31% | YES |
| 2024-08-07 | QCOM | 50 | initiate | no | +4.34% | +11.41% | +8.75% | YES |
| 2024-09-04 | QCOM | 50 | hold | no | -2.26% | +1.50% | +0.48% |  |

## Enhanced Failure Analysis

### Premature Exits (stock recovered after exit)
- **AMD** exited 2024-08-07 at conviction 50.0, recovered +32.82% over 60D
- **AVGO** exited 2024-08-07 at conviction 50.0, recovered +30.05% over 60D
- **CRWD** exited 2024-08-07 at conviction 50.0, recovered +26.69% over 60D
- **CRWD** exited 2024-08-21 at conviction 50.0, recovered +13.52% over 60D
- **CRWD** exited 2024-09-04 at conviction 50.0, recovered +16.89% over 60D
- **CRWD** exited 2024-09-18 at conviction 50.0, recovered +26.07% over 60D
- **CRWD** exited 2024-10-02 at conviction 50.0, recovered +23.45% over 60D
- **NVDA** exited 2024-08-07 at conviction 50.0, recovered +26.31% over 60D
- **QCOM** exited 2024-08-07 at conviction 50.0, recovered +8.75% over 60D

### Repeatedly Negative Tickers
- **AMD**: 9 actions with >5% loss at 20D
- **AVGO**: 3 actions with >5% loss at 20D
- **CRM**: 3 actions with >5% loss at 20D
- **INTC**: 5 actions with >5% loss at 20D
- **META**: 3 actions with >5% loss at 20D
- **NVDA**: 5 actions with >5% loss at 20D
- **QCOM**: 2 actions with >5% loss at 20D
- **TSLA**: 2 actions with >5% loss at 20D

## Limitations
- **Stub LLM mode**: claim extraction uses deterministic stub, not real LLM
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
