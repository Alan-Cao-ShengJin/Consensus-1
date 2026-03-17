"""yfinance ticker info updater: enriches the companies table with sector/industry/etc."""
from __future__ import annotations

import logging

from connectors.base import NonDocumentUpdater, NonDocumentResult

logger = logging.getLogger(__name__)


class YFinanceTickerInfoUpdater(NonDocumentUpdater):
    """Fetches company info via yfinance and enriches the companies table."""

    @property
    def source_key(self) -> str:
        return "ticker_master"

    def update(self, session, ticker: str, days: int = 0, dry_run: bool = False) -> NonDocumentResult:
        result = NonDocumentResult(source_key=self.source_key, ticker=ticker)

        try:
            import yfinance as yf
        except ImportError:
            result.errors.append("yfinance not installed; pip install yfinance")
            return result

        try:
            tk = yf.Ticker(ticker)
            info = tk.info or {}
        except Exception as e:
            result.errors.append(f"yfinance info fetch failed: {e}")
            return result

        if not info:
            logger.info("yfinance ticker info: no data for %s", ticker)
            return result

        enrichment = {}
        if info.get("sector"):
            enrichment["sector"] = info["sector"]
        if info.get("industry"):
            enrichment["industry"] = info["industry"]
        if info.get("country"):
            enrichment["country"] = info["country"]
        if info.get("exchange"):
            enrichment["primary_exchange"] = info["exchange"]
        if info.get("longName") or info.get("shortName"):
            enrichment["name"] = info.get("longName") or info.get("shortName")
        if info.get("beta") is not None:
            enrichment["beta"] = info["beta"]

        # Market cap bucket
        mc = info.get("marketCap")
        if mc:
            if mc >= 200_000_000_000:
                enrichment["market_cap_bucket"] = "mega"
            elif mc >= 10_000_000_000:
                enrichment["market_cap_bucket"] = "large"
            elif mc >= 2_000_000_000:
                enrichment["market_cap_bucket"] = "mid"
            else:
                enrichment["market_cap_bucket"] = "small"

        if not enrichment:
            return result

        if dry_run:
            result.rows_upserted = 1
            logger.info("yfinance ticker info [DRY RUN]: would enrich %s with %s", ticker, list(enrichment.keys()))
            return result

        from company_enrichment_service import enrich_company
        updated = enrich_company(session, ticker, enrichment)
        result.rows_upserted = 1 if updated else 0

        logger.info("yfinance ticker info: enriched %s (%d fields)", ticker, len(enrichment))
        return result
