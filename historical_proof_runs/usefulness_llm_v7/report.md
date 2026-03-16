# Historical Proof Run: usefulness_llm_v7
Generated: 2026-03-13 22:54 UTC

## Run Configuration
- **Mode**: usefulness_run
- **Backfill window**: 2024-01-01 to 2025-01-01
- **Eval window**: 2025-09-01 to 2025-12-15
- **Cadence**: 7 days
- **Initial cash**: $1,000,000
- **Universe**: 15 tickers
- **Extractor**: stub_heuristic
- **Memory**: enabled
- **Benchmark**: SPY

## Degraded Run Warnings
- **DEGRADED: Running usefulness test with stub extractor. Results reflect heuristic claim extraction, not real LLM analysis. Pass --use-llm for real extraction.**

## Key Metrics
| Metric | Value |
|--------|-------|
| Total return | +3.56% |
| Annualized return | +12.93% |
| Max drawdown | 4.44% |
| Reviews | 16 |
| Purity | degraded |

## Benchmark Comparison
| Benchmark | Return |
|-----------|--------|
| Portfolio | +3.56% |
| SPY | +6.61% |
| Excess vs SPY | -3.05% |
| Equal-weight | +14.98% |
| Excess vs EW | -11.41% |

## Forward Returns by Action Type
| Action | Count | Avg 5D | Avg 20D | Avg 60D |
|--------|-------|--------|---------|---------|
| hold | 162 | -0.17% | +1.33% | +3.10% |
| initiate | 14 | -1.74% | +1.03% | +11.37% |

## Conviction Bucket Analysis
| Bucket | Actions | Avg Conviction | Avg 5D | Avg 20D | Avg 60D |
|--------|---------|----------------|--------|---------|---------|
| low | 0 | N/A | N/A | N/A | N/A |
| medium | 116 | 55 | +0.04% | +2.41% | +6.07% |
| high | 60 | 72 | -0.93% | -0.82% | -1.09% |

## Best Decisions (by 20D forward return)
| Date | Ticker | Action | Conviction | 5D | 20D | 60D |
|------|--------|--------|------------|-----|------|------|
| 2025-09-08 | TSLA | initiate | 50.0 | +14.30% | +27.14% | +24.00% |
| 2025-09-01 | INTC | initiate | 60.1 | +0.57% | +21.48% | +64.23% |
| 2025-09-01 | CRWD | initiate | 53.5 | -1.43% | +18.61% | +28.16% |
| 2025-09-01 | QCOM | initiate | 50.0 | +0.01% | +4.40% | +13.19% |
| 2025-09-01 | NVDA | initiate | 50.0 | -4.11% | +1.44% | +16.26% |
| 2025-11-03 | AAPL | initiate | 54.4 | -0.22% | +1.00% | +1.14% |
| 2025-10-06 | MSFT | initiate | 50.0 | -3.33% | -0.94% | -8.42% |
| 2025-09-08 | AVGO | initiate | 50.0 | +4.11% | -3.05% | +1.27% |
| 2025-09-01 | AMD | initiate | 50.0 | -7.07% | -3.22% | +57.49% |
| 2025-09-08 | CRM | initiate | 67.7 | -3.77% | -3.34% | -4.75% |

## Worst Decisions (by 20D forward return)
| Date | Ticker | Action | Conviction | 5D | 20D | 60D |
|------|--------|--------|------------|-----|------|------|
| 2025-11-03 | PLTR | initiate | 50.0 | -14.12% | -25.26% | -14.21% |
| 2025-11-03 | AMZN | initiate | 50.0 | -3.78% | -13.11% | -9.13% |
| 2025-11-03 | META | initiate | 58.7 | -2.51% | -6.82% | +3.59% |
| 2025-09-29 | NOW | initiate | 50.0 | -3.03% | -3.96% | -13.65% |
| 2025-09-08 | CRM | initiate | 67.7 | -3.77% | -3.34% | -4.75% |
| 2025-09-01 | AMD | initiate | 50.0 | -7.07% | -3.22% | +57.49% |
| 2025-09-08 | AVGO | initiate | 50.0 | +4.11% | -3.05% | +1.27% |
| 2025-10-06 | MSFT | initiate | 50.0 | -3.33% | -0.94% | -8.42% |
| 2025-11-03 | AAPL | initiate | 54.4 | -0.22% | +1.00% | +1.14% |
| 2025-09-01 | NVDA | initiate | 50.0 | -4.11% | +1.44% | +16.26% |

## Per-Name Usefulness Summary
| Ticker | Actions | Docs | Claims | Avg 5D | Avg 20D | Avg 60D | Price Cov |
|--------|---------|------|--------|--------|---------|---------|-----------|
| AAPL | 7 | 3 | 7 | +0.27% | +0.55% | +1.14% | 99% |
| AMD | 16 | 6 | 20 | -0.72% | +4.48% | +18.56% | 99% |
| AMZN | 7 | 3 | 8 | -1.64% | -2.47% | -9.13% | 99% |
| AVGO | 15 | 7 | 25 | -0.81% | -0.68% | +2.95% | 99% |
| CRM | 15 | 6 | 16 | -0.18% | +1.10% | +0.06% | 99% |
| CRWD | 16 | 5 | 18 | -0.06% | +1.49% | +5.27% | 99% |
| GOOGL | 0 | 5 | 14 | — | — | — | 99% |
| INTC | 16 | 13 | 28 | +2.89% | +9.31% | +19.73% | 99% |
| META | 7 | 5 | 14 | +0.26% | +2.44% | +3.59% | 99% |
| MSFT | 11 | 4 | 11 | -1.06% | -1.98% | -7.06% | 99% |
| NOW | 12 | 6 | 10 | -1.10% | -3.58% | -12.77% | 99% |
| NVDA | 16 | 4 | 8 | -1.09% | +0.11% | +0.98% | 99% |
| PLTR | 7 | 2 | 6 | -2.11% | -0.36% | -14.21% | 99% |
| QCOM | 16 | 6 | 12 | -0.25% | +0.85% | +3.48% | 99% |
| TSLA | 15 | 5 | 16 | -0.06% | +1.86% | +2.67% | 99% |

## Source Coverage Diagnostics
- **Extractor mode**: stub_heuristic
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
- **ALL**: No documents ingested in 2024-01
- **ALL**: No documents ingested in 2024-02
- **ALL**: No documents ingested in 2024-03
- **ALL**: No documents ingested in 2024-04
- **ALL**: No documents ingested in 2024-05
- **ALL**: No documents ingested in 2024-06
- **ALL**: No documents ingested in 2024-07
- **ALL**: No documents ingested in 2024-08
- **ALL**: No documents ingested in 2024-09
- **ALL**: No documents ingested in 2024-10
- **ALL**: No documents ingested in 2024-11
- **ALL**: No documents ingested in 2024-12
- **ALL**: No documents ingested in 2025-01

## Decision Summary
- Total actions: 191
- Recommendation changes: 14
- Change rate: 0.875 per review
- Short-hold exits (<30d): 0

### Action Mix
| Action | Count | % |
|--------|-------|---|
| hold | 162 | 84.8% |
| no_action | 15 | 7.9% |
| initiate | 14 | 7.3% |

## Failure Analysis

### Degraded Run Flags
- Stub extraction: claims are heuristic, not LLM-generated

### Sparse Coverage Tickers
| Ticker | Issues | Docs | Claims | Price Cov |
|--------|--------|------|--------|-----------|
| PLTR | only 2 documents | 2 | 6 | 98.7% |

### Action Types with Negative Forward Returns
- hold actions have negative avg 5D return (-0.17%)
- initiate actions have negative avg 5D return (-1.74%)

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
- **AMD**: 3 actions with >5% loss at 20D
- **AMZN**: 2 actions with >5% loss at 20D
- **AVGO**: 5 actions with >5% loss at 20D
- **CRM**: 2 actions with >5% loss at 20D
- **CRWD**: 3 actions with >5% loss at 20D
- **INTC**: 4 actions with >5% loss at 20D
- **NOW**: 6 actions with >5% loss at 20D
- **NVDA**: 2 actions with >5% loss at 20D
- **PLTR**: 2 actions with >5% loss at 20D
- **QCOM**: 3 actions with >5% loss at 20D
- **TSLA**: 3 actions with >5% loss at 20D

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
