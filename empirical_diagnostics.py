"""Empirical diagnostics: probation/exit analysis, premature-exit detection,
policy comparison, and multi-window aggregation.

All logic is derived from existing ActionOutcome data and replay results.
No new abstractions or frameworks — just structured analysis of real outputs.
"""
from __future__ import annotations

import csv
import logging
import os
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Probation/Exit event records
# ---------------------------------------------------------------------------

@dataclass
class ProbationEvent:
    """A single probation event for a ticker."""
    review_date: date
    ticker: str
    thesis_conviction: float
    action_score: float
    prior_action: str = ""
    prior_conviction: float = 0.0
    followed_by_exit: bool = False
    exit_date: Optional[date] = None
    resolved_to_improvement: bool = False
    forward_5d: Optional[float] = None
    forward_20d: Optional[float] = None
    forward_60d: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "review_date": self.review_date.isoformat(),
            "ticker": self.ticker,
            "thesis_conviction": round(self.thesis_conviction, 1),
            "action_score": round(self.action_score, 1),
            "prior_action": self.prior_action,
            "prior_conviction": round(self.prior_conviction, 1),
            "followed_by_exit": self.followed_by_exit,
            "exit_date": self.exit_date.isoformat() if self.exit_date else "",
            "resolved_to_improvement": self.resolved_to_improvement,
            "forward_5d_pct": round(self.forward_5d, 2) if self.forward_5d is not None else None,
            "forward_20d_pct": round(self.forward_20d, 2) if self.forward_20d is not None else None,
            "forward_60d_pct": round(self.forward_60d, 2) if self.forward_60d is not None else None,
        }


@dataclass
class ExitEvent:
    """A single exit event for a ticker."""
    review_date: date
    ticker: str
    thesis_conviction: float
    action_score: float
    prior_action: str = ""
    prior_conviction: float = 0.0
    preceded_by_probation: bool = False
    probation_date: Optional[date] = None
    forward_5d: Optional[float] = None
    forward_20d: Optional[float] = None
    forward_60d: Optional[float] = None
    # Recovery detection: did the stock recover after exit?
    recovery_20d: bool = False
    recovery_60d: bool = False

    def to_dict(self) -> dict:
        return {
            "review_date": self.review_date.isoformat(),
            "ticker": self.ticker,
            "thesis_conviction": round(self.thesis_conviction, 1),
            "action_score": round(self.action_score, 1),
            "prior_action": self.prior_action,
            "prior_conviction": round(self.prior_conviction, 1),
            "preceded_by_probation": self.preceded_by_probation,
            "probation_date": self.probation_date.isoformat() if self.probation_date else "",
            "forward_5d_pct": round(self.forward_5d, 2) if self.forward_5d is not None else None,
            "forward_20d_pct": round(self.forward_20d, 2) if self.forward_20d is not None else None,
            "forward_60d_pct": round(self.forward_60d, 2) if self.forward_60d is not None else None,
            "premature_exit_20d": self.recovery_20d,
            "premature_exit_60d": self.recovery_60d,
        }


@dataclass
class DeteriorationDiagnostics:
    """Aggregated probation/exit diagnostics."""
    probation_events: list[ProbationEvent] = field(default_factory=list)
    exit_events: list[ExitEvent] = field(default_factory=list)
    # Summary stats
    total_probations: int = 0
    probation_to_exit_count: int = 0
    probation_resolved_count: int = 0
    probation_false_alarm_count: int = 0
    total_exits: int = 0
    premature_exits_20d: int = 0
    premature_exits_60d: int = 0
    avg_exit_forward_20d: Optional[float] = None
    avg_probation_forward_20d: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "total_probations": self.total_probations,
            "probation_to_exit_count": self.probation_to_exit_count,
            "probation_resolved_count": self.probation_resolved_count,
            "probation_false_alarm_count": self.probation_false_alarm_count,
            "total_exits": self.total_exits,
            "premature_exits_20d": self.premature_exits_20d,
            "premature_exits_60d": self.premature_exits_60d,
            "avg_exit_forward_20d_pct": round(self.avg_exit_forward_20d, 2) if self.avg_exit_forward_20d is not None else None,
            "avg_probation_forward_20d_pct": round(self.avg_probation_forward_20d, 2) if self.avg_probation_forward_20d is not None else None,
        }


def compute_deterioration_diagnostics(action_outcomes: list) -> DeteriorationDiagnostics:
    """Extract probation/exit events and compute diagnostics from action outcomes.

    action_outcomes: list of ActionOutcome objects from historical_evaluation.
    """
    diag = DeteriorationDiagnostics()

    # Build per-ticker timeline
    by_ticker: dict[str, list] = defaultdict(list)
    for o in action_outcomes:
        by_ticker[o.ticker].append(o)

    for ticker in sorted(by_ticker.keys()):
        events = sorted(by_ticker[ticker], key=lambda o: o.review_date)

        for i, o in enumerate(events):
            prior = events[i - 1] if i > 0 else None

            if o.action == "probation":
                pe = ProbationEvent(
                    review_date=o.review_date,
                    ticker=o.ticker,
                    thesis_conviction=o.thesis_conviction,
                    action_score=o.action_score,
                    prior_action=prior.action if prior else "",
                    prior_conviction=prior.thesis_conviction if prior else 0.0,
                    forward_5d=o.forward_5d,
                    forward_20d=o.forward_20d,
                    forward_60d=o.forward_60d,
                )

                # Look ahead: did this probation lead to exit?
                for j in range(i + 1, len(events)):
                    if events[j].action == "exit":
                        pe.followed_by_exit = True
                        pe.exit_date = events[j].review_date
                        break
                    if events[j].action not in ("probation", "hold"):
                        # Something else happened (initiate, add) — probation resolved
                        break

                # Did conviction improve after probation?
                if not pe.followed_by_exit and i + 1 < len(events):
                    next_o = events[i + 1]
                    if next_o.thesis_conviction > o.thesis_conviction:
                        pe.resolved_to_improvement = True

                # False alarm: probation but stock went up
                diag.probation_events.append(pe)

            elif o.action == "exit":
                ee = ExitEvent(
                    review_date=o.review_date,
                    ticker=o.ticker,
                    thesis_conviction=o.thesis_conviction,
                    action_score=o.action_score,
                    prior_action=prior.action if prior else "",
                    prior_conviction=prior.thesis_conviction if prior else 0.0,
                    forward_5d=o.forward_5d,
                    forward_20d=o.forward_20d,
                    forward_60d=o.forward_60d,
                )

                # Was this preceded by probation?
                if prior and prior.action == "probation":
                    ee.preceded_by_probation = True
                    ee.probation_date = prior.review_date
                elif i >= 2 and events[i - 2].action == "probation":
                    ee.preceded_by_probation = True
                    ee.probation_date = events[i - 2].review_date

                # Premature exit detection: stock recovered after exit
                if o.forward_20d is not None and o.forward_20d > 5.0:
                    ee.recovery_20d = True
                if o.forward_60d is not None and o.forward_60d > 10.0:
                    ee.recovery_60d = True

                diag.exit_events.append(ee)

    # Compute summary stats
    diag.total_probations = len(diag.probation_events)
    diag.probation_to_exit_count = sum(1 for p in diag.probation_events if p.followed_by_exit)
    diag.probation_resolved_count = sum(1 for p in diag.probation_events if p.resolved_to_improvement)
    # False alarm: probation but 20D forward return was positive (stock went up)
    diag.probation_false_alarm_count = sum(
        1 for p in diag.probation_events
        if p.forward_20d is not None and p.forward_20d > 0 and not p.followed_by_exit
    )

    diag.total_exits = len(diag.exit_events)
    diag.premature_exits_20d = sum(1 for e in diag.exit_events if e.recovery_20d)
    diag.premature_exits_60d = sum(1 for e in diag.exit_events if e.recovery_60d)

    exit_fwd_20 = [e.forward_20d for e in diag.exit_events if e.forward_20d is not None]
    if exit_fwd_20:
        diag.avg_exit_forward_20d = sum(exit_fwd_20) / len(exit_fwd_20)

    prob_fwd_20 = [p.forward_20d for p in diag.probation_events if p.forward_20d is not None]
    if prob_fwd_20:
        diag.avg_probation_forward_20d = sum(prob_fwd_20) / len(prob_fwd_20)

    return diag


# ---------------------------------------------------------------------------
# Enhanced failure analysis
# ---------------------------------------------------------------------------

@dataclass
class EnhancedFailureAnalysis:
    """Extended failure analysis beyond the basic version."""
    premature_exits: list[dict] = field(default_factory=list)
    correct_probation_warnings: list[dict] = field(default_factory=list)
    false_alarm_probations: list[dict] = field(default_factory=list)
    repeated_negative_tickers: list[dict] = field(default_factory=list)
    low_coverage_poor_outcomes: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "premature_exits": self.premature_exits,
            "correct_probation_warnings": self.correct_probation_warnings,
            "false_alarm_probations": self.false_alarm_probations,
            "repeated_negative_tickers": self.repeated_negative_tickers,
            "low_coverage_poor_outcomes": self.low_coverage_poor_outcomes,
        }


def compute_enhanced_failure_analysis(
    action_outcomes: list,
    deterioration_diag: DeteriorationDiagnostics,
    per_name_summary: list = None,
) -> EnhancedFailureAnalysis:
    """Compute enhanced failure analysis from action outcomes and diagnostics."""
    fa = EnhancedFailureAnalysis()

    # 1. Premature exits: exited but stock recovered significantly
    for ee in deterioration_diag.exit_events:
        if ee.recovery_20d or ee.recovery_60d:
            fa.premature_exits.append({
                "review_date": ee.review_date.isoformat(),
                "ticker": ee.ticker,
                "conviction_at_exit": round(ee.thesis_conviction, 1),
                "forward_20d_pct": round(ee.forward_20d, 2) if ee.forward_20d is not None else None,
                "forward_60d_pct": round(ee.forward_60d, 2) if ee.forward_60d is not None else None,
                "preceded_by_probation": ee.preceded_by_probation,
                "concern": f"{ee.ticker} exited at conviction {ee.thesis_conviction:.0f} but recovered "
                           f"{ee.forward_60d:+.1f}% over 60D" if ee.forward_60d else "",
            })

    # 2. Correct probation warnings: probation followed by exit or negative forward returns
    for pe in deterioration_diag.probation_events:
        if pe.followed_by_exit or (pe.forward_20d is not None and pe.forward_20d < -3.0):
            fa.correct_probation_warnings.append({
                "review_date": pe.review_date.isoformat(),
                "ticker": pe.ticker,
                "conviction": round(pe.thesis_conviction, 1),
                "forward_20d_pct": round(pe.forward_20d, 2) if pe.forward_20d is not None else None,
                "followed_by_exit": pe.followed_by_exit,
            })

    # 3. False alarm probations: probation but stock went up
    for pe in deterioration_diag.probation_events:
        if pe.forward_20d is not None and pe.forward_20d > 0 and not pe.followed_by_exit:
            fa.false_alarm_probations.append({
                "review_date": pe.review_date.isoformat(),
                "ticker": pe.ticker,
                "conviction": round(pe.thesis_conviction, 1),
                "forward_20d_pct": round(pe.forward_20d, 2),
            })

    # 4. Repeated negative tickers: names with 2+ negative outcomes
    by_ticker_neg: dict[str, int] = defaultdict(int)
    for o in action_outcomes:
        if o.forward_20d is not None and o.forward_20d < -5.0 and o.action in ("initiate", "add", "hold"):
            by_ticker_neg[o.ticker] += 1
    for ticker, count in sorted(by_ticker_neg.items()):
        if count >= 2:
            fa.repeated_negative_tickers.append({
                "ticker": ticker,
                "negative_outcome_count": count,
            })

    # 5. Low coverage poor outcomes correlation
    if per_name_summary:
        for pns in per_name_summary:
            if hasattr(pns, 'doc_count') and pns.doc_count < 3:
                avg_20d = getattr(pns, 'avg_forward_20d', None)
                if avg_20d is not None and avg_20d < 0:
                    fa.low_coverage_poor_outcomes.append({
                        "ticker": pns.ticker,
                        "doc_count": pns.doc_count,
                        "avg_forward_20d_pct": round(avg_20d, 2),
                    })

    return fa


# ---------------------------------------------------------------------------
# Policy comparison
# ---------------------------------------------------------------------------

@dataclass
class PolicyComparisonResult:
    """Comparison of multiple exit policy variants on the same data."""
    policy_results: dict[str, dict] = field(default_factory=dict)
    # Each key is policy label, value has: return, drawdown, action_counts,
    # probation_count, exit_count, avg_forward_after_exit, premature_exits, etc.

    def to_dict(self) -> dict:
        return {"policy_results": self.policy_results}


def build_policy_comparison(
    policy_eval_results: dict[str, "HistoricalEvalResult"],
    policy_diags: dict[str, DeteriorationDiagnostics],
) -> PolicyComparisonResult:
    """Build comparison table from multiple policy evaluation results."""
    comp = PolicyComparisonResult()

    for label, eval_result in policy_eval_results.items():
        m = eval_result.metrics
        diag = policy_diags.get(label)

        row = {
            "policy": label,
            "return_pct": round(m.total_return_pct, 2) if m else None,
            "annualized_return_pct": round(m.annualized_return_pct, 2) if m and m.annualized_return_pct else None,
            "max_drawdown_pct": round(m.max_drawdown_pct, 2) if m else None,
            "total_actions": sum(eval_result.diagnostics.action_counts.values()) if eval_result.diagnostics else 0,
        }

        # Action counts by type
        if eval_result.diagnostics:
            row["action_counts"] = dict(eval_result.diagnostics.action_counts)
            row["probation_count"] = eval_result.diagnostics.action_counts.get("probation", 0)
            row["exit_count"] = eval_result.diagnostics.action_counts.get("exit", 0)
            row["initiation_count"] = eval_result.diagnostics.action_counts.get("initiate", 0)

        if diag:
            row["premature_exits_20d"] = diag.premature_exits_20d
            row["premature_exits_60d"] = diag.premature_exits_60d
            row["avg_exit_forward_20d_pct"] = round(diag.avg_exit_forward_20d, 2) if diag.avg_exit_forward_20d is not None else None
            row["avg_probation_forward_20d_pct"] = round(diag.avg_probation_forward_20d, 2) if diag.avg_probation_forward_20d is not None else None
            row["probation_false_alarm_count"] = diag.probation_false_alarm_count

        # Best/worst decisions
        if eval_result.best_decisions:
            bd = eval_result.best_decisions[0]
            row["best_decision"] = f"{bd['review_date']} {bd['ticker']} {bd['action']}"
        if eval_result.worst_decisions:
            wd = eval_result.worst_decisions[0]
            row["worst_decision"] = f"{wd['review_date']} {wd['ticker']} {wd['action']}"

        comp.policy_results[label] = row

    return comp


# ---------------------------------------------------------------------------
# Multi-window aggregation
# ---------------------------------------------------------------------------

@dataclass
class WindowResult:
    """Result from a single evaluation window."""
    window_label: str
    start_date: date
    end_date: date
    return_pct: Optional[float] = None
    annualized_return_pct: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    total_actions: int = 0
    initiation_count: int = 0
    exit_count: int = 0
    probation_count: int = 0
    premature_exits: int = 0

    def to_dict(self) -> dict:
        return {
            "window": self.window_label,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "return_pct": round(self.return_pct, 2) if self.return_pct is not None else None,
            "annualized_return_pct": round(self.annualized_return_pct, 2) if self.annualized_return_pct is not None else None,
            "max_drawdown_pct": round(self.max_drawdown_pct, 2) if self.max_drawdown_pct is not None else None,
            "total_actions": self.total_actions,
            "initiation_count": self.initiation_count,
            "exit_count": self.exit_count,
            "probation_count": self.probation_count,
            "premature_exits": self.premature_exits,
        }


@dataclass
class MultiWindowResult:
    """Aggregated results across multiple evaluation windows."""
    windows: list[WindowResult] = field(default_factory=list)
    aggregate: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "windows": [w.to_dict() for w in self.windows],
            "aggregate": self.aggregate,
            "warnings": self.warnings,
        }


def aggregate_multi_window(window_results: list[WindowResult]) -> MultiWindowResult:
    """Aggregate results across multiple windows and flag instability."""
    mw = MultiWindowResult(windows=window_results)

    if not window_results:
        mw.warnings.append("No windows to aggregate")
        return mw

    returns = [w.return_pct for w in window_results if w.return_pct is not None]
    drawdowns = [w.max_drawdown_pct for w in window_results if w.max_drawdown_pct is not None]

    if returns:
        mw.aggregate["avg_return_pct"] = round(sum(returns) / len(returns), 2)
        mw.aggregate["min_return_pct"] = round(min(returns), 2)
        mw.aggregate["max_return_pct"] = round(max(returns), 2)
        mw.aggregate["return_spread_pct"] = round(max(returns) - min(returns), 2)

        # Flag instability: if return spread > 10% or sign changes
        if max(returns) - min(returns) > 10.0:
            mw.warnings.append(
                f"High return spread across windows: {max(returns) - min(returns):.1f}% "
                f"— conclusions may be unstable"
            )
        if min(returns) < 0 and max(returns) > 0:
            mw.warnings.append(
                "Returns change sign across windows — positive result is not robust"
            )

    if drawdowns:
        mw.aggregate["avg_drawdown_pct"] = round(sum(drawdowns) / len(drawdowns), 2)
        mw.aggregate["max_drawdown_pct"] = round(max(drawdowns), 2)

    total_actions = sum(w.total_actions for w in window_results)
    mw.aggregate["total_actions"] = total_actions
    mw.aggregate["total_exits"] = sum(w.exit_count for w in window_results)
    mw.aggregate["total_probations"] = sum(w.probation_count for w in window_results)
    mw.aggregate["total_premature_exits"] = sum(w.premature_exits for w in window_results)
    mw.aggregate["windows_count"] = len(window_results)

    if len(window_results) < 3:
        mw.warnings.append(
            f"Only {len(window_results)} window(s) — sample too small for robust conclusions"
        )

    return mw


# ---------------------------------------------------------------------------
# CSV writers
# ---------------------------------------------------------------------------

def write_probation_events_csv(output_dir: str, events: list[ProbationEvent]) -> None:
    path = os.path.join(output_dir, "probation_events.csv")
    fieldnames = [
        "review_date", "ticker", "thesis_conviction", "action_score",
        "prior_action", "prior_conviction",
        "followed_by_exit", "exit_date", "resolved_to_improvement",
        "forward_5d_pct", "forward_20d_pct", "forward_60d_pct",
    ]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for e in events:
            writer.writerow(e.to_dict())
    logger.info("Probation events CSV: %s (%d rows)", path, len(events))


def write_exit_events_csv(output_dir: str, events: list[ExitEvent]) -> None:
    path = os.path.join(output_dir, "exit_events.csv")
    fieldnames = [
        "review_date", "ticker", "thesis_conviction", "action_score",
        "prior_action", "prior_conviction",
        "preceded_by_probation", "probation_date",
        "forward_5d_pct", "forward_20d_pct", "forward_60d_pct",
        "premature_exit_20d", "premature_exit_60d",
    ]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for e in events:
            writer.writerow(e.to_dict())
    logger.info("Exit events CSV: %s (%d rows)", path, len(events))


def write_policy_comparison_csv(output_dir: str, comparison: PolicyComparisonResult) -> None:
    path = os.path.join(output_dir, "policy_comparison.csv")
    fieldnames = [
        "policy", "return_pct", "annualized_return_pct", "max_drawdown_pct",
        "total_actions", "initiation_count", "exit_count", "probation_count",
        "premature_exits_20d", "premature_exits_60d",
        "avg_exit_forward_20d_pct", "avg_probation_forward_20d_pct",
        "probation_false_alarm_count",
        "best_decision", "worst_decision",
    ]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for label in sorted(comparison.policy_results.keys()):
            row = comparison.policy_results[label]
            writer.writerow(row)
    logger.info("Policy comparison CSV: %s", path)


def write_window_summary_csv(output_dir: str, mw: MultiWindowResult) -> None:
    path = os.path.join(output_dir, "window_summary.csv")
    fieldnames = [
        "window", "start_date", "end_date",
        "return_pct", "annualized_return_pct", "max_drawdown_pct",
        "total_actions", "initiation_count", "exit_count",
        "probation_count", "premature_exits",
    ]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for w in mw.windows:
            writer.writerow(w.to_dict())
    logger.info("Window summary CSV: %s (%d windows)", path, len(mw.windows))


# ---------------------------------------------------------------------------
# Markdown report sections
# ---------------------------------------------------------------------------

def format_deterioration_section(diag: DeteriorationDiagnostics) -> list[str]:
    """Generate markdown lines for the probation/exit diagnostics section."""
    lines = []
    lines.append("## Probation/Exit Diagnostics")
    lines.append("")
    lines.append("### Summary")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Total probations | {diag.total_probations} |")
    lines.append(f"| Probation -> exit | {diag.probation_to_exit_count} |")
    lines.append(f"| Probation resolved (improvement) | {diag.probation_resolved_count} |")
    lines.append(f"| Probation false alarms | {diag.probation_false_alarm_count} |")
    lines.append(f"| Total exits | {diag.total_exits} |")
    lines.append(f"| Premature exits (20D recovery >5%) | {diag.premature_exits_20d} |")
    lines.append(f"| Premature exits (60D recovery >10%) | {diag.premature_exits_60d} |")
    if diag.avg_exit_forward_20d is not None:
        lines.append(f"| Avg forward 20D after exit | {diag.avg_exit_forward_20d:+.2f}% |")
    if diag.avg_probation_forward_20d is not None:
        lines.append(f"| Avg forward 20D after probation | {diag.avg_probation_forward_20d:+.2f}% |")
    lines.append("")

    if diag.exit_events:
        lines.append("### Exit Events")
        lines.append("| Date | Ticker | Conviction | Prior Action | Probation? | 5D | 20D | 60D | Premature? |")
        lines.append("|------|--------|------------|--------------|------------|-----|------|------|------------|")
        for e in diag.exit_events:
            f5 = f"{e.forward_5d:+.2f}%" if e.forward_5d is not None else "-"
            f20 = f"{e.forward_20d:+.2f}%" if e.forward_20d is not None else "-"
            f60 = f"{e.forward_60d:+.2f}%" if e.forward_60d is not None else "-"
            premature = "YES" if e.recovery_20d or e.recovery_60d else ""
            lines.append(
                f"| {e.review_date} | {e.ticker} | {e.thesis_conviction:.0f} | "
                f"{e.prior_action} | {'yes' if e.preceded_by_probation else 'no'} | "
                f"{f5} | {f20} | {f60} | {premature} |"
            )
        lines.append("")

    if diag.probation_events:
        lines.append("### Probation Events")
        lines.append("| Date | Ticker | Conviction | Prior Action | Led to Exit? | Resolved? | 20D |")
        lines.append("|------|--------|------------|--------------|-------------|-----------|------|")
        for p in diag.probation_events:
            f20 = f"{p.forward_20d:+.2f}%" if p.forward_20d is not None else "-"
            lines.append(
                f"| {p.review_date} | {p.ticker} | {p.thesis_conviction:.0f} | "
                f"{p.prior_action} | {'yes' if p.followed_by_exit else 'no'} | "
                f"{'yes' if p.resolved_to_improvement else 'no'} | {f20} |"
            )
        lines.append("")

    return lines


def format_enhanced_failure_section(efa: EnhancedFailureAnalysis) -> list[str]:
    """Generate markdown for enhanced failure analysis."""
    lines = []
    has_content = (
        efa.premature_exits or efa.correct_probation_warnings or
        efa.false_alarm_probations or efa.repeated_negative_tickers or
        efa.low_coverage_poor_outcomes
    )
    if not has_content:
        return lines

    lines.append("## Enhanced Failure Analysis")
    lines.append("")

    if efa.premature_exits:
        lines.append("### Premature Exits (stock recovered after exit)")
        for pe in efa.premature_exits:
            f60 = f"{pe['forward_60d_pct']:+.2f}%" if pe.get('forward_60d_pct') is not None else "N/A"
            lines.append(f"- **{pe['ticker']}** exited {pe['review_date']} at conviction {pe['conviction_at_exit']}, recovered {f60} over 60D")
        lines.append("")

    if efa.correct_probation_warnings:
        lines.append(f"### Correct Probation Warnings ({len(efa.correct_probation_warnings)})")
        lines.append("Probation events that correctly predicted deterioration or led to exit.")
        lines.append("")

    if efa.false_alarm_probations:
        lines.append(f"### False Alarm Probations ({len(efa.false_alarm_probations)})")
        lines.append("Probation events where the stock subsequently rose.")
        lines.append("")

    if efa.repeated_negative_tickers:
        lines.append("### Repeatedly Negative Tickers")
        for rn in efa.repeated_negative_tickers:
            lines.append(f"- **{rn['ticker']}**: {rn['negative_outcome_count']} actions with >5% loss at 20D")
        lines.append("")

    return lines


def format_policy_comparison_section(comparison: PolicyComparisonResult) -> list[str]:
    """Generate markdown for policy comparison."""
    lines = []
    if not comparison.policy_results:
        return lines

    lines.append("## Exit Policy Comparison")
    lines.append("")
    lines.append("| Policy | Return | Drawdown | Exits | Probations | Premature Exits (60D) | Avg Exit 20D |")
    lines.append("|--------|--------|----------|-------|------------|----------------------|-------------|")
    for label in sorted(comparison.policy_results.keys()):
        r = comparison.policy_results[label]
        ret = f"{r['return_pct']:+.2f}%" if r.get('return_pct') is not None else "N/A"
        dd = f"{r['max_drawdown_pct']:.2f}%" if r.get('max_drawdown_pct') is not None else "N/A"
        exits = r.get('exit_count', 0)
        probs = r.get('probation_count', 0)
        prem = r.get('premature_exits_60d', 0)
        avg_exit = f"{r['avg_exit_forward_20d_pct']:+.2f}%" if r.get('avg_exit_forward_20d_pct') is not None else "N/A"
        lines.append(f"| {label} | {ret} | {dd} | {exits} | {probs} | {prem} | {avg_exit} |")
    lines.append("")

    return lines


def format_multi_window_section(mw: MultiWindowResult) -> list[str]:
    """Generate markdown for multi-window summary."""
    lines = []
    if not mw.windows:
        return lines

    lines.append("## Multi-Window Summary")
    lines.append("")
    lines.append("| Window | Dates | Return | Drawdown | Actions | Exits | Premature |")
    lines.append("|--------|-------|--------|----------|---------|-------|-----------|")
    for w in mw.windows:
        ret = f"{w.return_pct:+.2f}%" if w.return_pct is not None else "N/A"
        dd = f"{w.max_drawdown_pct:.2f}%" if w.max_drawdown_pct is not None else "N/A"
        lines.append(
            f"| {w.window_label} | {w.start_date} to {w.end_date} | "
            f"{ret} | {dd} | {w.total_actions} | {w.exit_count} | {w.premature_exits} |"
        )
    lines.append("")

    if mw.aggregate:
        lines.append("### Aggregate")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        for k, v in sorted(mw.aggregate.items()):
            lines.append(f"| {k} | {v} |")
        lines.append("")

    if mw.warnings:
        lines.append("### Stability Warnings")
        for w in mw.warnings:
            lines.append(f"- {w}")
        lines.append("")

    return lines
