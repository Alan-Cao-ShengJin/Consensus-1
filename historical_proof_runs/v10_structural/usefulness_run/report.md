# Historical Proof Run: usefulness_run
Generated: 2026-03-15 00:55 UTC

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
| Total return | +11.58% |
| Annualized return | +29.65% |
| Max drawdown | 6.41% |
| Reviews | 23 |
| Purity | degraded |

## Benchmark Comparison
| Benchmark | Return |
|-----------|--------|
| Portfolio | +11.58% |
| SPY | +7.09% |
| Excess vs SPY | +4.49% |
| Equal-weight | +28.21% |
| Excess vs EW | -16.63% |

## Forward Returns by Action Type
| Action | Count | Avg 5D | Avg 20D | Avg 60D |
|--------|-------|--------|---------|---------|
| exit | 6 | +6.05% | +18.70% | +24.92% |
| hold | 196 | +0.95% | +4.68% | +15.38% |
| initiate | 17 | -5.58% | +2.28% | +6.91% |
| trim | 7 | +4.23% | +7.13% | +18.47% |

## Conviction Bucket Analysis
| Bucket | Actions | Avg Conviction | Avg 5D | Avg 20D | Avg 60D |
|--------|---------|----------------|--------|---------|---------|
| low | 0 | N/A | N/A | N/A | N/A |
| medium | 226 | 50 | +0.68% | +4.93% | +14.92% |
| high | 0 | N/A | N/A | N/A | N/A |

## Best Decisions (by 20D forward return)
| Date | Ticker | Action | Conviction | 5D | 20D | 60D |
|------|--------|--------|------------|-----|------|------|
| 2024-08-07 | NVDA | exit | 50.0 | +10.22% | +29.71% | +26.31% |
| 2024-07-31 | PLTR | initiate | 50.0 | -10.41% | +20.19% | +37.00% |
| 2024-08-07 | AVGO | exit | 50.0 | +9.06% | +18.43% | +30.05% |
| 2024-09-04 | INTC | trim | 50.0 | -1.85% | +17.40% | +19.40% |
| 2024-08-07 | CRWD | exit | 50.0 | +3.76% | +16.98% | +26.69% |
| 2024-08-07 | AMD | exit | 50.0 | +6.30% | +16.97% | +32.82% |
| 2024-09-11 | INTC | trim | 50.0 | +6.47% | +15.53% | +33.40% |
| 2024-07-31 | CRWD | initiate | 50.0 | -4.27% | +14.90% | +23.24% |
| 2024-09-18 | INTC | trim | 50.0 | +8.62% | +12.28% | +17.24% |
| 2024-08-07 | QCOM | exit | 50.0 | +4.34% | +11.41% | +8.75% |

## Worst Decisions (by 20D forward return)
| Date | Ticker | Action | Conviction | 5D | 20D | 60D |
|------|--------|--------|------------|-----|------|------|
| 2024-07-31 | INTC | initiate | 50.0 | -34.58% | -31.28% | -21.73% |
| 2024-08-21 | INTC | trim | 50.0 | -5.98% | -11.35% | +6.35% |
| 2024-08-28 | NVDA | initiate | 50.0 | -4.97% | -7.97% | +12.69% |
| 2024-07-31 | QCOM | initiate | 50.0 | -12.71% | -4.89% | -5.49% |
| 2024-07-31 | GOOGL | initiate | 50.0 | -7.16% | -2.54% | -4.30% |
| 2024-08-14 | AAPL | initiate | 50.0 | +1.88% | +0.47% | +2.63% |
| 2024-08-14 | INTC | trim | 50.0 | +8.03% | +0.90% | +18.27% |
| 2024-07-31 | MSFT | initiate | 50.0 | -5.55% | +1.72% | +2.50% |
| 2024-08-28 | AMD | initiate | 50.0 | +1.50% | +3.05% | +6.74% |
| 2024-07-31 | AVGO | initiate | 50.0 | -11.58% | +3.28% | +7.83% |

## Per-Name Usefulness Summary
| Ticker | Actions | Docs | Claims | Avg 5D | Avg 20D | Avg 60D | Price Cov |
|--------|---------|------|--------|--------|---------|---------|-----------|
| AAPL | 21 | 7 | 8 | +0.70% | +2.21% | +5.18% | 97% |
| AMD | 19 | 8 | 8 | +0.56% | -0.30% | -5.94% | 97% |
| AMZN | 21 | 4 | 4 | +0.60% | +4.21% | +12.66% | 97% |
| AVGO | 2 | 9 | 9 | -1.26% | +10.86% | +18.94% | 97% |
| CRM | 0 | 8 | 8 | — | — | — | 97% |
| CRWD | 2 | 9 | 9 | -0.26% | +15.94% | +24.96% | 97% |
| GOOGL | 23 | 11 | 11 | +0.04% | +2.47% | +6.75% | 97% |
| INTC | 10 | 10 | 11 | -0.87% | +2.33% | +13.44% | 97% |
| META | 23 | 6 | 6 | +0.45% | +3.23% | +8.08% | 97% |
| MSFT | 23 | 7 | 7 | -0.39% | +0.94% | +1.50% | 97% |
| NOW | 0 | 5 | 5 | — | — | — | 97% |
| NVDA | 21 | 7 | 7 | -0.20% | +4.57% | +11.26% | 97% |
| PLTR | 23 | 6 | 6 | +2.80% | +16.29% | +60.77% | 97% |
| QCOM | 17 | 7 | 9 | +0.13% | -0.07% | -5.16% | 97% |
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
- Recommendation changes: 32
- Change rate: 1.391 per review
- Short-hold exits (<30d): 5

### Action Mix
| Action | Count | % |
|--------|-------|---|
| hold | 196 | 57.1% |
| no_action | 117 | 34.1% |
| initiate | 17 | 5.0% |
| trim | 7 | 2.0% |
| exit | 6 | 1.7% |

## Failure Analysis

### Degraded Run Flags
- Stub extraction: claims are heuristic, not LLM-generated

### Action Types with Negative Forward Returns
- initiate actions have negative avg 5D return (-5.58%)

## Probation/Exit Diagnostics

### Summary
| Metric | Value |
|--------|-------|
| Total probations | 0 |
| Probation -> exit | 0 |
| Probation resolved (improvement) | 0 |
| Probation false alarms | 0 |
| Total exits | 6 |
| Premature exits (20D recovery >5%) | 5 |
| Premature exits (60D recovery >10%) | 4 |
| Avg forward 20D after exit | +18.70% |

### Exit Events
| Date | Ticker | Conviction | Prior Action | Probation? | 5D | 20D | 60D | Premature? |
|------|--------|------------|--------------|------------|-----|------|------|------------|
| 2024-08-07 | AMD | 50 | initiate | no | +6.30% | +16.97% | +32.82% | YES |
| 2024-12-18 | AMD | 50 | hold | no | +2.63% | - | - |  |
| 2024-08-07 | AVGO | 50 | initiate | no | +9.06% | +18.43% | +30.05% | YES |
| 2024-08-07 | CRWD | 50 | initiate | no | +3.76% | +16.98% | +26.69% | YES |
| 2024-08-07 | NVDA | 50 | initiate | no | +10.22% | +29.71% | +26.31% | YES |
| 2024-08-07 | QCOM | 50 | initiate | no | +4.34% | +11.41% | +8.75% | YES |

## Enhanced Failure Analysis

### Premature Exits (stock recovered after exit)
- **AMD** exited 2024-08-07 at conviction 50.0, recovered +32.82% over 60D
- **AVGO** exited 2024-08-07 at conviction 50.0, recovered +30.05% over 60D
- **CRWD** exited 2024-08-07 at conviction 50.0, recovered +26.69% over 60D
- **NVDA** exited 2024-08-07 at conviction 50.0, recovered +26.31% over 60D
- **QCOM** exited 2024-08-07 at conviction 50.0, recovered +8.75% over 60D

### Repeatedly Negative Tickers
- **AMD**: 8 actions with >5% loss at 20D
- **META**: 3 actions with >5% loss at 20D
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
