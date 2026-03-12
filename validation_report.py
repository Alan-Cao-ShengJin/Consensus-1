"""Operational validation report generation.

Produces structured summaries of multi-scenario validation runs,
with per-scenario pass/fail and aggregated statistics.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from operating_validator import ScenarioResult, CycleOutcome

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Validation report
# ---------------------------------------------------------------------------

@dataclass
class ValidationReport:
    """Aggregated report across all validation scenarios."""
    report_id: str
    generated_at: str
    total_scenarios: int = 0
    passed_scenarios: int = 0
    failed_scenarios: int = 0
    total_cycles: int = 0
    total_fills: int = 0
    total_invariant_violations: int = 0
    approvals_requested: int = 0
    approvals_granted: int = 0
    approvals_missing: int = 0
    duplicate_runs_blocked: int = 0
    duplicate_batches_blocked: int = 0
    resumes_performed: int = 0
    faults_injected: int = 0
    scenario_results: list[dict] = field(default_factory=list)
    overall_passed: bool = True

    def to_dict(self) -> dict:
        return {
            "report_id": self.report_id,
            "generated_at": self.generated_at,
            "overall_passed": self.overall_passed,
            "summary": {
                "total_scenarios": self.total_scenarios,
                "passed": self.passed_scenarios,
                "failed": self.failed_scenarios,
                "total_cycles": self.total_cycles,
                "total_fills": self.total_fills,
                "total_invariant_violations": self.total_invariant_violations,
            },
            "operations": {
                "approvals_requested": self.approvals_requested,
                "approvals_granted": self.approvals_granted,
                "approvals_missing": self.approvals_missing,
                "duplicate_runs_blocked": self.duplicate_runs_blocked,
                "duplicate_batches_blocked": self.duplicate_batches_blocked,
                "resumes_performed": self.resumes_performed,
                "faults_injected": self.faults_injected,
            },
            "scenarios": self.scenario_results,
        }


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------

def build_report(
    results: list[ScenarioResult],
    report_id: Optional[str] = None,
) -> ValidationReport:
    """Build a ValidationReport from a list of ScenarioResults."""
    report = ValidationReport(
        report_id=report_id or f"val_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
        generated_at=datetime.utcnow().isoformat(),
    )

    for sr in results:
        report.total_scenarios += 1
        if sr.passed:
            report.passed_scenarios += 1
        else:
            report.failed_scenarios += 1
            report.overall_passed = False

        report.total_invariant_violations += len(sr.invariant_violations)

        for oc in sr.cycles:
            report.total_cycles += 1
            report.total_fills += oc.fills_count
            if oc.duplicate_run_blocked:
                report.duplicate_runs_blocked += 1
            if oc.duplicate_batch_blocked:
                report.duplicate_batches_blocked += 1
            if oc.approval_blocked:
                report.approvals_missing += 1
                report.approvals_requested += 1
            if oc.fault_injected:
                report.faults_injected += 1
            if oc.resumed:
                report.resumes_performed += 1

        # Check if approval was eventually granted in this scenario
        for oc in sr.cycles:
            m = oc.manifest
            if m.approval_status == "APPROVED":
                report.approvals_granted += 1
                break

        report.scenario_results.append(sr.to_dict())

    return report


# ---------------------------------------------------------------------------
# Text formatting
# ---------------------------------------------------------------------------

def format_report_text(report: ValidationReport) -> str:
    """Format validation report as human-readable text."""
    lines = []
    lines.append("=" * 70)
    lines.append("OPERATING VALIDATION REPORT")
    lines.append("=" * 70)
    lines.append(f"Report ID: {report.report_id}")
    lines.append(f"Generated: {report.generated_at}")
    lines.append("")

    # Overall verdict
    verdict = "PASS" if report.overall_passed else "FAIL"
    lines.append(f"Overall: {verdict}")
    lines.append(
        f"Scenarios: {report.passed_scenarios}/{report.total_scenarios} passed"
    )
    lines.append(f"Total cycles: {report.total_cycles}")
    lines.append(f"Total fills: {report.total_fills}")
    lines.append(
        f"Invariant violations: {report.total_invariant_violations}"
    )
    lines.append("")

    # Operations
    lines.append("--- Operations ---")
    lines.append(f"  Duplicate runs blocked:   {report.duplicate_runs_blocked}")
    lines.append(f"  Duplicate batches blocked: {report.duplicate_batches_blocked}")
    lines.append(f"  Approvals requested:      {report.approvals_requested}")
    lines.append(f"  Approvals granted:        {report.approvals_granted}")
    lines.append(f"  Approvals missing:        {report.approvals_missing}")
    lines.append(f"  Resumes performed:        {report.resumes_performed}")
    lines.append(f"  Faults injected:          {report.faults_injected}")
    lines.append("")

    # Per-scenario
    lines.append("--- Scenario Results ---")
    for sr_dict in report.scenario_results:
        name = sr_dict["scenario_name"]
        passed = sr_dict["passed"]
        status = "PASS" if passed else "FAIL"
        desc = sr_dict.get("scenario_description", "")
        cycles = sr_dict.get("cycles", [])
        violations = sr_dict.get("invariant_violations", [])

        lines.append(f"  [{status}] {name}: {desc}")
        for c in cycles:
            cnum = c["cycle_num"]
            cstatus = c["status"]
            fills = c.get("fills_count", 0)
            line = f"    Cycle {cnum}: {cstatus}"
            if fills:
                line += f" ({fills} fills)"
            if c.get("duplicate_run_blocked"):
                line += " [dup-run blocked]"
            if c.get("duplicate_batch_blocked"):
                line += " [dup-batch blocked]"
            if c.get("approval_blocked"):
                line += " [approval blocked]"
            if c.get("fault_injected"):
                line += " [fault injected]"
            if c.get("resumed"):
                line += " [resumed]"
            lines.append(line)

        if violations:
            for v in violations:
                lines.append(f"    VIOLATION: [{v['check_name']}] {v['message']}")

        if sr_dict.get("error"):
            lines.append(f"    ERROR: {sr_dict['error']}")
        lines.append("")

    lines.append("=" * 70)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_report(
    report: ValidationReport,
    output_dir: str,
) -> dict[str, str]:
    """Export validation report to JSON and text files.

    Returns dict of {format: path}.
    """
    os.makedirs(output_dir, exist_ok=True)
    paths = {}

    # JSON
    json_path = os.path.join(output_dir, "validation_report.json")
    with open(json_path, "w") as f:
        json.dump(report.to_dict(), f, indent=2, default=str)
    paths["json"] = json_path

    # Text
    text_path = os.path.join(output_dir, "validation_report.txt")
    with open(text_path, "w") as f:
        f.write(format_report_text(report))
    paths["text"] = text_path

    # Scenario config snapshot
    config_path = os.path.join(output_dir, "scenario_configs.json")
    with open(config_path, "w") as f:
        configs = {}
        for sr in report.scenario_results:
            configs[sr["scenario_name"]] = sr
        json.dump(configs, f, indent=2, default=str)
    paths["configs"] = config_path

    logger.info("Report exported to %s", output_dir)
    return paths
