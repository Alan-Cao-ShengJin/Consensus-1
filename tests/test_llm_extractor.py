"""Tests for LLMClaimExtractor — uses mocked OpenAI responses."""
import json
from unittest.mock import patch, MagicMock

import pytest

from claim_extractor import LLMClaimExtractor
from schemas import ExtractedClaim


METADATA = {
    "primary_company_ticker": "NVDA",
    "title": "Q4 Earnings",
    "source_type": "earnings_transcript",
}

VALID_CLAIM_DICT = {
    "claim_text_normalized": "Revenue grew 93% year-over-year to $22.1 billion",
    "claim_text_short": "Revenue up 93% YoY",
    "claim_type": "demand",
    "economic_channel": "revenue",
    "direction": "positive",
    "strength": 0.9,
    "time_horizon": "Q4 FY2025",
    "novelty_type": "new",
    "confidence": 0.85,
    "is_structural": False,
    "is_ephemeral": False,
    "affected_tickers": ["NVDA"],
    "themes": ["AI Infrastructure Spend"],
    "thesis_link_type": "supports",
}

SECOND_CLAIM_DICT = {
    "claim_text_normalized": "Gross margin expanded to 76% from 73%",
    "claim_text_short": "Margin expansion to 76%",
    "claim_type": "margin",
    "economic_channel": "gross_margin",
    "direction": "positive",
    "strength": 0.7,
    "novelty_type": "confirming",
    "confidence": 0.8,
    "affected_tickers": ["NVDA"],
    "themes": ["Margin Expansion"],
    "thesis_link_type": "supports",
}


def _mock_openai_response(content: str):
    """Create a mock OpenAI ChatCompletion response."""
    choice = MagicMock()
    choice.message.content = content
    response = MagicMock()
    response.choices = [choice]
    return response


class TestLLMExtractorParsing:

    @patch("llm_client.get_openai_client")
    def test_successful_single_claim(self, mock_get_client):
        client = MagicMock()
        client.chat.completions.create.return_value = _mock_openai_response(
            json.dumps({"claims": [VALID_CLAIM_DICT]})
        )
        mock_get_client.return_value = client

        extractor = LLMClaimExtractor()
        claims = extractor.extract_claims("Revenue grew 93%.", METADATA)

        assert len(claims) == 1
        assert isinstance(claims[0], ExtractedClaim)
        assert claims[0].claim_type.value == "demand"
        assert claims[0].affected_tickers == ["NVDA"]

    @patch("llm_client.get_openai_client")
    def test_successful_multiple_claims(self, mock_get_client):
        client = MagicMock()
        client.chat.completions.create.return_value = _mock_openai_response(
            json.dumps({"claims": [VALID_CLAIM_DICT, SECOND_CLAIM_DICT]})
        )
        mock_get_client.return_value = client

        extractor = LLMClaimExtractor()
        claims = extractor.extract_claims("Revenue grew. Margins expanded.", METADATA)

        assert len(claims) == 2
        assert claims[0].claim_text_short == "Revenue up 93% YoY"
        assert claims[1].claim_type.value == "margin"

    @patch("llm_client.get_openai_client")
    def test_bare_json_array(self, mock_get_client):
        """LLM returns a bare array instead of a wrapper object."""
        client = MagicMock()
        client.chat.completions.create.return_value = _mock_openai_response(
            json.dumps([VALID_CLAIM_DICT])
        )
        mock_get_client.return_value = client

        extractor = LLMClaimExtractor()
        claims = extractor.extract_claims("text", METADATA)
        assert len(claims) == 1


class TestLLMExtractorErrorHandling:

    @patch("llm_client.get_openai_client")
    def test_malformed_json_returns_empty(self, mock_get_client):
        """Completely invalid JSON from LLM should raise."""
        client = MagicMock()
        client.chat.completions.create.return_value = _mock_openai_response(
            "This is not JSON at all"
        )
        mock_get_client.return_value = client

        extractor = LLMClaimExtractor()
        with pytest.raises(json.JSONDecodeError):
            extractor.extract_claims("text", METADATA)

    @patch("llm_client.get_openai_client")
    def test_empty_claims_array(self, mock_get_client):
        """LLM returns an empty array — should return empty list."""
        client = MagicMock()
        client.chat.completions.create.return_value = _mock_openai_response(
            json.dumps({"claims": []})
        )
        mock_get_client.return_value = client

        extractor = LLMClaimExtractor()
        claims = extractor.extract_claims("text", METADATA)
        assert claims == []

    @patch("llm_client.get_openai_client")
    def test_validation_failure_skips_bad_claims(self, mock_get_client):
        """If one claim fails Pydantic validation, it's skipped; valid ones kept."""
        bad_claim = {"claim_text_normalized": "bad", "claim_type": "INVALID_TYPE"}
        client = MagicMock()
        client.chat.completions.create.return_value = _mock_openai_response(
            json.dumps({"claims": [bad_claim, VALID_CLAIM_DICT]})
        )
        mock_get_client.return_value = client

        extractor = LLMClaimExtractor()
        claims = extractor.extract_claims("text", METADATA)

        assert len(claims) == 1
        assert claims[0].claim_text_short == "Revenue up 93% YoY"

    @patch("llm_client.get_openai_client")
    def test_all_claims_invalid_returns_empty(self, mock_get_client):
        """All claims fail validation — returns empty list."""
        bad1 = {"claim_text_normalized": "bad", "strength": 5.0}  # strength > 1
        bad2 = {"garbage": True}
        client = MagicMock()
        client.chat.completions.create.return_value = _mock_openai_response(
            json.dumps({"claims": [bad1, bad2]})
        )
        mock_get_client.return_value = client

        extractor = LLMClaimExtractor()
        claims = extractor.extract_claims("text", METADATA)
        assert claims == []

    @patch("llm_client.get_openai_client")
    def test_api_failure_retries_then_raises(self, mock_get_client):
        """Transient API errors should retry and eventually raise."""
        client = MagicMock()
        client.chat.completions.create.side_effect = ConnectionError("timeout")
        mock_get_client.return_value = client

        extractor = LLMClaimExtractor()
        with pytest.raises(RuntimeError, match="failed after 3 retries"):
            extractor.extract_claims("text", METADATA)

        assert client.chat.completions.create.call_count == 3


class TestLLMExtractorWrapperKeys:

    @patch("llm_client.get_openai_client")
    def test_results_key(self, mock_get_client):
        """LLM wraps in {"results": [...]}."""
        client = MagicMock()
        client.chat.completions.create.return_value = _mock_openai_response(
            json.dumps({"results": [VALID_CLAIM_DICT]})
        )
        mock_get_client.return_value = client

        extractor = LLMClaimExtractor()
        claims = extractor.extract_claims("text", METADATA)
        assert len(claims) == 1

    @patch("llm_client.get_openai_client")
    def test_unknown_wrapper_key_raises(self, mock_get_client):
        """LLM returns {"foo": [...]} — no recognizable key."""
        client = MagicMock()
        client.chat.completions.create.return_value = _mock_openai_response(
            json.dumps({"foo": [VALID_CLAIM_DICT]})
        )
        mock_get_client.return_value = client

        extractor = LLMClaimExtractor()
        with pytest.raises(json.JSONDecodeError):
            extractor.extract_claims("text", METADATA)
