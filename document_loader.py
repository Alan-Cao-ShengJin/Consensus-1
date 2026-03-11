"""Load raw documents from local files (text, HTML, JSON)."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from models import SourceType, SourceTier


@dataclass
class LoadedDocument:
    title: str
    raw_text: str
    source_type: SourceType
    source_tier: SourceTier = SourceTier.TIER_2
    url: Optional[str] = None
    published_at: Optional[datetime] = None
    publisher: Optional[str] = None
    primary_company_ticker: Optional[str] = None


def _detect_format(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in (".html", ".htm"):
        return "html"
    if ext == ".json":
        return "json"
    return "text"


def load_from_text(path: str, source_type: SourceType, **overrides) -> LoadedDocument:
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    title = overrides.pop("title", os.path.basename(path))
    return LoadedDocument(title=title, raw_text=raw, source_type=source_type, **overrides)


def load_from_html(path: str, source_type: SourceType, **overrides) -> LoadedDocument:
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    title = overrides.pop("title", os.path.basename(path))
    return LoadedDocument(title=title, raw_text=raw, source_type=source_type, **overrides)


def load_from_json(path: str, source_type: SourceType, **overrides) -> LoadedDocument:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    title = overrides.pop("title", data.get("title", os.path.basename(path)))
    return LoadedDocument(
        title=title,
        raw_text=data.get("raw_text", data.get("text", data.get("body", ""))),
        source_type=source_type,
        url=data.get("url"),
        published_at=_parse_dt(data.get("published_at")),
        publisher=data.get("publisher"),
        primary_company_ticker=data.get("primary_company_ticker"),
        **overrides,
    )


def load_document(path: str, source_type: SourceType, **overrides) -> LoadedDocument:
    """Auto-detect format and load a document from a local file."""
    fmt = _detect_format(path)
    if fmt == "json":
        return load_from_json(path, source_type, **overrides)
    if fmt == "html":
        return load_from_html(path, source_type, **overrides)
    return load_from_text(path, source_type, **overrides)


def _parse_dt(val) -> Optional[datetime]:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    try:
        return datetime.fromisoformat(val)
    except (TypeError, ValueError):
        return None
