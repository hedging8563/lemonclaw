"""Token-level message compaction.

Unlike consolidation (message-count based, background, writes MEMORY.md),
compaction is token-precise, synchronous, and replaces middle messages
in-place with an LLM summary before each LLM call.

Trigger: total tokens > context_window * THRESHOLD_RATIO
Strategy: keep system prompt + recent N messages → LLM summarize middle
"""

from __future__ import annotations

from typing import Any

from loguru import logger


# ============================================================================
# Configuration
# ============================================================================

THRESHOLD_RATIO = 0.7       # trigger compaction at 70% of context window
RECENT_KEEP = 8             # keep last N messages (4 user-assistant turns)
FALLBACK_CONTEXT_WINDOW = 128_000  # when model info unavailable
SUMMARY_MAX_TOKENS = 1024   # max tokens for the summary output

SUMMARY_SYSTEM_PROMPT = (
    "You are a conversation summarizer. Summarize the following conversation "
    "between a user and an AI assistant.\n"
    "Focus on: key decisions made, important facts/data mentioned, pending tasks, "
    "and context needed for the conversation to continue.\n"
    "Be concise but preserve critical details. Output only the summary."
)


# ============================================================================
# Token counting
# ============================================================================


def count_tokens(messages: list[dict[str, Any]], model: str) -> int:
    """Count tokens in a message list using litellm.

    Falls back to rough char-based estimate if litellm doesn't recognize the model.
    """
    try:
        from litellm import token_counter
        return token_counter(model=model, messages=messages)
    except Exception:
        # Rough estimate: ~4 chars per token for English
        total_chars = sum(len(str(m.get("content", ""))) for m in messages)
        return total_chars // 4


def get_context_window(model: str) -> int:
    """Get the context window size for a model."""
    try:
        from litellm import get_model_info
        info = get_model_info(model)
        return info.get("max_input_tokens") or FALLBACK_CONTEXT_WINDOW
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

    Walks backward from target_idx to find a boundary right before a 'user'
    or 'system' message (i.e., not splitting assistant+tool groups).
    """
    for i in range(target_idx, 0, -1):
        role = messages[i].get("role")
        if role in ("user", "system"):
            return i
    return target_idx


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

    logger.info(
        "compaction: {} tokens > {} threshold, summarizing {} middle messages",
        token_count, threshold, len(middle),
    )

    summary_text = await _summarize(middle, model, provider, max_tokens)

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
) -> str:
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
        return "[Earlier conversation could not be summarized — context condensed]"
