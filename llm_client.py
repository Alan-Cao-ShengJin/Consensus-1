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

# Models that only support temperature=1 (no custom temperature)
_FIXED_TEMP_MODELS = {"gpt-5-nano", "o1-mini", "o1-preview", "o1", "o3-mini"}


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

    # Some models (gpt-5-nano, o1, etc.) don't support custom temperature
    extra_params = {}
    model_base = model.split("-2")[0] if "-2" in model else model  # strip date suffix
    if model_base not in _FIXED_TEMP_MODELS:
        extra_params["temperature"] = temperature

    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                response_format={"type": "json_object"},
                **extra_params,
            )
            raw_text = response.choices[0].message.content or ""
            return _parse_json_array(raw_text)
        except json.JSONDecodeError as e:
            logger.error("LLM returned unparseable JSON (attempt %d): %s", attempt, e)
            last_error = e
            if attempt < MAX_RETRIES:
                time.sleep(backoff)
                backoff *= 2
                continue
            raise  # exhausted retries
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


def call_openai_json_object(
    messages: list[dict],
    model: str | None = None,
    temperature: float = 0.2,
) -> dict[str, Any]:
    """Call OpenAI and parse the response as a single JSON object.

    Unlike call_openai_json (which expects an array), this returns the
    top-level dict directly.  Used for thesis-update responses.
    """
    client = get_openai_client()
    model = model or os.getenv("OPENAI_MODEL", DEFAULT_MODEL)
    backoff = RETRY_BACKOFF

    # Some models don't support custom temperature
    extra_params = {}
    model_base = model.split("-2")[0] if "-2" in model else model
    if model_base not in _FIXED_TEMP_MODELS:
        extra_params["temperature"] = temperature

    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                response_format={"type": "json_object"},
                **extra_params,
            )
            raw_text = response.choices[0].message.content or ""
            data = json.loads(raw_text)
            if not isinstance(data, dict):
                raise json.JSONDecodeError(
                    f"Expected JSON object, got {type(data).__name__}", raw_text, 0
                )
            return data
        except json.JSONDecodeError as e:
            logger.error("LLM returned unparseable JSON (attempt %d): %s", attempt, e)
            raise
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
        # Empty dict — treat as no claims
        if not data:
            logger.info("LLM returned empty object, treating as no claims")
            return []
        # Single claim object — wrap in a list if it looks like a claim
        if "claim_text_normalized" in data or "claim_type" in data:
            logger.info("LLM returned single claim object, wrapping in list")
            return [data]
        raise json.JSONDecodeError(
            f"JSON object has no recognizable array key. Keys: {list(data.keys())}",
            raw,
            0,
        )
    raise json.JSONDecodeError(
        f"Expected JSON array or object, got {type(data).__name__}", raw, 0
    )
