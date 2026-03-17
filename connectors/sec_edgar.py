"""SEC EDGAR connector: fetches 10-K, 10-Q, 8-K, 13F-HR filings via edgartools.

Uses the edgartools library (https://github.com/dgunning/edgartools) for
filing discovery, section extraction, and exhibit text retrieval.
"""
from __future__ import annotations

import logging
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Optional

import edgar
from dotenv import load_dotenv

load_dotenv()

from models import SourceType, SourceTier
from connectors.base import DocumentConnector, DocumentPayload

logger = logging.getLogger(__name__)

# Mapping from filing type to source registry key and SourceType
_FILING_MAP = {
    "10-K": ("sec_10k", SourceType.TEN_K),
    "10-Q": ("sec_10q", SourceType.TEN_Q),
    "8-K":  ("sec_8k",  SourceType.EIGHT_K),
    "13F-HR": ("sec_13f", SourceType.THIRTEEN_F),
}

# Max text size per document payload
_MAX_TEXT_BYTES = 500_000

# SEC EDGAR archives base URL (for building filing URLs)
_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"

# Set SEC identity on import
_SEC_IDENTITY = os.getenv("SEC_USER_AGENT", "Consensus-1 Research Platform admin@example.com")
edgar.set_identity(_SEC_IDENTITY)


def _get_user_agent() -> str:
    """Return the SEC User-Agent string (used by tests)."""
    return os.getenv("SEC_USER_AGENT", "Consensus-1 Research Platform admin@example.com")


def _clean_whitespace(text: str) -> str:
    """Consolidate excessive blank lines and spaces."""
    text = re.sub(r"([ ]*\n[ ]*){3,}", "\n\n", text)
    text = re.sub(r"[ ]{2,}", " ", text)
    return text.strip()


def _filing_url(cik: int | str, accession: str, primary_doc: str = "") -> str:
    """Build an EDGAR archives URL for a filing."""
    cik_str = str(cik).lstrip("0")
    acc_clean = accession.replace("-", "")
    if primary_doc:
        return f"{_ARCHIVES_BASE}/{cik_str}/{acc_clean}/{primary_doc}"
    return f"{_ARCHIVES_BASE}/{cik_str}/{acc_clean}/"


# ---------------------------------------------------------------------------
# Section extraction helpers
# ---------------------------------------------------------------------------

def _extract_10k_text(filing) -> str:
    """Extract key sections from a 10-K filing using edgartools."""
    sections = []
    section_map = [
        ("Item 1A", "RISK FACTORS"),
        ("Item 7", "MANAGEMENT'S DISCUSSION AND ANALYSIS"),
        ("Item 7A", "QUANTITATIVE AND QUALITATIVE DISCLOSURES ABOUT MARKET RISK"),
    ]

    tenk = filing.obj()
    for item_key, label in section_map:
        try:
            text = tenk[item_key]
            if text and len(str(text)) > 200:
                sections.append(f"=== {item_key.upper()}: {label} ===\n\n{str(text)}")
        except (KeyError, IndexError, Exception) as e:
            logger.debug("10-K section %s not found: %s", item_key, e)

    if sections:
        result = "\n\n".join(sections)
    else:
        # Fallback: try to get full text
        try:
            result = str(tenk)
        except Exception:
            result = ""

    return _clean_whitespace(result)[:_MAX_TEXT_BYTES]


def _extract_10q_text(filing) -> str:
    """Extract key sections from a 10-Q filing using edgartools."""
    sections = []
    section_map = [
        ("Part I, Item 2", "MANAGEMENT'S DISCUSSION AND ANALYSIS"),
        ("Part I, Item 3", "QUANTITATIVE AND QUALITATIVE DISCLOSURES ABOUT MARKET RISK"),
        ("Part II, Item 1A", "RISK FACTORS"),
    ]

    tenq = filing.obj()
    for item_key, label in section_map:
        try:
            text = tenq[item_key]
            if text and len(str(text)) > 200:
                sections.append(f"=== {item_key.upper()}: {label} ===\n\n{str(text)}")
        except (KeyError, IndexError, Exception) as e:
            logger.debug("10-Q section %s not found: %s", item_key, e)

    # Also try short-form keys as fallback
    if not sections:
        fallback_keys = [
            ("Item 2", "MANAGEMENT'S DISCUSSION AND ANALYSIS"),
            ("Item 3", "QUANTITATIVE AND QUALITATIVE DISCLOSURES ABOUT MARKET RISK"),
            ("Item 1A", "RISK FACTORS"),
        ]
        for item_key, label in fallback_keys:
            try:
                text = tenq[item_key]
                if text and len(str(text)) > 200:
                    sections.append(f"=== {item_key.upper()}: {label} ===\n\n{str(text)}")
            except (KeyError, IndexError, Exception) as e:
                logger.debug("10-Q fallback section %s not found: %s", item_key, e)

    if sections:
        result = "\n\n".join(sections)
    else:
        try:
            result = str(tenq)
        except Exception:
            result = ""

    return _clean_whitespace(result)[:_MAX_TEXT_BYTES]


def _extract_8k_exhibits(filing) -> list[dict]:
    """Extract EX-99.x exhibit texts from an 8-K filing.

    Returns list of dicts with keys: name, description, text, url.
    """
    exhibits = []
    try:
        attachments = filing.attachments
        if not attachments:
            return []

        for att in attachments:
            desc = getattr(att, "description", "") or ""
            doc_type = getattr(att, "document_type", "") or getattr(att, "type", "") or ""

            # Only grab EX-99.x exhibits (press releases, CFO commentary, etc.)
            is_exhibit = (
                "EX-99" in doc_type.upper()
                or "EX-99" in desc.upper()
                or "EXHIBIT 99" in desc.upper()
            )
            if not is_exhibit:
                continue

            try:
                # Use markdown() for proper table formatting; fall back to text()
                try:
                    text = att.markdown()
                except Exception:
                    text = att.text()
                if not text or len(text.strip()) < 100:
                    continue
                text = _clean_whitespace(text)[:_MAX_TEXT_BYTES]
            except Exception as e:
                logger.warning("Failed to get text for exhibit %s: %s", doc_type, e)
                continue

            url = getattr(att, "url", "") or ""
            name = getattr(att, "document", "") or getattr(att, "filename", "") or doc_type

            exhibits.append({
                "name": name,
                "description": doc_type or desc,
                "text": text,
                "url": url,
            })

    except Exception as e:
        logger.warning("Failed to enumerate 8-K attachments: %s", e)

    return exhibits


def _extract_13f_holdings(filing) -> str:
    """Extract the holdings table from a 13F-HR filing.

    Parses the informationTable.xml attachment to extract institutional
    holdings data. Falls back to primary document text if XML parsing fails.
    """
    filer_name = getattr(filing, "company", "") or getattr(filing, "filer", "") or "UNKNOWN"
    if hasattr(filer_name, "name"):
        filer_name = filer_name.name
    filing_date = getattr(filing, "filing_date", "")
    period_of_report = getattr(filing, "period_of_report", filing_date) or filing_date

    holdings: list[dict] = []

    # --- Try XML information table ---
    try:
        attachments = filing.attachments
        xml_text = None

        if attachments:
            for att in attachments:
                doc_type = (getattr(att, "document_type", "") or
                            getattr(att, "type", "") or "")
                filename = (getattr(att, "document", "") or
                            getattr(att, "filename", "") or "")
                is_info_table = (
                    "INFORMATION TABLE" in doc_type.upper()
                    or "INFOTABLE" in filename.upper().replace("_", "").replace("-", "")
                    or filename.lower().endswith(".xml")
                    and "info" in filename.lower()
                )
                if is_info_table:
                    try:
                        xml_text = att.text() if callable(getattr(att, "text", None)) else str(att)
                    except Exception:
                        try:
                            xml_text = att.content if hasattr(att, "content") else None
                        except Exception:
                            pass
                    if xml_text:
                        break

        if xml_text:
            # Strip namespace prefixes for easier parsing
            xml_clean = re.sub(r'xmlns[^"]*"[^"]*"', '', xml_text)
            xml_clean = re.sub(r'<(/?)ns\d+:', r'<\1', xml_clean)
            xml_clean = re.sub(r'<(/?)[\w]+:', r'<\1', xml_clean)

            root = ET.fromstring(xml_clean)

            # Find all infoTable entries (various tag names)
            entries = (root.findall(".//infoTable") or
                       root.findall(".//InfoTable") or
                       root.findall(".//{*}infoTable"))

            for entry in entries:
                def _find_text(parent, tags):
                    for tag in tags:
                        el = parent.find(tag)
                        if el is not None and el.text:
                            return el.text.strip()
                        # Also try case-insensitive child search
                        for child in parent:
                            if child.tag.lower().endswith(tag.lower()):
                                if child.text:
                                    return child.text.strip()
                    return ""

                name = _find_text(entry, ["nameOfIssuer", "nameofissuer"])
                title = _find_text(entry, ["titleOfClass", "titleofclass"])
                cusip = _find_text(entry, ["cusip", "CUSIP"])
                value_str = _find_text(entry, ["value"])
                put_call = _find_text(entry, ["putCall", "putcall"])

                # Shares can be nested inside shrsOrPrnAmt
                shares_str = ""
                shares_parent = (entry.find("shrsOrPrnAmt") or
                                 entry.find("ShrsOrPrnAmt"))
                if shares_parent is not None:
                    shares_str = _find_text(shares_parent, ["sshPrnamt", "SshPrnamt"])
                if not shares_str:
                    shares_str = _find_text(entry, ["sshPrnamt", "SshPrnamt"])

                try:
                    value_thousands = int(value_str.replace(",", "")) if value_str else 0
                except (ValueError, AttributeError):
                    value_thousands = 0

                try:
                    shares = int(shares_str.replace(",", "")) if shares_str else 0
                except (ValueError, AttributeError):
                    shares = 0

                holdings.append({
                    "name": name,
                    "title": title,
                    "cusip": cusip,
                    "value_thousands": value_thousands,
                    "shares": shares,
                    "put_call": put_call,
                })

    except Exception as e:
        logger.warning("13F XML parsing failed: %s", e)

    # --- Format output ---
    if holdings:
        # Sort by value descending
        holdings.sort(key=lambda h: h["value_thousands"], reverse=True)
        total_value = sum(h["value_thousands"] for h in holdings)
        num_positions = len(holdings)

        lines = [
            f"{filer_name} 13F-HR — {period_of_report}",
            "=" * 60,
            "Top Holdings:",
        ]

        # Show top 50 holdings
        for i, h in enumerate(holdings[:50], 1):
            value_dollars = h["value_thousands"] * 1000
            pct = (h["value_thousands"] / total_value * 100) if total_value else 0
            shares_fmt = f"{h['shares']:,}" if h["shares"] else "N/A"

            # Format value nicely
            if value_dollars >= 1e9:
                val_fmt = f"${value_dollars / 1e9:.1f}B"
            elif value_dollars >= 1e6:
                val_fmt = f"${value_dollars / 1e6:.1f}M"
            else:
                val_fmt = f"${value_dollars:,.0f}"

            name = h["name"]
            title_suffix = f" ({h['title']})" if h["title"] else ""
            pc_suffix = f" [{h['put_call']}]" if h["put_call"] else ""

            lines.append(
                f"{i:>3}. {name}{title_suffix}{pc_suffix} — "
                f"{val_fmt} ({pct:.1f}% of portfolio) — "
                f"{shares_fmt} shares"
            )

        # Summary
        total_fmt = (
            f"${total_value * 1000 / 1e9:.1f}B" if total_value * 1000 >= 1e9
            else f"${total_value * 1000 / 1e6:.1f}M"
        )
        lines.append("")
        lines.append(f"Total portfolio value: {total_fmt} across {num_positions} positions")

        if num_positions > 50:
            lines.append(f"(Showing top 50 of {num_positions} positions)")

        result = "\n".join(lines)
    else:
        # Fallback: try primary document text
        logger.info("13F: No XML holdings parsed, falling back to primary document text.")
        try:
            result = str(filing.obj()) if hasattr(filing, "obj") else str(filing)
        except Exception:
            try:
                result = filing.text() if callable(getattr(filing, "text", None)) else ""
            except Exception:
                result = ""

        if not result:
            return ""

        result = f"{filer_name} 13F-HR — {period_of_report}\n{'=' * 60}\n\n{result}"

    return _clean_whitespace(result)[:_MAX_TEXT_BYTES]


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------

class SECEdgarConnector(DocumentConnector):
    """Fetches SEC filings (10-K, 10-Q, 8-K) for a ticker via edgartools."""

    def __init__(self, filing_types: Optional[list[str]] = None):
        self._filing_types = filing_types or ["10-K", "10-Q", "8-K"]

    @property
    def source_key(self) -> str:
        return "sec_edgar"

    def fetch(self, ticker: str, days: int = 30, start_date=None, end_date=None) -> list[DocumentPayload]:
        # Resolve date range
        if start_date:
            cutoff = datetime(start_date.year, start_date.month, start_date.day) if hasattr(start_date, 'year') else datetime.fromisoformat(str(start_date))
        else:
            cutoff = datetime.utcnow() - timedelta(days=days)

        end_dt = None
        if end_date:
            end_dt = datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59) if hasattr(end_date, 'year') else datetime.fromisoformat(str(end_date))

        # Look up company
        try:
            company = edgar.Company(ticker)
        except Exception as e:
            logger.warning("edgartools: could not find company for %s: %s", ticker, e)
            return []

        cik = company.cik

        payloads: list[DocumentPayload] = []

        for form_type in self._filing_types:
            source_key, source_type = _FILING_MAP[form_type]

            try:
                filings = company.get_filings(form=form_type)
            except Exception as e:
                logger.warning("edgartools: failed to get %s filings for %s: %s", form_type, ticker, e)
                continue

            if filings is None or len(filings) == 0:
                continue

            for filing in filings:
                # Parse filing date
                try:
                    fd = filing.filing_date
                    if isinstance(fd, str):
                        filing_date = datetime.strptime(fd, "%Y-%m-%d")
                    elif hasattr(fd, 'year'):
                        filing_date = datetime(fd.year, fd.month, fd.day)
                    else:
                        continue
                except Exception:
                    continue

                # Date filtering
                if filing_date < cutoff:
                    break  # Filings are in reverse chronological order
                if end_dt and filing_date > end_dt:
                    continue

                accession = getattr(filing, 'accession_no', '') or getattr(filing, 'accession_number', '') or ''
                date_str = filing_date.strftime("%Y-%m-%d")
                url = getattr(filing, 'filing_url', '') or getattr(filing, 'url', '') or ''
                if not url and accession:
                    url = _filing_url(cik, accession)

                if form_type == "10-K":
                    payloads.extend(self._process_10k(
                        ticker, filing, accession, filing_date, date_str, cik, url,
                        source_key, source_type,
                    ))
                elif form_type == "10-Q":
                    payloads.extend(self._process_10q(
                        ticker, filing, accession, filing_date, date_str, cik, url,
                        source_key, source_type,
                    ))
                elif form_type == "8-K":
                    payloads.extend(self._process_8k(
                        ticker, filing, accession, filing_date, date_str, cik, url,
                        source_key, source_type,
                    ))
                elif form_type == "13F-HR":
                    payloads.extend(self._process_13f(
                        ticker, filing, accession, filing_date, date_str, cik, url,
                        source_key, source_type,
                    ))

        logger.info("SEC EDGAR: fetched %d documents for %s (days=%d)", len(payloads), ticker, days)
        return payloads

    def _process_13f(
        self, ticker, filing, accession, filing_date, date_str, cik, url,
        source_key, source_type,
    ) -> list[DocumentPayload]:
        try:
            raw_text = _extract_13f_holdings(filing)
        except Exception as e:
            logger.warning("Failed to extract 13F-HR text for %s %s: %s", ticker, accession, e)
            raw_text = ""

        if not raw_text:
            return []

        return [DocumentPayload(
            source_key=source_key,
            source_type=source_type,
            source_tier=SourceTier.TIER_2,
            ticker=ticker,
            title=f"{ticker} 13F-HR filed {date_str}",
            url=url,
            published_at=filing_date,
            author="SEC EDGAR",
            external_id=accession,
            raw_text=raw_text,
            metadata={"form_type": "13F-HR", "cik": str(cik), "accession": accession},
        )]

    def _process_10k(
        self, ticker, filing, accession, filing_date, date_str, cik, url,
        source_key, source_type,
    ) -> list[DocumentPayload]:
        try:
            raw_text = _extract_10k_text(filing)
        except Exception as e:
            logger.warning("Failed to extract 10-K text for %s %s: %s", ticker, accession, e)
            raw_text = ""

        if not raw_text:
            return []

        return [DocumentPayload(
            source_key=source_key,
            source_type=source_type,
            source_tier=SourceTier.TIER_1,
            ticker=ticker,
            title=f"{ticker} 10-K filed {date_str}",
            url=url,
            published_at=filing_date,
            author="SEC EDGAR",
            external_id=accession,
            raw_text=raw_text,
            metadata={"form_type": "10-K", "cik": str(cik), "accession": accession},
        )]

    def _process_10q(
        self, ticker, filing, accession, filing_date, date_str, cik, url,
        source_key, source_type,
    ) -> list[DocumentPayload]:
        try:
            raw_text = _extract_10q_text(filing)
        except Exception as e:
            logger.warning("Failed to extract 10-Q text for %s %s: %s", ticker, accession, e)
            raw_text = ""

        if not raw_text:
            return []

        return [DocumentPayload(
            source_key=source_key,
            source_type=source_type,
            source_tier=SourceTier.TIER_1,
            ticker=ticker,
            title=f"{ticker} 10-Q filed {date_str}",
            url=url,
            published_at=filing_date,
            author="SEC EDGAR",
            external_id=accession,
            raw_text=raw_text,
            metadata={"form_type": "10-Q", "cik": str(cik), "accession": accession},
        )]

    def _process_8k(
        self, ticker, filing, accession, filing_date, date_str, cik, url,
        source_key, source_type,
    ) -> list[DocumentPayload]:
        payloads = []

        # Skip cover page — it's just boilerplate item references.
        # All useful content lives in the EX-99.x exhibits.
        exhibits = _extract_8k_exhibits(filing)
        for exhibit in exhibits:
            exhibit_id = f"{accession}:{exhibit['name']}"
            payloads.append(DocumentPayload(
                source_key=source_key,
                source_type=source_type,
                source_tier=SourceTier.TIER_1,
                ticker=ticker,
                title=f"{ticker} 8-K {exhibit['description']} filed {date_str}",
                url=exhibit.get("url", url),
                published_at=filing_date,
                author="SEC EDGAR",
                external_id=exhibit_id,
                raw_text=exhibit["text"],
                metadata={
                    "form_type": "8-K",
                    "cik": str(cik),
                    "accession": accession,
                    "exhibit": exhibit["description"],
                    "exhibit_filename": exhibit["name"],
                },
            ))

        return payloads


# ---------------------------------------------------------------------------
# 13F-HR Connector (separate from SECEdgarConnector)
# ---------------------------------------------------------------------------

class SEC13FConnector(DocumentConnector):
    """Fetches 13F-HR institutional holdings filings.

    Unlike other SEC filings which are filed by operating companies,
    13F filings are filed by investment managers (hedge funds, mutual funds).
    Use fetch() with the manager's ticker/CIK.
    """

    @property
    def source_key(self) -> str:
        return "sec_13f"

    def fetch(self, entity: str, days: int = 180, start_date=None, end_date=None) -> list[DocumentPayload]:
        """Fetch 13F-HR filings for an investment manager.

        Args:
            entity: Manager ticker (e.g. "BRK-B") or CIK number.
            days: How many days back to look (default 180 for quarterly filings).
            start_date: Optional start date override.
            end_date: Optional end date override.

        Returns:
            List of DocumentPayload objects with parsed holdings data.
        """
        # Resolve date range
        if start_date:
            cutoff = (datetime(start_date.year, start_date.month, start_date.day)
                      if hasattr(start_date, 'year')
                      else datetime.fromisoformat(str(start_date)))
        else:
            cutoff = datetime.utcnow() - timedelta(days=days)

        end_dt = None
        if end_date:
            end_dt = (datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59)
                      if hasattr(end_date, 'year')
                      else datetime.fromisoformat(str(end_date)))

        # Look up company/manager
        try:
            company = edgar.Company(entity)
        except Exception as e:
            logger.warning("edgartools: could not find entity for %s: %s", entity, e)
            return []

        cik = company.cik
        source_key, source_type = _FILING_MAP["13F-HR"]

        try:
            filings = company.get_filings(form="13F-HR")
        except Exception as e:
            logger.warning("edgartools: failed to get 13F-HR filings for %s: %s", entity, e)
            return []

        if filings is None or len(filings) == 0:
            return []

        payloads: list[DocumentPayload] = []

        for filing in filings:
            # Parse filing date
            try:
                fd = filing.filing_date
                if isinstance(fd, str):
                    filing_date = datetime.strptime(fd, "%Y-%m-%d")
                elif hasattr(fd, 'year'):
                    filing_date = datetime(fd.year, fd.month, fd.day)
                else:
                    continue
            except Exception:
                continue

            # Date filtering
            if filing_date < cutoff:
                break  # Filings are in reverse chronological order
            if end_dt and filing_date > end_dt:
                continue

            accession = (getattr(filing, 'accession_no', '') or
                         getattr(filing, 'accession_number', '') or '')
            date_str = filing_date.strftime("%Y-%m-%d")
            url = (getattr(filing, 'filing_url', '') or
                   getattr(filing, 'url', '') or '')
            if not url and accession:
                url = _filing_url(cik, accession)

            # Extract holdings
            try:
                raw_text = _extract_13f_holdings(filing)
            except Exception as e:
                logger.warning("Failed to extract 13F-HR text for %s %s: %s",
                               entity, accession, e)
                raw_text = ""

            if not raw_text:
                continue

            payloads.append(DocumentPayload(
                source_key=source_key,
                source_type=source_type,
                source_tier=SourceTier.TIER_2,
                ticker=entity,
                title=f"{entity} 13F-HR filed {date_str}",
                url=url,
                published_at=filing_date,
                author="SEC EDGAR",
                external_id=accession,
                raw_text=raw_text,
                metadata={
                    "form_type": "13F-HR",
                    "cik": str(cik),
                    "accession": accession,
                },
            ))

        logger.info("SEC 13F: fetched %d filings for %s (days=%d)",
                     len(payloads), entity, days)
        return payloads
