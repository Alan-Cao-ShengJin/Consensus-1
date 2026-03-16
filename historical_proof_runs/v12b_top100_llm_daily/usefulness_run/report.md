# Historical Proof Run: usefulness_run
Generated: 2026-03-16 05:01 UTC

## Run Configuration
- **Mode**: evaluate_only
- **Backfill window**: 2024-06-01 to 2025-01-01
- **Eval window**: 2024-07-31 to 2025-01-01
- **Cadence**: 1 days
- **Initial cash**: $1,000,000
- **Universe**: 100 tickers
- **Extractor**: real_llm
- **Memory**: enabled
- **Benchmark**: SPY

## Degraded Run Warnings
- **Universe has 100 tickers — consider narrowing for inspectable results**

## Key Metrics
| Metric | Value |
|--------|-------|
| Total return | +22.40% |
| Annualized return | +61.45% |
| Max drawdown | 7.53% |
| Reviews | 155 |
| Purity | degraded |

## Benchmark Comparison
| Benchmark | Return |
|-----------|--------|
| Portfolio | +22.40% |
| SPY | +7.09% |
| Excess vs SPY | +15.31% |
| Equal-weight | +11.58% |
| Excess vs EW | +10.82% |

## Forward Returns by Action Type
| Action | Count | Avg 5D | Avg 20D | Avg 60D |
|--------|-------|--------|---------|---------|
| add | 15 | +2.92% | +2.59% | +16.35% |
| exit | 5 | +0.68% | +11.33% | +11.81% |
| hold | 1496 | +0.94% | +3.64% | +11.65% |
| initiate | 15 | -2.22% | +8.61% | +12.32% |
| trim | 3 | +2.79% | +5.49% | N/A |

## Conviction Bucket Analysis
| Bucket | Actions | Avg Conviction | Avg 5D | Avg 20D | Avg 60D |
|--------|---------|----------------|--------|---------|---------|
| low | 0 | N/A | N/A | N/A | N/A |
| medium | 661 | 53 | +0.46% | +1.65% | +5.06% |
| high | 873 | 73 | +1.28% | +5.38% | +18.32% |

## Best Decisions (by 20D forward return)
| Date | Ticker | Action | Conviction | 5D | 20D | 60D |
|------|--------|--------|------------|-----|------|------|
| 2024-08-03 | PLTR | initiate | 50.0 | +18.35% | +28.46% | +51.54% |
| 2024-09-06 | AMAT | exit | 56.5 | +6.40% | +19.95% | +6.71% |
| 2024-08-27 | PLTR | add | 71.8 | +2.08% | +17.74% | +45.46% |
| 2024-08-07 | AMD | exit | 57.2 | +6.30% | +16.97% | +32.82% |
| 2024-08-26 | PLTR | add | 71.8 | +2.04% | +15.36% | +45.41% |
| 2024-08-02 | AMD | initiate | 60.9 | -2.89% | +14.49% | +20.57% |
| 2024-08-05 | CSCO | initiate | 65.7 | +1.63% | +13.41% | +18.80% |
| 2024-08-02 | MU | exit | 48.8 | -6.36% | +12.47% | +8.21% |
| 2024-08-04 | TXN | initiate | 45.2 | +2.53% | +11.96% | +7.58% |
| 2024-09-11 | ANET | initiate | 61.4 | +4.73% | +11.35% | +16.77% |

## Worst Decisions (by 20D forward return)
| Date | Ticker | Action | Conviction | 5D | 20D | 60D |
|------|--------|--------|------------|-----|------|------|
| 2024-08-14 | NVDA | add | 66.6 | +10.09% | -8.54% | +14.17% |
| 2024-08-14 | KLAC | add | 73.5 | +3.53% | -6.44% | +1.42% |
| 2024-08-03 | INTC | initiate | 58.0 | -4.00% | -3.77% | +4.90% |
| 2024-08-04 | INTC | exit | 55.6 | -7.66% | -3.77% | +4.29% |
| 2024-08-14 | AVGO | add | 77.0 | +6.35% | -3.11% | +15.47% |
| 2024-08-21 | MSFT | add | 61.5 | -2.51% | -2.34% | -1.41% |
| 2024-10-15 | ANET | add | 61.4 | +2.47% | +0.66% | +14.57% |
| 2024-09-03 | AAPL | add | 62.4 | -0.88% | +1.66% | +0.06% |
| 2024-07-31 | MSFT | initiate | 50.0 | -5.55% | +1.72% | +2.50% |
| 2024-08-22 | MSFT | add | 61.5 | -0.41% | +1.80% | +0.78% |

## Per-Name Usefulness Summary
| Ticker | Actions | Docs | Claims | Avg 5D | Avg 20D | Avg 60D | Price Cov |
|--------|---------|------|--------|--------|---------|---------|-----------|
| AAPL | 154 | 7 | 20 | +0.49% | +2.22% | +5.08% | 97% |
| ABBV | 0 | 8 | 25 | — | — | — | 97% |
| ABT | 0 | 5 | 11 | — | — | — | 97% |
| ACN | 0 | 10 | 34 | — | — | — | 97% |
| ADI | 0 | 8 | 18 | — | — | — | 97% |
| AMAT | 36 | 5 | 15 | -0.12% | -1.38% | -0.87% | 97% |
| AMD | 6 | 8 | 37 | +1.73% | +15.93% | +25.82% | 97% |
| AMGN | 0 | 5 | 19 | — | — | — | 97% |
| AMZN | 0 | 4 | 12 | — | — | — | 97% |
| ANET | 113 | 6 | 14 | +1.05% | +4.02% | +8.42% | 97% |
| APH | 0 | 8 | 28 | — | — | — | 97% |
| APP | 0 | 9 | 34 | — | — | — | 97% |
| AVGO | 155 | 9 | 35 | +1.79% | +7.37% | +13.87% | 97% |
| AXP | 0 | 13 | 53 | — | — | — | 97% |
| BA | 0 | 13 | 33 | — | — | — | 97% |
| BAC | 0 | 8 | 20 | — | — | — | 97% |
| BKNG | 0 | 8 | 25 | — | — | — | 97% |
| BLK | 0 | 5 | 17 | — | — | — | 97% |
| BMY | 0 | 5 | 13 | — | — | — | 97% |
| BRK-B | 0 | 5 | 13 | — | — | — | 97% |
| C | 0 | 12 | 24 | — | — | — | 97% |
| CAT | 0 | 7 | 20 | — | — | — | 97% |
| CB | 0 | 9 | 10 | — | — | — | 97% |
| COP | 0 | 12 | 35 | — | — | — | 97% |
| COST | 0 | 9 | 28 | — | — | — | 97% |
| CRM | 0 | 8 | 24 | — | — | — | 97% |
| CRWD | 0 | 9 | 25 | — | — | — | 97% |
| CSCO | 150 | 8 | 24 | +0.96% | +3.47% | +11.91% | 97% |
| CVX | 0 | 9 | 25 | — | — | — | 97% |
| DE | 0 | 7 | 10 | — | — | — | 97% |
| DHR | 0 | 6 | 19 | — | — | — | 97% |
| DIS | 0 | 6 | 14 | — | — | — | 97% |
| ETN | 0 | 7 | 24 | — | — | — | 97% |
| GE | 0 | 6 | 21 | — | — | — | 97% |
| GEV | 0 | 5 | 19 | — | — | — | 97% |
| GILD | 0 | 6 | 17 | — | — | — | 97% |
| GOOGL | 0 | 11 | 45 | — | — | — | 97% |
| GS | 0 | 13 | 26 | — | — | — | 97% |
| HCA | 0 | 6 | 19 | — | — | — | 97% |
| HD | 0 | 9 | 35 | — | — | — | 97% |
| HON | 0 | 13 | 34 | — | — | — | 97% |
| IBM | 0 | 9 | 25 | — | — | — | 97% |
| INTC | 2 | 10 | 39 | -5.83% | -3.77% | +4.59% | 97% |
| INTU | 0 | 7 | 21 | — | — | — | 97% |
| ISRG | 0 | 5 | 13 | — | — | — | 97% |
| JNJ | 0 | 7 | 15 | — | — | — | 97% |
| JPM | 0 | 17 | 37 | — | — | — | 97% |
| KLAC | 147 | 11 | 30 | -0.45% | -3.01% | -10.98% | 97% |
| KO | 0 | 12 | 33 | — | — | — | 97% |
| LIN | 0 | 9 | 33 | — | — | — | 97% |
| LLY | 0 | 10 | 21 | — | — | — | 97% |
| LMT | 0 | 9 | 26 | — | — | — | 97% |
| LOW | 0 | 6 | 19 | — | — | — | 97% |
| LRCX | 2 | 9 | 26 | +1.39% | +10.29% | +5.92% | 97% |
| MA | 0 | 7 | 26 | — | — | — | 97% |
| MCD | 0 | 5 | 17 | — | — | — | 97% |
| MCK | 0 | 9 | 26 | — | — | — | 97% |
| META | 0 | 6 | 20 | — | — | — | 97% |
| MO | 0 | 4 | 11 | — | — | — | 97% |
| MRK | 0 | 5 | 11 | — | — | — | 97% |
| MS | 0 | 8 | 13 | — | — | — | 97% |
| MSFT | 155 | 7 | 20 | +0.11% | +0.85% | +1.95% | 97% |
| MU | 2 | 10 | 36 | -9.34% | +9.59% | +5.19% | 97% |
| NEE | 0 | 13 | 38 | — | — | — | 97% |
| NEM | 0 | 7 | 11 | — | — | — | 97% |
| NFLX | 0 | 6 | 21 | — | — | — | 97% |
| NOW | 0 | 5 | 24 | — | — | — | 97% |
| NVDA | 155 | 7 | 17 | +0.84% | +3.28% | +12.50% | 97% |
| ORCL | 154 | 8 | 27 | +0.82% | +3.79% | +14.49% | 97% |
| PANW | 0 | 8 | 33 | — | — | — | 97% |
| PEP | 0 | 7 | 21 | — | — | — | 97% |
| PFE | 0 | 9 | 21 | — | — | — | 97% |
| PG | 0 | 10 | 20 | — | — | — | 97% |
| PGR | 0 | 11 | 20 | — | — | — | 97% |
| PH | 0 | 6 | 16 | — | — | — | 97% |
| PLD | 0 | 5 | 10 | — | — | — | 97% |
| PLTR | 152 | 6 | 13 | +4.00% | +16.04% | +63.13% | 97% |
| PM | 0 | 16 | 33 | — | — | — | 97% |
| QCOM | 0 | 7 | 19 | — | — | — | 97% |
| RTX | 0 | 8 | 24 | — | — | — | 97% |
| SBUX | 0 | 8 | 20 | — | — | — | 97% |
| SCHW | 0 | 6 | 19 | — | — | — | 97% |
| SPGI | 0 | 7 | 27 | — | — | — | 97% |
| SYK | 0 | 5 | 16 | — | — | — | 97% |
| T | 0 | 7 | 22 | — | — | — | 97% |
| TJX | 0 | 6 | 14 | — | — | — | 97% |
| TMO | 0 | 5 | 11 | — | — | — | 97% |
| TMUS | 0 | 11 | 37 | — | — | — | 97% |
| TSLA | 0 | 7 | 24 | — | — | — | 97% |
| TXN | 151 | 5 | 17 | +0.09% | -0.33% | -1.14% | 97% |
| UBER | 0 | 7 | 21 | — | — | — | 97% |
| UNH | 0 | 9 | 21 | — | — | — | 97% |
| UNP | 0 | 5 | 18 | — | — | — | 97% |
| V | 0 | 7 | 24 | — | — | — | 97% |
| VRTX | 0 | 7 | 18 | — | — | — | 97% |
| VZ | 0 | 16 | 100 | — | — | — | 97% |
| WELL | 0 | 9 | 29 | — | — | — | 97% |
| WFC | 0 | 8 | 15 | — | — | — | 97% |
| WMT | 0 | 10 | 37 | — | — | — | 97% |
| XOM | 0 | 9 | 15 | — | — | — | 97% |

## Source Coverage Diagnostics
- **Extractor mode**: real_llm
- **Benchmark available**: yes
- **Tickers with prices**: 100
- **Tickers without prices**: 0
- **Total price rows**: 14700

### Documents by Source Type
| Source Type | Count |
|------------|-------|
| 10K | 21 |
| 10Q | 185 |
| 8K | 596 |

### Source Gaps
- **ALL**: No documents ingested in 2025-01

## Decision Summary
- Total actions: 15379
- Recommendation changes: 53
- Change rate: 0.342 per review
- Short-hold exits (<30d): 4

### Action Mix
| Action | Count | % |
|--------|-------|---|
| no_action | 13845 | 90.0% |
| hold | 1496 | 9.7% |
| initiate | 15 | 0.1% |
| add | 15 | 0.1% |
| exit | 5 | 0.0% |
| trim | 3 | 0.0% |

## Failure Analysis

### Action Types with Negative Forward Returns
- initiate actions have negative avg 5D return (-2.22%)

## Probation/Exit Diagnostics

### Summary
| Metric | Value |
|--------|-------|
| Total probations | 0 |
| Probation -> exit | 0 |
| Probation resolved (improvement) | 0 |
| Probation false alarms | 0 |
| Total exits | 5 |
| Premature exits (20D recovery >5%) | 4 |
| Premature exits (60D recovery >10%) | 1 |
| Avg forward 20D after exit | +11.33% |

### Exit Events
| Date | Ticker | Conviction | Prior Action | Probation? | 5D | 20D | 60D | Premature? |
|------|--------|------------|--------------|------------|-----|------|------|------------|
| 2024-09-06 | AMAT | 56 | hold | no | +6.40% | +19.95% | +6.71% | YES |
| 2024-08-07 | AMD | 57 | hold | no | +6.30% | +16.97% | +32.82% | YES |
| 2024-08-04 | INTC | 56 | initiate | no | -7.66% | -3.77% | +4.29% |  |
| 2024-08-03 | LRCX | 50 | initiate | no | +4.74% | +11.06% | +7.02% | YES |
| 2024-08-02 | MU | 49 | initiate | no | -6.36% | +12.47% | +8.21% | YES |

## Enhanced Failure Analysis

### Premature Exits (stock recovered after exit)
- **AMAT** exited 2024-09-06 at conviction 56.5, recovered +6.71% over 60D
- **AMD** exited 2024-08-07 at conviction 57.2, recovered +32.82% over 60D
- **LRCX** exited 2024-08-03 at conviction 50.0, recovered +7.02% over 60D
- **MU** exited 2024-08-02 at conviction 48.8, recovered +8.21% over 60D

### Repeatedly Negative Tickers
- **AAPL**: 2 actions with >5% loss at 20D
- **AMAT**: 12 actions with >5% loss at 20D
- **ANET**: 6 actions with >5% loss at 20D
- **AVGO**: 22 actions with >5% loss at 20D
- **KLAC**: 54 actions with >5% loss at 20D
- **MSFT**: 7 actions with >5% loss at 20D
- **NVDA**: 27 actions with >5% loss at 20D
- **ORCL**: 22 actions with >5% loss at 20D
- **PLTR**: 4 actions with >5% loss at 20D
- **TXN**: 24 actions with >5% loss at 20D

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
