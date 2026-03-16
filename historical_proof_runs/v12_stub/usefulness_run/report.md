# Historical Proof Run: usefulness_run
Generated: 2026-03-15 06:18 UTC

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
| Total return | +13.73% |
| Annualized return | +35.65% |
| Max drawdown | 6.43% |
| Reviews | 23 |
| Purity | degraded |

## Benchmark Comparison
| Benchmark | Return |
|-----------|--------|
| Portfolio | +13.73% |
| SPY | +7.09% |
| Excess vs SPY | +6.64% |
| Equal-weight | +28.21% |
| Excess vs EW | -14.48% |

## Forward Returns by Action Type
| Action | Count | Avg 5D | Avg 20D | Avg 60D |
|--------|-------|--------|---------|---------|
| exit | 3 | +3.88% | +2.85% | +21.54% |
| hold | 197 | +1.22% | +5.60% | +17.76% |
| initiate | 13 | -1.10% | +6.76% | +13.24% |

## Conviction Bucket Analysis
| Bucket | Actions | Avg Conviction | Avg 5D | Avg 20D | Avg 60D |
|--------|---------|----------------|--------|---------|---------|
| low | 0 | N/A | N/A | N/A | N/A |
| medium | 213 | 50 | +1.11% | +5.64% | +17.40% |
| high | 0 | N/A | N/A | N/A | N/A |

## Best Decisions (by 20D forward return)
| Date | Ticker | Action | Conviction | 5D | 20D | 60D |
|------|--------|--------|------------|-----|------|------|
| 2024-08-28 | PLTR | initiate | 50.0 | +3.69% | +20.06% | +47.76% |
| 2024-08-07 | AMD | exit | 50.0 | +6.30% | +16.97% | +32.82% |
| 2024-08-07 | QCOM | initiate | 50.0 | +4.34% | +11.41% | +8.75% |
| 2024-09-04 | META | initiate | 50.0 | -1.55% | +9.97% | +10.72% |
| 2024-09-04 | CRM | initiate | 50.0 | -0.78% | +9.36% | +19.18% |
| 2024-07-31 | NVDA | initiate | 50.0 | -14.16% | +8.74% | +3.75% |
| 2024-07-31 | AMD | initiate | 50.0 | -6.69% | +8.25% | +13.75% |
| 2024-08-07 | INTC | initiate | 50.0 | +1.95% | +5.69% | +18.96% |
| 2024-08-07 | MSFT | initiate | 50.0 | +2.10% | +4.05% | +4.61% |
| 2024-08-14 | CRWD | initiate | 50.0 | +4.12% | +4.05% | +24.97% |

## Worst Decisions (by 20D forward return)
| Date | Ticker | Action | Conviction | 5D | 20D | 60D |
|------|--------|--------|------------|-----|------|------|
| 2024-08-21 | CRWD | exit | 50.0 | -2.69% | -9.32% | +13.52% |
| 2024-08-14 | GOOGL | initiate | 50.0 | +3.93% | -1.88% | +1.92% |
| 2024-08-14 | INTC | exit | 50.0 | +8.03% | +0.90% | +18.27% |
| 2024-08-21 | TSLA | initiate | 50.0 | -4.51% | +1.30% | -1.15% |
| 2024-07-31 | AVGO | initiate | 50.0 | -11.58% | +3.28% | +7.83% |
| 2024-08-14 | AMZN | initiate | 50.0 | +4.77% | +3.62% | +11.01% |
| 2024-08-14 | CRWD | initiate | 50.0 | +4.12% | +4.05% | +24.97% |
| 2024-08-07 | MSFT | initiate | 50.0 | +2.10% | +4.05% | +4.61% |
| 2024-08-07 | INTC | initiate | 50.0 | +1.95% | +5.69% | +18.96% |
| 2024-07-31 | AMD | initiate | 50.0 | -6.69% | +8.25% | +13.75% |

## Per-Name Usefulness Summary
| Ticker | Actions | Docs | Claims | Avg 5D | Avg 20D | Avg 60D | Price Cov |
|--------|---------|------|--------|--------|---------|---------|-----------|
| AAPL | 0 | 7 | 8 | — | — | — | 97% |
| AMD | 2 | 8 | 8 | -0.20% | +12.61% | +23.29% | 97% |
| AMZN | 21 | 4 | 4 | +0.60% | +4.21% | +12.66% | 97% |
| AVGO | 23 | 9 | 9 | +2.04% | +7.51% | +13.79% | 97% |
| CRM | 18 | 8 | 8 | +1.13% | +5.83% | +21.20% | 97% |
| CRWD | 2 | 9 | 9 | +0.72% | -2.64% | +19.25% | 97% |
| GOOGL | 21 | 11 | 11 | +0.30% | +2.69% | +7.72% | 97% |
| INTC | 2 | 10 | 11 | +4.99% | +3.30% | +18.62% | 97% |
| META | 18 | 6 | 6 | +0.33% | +3.48% | +4.86% | 97% |
| MSFT | 22 | 7 | 7 | -0.15% | +0.90% | +1.43% | 97% |
| NOW | 0 | 5 | 5 | — | — | — | 97% |
| NVDA | 23 | 7 | 7 | +0.20% | +2.89% | +11.20% | 97% |
| PLTR | 19 | 6 | 6 | +3.38% | +17.70% | +68.20% | 97% |
| QCOM | 22 | 7 | 9 | +0.70% | -0.35% | -3.00% | 97% |
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
- Recommendation changes: 26
- Change rate: 1.130 per review
- Short-hold exits (<30d): 3

### Action Mix
| Action | Count | % |
|--------|-------|---|
| hold | 197 | 57.4% |
| no_action | 130 | 37.9% |
| initiate | 13 | 3.8% |
| exit | 3 | 0.9% |

## Failure Analysis

### Degraded Run Flags
- Stub extraction: claims are heuristic, not LLM-generated

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
| 2024-08-07 | AMD | 50 | initiate | no | +6.30% | +16.97% | +32.82% | YES |
| 2024-08-21 | CRWD | 50 | initiate | no | -2.69% | -9.32% | +13.52% | YES |
| 2024-08-14 | INTC | 50 | initiate | no | +8.03% | +0.90% | +18.27% | YES |

## Enhanced Failure Analysis

### Premature Exits (stock recovered after exit)
- **AMD** exited 2024-08-07 at conviction 50.0, recovered +32.82% over 60D
- **CRWD** exited 2024-08-21 at conviction 50.0, recovered +13.52% over 60D
- **INTC** exited 2024-08-14 at conviction 50.0, recovered +18.27% over 60D

### Repeatedly Negative Tickers
- **AVGO**: 3 actions with >5% loss at 20D
- **CRM**: 2 actions with >5% loss at 20D
- **META**: 2 actions with >5% loss at 20D
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
