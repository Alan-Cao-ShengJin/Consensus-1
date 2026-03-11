# Step 7: Portfolio Decision Engine

## What Step 7 Adds

The first portfolio layer: converts thesis state + conviction + valuation context + checkpoint timing into concrete portfolio actions under capital constraints.

Output is not "interesting thesis notes." It is explicit decisions: initiate, add, hold, trim, probation, exit, or no_action.

**Core principle:** LLM is not used in the decision engine. All decisions are deterministic code using thesis state, conviction score, valuation zone, evidence signals, checkpoint timing, and capital constraints.

## Architecture

```
Thesis State + Conviction
    │
    ├── valuation_policy.py    → zone classification (BUY/HOLD/TRIM/FULL_EXIT)
    │
    ├── portfolio_decision_engine.py  → per-ticker decisions
    │       evaluate_holding()        → holding action
    │       evaluate_candidate()      → initiation gate check
    │       run_decision_engine()     → ranked + turnover-capped
    │
    ├── portfolio_review_service.py   → weekly review loop
    │       build snapshots from DB
    │       call engine
    │       apply side effects (probation, cooldown)
    │       persist review + decisions
    │
    └── scripts/run_portfolio_review.py → CLI entrypoint
```

## Files

| File | Purpose |
|------|---------|
| `portfolio_decision_engine.py` | Core engine: decision rules, entry gates, capital competition, turnover cap |
| `valuation_policy.py` | V1 zone classification from valuation gap / base-case rerating |
| `portfolio_review_service.py` | Weekly review service: DB snapshot → engine → side effects → persistence |
| `scripts/run_portfolio_review.py` | CLI: `--as-of`, `--ticker`, `--json`, `--type`, `--no-persist` |
| `tests/test_portfolio_decision.py` | 42 tests covering all decision rules |
| `alembic/versions/b2c3d4e5f6a7_step7_...` | Migration: new fields + two new tables |

## Decision Rules

### Supported Actions

| Action | When |
|--------|------|
| `initiate` | All four entry gates pass + beats weakest holding |
| `add` | Existing holding in BUY zone with conviction ≥ 50 |
| `hold` | Default — no action needed |
| `trim` | Valuation stretched or conviction low with weakening thesis |
| `probation` | Conviction ≤ 35 — blocks adds, mandatory review |
| `exit` | Thesis broken, probation expired, or valuation in full-exit zone |
| `no_action` | Candidate that fails entry gates |

### A. Entry Gates (all must pass for initiation)

1. **Differentiated thesis exists** — active thesis, not broken, conviction ≥ 55
2. **Credible evidence** — at least one novel or confirming claim in last 7 days
3. **Valuation asymmetry** — zone must be BUY
4. **Checkpoint ahead** — visible upcoming checkpoint in DB

### B. Capital Competition

- Candidate must beat weakest current holding by conviction margin of 5 points
- If initiation needs capital beyond 100% allocation, engine suggests trimming weakest holding

### C. Add Rules

**Winners** (current_price ≥ avg_cost):
- Conviction ≥ 50 + BUY zone + thesis STRENGTHENING or STABLE → add allowed

**Losers** (current_price < avg_cost):
- All of: thesis intact, confirming evidence in last 7 days, BUY zone
- Lower price alone is never sufficient

### D. Trim / Exit

- **Trim:** TRIM zone or conviction < 40 with weakening thesis
- **Exit:** thesis BROKEN (forced), thesis ACHIEVED + not BUY zone, FULL_EXIT zone, probation expired, conviction ≤ 25

### E. Probation

- Entered when conviction ≤ 35
- No adds while on probation
- Mandatory next-week review
- Forced exit after 2 weekly reviews without improvement (improvement = conviction delta ≥ 3)

### F. Cooldown

- 21 days after exit before re-entry is allowed
- Tracked on both PortfolioPosition and Candidate records

### G. Turnover Cap

- 20% weekly cap at the recommendation layer
- Higher-urgency actions (exits) processed first
- Lower-priority actions blocked when cap exhausted

### H. Immediate Review Trigger

- 5-day price move ≥ ±8% flagged in `required_followup`
- No separate alerting layer yet — represented in engine output

## Conviction Thresholds

| Threshold | Value | Purpose |
|-----------|-------|---------|
| Initiation floor | 55 | Minimum for new position |
| Relative hurdle margin | 5 | Must beat weakest holding by |
| Add floor | 50 | Minimum for adding to position |
| Trim ceiling | 40 | Trim when below (+ weakening) |
| Probation ceiling | 35 | Enter probation when below |
| Exit ceiling | 25 | Force exit when below |

## Valuation Policy (V1 Placeholder)

Zone classification from `valuation_gap_pct`:
- **BUY:** gap ≥ 10%
- **HOLD:** gap ≥ -5%
- **TRIM:** gap ≥ -20%
- **FULL_EXIT:** gap < -20%

Priority: thesis.valuation_gap_pct → derived from base_case_rerating → default HOLD.

This is a placeholder until richer valuation modeling exists.

## Schema Changes (migration `b2c3d4e5f6a7`)

### New fields on `portfolio_positions`
- `probation_start_date` (Date, nullable)
- `probation_reviews_count` (Integer, default 0)
- `cooldown_until` (Date, nullable)
- `exit_date` (Date, nullable)
- `exit_reason` (String 100, nullable)

### New field on `candidates`
- `cooldown_until` (Date, nullable)

### New table: `portfolio_reviews`
- `id`, `review_date`, `review_type`, `holdings_reviewed`, `candidates_reviewed`, `turnover_pct`, `summary`, `created_at`

### New table: `portfolio_decisions`
- `id`, `review_id` (FK), `ticker` (FK), `action`, `action_score`, `target_weight_change`, `suggested_weight`, `reason_codes` (JSON), `rationale`, `blocking_conditions` (JSON), `required_followup` (JSON), `was_executed`, `generated_at`

### New enum: `ActionType`
- initiate, add, hold, trim, probation, exit, no_action

## How to Run

```bash
# Weekly review (default)
python scripts/run_portfolio_review.py

# Review as of specific date
python scripts/run_portfolio_review.py --as-of 2026-03-12

# Single ticker
python scripts/run_portfolio_review.py --ticker NVDA

# JSON output
python scripts/run_portfolio_review.py --json

# Immediate review type
python scripts/run_portfolio_review.py --type immediate

# Don't persist to DB
python scripts/run_portfolio_review.py --no-persist

# Verbose logging
python scripts/run_portfolio_review.py -v
```

## Assumptions / Placeholders

1. **Valuation is v1 placeholder.** Uses `valuation_gap_pct` from thesis or derives from `base_case_rerating`. No DCF or comparable-based modeling yet.
2. **Weight changes are recommendations only.** The engine suggests target_weight_change but does not execute trades. Execution is Step 8+.
3. **Evidence counting is simple.** Counts novel/confirming claims in 7 days. Does not weight by source tier or materiality. Sufficient for v1.
4. **Fair value is not stored as a separate field.** Derived from thesis.base_case_rerating * price when valuation_gap_pct is not set.
5. **Checkpoint detection relies on DB records.** If no checkpoints are ingested for a ticker, the checkpoint gate fails. The yfinance_calendar connector populates these.

## Known Limitations

- No execution layer — decisions are advisory only
- No portfolio-level risk constraints (sector concentration, correlation)
- No shadow/paper portfolio tracking
- No replay engine for backtesting decisions
- Turnover cap is per-review, not truly weekly (no memory of intra-week changes)
- Candidate pool must be manually maintained (Candidate table rows)
- No automatic promotion from "interesting thesis" to "candidate"

## What Remains for Step 8

- Shadow portfolio / paper execution
- Replay engine for decision audit
- Portfolio-level risk constraints (sector limits, correlation)
- Automated candidate pipeline (thesis quality → candidate promotion)
- Richer valuation modeling (DCF, comps, scenario analysis)
- Execution layer (simulated or real)
- Performance attribution
