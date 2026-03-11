"""Thin wrapper around the OpenAI chat-completions API."""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gpt-4o-mini"
MAX_RETRIES = 3
RETRY_BACKOFF = 2  # seconds, doubled each retry


def get_openai_client():
    """Lazy-import and return an OpenAI client."""
    try:
        from openai import OpenAI  # type: ignore
    except ImportError:
        raise ImportError(
            "openai package is required for LLM extraction. "
            "Install it with: pip install openai"
        )

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "OPENAI_API_KEY environment variable is not set. "
            "Set it before using the LLM extractor."
        )
    return OpenAI(api_key=api_key)


def call_openai_json(
    messages: list[dict],
    model: str | None = None,
    temperature: float = 0.2,
) -> list[dict[str, Any]]:
    """Call OpenAI and parse the response as a JSON array of claim dicts.

    Retries on transient API errors with exponential backoff.
    Raises on persistent failure or unparseable response.
    """
    client = get_openai_client()
    model = model or os.getenv("OPENAI_MODEL", DEFAULT_MODEL)
    backoff = RETRY_BACKOFF

    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                response_format={"type": "json_object"},
            )
            raw_text = response.choices[0].message.content or ""
            return _parse_json_array(raw_text)
        except json.JSONDecodeError as e:
            logger.error("LLM returned unparseable JSON (attempt %d): %s", attempt, e)
            raise  # no point retrying a parse error on the same response
        except Exception as e:
            last_error = e
            logger.warning(
                "OpenAI API error (attempt %d/%d): %s", attempt, MAX_RETRIES, e
            )
            if attempt < MAX_RETRIES:
                time.sleep(backoff)
                backoff *= 2

    raise RuntimeError(
        f"OpenAI API failed after {MAX_RETRIES} retries: {last_error}"
    )


def _parse_json_array(raw: str) -> list[dict[str, Any]]:
    """Parse LLM output into a list of dicts.

    Handles both bare arrays and {"claims": [...]} wrapper objects.
    """
    data = json.loads(raw)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        # Try common wrapper keys
        for key in ("claims", "results", "data", "extracted_claims"):
            if key in data and isinstance(data[key], list):
                return data[key]
        raise json.JSONDecodeError(
            f"JSON object has no recognizable array key. Keys: {list(data.keys())}",
            raw,
            0,
        )
    raise json.JSONDecodeError(
        f"Expected JSON array or object, got {type(data).__name__}", raw, 0
    )
