"""Financial Modeling Prep (FMP) connectors.

Two connectors (stable API):
  1. FMPFinancialsConnector  — income statement / balance sheet / cash flow (Tier 1)
  2. FMPEstimatesConnector   — analyst consensus estimates with beat/miss (Tier 2)

FMPTranscriptConnector is kept but requires a higher-tier FMP plan.

All require FMP_API_KEY env var.  Uses the /stable/ API base.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta
from typing import Optional

import requests
from dotenv import load_dotenv
from sqlalchemy import select

load_dotenv()

from models import SourceType, SourceTier
from connectors.base import DocumentConnector, DocumentPayload

logger = logging.getLogger(__name__)

FMP_BASE = "https://financialmodelingprep.com/stable"


def _fmp_api_key() -> str:
    return os.getenv("FMP_API_KEY", "")


def _fmp_get(path: str, params: dict | None = None, timeout: int = 30) -> list | dict | None:
    """Make a GET request to FMP API. Returns parsed JSON or None on error."""
    api_key = _fmp_api_key()
    if not api_key:
        return None
    if params is None:
        params = {}
    params["apikey"] = api_key

    try:
        resp = requests.get(f"{FMP_BASE}{path}", params=params, timeout=timeout)
        if resp.status_code == 402:
            logger.info("FMP endpoint %s requires higher plan tier, skipping", path)
            return None
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error("FMP request failed: %s %s: %s", path, params, e)
        return None


# ---------------------------------------------------------------------------
# 1. Earnings Transcripts
# ---------------------------------------------------------------------------

class FMPTranscriptConnector(DocumentConnector):
    """Fetches earnings call transcripts from FMP.

    Requires a higher-tier FMP plan (Professional or above).
    Uses stable API: /earning-call-transcript?symbol={symbol}
    """

    def __init__(self):
        self._api_key = _fmp_api_key()

    @property
    def source_key(self) -> str:
        return "earnings_transcript_fmp"

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def fetch(self, ticker: str, days: int = 365) -> list[DocumentPayload]:
        if not self._api_key:
            return []

        # Get list of available transcripts
        data = _fmp_get("/earning-call-transcript", {"symbol": ticker})
        if not data or not isinstance(data, list):
            logger.info("FMP transcripts: no data for %s", ticker)
            return []

        cutoff = datetime.utcnow() - timedelta(days=days)
        payloads = []

        for item in data:
            date_str = item.get("date", "")
            try:
                published = datetime.fromisoformat(date_str.replace("Z", "+00:00")).replace(tzinfo=None)
            except (ValueError, AttributeError):
                try:
                    published = datetime.strptime(date_str[:10], "%Y-%m-%d")
                except (ValueError, AttributeError):
                    published = None

            if published and published < cutoff:
                continue

            quarter = item.get("quarter", "")
            year = item.get("year", "")
            content = item.get("content", "")

            if not content or len(content) < 100:
                continue

            external_id = f"{ticker}_transcript_Q{quarter}_{year}"

            payloads.append(DocumentPayload(
                source_key=self.source_key,
                source_type=SourceType.EARNINGS_TRANSCRIPT,
                source_tier=SourceTier.TIER_1,
                ticker=ticker,
                title=f"{ticker} Q{quarter} {year} Earnings Call Transcript",
                url=None,
                published_at=published,
                author="Company Management",
                external_id=external_id,
                raw_text=content,
                metadata={
                    "quarter": quarter,
                    "year": year,
                    "symbol": item.get("symbol", ticker),
                },
            ))

        logger.info("FMP transcripts: fetched %d for %s (days=%d)", len(payloads), ticker, days)
        return payloads


# ---------------------------------------------------------------------------
# 2. Structured Financial Statements
# ---------------------------------------------------------------------------

def _format_financial_summary(
    ticker: str,
    period: str,
    income: dict,
    balance: dict | None,
    cashflow: dict | None,
) -> str:
    """Convert structured financial JSON into readable text for claim extraction."""
    lines = [f"{ticker} {period} Financial Summary"]
    lines.append("=" * 50)

    # Income statement
    rev = income.get("revenue")
    gp = income.get("grossProfit")
    oi = income.get("operatingIncome")
    ni = income.get("netIncome")
    eps = income.get("epsDiluted") or income.get("epsdiluted") or income.get("eps")
    ebitda = income.get("ebitda")

    if rev is not None:
        lines.append(f"Revenue: ${rev / 1e9:.2f}B")
    if gp is not None and rev:
        gm = gp / rev * 100
        lines.append(f"Gross Profit: ${gp / 1e9:.2f}B (margin {gm:.1f}%)")
    if oi is not None and rev:
        om = oi / rev * 100
        lines.append(f"Operating Income: ${oi / 1e9:.2f}B (margin {om:.1f}%)")
    if ni is not None:
        lines.append(f"Net Income: ${ni / 1e9:.2f}B")
    if eps is not None:
        lines.append(f"EPS (diluted): ${eps:.2f}")
    if ebitda is not None:
        lines.append(f"EBITDA: ${ebitda / 1e9:.2f}B")

    # Revenue growth (if we have prior period data in the same response)
    rev_growth = income.get("revenueGrowth")
    if rev_growth is not None:
        lines.append(f"Revenue Growth: {rev_growth * 100:.1f}%")

    # Balance sheet
    if balance:
        total_assets = balance.get("totalAssets")
        total_debt = balance.get("totalDebt")
        cash = balance.get("cashAndCashEquivalents") or balance.get("cashAndShortTermInvestments")
        if total_assets:
            lines.append(f"Total Assets: ${total_assets / 1e9:.2f}B")
        if total_debt:
            lines.append(f"Total Debt: ${total_debt / 1e9:.2f}B")
        if cash:
            lines.append(f"Cash & Equivalents: ${cash / 1e9:.2f}B")
        if total_debt and cash:
            net_debt = total_debt - cash
            lines.append(f"Net Debt: ${net_debt / 1e9:.2f}B")

    # Cash flow
    if cashflow:
        ocf = cashflow.get("operatingCashFlow")
        capex = cashflow.get("capitalExpenditure")
        fcf = cashflow.get("freeCashFlow")
        dividends = cashflow.get("dividendsPaid")
        buybacks = cashflow.get("commonStockRepurchased")
        if ocf:
            lines.append(f"Operating Cash Flow: ${ocf / 1e9:.2f}B")
        if fcf:
            lines.append(f"Free Cash Flow: ${fcf / 1e9:.2f}B")
        elif ocf and capex:
            fcf_calc = ocf + capex  # capex is negative
            lines.append(f"Free Cash Flow: ${fcf_calc / 1e9:.2f}B")
        if dividends:
            lines.append(f"Dividends Paid: ${abs(dividends) / 1e9:.2f}B")
        if buybacks:
            lines.append(f"Buybacks: ${abs(buybacks) / 1e9:.2f}B")

    return "\n".join(lines)


class FMPFinancialsConnector(DocumentConnector):
    """Fetches structured financial statements from FMP.

    Pulls income statement, balance sheet, and cash flow for each quarter,
    then formats them into readable text for claim extraction.
    """

    def __init__(self):
        self._api_key = _fmp_api_key()

    @property
    def source_key(self) -> str:
        return "financials_fmp"

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def fetch(self, ticker: str, days: int = 365) -> list[DocumentPayload]:
        if not self._api_key:
            return []

        limit = max(4, days // 90)  # ~1 quarter per 90 days

        income_data = _fmp_get("/income-statement", {"symbol": ticker, "period": "quarter", "limit": limit})
        balance_data = _fmp_get("/balance-sheet-statement", {"symbol": ticker, "period": "quarter", "limit": limit})
        cashflow_data = _fmp_get("/cash-flow-statement", {"symbol": ticker, "period": "quarter", "limit": limit})

        if not income_data or not isinstance(income_data, list):
            logger.info("FMP financials: no income data for %s", ticker)
            return []

        # Index balance sheet and cash flow by date for matching
        balance_by_date = {}
        if balance_data and isinstance(balance_data, list):
            for b in balance_data:
                balance_by_date[b.get("date", "")] = b

        cashflow_by_date = {}
        if cashflow_data and isinstance(cashflow_data, list):
            for c in cashflow_data:
                cashflow_by_date[c.get("date", "")] = c

        cutoff = datetime.utcnow() - timedelta(days=days)
        payloads = []

        for inc in income_data:
            date_str = inc.get("date", "")
            period_label = inc.get("period", "")  # "Q1", "Q2", etc.
            cal_year = inc.get("calendarYear") or inc.get("fiscalYear", "")

            try:
                filing_date_str = inc.get("filingDate") or inc.get("fillingDate") or inc.get("acceptedDate") or date_str
                published = datetime.strptime(filing_date_str[:10], "%Y-%m-%d")
            except (ValueError, AttributeError):
                try:
                    published = datetime.strptime(date_str[:10], "%Y-%m-%d")
                except (ValueError, AttributeError):
                    published = None

            if published and published < cutoff:
                continue

            balance = balance_by_date.get(date_str)
            cashflow = cashflow_by_date.get(date_str)

            period = f"{period_label} {cal_year}" if period_label and cal_year else date_str
            raw_text = _format_financial_summary(ticker, period, inc, balance, cashflow)
            external_id = f"{ticker}_financials_{period_label}_{cal_year}"

            payloads.append(DocumentPayload(
                source_key=self.source_key,
                source_type=SourceType.TEN_Q,
                source_tier=SourceTier.TIER_1,
                ticker=ticker,
                title=f"{ticker} {period} Financial Statements",
                url=None,
                published_at=published,
                author="FMP",
                external_id=external_id,
                raw_text=raw_text,
                metadata={
                    "period": period_label,
                    "year": cal_year,
                    "revenue": inc.get("revenue"),
                    "net_income": inc.get("netIncome"),
                    "eps": inc.get("epsDiluted") or inc.get("epsdiluted") or inc.get("eps"),
                    "gross_margin": (inc["grossProfit"] / inc["revenue"] * 100)
                        if inc.get("grossProfit") and inc.get("revenue") else None,
                    "operating_margin": (inc["operatingIncome"] / inc["revenue"] * 100)
                        if inc.get("operatingIncome") and inc.get("revenue") else None,
                },
            ))

        logger.info("FMP financials: fetched %d quarters for %s (days=%d)", len(payloads), ticker, days)
        return payloads


# ---------------------------------------------------------------------------
# 3. Analyst Consensus Estimates
# ---------------------------------------------------------------------------

def _format_estimates_summary(
    ticker: str,
    estimates: list[dict],
    actuals_by_date: dict[str, dict],
) -> list[tuple[str, str, datetime | None, dict]]:
    """Format estimates into readable text documents, one per period.

    Returns list of (external_id, raw_text, published_at, metadata).
    """
    results = []

    for est in estimates:
        date_str = est.get("date", "")
        try:
            published = datetime.strptime(date_str[:10], "%Y-%m-%d")
        except (ValueError, AttributeError):
            published = None

        lines = [f"{ticker} Analyst Consensus Estimates — {date_str}"]
        lines.append("=" * 50)

        # Stable API uses revenueAvg/epsAvg; legacy used estimatedRevenueAvg
        est_rev = est.get("revenueAvg") or est.get("estimatedRevenueAvg")
        est_eps = est.get("epsAvg") or est.get("estimatedEpsAvg")
        est_ebitda = est.get("ebitdaAvg") or est.get("estimatedEbitdaAvg")
        est_ni = est.get("netIncomeAvg") or est.get("estimatedNetIncomeAvg")

        num_analysts = (est.get("numAnalystsRevenue")
                        or est.get("numberAnalystEstimatedRevenue")
                        or est.get("numberAnalystsEstimatedRevenue"))

        if est_rev:
            lines.append(f"Revenue Estimate (consensus): ${est_rev / 1e9:.2f}B")
            rev_low = est.get("revenueLow") or est.get("estimatedRevenueLow")
            rev_high = est.get("revenueHigh") or est.get("estimatedRevenueHigh")
            if rev_low and rev_high:
                lines.append(f"  Range: ${rev_low / 1e9:.2f}B — ${rev_high / 1e9:.2f}B")
        if est_eps:
            lines.append(f"EPS Estimate (consensus): ${est_eps:.2f}")
            eps_low = est.get("epsLow") or est.get("estimatedEpsLow")
            eps_high = est.get("epsHigh") or est.get("estimatedEpsHigh")
            if eps_low and eps_high:
                lines.append(f"  Range: ${eps_low:.2f} — ${eps_high:.2f}")
        if est_ebitda:
            lines.append(f"EBITDA Estimate: ${est_ebitda / 1e9:.2f}B")
        if est_ni:
            lines.append(f"Net Income Estimate: ${est_ni / 1e9:.2f}B")
        if num_analysts:
            lines.append(f"Number of Analysts: {num_analysts}")

        # Match with actuals if available
        actual = actuals_by_date.get(date_str, {})
        actual_rev = actual.get("revenue")
        actual_eps = actual.get("eps") or actual.get("epsdiluted")

        beat_miss_meta = {}
        if actual_rev and est_rev:
            rev_surprise = (actual_rev - est_rev) / abs(est_rev) * 100
            beat_miss = "beat" if rev_surprise > 0 else "missed"
            lines.append(f"Actual Revenue: ${actual_rev / 1e9:.2f}B ({beat_miss} by {abs(rev_surprise):.1f}%)")
            beat_miss_meta["revenue_surprise_pct"] = round(rev_surprise, 2)

        if actual_eps is not None and est_eps:
            eps_surprise = (actual_eps - est_eps) / abs(est_eps) * 100 if est_eps != 0 else 0
            beat_miss = "beat" if eps_surprise > 0 else "missed"
            lines.append(f"Actual EPS: ${actual_eps:.2f} ({beat_miss} by {abs(eps_surprise):.1f}%)")
            beat_miss_meta["eps_surprise_pct"] = round(eps_surprise, 2)

        external_id = f"{ticker}_estimates_{date_str}"
        metadata = {
            "estimated_revenue": est_rev,
            "estimated_eps": est_eps,
            "actual_revenue": actual_rev,
            "actual_eps": actual_eps,
            "num_analysts": num_analysts,
            **beat_miss_meta,
        }
        results.append((external_id, "\n".join(lines), published, metadata))

    return results


class FMPEstimatesConnector(DocumentConnector):
    """Fetches analyst consensus estimates from FMP with beat/miss comparison."""

    def __init__(self):
        self._api_key = _fmp_api_key()

    @property
    def source_key(self) -> str:
        return "consensus_estimates_fmp"

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def fetch(self, ticker: str, days: int = 365) -> list[DocumentPayload]:
        if not self._api_key:
            return []

        limit = max(3, days // 365 + 1)

        # Use annual period (quarterly requires higher FMP plan)
        estimates = _fmp_get("/analyst-estimates", {
            "symbol": ticker, "period": "annual", "page": 0, "limit": limit,
        })
        if not estimates or not isinstance(estimates, list):
            logger.info("FMP estimates: no data for %s", ticker)
            return []

        # Get actuals from annual income statement for beat/miss comparison
        income_data = _fmp_get("/income-statement", {
            "symbol": ticker, "period": "annual", "limit": limit,
        })
        actuals_by_date: dict[str, dict] = {}
        if income_data and isinstance(income_data, list):
            for inc in income_data:
                actuals_by_date[inc.get("date", "")] = inc

        cutoff = datetime.utcnow() - timedelta(days=days)
        formatted = _format_estimates_summary(ticker, estimates, actuals_by_date)

        payloads = []
        for external_id, raw_text, published, metadata in formatted:
            if published and published < cutoff:
                continue

            payloads.append(DocumentPayload(
                source_key=self.source_key,
                source_type=SourceType.NEWS,
                source_tier=SourceTier.TIER_2,
                ticker=ticker,
                title=f"{ticker} Analyst Consensus Estimates — {published.strftime('%Y-%m-%d') if published else 'N/A'}",
                url=None,
                published_at=published,
                author="FMP Consensus",
                external_id=external_id,
                raw_text=raw_text,
                metadata=metadata,
            ))

        logger.info("FMP estimates: fetched %d periods for %s (days=%d)", len(payloads), ticker, days)
        return payloads

    def persist_estimates(self, session, ticker: str, days: int = 365) -> int:
        """Fetch estimates from FMP and persist to EarningsEstimate table.

        Returns number of rows upserted.
        """
        if not self._api_key:
            return 0

        from models import EarningsEstimate
        from earnings_surprise import compute_earnings_surprise

        limit = max(3, days // 365 + 1)

        estimates = _fmp_get("/analyst-estimates", {
            "symbol": ticker, "period": "annual", "page": 0, "limit": limit,
        })
        if not estimates or not isinstance(estimates, list):
            return 0

        # Get actuals
        income_data = _fmp_get("/income-statement", {
            "symbol": ticker, "period": "annual", "limit": limit,
        })
        actuals_by_date: dict[str, dict] = {}
        if income_data and isinstance(income_data, list):
            for inc in income_data:
                actuals_by_date[inc.get("date", "")] = inc

        count = 0
        for est in estimates:
            date_str = est.get("date", "")
            try:
                fiscal_date = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
            except (ValueError, AttributeError):
                continue

            est_rev = est.get("revenueAvg") or est.get("estimatedRevenueAvg")
            est_eps = est.get("epsAvg") or est.get("estimatedEpsAvg")
            est_ebitda = est.get("ebitdaAvg") or est.get("estimatedEbitdaAvg")
            est_ni = est.get("netIncomeAvg") or est.get("estimatedNetIncomeAvg")
            num_analysts = (
                est.get("numAnalystsRevenue")
                or est.get("numberAnalystEstimatedRevenue")
                or est.get("numberAnalystsEstimatedRevenue")
            )

            actual = actuals_by_date.get(date_str, {})
            actual_rev = actual.get("revenue")
            actual_eps = actual.get("eps") or actual.get("epsdiluted")

            # Compute surprise
            surprise = compute_earnings_surprise(
                ticker,
                actual_revenue=actual_rev,
                estimated_revenue=est_rev,
                actual_eps=actual_eps,
                estimated_eps=est_eps,
                num_analysts=num_analysts,
                fiscal_period=f"FY{fiscal_date.year}",
            )

            surprise_bucket = surprise.composite_bucket if surprise else None
            rev_surprise_pct = surprise.revenue.surprise_pct if surprise and surprise.revenue else None
            eps_surprise_pct = surprise.eps.surprise_pct if surprise and surprise.eps else None

            # Upsert
            from sqlalchemy import select
            existing = session.scalars(
                select(EarningsEstimate).where(
                    EarningsEstimate.ticker == ticker,
                    EarningsEstimate.fiscal_date == fiscal_date,
                )
            ).first()

            if existing:
                existing.estimated_revenue = est_rev
                existing.estimated_eps = est_eps
                existing.estimated_ebitda = est_ebitda
                existing.estimated_net_income = est_ni
                existing.num_analysts = num_analysts
                existing.actual_revenue = actual_rev
                existing.actual_eps = actual_eps
                existing.revenue_surprise_pct = rev_surprise_pct
                existing.eps_surprise_pct = eps_surprise_pct
                existing.surprise_bucket = surprise_bucket
                existing.revenue_low = est.get("revenueLow") or est.get("estimatedRevenueLow")
                existing.revenue_high = est.get("revenueHigh") or est.get("estimatedRevenueHigh")
                existing.eps_low = est.get("epsLow") or est.get("estimatedEpsLow")
                existing.eps_high = est.get("epsHigh") or est.get("estimatedEpsHigh")
                existing.source = "fmp"
            else:
                session.add(EarningsEstimate(
                    ticker=ticker,
                    fiscal_date=fiscal_date,
                    fiscal_period=f"FY{fiscal_date.year}",
                    estimated_revenue=est_rev,
                    estimated_eps=est_eps,
                    estimated_ebitda=est_ebitda,
                    estimated_net_income=est_ni,
                    num_analysts=num_analysts,
                    actual_revenue=actual_rev,
                    actual_eps=actual_eps,
                    revenue_surprise_pct=rev_surprise_pct,
                    eps_surprise_pct=eps_surprise_pct,
                    surprise_bucket=surprise_bucket,
                    revenue_low=est.get("revenueLow") or est.get("estimatedRevenueLow"),
                    revenue_high=est.get("revenueHigh") or est.get("estimatedRevenueHigh"),
                    eps_low=est.get("epsLow") or est.get("estimatedEpsLow"),
                    eps_high=est.get("epsHigh") or est.get("estimatedEpsHigh"),
                    source="fmp",
                ))
            count += 1

        logger.info("FMP estimates: persisted %d estimate rows for %s", count, ticker)
        return count


# ---------------------------------------------------------------------------
# 4. Stock News
# ---------------------------------------------------------------------------

class FMPNewsConnector(DocumentConnector):
    """Fetches stock news from FMP.

    Uses /news/stock endpoint. The starter plan returns a general feed
    (filtering by ticker may not work), so we filter client-side.
    """

    def __init__(self):
        self._api_key = _fmp_api_key()

    @property
    def source_key(self) -> str:
        return "news_fmp"

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def fetch(self, ticker: str, days: int = 7) -> list[DocumentPayload]:
        if not self._api_key:
            return []

        # Fetch with ticker filter — FMP may or may not respect it
        data = _fmp_get("/news/stock", {"tickers": ticker, "limit": 100})
        if not data or not isinstance(data, list):
            logger.info("FMP news: no data for %s", ticker)
            return []

        cutoff = datetime.utcnow() - timedelta(days=days)
        payloads = []

        for item in data:
            # Client-side ticker filter (FMP may return mixed symbols)
            item_symbol = item.get("symbol", "")
            if item_symbol and item_symbol.upper() != ticker.upper():
                continue

            date_str = item.get("publishedDate", "")
            try:
                published = datetime.strptime(date_str[:19], "%Y-%m-%d %H:%M:%S")
            except (ValueError, AttributeError):
                try:
                    published = datetime.strptime(date_str[:10], "%Y-%m-%d")
                except (ValueError, AttributeError):
                    published = None

            if published and published < cutoff:
                continue

            title = item.get("title", "")
            text = item.get("text", "")
            url = item.get("url", "")

            if not title:
                continue

            raw_text = f"{title}\n\n{text}" if text else title

            payloads.append(DocumentPayload(
                source_key=self.source_key,
                source_type=SourceType.NEWS,
                source_tier=SourceTier.TIER_2,
                ticker=ticker,
                title=title,
                url=url or None,
                published_at=published,
                author=item.get("site", "") or item.get("publisher", ""),
                external_id=None,  # dedupe on content hash
                raw_text=raw_text,
                metadata={
                    "source_site": item.get("site", ""),
                    "publisher": item.get("publisher", ""),
                },
            ))

        logger.info("FMP news: fetched %d articles for %s (days=%d)", len(payloads), ticker, days)
        return payloads


# ---------------------------------------------------------------------------
# 5. Stock Peers (for cross-ticker relationship discovery)
# ---------------------------------------------------------------------------

def fetch_fmp_peers(ticker: str) -> list[dict]:
    """Fetch peer companies from FMP stable/stock-peers endpoint.

    Returns list of dicts with {symbol, companyName, price, mktCap}.
    Useful for auto-discovering competitor relationships.
    """
    data = _fmp_get("/stock-peers", {"symbol": ticker})
    if not data or not isinstance(data, list):
        return []
    # First entry is usually the queried ticker itself
    peers = [p for p in data if p.get("symbol", "").upper() != ticker.upper()]
    return peers


def discover_peer_relationships(
    session,
    tickers: list[str],
    universe: set[str] | None = None,
) -> int:
    """Auto-discover competitor relationships from FMP peers endpoint.

    For each ticker, fetches FMP peers and creates CompanyRelationship rows
    for any peer that's also in our universe. Only creates relationships
    that don't already exist.

    Args:
        session: SQLAlchemy session.
        tickers: Tickers to discover peers for.
        universe: Optional set of valid tickers (filters peers to our universe).

    Returns:
        Number of new relationships created.
    """
    from models import CompanyRelationship, RelationshipType

    if not _fmp_api_key():
        logger.info("FMP API key not set, skipping peer discovery")
        return 0

    if universe is None:
        from source_registry import get_universe_tickers
        universe = set(get_universe_tickers())

    created = 0
    for ticker in tickers:
        peers = fetch_fmp_peers(ticker)
        if not peers:
            continue

        for peer in peers:
            peer_ticker = peer.get("symbol", "").upper()
            if peer_ticker not in universe:
                continue

            # Check if relationship already exists (either direction)
            existing = session.scalar(
                select(CompanyRelationship).where(
                    ((CompanyRelationship.source_ticker == ticker) &
                     (CompanyRelationship.target_ticker == peer_ticker)) |
                    ((CompanyRelationship.source_ticker == peer_ticker) &
                     (CompanyRelationship.target_ticker == ticker)),
                    CompanyRelationship.relationship_type == RelationshipType.COMPETITOR,
                )
            )
            if existing:
                continue

            peer_name = peer.get("companyName", peer_ticker)
            session.add(CompanyRelationship(
                source_ticker=ticker,
                target_ticker=peer_ticker,
                relationship_type=RelationshipType.COMPETITOR,
                description=f"FMP sector peer: {peer_name}",
                strength=0.3,  # default low strength for auto-discovered peers
                bidirectional=True,
                source="fmp_peers",
            ))
            created += 1

        # Rate limit: 1 request per ticker already sent, brief pause
        time.sleep(0.2)

    if created:
        session.flush()
    logger.info("FMP peer discovery: %d new competitor relationships from %d tickers",
                created, len(tickers))
    return created
