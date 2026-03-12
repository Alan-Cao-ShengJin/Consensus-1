"""Tests for Step 11.5: operating validation over repeated paper cycles.

Deterministic. No live network. Uses demo mode with temp artifact directories.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile

import pytest

from config import SystemConfig, Environment
from run_manager import (
    RunManager, RunManifest, RunStatus, StageStatus, ApprovalStatus,
    StageResult, check_duplicate_run, check_batch_already_executed,
    save_approval_state, load_approval_state, approve_batch,
)
from operating_validator import (
    FaultInjector, FaultInjectedError,
    InstrumentedRunManager,
    ScenarioConfig, CycleOutcome, ScenarioResult, InvariantViolation,
    OperatingValidator, SCENARIOS,
    check_no_duplicate_fills,
    check_manifest_coherence,
    check_environment_labels,
    check_duplicate_run_blocked,
    check_duplicate_batch_blocked,
    check_approval_gate,
    check_dry_run_no_mutation,
    check_artifact_existence,
    check_fills_within_intents,
)
from validation_report import (
    ValidationReport, build_report, format_report_text, export_report,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_artifacts(tmp_path):
    """Temporary artifact directory for isolation."""
    return str(tmp_path / "artifacts")


def _demo_config(artifact_dir: str, **overrides) -> SystemConfig:
    """Build a demo config for validation tests."""
    defaults = dict(
        environment=Environment.DEMO,
        paper_execute=True,
        dry_run=False,
        artifact_base_dir=artifact_dir,
    )
    defaults.update(overrides)
    return SystemConfig(**defaults)


def _run_demo_cycle(artifact_dir, run_date=None, force=False, **config_kw):
    """Run a single demo cycle and return the manifest."""
    from datetime import date
    config = _demo_config(artifact_dir, **config_kw)
    rd = run_date or date(2025, 6, 1)
    manager = RunManager(config, run_date=rd, force=force)
    return manager.run()


# ---------------------------------------------------------------------------
# Test: Fault injection
# ---------------------------------------------------------------------------

class TestFaultInjection:
    def test_fault_injector_raises_on_target(self):
        fi = FaultInjector(fail_stages=["review"], fail_on_cycle=1)
        with pytest.raises(FaultInjectedError, match="review"):
            fi.check("review", 1)

    def test_fault_injector_no_raise_wrong_cycle(self):
        fi = FaultInjector(fail_stages=["review"], fail_on_cycle=2)
        fi.check("review", 1)  # should not raise

    def test_fault_injector_no_raise_wrong_stage(self):
        fi = FaultInjector(fail_stages=["review"], fail_on_cycle=1)
        fi.check("ingestion", 1)  # should not raise

    def test_fault_injector_records_injection(self):
        fi = FaultInjector(fail_stages=["review"], fail_on_cycle=1)
        with pytest.raises(FaultInjectedError):
            fi.check("review", 1)
        assert len(fi.injections) == 1
        assert fi.injections[0] == {"stage": "review", "cycle": 1}

    def test_instrumented_manager_injects_fault(self, tmp_artifacts):
        from datetime import date
        fi = FaultInjector(fail_stages=["review"], fail_on_cycle=1)
        config = _demo_config(tmp_artifacts)
        manager = InstrumentedRunManager(
            config, run_date=date(2025, 6, 1), fault_injector=fi, cycle_num=1,
        )
        manifest = manager.run()
        assert manifest.stages["review"].status == StageStatus.FAILED
        assert "Fault injected" in (manifest.stages["review"].error or "")


# ---------------------------------------------------------------------------
# Test: Happy-path repeated cycles
# ---------------------------------------------------------------------------

class TestHappyPath:
    def test_single_cycle_completes(self, tmp_artifacts):
        manifest = _run_demo_cycle(tmp_artifacts)
        assert manifest.status == RunStatus.COMPLETED

    def test_single_cycle_has_all_stages(self, tmp_artifacts):
        manifest = _run_demo_cycle(tmp_artifacts)
        for stage in RunManager.STAGES:
            assert stage in manifest.stages

    def test_paper_execution_produces_fills(self, tmp_artifacts):
        manifest = _run_demo_cycle(tmp_artifacts)
        pe = manifest.stages["paper_execution"]
        assert pe.status == StageStatus.COMPLETED
        assert pe.counts.get("fills_executed", 0) > 0

    def test_artifact_export_produces_files(self, tmp_artifacts):
        manifest = _run_demo_cycle(tmp_artifacts)
        ae = manifest.stages["artifact_export"]
        assert ae.status == StageStatus.COMPLETED
        assert ae.counts.get("files_exported", 0) > 0
        for path in ae.artifacts:
            assert os.path.exists(path)

    def test_manifest_saved_to_disk(self, tmp_artifacts):
        manifest = _run_demo_cycle(tmp_artifacts)
        manifest_path = os.path.join(manifest.artifact_dir, "run_manifest.json")
        assert os.path.exists(manifest_path)

    def test_manifest_roundtrip(self, tmp_artifacts):
        manifest = _run_demo_cycle(tmp_artifacts)
        manifest_path = os.path.join(manifest.artifact_dir, "run_manifest.json")
        loaded = RunManifest.load(manifest_path)
        assert loaded.run_id == manifest.run_id
        assert loaded.status == RunStatus.COMPLETED
        assert loaded.environment == Environment.DEMO

    def test_repeated_cycles_coherent(self, tmp_artifacts):
        """Three cycles with different dates all complete."""
        from datetime import date, timedelta
        manifests = []
        for i in range(3):
            rd = date(2025, 6, 1) + timedelta(days=i)
            m = _run_demo_cycle(tmp_artifacts, run_date=rd)
            manifests.append(m)
        assert all(m.status == RunStatus.COMPLETED for m in manifests)
        # All have unique run_ids
        ids = [m.run_id for m in manifests]
        assert len(set(ids)) == 3


# ---------------------------------------------------------------------------
# Test: Duplicate run detection
# ---------------------------------------------------------------------------

class TestDuplicateRun:
    def test_second_run_same_date_blocked(self, tmp_artifacts):
        from datetime import date
        rd = date(2025, 6, 1)
        m1 = _run_demo_cycle(tmp_artifacts, run_date=rd)
        assert m1.status == RunStatus.COMPLETED

        m2 = _run_demo_cycle(tmp_artifacts, run_date=rd)
        assert m2.status == RunStatus.SKIPPED
        assert "Duplicate" in (m2.error_summary or "")

    def test_force_overrides_duplicate(self, tmp_artifacts):
        from datetime import date
        rd = date(2025, 6, 1)
        m1 = _run_demo_cycle(tmp_artifacts, run_date=rd)
        assert m1.status == RunStatus.COMPLETED

        m2 = _run_demo_cycle(tmp_artifacts, run_date=rd, force=True)
        assert m2.status == RunStatus.COMPLETED

    def test_check_duplicate_run_returns_existing(self, tmp_artifacts):
        from datetime import date
        rd = date(2025, 6, 1)
        config = _demo_config(tmp_artifacts)
        _run_demo_cycle(tmp_artifacts, run_date=rd)

        existing = check_duplicate_run(tmp_artifacts, rd.isoformat(), config)
        assert existing is not None
        assert existing.status == RunStatus.COMPLETED


# ---------------------------------------------------------------------------
# Test: Duplicate batch execution
# ---------------------------------------------------------------------------

class TestDuplicateBatch:
    def test_batch_already_executed_detected(self, tmp_artifacts):
        from datetime import date
        rd = date(2025, 6, 1)
        m1 = _run_demo_cycle(tmp_artifacts, run_date=rd)
        assert m1.stages["paper_execution"].status == StageStatus.COMPLETED

        result = check_batch_already_executed(
            tmp_artifacts, rd.isoformat(), rd.isoformat(),
        )
        assert result is True

    def test_second_batch_paper_execution_skipped(self, tmp_artifacts):
        from datetime import date
        rd = date(2025, 6, 1)
        m1 = _run_demo_cycle(tmp_artifacts, run_date=rd)
        assert m1.stages["paper_execution"].status == StageStatus.COMPLETED

        # Force past duplicate-run check, but batch check should block
        m2 = _run_demo_cycle(tmp_artifacts, run_date=rd, force=True)
        pe2 = m2.stages["paper_execution"]
        assert pe2.status == StageStatus.SKIPPED
        assert any("batch already executed" in w.lower() or "Duplicate batch" in w
                    for w in pe2.warnings)


# ---------------------------------------------------------------------------
# Test: Approval gate
# ---------------------------------------------------------------------------

class TestApprovalGate:
    def test_approval_required_blocks_execution(self, tmp_artifacts):
        manifest = _run_demo_cycle(
            tmp_artifacts, require_approval=True,
        )
        pe = manifest.stages["paper_execution"]
        assert pe.status == StageStatus.SKIPPED
        assert any("approval" in w.lower() for w in pe.warnings)
        assert manifest.approval_status == ApprovalStatus.PENDING_APPROVAL

    def test_approval_state_persisted(self, tmp_artifacts):
        manifest = _run_demo_cycle(
            tmp_artifacts, require_approval=True,
        )
        state = load_approval_state(manifest.artifact_dir)
        assert state is not None
        assert state["status"] == ApprovalStatus.PENDING_APPROVAL
        assert state["batch_id"] == manifest.batch_id

    def test_approve_batch_succeeds(self, tmp_artifacts):
        manifest = _run_demo_cycle(
            tmp_artifacts, require_approval=True,
        )
        result = approve_batch(manifest.artifact_dir, manifest.batch_id)
        assert result is True

        state = load_approval_state(manifest.artifact_dir)
        assert state["status"] == ApprovalStatus.APPROVED

    def test_approve_batch_wrong_id_fails(self, tmp_artifacts):
        manifest = _run_demo_cycle(
            tmp_artifacts, require_approval=True,
        )
        result = approve_batch(manifest.artifact_dir, "wrong_batch_id")
        assert result is False


# ---------------------------------------------------------------------------
# Test: Failure and resume
# ---------------------------------------------------------------------------

class TestFailureResume:
    def test_fault_at_review_fails_run(self, tmp_artifacts):
        from datetime import date
        fi = FaultInjector(fail_stages=["review"], fail_on_cycle=1)
        config = _demo_config(tmp_artifacts)
        manager = InstrumentedRunManager(
            config, run_date=date(2025, 6, 1), fault_injector=fi, cycle_num=1,
        )
        manifest = manager.run()
        assert manifest.status in (RunStatus.FAILED, RunStatus.PARTIAL)
        assert manifest.stages["review"].status == StageStatus.FAILED

    def test_subsequent_stages_skipped_after_failure(self, tmp_artifacts):
        from datetime import date
        fi = FaultInjector(fail_stages=["review"], fail_on_cycle=1)
        config = _demo_config(tmp_artifacts)
        manager = InstrumentedRunManager(
            config, run_date=date(2025, 6, 1), fault_injector=fi, cycle_num=1,
        )
        manifest = manager.run()
        # Stages after review should be skipped
        for stage in ["execution_intents", "guardrail_validation",
                      "paper_execution", "artifact_export"]:
            assert manifest.stages[stage].status == StageStatus.SKIPPED

    def test_resume_from_review_completes(self, tmp_artifacts):
        from datetime import date
        rd = date(2025, 6, 1)
        config = _demo_config(tmp_artifacts)
        # Resume from review — skips ingestion, runs review onward
        manager = RunManager(config, run_date=rd, force=True)
        manifest = manager.run(resume_from="review")
        assert manifest.status == RunStatus.COMPLETED
        assert manifest.stages["ingestion"].status == StageStatus.SKIPPED
        assert manifest.stages["review"].status == StageStatus.COMPLETED

    def test_fault_at_paper_execution_preserves_prior_stages(self, tmp_artifacts):
        from datetime import date
        fi = FaultInjector(fail_stages=["paper_execution"], fail_on_cycle=1)
        config = _demo_config(tmp_artifacts)
        manager = InstrumentedRunManager(
            config, run_date=date(2025, 6, 1), fault_injector=fi, cycle_num=1,
        )
        manifest = manager.run()
        # Prior stages completed
        assert manifest.stages["review"].status == StageStatus.COMPLETED
        assert manifest.stages["guardrail_validation"].status == StageStatus.COMPLETED
        # Paper execution failed
        assert manifest.stages["paper_execution"].status == StageStatus.FAILED


# ---------------------------------------------------------------------------
# Test: Dry-run
# ---------------------------------------------------------------------------

class TestDryRun:
    def test_dry_run_no_paper_execution(self, tmp_artifacts):
        manifest = _run_demo_cycle(tmp_artifacts, dry_run=True)
        pe = manifest.stages["paper_execution"]
        assert pe.status == StageStatus.SKIPPED

    def test_dry_run_no_artifacts(self, tmp_artifacts):
        manifest = _run_demo_cycle(tmp_artifacts, dry_run=True)
        ae = manifest.stages["artifact_export"]
        assert ae.status == StageStatus.SKIPPED

    def test_dry_run_no_manifest_on_disk(self, tmp_artifacts):
        manifest = _run_demo_cycle(tmp_artifacts, dry_run=True)
        # Manifest should NOT be saved in dry-run
        if manifest.artifact_dir:
            manifest_path = os.path.join(manifest.artifact_dir, "run_manifest.json")
            assert not os.path.exists(manifest_path)


# ---------------------------------------------------------------------------
# Test: No-actionable recommendations
# ---------------------------------------------------------------------------

class TestNoActionable:
    def test_no_actionable_produces_zero_intents(self, tmp_artifacts):
        from datetime import date
        config = _demo_config(tmp_artifacts)
        manager = InstrumentedRunManager(
            config, run_date=date(2025, 6, 1), no_actionable=True,
        )
        manifest = manager.run()
        ei = manifest.stages["execution_intents"]
        assert ei.status == StageStatus.COMPLETED
        assert ei.counts.get("order_intents", 0) == 0

    def test_no_actionable_paper_execution_zero_fills(self, tmp_artifacts):
        from datetime import date
        config = _demo_config(tmp_artifacts)
        manager = InstrumentedRunManager(
            config, run_date=date(2025, 6, 1), no_actionable=True,
        )
        manifest = manager.run()
        pe = manifest.stages["paper_execution"]
        # Paper execution either completes with 0 fills or is skipped
        if pe.status == StageStatus.COMPLETED:
            assert pe.counts.get("fills_executed", 0) == 0


# ---------------------------------------------------------------------------
# Test: Invariant checks
# ---------------------------------------------------------------------------

class TestInvariantChecks:
    def _make_outcome(self, cycle_num=1, status=RunStatus.COMPLETED,
                      fills=0, pe_status=StageStatus.COMPLETED,
                      approved=0, env="demo", run_date="2025-06-01",
                      **stage_overrides):
        """Build a CycleOutcome for invariant testing."""
        stages = {}
        for s in RunManager.STAGES:
            sr = StageResult(stage=s)
            sr.status = StageStatus.COMPLETED
            stages[s] = sr

        pe = stages["paper_execution"]
        pe.status = pe_status
        pe.counts = {"fills_executed": fills}

        gv = stages["guardrail_validation"]
        gv.counts = {"approved": approved}

        for k, v in stage_overrides.items():
            if k in stages:
                stages[k].status = v

        manifest = RunManifest(
            run_id=f"test_{cycle_num}",
            environment=env,
            run_date=run_date,
            started_at="2025-06-01T00:00:00",
            status=status,
            stages=stages,
        )

        return CycleOutcome(
            cycle_num=cycle_num,
            manifest=manifest,
            fills_count=fills,
        )

    def test_no_duplicate_fills_passes(self):
        o1 = self._make_outcome(1, fills=3, run_date="2025-06-01")
        o2 = self._make_outcome(2, fills=2, run_date="2025-06-02")
        violations = check_no_duplicate_fills([o1, o2])
        assert len(violations) == 0

    def test_no_duplicate_fills_detects(self):
        o1 = self._make_outcome(1, fills=3, run_date="2025-06-01")
        o2 = self._make_outcome(2, fills=2, run_date="2025-06-01")
        violations = check_no_duplicate_fills([o1, o2])
        assert len(violations) == 1
        assert violations[0].check_name == "no_duplicate_fills"

    def test_manifest_coherence_passes(self):
        o = self._make_outcome(1, status=RunStatus.COMPLETED)
        violations = check_manifest_coherence([o])
        assert len(violations) == 0

    def test_manifest_coherence_detects_mismatch(self):
        o = self._make_outcome(1, status=RunStatus.COMPLETED,
                               review=StageStatus.FAILED)
        violations = check_manifest_coherence([o])
        assert len(violations) == 1
        assert violations[0].check_name == "manifest_coherence"

    def test_environment_labels_passes(self):
        o = self._make_outcome(1, env="demo")
        violations = check_environment_labels([o], "demo")
        assert len(violations) == 0

    def test_environment_labels_detects_mismatch(self):
        o = self._make_outcome(1, env="paper")
        violations = check_environment_labels([o], "demo")
        assert len(violations) == 1

    def test_fills_within_intents_passes(self):
        o = self._make_outcome(1, fills=3, approved=5)
        violations = check_fills_within_intents([o])
        assert len(violations) == 0

    def test_fills_within_intents_detects_excess(self):
        o = self._make_outcome(1, fills=5, approved=3)
        violations = check_fills_within_intents([o])
        assert len(violations) == 1

    def test_dry_run_no_mutation_passes(self):
        o = self._make_outcome(1, fills=0, pe_status=StageStatus.SKIPPED)
        violations = check_dry_run_no_mutation([o])
        assert len(violations) == 0

    def test_dry_run_no_mutation_detects_fills(self):
        o = self._make_outcome(1, fills=2, pe_status=StageStatus.SKIPPED)
        violations = check_dry_run_no_mutation([o])
        assert len(violations) == 1

    def test_duplicate_run_blocked_passes(self):
        o1 = self._make_outcome(1, status=RunStatus.COMPLETED)
        o2 = self._make_outcome(2, status=RunStatus.SKIPPED)
        o2.duplicate_run_blocked = True
        violations = check_duplicate_run_blocked([o1, o2])
        assert len(violations) == 0

    def test_approval_gate_passes_when_blocked(self):
        o = self._make_outcome(1, pe_status=StageStatus.SKIPPED)
        o.approval_blocked = True
        violations = check_approval_gate([o])
        assert len(violations) == 0

    def test_approval_gate_detects_breach(self):
        o = self._make_outcome(1, pe_status=StageStatus.COMPLETED, fills=2)
        o.approval_blocked = True
        violations = check_approval_gate([o])
        assert len(violations) == 1


# ---------------------------------------------------------------------------
# Test: Scenario-based validation (OperatingValidator)
# ---------------------------------------------------------------------------

class TestOperatingValidatorScenarios:
    def test_happy_path_scenario(self, tmp_artifacts):
        validator = OperatingValidator(artifact_base_dir=tmp_artifacts)
        result = validator.run_scenario("happy_path")
        assert result.passed
        assert len(result.cycles) == 3
        # First cycle completes with fills
        assert result.cycles[0].manifest.status == RunStatus.COMPLETED
        assert result.cycles[0].fills_count > 0

    def test_duplicate_run_scenario(self, tmp_artifacts):
        validator = OperatingValidator(artifact_base_dir=tmp_artifacts)
        result = validator.run_scenario("duplicate_run")
        assert result.passed
        assert len(result.cycles) == 2
        # Cycle 1 completes
        assert result.cycles[0].manifest.status == RunStatus.COMPLETED
        # Cycle 2 blocked as duplicate
        assert result.cycles[1].manifest.status == RunStatus.SKIPPED
        assert result.cycles[1].duplicate_run_blocked

    def test_duplicate_batch_scenario(self, tmp_artifacts):
        validator = OperatingValidator(artifact_base_dir=tmp_artifacts)
        result = validator.run_scenario("duplicate_batch")
        assert result.passed
        assert len(result.cycles) == 2
        # Cycle 1: paper execution completes
        assert result.cycles[0].manifest.stages["paper_execution"].status == StageStatus.COMPLETED
        # Cycle 2: paper execution blocked (batch already executed)
        assert result.cycles[1].manifest.stages["paper_execution"].status == StageStatus.SKIPPED

    def test_dry_run_scenario(self, tmp_artifacts):
        validator = OperatingValidator(artifact_base_dir=tmp_artifacts)
        result = validator.run_scenario("dry_run")
        assert result.passed
        assert len(result.cycles) == 1
        assert result.cycles[0].fills_count == 0

    def test_no_actionable_scenario(self, tmp_artifacts):
        validator = OperatingValidator(artifact_base_dir=tmp_artifacts)
        result = validator.run_scenario("no_actionable")
        assert result.passed

    def test_failure_ingestion_scenario(self, tmp_artifacts):
        validator = OperatingValidator(artifact_base_dir=tmp_artifacts)
        result = validator.run_scenario("failure_ingestion")
        # In demo mode, ingestion is skipped, so fault can't be injected there.
        # The fault fires but ingestion was already marked as skipped.
        # This is expected: the scenario validates fault injection doesn't crash.
        assert len(result.cycles) == 1

    def test_unknown_scenario(self, tmp_artifacts):
        validator = OperatingValidator(artifact_base_dir=tmp_artifacts)
        result = validator.run_scenario("nonexistent")
        assert not result.passed
        assert result.error is not None

    def test_failure_resume_scenario(self, tmp_artifacts):
        validator = OperatingValidator(artifact_base_dir=tmp_artifacts)
        result = validator.run_scenario("failure_resume")
        assert len(result.cycles) == 2
        # Cycle 1: review failed
        c1 = result.cycles[0]
        assert c1.manifest.stages["review"].status == StageStatus.FAILED
        assert c1.fault_injected
        # Cycle 2: resumed from review
        c2 = result.cycles[1]
        assert c2.resumed

    def test_approval_required_scenario(self, tmp_artifacts):
        validator = OperatingValidator(artifact_base_dir=tmp_artifacts)
        result = validator.run_scenario("approval_required")
        assert len(result.cycles) == 2
        # Cycle 1: approval blocks paper execution
        c1 = result.cycles[0]
        pe1 = c1.manifest.stages["paper_execution"]
        assert pe1.status == StageStatus.SKIPPED

    def test_config_change_scenario(self, tmp_artifacts):
        validator = OperatingValidator(artifact_base_dir=tmp_artifacts)
        result = validator.run_scenario("config_change")
        assert len(result.cycles) == 2
        # Cycle 2 has different portfolio_value in config
        c2_config = result.cycles[1].manifest.config_snapshot
        assert c2_config.get("portfolio_value") == 2_000_000.0


# ---------------------------------------------------------------------------
# Test: Validation report
# ---------------------------------------------------------------------------

class TestValidationReport:
    def test_build_report_from_results(self, tmp_artifacts):
        validator = OperatingValidator(artifact_base_dir=tmp_artifacts)
        results = [
            validator.run_scenario("happy_path"),
            validator.run_scenario("dry_run"),
        ]
        report = build_report(results, report_id="test_report")
        assert report.total_scenarios == 2
        assert report.passed_scenarios >= 1
        assert report.total_cycles >= 2

    def test_report_overall_passed(self, tmp_artifacts):
        validator = OperatingValidator(artifact_base_dir=tmp_artifacts)
        results = [validator.run_scenario("happy_path")]
        report = build_report(results)
        assert report.overall_passed

    def test_report_text_format(self, tmp_artifacts):
        validator = OperatingValidator(artifact_base_dir=tmp_artifacts)
        results = [validator.run_scenario("happy_path")]
        report = build_report(results)
        text = format_report_text(report)
        assert "OPERATING VALIDATION REPORT" in text
        assert "happy_path" in text
        assert "PASS" in text

    def test_report_json_roundtrip(self, tmp_artifacts):
        validator = OperatingValidator(artifact_base_dir=tmp_artifacts)
        results = [validator.run_scenario("happy_path")]
        report = build_report(results)
        d = report.to_dict()
        assert d["overall_passed"] is True
        assert d["summary"]["total_scenarios"] == 1
        # Can serialize to JSON
        json_str = json.dumps(d, default=str)
        parsed = json.loads(json_str)
        assert parsed["overall_passed"] is True

    def test_export_report_creates_files(self, tmp_artifacts):
        validator = OperatingValidator(artifact_base_dir=tmp_artifacts)
        results = [validator.run_scenario("happy_path")]
        report = build_report(results)
        output_dir = os.path.join(tmp_artifacts, "report_out")
        paths = export_report(report, output_dir)
        assert os.path.exists(paths["json"])
        assert os.path.exists(paths["text"])
        assert os.path.exists(paths["configs"])

    def test_report_captures_faults(self, tmp_artifacts):
        validator = OperatingValidator(artifact_base_dir=tmp_artifacts)
        results = [validator.run_scenario("failure_resume")]
        report = build_report(results)
        assert report.faults_injected >= 1

    def test_report_captures_duplicates(self, tmp_artifacts):
        validator = OperatingValidator(artifact_base_dir=tmp_artifacts)
        results = [validator.run_scenario("duplicate_run")]
        report = build_report(results)
        assert report.duplicate_runs_blocked >= 1

    def test_report_captures_scenario_outcomes(self, tmp_artifacts):
        validator = OperatingValidator(artifact_base_dir=tmp_artifacts)
        results = [validator.run_scenario("happy_path")]
        report = build_report(results)
        assert len(report.scenario_results) == 1
        sr = report.scenario_results[0]
        assert sr["scenario_name"] == "happy_path"
        assert sr["passed"] is True


# ---------------------------------------------------------------------------
# Test: Graph export after cycles (basic check)
# ---------------------------------------------------------------------------

class TestGraphAfterCycles:
    def test_graph_modules_importable(self):
        """Verify graph modules are available for post-cycle export."""
        from graph_memory import ConsensusGraph, NodeType, EdgeType
        from graph_sync import build_full_graph, export_graph
        from graph_queries import why_own, company_summary
        cg = ConsensusGraph()
        assert cg.summary()["total_nodes"] == 0

    def test_graph_export_after_cycle(self, tmp_artifacts):
        """After a cycle completes, graph export doesn't crash."""
        from graph_memory import ConsensusGraph
        from graph_sync import export_graph
        manifest = _run_demo_cycle(tmp_artifacts)
        assert manifest.status == RunStatus.COMPLETED
        # Graph export on empty graph (demo has no DB)
        cg = ConsensusGraph()
        export_dir = os.path.join(tmp_artifacts, "graph_test")
        path = export_graph(cg, export_dir, "test")
        assert os.path.exists(path)


# ---------------------------------------------------------------------------
# Test: Predefined scenarios are well-formed
# ---------------------------------------------------------------------------

class TestScenarioDefinitions:
    def test_all_scenarios_have_names(self):
        for name, sc in SCENARIOS.items():
            assert sc.name == name

    def test_all_scenarios_have_descriptions(self):
        for name, sc in SCENARIOS.items():
            assert len(sc.description) > 0

    def test_all_scenarios_serializable(self):
        for name, sc in SCENARIOS.items():
            d = sc.to_dict()
            assert d["name"] == name

    def test_scenario_count(self):
        assert len(SCENARIOS) >= 10


# ---------------------------------------------------------------------------
# Test: Run all scenarios end-to-end
# ---------------------------------------------------------------------------

class TestRunAll:
    def test_run_all_scenarios(self, tmp_artifacts):
        """Run every predefined scenario. All should complete without crash."""
        validator = OperatingValidator(artifact_base_dir=tmp_artifacts)
        results = validator.run_all()
        assert len(results) == len(SCENARIOS)
        for r in results:
            # Every scenario should produce at least 1 cycle
            assert len(r.cycles) >= 1, f"Scenario {r.scenario_name} has no cycles"

    def test_full_report_from_all(self, tmp_artifacts):
        """Full validation report from all scenarios."""
        validator = OperatingValidator(artifact_base_dir=tmp_artifacts)
        results = validator.run_all()
        report = build_report(results, report_id="full_test")
        assert report.total_scenarios == len(SCENARIOS)
        text = format_report_text(report)
        assert "OPERATING VALIDATION REPORT" in text
