"""Historical evaluation config: bounded configuration for historical proof runs.

Supports:
- Universe selection (full or subset)
- Date range for backfill and evaluation
- Source toggles (which connectors to use)
- Backfill-only vs full regeneration vs evaluate-only modes
- Rebuild from scratch vs incremental continuation
- Forward-return measurement horizons
- Memory ablation toggle
- Deterministic run ID and output paths
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


class HistoricalRunMode:
    """Run mode constants."""
    BACKFILL_ONLY = "backfill_only"          # fetch historical data, no thesis regeneration
    REGENERATE = "regenerate"                 # backfill + thesis regeneration + evaluation
    EVALUATE_ONLY = "evaluate_only"           # evaluate on existing regenerated state
    MEMORY_ABLATION = "memory_ablation"       # run regeneration twice: memory ON vs OFF
    USEFULNESS_RUN = "usefulness_run"         # bounded real usefulness test with diagnostics


@dataclass
class HistoricalEvalConfig:
    """Configuration for a historical proof run.

    All fields have sensible defaults for a bounded, repeatable run.
    """
    # --- Run identity ---
    run_id: str = "historical_default"
    run_label: str = ""

    # --- Mode ---
    mode: str = HistoricalRunMode.REGENERATE

    # --- Universe ---
    tickers: list[str] = field(default_factory=list)  # empty = full UNIVERSE_TICKERS

    # --- Date range ---
    backfill_start: date = date(2024, 1, 1)
    backfill_end: date = date(2025, 1, 1)
    eval_start: date = date(2024, 3, 1)       # evaluation starts after backfill warmup
    eval_end: date = date(2025, 1, 1)

    # --- Review cadence ---
    cadence_days: int = 7                       # weekly review

    # --- Source toggles ---
    backfill_prices: bool = True
    backfill_sec_filings: bool = True
    backfill_news_rss: bool = True
    backfill_pr_rss: bool = True

    # --- Thesis regeneration ---
    rebuild_from_scratch: bool = True           # True = clean DB, False = incremental
    use_llm: bool = False                       # stub mode by default

    # --- Portfolio ---
    initial_cash: float = 1_000_000.0
    transaction_cost_bps: float = 10.0
    apply_trades: bool = True
    strict_replay: bool = False

    # --- Forward-return horizons ---
    forward_return_days: list[int] = field(default_factory=lambda: [5, 20, 60])

    # --- Conviction buckets ---
    conviction_buckets: list[tuple[float, float, str]] = field(
        default_factory=lambda: [
            (0, 40, "low"),
            (40, 65, "medium"),
            (65, 100, "high"),
        ]
    )

    # --- Memory ablation ---
    memory_enabled: bool = True

    # --- Benchmark ---
    benchmark_ticker: str = "SPY"
    include_equal_weight_baseline: bool = True

    # --- Output ---
    output_dir: str = "historical_proof_runs"

    # --- Determinism ---
    seed: int = 42

    def effective_tickers(self) -> list[str]:
        """Return the ticker list to use.

        Falls back to proof universe for usefulness runs, full universe otherwise.
        """
        if self.tickers:
            return list(self.tickers)
        if self.mode == HistoricalRunMode.USEFULNESS_RUN:
            from proof_universe import PROOF_UNIVERSE_TICKERS
            return list(PROOF_UNIVERSE_TICKERS)
        from source_registry import UNIVERSE_TICKERS
        return list(UNIVERSE_TICKERS)

    def is_usefulness_run(self) -> bool:
        """Whether this is a real usefulness testing run."""
        return self.mode == HistoricalRunMode.USEFULNESS_RUN

    def extractor_mode_label(self) -> str:
        """Human-readable label for the extraction mode."""
        return "real_llm" if self.use_llm else "stub_heuristic"

    def validate_for_usefulness_run(self) -> list[str]:
        """Check config for usefulness run readiness. Returns list of warnings."""
        warnings = []
        if not self.use_llm:
            warnings.append(
                "DEGRADED: Running usefulness test with stub extractor. "
                "Results reflect heuristic claim extraction, not real LLM analysis. "
                "Pass --use-llm for real extraction."
            )
        if not self.backfill_sec_filings:
            warnings.append("SEC filings disabled — primary evidence source missing")
        if not self.backfill_prices:
            warnings.append("Price backfill disabled — forward returns will be unavailable")
        tickers = self.effective_tickers()
        if len(tickers) > 25:
            warnings.append(
                f"Universe has {len(tickers)} tickers — consider narrowing for inspectable results"
            )
        return warnings

    def conviction_bucket_for(self, score: float) -> str:
        """Return the bucket label for a conviction score."""
        for low, high, label in self.conviction_buckets:
            if low <= score < high:
                return label
        return "high"  # scores at 100

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "run_label": self.run_label,
            "mode": self.mode,
            "tickers": self.effective_tickers(),
            "backfill_start": self.backfill_start.isoformat(),
            "backfill_end": self.backfill_end.isoformat(),
            "eval_start": self.eval_start.isoformat(),
            "eval_end": self.eval_end.isoformat(),
            "cadence_days": self.cadence_days,
            "backfill_prices": self.backfill_prices,
            "backfill_sec_filings": self.backfill_sec_filings,
            "backfill_news_rss": self.backfill_news_rss,
            "backfill_pr_rss": self.backfill_pr_rss,
            "rebuild_from_scratch": self.rebuild_from_scratch,
            "use_llm": self.use_llm,
            "extractor_mode": self.extractor_mode_label(),
            "initial_cash": self.initial_cash,
            "transaction_cost_bps": self.transaction_cost_bps,
            "strict_replay": self.strict_replay,
            "forward_return_days": self.forward_return_days,
            "memory_enabled": self.memory_enabled,
            "benchmark_ticker": self.benchmark_ticker,
            "output_dir": self.output_dir,
            "seed": self.seed,
        }

    @staticmethod
    def memory_ablation_pair(
        *,
        tickers: list[str] | None = None,
        backfill_start: date = date(2024, 1, 1),
        backfill_end: date = date(2025, 1, 1),
        eval_start: date = date(2024, 3, 1),
        eval_end: date = date(2025, 1, 1),
        cadence_days: int = 7,
    ) -> tuple[HistoricalEvalConfig, HistoricalEvalConfig]:
        """Create matched pair for memory-on vs memory-off historical ablation."""
        base = dict(
            tickers=tickers or [],
            backfill_start=backfill_start,
            backfill_end=backfill_end,
            eval_start=eval_start,
            eval_end=eval_end,
            cadence_days=cadence_days,
            mode=HistoricalRunMode.MEMORY_ABLATION,
        )
        config_on = HistoricalEvalConfig(
            run_id="historical_memory_on",
            run_label="Historical regeneration: memory ON",
            memory_enabled=True,
            **base,
        )
        config_off = HistoricalEvalConfig(
            run_id="historical_memory_off",
            run_label="Historical regeneration: memory OFF",
            memory_enabled=False,
            **base,
        )
        return config_on, config_off

    @staticmethod
    def usefulness_run_config(
        *,
        tickers: list[str] | None = None,
        backfill_start: date = date(2024, 6, 1),
        backfill_end: date = date(2025, 1, 1),
        eval_start: date | None = None,
        cadence_days: int = 7,
        use_llm: bool = False,
        output_dir: str = "historical_proof_runs",
        run_id: str = "usefulness_run",
    ) -> HistoricalEvalConfig:
        """Create config for a bounded real usefulness test.

        Uses the narrow proof universe by default (15 names).
        """
        import datetime as dt
        if eval_start is None:
            eval_start = backfill_start + dt.timedelta(days=60)

        return HistoricalEvalConfig(
            run_id=run_id,
            run_label=f"Usefulness run: {backfill_start} to {backfill_end}",
            mode=HistoricalRunMode.USEFULNESS_RUN,
            tickers=tickers or [],
            backfill_start=backfill_start,
            backfill_end=backfill_end,
            eval_start=eval_start,
            eval_end=backfill_end,
            cadence_days=cadence_days,
            use_llm=use_llm,
            output_dir=output_dir,
        )
