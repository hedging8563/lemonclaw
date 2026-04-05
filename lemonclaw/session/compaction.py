"""Token-level message compaction.

Unlike consolidation (message-count based, background, writes MEMORY.md),
compaction is token-precise, synchronous, and replaces middle messages
in-place with an LLM summary before each LLM call.

Trigger: total tokens > context_window * THRESHOLD_RATIO
Strategy: keep system prompt + recent N messages → LLM summarize middle
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from loguru import logger

from lemonclaw.providers.litellm_provider import LiteLLMProvider


# ============================================================================
# Configuration
# ============================================================================

THRESHOLD_RATIO = 0.7       # trigger compaction at 70% of context window
RECENT_KEEP = 8             # keep last N messages (4 user-assistant turns)
FALLBACK_CONTEXT_WINDOW = 128_000  # when model info unavailable
SUMMARY_MAX_TOKENS = 1024   # max tokens for the summary output
SUMMARY_FAILURE_COOLDOWN_MS = 60_000

_SUMMARY_FAILURE_CACHE: dict[str, int] = {}

SUMMARY_SYSTEM_PROMPT = (
    "You are a conversation summarizer. Summarize the following conversation "
    "between a user and an AI assistant.\n"
    "Focus on: key decisions made, important facts/data mentioned, pending tasks, "
    "and context needed for the conversation to continue.\n"
    "Be concise but preserve critical details. Output only the summary.\n"
    "IMPORTANT: Write the summary in the same language as the user's messages."
)


# ============================================================================
# Token counting
# ============================================================================


def count_tokens(messages: list[dict[str, Any]], model: str) -> int:
    """Count tokens in a message list using provider-aware helpers.

    Falls back to rough char-based estimate if litellm doesn't recognize the model.
    """
    try:
        provider = LiteLLMProvider()
        return provider.count_tokens(messages, model)
    except Exception:
        # Rough estimate: ~4 chars per token for English
        total_chars = sum(len(str(m.get("content", ""))) for m in messages)
        return total_chars // 4


def get_context_window(model: str) -> int:
    """Get the context window size for a model."""
    try:
        provider = LiteLLMProvider()
        return provider.get_context_window(model)
    except Exception:
        return FALLBACK_CONTEXT_WINDOW


# ============================================================================
# Compaction logic
# ============================================================================


def needs_compaction(messages: list[dict[str, Any]], model: str) -> bool:
    """Check whether messages exceed the compaction threshold."""
    threshold = int(get_context_window(model) * THRESHOLD_RATIO)
    return count_tokens(messages, model) > threshold


def _find_safe_split(messages: list[dict[str, Any]], target_idx: int) -> int:
    """Find a safe split point that doesn't break a tool-call sequence.

    A safe boundary is right before a 'user' message that is NOT a tool
    result (role="tool" or role="user" with tool_call_id).  This ensures
    we never orphan tool_result messages from their preceding
    assistant(tool_use) message.
    """
    for i in range(target_idx, 0, -1):
        role = messages[i].get("role")
        if role == "system":
            return i
        if role == "user" and "tool_call_id" not in messages[i]:
            # Genuine user message — safe to split here
            return i
        # role == "tool" or role == "assistant" or user-with-tool_call_id:
        # keep walking backward to avoid orphaning tool pairs
    return target_idx


def _current_ms() -> int:
    return int(time.time() * 1000)


def _summary_cache_key(messages: list[dict[str, Any]], model: str) -> str:
    digest = hashlib.blake2b(digest_size=16)
    digest.update(model.encode("utf-8"))
    for message in messages:
        digest.update(json.dumps(message, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    return digest.hexdigest()


async def compact(
    messages: list[dict[str, Any]],
    model: str,
    provider: Any,
    *,
    max_tokens: int = SUMMARY_MAX_TOKENS,
) -> list[dict[str, Any]]:
    """Compact messages by LLM-summarizing the middle portion.

    Message layout:
        messages[0]           = system prompt (always keep)
        messages[1:split]     = middle (candidates for summarization)
        messages[split:]      = recent tail (always keep)

    Returns the original list if compaction is not needed or if there
    are too few messages to compact.
    """
    context_window = get_context_window(model)
    threshold = int(context_window * THRESHOLD_RATIO)
    token_count = count_tokens(messages, model)

    if token_count <= threshold:
        return messages

    # Need at least system + some middle + RECENT_KEEP tail
    if len(messages) < RECENT_KEEP + 3:
        logger.debug("compaction: too few messages ({}) to compact", len(messages))
        return messages

    # Split: system | middle | tail
    raw_split = max(2, len(messages) - RECENT_KEEP)
    split_idx = _find_safe_split(messages, raw_split)

    # Ensure we have at least 2 middle messages to summarize
    if split_idx <= 2:
        logger.debug("compaction: split_idx={}, not enough middle to compact", split_idx)
        return messages

    system = messages[0]
    middle = messages[1:split_idx]
    tail = messages[split_idx:]
    cache_key = _summary_cache_key(middle, model)
    last_failed_at = _SUMMARY_FAILURE_CACHE.get(cache_key, 0)
    now_ms = _current_ms()
    if last_failed_at and (now_ms - last_failed_at) < SUMMARY_FAILURE_COOLDOWN_MS:
        logger.debug("compaction: skipping summarize retry during cooldown")
        return messages

    logger.info(
        "compaction: {} tokens > {} threshold, summarizing {} middle messages",
        token_count, threshold, len(middle),
    )

    summary_text = await _summarize(middle, model, provider, max_tokens)
    if summary_text is None:
        _SUMMARY_FAILURE_CACHE[cache_key] = now_ms
        logger.warning("compaction: summarization failed, keeping original messages")
        return messages
    _SUMMARY_FAILURE_CACHE.pop(cache_key, None)

    compacted = [
        system,
        {
            "role": "user",
            "content": (
                "[Conversation Summary — condensed from earlier messages]\n\n"
                f"{summary_text}\n\n"
                "[End of summary — conversation continues below]"
            ),
        },
        *tail,
    ]

    new_count = count_tokens(compacted, model)
    logger.info(
        "compaction: {} → {} tokens (saved {})",
        token_count, new_count, token_count - new_count,
    )
    return compacted


async def _summarize(
    middle: list[dict[str, Any]],
    model: str,
    provider: Any,
    max_tokens: int,
) -> str | None:
    """Use the LLM to summarize a block of messages."""
    # Format middle messages into readable text for the summarizer
    lines: list[str] = []
    for m in middle:
        role = m.get("role", "unknown")
        content = m.get("content", "")
        if isinstance(content, list):
            # Multimodal content — extract text parts
            text_parts = [c.get("text", "") for c in content if c.get("type") == "text"]
            content = "\n".join(text_parts)
        if not content:
            continue

        # Truncate very long individual messages for the summary input
        if len(content) > 2000:
            content = content[:2000] + "... (truncated)"

        if role == "tool":
            name = m.get("name", "tool")
            lines.append(f"[Tool: {name}] {content}")
        else:
            lines.append(f"[{role.title()}] {content}")

    conversation_text = "\n\n".join(lines)

    try:
        response = await provider.chat(
            messages=[
                {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
                {"role": "user", "content": conversation_text},
            ],
            model=model,
            temperature=0.0,
            max_tokens=max_tokens,
        )
        return response.content or "(summary unavailable)"
    except Exception as e:
        logger.warning("compaction: summarization failed: {}", e)
        return None
