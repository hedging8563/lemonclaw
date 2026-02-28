"""LiteLLM provider implementation for multi-provider support."""

import asyncio
import json_repair
import os
from typing import Any

import litellm
from litellm import acompletion
from litellm.exceptions import (
    AuthenticationError,
    RateLimitError,
    APIConnectionError,
    APIError,
)
from loguru import logger

from lemonclaw.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from lemonclaw.providers.catalog import MODEL_MAP
from lemonclaw.providers.registry import find_by_model, find_gateway


# Standard OpenAI chat-completion message keys.
_ALLOWED_MSG_KEYS = frozenset({"role", "content", "tool_calls", "tool_call_id", "name"})

# Models that support reasoning_content field (thinking-enabled models).
_REASONING_MODEL_KEYWORDS = ("deepseek-r1", "kimi-k2", "o1", "o3", "o4")


class LiteLLMProvider(LLMProvider):
    """
    LLM provider using LiteLLM for multi-provider support.
    
    Supports OpenRouter, Anthropic, OpenAI, Gemini, MiniMax, and many other providers through
    a unified interface.  Provider-specific logic is driven by the registry
    (see providers/registry.py) — no if-elif chains needed here.
    """
    
    def __init__(
        self, 
        api_key: str | None = None, 
        api_base: str | None = None,
        default_model: str = "anthropic/claude-opus-4-5",
        extra_headers: dict[str, str] | None = None,
        provider_name: str | None = None,
    ):
        super().__init__(api_key, api_base)
        self.default_model = default_model
        self.extra_headers = extra_headers or {}
        
        # Detect gateway / local deployment.
        # provider_name (from config key) is the primary signal;
        # api_key / api_base are fallback for auto-detection.
        self._gateway = find_gateway(provider_name, api_key, api_base)
        
        # Configure environment variables
        if api_key:
            self._setup_env(api_key, api_base, default_model)
        
        if api_base:
            litellm.api_base = api_base
        
        # Disable LiteLLM logging noise
        litellm.suppress_debug_info = True
        # Drop unsupported parameters for providers (e.g., gpt-5 rejects some params)
        litellm.drop_params = True
    
    def _setup_env(self, api_key: str, api_base: str | None, model: str) -> None:
        """Set environment variables based on detected provider."""
        spec = self._gateway or find_by_model(model)
        if not spec:
            return
        if not spec.env_key:
            # OAuth/provider-only specs (for example: openai_codex)
            return

        # Gateway/local overrides existing env; standard provider doesn't
        if self._gateway:
            os.environ[spec.env_key] = api_key
        else:
            os.environ.setdefault(spec.env_key, api_key)

        # Resolve env_extras placeholders:
        #   {api_key}  → user's API key
        #   {api_base} → user's api_base, falling back to spec.default_api_base
        effective_base = api_base or spec.default_api_base
        for env_name, env_val in spec.env_extras:
            resolved = env_val.replace("{api_key}", api_key)
            resolved = resolved.replace("{api_base}", effective_base)
            os.environ.setdefault(env_name, resolved)
    
    def _resolve_model(self, model: str, *, gateway: "ProviderSpec | None" = None) -> str:
        """Resolve model name by applying provider/gateway prefixes.

        Args:
            gateway: Override gateway to use instead of self._gateway.
                     Avoids mutating instance state for concurrent safety.
        """
        gw = gateway if gateway is not None else self._gateway
        if gw:
            # Gateway mode: apply gateway prefix, skip provider-specific prefixes
            prefix = gw.litellm_prefix
            if gw.strip_model_prefix:
                model = model.split("/")[-1]
            if prefix and not model.startswith(f"{prefix}/"):
                model = f"{prefix}/{model}"
            return model

        # Standard mode: auto-prefix for known providers
        spec = find_by_model(model)
        if spec and spec.litellm_prefix:
            model = self._canonicalize_explicit_prefix(model, spec.name, spec.litellm_prefix)
            if not any(model.startswith(s) for s in spec.skip_prefixes):
                model = f"{spec.litellm_prefix}/{model}"

        return model

    def _resolve_gateway_for_model(self, model: str) -> "ProviderSpec | None":
        """Find the correct gateway spec for a model, considering keyword matching.

        When the user switches models at runtime (e.g. claude → kimi), the
        initial _gateway may not match. This method finds the right sibling
        gateway so chat() can override api_base and prefix accordingly.

        Returns None if the current _gateway already matches or no gateway is active.
        """
        if not self._gateway:
            return None
        gw_keywords = self._gateway.keywords
        model_lower = model.lower()

        # If current gateway has keywords and they match this model, keep it.
        if gw_keywords and any(kw in model_lower for kw in gw_keywords):
            return None

        # Find a more specific sibling gateway by model keywords.
        # This handles both: (a) current gateway has wrong keywords,
        # and (b) current gateway is the fallback (no keywords) but a
        # keyword-specific gateway exists (e.g. lemondata_claude for claude models).
        from lemonclaw.providers.registry import PROVIDERS
        for spec in PROVIDERS:
            if not spec.is_gateway:
                continue
            if spec.name == self._gateway.name:
                continue
            if spec.keywords and any(kw in model_lower for kw in spec.keywords):
                return spec

        # No keyword match found — if current gateway is already the fallback, keep it.
        if not gw_keywords:
            return None

        # Current gateway has keywords that don't match — fall back to generic gateway.
        for spec in PROVIDERS:
            if spec.is_gateway and not spec.keywords:
                return spec
        return None

    @staticmethod
    def _canonicalize_explicit_prefix(model: str, spec_name: str, canonical_prefix: str) -> str:
        """Normalize explicit provider prefixes like `github-copilot/...`."""
        if "/" not in model:
            return model
        prefix, remainder = model.split("/", 1)
        if prefix.lower().replace("-", "_") != spec_name:
            return model
        return f"{canonical_prefix}/{remainder}"
    
    def _supports_cache_control(self, model: str, *, gateway: "ProviderSpec | None" = None) -> bool:
        """Return True when the provider supports cache_control on content blocks."""
        gw = gateway if gateway is not None else self._gateway
        if gw is not None:
            return gw.supports_prompt_caching
        spec = find_by_model(model)
        return spec is not None and spec.supports_prompt_caching

    def _apply_cache_control(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None]:
        """Return copies of messages and tools with cache_control injected."""
        new_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                content = msg["content"]
                if isinstance(content, str):
                    new_content = [{"type": "text", "text": content, "cache_control": {"type": "ephemeral"}}]
                else:
                    new_content = list(content)
                    new_content[-1] = {**new_content[-1], "cache_control": {"type": "ephemeral"}}
                new_messages.append({**msg, "content": new_content})
            else:
                new_messages.append(msg)

        new_tools = tools
        if tools:
            new_tools = list(tools)
            new_tools[-1] = {**new_tools[-1], "cache_control": {"type": "ephemeral"}}

        return new_messages, new_tools

    def _apply_model_overrides(self, model: str, kwargs: dict[str, Any]) -> None:
        """Apply model-specific parameter overrides from the registry."""
        model_lower = model.lower()
        spec = find_by_model(model)
        if spec:
            for pattern, overrides in spec.model_overrides:
                if pattern in model_lower:
                    kwargs.update(overrides)
                    return
    
    @staticmethod
    def _sanitize_messages(messages: list[dict[str, Any]], *, keep_reasoning: bool = False) -> list[dict[str, Any]]:
        """Strip non-standard keys and ensure assistant messages have a content key.

        Many OpenAI-compatible gateways reject ``"content": null`` on assistant
        messages (even though the OpenAI spec allows it when tool_calls are
        present).  We normalise to ``""`` which is universally accepted.
        """
        allowed = _ALLOWED_MSG_KEYS | {"reasoning_content"} if keep_reasoning else _ALLOWED_MSG_KEYS
        sanitized = []
        for msg in messages:
            clean = {k: v for k, v in msg.items() if k in allowed}
            # Ensure assistant messages always have a content key.
            # Use "" instead of None — many gateways reject null content.
            if clean.get("role") == "assistant":
                if "content" not in clean or clean["content"] is None:
                    clean["content"] = ""
            sanitized.append(clean)
        return sanitized

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """
        Send a chat completion request via LiteLLM.
        
        Args:
            messages: List of message dicts with 'role' and 'content'.
            tools: Optional list of tool definitions in OpenAI format.
            model: Model identifier (e.g., 'anthropic/claude-sonnet-4-5').
            max_tokens: Maximum tokens in response.
            temperature: Sampling temperature.
        
        Returns:
            LLMResponse with content and/or tool calls.
        """
        original_model = model or self.default_model

        # Dynamic gateway resolution: when user switches models at runtime,
        # the initial gateway may not match (e.g. claude gw for kimi model).
        # We pass the effective gateway as a parameter — never mutate self._gateway.
        effective_gw = self._resolve_gateway_for_model(original_model) or self._gateway

        model = self._resolve_model(original_model, gateway=effective_gw)

        if self._supports_cache_control(original_model, gateway=effective_gw):
            messages, tools = self._apply_cache_control(messages, tools)

        # Clamp max_tokens to at least 1 — negative or zero values cause
        # LiteLLM to reject the request with "max_tokens must be at least 1".
        max_tokens = max(1, max_tokens)

        # Only keep reasoning_content for models that support it
        model_lower = original_model.lower()
        keep_reasoning = any(kw in model_lower for kw in _REASONING_MODEL_KEYWORDS)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": self._sanitize_messages(
                self._sanitize_empty_content(messages), keep_reasoning=keep_reasoning,
            ),
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        # Apply model-specific overrides (e.g. kimi-k2.5 temperature)
        self._apply_model_overrides(model, kwargs)

        # Pass api_key directly — more reliable than env vars alone
        if self.api_key:
            kwargs["api_key"] = self.api_key

        # Pass api_base from the effective gateway
        effective_base = (effective_gw.default_api_base if effective_gw else None) or self.api_base
        if effective_base:
            kwargs["api_base"] = effective_base

        # Pass extra headers (e.g. APP-Code for AiHubMix)
        if self.extra_headers:
            kwargs["extra_headers"] = self.extra_headers

        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        # Always use streaming to work around upstream gateways that drop
        # tool_use.input in non-streaming Anthropic responses (e.g. Packy).
        kwargs["stream"] = True

        logger.debug(
            "LLM request: model={}, api_base={}, effective_gw={}",
            kwargs.get("model"), kwargs.get("api_base", "-"),
            effective_gw.name if effective_gw else None,
        )

        return await self._chat_with_retry(kwargs, original_model)

    # ── Retry + fallback engine ──────────────────────────────────────────

    _MAX_RETRIES = 2
    _RETRY_DELAYS = (1.0, 2.0, 4.0)  # exponential backoff seconds

    async def _chat_with_retry(
        self, kwargs: dict[str, Any], original_model: str,
    ) -> LLMResponse:
        """Call LLM with exponential backoff retries and automatic fallback.

        Retry logic:
        - AuthenticationError: never retry, never fallback
        - RateLimitError / APIConnectionError / APIError: retry up to _MAX_RETRIES
        - All retries exhausted: try fallback model (one shot, no further retries)
        """
        last_error: Exception | None = None

        for attempt in range(1 + self._MAX_RETRIES):
            try:
                response = await acompletion(**kwargs)
                return await self._collect_stream(response)
            except AuthenticationError as e:
                logger.error("Authentication failed: {}", e)
                return LLMResponse(
                    content="API key 无效或已过期，请检查配置。",
                    finish_reason="error",
                )
            except (RateLimitError, APIConnectionError, APIError) as e:
                last_error = e
                if attempt < self._MAX_RETRIES:
                    delay = self._RETRY_DELAYS[min(attempt, len(self._RETRY_DELAYS) - 1)]
                    logger.warning(
                        "LLM error (attempt {}/{}), retrying in {:.0f}s: {}",
                        attempt + 1, 1 + self._MAX_RETRIES, delay, e,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.warning(
                        "LLM error after {} attempts: {}", 1 + self._MAX_RETRIES, e,
                    )
            except Exception as e:
                last_error = e
                logger.error("Unexpected LLM error: {}", e)
                break  # Don't retry unexpected errors

        # All retries exhausted — try fallback model
        entry = MODEL_MAP.get(original_model)
        if entry and entry.fallback and entry.fallback != original_model:
            logger.info("Falling back from {} → {}", original_model, entry.fallback)
            fb_original = entry.fallback
            fb_gw = self._resolve_gateway_for_model(fb_original) or self._gateway
            fb_model = self._resolve_model(fb_original, gateway=fb_gw)
            fb_kwargs = {**kwargs, "model": fb_model}
            # Set correct api_base for fallback model's gateway.
            # The original kwargs may carry a different gateway's api_base
            # (e.g. /v1 for OpenAI-compat) which breaks Anthropic (/v1/v1/messages).
            if fb_gw and fb_gw.default_api_base:
                fb_kwargs["api_base"] = fb_gw.default_api_base
            elif fb_gw and not fb_gw.default_api_base:
                fb_kwargs.pop("api_base", None)  # Let LiteLLM use its default
            try:
                response = await acompletion(**fb_kwargs)
                return await self._collect_stream(response)
            except Exception as fb_err:
                logger.error("Fallback model {} also failed: {}", entry.fallback, fb_err)

        # Everything failed
        error_msg = str(last_error) if last_error else "Unknown error"
        return LLMResponse(
            content=f"LLM 服务暂时不可用: {error_msg}",
            finish_reason="error",
        )
    
    async def _collect_stream(self, stream: Any) -> LLMResponse:
        """Collect streaming chunks into a complete LLMResponse."""
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        # tool_calls indexed by position: {index: {id, name, arguments_parts}}
        tc_accum: dict[int, dict[str, Any]] = {}
        finish_reason = "stop"
        usage: dict[str, int] = {}

        async for chunk in stream:
            if not chunk.choices:
                # Final chunk may carry only usage
                if hasattr(chunk, "usage") and chunk.usage:
                    usage = {
                        "prompt_tokens": chunk.usage.prompt_tokens or 0,
                        "completion_tokens": chunk.usage.completion_tokens or 0,
                        "total_tokens": chunk.usage.total_tokens or 0,
                    }
                continue

            delta = chunk.choices[0].delta
            if chunk.choices[0].finish_reason:
                finish_reason = chunk.choices[0].finish_reason

            # Text content
            if getattr(delta, "content", None):
                content_parts.append(delta.content)

            # Reasoning / thinking content
            if getattr(delta, "reasoning_content", None):
                reasoning_parts.append(delta.reasoning_content)

            # Tool call deltas
            if getattr(delta, "tool_calls", None):
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index if hasattr(tc_delta, "index") else 0
                    if idx not in tc_accum:
                        tc_accum[idx] = {"id": "", "name": "", "arguments_parts": []}
                    acc = tc_accum[idx]
                    if getattr(tc_delta, "id", None):
                        acc["id"] = tc_delta.id
                    if hasattr(tc_delta, "function") and tc_delta.function:
                        if getattr(tc_delta.function, "name", None):
                            acc["name"] = tc_delta.function.name
                        if getattr(tc_delta.function, "arguments", None):
                            acc["arguments_parts"].append(tc_delta.function.arguments)

            # Usage in final chunk
            if hasattr(chunk, "usage") and chunk.usage:
                usage = {
                    "prompt_tokens": chunk.usage.prompt_tokens or 0,
                    "completion_tokens": chunk.usage.completion_tokens or 0,
                    "total_tokens": chunk.usage.total_tokens or 0,
                }

        # Assemble tool calls
        tool_calls: list[ToolCallRequest] = []
        for idx in sorted(tc_accum):
            acc = tc_accum[idx]
            raw_args = "".join(acc["arguments_parts"])
            args = json_repair.loads(raw_args) if raw_args else {}
            tool_calls.append(ToolCallRequest(
                id=acc["id"],
                name=acc["name"],
                arguments=args if isinstance(args, dict) else {},
            ))

        return LLMResponse(
            content="".join(content_parts) or None,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
            reasoning_content="".join(reasoning_parts) or None,
        )

    def get_default_model(self) -> str:
        """Get the default model."""
        return self.default_model
