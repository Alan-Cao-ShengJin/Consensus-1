# Historical Proof Run: full_llm_v1
Generated: 2026-03-13 23:44 UTC

## Run Configuration
- **Mode**: usefulness_run
- **Backfill window**: 2025-06-01 to 2026-03-01
- **Eval window**: 2025-09-01 to 2026-03-01
- **Cadence**: 7 days
- **Initial cash**: $1,000,000
- **Universe**: 5 tickers
- **Extractor**: real_llm
- **Memory**: enabled
- **Benchmark**: SPY

## Regeneration Summary
- Documents processed: 53
- Claims created: 0
- Thesis updates: 0
- State changes: 0
- State flips: 0

### Data Coverage
- Tickers with price data: 5/5
- Total price rows: 890
- Total documents: 53
  - 10K: 5
  - 10Q: 10
  - 8K: 38

## Key Metrics
| Metric | Value |
|--------|-------|
| Total return | +0.00% |
| Annualized return | +0.00% |
| Max drawdown | 0.00% |
| Reviews | 26 |
| Purity | strict |

## Benchmark Comparison
| Benchmark | Return |
|-----------|--------|
| Portfolio | +0.00% |
| SPY | +7.76% |
| Excess vs SPY | -7.76% |

## Conviction Bucket Analysis
| Bucket | Actions | Avg Conviction | Avg 5D | Avg 20D | Avg 60D |
|--------|---------|----------------|--------|---------|---------|
| low | 0 | N/A | N/A | N/A | N/A |
| medium | 0 | N/A | N/A | N/A | N/A |
| high | 0 | N/A | N/A | N/A | N/A |

## Per-Name Usefulness Summary
| Ticker | Actions | Docs | Claims | Avg 5D | Avg 20D | Avg 60D | Price Cov |
|--------|---------|------|--------|--------|---------|---------|-----------|
| AAPL | 0 | 11 | 0 | — | — | — | 96% |
| AMD | 0 | 14 | 0 | — | — | — | 96% |
| META | 0 | 10 | 0 | — | — | — | 96% |
| MSFT | 0 | 9 | 0 | — | — | — | 96% |
| NVDA | 0 | 9 | 0 | — | — | — | 96% |

## Source Coverage Diagnostics
- **Extractor mode**: real_llm
- **Benchmark available**: yes
- **Tickers with prices**: 5
- **Tickers without prices**: 0
- **Total price rows**: 890

### Documents by Source Type
| Source Type | Count |
|------------|-------|
| 10K | 5 |
| 10Q | 10 |
| 8K | 38 |

### Source Gaps
- **ALL**: No documents ingested in 2025-06
- **ALL**: No documents ingested in 2026-03

## Decision Summary
- Total actions: 0
- Recommendation changes: 0
- Change rate: 0.000 per review
- Short-hold exits (<30d): 0

## Failure Analysis

### Sparse Coverage Tickers
| Ticker | Issues | Docs | Claims | Price Cov |
|--------|--------|------|--------|-----------|
| AAPL | no claims extracted | 11 | 0 | 95.9% |
| AMD | no claims extracted | 14 | 0 | 95.9% |
| META | no claims extracted | 10 | 0 | 95.9% |
| MSFT | no claims extracted | 9 | 0 | 95.9% |
| NVDA | no claims extracted | 9 | 0 | 95.9% |

### Low Evidence Periods
- Only 1 document(s) in 2025-09

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

## Warnings
- Claim extraction failed for NVDA doc 1: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for MSFT doc 2: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for AMD doc 3: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for AAPL doc 4: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for AAPL doc 5: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for MSFT doc 6: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for MSFT doc 7: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for META doc 8: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for AAPL doc 9: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for META doc 10: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for AAPL doc 11: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for NVDA doc 12: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for AMD doc 13: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for AMD doc 14: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for AMD doc 15: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for NVDA doc 16: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for NVDA doc 17: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for MSFT doc 18: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for AMD doc 19: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for AMD doc 20: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for MSFT doc 21: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for MSFT doc 22: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for META doc 23: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for META doc 24: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for AAPL doc 25: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for AAPL doc 26: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for META doc 27: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for AMD doc 28: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for AMD doc 29: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for NVDA doc 30: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for NVDA doc 31: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for AAPL doc 32: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for MSFT doc 33: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for META doc 34: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for AMD doc 35: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for META doc 36: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for AAPL doc 37: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for META doc 38: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for AMD doc 39: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for NVDA doc 40: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for MSFT doc 41: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for MSFT doc 42: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for META doc 43: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for META doc 44: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for AAPL doc 45: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for AAPL doc 46: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for AMD doc 47: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for AMD doc 48: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for AMD doc 49: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for AMD doc 50: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for AAPL doc 51: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for NVDA doc 52: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- Claim extraction failed for NVDA doc 53: OPENAI_API_KEY environment variable is not set. Set it before using the LLM extractor.
- No action outcomes generated — check data availability

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
