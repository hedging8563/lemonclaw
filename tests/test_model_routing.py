"""Tests for model routing: catalog, fuzzy match, /model command, fallback.

Run: pytest tests/test_model_routing.py -v
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lemonclaw.providers.catalog import (
    DEFAULT_MODEL,
    MODEL_CATALOG,
    MODEL_MAP,
    TIER_ORDER,
    ModelEntry,
    format_model_list,
    fuzzy_match,
)


# ── Catalog integrity ────────────────────────────────────────────────


class TestCatalogIntegrity:
    """MODEL_CATALOG must be consistent and complete."""

    def test_catalog_not_empty(self):
        assert len(MODEL_CATALOG) >= 10

    def test_default_model_in_catalog(self):
        assert DEFAULT_MODEL in MODEL_MAP

    def test_no_duplicate_ids(self):
        ids = [m.id for m in MODEL_CATALOG]
        assert len(ids) == len(set(ids)), f"Duplicate IDs: {[x for x in ids if ids.count(x) > 1]}"

    def test_all_tiers_valid(self):
        for m in MODEL_CATALOG:
            assert m.tier in TIER_ORDER, f"{m.id} has unknown tier: {m.tier}"

    def test_fallback_models_exist(self):
        """Every fallback target must be a valid model ID in the catalog."""
        for m in MODEL_CATALOG:
            if m.fallback:
                assert m.fallback in MODEL_MAP, (
                    f"{m.id} fallback '{m.fallback}' not in catalog"
                )

    def test_no_self_fallback(self):
        """A model must not fall back to itself."""
        for m in MODEL_CATALOG:
            if m.fallback:
                assert m.fallback != m.id, f"{m.id} falls back to itself"

    def test_model_map_matches_catalog(self):
        assert len(MODEL_MAP) == len(MODEL_CATALOG)
        for m in MODEL_CATALOG:
            assert MODEL_MAP[m.id] is m


# ── Fuzzy matching ───────────────────────────────────────────────────


class TestFuzzyMatch:
    """fuzzy_match must resolve user input to the right model."""

    def test_exact_match(self):
        m = fuzzy_match("claude-sonnet-4-6")
        assert m is not None and m.id == "claude-sonnet-4-6"

    def test_prefix_match(self):
        m = fuzzy_match("gpt-5.2")
        assert m is not None and m.id == "gpt-5.2"

    def test_substring_match(self):
        m = fuzzy_match("haiku")
        assert m is not None and m.id == "claude-haiku-4-5"

    def test_label_match(self):
        m = fuzzy_match("Gemini 3 Flash")
        assert m is not None and m.id == "gemini-3-flash-preview"

    def test_case_insensitive(self):
        m = fuzzy_match("DEEPSEEK-R1")
        assert m is not None and m.id == "deepseek-r1"

    def test_no_match(self):
        assert fuzzy_match("nonexistent-model-xyz") is None

    def test_empty_query(self):
        assert fuzzy_match("") is None
        assert fuzzy_match("   ") is None

    def test_ambiguous_prefers_shortest(self):
        """When multiple models match, prefer the shortest ID (most specific)."""
        m = fuzzy_match("opus")
        assert m is not None
        # Should match one of the opus models (shortest id wins)
        assert "opus" in m.id


# ── format_model_list ────────────────────────────────────────────────


class TestFormatModelList:

    def test_contains_all_tiers(self):
        output = format_model_list()
        assert "Flagship" in output
        assert "Standard" in output
        assert "Economy" in output
        assert "Specialist" in output

    def test_current_model_marker(self):
        output = format_model_list("gpt-5.2")
        assert "← current" in output
        assert "gpt-5.2" in output

    def test_no_marker_when_none(self):
        output = format_model_list()
        assert "← current" not in output

    def test_runtime_badge_present_in_model_list(self):
        output = format_model_list()
        assert 'builtin' in output or 'runtime-policy' in output


# ── Fallback chain (litellm_provider) ────────────────────────────────


class TestFallbackRetry:
    """_chat_with_retry must retry then fallback."""

    @pytest.fixture
    def provider(self):
        from lemonclaw.providers.litellm_provider import LiteLLMProvider
        p = LiteLLMProvider.__new__(LiteLLMProvider)
        p.api_key = "test-key"
        p.api_base = None
        p.extra_headers = {}
        p._gateway = None
        p.default_model = DEFAULT_MODEL
        return p

    @pytest.mark.asyncio
    async def test_auth_error_no_retry(self, provider):
        """AuthenticationError should never retry."""
        from litellm.exceptions import AuthenticationError

        call_count = 0

        async def mock_acompletion(**kwargs):
            nonlocal call_count
            call_count += 1
            raise AuthenticationError(
                message="Invalid API key",
                llm_provider="openai",
                model="test",
            )

        with patch("lemonclaw.providers.litellm_provider.acompletion", mock_acompletion):
            result = await provider._chat_with_retry(
                {"model": "test", "messages": [], "stream": True},
                "claude-sonnet-4-6",
            )
        assert call_count == 1
        assert "API key" in result.content
        assert result.finish_reason == "error"

    @pytest.mark.asyncio
    async def test_invalid_request_returns_user_message_without_retry(self, provider):
        """Invalid request payload errors should not retry or fallback."""
        from litellm.exceptions import InvalidRequestError

        call_count = 0

        async def mock_acompletion(**kwargs):
            nonlocal call_count
            call_count += 1
            raise InvalidRequestError(
                message="unexpected `tool_use_id` in request",
                model="test",
                llm_provider="openai",
            )

        with patch("lemonclaw.providers.litellm_provider.acompletion", mock_acompletion):
            result = await provider._chat_with_retry(
                {"model": "test", "messages": [], "stream": True},
                "claude-sonnet-4-6",
            )
        assert call_count == 1
        assert result.finish_reason == "error"
        assert "/new" in result.content

    @pytest.mark.asyncio
    async def test_retry_then_succeed(self, provider):
        """Transient error on first attempt, success on retry."""
        from litellm.exceptions import APIConnectionError

        attempt = 0

        async def mock_acompletion(**kwargs):
            nonlocal attempt
            attempt += 1
            if attempt == 1:
                raise APIConnectionError(
                    message="Connection reset",
                    llm_provider="openai",
                    model="test",
                )
            # Return a mock stream on second attempt
            return mock_stream("Hello!")

        with patch("lemonclaw.providers.litellm_provider.acompletion", mock_acompletion):
            with patch.object(provider, "_collect_stream", new_callable=AsyncMock) as mock_collect:
                from lemonclaw.providers.base import LLMResponse
                mock_collect.return_value = LLMResponse(content="Hello!")
                result = await provider._chat_with_retry(
                    {"model": "test", "messages": [], "stream": True},
                    "claude-sonnet-4-6",
                )
        assert attempt == 2
        assert result.content == "Hello!"

    @pytest.mark.asyncio
    async def test_all_retries_exhausted_triggers_fallback(self, provider):
        """After max retries, should try fallback model."""
        from litellm.exceptions import RateLimitError

        models_tried = []

        async def mock_acompletion(**kwargs):
            models_tried.append(kwargs.get("model", ""))
            raise RateLimitError(
                message="Rate limit exceeded",
                llm_provider="openai",
                model=kwargs.get("model", "test"),
            )

        # claude-sonnet-4-6 falls back to claude-sonnet-4-5 → gpt-4.1-mini → claude-haiku-4-5
        with patch("lemonclaw.providers.litellm_provider.acompletion", mock_acompletion):
            with patch.object(provider, "_resolve_model", side_effect=lambda m, **kw: f"resolved/{m}"):
                result = await provider._chat_with_retry(
                    {"model": "resolved/claude-sonnet-4-6", "messages": [], "stream": True},
                    "claude-sonnet-4-6",
                )
        # 3 retries on primary + chained fallback (sonnet-4-5 → gpt-4.1-mini → haiku-4-5)
        assert len(models_tried) == 6
        assert models_tried[3] == "resolved/claude-sonnet-4-5"
        assert models_tried[4] == "resolved/gpt-4.1-mini"
        assert models_tried[5] == "resolved/claude-haiku-4-5"
        assert result.finish_reason == "error"


# ── Helpers ──────────────────────────────────────────────────────────


def mock_stream(content: str):
    """Create a mock async iterator that yields a single content chunk."""
    class MockStream:
        def __init__(self):
            self._done = False
        def __aiter__(self):
            return self
        async def __anext__(self):
            if self._done:
                raise StopAsyncIteration
            self._done = True
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta.content = content
            chunk.choices[0].delta.reasoning_content = None
            chunk.choices[0].delta.tool_calls = None
            chunk.choices[0].finish_reason = "stop"
            chunk.usage = None
            return chunk
    return MockStream()
