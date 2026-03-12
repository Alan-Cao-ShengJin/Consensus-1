# Step 8: Replay Engine + Shadow Portfolio

## What Step 8 Adds

A replay and evaluation layer that runs the decision engine through historical time under leakage-aware constraints, optionally applying recommendations to a shadow (paper) portfolio to measure whether the decision engine deserves capital.

**Core principle:** Replay consumes recommendation outputs, not executed-state assumptions. The shadow portfolio is separate from the live DB state.

## Architecture

```
Historical DB (prices, claims, theses, checkpoints)
    │
    ├── replay_engine.py         → per-date review with as-of filtering
    │       run_replay_review()  → build snapshots from shadow state + DB research
    │       generate_review_dates()
    │
    ├── shadow_portfolio.py      → simulated portfolio (cash + positions)
    │       apply_trade()        → deterministic position management
    │       take_snapshot()      → point-in-time state capture
    │
    ├── shadow_execution_policy.py → recommendation → shadow trade translation
    │       apply_recommendations()
    │       get_execution_price()   → next-trading-day close lookup
    │
    ├── replay_metrics.py        → performance + discipline + integrity metrics
    │       compute_metrics()
    │
    ├── replay_runner.py         → orchestrator: start/end/cadence → full run
    │       run_replay()         → returns (result, portfolio, metrics)
    │       export_replay_json() → file-based output
    │
    └── scripts/run_replay.py    → CLI entrypoint
```

## Files

| File | Purpose |
|------|---------|
| `replay_engine.py` | Core replay loop: date stepping, snapshot building from shadow + DB |
| `shadow_portfolio.py` | Simulated portfolio: cash, positions, trades, snapshots, PnL |
| `shadow_execution_policy.py` | Deterministic policy: recommendation → shadow trade |
| `replay_metrics.py` | Performance, discipline, and integrity metrics |
| `replay_runner.py` | Orchestrator + JSON export + text report |
| `scripts/run_replay.py` | CLI: `--start`, `--end`, `--json`, `--no-apply`, `--ticker` |
| `tests/test_replay.py` | 28 tests covering leakage, execution, shadow portfolio, metrics |
| `portfolio_review_service.py` | Modified: as-of filtering for prices, claims, thesis state |

## As-of-Date Leakage Controls

Every replay date sees **only information that was knowable on that date**.

### What is filtered

| Data | Filter | Anti-leakage rule |
|------|--------|-------------------|
| **Prices** | `Price.date <= as_of` | No future prices in valuation or price-change calculations |
| **Claims (7-day window)** | `published_at >= cutoff AND published_at <= as_of` | Upper bound prevents future claims from counting |
| **Thesis state/conviction** | `ThesisStateHistory.created_at <= as_of` | Uses historical state, not live mutable Thesis record |
| **Checkpoints** | `Checkpoint.date_expected >= as_of` | Already correct (looks forward from review date) |
| **Execution price** | `Price.date > review_date` (strictly after) | Next-trading-day close, not same-day |

### Thesis state fallback

If no `ThesisStateHistory` entry exists before `as_of`:
1. If `Thesis.created_at <= as_of`: use current live thesis state (known v1 impurity)
2. If `Thesis.created_at > as_of`: thesis didn't exist yet → return FORMING/None

## Replay Assumptions

### Starting state

**Default: all-cash.** The shadow portfolio starts with `initial_cash` and zero positions. No inherited live DB positions. This is the clean evaluation mode.

### Execution assumption

**Next-trading-day close execution.**
- Recommendations generated using data as-of review date T
- Shadow trades execute at the close price on the first trading day **after** T
- This ensures the execution price was not available when the recommendation was formed
- If no next-day price exists (e.g., final replay date), the trade is skipped and logged as unfillable

### Execution policy (deterministic)

| Recommendation | Shadow trade |
|----------------|-------------|
| INITIATE | Buy to target starter weight |
| ADD | Increase weight per recommendation delta |
| TRIM | Reduce weight per recommendation delta |
| EXIT | Fully exit position |
| HOLD | No trade |
| PROBATION | No trade (probation state tracked on shadow position) |
| NO_ACTION | No trade |

Funded pairings: if `funded_by_ticker` is present, the funding exit/trim executes first to free capital.

### Transaction costs

- Configurable basis points (default 10bp / 0.1%)
- Applied to notional value of each trade
- No slippage model

## Known v1 Impurities (documented, not hidden)

1. **Candidate pool** — Uses current `Candidate` table. No `created_at` on Candidate, so candidates added after replay start date appear earlier than they should.

2. **Valuation inputs** — `valuation_gap_pct` and `base_case_rerating` come from the current Thesis record. `ThesisStateHistory` does not track these fields. These use current values regardless of replay date.

3. **Checkpoint ingestion timing** — Checkpoints may have been ingested into the DB after the replay date but with `date_expected` before it. No `created_at` on Checkpoint table to filter by.

4. **Early thesis fallback** — Theses created before history tracking was enabled use their current live state as a frozen approximation when no `ThesisStateHistory` entry exists.

5. **Portfolio starting state** — Research state is replayed as-of historical date with leakage controls. Portfolio starting state is always all-cash (clean). If the replay starts from current positions (optional future mode), that inherits live state limitations.

## Metrics Produced

### Performance metrics
- Total return (%)
- Annualized return (% if period allows)
- Max drawdown (% with peak/trough dates)

### Activity metrics
- Count by action type: initiations, adds, trims, exits, holds, probations, blocked
- Hit rate (v1 placeholder — per-exit PnL tracking needed for precision)
- Average holding period (days)

### Turnover metrics
- Total turnover (%)
- Average turnover per review (%)

### Cash exposure metrics
- Average, min, max cash as % of portfolio

### Discipline metrics
- Probation → exit count (how often probation eventually led to exit)
- Funded pairing usage count
- Turnover cap blocked count
- Average conviction at initiation
- Action distribution by month

### Replay integrity metrics
- Number of review dates processed
- Number of recommendations generated
- Number of trades applied vs skipped
- Number of fallback behaviors used
- Number of missing-price events
- Dates skipped due to missing data

## How to Run

```bash
# Basic weekly replay
python scripts/run_replay.py --start 2025-01-01 --end 2025-12-31

# With custom initial cash
python scripts/run_replay.py --start 2025-01-01 --end 2025-12-31 --initial-cash 500000

# Recommendation history only (no shadow trades)
python scripts/run_replay.py --start 2025-01-01 --end 2025-12-31 --no-apply

# JSON output
python scripts/run_replay.py --start 2025-01-01 --end 2025-12-31 --json

# Export full results to file
python scripts/run_replay.py --start 2025-01-01 --end 2025-12-31 --export

# Single ticker
python scripts/run_replay.py --ticker NVDA --start 2025-01-01 --end 2025-06-30

# Biweekly cadence
python scripts/run_replay.py --start 2025-01-01 --end 2025-12-31 --cadence 14

# Custom transaction cost (5bp)
python scripts/run_replay.py --start 2025-01-01 --end 2025-12-31 --cost-bps 5

# Verbose logging
python scripts/run_replay.py --start 2025-01-01 --end 2025-12-31 -v
```

## Persistence

**v1: file-based + in-memory.** No new DB tables or migrations.

- Replay results stored as JSON files in `replay_outputs/` (one per run)
- Shadow portfolio state is in-memory dataclasses with `to_dict()` / JSON export
- Tradeoff: not queryable via SQL, but avoids schema coupling
- Replay is an evaluation tool — DB persistence can be added if replay proves useful

## Tests (28 total)

### Leakage prevention
- Price lookup returns latest on-or-before as_of, not absolute latest
- Price change 5d uses only prices on-or-before as_of
- Live mode (as_of=None) still returns absolute latest
- Claim 7-day window excludes claims published after as_of
- Thesis state uses ThesisStateHistory, not live mutable Thesis
- Thesis fallback to live state if no history exists before as_of
- Thesis created after as_of returns FORMING/None

### Execution causality
- Next-day execution price comes from strictly after review date
- No execution price when no future data exists

### Shadow portfolio determinism
- INITIATE creates position
- EXIT removes position and tracks realized PnL
- ADD increases position size
- HOLD / PROBATION / NO_ACTION do not create trades
- Transaction cost applied correctly

### Funded pairing execution
- Funded initiation produces both exit and initiate trades

### Replay modes
- Replay from all-cash with no inherited positions
- Replay with --no-apply produces recommendation history only

### Engine integration
- Turnover cap respected through replay path

### Metrics
- Max drawdown computes correctly on toy peak→trough→recovery path
- Total return computes correctly
- Zero drawdown on flat portfolio
- Replay integrity fields in run result and metrics output

### Consistency
- Review date generation at correct cadence
- Preloaded prices sorted ascending
- Portfolio snapshot captures position values and weights

## Limitations

- No per-exit hit rate tracking (requires avg_cost at exit time — v1 placeholder)
- No replay from live positions (default is all-cash only)
- Candidate pool uses current DB state (no temporal filtering)
- Valuation gap/rerating use current thesis values (not historically versioned)
- No multi-run comparison or parameter sweep
- No visualization or charting
- File-based output only (no DB persistence for replay results)
- No intraday execution modeling

## What Remains for Step 9

- Per-exit PnL tracking for true hit rate
- Replay from live positions mode (optional)
- Multi-run comparison framework
- Parameter sensitivity analysis (conviction thresholds, turnover caps)
- Visualization / charting of replay results
- DB persistence for replay results (if needed)
- Temporal filtering for candidates (add created_at to Candidate table)
- Temporal filtering for checkpoints (add created_at to Checkpoint table)
- Historical valuation_gap_pct / base_case_rerating tracking in ThesisStateHistory
- Portfolio-level risk constraints (sector concentration, correlation)
- Real execution layer (broker integration, order routing)
- Performance attribution by action type
