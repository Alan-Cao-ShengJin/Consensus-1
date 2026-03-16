# Historical Proof Run: historical_proof
Generated: 2026-03-16 04:38 UTC

## Run Configuration
- **Mode**: evaluate_only
- **Backfill window**: 2024-06-01 to 2025-01-01
- **Eval window**: 2024-07-31 to 2025-01-01
- **Cadence**: 7 days
- **Initial cash**: $1,000,000
- **Universe**: 100 tickers
- **Extractor**: stub_heuristic
- **Memory**: enabled
- **Benchmark**: SPY

## Degraded Run Warnings
- **DEGRADED: Running usefulness test with stub extractor. Results reflect heuristic claim extraction, not real LLM analysis. Pass --use-llm for real extraction.**
- **Universe has 100 tickers — consider narrowing for inspectable results**

## Key Metrics
| Metric | Value |
|--------|-------|
| Total return | +15.42% |
| Annualized return | +40.49% |
| Max drawdown | 6.63% |
| Reviews | 23 |
| Purity | degraded |

## Benchmark Comparison
| Benchmark | Return |
|-----------|--------|
| Portfolio | +15.42% |
| SPY | +7.09% |
| Excess vs SPY | +8.34% |
| Equal-weight | +11.58% |
| Excess vs EW | +3.85% |

## Forward Returns by Action Type
| Action | Count | Avg 5D | Avg 20D | Avg 60D |
|--------|-------|--------|---------|---------|
| add | 11 | +1.58% | -2.06% | +7.98% |
| exit | 4 | +5.55% | +0.50% | +6.80% |
| hold | 187 | +0.78% | +3.19% | +9.36% |
| initiate | 13 | +0.83% | +2.81% | +11.84% |
| trim | 3 | -0.80% | N/A | N/A |

## Conviction Bucket Analysis
| Bucket | Actions | Avg Conviction | Avg 5D | Avg 20D | Avg 60D |
|--------|---------|----------------|--------|---------|---------|
| low | 0 | N/A | N/A | N/A | N/A |
| medium | 105 | 53 | +0.79% | +0.10% | +2.31% |
| high | 113 | 72 | +0.97% | +5.47% | +17.24% |

## Best Decisions (by 20D forward return)
| Date | Ticker | Action | Conviction | 5D | 20D | 60D |
|------|--------|--------|------------|-----|------|------|
| 2024-09-04 | PLTR | initiate | 71.8 | +13.11% | +20.63% | +37.04% |
| 2024-11-20 | PLTR | add | 70.8 | +4.07% | +14.12% | — |
| 2024-08-07 | MU | initiate | 61.2 | +9.03% | +12.74% | +17.80% |
| 2024-08-14 | CSCO | initiate | 52.3 | +9.99% | +10.17% | +20.30% |
| 2024-08-07 | ORCL | initiate | 65.7 | +5.31% | +9.99% | +35.71% |
| 2024-08-28 | INTC | exit | 51.1 | +12.39% | +9.48% | +15.66% |
| 2024-08-07 | AAPL | initiate | 50.0 | +3.79% | +8.80% | +8.22% |
| 2024-07-31 | NVDA | initiate | 66.6 | -14.16% | +8.74% | +3.75% |
| 2024-09-11 | AMD | add | 65.1 | +1.48% | +6.60% | -1.27% |
| 2024-12-11 | PLTR | add | 73.8 | +4.47% | +4.30% | — |

## Worst Decisions (by 20D forward return)
| Date | Ticker | Action | Conviction | 5D | 20D | 60D |
|------|--------|--------|------------|-----|------|------|
| 2024-08-21 | LRCX | initiate | 79.5 | -6.23% | -16.23% | -16.34% |
| 2024-08-21 | NVDA | add | 66.6 | -1.59% | -15.88% | +7.40% |
| 2024-08-14 | MU | exit | 58.8 | +8.19% | -11.78% | +6.60% |
| 2024-08-21 | INTC | initiate | 58.0 | -5.98% | -11.35% | +6.35% |
| 2024-08-21 | AVGO | add | 77.0 | -3.72% | -10.60% | +8.87% |
| 2024-08-21 | AMD | add | 62.5 | -4.96% | -9.49% | -1.17% |
| 2024-08-14 | AMAT | initiate | 50.0 | +4.62% | -8.88% | +1.90% |
| 2024-08-14 | NVDA | add | 66.6 | +10.09% | -8.54% | +14.17% |
| 2024-08-14 | AVGO | add | 77.0 | +6.35% | -3.11% | +15.47% |
| 2024-08-14 | AMD | initiate | 60.9 | +10.32% | -2.71% | +19.28% |

## Per-Name Usefulness Summary
| Ticker | Actions | Docs | Claims | Avg 5D | Avg 20D | Avg 60D | Price Cov |
|--------|---------|------|--------|--------|---------|---------|-----------|
| AAPL | 22 | 7 | 20 | +0.85% | +2.56% | +5.40% | 97% |
| ABBV | 0 | 8 | 25 | — | — | — | 97% |
| ABT | 0 | 5 | 11 | — | — | — | 97% |
| ACN | 0 | 10 | 34 | — | — | — | 97% |
| ADI | 0 | 8 | 18 | — | — | — | 97% |
| AMAT | 21 | 5 | 15 | +0.24% | -2.76% | -7.55% | 97% |
| AMD | 21 | 8 | 37 | +0.67% | -2.38% | -8.13% | 97% |
| AMGN | 0 | 5 | 19 | — | — | — | 97% |
| AMZN | 0 | 4 | 12 | — | — | — | 97% |
| ANET | 0 | 6 | 14 | — | — | — | 97% |
| APH | 0 | 8 | 28 | — | — | — | 97% |
| APP | 0 | 9 | 34 | — | — | — | 97% |
| AVGO | 23 | 9 | 35 | +2.04% | +7.51% | +13.79% | 97% |
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
| CSCO | 21 | 8 | 24 | +0.94% | +2.99% | +11.26% | 97% |
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
| INTC | 2 | 10 | 39 | +3.21% | -0.93% | +11.00% | 97% |
| INTU | 0 | 7 | 21 | — | — | — | 97% |
| ISRG | 0 | 5 | 13 | — | — | — | 97% |
| JNJ | 0 | 7 | 15 | — | — | — | 97% |
| JPM | 0 | 17 | 37 | — | — | — | 97% |
| KLAC | 0 | 11 | 30 | — | — | — | 97% |
| KO | 0 | 12 | 33 | — | — | — | 97% |
| LIN | 0 | 9 | 33 | — | — | — | 97% |
| LLY | 0 | 10 | 21 | — | — | — | 97% |
| LMT | 0 | 9 | 26 | — | — | — | 97% |
| LOW | 0 | 6 | 19 | — | — | — | 97% |
| LRCX | 3 | 9 | 26 | -2.73% | -5.67% | -7.14% | 97% |
| MA | 0 | 7 | 26 | — | — | — | 97% |
| MCD | 0 | 5 | 17 | — | — | — | 97% |
| MCK | 0 | 9 | 26 | — | — | — | 97% |
| META | 0 | 6 | 20 | — | — | — | 97% |
| MO | 0 | 4 | 11 | — | — | — | 97% |
| MRK | 0 | 5 | 11 | — | — | — | 97% |
| MS | 0 | 8 | 13 | — | — | — | 97% |
| MSFT | 23 | 7 | 20 | -0.39% | +0.94% | +1.50% | 97% |
| MU | 2 | 10 | 36 | +8.61% | +0.48% | +12.20% | 97% |
| NEE | 0 | 13 | 38 | — | — | — | 97% |
| NEM | 0 | 7 | 11 | — | — | — | 97% |
| NFLX | 0 | 6 | 21 | — | — | — | 97% |
| NOW | 0 | 5 | 24 | — | — | — | 97% |
| NVDA | 23 | 7 | 17 | +0.20% | +2.89% | +11.20% | 97% |
| ORCL | 22 | 8 | 27 | +0.62% | +3.73% | +13.60% | 97% |
| PANW | 0 | 8 | 33 | — | — | — | 97% |
| PEP | 0 | 7 | 21 | — | — | — | 97% |
| PFE | 0 | 9 | 21 | — | — | — | 97% |
| PG | 0 | 10 | 20 | — | — | — | 97% |
| PGR | 0 | 11 | 20 | — | — | — | 97% |
| PH | 0 | 6 | 16 | — | — | — | 97% |
| PLD | 0 | 5 | 10 | — | — | — | 97% |
| PLTR | 18 | 6 | 13 | +3.36% | +17.54% | +70.24% | 97% |
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
| TXN | 17 | 5 | 17 | +0.11% | -1.66% | -3.22% | 97% |
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
- **Extractor mode**: stub_heuristic
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
- Total actions: 2279
- Recommendation changes: 44
- Change rate: 1.913 per review
- Short-hold exits (<30d): 3

### Action Mix
| Action | Count | % |
|--------|-------|---|
| no_action | 2061 | 90.4% |
| hold | 187 | 8.2% |
| initiate | 13 | 0.6% |
| add | 11 | 0.5% |
| exit | 4 | 0.2% |
| trim | 3 | 0.1% |

## Failure Analysis

### Degraded Run Flags
- Stub extraction: claims are heuristic, not LLM-generated

### Action Types with Negative Forward Returns
- add actions have negative avg 20D return (-2.06%)
- trim actions have negative avg 5D return (-0.80%)

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
| Total exits | 4 |
| Premature exits (20D recovery >5%) | 1 |
| Premature exits (60D recovery >10%) | 1 |
| Avg forward 20D after exit | +0.50% |

### Exit Events
| Date | Ticker | Conviction | Prior Action | Probation? | 5D | 20D | 60D | Premature? |
|------|--------|------------|--------------|------------|-----|------|------|------------|
| 2025-01-01 | AMD | 66 | hold | no | - | - | - |  |
| 2024-08-28 | INTC | 51 | initiate | no | +12.39% | +9.48% | +15.66% | YES |
| 2024-09-04 | LRCX | 70 | hold | no | -3.94% | +3.80% | -1.85% |  |
| 2024-08-14 | MU | 59 | initiate | no | +8.19% | -11.78% | +6.60% |  |

## Enhanced Failure Analysis

### Premature Exits (stock recovered after exit)
- **INTC** exited 2024-08-28 at conviction 51.1, recovered +15.66% over 60D

### Repeatedly Negative Tickers
- **AMAT**: 7 actions with >5% loss at 20D
- **AMD**: 9 actions with >5% loss at 20D
- **AVGO**: 3 actions with >5% loss at 20D
- **NVDA**: 5 actions with >5% loss at 20D
- **ORCL**: 4 actions with >5% loss at 20D
- **TXN**: 2 actions with >5% loss at 20D

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
