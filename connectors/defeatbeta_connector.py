"""DefeatBeta connector: free earnings call transcripts from HuggingFace parquet.

No API key required. Data sourced from:
  https://huggingface.co/datasets/defeatbeta/yahoo-finance-data

Uses DuckDB to query remote parquet files directly.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from models import SourceType, SourceTier
from connectors.base import DocumentConnector, DocumentPayload

logger = logging.getLogger(__name__)

PARQUET_URL = (
    "https://huggingface.co/datasets/defeatbeta/yahoo-finance-data"
    "/resolve/main/data/stock_earning_call_transcripts.parquet"
)


def _query_transcripts(ticker: str, days: int = 365) -> list[dict]:
    """Query parquet file for transcripts matching ticker and date range."""
    try:
        import duckdb
    except ImportError:
        logger.warning("duckdb not installed — DefeatBeta connector unavailable")
        return []

    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")

    try:
        conn = duckdb.connect(config={"custom_user_agent": "ConsensusEngine/1.0"})
        conn.execute("INSTALL httpfs; LOAD httpfs;")

        rows = conn.execute(
            f"""
            SELECT symbol, fiscal_year, fiscal_quarter, report_date, transcripts
            FROM '{PARQUET_URL}'
            WHERE symbol = $1
              AND report_date >= $2
            ORDER BY report_date DESC
            """,
            [ticker, cutoff],
        ).fetchall()

        results = []
        for row in rows:
            paragraphs = []
            for item in (row[4] or []):
                speaker = item.get("speaker", "") or item["speaker"] if isinstance(item, dict) else item[1]
                content = item.get("content", "") or item["content"] if isinstance(item, dict) else item[2]
                paragraphs.append({"speaker": speaker, "content": content})

            results.append({
                "symbol": row[0],
                "fiscal_year": row[1],
                "fiscal_quarter": row[2],
                "report_date": row[3],
                "paragraphs": paragraphs,
            })

        conn.close()
        return results

    except Exception as e:
        logger.error("DefeatBeta parquet query failed for %s: %s", ticker, e)
        return []


class DefeatBetaTranscriptConnector(DocumentConnector):
    """Fetches free earnings call transcripts from HuggingFace parquet data.

    No API key required. Covers a wide range of US stocks.
    Transcripts include speaker-attributed paragraphs from earnings calls.
    """

    def __init__(self):
        self._available = None

    @property
    def source_key(self) -> str:
        return "earnings_transcript_defeatbeta"

    @property
    def available(self) -> bool:
        if self._available is None:
            try:
                import duckdb  # noqa: F401
                self._available = True
            except ImportError:
                self._available = False
        return self._available

    def fetch(self, ticker: str, days: int = 365) -> list[DocumentPayload]:
        if not self.available:
            return []

        rows = _query_transcripts(ticker, days=days)
        if not rows:
            logger.info("DefeatBeta: no transcripts for %s (days=%d)", ticker, days)
            return []

        payloads = []
        for row in rows:
            date_str = row["report_date"]
            try:
                published = datetime.strptime(date_str[:10], "%Y-%m-%d")
            except (ValueError, AttributeError):
                continue

            fy = row["fiscal_year"]
            fq = row["fiscal_quarter"]
            paragraphs = row["paragraphs"]

            # Build readable transcript text
            lines = [
                f"{ticker} Earnings Call Transcript — FY{fy} Q{fq}",
                "=" * 60,
                f"Date: {date_str}",
                "",
            ]

            for p in paragraphs:
                speaker = (p.get("speaker") or "").strip()
                content = (p.get("content") or "").strip()
                if not content:
                    continue
                if speaker:
                    lines.append(f"[{speaker}]: {content}")
                else:
                    lines.append(content)
                lines.append("")

            raw_text = "\n".join(lines)
            external_id = f"{ticker}_transcript_FY{fy}_Q{fq}"

            payloads.append(DocumentPayload(
                source_key=self.source_key,
                source_type=SourceType.EARNINGS_TRANSCRIPT,
                source_tier=SourceTier.TIER_1,
                ticker=ticker,
                title=f"{ticker} Earnings Call — FY{fy} Q{fq}",
                url=None,
                published_at=published,
                author="DefeatBeta/Yahoo Finance",
                external_id=external_id,
                raw_text=raw_text,
                metadata={
                    "fiscal_year": fy,
                    "fiscal_quarter": fq,
                    "num_paragraphs": len(paragraphs),
                    "source": "defeatbeta_huggingface",
                },
            ))

        logger.info(
            "DefeatBeta: fetched %d transcripts for %s (days=%d)",
            len(payloads), ticker, days,
        )
        return payloads
