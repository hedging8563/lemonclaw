"""Tests for P2-E memory system enhancements.

Run: pytest tests/test_memory.py -v
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from lemonclaw.agent.memory import (
    CONSOLIDATION_TIMEOUT,
    HISTORY_KEEP_ENTRIES,
    HISTORY_MAX_ENTRIES,
    MemoryStore,
)


@pytest.fixture
def store(tmp_path):
    return MemoryStore(tmp_path)


@pytest.fixture
def mock_session():
    session = MagicMock()
    session.key = "test:session"
    session.messages = [
        {"role": "user", "content": "hello", "timestamp": "2026-03-01T10:00"},
        {"role": "assistant", "content": "hi there", "timestamp": "2026-03-01T10:01"},
        {"role": "user", "content": "do something", "timestamp": "2026-03-01T10:02"},
        {"role": "assistant", "content": "done", "timestamp": "2026-03-01T10:03"},
    ] * 15  # 60 messages
    session.last_consolidated = 0
    return session


@pytest.fixture
def mock_provider():
    from lemonclaw.providers.base import LLMResponse, ToolCallRequest

    provider = AsyncMock()
    provider.chat.return_value = LLMResponse(
        content=None,
        tool_calls=[
            ToolCallRequest(
                id="tc_1",
                name="save_memory",
                arguments={
                    "history_entry": "[2026-03-01 10:00] User greeted bot and asked to do something.",
                    "memory_update": "# Memory\nUser likes greetings.",
                },
            )
        ],
    )
    return provider


# ── Consolidation timeout ─────────────────────────────────────────────


class TestConsolidationTimeout:

    @pytest.mark.asyncio
    async def test_timeout_returns_false(self, store, mock_session):
        """Consolidation should return False on timeout, not hang."""
        slow_provider = AsyncMock()

        async def slow_chat(**kwargs):
            await asyncio.sleep(10)  # Way longer than timeout

        slow_provider.chat = slow_chat

        result = await store.consolidate(
            mock_session, slow_provider, "test-model",
            memory_window=50, timeout=0.1,  # Very short timeout for test
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_success_within_timeout(self, store, mock_session, mock_provider):
        """Normal consolidation should succeed within timeout."""
        result = await store.consolidate(
            mock_session, mock_provider, "test-model",
            memory_window=50,
        )
        assert result is True
        assert store.memory_file.exists()
        assert store.history_file.exists()


# ── Session truncation after consolidation ────────────────────────────


class TestSessionTruncation:

    @pytest.mark.asyncio
    async def test_messages_truncated_after_consolidation(self, store, mock_session, mock_provider):
        """Old messages should be removed after successful consolidation."""
        original_count = len(mock_session.messages)
        assert original_count == 60

        result = await store.consolidate(
            mock_session, mock_provider, "test-model",
            memory_window=50,
        )
        assert result is True
        # Messages should be truncated: only keep_count (50//2=25) remain
        assert len(mock_session.messages) == 25
        assert mock_session.last_consolidated == 0

    @pytest.mark.asyncio
    async def test_archive_all_does_not_truncate(self, store, mock_session, mock_provider):
        """archive_all mode should not truncate (session.clear() handles it)."""
        result = await store.consolidate(
            mock_session, mock_provider, "test-model",
            archive_all=True,
        )
        assert result is True
        # archive_all doesn't truncate — caller (loop.py /new) does session.clear()
        assert len(mock_session.messages) == 60

    @pytest.mark.asyncio
    async def test_no_truncation_on_failure(self, store, mock_session):
        """Failed consolidation should not modify messages."""
        failing_provider = AsyncMock()
        failing_provider.chat.side_effect = Exception("API error")

        original_count = len(mock_session.messages)
        result = await store.consolidate(
            mock_session, failing_provider, "test-model",
            memory_window=50,
        )
        assert result is False
        assert len(mock_session.messages) == original_count


# ── HISTORY.md rolling truncation ─────────────────────────────────────


class TestHistoryTruncation:

    def test_no_truncation_under_limit(self, store):
        """Should not truncate when under HISTORY_MAX_ENTRIES."""
        for i in range(10):
            store.append_history(f"Entry {i}")
        text = store.history_file.read_text()
        entries = [e for e in text.split("\n\n") if e.strip()]
        assert len(entries) == 10

    def test_truncation_over_limit(self, store):
        """Should truncate to HISTORY_KEEP_ENTRIES when over HISTORY_MAX_ENTRIES."""
        total = HISTORY_MAX_ENTRIES + 10
        for i in range(total):
            store.append_history(f"Entry {i}")
        text = store.history_file.read_text()
        entries = [e for e in text.split("\n\n") if e.strip()]
        # After multiple truncations, should be <= HISTORY_KEEP_ENTRIES + entries added after last truncation
        assert len(entries) <= HISTORY_KEEP_ENTRIES + 10
        # Most recent entry should always be present
        assert entries[-1] == f"Entry {total - 1}"

    def test_truncation_preserves_recent(self, store):
        """Truncation should keep the newest entries, not the oldest."""
        total = HISTORY_MAX_ENTRIES + 5
        for i in range(total):
            store.append_history(f"[2026-03-01] Event {i}")
        text = store.history_file.read_text()
        entries = [e for e in text.split("\n\n") if e.strip()]
        # Most recent should be present
        assert f"Event {total - 1}" in entries[-1]
        # Oldest entries should be gone
        assert f"Event 0" not in entries[0]


# ── Memory read/write basics ─────────────────────────────────────────


class TestMemoryBasics:

    def test_read_empty(self, store):
        assert store.read_long_term() == ""

    def test_write_and_read(self, store):
        store.write_long_term("# Test Memory")
        assert store.read_long_term() == "# Test Memory"

    def test_get_memory_context_empty(self, store):
        assert store.get_memory_context() == ""

    def test_get_memory_context_with_content(self, store):
        store.write_long_term("Some facts")
        ctx = store.get_memory_context()
        assert "Long-term Memory" in ctx
        assert "Some facts" in ctx
