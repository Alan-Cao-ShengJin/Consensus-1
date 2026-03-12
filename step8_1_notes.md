# Step 8.1: Replay Purity Hardening

## Purpose

Narrow hardening pass to reduce replay impurity so backtest/shadow results are more historically defensible. Not Step 9. No execution, no broker APIs, no Graphiti.

## What Was Impure (Before 8.1)

| Source | Why It Leaked | Severity |
|--------|--------------|----------|
| **Candidate pool** | No `created_at` on Candidate — replay saw future candidates | HIGH |
| **Valuation inputs** | `valuation_gap_pct` / `base_case_rerating` from mutable Thesis, not versioned in history | HIGH |
| **Checkpoints** | No `created_at` on Checkpoint — replay saw future-ingested checkpoints | HIGH |
| **Candidate mutable fields** | `conviction_score`, `zone_state` reflect current state, not historical | MEDIUM |

## What Was Fixed

### 1. Schema Additions (Minimal)

| Table | Field Added | Purpose |
|-------|-----------|---------|
| `Candidate` | `created_at` (DateTime, nullable, default=utcnow) | Temporal provenance for candidate filtering |
| `Checkpoint` | `created_at` (DateTime, nullable, default=utcnow) | Temporal provenance for checkpoint filtering |
| `ThesisStateHistory` | `valuation_gap_pct` (Float, nullable) | Historical valuation gap tracking |
| `ThesisStateHistory` | `base_case_rerating` (Float, nullable) | Historical base case rerating tracking |

All fields are nullable to maintain backward compatibility with existing records.

### 2. Candidate Temporal Filtering

- **Strict mode:** Only candidates with `created_at <= as_of` are included. Candidates without `created_at` or created after the replay date are excluded.
- **Non-strict mode:** Candidates without `created_at` are included but flagged with an integrity warning. Candidates created after the replay date are always excluded.

### 3. Historical Valuation Lookup

New function `_get_valuation_as_of()` in `portfolio_review_service.py`:
- Queries `ThesisStateHistory` for the most recent record on or before `as_of` that has `valuation_gap_pct` populated
- Returns `(valuation_gap_pct, base_case_rerating, is_historical)`
- `is_historical=True` if values came from history, `False` if fallback

Replay engine uses this for both holdings and candidates:
- **Strict mode:** When no historical valuation exists, `None` is used → zone defaults to HOLD (safe default, no zone-dependent actions triggered by impure data)
- **Non-strict mode:** Falls back to current thesis values with an integrity warning

### 4. Checkpoint Temporal Filtering

`_has_checkpoint_ahead()` now accepts `filter_created_at=True`:
- When enabled, only checkpoints with `created_at IS NOT NULL AND created_at <= as_of` are visible
- Checkpoints without `created_at` are excluded (cannot prove temporal provenance)
- **Strict mode:** `filter_created_at=True`
- **Non-strict mode:** `filter_created_at=False` (legacy behavior)

### 5. Purity Reporting

New `ReplayPurityFlags` dataclass tracks per-review-date:
- `impure_candidate_count` — candidates used without temporal provenance
- `impure_valuation_count` — holdings/candidates using current valuation
- `impure_checkpoint_count` — checkpoints without temporal provenance
- `skipped_impure_candidates` — candidates excluded in strict mode
- `skipped_impure_valuation` — valuation paths skipped in strict mode
- `skipped_impure_checkpoints` — checkpoints excluded in strict mode
- `integrity_warnings` — human-readable list of warnings
- `is_pure` — True if all counts are zero

Run-level purity in `ReplayRunResult`:
- `purity_level`: `"strict"` | `"degraded"` | `"mixed"`
- `total_impure_candidates`, `total_impure_valuations`, `total_impure_checkpoints`
- `total_skipped_impure`
- `integrity_warnings`

### 6. Strict Replay Mode

Flag: `strict_replay=True/False` on `run_replay()` and CLI `--strict`

| Behavior | Strict (`True`) | Non-Strict (`False`) |
|----------|----------------|---------------------|
| Candidate without `created_at` | Excluded | Included + warning |
| Candidate created after `as_of` | Excluded | Excluded |
| No historical valuation | Zone defaults to HOLD | Uses current thesis values + warning |
| Checkpoint without `created_at` | Excluded | Included (legacy) |
| Checkpoint created after `as_of` | Excluded | Excluded (in strict filter path) |

Purity level:
- **strict**: zero impure fallbacks used (may have skips)
- **degraded**: some impure fallbacks used, no skips
- **mixed**: both impure fallbacks and skips

## What Remains Imperfect

1. **Candidate mutable fields** (`conviction_score`, `zone_state`, `cooldown_flag`) still reflect current DB state. These are partially mitigated because the replay uses thesis-derived conviction from `_get_thesis_state_as_of()`, but the Candidate record's own fields are not versioned.

2. **Existing records without `created_at`** — All Candidate and Checkpoint records created before this change have `created_at=NULL`. In strict mode, they are excluded. In non-strict mode, they are included with warnings.

3. **ThesisStateHistory valuation gap backfill** — Existing ThesisStateHistory records do not have `valuation_gap_pct` or `base_case_rerating` populated. Historical replay of periods before this change will fall back to current thesis values (non-strict) or HOLD zone (strict).

4. **Candidate `conviction_score` and `zone_state`** — These are mutable fields on the Candidate table, not versioned. The replay already uses thesis-derived conviction where possible, but candidates without a thesis use their current record values.

## How to Run

```bash
# Non-strict replay (default — documented fallbacks)
python scripts/run_replay.py --start 2025-01-01 --end 2025-12-31

# Strict replay (skip impure inputs)
python scripts/run_replay.py --start 2025-01-01 --end 2025-12-31 --strict

# Strict + verbose to see warnings
python scripts/run_replay.py --start 2025-01-01 --end 2025-12-31 --strict -v
```

## Tests Added (Step 8.1)

| Test Class | Count | What It Proves |
|-----------|-------|---------------|
| `TestCandidateTemporalFiltering` | 5 | Candidate created_at filtering works in strict/non-strict, decisions differ before/after creation |
| `TestCheckpointTemporalFiltering` | 5 | Checkpoint created_at filtering in strict/non-strict, visibility changes across creation date |
| `TestHistoricalValuation` | 7 | ThesisStateHistory valuation used when available, fallback with warnings, strict skips |
| `TestPurityLevel` | 4 | strict/degraded/mixed computation logic |
| `TestPurityFlagsInOutput` | 3 | Purity fields present in run result, per-review, and to_dict |
| `TestMetricsPurity` | 1 | Metrics to_dict includes purity section |
| `TestReplayPurityFlags` | 5 | Dataclass is_pure logic, to_dict |
| `TestStrictVsNonStrictReplay` | 2 | Same data yields different behavior under strict vs non-strict |
| **Total** | **32** | |

## Interpreting Replay Results

When reviewing replay output:

1. Check `purity_level` first:
   - `strict` = historically defensible (impure inputs were excluded)
   - `degraded` = some current-state fallbacks were used (results may be optimistic)
   - `mixed` = combination of both

2. Check `integrity_warnings` for specifics on what was impure

3. Compare strict vs non-strict runs to assess how much impurity affects results

4. The PURITY section in text output summarizes all fallback counts

## What This Means for Step 9

- Schema now supports temporal tracking of valuation changes
- Future thesis updates should populate `valuation_gap_pct` and `base_case_rerating` in ThesisStateHistory
- Future candidate creation should set `created_at`
- Future checkpoint creation should set `created_at`
- Backfill scripts may be needed for existing records
