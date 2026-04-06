"""Base LLM provider interface."""

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
import json
from typing import Any


def _extract_text_parts(content: Any) -> list[str]:
    parts: list[str] = []

    if content is None:
        return parts

    if isinstance(content, str):
        stripped = content.strip()
        if stripped.startswith(("[", "{")):
            try:
                parsed = json.loads(stripped)
            except Exception:
                return [content]
            parsed_parts = _extract_text_parts(parsed)
            if parsed_parts:
                return parsed_parts
        return [content]

    if isinstance(content, list):
        for item in content:
            parts.extend(_extract_text_parts(item))
        return parts

    if isinstance(content, dict):
        item_type = str(content.get("type") or "")
        if item_type in {"text", "input_text", "output_text"}:
            text = content.get("text")
            if isinstance(text, dict):
                value = text.get("value")
                if isinstance(value, str) and value:
                    return [value]
            if isinstance(text, str) and text:
                return [text]
        nested_content = content.get("content")
        if isinstance(nested_content, (list, dict)):
            return _extract_text_parts(nested_content)
        output = content.get("output")
        if isinstance(output, str) and output:
            return [output]

    return parts


def normalize_text_content(content: Any) -> str | None:
    parts = [part.strip() for part in _extract_text_parts(content) if isinstance(part, str) and part.strip()]
    if not parts:
        return None
    return "\n".join(parts)

# Callback type for streaming text chunks to the caller.
# (delta_text, *, first: bool) — first=True on the first text chunk of a stream.
OnChunkCallback = Callable[..., Awaitable[None]]


@dataclass
class ToolCallRequest:
    """A tool call request from the LLM."""
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    """Response from an LLM provider."""
    content: str | None
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: dict[str, int] = field(default_factory=dict)
    reasoning_content: str | None = None  # Kimi, DeepSeek-R1 etc.
    
    @property
    def has_tool_calls(self) -> bool:
        """Check if response contains tool calls."""
        return len(self.tool_calls) > 0

    def __post_init__(self) -> None:
        self.content = normalize_text_content(self.content)
        self.reasoning_content = normalize_text_content(self.reasoning_content)


class LLMProvider(ABC):
    """
    Abstract base class for LLM providers.
    
    Implementations should handle the specifics of each provider's API
    while maintaining a consistent interface.
    """
    
    def __init__(self, api_key: str | None = None, api_base: str | None = None):
        self.api_key = api_key
        self.api_base = api_base

    @staticmethod
    def _sanitize_empty_content(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Replace empty text content that causes provider 400 errors.

        Empty content can appear when MCP tools return nothing. Most providers
        reject empty-string content or empty text blocks in list content.
        """
        result: list[dict[str, Any]] = []
        for msg in messages:
            content = msg.get("content")

            if isinstance(content, str) and not content:
                clean = dict(msg)
                clean["content"] = None if (msg.get("role") == "assistant" and msg.get("tool_calls")) else "(empty)"
                result.append(clean)
                continue

            if isinstance(content, list):
                filtered = [
                    item for item in content
                    if not (
                        isinstance(item, dict)
                        and item.get("type") in ("text", "input_text", "output_text")
                        and not item.get("text")
                    )
                ]
                if len(filtered) != len(content):
                    clean = dict(msg)
                    if filtered:
                        clean["content"] = filtered
                    elif msg.get("role") == "assistant" and msg.get("tool_calls"):
                        clean["content"] = None
                    else:
                        clean["content"] = "(empty)"
                    result.append(clean)
                    continue

            result.append(msg)
        return result
    
    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        on_chunk: OnChunkCallback | None = None,
    ) -> LLMResponse:
        """
        Send a chat completion request.

        Args:
            messages: List of message dicts with 'role' and 'content'.
            tools: Optional list of tool definitions.
            model: Model identifier (provider-specific).
            max_tokens: Maximum tokens in response.
            temperature: Sampling temperature.
            on_chunk: Optional callback for streaming text deltas.
                      Signature: async (delta: str, *, first: bool) -> None

        Returns:
            LLMResponse with content and/or tool calls.
        """
        pass

    async def embed(
        self,
        texts: list[str],
        model: str | None = None,
    ) -> list[list[float]]:
        """Generate embeddings for the given texts.

        Providers that do not support embeddings may raise NotImplementedError.
        """
        raise NotImplementedError("This provider does not implement embeddings.")

    def count_tokens(self, messages: list[dict[str, Any]], model: str) -> int:
        """Provider-aware token counting helper."""
        raise NotImplementedError("This provider does not implement token counting.")

    def get_context_window(self, model: str) -> int:
        """Provider-aware context-window helper."""
        raise NotImplementedError("This provider does not implement context-window lookup.")
    
    @abstractmethod
    def get_default_model(self) -> str:
        """Get the default model for this provider."""
        pass
