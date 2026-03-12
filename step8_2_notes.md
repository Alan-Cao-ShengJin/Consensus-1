# Step 8.2: Historical Valuation-State Backfill & Provenance Hardening

## Purpose

Improve strict replay coverage by ensuring historically defensible valuation state exists for the replay engine to use, without weakening purity standards. Step 8.1 proved the plumbing works. Step 8.2 fills the data gaps that left strict replay under-informed.

## What Was Wrong (Before 8.2)

| Problem | Impact |
|---------|--------|
| `thesis_update_service` did not write `valuation_gap_pct` or `base_case_rerating` into `ThesisStateHistory` | Every historical valuation lookup returned `is_historical=False` |
| No provenance tracking on valuation data | Replay couldn't distinguish "truly recorded" from "backfilled" from "missing" |
| Existing ThesisStateHistory records had NULL valuation fields | Strict replay defaulted all zones to HOLD |
| No diagnostics explaining why strict stayed conservative | Users couldn't tell what was blocking coverage |

## What Was Fixed

### 1. Going-Forward Fix: Thesis Updates Now Persist Valuation

**File: `thesis_update_service.py`**

`update_thesis_from_claims()` now writes `valuation_gap_pct` and `base_case_rerating` from the current thesis into every new `ThesisStateHistory` record, with provenance:
- If `thesis.valuation_gap_pct` is not None: provenance = `historical_recorded`
- If `thesis.valuation_gap_pct` is None: provenance = `missing`

This means every future thesis update automatically captures a dated valuation snapshot.

### 2. Schema: ValuationProvenance Enum + Field

**File: `models.py`**

New enum `ValuationProvenance`:
- `historical_recorded` — captured at thesis update time
- `backfilled_from_thesis_snapshot` — conservatively backfilled from dated state
- `missing` — no defensible source

New field on `ThesisStateHistory`:
- `valuation_provenance: Optional[str]` (String(50), nullable)

### 3. Conservative Backfill

**File: `scripts/backfill_valuation_history.py`**

Strategy:
1. For each ThesisStateHistory record with `valuation_gap_pct=NULL`:
   - Look for the closest **earlier** history record on the same thesis that has `valuation_gap_pct` populated
   - If found within `max_gap_days` (default 30): copy values with provenance `backfilled_from_thesis_snapshot`
   - Otherwise: mark provenance as `missing`
2. For records that already have valuation but no provenance: tag as `historical_recorded`
3. **Never** uses the current mutable `Thesis.valuation_gap_pct` as a historical source

Features:
- `--dry-run` mode for inspection without changes
- `--max-gap-days` configurable threshold
- Coverage report before and after backfill
- Per-thesis breakdown

### 4. Enhanced Valuation Retrieval

**File: `portfolio_review_service.py`**

`_get_valuation_as_of()` now returns a 4-tuple:
```python
(valuation_gap_pct, base_case_rerating, is_historical, provenance)
```

- `provenance` is the `valuation_provenance` value from the history record
- For pre-8.2 records without provenance, defaults to `historical_recorded`
- For fallback to current thesis values: `current_fallback`

Strict replay accepts both `historical_recorded` and `backfilled_from_thesis_snapshot` as valid (both are `is_historical=True` from ThesisStateHistory).

### 5. Replay Diagnostics

**File: `replay_diagnostics.py`**

Two diagnostic tools:

**CandidateProvenanceReport**: For a replay period, shows:
- Which candidates were excluded in strict mode due to missing `created_at`
- First date they became eligible
- How many review dates they were skipped
- Whether they later entered the replay universe

**ReplayCoverageDiagnostics**: Explains "why strict stayed in cash":
- Candidate exclusions (no provenance / future created)
- Checkpoint exclusions (no provenance)
- Valuation fallback/missing counts
- Names downgraded to HOLD due to missing historical valuation
- Names skipped entirely due to strict purity

### 6. CLI Integration

**File: `scripts/run_replay.py`**

New `--diagnostics` flag appends coverage diagnostics to replay output:
```bash
python scripts/run_replay.py --start 2025-01-01 --end 2025-12-31 --strict --diagnostics
```

### 7. Warning Messages Include Provenance

Integrity warnings now include the provenance reason:
- `"Holding NVDA: no historical valuation (provenance=current_fallback), zone defaulted to HOLD"`
- `"Candidate NVDA: using current valuation (provenance=current_fallback)"`

## What Valuation History Is Now Captured Going Forward

Every call to `update_thesis_from_claims()` now writes:
- `ThesisStateHistory.valuation_gap_pct` = current `Thesis.valuation_gap_pct`
- `ThesisStateHistory.base_case_rerating` = current `Thesis.base_case_rerating`
- `ThesisStateHistory.valuation_provenance` = `historical_recorded` or `missing`

This is automatic. No additional code paths needed.

## What Was Conservatively Backfilled

The backfill script (`scripts/backfill_valuation_history.py`):
- Copies valuation from the nearest earlier history record on the same thesis
- Only if the gap is ≤30 days (configurable)
- Tags provenance as `backfilled_from_thesis_snapshot`
- Never fabricates values or uses current mutable thesis fields

## How Strict Replay Coverage Improves

Before 8.2: Strict replay saw zero historical valuation records → every zone defaulted to HOLD → no initiations triggered by valuation attractiveness.

After 8.2:
1. **Going forward**: Every thesis update creates a dated valuation snapshot → strict replay can use it
2. **Backfill**: Existing history gaps within 30 days of a valuation-bearing record are filled → strict replay has more data points
3. **Diagnostics**: Users can see exactly what is missing and why coverage is limited

## What Still Remains Missing

1. **Candidate mutable fields** (`conviction_score`, `zone_state`) still reflect current DB state — not versioned.
2. **Pre-existing records with no nearby valuation source** — cannot be backfilled without fabrication. These stay `missing`.
3. **Thesis records where valuation was never populated** — if `Thesis.valuation_gap_pct` has always been NULL, there is no dated source. The going-forward fix captures `missing` provenance for these.
4. **Checkpoint provenance** — Step 8.1's `created_at` filtering handles temporal provenance, but checkpoint content is not versioned.

## Is This Enough for Step 9?

Step 8.2 closes the main data gap that made strict replay empty. The system now:
- Records valuation state historically (going forward)
- Backfills defensibly where possible
- Explains its conservatism in structured diagnostics
- Accepts backfilled data with explicit provenance

Remaining purity gaps are addressable incrementally. The framework supports it. Step 9 can proceed knowing:
- Strict replay results are historically defensible
- Non-strict results have documented, measurable impurity
- The gap between the two is visible and shrinking

## Tests Added (Step 8.2)

| Test Class | Count | What It Proves |
|-----------|-------|---------------|
| `TestThesisUpdatePersistsValuation` | 2 | Valuation fields + provenance written on thesis update |
| `TestValuationProvenance` | 4 | _get_valuation_as_of returns correct provenance in all cases |
| `TestBackfillValuationHistory` | 6 | Backfill copies defensibly, respects gap limit, never fakes, tags provenance |
| `TestStrictReplayUsesBackfilled` | 3 | Strict accepts backfilled, still skips when missing, warnings include provenance |
| `TestCandidateProvenanceReport` | 3 | Report identifies missing provenance, tracks eligible dates |
| `TestReplayCoverageDiagnostics` | 4 | Diagnostics extract exclusions, downgrades, serialize correctly |
| `TestValuationProvenanceEnum` | 2 | Enum values correct, storable on model |
| **Total** | **24** | |

## Files Changed

| File | Change |
|------|--------|
| `models.py` | Added `ValuationProvenance` enum, `valuation_provenance` field on `ThesisStateHistory` |
| `thesis_update_service.py` | `update_thesis_from_claims` now writes valuation fields + provenance to history |
| `portfolio_review_service.py` | `_get_valuation_as_of` returns 4-tuple with provenance |
| `replay_engine.py` | Callers updated for 4-tuple, warnings include provenance |
| `replay_diagnostics.py` | **NEW** — candidate provenance report + coverage diagnostics |
| `scripts/backfill_valuation_history.py` | **NEW** — conservative backfill script |
| `scripts/run_replay.py` | Added `--diagnostics` flag |
| `tests/test_step8_2.py` | **NEW** — 24 tests for Step 8.2 |
