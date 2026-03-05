"""Memory system for persistent agent memory."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from lemonclaw.utils.helpers import ensure_dir

if TYPE_CHECKING:
    from lemonclaw.providers.base import LLMProvider
    from lemonclaw.session.manager import Session

# Consolidation timeout — prevents Cloudflare 524 / slow API from blocking session.
CONSOLIDATION_TIMEOUT = 30  # seconds

# HISTORY.md rolling window — truncate when exceeding this many entries.
HISTORY_MAX_ENTRIES = 200
HISTORY_KEEP_ENTRIES = 150

# Max models to try when tool call fails (walk fallback chain).
_MAX_CONSOLIDATION_FALLBACKS = 3


_SAVE_MEMORY_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": "Save the memory consolidation result to persistent storage.",
            "parameters": {
                "type": "object",
                "properties": {
                    "history_entry": {
                        "type": "string",
                        "description": "A paragraph (2-5 sentences) summarizing key events/decisions/topics. "
                        "Start with [YYYY-MM-DD HH:MM]. Include detail useful for grep search.",
                    },
                    "memory_update": {
                        "type": "string",
                        "description": "Full updated long-term memory as markdown. Include all existing "
                        "facts plus new ones. Return unchanged if nothing new.",
                    },
                },
                "required": ["history_entry", "memory_update"],
            },
        },
    }
]


class MemoryStore:
    """Bionic memory: STM (session + today.md + HISTORY.md) + LTM (entity cards) + Core (core.md).

    Layers:
    - STM: session.messages (in-memory) + today.md (daily hot data) + HISTORY.md (timeline log)
    - LTM: memory/entities/*.md (structured Frontmatter + Markdown cards)
    - Core: memory/core.md (high-frequency facts, always in system prompt)
    - Procedural: memory/rules.md (experience rules from reflect, Step 2)
    """

    # Per-workspace write lock — prevents concurrent consolidation from corrupting files.
    # Shared across all sessions that use the same workspace.
    _write_locks: dict[str, asyncio.Lock] = {}

    def __init__(self, workspace: Path):
        from lemonclaw.memory.entities import EntityStore
        from lemonclaw.memory.promote import CorePromoter
        from lemonclaw.memory.reflect import ProceduralMemory
        from lemonclaw.memory.search import MemorySearchIndex
        from lemonclaw.memory.today import TodayLog
        from lemonclaw.memory.trigger import MemoryTrigger

        self.memory_dir = ensure_dir(workspace / "memory")
        self.memory_file = self.memory_dir / "MEMORY.md"
        self.history_file = self.memory_dir / "HISTORY.md"
        self.core_file = self.memory_dir / "core.md"
        self._provider: LLMProvider | None = None

        # Bionic memory layers
        self.search_index = MemorySearchIndex(self.memory_dir)
        self.entities = EntityStore(self.memory_dir, on_write=self._on_entity_write)
        self.today = TodayLog(self.memory_dir)
        self.trigger = MemoryTrigger(self.entities, search_index=self.search_index)
        self.procedural = ProceduralMemory(self.memory_dir)
        self.promoter = CorePromoter(self.memory_dir, self.entities)

        # Get or create a lock for this workspace
        ws_key = str(workspace)
        if ws_key not in MemoryStore._write_locks:
            MemoryStore._write_locks[ws_key] = asyncio.Lock()
        self._lock = MemoryStore._write_locks[ws_key]

    def _on_entity_write(self, name: str, body: str) -> None:
        """Fire-and-forget search index update when an entity card is written."""
        if not self.search_index.available or self._provider is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # No event loop — skip (e.g. migration scripts)
        task = loop.create_task(self.search_index.upsert_entity(name, body, self._provider))
        task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)

    def set_provider(self, provider: LLMProvider) -> None:
        """Bind an LLM provider for search index updates."""
        self._provider = provider

    def read_long_term(self) -> str:
        if self.memory_file.exists():
            return self.memory_file.read_text(encoding="utf-8")
        return ""

    def write_long_term(self, content: str) -> None:
        self.memory_file.write_text(content, encoding="utf-8")

    async def _async_write_long_term(self, content: str) -> None:
        """Non-blocking write for use in async consolidation path."""
        await asyncio.to_thread(self.write_long_term, content)

    def append_history(self, entry: str) -> None:
        """Append a history entry, truncating old entries if file grows too large."""
        with open(self.history_file, "a", encoding="utf-8") as f:
            f.write(entry.rstrip() + "\n\n")

        # Rolling truncation: keep only the most recent entries
        self._truncate_history_if_needed()

    async def _async_append_history(self, entry: str) -> None:
        """Non-blocking append for use in async consolidation path."""
        await asyncio.to_thread(self.append_history, entry)

    def _truncate_history_if_needed(self) -> None:
        """Keep HISTORY.md under HISTORY_MAX_ENTRIES by dropping oldest entries."""
        if not self.history_file.exists():
            return
        text = self.history_file.read_text(encoding="utf-8")
        # Entries are separated by double newlines
        entries = [e for e in text.split("\n\n") if e.strip()]
        if len(entries) <= HISTORY_MAX_ENTRIES:
            return
        kept = entries[-HISTORY_KEEP_ENTRIES:]
        self.history_file.write_text("\n\n".join(kept) + "\n\n", encoding="utf-8")
        logger.info("HISTORY.md truncated: {} → {} entries", len(entries), len(kept))

    def get_memory_context(self) -> str:
        long_term = self.read_long_term()
        return f"## Long-term Memory\n{long_term}" if long_term else ""

    def read_core(self) -> str:
        """Read core.md — high-frequency facts that are always in system prompt."""
        if self.core_file.exists():
            return self.core_file.read_text(encoding="utf-8")
        return ""

    def write_core(self, content: str) -> None:
        self.core_file.write_text(content, encoding="utf-8")

    async def consolidate(
        self,
        session: Session,
        provider: LLMProvider,
        model: str,
        *,
        archive_all: bool = False,
        memory_window: int = 50,
        timeout: float = CONSOLIDATION_TIMEOUT,
    ) -> bool:
        """Consolidate old messages into MEMORY.md + HISTORY.md via LLM tool call.

        Returns True on success (including no-op), False on failure.
        If the model fails or doesn't call save_memory, walks the fallback
        chain from MODEL_MAP before giving up.

        Uses a per-workspace lock to prevent concurrent writes to MEMORY.md/HISTORY.md.
        """
        async with self._lock:
            if archive_all:
                old_messages = session.messages
                keep_count = 0
                logger.info("Memory consolidation (archive_all): {} messages", len(session.messages))
            else:
                keep_count = memory_window // 2
                if len(session.messages) <= keep_count:
                    return True
                if len(session.messages) - session.last_consolidated <= 0:
                    return True
                old_messages = session.messages[session.last_consolidated:-keep_count]
                if not old_messages:
                    return True
                logger.info("Memory consolidation: {} to consolidate, {} keep", len(old_messages), keep_count)

            lines = []
            for m in old_messages:
                if not m.get("content"):
                    continue
                tools = f" [tools: {', '.join(m['tools_used'])}]" if m.get("tools_used") else ""
                lines.append(f"[{m.get('timestamp', '?')[:16]}] {m['role'].upper()}{tools}: {m['content']}")

            current_memory = self.read_long_term()
            prompt = f"""Process this conversation and call the save_memory tool with your consolidation.

IMPORTANT: Do NOT save information about content refusals, safety warnings, or "I can't discuss that" interactions.
These are model artifacts, not useful memories. Focus on actual tasks, preferences, and facts.

## Current Long-term Memory
{current_memory or "(empty)"}

## Conversation to Process
{chr(10).join(lines)}"""

            messages = [
                {"role": "system", "content": "You are a memory consolidation agent. Call the save_memory tool with your consolidation of the conversation."},
                {"role": "user", "content": prompt},
            ]

            # Walk fallback chain: try current model, then its fallbacks
            from lemonclaw.providers.catalog import MODEL_MAP
            current_model = model
            visited: set[str] = set()

            while current_model and current_model not in visited and len(visited) <= _MAX_CONSOLIDATION_FALLBACKS:
                visited.add(current_model)
                try:
                    response = await asyncio.wait_for(
                        provider.chat(
                            messages=messages,
                            tools=_SAVE_MEMORY_TOOL,
                            model=current_model,
                        ),
                        timeout=timeout,
                    )

                    if not response.has_tool_calls:
                        entry = MODEL_MAP.get(current_model)
                        next_model = entry.fallback if entry else None
                        if next_model and next_model not in visited:
                            logger.warning(
                                "Memory consolidation: {} did not call save_memory, trying {}",
                                current_model, next_model,
                            )
                            current_model = next_model
                            continue
                        logger.warning("Memory consolidation: LLM did not call save_memory, giving up")
                        return False

                    args = response.tool_calls[0].arguments
                    if isinstance(args, str):
                        args = json.loads(args)
                    if not isinstance(args, dict):
                        logger.warning("Memory consolidation: unexpected arguments type {}", type(args).__name__)
                        return False

                    if entry := args.get("history_entry"):
                        if not isinstance(entry, str):
                            entry = json.dumps(entry, ensure_ascii=False)
                        await self._async_append_history(entry)
                    if update := args.get("memory_update"):
                        if not isinstance(update, str):
                            update = json.dumps(update, ensure_ascii=False)
                        if update != current_memory:
                            await self._async_write_long_term(update)

                    new_consolidated = 0 if archive_all else len(session.messages) - keep_count
                    session.last_consolidated = new_consolidated

                    if not archive_all and new_consolidated > 0:
                        session.messages = session.messages[new_consolidated:]
                        session.last_consolidated = 0
                        logger.info(
                            "Session truncated: dropped {} old messages, {} remaining",
                            new_consolidated, len(session.messages),
                        )

                    logger.info("Memory consolidation done (model={}): {} messages remaining",
                                current_model, len(session.messages))
                    return True

                except asyncio.TimeoutError:
                    entry = MODEL_MAP.get(current_model)
                    next_model = entry.fallback if entry else None
                    if next_model and next_model not in visited:
                        logger.warning(
                            "Memory consolidation: {} timed out after {}s, trying {}",
                            current_model, timeout, next_model,
                        )
                        current_model = next_model
                        continue
                    logger.warning("Memory consolidation timed out after {}s, giving up", timeout)
                    return False
                except Exception:
                    entry = MODEL_MAP.get(current_model)
                    next_model = entry.fallback if entry else None
                    if next_model and next_model not in visited:
                        logger.warning(
                            "Memory consolidation: {} failed, trying {}",
                            current_model, next_model, exc_info=True,
                        )
                        current_model = next_model
                        continue
                    logger.exception("Memory consolidation failed")
                    return False

            logger.warning("Memory consolidation: exhausted all fallbacks")
            return False
