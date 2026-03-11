"""Normalize raw document text for claim extraction."""
from __future__ import annotations

import re


def strip_html(raw: str) -> str:
    """Remove HTML tags and decode common entities."""
    text = re.sub(r"<script[^>]*>.*?</script>", "", raw, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    # Decode common HTML entities
    for entity, char in [("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                         ("&quot;", '"'), ("&#39;", "'"), ("&nbsp;", " ")]:
        text = text.replace(entity, char)
    return text


def normalize_whitespace(text: str) -> str:
    """Collapse runs of whitespace into single spaces, strip leading/trailing."""
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_document(raw_text: str, is_html: bool = False) -> str:
    """Return cleaned plain text ready for claim extraction."""
    if is_html or _looks_like_html(raw_text):
        raw_text = strip_html(raw_text)
    return normalize_whitespace(raw_text)


def _looks_like_html(text: str) -> bool:
    return bool(re.search(r"<(?:html|head|body|div|p|span)\b", text, re.IGNORECASE))
