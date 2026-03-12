"""Multi-cycle operating validator for repeated paper-mode cycles.

Orchestrates existing modules (RunManager, paper execution, guardrails, etc.)
over repeated cycles and validates operational coherence across time.

Does not reimplement business logic. Wraps RunManager with:
  - Configurable scenarios
  - Fault injection for controlled stage failures
  - Cross-cycle invariant checks
  - Validation reporting
"""
from __future__ import annotations

import json
import logging
import os
import traceback
from dataclasses import dataclass, field, asdict
from datetime import date, timedelta
from typing import Optional

from config import SystemConfig, Environment
from run_manager import (
    RunManager, RunManifest, RunStatus, StageStatus, ApprovalStatus,
    check_duplicate_run, check_batch_already_executed,
    save_approval_state, load_approval_state, approve_batch,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Fault injection
# ---------------------------------------------------------------------------

class FaultInjectedError(Exception):
    """Raised when a fault is deliberately injected during validation."""
    pass


class FaultInjector:
    """Small validation-only hook that forces failures in controlled stages."""

    def __init__(
        self,
        fail_stages: Optional[list[str]] = None,
        fail_on_cycle: int = 1,
    ):
        self.fail_stages = set(fail_stages or [])
        self.fail_on_cycle = fail_on_cycle
        self.injections: list[dict] = []

    def check(self, stage: str, cycle: int):
        """Raise FaultInjectedError if this stage/cycle should fail."""
        if stage in self.fail_stages and cycle == self.fail_on_cycle:
            record = {"stage": stage, "cycle": cycle}
            self.injections.append(record)
            raise FaultInjectedError(
                f"Fault injected: stage={stage}, cycle={cycle}"
            )


# ---------------------------------------------------------------------------
# Instrumented RunManager
# ---------------------------------------------------------------------------

class InstrumentedRunManager(RunManager):
    """RunManager with fault injection and scenario hooks."""

    def __init__(
        self,
        config: SystemConfig,
        run_date: Optional[date] = None,
        force: bool = False,
        fault_injector: Optional[FaultInjector] = None,
        cycle_num: int = 1,
        no_actionable: bool = False,
    ):
        super().__init__(config, run_date=run_date, force=force)
        self._fault_injector = fault_injector
        self._cycle_num = cycle_num
        self._no_actionable = no_actionable

    def _run_stage(self, stage_name: str):
        if self._fault_injector:
            self._fault_injector.check(stage_name, self._cycle_num)
        super()._run_stage(stage_name)

    def _build_demo_review(self):
        """Override to support no-actionable scenarios."""
        if self._no_actionable:
            self._build_no_actionable_review()
        else:
            super()._build_demo_review()

    def _build_no_actionable_review(self):
        """Build a review where all decisions are HOLD — no order intents."""
        from models import ActionType
        from portfolio_decision_engine import (
            TickerDecision, PortfolioReviewResult, ReasonCode,
            PRIORITY_NEUTRAL,
        )

        decisions = [
            TickerDecision(
                ticker="STDY", action=ActionType.HOLD, action_score=0.0,
                recommendation_priority=PRIORITY_NEUTRAL,
                reason_codes=[ReasonCode.VALUATION_NEUTRAL],
                rationale="Hold — thesis stable, no action required",
            ),
            TickerDecision(
                ticker="SAFE", action=ActionType.HOLD, action_score=0.0,
                recommendation_priority=PRIORITY_NEUTRAL,
                reason_codes=[ReasonCode.VALUATION_NEUTRAL],
                rationale="Hold — no change",
            ),
        ]

        self._review_result = PortfolioReviewResult(
            review_date=self.run_date,
            decisions=decisions,
            turnover_pct_planned=0.0,
            turnover_pct_cap=20.0,
        )
        self._demo_weights = {"STDY": 4.0, "SAFE": 3.0}
        self._demo_prices = {"STDY": 150.0, "SAFE": 80.0}


# ---------------------------------------------------------------------------
# Scenario configuration
# ---------------------------------------------------------------------------

@dataclass
class ScenarioConfig:
    """Defines a validation scenario."""
    name: str
    description: str
    num_cycles: int = 1
    environment: str = Environment.DEMO
    paper_execute: bool = True
    require_approval: bool = False
    dry_run: bool = False
    force_per_cycle: Optional[list[bool]] = None
    fault_stages: Optional[list[str]] = None
    fault_on_cycle: int = 1
    resume_on_cycle: Optional[dict[int, str]] = None
    approve_before_cycle: Optional[list[int]] = None
    config_overrides_per_cycle: Optional[dict[int, dict]] = None
    no_actionable: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Predefined scenarios
# ---------------------------------------------------------------------------

SCENARIOS: dict[str, ScenarioConfig] = {
    "happy_path": ScenarioConfig(
        name="happy_path",
        description="Repeated happy-path paper cycles",
        num_cycles=3,
        paper_execute=True,
    ),
    "duplicate_run": ScenarioConfig(
        name="duplicate_run",
        description="Second run on same date is blocked as duplicate",
        num_cycles=2,
        paper_execute=True,
        # cycle 2 should be SKIPPED because cycle 1 completed
    ),
    "duplicate_batch": ScenarioConfig(
        name="duplicate_batch",
        description="Second batch execution on same date is blocked",
        num_cycles=2,
        paper_execute=True,
        force_per_cycle=[False, True],  # force cycle 2 past duplicate-run check
    ),
    "failure_resume": ScenarioConfig(
        name="failure_resume",
        description="Fault in review, then resume from review",
        num_cycles=2,
        paper_execute=True,
        fault_stages=["review"],
        fault_on_cycle=1,
        resume_on_cycle={2: "review"},
        force_per_cycle=[False, True],
    ),
    "failure_paper_execution": ScenarioConfig(
        name="failure_paper_execution",
        description="Fault in paper execution, then resume",
        num_cycles=2,
        paper_execute=True,
        fault_stages=["paper_execution"],
        fault_on_cycle=1,
        resume_on_cycle={2: "paper_execution"},
        force_per_cycle=[False, True],
    ),
    "approval_required": ScenarioConfig(
        name="approval_required",
        description="Approval gate blocks execution until approved",
        num_cycles=2,
        paper_execute=True,
        require_approval=True,
        approve_before_cycle=[2],
        force_per_cycle=[False, True],
        resume_on_cycle={2: "paper_execution"},
    ),
    "config_change": ScenarioConfig(
        name="config_change",
        description="Config change between cycles",
        num_cycles=2,
        paper_execute=True,
        config_overrides_per_cycle={
            2: {"portfolio_value": 2_000_000.0},
        },
        force_per_cycle=[False, True],
    ),
    "dry_run": ScenarioConfig(
        name="dry_run",
        description="Dry-run cycle does not mutate paper portfolio",
        num_cycles=1,
        dry_run=True,
        paper_execute=True,
    ),
    "no_actionable": ScenarioConfig(
        name="no_actionable",
        description="Paper cycle with no actionable recommendations",
        num_cycles=1,
        paper_execute=True,
        no_actionable=True,
    ),
    "failure_ingestion": ScenarioConfig(
        name="failure_ingestion",
        description="Fault during ingestion, verify remaining stages skipped",
        num_cycles=1,
        paper_execute=True,
        fault_stages=["ingestion"],
        fault_on_cycle=1,
    ),
}


# ---------------------------------------------------------------------------
# Cycle and scenario outcomes
# ---------------------------------------------------------------------------

@dataclass
class CycleOutcome:
    """Result of one cycle within a validation scenario."""
    cycle_num: int
    manifest: RunManifest
    fills_count: int = 0
    approval_blocked: bool = False
    duplicate_run_blocked: bool = False
    duplicate_batch_blocked: bool = False
    fault_injected: bool = False
    resumed: bool = False
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "cycle_num": self.cycle_num,
            "run_id": self.manifest.run_id,
            "status": self.manifest.status,
            "fills_count": self.fills_count,
            "approval_blocked": self.approval_blocked,
            "duplicate_run_blocked": self.duplicate_run_blocked,
            "duplicate_batch_blocked": self.duplicate_batch_blocked,
            "fault_injected": self.fault_injected,
            "resumed": self.resumed,
            "error": self.error,
            "stages": {
                name: sr.status
                for name, sr in self.manifest.stages.items()
            },
        }


@dataclass
class InvariantViolation:
    """A detected invariant violation."""
    check_name: str
    message: str
    cycle: Optional[int] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ScenarioResult:
    """Result of running a complete validation scenario."""
    scenario_name: str
    scenario_description: str
    passed: bool
    cycles: list[CycleOutcome] = field(default_factory=list)
    invariant_violations: list[InvariantViolation] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "scenario_name": self.scenario_name,
            "scenario_description": self.scenario_description,
            "passed": self.passed,
            "cycles": [c.to_dict() for c in self.cycles],
            "invariant_violations": [v.to_dict() for v in self.invariant_violations],
            "notes": self.notes,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Invariant checks
# ---------------------------------------------------------------------------

def check_no_duplicate_fills(outcomes: list[CycleOutcome]) -> list[InvariantViolation]:
    """Verify no duplicate paper fills from reruns."""
    violations = []
    executed_dates = []
    for oc in outcomes:
        pe = oc.manifest.stages.get("paper_execution")
        if pe and pe.status == StageStatus.COMPLETED and oc.fills_count > 0:
            review_date = oc.manifest.run_date
            if review_date in executed_dates:
                violations.append(InvariantViolation(
                    check_name="no_duplicate_fills",
                    message=f"Duplicate paper fills for date {review_date}",
                    cycle=oc.cycle_num,
                ))
            executed_dates.append(review_date)
    return violations


def check_manifest_coherence(outcomes: list[CycleOutcome]) -> list[InvariantViolation]:
    """Verify run statuses reflect actual stage outcomes."""
    violations = []
    for oc in outcomes:
        m = oc.manifest
        stages = m.stages
        any_failed = any(sr.status == StageStatus.FAILED for sr in stages.values())
        any_completed = any(sr.status == StageStatus.COMPLETED for sr in stages.values())

        if m.status == RunStatus.COMPLETED and any_failed:
            violations.append(InvariantViolation(
                check_name="manifest_coherence",
                message=f"Cycle {oc.cycle_num}: status=COMPLETED but has FAILED stages",
                cycle=oc.cycle_num,
            ))
        if m.status == RunStatus.FAILED and not any_failed:
            violations.append(InvariantViolation(
                check_name="manifest_coherence",
                message=f"Cycle {oc.cycle_num}: status=FAILED but no FAILED stages",
                cycle=oc.cycle_num,
            ))
    return violations


def check_environment_labels(
    outcomes: list[CycleOutcome], expected_env: str,
) -> list[InvariantViolation]:
    """Verify all manifests have correct environment label."""
    violations = []
    for oc in outcomes:
        if oc.manifest.environment != expected_env:
            violations.append(InvariantViolation(
                check_name="environment_labels",
                message=(
                    f"Cycle {oc.cycle_num}: expected env={expected_env}, "
                    f"got {oc.manifest.environment}"
                ),
                cycle=oc.cycle_num,
            ))
    return violations


def check_duplicate_run_blocked(outcomes: list[CycleOutcome]) -> list[InvariantViolation]:
    """For duplicate_run scenario: verify second run is SKIPPED."""
    violations = []
    if len(outcomes) >= 2:
        oc1 = outcomes[0]
        oc2 = outcomes[1]
        if oc1.manifest.status == RunStatus.COMPLETED and not oc2.duplicate_run_blocked:
            # Only flag if cycle 2 was NOT forced
            if oc2.manifest.status != RunStatus.SKIPPED:
                violations.append(InvariantViolation(
                    check_name="duplicate_run_blocked",
                    message="Second run was not blocked as duplicate",
                    cycle=2,
                ))
    return violations


def check_duplicate_batch_blocked(outcomes: list[CycleOutcome]) -> list[InvariantViolation]:
    """For duplicate_batch scenario: verify second batch execution is blocked."""
    violations = []
    if len(outcomes) >= 2:
        oc2 = outcomes[1]
        pe = oc2.manifest.stages.get("paper_execution")
        if pe and pe.status == StageStatus.COMPLETED:
            # Second batch was NOT blocked — violation
            violations.append(InvariantViolation(
                check_name="duplicate_batch_blocked",
                message="Second batch execution was not blocked",
                cycle=2,
            ))
    return violations


def check_approval_gate(outcomes: list[CycleOutcome]) -> list[InvariantViolation]:
    """Verify approval gate blocks execution when required."""
    violations = []
    for oc in outcomes:
        if oc.approval_blocked:
            pe = oc.manifest.stages.get("paper_execution")
            if pe and pe.status == StageStatus.COMPLETED:
                violations.append(InvariantViolation(
                    check_name="approval_gate",
                    message=f"Cycle {oc.cycle_num}: paper execution ran despite pending approval",
                    cycle=oc.cycle_num,
                ))
    return violations


def check_dry_run_no_mutation(outcomes: list[CycleOutcome]) -> list[InvariantViolation]:
    """Verify dry-run cycles produce no paper fills and no artifacts."""
    violations = []
    for oc in outcomes:
        if oc.fills_count > 0:
            violations.append(InvariantViolation(
                check_name="dry_run_no_mutation",
                message=f"Cycle {oc.cycle_num}: dry-run produced {oc.fills_count} fills",
                cycle=oc.cycle_num,
            ))
        pe = oc.manifest.stages.get("paper_execution")
        if pe and pe.status == StageStatus.COMPLETED:
            violations.append(InvariantViolation(
                check_name="dry_run_no_mutation",
                message=f"Cycle {oc.cycle_num}: dry-run completed paper execution",
                cycle=oc.cycle_num,
            ))
    return violations


def check_artifact_existence(outcomes: list[CycleOutcome]) -> list[InvariantViolation]:
    """Verify exported artifacts exist on disk."""
    violations = []
    for oc in outcomes:
        ae = oc.manifest.stages.get("artifact_export")
        if ae and ae.status == StageStatus.COMPLETED:
            for artifact_path in ae.artifacts:
                if not os.path.exists(artifact_path):
                    violations.append(InvariantViolation(
                        check_name="artifact_existence",
                        message=f"Cycle {oc.cycle_num}: artifact missing: {artifact_path}",
                        cycle=oc.cycle_num,
                    ))
    return violations


def check_fills_within_intents(outcomes: list[CycleOutcome]) -> list[InvariantViolation]:
    """Verify fills count does not exceed approved intents."""
    violations = []
    for oc in outcomes:
        gv = oc.manifest.stages.get("guardrail_validation")
        pe = oc.manifest.stages.get("paper_execution")
        if gv and pe and pe.status == StageStatus.COMPLETED:
            approved = gv.counts.get("approved", 0)
            if oc.fills_count > approved:
                violations.append(InvariantViolation(
                    check_name="fills_within_intents",
                    message=(
                        f"Cycle {oc.cycle_num}: {oc.fills_count} fills > "
                        f"{approved} approved intents"
                    ),
                    cycle=oc.cycle_num,
                ))
    return violations


# ---------------------------------------------------------------------------
# Operating validator
# ---------------------------------------------------------------------------

class OperatingValidator:
    """Run the system over repeated paper cycles and validate coherence."""

    def __init__(
        self,
        artifact_base_dir: str,
        scenarios: Optional[dict[str, ScenarioConfig]] = None,
    ):
        self.artifact_base_dir = artifact_base_dir
        self.scenarios = scenarios or SCENARIOS

    def run_scenario(
        self,
        scenario: str | ScenarioConfig,
    ) -> ScenarioResult:
        """Run a single validation scenario."""
        if isinstance(scenario, str):
            if scenario not in self.scenarios:
                return ScenarioResult(
                    scenario_name=scenario,
                    scenario_description="unknown",
                    passed=False,
                    error=f"Unknown scenario: {scenario}",
                )
            sc = self.scenarios[scenario]
        else:
            sc = scenario

        logger.info("=== Scenario: %s ===", sc.name)
        logger.info("  %s", sc.description)

        outcomes: list[CycleOutcome] = []
        fault_injector = None
        if sc.fault_stages:
            fault_injector = FaultInjector(
                fail_stages=sc.fault_stages,
                fail_on_cycle=sc.fault_on_cycle,
            )

        # Track first cycle's artifact_dir for approval flow
        first_artifact_dir = None
        first_batch_id = None

        try:
            for cycle in range(1, sc.num_cycles + 1):
                logger.info("--- Cycle %d/%d ---", cycle, sc.num_cycles)

                # Build config for this cycle
                config = SystemConfig(
                    environment=sc.environment,
                    paper_execute=sc.paper_execute,
                    dry_run=sc.dry_run,
                    require_approval=sc.require_approval,
                    artifact_base_dir=self.artifact_base_dir,
                )

                # Apply per-cycle config overrides
                if sc.config_overrides_per_cycle and cycle in sc.config_overrides_per_cycle:
                    overrides = sc.config_overrides_per_cycle[cycle]
                    config = config.merge(overrides)

                # Per-cycle force flag
                force = False
                if sc.force_per_cycle and cycle <= len(sc.force_per_cycle):
                    force = sc.force_per_cycle[cycle - 1]

                # Resume?
                resume_from = None
                resumed = False
                if sc.resume_on_cycle and cycle in sc.resume_on_cycle:
                    resume_from = sc.resume_on_cycle[cycle]
                    resumed = True

                # Auto-approve before this cycle?
                if sc.approve_before_cycle and cycle in sc.approve_before_cycle:
                    if first_artifact_dir and first_batch_id:
                        approve_batch(first_artifact_dir, first_batch_id)
                        logger.info("Auto-approved batch %s", first_batch_id)

                # Use same date for all cycles (to test duplicate detection)
                run_date = date(2025, 6, 1)

                manager = InstrumentedRunManager(
                    config=config,
                    run_date=run_date,
                    force=force,
                    fault_injector=fault_injector,
                    cycle_num=cycle,
                    no_actionable=sc.no_actionable,
                )

                manifest = manager.run(resume_from=resume_from)

                # Track fills
                fills_count = 0
                pe = manifest.stages.get("paper_execution")
                if pe and pe.status == StageStatus.COMPLETED:
                    fills_count = pe.counts.get("fills_executed", 0)

                # Track blocking reasons
                duplicate_run_blocked = manifest.status == RunStatus.SKIPPED and (
                    manifest.error_summary or ""
                ).startswith("Duplicate of completed run")

                duplicate_batch_blocked = False
                if pe and pe.status == StageStatus.SKIPPED:
                    duplicate_batch_blocked = any(
                        "Duplicate batch" in w or "batch already executed" in w.lower()
                        for w in pe.warnings
                    )

                approval_blocked = False
                if pe and pe.status == StageStatus.SKIPPED:
                    approval_blocked = any(
                        "requires approval" in w.lower() or "awaiting" in w.lower()
                        for w in pe.warnings
                    )

                fault_injected = False
                if fault_injector and fault_injector.injections:
                    fault_injected = any(
                        inj["cycle"] == cycle for inj in fault_injector.injections
                    )

                outcome = CycleOutcome(
                    cycle_num=cycle,
                    manifest=manifest,
                    fills_count=fills_count,
                    approval_blocked=approval_blocked,
                    duplicate_run_blocked=duplicate_run_blocked,
                    duplicate_batch_blocked=duplicate_batch_blocked,
                    fault_injected=fault_injected,
                    resumed=resumed,
                )
                outcomes.append(outcome)

                # Track first successful run for approval flow
                if cycle == 1 and manifest.artifact_dir:
                    first_artifact_dir = manifest.artifact_dir
                    first_batch_id = manifest.batch_id

                logger.info(
                    "Cycle %d: status=%s fills=%d",
                    cycle, manifest.status, fills_count,
                )

        except Exception as e:
            logger.error("Scenario %s failed: %s", sc.name, e)
            return ScenarioResult(
                scenario_name=sc.name,
                scenario_description=sc.description,
                passed=False,
                cycles=outcomes,
                error=f"Unexpected error: {e}",
            )

        # Run invariant checks
        violations = self._check_invariants(sc, outcomes)

        passed = len(violations) == 0
        notes = self._build_notes(sc, outcomes)

        result = ScenarioResult(
            scenario_name=sc.name,
            scenario_description=sc.description,
            passed=passed,
            cycles=outcomes,
            invariant_violations=violations,
            notes=notes,
        )

        logger.info(
            "Scenario %s: %s (%d violations)",
            sc.name, "PASSED" if passed else "FAILED", len(violations),
        )
        return result

    def run_all(self) -> list[ScenarioResult]:
        """Run all configured scenarios."""
        results = []
        for name in sorted(self.scenarios.keys()):
            results.append(self.run_scenario(name))
        return results

    def _check_invariants(
        self,
        sc: ScenarioConfig,
        outcomes: list[CycleOutcome],
    ) -> list[InvariantViolation]:
        """Run all applicable invariant checks for a scenario."""
        violations: list[InvariantViolation] = []

        # Always check
        violations.extend(check_manifest_coherence(outcomes))
        violations.extend(check_environment_labels(outcomes, sc.environment))
        violations.extend(check_fills_within_intents(outcomes))

        # Non-dry-run checks
        if not sc.dry_run:
            violations.extend(check_no_duplicate_fills(outcomes))
            violations.extend(check_artifact_existence(outcomes))

        # Scenario-specific checks
        if sc.name == "duplicate_run":
            violations.extend(check_duplicate_run_blocked(outcomes))

        if sc.name == "duplicate_batch":
            violations.extend(check_duplicate_batch_blocked(outcomes))

        if sc.name == "approval_required":
            violations.extend(check_approval_gate(outcomes))

        if sc.dry_run:
            violations.extend(check_dry_run_no_mutation(outcomes))

        return violations

    def _build_notes(
        self,
        sc: ScenarioConfig,
        outcomes: list[CycleOutcome],
    ) -> list[str]:
        """Build human-readable notes about the scenario run."""
        notes = []
        for oc in outcomes:
            status = oc.manifest.status
            note = f"Cycle {oc.cycle_num}: {status}"
            if oc.duplicate_run_blocked:
                note += " (duplicate run blocked)"
            if oc.duplicate_batch_blocked:
                note += " (duplicate batch blocked)"
            if oc.approval_blocked:
                note += " (approval blocked)"
            if oc.fault_injected:
                note += " (fault injected)"
            if oc.resumed:
                note += " (resumed)"
            if oc.fills_count > 0:
                note += f" ({oc.fills_count} fills)"
            notes.append(note)
        return notes
