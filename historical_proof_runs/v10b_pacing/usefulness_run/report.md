# Historical Proof Run: usefulness_run
Generated: 2026-03-15 01:01 UTC

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
| Total return | +9.67% |
| Annualized return | +24.47% |
| Max drawdown | 6.28% |
| Reviews | 23 |
| Purity | degraded |

## Benchmark Comparison
| Benchmark | Return |
|-----------|--------|
| Portfolio | +9.67% |
| SPY | +7.09% |
| Excess vs SPY | +2.58% |
| Equal-weight | +28.21% |
| Excess vs EW | -18.53% |

## Forward Returns by Action Type
| Action | Count | Avg 5D | Avg 20D | Avg 60D |
|--------|-------|--------|---------|---------|
| exit | 10 | +4.22% | +8.33% | +21.02% |
| hold | 177 | +0.84% | +4.03% | +10.05% |
| initiate | 20 | -0.66% | +4.74% | +9.29% |

## Conviction Bucket Analysis
| Bucket | Actions | Avg Conviction | Avg 5D | Avg 20D | Avg 60D |
|--------|---------|----------------|--------|---------|---------|
| low | 0 | N/A | N/A | N/A | N/A |
| medium | 207 | 50 | +0.86% | +4.32% | +10.71% |
| high | 0 | N/A | N/A | N/A | N/A |

## Best Decisions (by 20D forward return)
| Date | Ticker | Action | Conviction | 5D | 20D | 60D |
|------|--------|--------|------------|-----|------|------|
| 2024-08-07 | NVDA | exit | 50.0 | +10.22% | +29.71% | +26.31% |
| 2024-08-07 | AVGO | exit | 50.0 | +9.06% | +18.43% | +30.05% |
| 2024-09-04 | INTC | initiate | 50.0 | -1.85% | +17.40% | +19.40% |
| 2024-08-07 | AMD | exit | 50.0 | +6.30% | +16.97% | +32.82% |
| 2024-09-11 | INTC | exit | 50.0 | +6.47% | +15.53% | +33.40% |
| 2024-08-07 | QCOM | initiate | 50.0 | +4.34% | +11.41% | +8.75% |
| 2024-09-04 | META | initiate | 50.0 | -1.55% | +9.97% | +10.72% |
| 2024-09-18 | CRWD | initiate | 50.0 | +9.74% | +9.69% | +26.07% |
| 2024-07-31 | NVDA | initiate | 50.0 | -14.16% | +8.74% | +3.75% |
| 2024-07-31 | AMD | initiate | 50.0 | -6.69% | +8.25% | +13.75% |

## Worst Decisions (by 20D forward return)
| Date | Ticker | Action | Conviction | 5D | 20D | 60D |
|------|--------|--------|------------|-----|------|------|
| 2024-08-21 | CRWD | exit | 50.0 | -2.69% | -9.32% | +13.52% |
| 2024-08-28 | NVDA | initiate | 50.0 | -4.97% | -7.97% | +12.69% |
| 2024-08-14 | QCOM | exit | 50.0 | +4.25% | -2.34% | +2.22% |
| 2024-08-14 | GOOGL | initiate | 50.0 | +3.93% | -1.88% | +1.92% |
| 2024-09-11 | QCOM | exit | 50.0 | +0.03% | -0.47% | +2.61% |
| 2024-08-14 | INTC | exit | 50.0 | +8.03% | +0.90% | +18.27% |
| 2024-08-21 | TSLA | initiate | 50.0 | -4.51% | +1.30% | -1.15% |
| 2024-09-04 | QCOM | initiate | 50.0 | -2.26% | +1.50% | +0.48% |
| 2024-09-18 | AAPL | initiate | 50.0 | +2.62% | +2.30% | +2.07% |
| 2024-08-28 | AVGO | initiate | 50.0 | +2.93% | +2.71% | +9.73% |

## Per-Name Usefulness Summary
| Ticker | Actions | Docs | Claims | Avg 5D | Avg 20D | Avg 60D | Price Cov |
|--------|---------|------|--------|--------|---------|---------|-----------|
| AAPL | 16 | 7 | 8 | +0.90% | +3.21% | +6.97% | 97% |
| AMD | 19 | 8 | 8 | +0.56% | -0.30% | -5.94% | 97% |
| AMZN | 21 | 4 | 4 | +0.60% | +4.21% | +12.66% | 97% |
| AVGO | 21 | 9 | 9 | +2.11% | +9.11% | +14.03% | 97% |
| CRM | 0 | 8 | 8 | — | — | — | 97% |
| CRWD | 4 | 9 | 9 | +2.27% | +2.49% | +23.63% | 97% |
| GOOGL | 21 | 11 | 11 | +0.30% | +2.69% | +7.72% | 97% |
| INTC | 6 | 10 | 11 | +2.35% | +9.88% | +22.51% | 97% |
| META | 18 | 6 | 6 | +0.33% | +3.48% | +4.86% | 97% |
| MSFT | 22 | 7 | 7 | -0.15% | +0.90% | +1.43% | 97% |
| NOW | 0 | 5 | 5 | — | — | — | 97% |
| NVDA | 21 | 7 | 7 | -0.20% | +4.57% | +11.26% | 97% |
| PLTR | 0 | 6 | 6 | — | — | — | 97% |
| QCOM | 18 | 7 | 9 | +0.93% | -0.05% | -2.88% | 97% |
| TSLA | 20 | 7 | 7 | +2.59% | +14.13% | +47.01% | 97% |

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
- Recommendation changes: 48
- Change rate: 2.087 per review
- Short-hold exits (<30d): 9

### Action Mix
| Action | Count | % |
|--------|-------|---|
| hold | 177 | 51.6% |
| no_action | 136 | 39.7% |
| initiate | 20 | 5.8% |
| exit | 10 | 2.9% |

## Failure Analysis

### Degraded Run Flags
- Stub extraction: claims are heuristic, not LLM-generated

### Action Types with Negative Forward Returns
- initiate actions have negative avg 5D return (-0.66%)

## Probation/Exit Diagnostics

### Summary
| Metric | Value |
|--------|-------|
| Total probations | 0 |
| Probation -> exit | 0 |
| Probation resolved (improvement) | 0 |
| Probation false alarms | 0 |
| Total exits | 10 |
| Premature exits (20D recovery >5%) | 5 |
| Premature exits (60D recovery >10%) | 7 |
| Avg forward 20D after exit | +8.33% |

### Exit Events
| Date | Ticker | Conviction | Prior Action | Probation? | 5D | 20D | 60D | Premature? |
|------|--------|------------|--------------|------------|-----|------|------|------------|
| 2024-08-07 | AMD | 50 | initiate | no | +6.30% | +16.97% | +32.82% | YES |
| 2024-12-18 | AMD | 50 | hold | no | +2.63% | - | - |  |
| 2024-08-07 | AVGO | 50 | initiate | no | +9.06% | +18.43% | +30.05% | YES |
| 2024-08-21 | CRWD | 50 | initiate | no | -2.69% | -9.32% | +13.52% | YES |
| 2024-09-25 | CRWD | 50 | initiate | no | -2.09% | +5.53% | +29.95% | YES |
| 2024-08-14 | INTC | 50 | initiate | no | +8.03% | +0.90% | +18.27% | YES |
| 2024-09-11 | INTC | 50 | initiate | no | +6.47% | +15.53% | +33.40% | YES |
| 2024-08-07 | NVDA | 50 | initiate | no | +10.22% | +29.71% | +26.31% | YES |
| 2024-08-14 | QCOM | 50 | initiate | no | +4.25% | -2.34% | +2.22% |  |
| 2024-09-11 | QCOM | 50 | initiate | no | +0.03% | -0.47% | +2.61% |  |

## Enhanced Failure Analysis

### Premature Exits (stock recovered after exit)
- **AMD** exited 2024-08-07 at conviction 50.0, recovered +32.82% over 60D
- **AVGO** exited 2024-08-07 at conviction 50.0, recovered +30.05% over 60D
- **CRWD** exited 2024-08-21 at conviction 50.0, recovered +13.52% over 60D
- **CRWD** exited 2024-09-25 at conviction 50.0, recovered +29.95% over 60D
- **INTC** exited 2024-08-14 at conviction 50.0, recovered +18.27% over 60D
- **INTC** exited 2024-09-11 at conviction 50.0, recovered +33.40% over 60D
- **NVDA** exited 2024-08-07 at conviction 50.0, recovered +26.31% over 60D

### Repeatedly Negative Tickers
- **AMD**: 8 actions with >5% loss at 20D
- **AVGO**: 2 actions with >5% loss at 20D
- **META**: 2 actions with >5% loss at 20D
- **NVDA**: 3 actions with >5% loss at 20D
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
