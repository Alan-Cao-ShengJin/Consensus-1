"""Exit policy variants for empirical comparison.

Three bounded, explicit policies:

  baseline  — Current policy. Conviction <= 25 -> immediate exit.
              Probation after 2 reviews -> forced exit.
  patient   — Extend probation to 3 reviews. Exit conviction threshold
              lowered to 20. Gives deteriorating names more time.
  graduated — Distinguish sharp vs moderate deterioration.
              Sharp conviction drop (>15pts in one review) -> immediate exit.
              Moderate -> probation with 2-review window (same as baseline).
              This tests whether exit timing should depend on *speed* of decline.

All policies are deterministic and inspectable.
"""
from __future__ import annotations

from enum import Enum
from dataclasses import dataclass


class ExitPolicyMode(str, Enum):
    BASELINE = "baseline"
    PATIENT = "patient"
    GRADUATED = "graduated"


@dataclass(frozen=True)
class ExitPolicyConfig:
    """Fully explicit exit policy parameters."""
    mode: ExitPolicyMode = ExitPolicyMode.BASELINE

    # conviction threshold for immediate exit
    exit_conviction_ceiling: float = 25.0
    # conviction threshold for probation entry
    probation_conviction_ceiling: float = 35.0
    # max reviews on probation before forced exit
    probation_max_reviews: int = 2
    # conviction improvement needed to leave probation
    probation_improvement_delta: float = 3.0
    # graduated-mode: conviction drop per review that triggers immediate exit
    sharp_drop_threshold: float = 15.0

    def label(self) -> str:
        return self.mode.value


# Pre-built configs for the three variants
BASELINE_POLICY = ExitPolicyConfig(
    mode=ExitPolicyMode.BASELINE,
    exit_conviction_ceiling=25.0,
    probation_conviction_ceiling=35.0,
    probation_max_reviews=2,
    probation_improvement_delta=3.0,
)

PATIENT_POLICY = ExitPolicyConfig(
    mode=ExitPolicyMode.PATIENT,
    exit_conviction_ceiling=20.0,
    probation_conviction_ceiling=35.0,
    probation_max_reviews=3,
    probation_improvement_delta=3.0,
)

GRADUATED_POLICY = ExitPolicyConfig(
    mode=ExitPolicyMode.GRADUATED,
    exit_conviction_ceiling=25.0,
    probation_conviction_ceiling=35.0,
    probation_max_reviews=2,
    probation_improvement_delta=3.0,
    sharp_drop_threshold=15.0,
)


ALL_POLICIES = [BASELINE_POLICY, PATIENT_POLICY, GRADUATED_POLICY]


def get_policy(name: str) -> ExitPolicyConfig:
    """Get a policy config by name."""
    try:
        mode = ExitPolicyMode(name)
    except ValueError:
        raise ValueError(f"Unknown exit policy: {name!r}. Choose from: {[p.value for p in ExitPolicyMode]}")
    for p in ALL_POLICIES:
        if p.mode == mode:
            return p
    raise ValueError(f"No config for policy {name!r}")
