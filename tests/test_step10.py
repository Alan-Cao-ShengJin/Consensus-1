"""Tests for Step 10: production hardening and operating layer.

Covers:
  - Full system cycle produces a run manifest
  - Duplicate run protection
  - Rerunning a completed batch does not re-apply paper fills
  - Stage failure produces FAILED/PARTIAL state with preserved artifacts
  - Config loading and overrides
  - Approval gate blocks paper execution until approved
  - Demo and paper modes are clearly separated
  - Dry-run path does not mutate paper portfolio state
  - Logs/manifests contain expected stage metadata
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import date
from unittest.mock import patch, MagicMock

import pytest

from config import SystemConfig, Environment, get_default_config
from run_manager import (
    RunManager, RunManifest, RunStatus, StageStatus,
    StageResult, ApprovalStatus,
    check_duplicate_run, check_batch_already_executed,
    approve_batch, save_approval_state, load_approval_state,
    run_system_cycle,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_artifacts(tmp_path):
    """Temporary artifact directory."""
    return str(tmp_path / "artifacts")


@pytest.fixture
def demo_config(tmp_artifacts):
    """Demo config with temporary artifact dir."""
    return SystemConfig(
        environment=Environment.DEMO,
        dry_run=False,
        paper_execute=False,
        artifact_base_dir=tmp_artifacts,
    )


@pytest.fixture
def demo_config_with_paper(tmp_artifacts):
    """Demo config with paper execution enabled."""
    return SystemConfig(
        environment=Environment.DEMO,
        dry_run=False,
        paper_execute=True,
        artifact_base_dir=tmp_artifacts,
    )


@pytest.fixture
def demo_config_dry_run(tmp_artifacts):
    """Demo config in dry-run mode."""
    return SystemConfig(
        environment=Environment.DEMO,
        dry_run=True,
        paper_execute=True,
        artifact_base_dir=tmp_artifacts,
    )


@pytest.fixture
def demo_config_approval(tmp_artifacts):
    """Demo config with approval required."""
    return SystemConfig(
        environment=Environment.DEMO,
        dry_run=False,
        paper_execute=True,
        require_approval=True,
        artifact_base_dir=tmp_artifacts,
    )


# ---------------------------------------------------------------------------
# Test: Full system cycle produces a run manifest
# ---------------------------------------------------------------------------

class TestFullSystemCycle:

    def test_demo_cycle_produces_manifest(self, demo_config):
        """A demo cycle completes and produces a manifest with all stages."""
        run_date = date(2025, 10, 1)
        manifest = run_system_cycle(demo_config, run_date=run_date)

        assert manifest.status == RunStatus.COMPLETED
        assert manifest.run_date == "2025-10-01"
        assert manifest.environment == Environment.DEMO
        assert manifest.run_id is not None
        assert manifest.started_at is not None
        assert manifest.ended_at is not None

        # All stages should have been processed
        assert "ingestion" in manifest.stages
        assert "review" in manifest.stages
        assert "execution_intents" in manifest.stages
        assert "guardrail_validation" in manifest.stages
        assert "paper_execution" in manifest.stages
        assert "artifact_export" in manifest.stages

    def test_demo_cycle_ingestion_skipped(self, demo_config):
        """Demo mode skips ingestion."""
        manifest = run_system_cycle(demo_config, run_date=date(2025, 10, 1))
        assert manifest.stages["ingestion"].status == StageStatus.SKIPPED

    def test_demo_cycle_review_completes(self, demo_config):
        """Demo mode completes review with synthetic data."""
        manifest = run_system_cycle(demo_config, run_date=date(2025, 10, 1))
        assert manifest.stages["review"].status == StageStatus.COMPLETED
        assert manifest.stages["review"].counts.get("decisions", 0) > 0

    def test_demo_cycle_execution_intents_generated(self, demo_config):
        """Demo mode generates execution intents."""
        manifest = run_system_cycle(demo_config, run_date=date(2025, 10, 1))
        assert manifest.stages["execution_intents"].status == StageStatus.COMPLETED
        assert manifest.stages["execution_intents"].counts.get("order_intents", 0) > 0

    def test_demo_cycle_guardrails_pass(self, demo_config):
        """Demo guardrail validation completes."""
        manifest = run_system_cycle(demo_config, run_date=date(2025, 10, 1))
        assert manifest.stages["guardrail_validation"].status == StageStatus.COMPLETED

    def test_demo_cycle_manifest_saved_to_disk(self, demo_config):
        """Manifest file is written to artifact directory."""
        manifest = run_system_cycle(demo_config, run_date=date(2025, 10, 1))
        manifest_path = os.path.join(manifest.artifact_dir, "run_manifest.json")
        assert os.path.exists(manifest_path)

        loaded = RunManifest.load(manifest_path)
        assert loaded.run_id == manifest.run_id
        assert loaded.status == RunStatus.COMPLETED

    def test_demo_with_paper_execution(self, demo_config_with_paper):
        """Demo + paper-execute runs the full pipeline including paper fills."""
        manifest = run_system_cycle(demo_config_with_paper, run_date=date(2025, 10, 1))
        assert manifest.status == RunStatus.COMPLETED
        assert manifest.stages["paper_execution"].status == StageStatus.COMPLETED
        assert manifest.stages["paper_execution"].counts.get("fills_executed", 0) > 0


# ---------------------------------------------------------------------------
# Test: Duplicate run protection
# ---------------------------------------------------------------------------

class TestDuplicateRunProtection:

    def test_duplicate_run_detected(self, demo_config):
        """Second run for the same date is detected as duplicate."""
        run_date = date(2025, 10, 1)

        # First run
        m1 = run_system_cycle(demo_config, run_date=run_date)
        assert m1.status == RunStatus.COMPLETED

        # Second run should detect duplicate
        m2 = run_system_cycle(demo_config, run_date=run_date)
        assert m2.status == RunStatus.SKIPPED
        assert "Duplicate" in (m2.error_summary or "")

    def test_force_bypasses_duplicate_check(self, demo_config):
        """--force allows rerun even if duplicate exists."""
        run_date = date(2025, 10, 1)

        m1 = run_system_cycle(demo_config, run_date=run_date)
        assert m1.status == RunStatus.COMPLETED

        # Force run should succeed
        m2 = run_system_cycle(demo_config, run_date=run_date, force=True)
        assert m2.status == RunStatus.COMPLETED
        assert m2.run_id != m1.run_id

    def test_dry_run_skips_duplicate_check(self, tmp_artifacts):
        """Dry run doesn't check for duplicates (no artifact dir)."""
        config = SystemConfig(
            environment=Environment.DEMO,
            dry_run=True,
            artifact_base_dir=tmp_artifacts,
        )
        run_date = date(2025, 10, 1)

        m1 = run_system_cycle(config, run_date=run_date)
        m2 = run_system_cycle(config, run_date=run_date)

        # Both should complete (no duplicate check in dry-run)
        assert m1.status == RunStatus.COMPLETED
        assert m2.status == RunStatus.COMPLETED


# ---------------------------------------------------------------------------
# Test: Rerunning a completed batch does not re-apply paper fills
# ---------------------------------------------------------------------------

class TestBatchIdempotency:

    def test_paper_execution_not_reapplied(self, demo_config_with_paper):
        """Once paper execution completes, a second run does not re-execute."""
        run_date = date(2025, 10, 2)

        m1 = run_system_cycle(demo_config_with_paper, run_date=run_date)
        assert m1.stages["paper_execution"].status == StageStatus.COMPLETED

        # Second run: duplicate detected at run level
        m2 = run_system_cycle(demo_config_with_paper, run_date=run_date)
        assert m2.status == RunStatus.SKIPPED

    def test_batch_already_executed_check(self, tmp_artifacts):
        """check_batch_already_executed works correctly."""
        # No manifests yet
        assert not check_batch_already_executed(tmp_artifacts, "2025-10-01", "2025-10-01")

        # Create a manifest with completed paper execution
        run_id = "2025-10-01_test1234"
        run_dir = os.path.join(tmp_artifacts, "2025-10-01", run_id)
        os.makedirs(run_dir)
        manifest = RunManifest(
            run_id=run_id,
            environment=Environment.DEMO,
            run_date="2025-10-01",
            started_at="2025-10-01T00:00:00",
            status=RunStatus.COMPLETED,
        )
        manifest.stages["paper_execution"] = StageResult(
            stage="paper_execution",
            status=StageStatus.COMPLETED,
        )
        manifest.save(os.path.join(run_dir, "run_manifest.json"))

        assert check_batch_already_executed(tmp_artifacts, "2025-10-01", "2025-10-01")


# ---------------------------------------------------------------------------
# Test: Stage failure produces FAILED/PARTIAL state
# ---------------------------------------------------------------------------

class TestFailureHandling:

    def test_stage_failure_recorded(self, demo_config):
        """When a stage fails, the failure is recorded with error info."""
        run_date = date(2025, 10, 3)
        manager = RunManager(demo_config, run_date=run_date)

        # Patch review to fail
        with patch.object(manager, '_build_demo_review', side_effect=RuntimeError("review broke")):
            manifest = manager.run()

        assert manifest.status in (RunStatus.FAILED, RunStatus.PARTIAL)
        review_stage = manifest.stages["review"]
        assert review_stage.status == StageStatus.FAILED
        assert "review broke" in review_stage.error

    def test_partial_state_when_later_stage_fails(self, demo_config_with_paper):
        """If a later stage fails, earlier completed stages are preserved."""
        run_date = date(2025, 10, 4)
        manager = RunManager(demo_config_with_paper, run_date=run_date)

        # Let review/intents succeed, but fail paper execution
        original_stage = manager._stage_paper_execution
        def failing_paper(*args, **kwargs):
            manager.manifest.stages["paper_execution"].mark_started()
            raise RuntimeError("paper engine broke")

        manager._stage_paper_execution = failing_paper
        manifest = manager.run()

        assert manifest.status == RunStatus.PARTIAL
        assert manifest.stages["review"].status == StageStatus.COMPLETED
        assert manifest.stages["execution_intents"].status == StageStatus.COMPLETED
        assert manifest.stages["paper_execution"].status == StageStatus.FAILED

    def test_subsequent_stages_skipped_after_failure(self, demo_config):
        """Stages after a failure are skipped."""
        run_date = date(2025, 10, 5)
        manager = RunManager(demo_config, run_date=run_date)

        with patch.object(manager, '_build_demo_review', side_effect=RuntimeError("fail")):
            manifest = manager.run()

        # Stages after review should be skipped
        assert manifest.stages["execution_intents"].status == StageStatus.SKIPPED
        assert manifest.stages["guardrail_validation"].status == StageStatus.SKIPPED

    def test_manifest_preserved_on_failure(self, demo_config):
        """Manifest is saved even when the run fails."""
        run_date = date(2025, 10, 6)
        manager = RunManager(demo_config, run_date=run_date)

        with patch.object(manager, '_build_demo_review', side_effect=RuntimeError("fail")):
            manifest = manager.run()

        # Manifest should be saved
        manifest_path = os.path.join(manifest.artifact_dir, "run_manifest.json")
        assert os.path.exists(manifest_path)
        loaded = RunManifest.load(manifest_path)
        assert loaded.status in (RunStatus.FAILED, RunStatus.PARTIAL)


# ---------------------------------------------------------------------------
# Test: Config loading and overrides
# ---------------------------------------------------------------------------

class TestConfigManagement:

    def test_default_config(self):
        """Default config has sane defaults."""
        config = SystemConfig()
        assert config.environment == Environment.PAPER
        assert config.portfolio_value == 1_000_000.0
        assert config.transaction_cost_bps == 10.0

    def test_demo_config(self):
        """Demo config sets expected defaults."""
        config = get_default_config(Environment.DEMO)
        assert config.environment == Environment.DEMO
        assert config.dry_run is True

    def test_paper_config(self):
        """Paper config sets expected defaults."""
        config = get_default_config(Environment.PAPER)
        assert config.environment == Environment.PAPER
        assert config.dry_run is False
        assert config.paper_execute is True

    def test_live_config_accepted(self):
        """LIVE environment is now supported."""
        config = SystemConfig(environment=Environment.LIVE)
        assert config.environment == "live"

    def test_invalid_environment_raises(self):
        """Invalid environment raises an error."""
        with pytest.raises(ValueError, match="Invalid environment"):
            SystemConfig(environment="production")

    def test_config_merge_overrides(self):
        """Merge applies overrides correctly."""
        base = SystemConfig(environment=Environment.DEMO, portfolio_value=500_000.0)
        merged = base.merge({"portfolio_value": 2_000_000.0, "dry_run": True})
        assert merged.portfolio_value == 2_000_000.0
        assert merged.dry_run is True
        assert merged.environment == Environment.DEMO

    def test_config_from_dict(self):
        """Config can be created from a dict."""
        d = {"environment": "demo", "portfolio_value": 750_000.0, "tickers": ["AAPL"]}
        config = SystemConfig.from_dict(d)
        assert config.environment == "demo"
        assert config.portfolio_value == 750_000.0
        assert config.tickers == ["AAPL"]

    def test_config_from_dict_ignores_unknown(self):
        """Unknown keys are ignored."""
        d = {"environment": "demo", "unknown_field": 42}
        config = SystemConfig.from_dict(d)
        assert config.environment == "demo"

    def test_config_from_json_file(self, tmp_path):
        """Config can be loaded from a JSON file."""
        config_data = {
            "environment": "demo",
            "portfolio_value": 500_000.0,
            "tickers": ["MSFT", "AAPL"],
        }
        config_path = str(tmp_path / "config.json")
        with open(config_path, "w") as f:
            json.dump(config_data, f)

        config = SystemConfig.from_file(config_path)
        assert config.environment == "demo"
        assert config.portfolio_value == 500_000.0
        assert config.tickers == ["MSFT", "AAPL"]

    def test_config_to_dict_roundtrip(self):
        """Config survives dict roundtrip."""
        original = SystemConfig(
            environment=Environment.DEMO,
            tickers=["NVDA"],
            portfolio_value=123_456.0,
        )
        d = original.to_dict()
        restored = SystemConfig.from_dict(d)
        assert restored.environment == original.environment
        assert restored.tickers == original.tickers
        assert restored.portfolio_value == original.portfolio_value


# ---------------------------------------------------------------------------
# Test: Approval gate
# ---------------------------------------------------------------------------

class TestApprovalGate:

    def test_approval_required_blocks_execution(self, demo_config_approval):
        """When approval is required, paper execution is blocked."""
        run_date = date(2025, 10, 7)
        manifest = run_system_cycle(demo_config_approval, run_date=run_date)

        assert manifest.stages["paper_execution"].status == StageStatus.SKIPPED
        assert manifest.approval_status == ApprovalStatus.PENDING_APPROVAL
        assert manifest.batch_id is not None

    def test_approval_state_saved(self, demo_config_approval):
        """Approval state is written to the artifact directory."""
        run_date = date(2025, 10, 8)
        manifest = run_system_cycle(demo_config_approval, run_date=run_date)

        state = load_approval_state(manifest.artifact_dir)
        assert state is not None
        assert state["status"] == ApprovalStatus.PENDING_APPROVAL
        assert state["batch_id"] == manifest.batch_id

    def test_approve_batch_works(self, demo_config_approval):
        """Approving a batch changes its status."""
        run_date = date(2025, 10, 9)
        manifest = run_system_cycle(demo_config_approval, run_date=run_date)

        batch_id = manifest.batch_id
        result = approve_batch(manifest.artifact_dir, batch_id)
        assert result is True

        state = load_approval_state(manifest.artifact_dir)
        assert state["status"] == ApprovalStatus.APPROVED

    def test_approve_wrong_batch_fails(self, demo_config_approval):
        """Approving with wrong batch_id fails."""
        run_date = date(2025, 10, 10)
        manifest = run_system_cycle(demo_config_approval, run_date=run_date)

        result = approve_batch(manifest.artifact_dir, "wrong_batch_id")
        assert result is False

    def test_no_approval_required_executes_directly(self, demo_config_with_paper):
        """Without require_approval, paper execution runs directly."""
        manifest = run_system_cycle(demo_config_with_paper, run_date=date(2025, 10, 11))
        assert manifest.stages["paper_execution"].status == StageStatus.COMPLETED
        assert manifest.approval_status == ApprovalStatus.NOT_REQUIRED


# ---------------------------------------------------------------------------
# Test: Demo and paper modes are clearly separated
# ---------------------------------------------------------------------------

class TestEnvironmentSeparation:

    def test_demo_environment_label(self, demo_config):
        """Demo runs are labeled with 'demo' environment."""
        manifest = run_system_cycle(demo_config, run_date=date(2025, 10, 12))
        assert manifest.environment == Environment.DEMO
        assert manifest.config_snapshot["environment"] == Environment.DEMO

    def test_paper_environment_label(self, tmp_artifacts):
        """Paper runs are labeled with 'paper' environment."""
        # We can't run full paper without DB, but we can verify config
        config = SystemConfig(
            environment=Environment.PAPER,
            artifact_base_dir=tmp_artifacts,
        )
        assert config.environment == Environment.PAPER

    def test_live_environment_accepted(self):
        """LIVE environment is now supported (no longer blocked)."""
        config = SystemConfig(environment=Environment.LIVE)
        assert config.environment == "live"

    def test_demo_and_paper_produce_different_configs(self):
        """Demo and paper default configs are different."""
        demo = get_default_config(Environment.DEMO)
        paper = get_default_config(Environment.PAPER)
        assert demo.dry_run != paper.dry_run
        assert demo.environment != paper.environment


# ---------------------------------------------------------------------------
# Test: Dry-run path does not mutate paper portfolio state
# ---------------------------------------------------------------------------

class TestDryRun:

    def test_dry_run_no_artifacts(self, demo_config_dry_run):
        """Dry run does not write artifact files."""
        manifest = run_system_cycle(demo_config_dry_run, run_date=date(2025, 10, 13))
        assert manifest.status == RunStatus.COMPLETED

        # Paper execution should be skipped in dry-run
        assert manifest.stages["paper_execution"].status == StageStatus.SKIPPED

        # Artifact export should be skipped
        assert manifest.stages["artifact_export"].status == StageStatus.SKIPPED

    def test_dry_run_no_manifest_file(self, demo_config_dry_run):
        """Dry run does not write manifest to disk."""
        manifest = run_system_cycle(demo_config_dry_run, run_date=date(2025, 10, 14))
        manifest_path = os.path.join(manifest.artifact_dir, "run_manifest.json")
        assert not os.path.exists(manifest_path)


# ---------------------------------------------------------------------------
# Test: Manifests contain expected stage metadata
# ---------------------------------------------------------------------------

class TestManifestMetadata:

    def test_manifest_has_config_snapshot(self, demo_config):
        """Manifest includes the config snapshot."""
        manifest = run_system_cycle(demo_config, run_date=date(2025, 10, 15))
        assert "environment" in manifest.config_snapshot
        assert manifest.config_snapshot["environment"] == Environment.DEMO

    def test_manifest_stages_have_timestamps(self, demo_config):
        """Completed stages have start/end timestamps."""
        manifest = run_system_cycle(demo_config, run_date=date(2025, 10, 16))

        for name, sr in manifest.stages.items():
            if sr.status == StageStatus.COMPLETED:
                assert sr.started_at is not None
                assert sr.ended_at is not None

    def test_manifest_stages_have_counts(self, demo_config):
        """Completed stages have count metadata."""
        manifest = run_system_cycle(demo_config, run_date=date(2025, 10, 17))

        review = manifest.stages["review"]
        assert review.status == StageStatus.COMPLETED
        assert "decisions" in review.counts

        intents = manifest.stages["execution_intents"]
        assert intents.status == StageStatus.COMPLETED
        assert "order_intents" in intents.counts

    def test_manifest_serialization_roundtrip(self, demo_config):
        """Manifest survives JSON save/load roundtrip."""
        manifest = run_system_cycle(demo_config, run_date=date(2025, 10, 18))
        manifest_path = os.path.join(manifest.artifact_dir, "run_manifest.json")

        loaded = RunManifest.load(manifest_path)
        assert loaded.run_id == manifest.run_id
        assert loaded.status == manifest.status
        assert loaded.environment == manifest.environment
        assert set(loaded.stages.keys()) == set(manifest.stages.keys())

    def test_manifest_to_dict_complete(self, demo_config):
        """to_dict includes all expected fields."""
        manifest = run_system_cycle(demo_config, run_date=date(2025, 10, 19))
        d = manifest.to_dict()

        required_keys = [
            "run_id", "environment", "run_date", "started_at",
            "ended_at", "status", "config_snapshot", "stages",
        ]
        for key in required_keys:
            assert key in d, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# Test: Stage result lifecycle
# ---------------------------------------------------------------------------

class TestStageResult:

    def test_mark_started(self):
        sr = StageResult(stage="test")
        sr.mark_started()
        assert sr.status == StageStatus.RUNNING
        assert sr.started_at is not None

    def test_mark_completed(self):
        sr = StageResult(stage="test")
        sr.mark_started()
        sr.mark_completed()
        assert sr.status == StageStatus.COMPLETED
        assert sr.ended_at is not None

    def test_mark_failed(self):
        sr = StageResult(stage="test")
        sr.mark_started()
        sr.mark_failed("something broke", "traceback here")
        assert sr.status == StageStatus.FAILED
        assert sr.error == "something broke"
        assert sr.error_traceback == "traceback here"

    def test_mark_skipped(self):
        sr = StageResult(stage="test")
        sr.mark_skipped("not needed")
        assert sr.status == StageStatus.SKIPPED
        assert "Skipped: not needed" in sr.warnings


# ---------------------------------------------------------------------------
# Test: Resume from stage
# ---------------------------------------------------------------------------

class TestResume:

    def test_resume_skips_earlier_stages(self, demo_config):
        """Resuming from a later stage skips earlier ones."""
        run_date = date(2025, 10, 20)
        manager = RunManager(demo_config, run_date=run_date)
        manifest = manager.run(resume_from="execution_intents")

        # Ingestion and review should be skipped
        assert manifest.stages["ingestion"].status == StageStatus.SKIPPED
        assert manifest.stages["review"].status == StageStatus.SKIPPED

        # execution_intents should have run (but may skip due to no review data)
        assert manifest.stages["execution_intents"].status in (
            StageStatus.COMPLETED, StageStatus.SKIPPED,
        )


# ---------------------------------------------------------------------------
# Test: Artifact files
# ---------------------------------------------------------------------------

class TestArtifactOutput:

    def test_artifact_dir_structure(self, demo_config):
        """Artifacts are organized under artifacts/<date>/<run_id>/."""
        manifest = run_system_cycle(demo_config, run_date=date(2025, 10, 21))
        assert manifest.artifact_dir is not None
        assert "2025-10-21" in manifest.artifact_dir
        assert os.path.isdir(manifest.artifact_dir)

    def test_config_exported(self, demo_config):
        """Config snapshot is exported to artifact dir."""
        manifest = run_system_cycle(demo_config, run_date=date(2025, 10, 22))
        config_path = os.path.join(manifest.artifact_dir, "config.json")
        assert os.path.exists(config_path)

        with open(config_path) as f:
            saved_config = json.load(f)
        assert saved_config["environment"] == Environment.DEMO

    def test_order_intents_exported(self, demo_config):
        """Order intents are exported when generated."""
        manifest = run_system_cycle(demo_config, run_date=date(2025, 10, 23))
        intents_path = os.path.join(manifest.artifact_dir, "order_intents.json")
        assert os.path.exists(intents_path)

        with open(intents_path) as f:
            data = json.load(f)
        assert "order_intents" in data

    def test_paper_fills_exported(self, demo_config_with_paper):
        """Paper fills are exported when paper execution runs."""
        manifest = run_system_cycle(demo_config_with_paper, run_date=date(2025, 10, 24))
        fills_path = os.path.join(manifest.artifact_dir, "paper_fills.json")
        assert os.path.exists(fills_path)

    def test_validation_exported(self, demo_config):
        """Validation result is exported."""
        manifest = run_system_cycle(demo_config, run_date=date(2025, 10, 25))
        val_path = os.path.join(manifest.artifact_dir, "validation_result.json")
        assert os.path.exists(val_path)


# ---------------------------------------------------------------------------
# Test: End-to-end demo cycle
# ---------------------------------------------------------------------------

class TestEndToEnd:

    def test_full_demo_paper_execute_cycle(self, tmp_artifacts):
        """Complete end-to-end: demo -> intents -> validate -> paper execute -> artifacts."""
        config = SystemConfig(
            environment=Environment.DEMO,
            dry_run=False,
            paper_execute=True,
            artifact_base_dir=tmp_artifacts,
        )
        manifest = run_system_cycle(config, run_date=date(2025, 10, 26))

        assert manifest.status == RunStatus.COMPLETED

        # All non-ingestion stages completed
        assert manifest.stages["ingestion"].status == StageStatus.SKIPPED  # demo
        assert manifest.stages["review"].status == StageStatus.COMPLETED
        assert manifest.stages["execution_intents"].status == StageStatus.COMPLETED
        assert manifest.stages["guardrail_validation"].status == StageStatus.COMPLETED
        assert manifest.stages["paper_execution"].status == StageStatus.COMPLETED
        assert manifest.stages["artifact_export"].status == StageStatus.COMPLETED

        # Counts are populated
        assert manifest.stages["review"].counts["decisions"] > 0
        assert manifest.stages["execution_intents"].counts["order_intents"] > 0
        assert manifest.stages["guardrail_validation"].counts["approved"] > 0
        assert manifest.stages["paper_execution"].counts["fills_executed"] > 0
        assert manifest.stages["artifact_export"].counts["files_exported"] > 0

        # Artifact files exist
        assert os.path.exists(os.path.join(manifest.artifact_dir, "run_manifest.json"))
        assert os.path.exists(os.path.join(manifest.artifact_dir, "config.json"))
        assert os.path.exists(os.path.join(manifest.artifact_dir, "order_intents.json"))
        assert os.path.exists(os.path.join(manifest.artifact_dir, "paper_fills.json"))
        assert os.path.exists(os.path.join(manifest.artifact_dir, "paper_execution_summary.json"))
        assert os.path.exists(os.path.join(manifest.artifact_dir, "portfolio_snapshot.json"))
