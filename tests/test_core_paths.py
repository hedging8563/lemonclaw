"""P1 #3: Core path tests — base channel ACL, session LRU, entity on_write, conductor retry."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── 1. Base Channel ACL ─────────────────────────────────────────────────


@dataclass
class _FakeConfig:
    allow_from: list[str] = field(default_factory=list)


class _FakeChannel:
    """Minimal stand-in that reuses BaseChannel.is_allowed logic."""

    def __init__(self, allow_from: list[str]):
        self.config = _FakeConfig(allow_from=allow_from)
        self.name = "test"

    def is_allowed(self, sender_id: str) -> bool:
        from lemonclaw.channels.base import BaseChannel
        return BaseChannel.is_allowed(self, sender_id)


class TestBaseChannelACL:
    def test_empty_allow_from_denies_all(self):
        ch = _FakeChannel([])
        assert ch.is_allowed("anyone") is False

    def test_exact_match_allows(self):
        ch = _FakeChannel(["user123"])
        assert ch.is_allowed("user123") is True

    def test_non_matching_denied(self):
        ch = _FakeChannel(["user123"])
        assert ch.is_allowed("user456") is False

    def test_pipe_separated_sender(self):
        """Sender IDs with | should match if any part is in allow_from."""
        ch = _FakeChannel(["alice"])
        assert ch.is_allowed("alice|bob") is True
        assert ch.is_allowed("bob|charlie") is False

    def test_multiple_allow_from(self):
        ch = _FakeChannel(["alice", "bob"])
        assert ch.is_allowed("alice") is True
        assert ch.is_allowed("bob") is True
        assert ch.is_allowed("charlie") is False


# ── 2. Session Manager LRU ──────────────────────────────────────────────


class TestSessionManagerLRU:
    def test_lru_eviction(self, tmp_path: Path):
        from lemonclaw.session.manager import SessionManager

        mgr = SessionManager(tmp_path)
        mgr._MAX_CACHED_SESSIONS = 3  # Low limit for testing

        s1 = mgr.get_or_create("a:1")
        s2 = mgr.get_or_create("a:2")
        s3 = mgr.get_or_create("a:3")
        assert len(mgr._cache) == 3

        # Adding a 4th should evict the oldest (a:1)
        s4 = mgr.get_or_create("a:4")
        assert len(mgr._cache) <= 3
        assert "a:1" not in mgr._cache

    def test_touch_refreshes_order(self, tmp_path: Path):
        from lemonclaw.session.manager import SessionManager

        mgr = SessionManager(tmp_path)
        mgr._MAX_CACHED_SESSIONS = 3

        mgr.get_or_create("a:1")
        mgr.get_or_create("a:2")
        mgr.get_or_create("a:3")

        # Touch a:1 to refresh it
        mgr.get_or_create("a:1")

        # Now a:2 should be oldest
        mgr.get_or_create("a:4")
        assert "a:2" not in mgr._cache
        assert "a:1" in mgr._cache

    def test_save_updates_cache(self, tmp_path: Path):
        from lemonclaw.session.manager import SessionManager

        mgr = SessionManager(tmp_path)
        session = mgr.get_or_create("test:1")
        session.add_message("user", "hello")
        mgr.save(session)

        # Reload from disk
        mgr.invalidate("test:1")
        reloaded = mgr.get_or_create("test:1")
        assert len(reloaded.messages) == 1
        assert reloaded.messages[0]["content"] == "hello"


# ── 3. Entity Store on_write Callback ────────────────────────────────────


class TestEntityStoreOnWrite:
    def test_on_write_called_on_create(self, tmp_path: Path):
        from lemonclaw.memory.entities import EntityStore

        calls: list[tuple[str, str]] = []
        store = EntityStore(tmp_path, on_write=lambda n, b: calls.append((n, b)))
        store.create_card("test-card", "test", ["kw1"], body="# Test\n")

        assert len(calls) == 1
        assert calls[0][0] == "test-card"

    def test_on_write_called_on_update(self, tmp_path: Path):
        from lemonclaw.memory.entities import EntityStore

        calls: list[tuple[str, str]] = []
        store = EntityStore(tmp_path, on_write=lambda n, b: calls.append((n, b)))
        store.create_card("test-card", "test", ["kw1"], body="# Test\n")
        calls.clear()

        store.update_card("test-card", "# Updated\n")
        assert len(calls) == 1
        assert calls[0][1] == "# Updated\n"

    def test_on_write_not_called_without_callback(self, tmp_path: Path):
        from lemonclaw.memory.entities import EntityStore

        # Should not raise even without callback
        store = EntityStore(tmp_path)
        card = store.create_card("test-card", "test", ["kw1"], body="# Test\n")
        assert card is not None

    def test_on_write_exception_swallowed(self, tmp_path: Path):
        from lemonclaw.memory.entities import EntityStore

        def bad_callback(n, b):
            raise RuntimeError("boom")

        store = EntityStore(tmp_path, on_write=bad_callback)
        # Should not raise
        card = store.create_card("test-card", "test", ["kw1"], body="# Test\n")
        assert card is not None


# ── 4. Session get_history Alignment ─────────────────────────────────────


class TestSessionGetHistory:
    def test_drops_leading_non_user_messages(self):
        from lemonclaw.session.manager import Session

        s = Session(key="test")
        s.add_message("assistant", "hi")
        s.add_message("user", "hello")
        s.add_message("assistant", "world")

        history = s.get_history()
        assert history[0]["role"] == "user"
        assert len(history) == 2

    def test_empty_when_no_user_message(self):
        from lemonclaw.session.manager import Session

        s = Session(key="test")
        s.add_message("assistant", "hi")
        s.add_message("assistant", "there")

        assert s.get_history() == []

    def test_respects_last_consolidated(self):
        from lemonclaw.session.manager import Session

        s = Session(key="test")
        for i in range(10):
            s.add_message("user" if i % 2 == 0 else "assistant", f"msg{i}")
        s.last_consolidated = 6

        history = s.get_history()
        # Should only include messages from index 6 onwards
        assert len(history) <= 4


# ── 5. Conductor Retry + Degradation ─────────────────────────────────────


class TestConductorRetryDegradation:
    @pytest.mark.asyncio
    async def test_all_failed_returns_none(self):
        """When all subtasks fail, handle_message should return None (degrade to single-agent)."""
        from lemonclaw.conductor.types import (
            IntentAnalysis,
            TaskComplexity,
        )

        mock_provider = AsyncMock()
        mock_bus = MagicMock()
        mock_registry = MagicMock()
        mock_registry.list_agents.return_value = []

        from lemonclaw.conductor.orchestrator import Orchestrator

        orch = Orchestrator(mock_provider, mock_bus, mock_registry, max_retries=0)

        # Mock _analyze to return COMPLEX
        intent = IntentAnalysis(
            complexity=TaskComplexity.COMPLEX,
            required_skills=["general"],
            reasoning="test",
            summary="test complex task",
        )

        with patch.object(orch, "_analyze", return_value=intent), \
             patch.object(orch, "_split") as mock_split, \
             patch.object(orch, "_assign", return_value=None), \
             patch.object(orch, "_monitor") as mock_monitor:

            from lemonclaw.conductor.types import (
                OrchestrationPlan,
                OrchestratorPhase,
                SubTask,
                SubTaskStatus,
            )

            plan = OrchestrationPlan(
                request_id="test123",
                original_message="test task",
                intent=intent,
                phase=OrchestratorPhase.SPLITTING,
            )
            plan.subtasks = [
                SubTask(id="t1", description="task 1", status=SubTaskStatus.FAILED, result="error"),
                SubTask(id="t2", description="task 2", status=SubTaskStatus.FAILED, result="error"),
            ]
            mock_split.return_value = plan

            async def fake_monitor(p):
                pass  # subtasks already marked as FAILED
            mock_monitor.side_effect = fake_monitor

            from lemonclaw.bus.events import InboundMessage
            msg = InboundMessage(
                channel="test", sender_id="user1", chat_id="chat1",
                content="complex task",
            )
            result = await orch.handle_message(msg)
            assert result is None  # Degraded to single-agent

    @pytest.mark.asyncio
    async def test_simple_task_returns_none(self):
        """Simple tasks should return None (pass-through)."""
        from lemonclaw.conductor.types import IntentAnalysis, TaskComplexity

        mock_provider = AsyncMock()
        mock_bus = MagicMock()
        mock_registry = MagicMock()

        from lemonclaw.conductor.orchestrator import Orchestrator

        orch = Orchestrator(mock_provider, mock_bus, mock_registry)

        intent = IntentAnalysis(
            complexity=TaskComplexity.SIMPLE,
            required_skills=["general"],
            reasoning="simple task",
            summary="simple hello",
        )

        with patch.object(orch, "_analyze", return_value=intent):
            from lemonclaw.bus.events import InboundMessage
            msg = InboundMessage(
                channel="test", sender_id="user1", chat_id="chat1",
                content="hello",
            )
            result = await orch.handle_message(msg)
            assert result is None


# ── 6. Memory Search upsert_entity ───────────────────────────────────────


class TestMemorySearchUpsert:
    def test_upsert_returns_false_when_unavailable(self):
        """upsert_entity should return False when lancedb is not available."""
        from lemonclaw.memory.search import MemorySearchIndex

        idx = MemorySearchIndex(Path("/tmp/nonexistent"))

        # Directly mock _lancedb_available to return False
        with patch("lemonclaw.memory.search._lancedb_available", return_value=False):
            result = asyncio.get_event_loop().run_until_complete(
                idx.upsert_entity("test", "body", AsyncMock())
            )
            assert result is False
