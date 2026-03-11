"""P1 #3: Core path tests — base channel ACL, session LRU, entity on_write, conductor retry."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
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

    def test_wildcard_allow_from_allows_any_sender(self):
        ch = _FakeChannel(["*"])
        assert ch.is_allowed("alice") is True
        assert ch.is_allowed("bob|charlie") is True


class TestAutoPairing:
    def test_stores_owner_and_pending_notify_targets(self, tmp_path: Path):
        from lemonclaw.channels.auto_pairing import AutoPairing

        pairing = AutoPairing('slack', tmp_path)
        assert pairing.check_or_pair('U1', notify_target='D1') == 'paired'
        assert pairing.owner_notify_target == 'D1'

        assert pairing.check_or_pair('U2', notify_target='D2') == 'pending'
        assert pairing.get_pending_notify_target('U2') == 'D2'
        assert pairing.approve('U2') == 'D2'

    def test_loads_legacy_pending_string_shape(self, tmp_path: Path):
        from lemonclaw.channels.auto_pairing import AutoPairing

        path = tmp_path / 'pairing' / 'telegram.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            'owner': 'alice',
            'approved': ['alice'],
            'pending': {'bob': 'bob'},
        }))

        pairing = AutoPairing('telegram', tmp_path)
        assert pairing.owner_notify_target == 'alice'
        assert pairing.get_pending_notify_target('bob') == 'bob'


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


class TestGroupPolicySemantics:
    def test_legacy_mention_alias_normalizes_to_open_with_require_mention(self):
        from types import SimpleNamespace
        from lemonclaw.channels.base import BaseChannel

        class DummyChannel(BaseChannel):
            async def start(self):
                return None
            async def stop(self):
                return None
            async def send(self, msg):
                return None

        channel = DummyChannel(SimpleNamespace(group_policy='mention', group_require_mention=False, allow_from=[]), None)
        assert channel._resolve_group_gate() == ('open', True)

    def test_allowlist_and_require_mention_are_composable(self):
        from lemonclaw.channels.base import BaseChannel

        assert BaseChannel._group_policy_allows('allowlist', in_allowlist=True, require_mention=True, was_mentioned=True) is True
        assert BaseChannel._group_policy_allows('allowlist', in_allowlist=True, require_mention=True, was_mentioned=False) is False
        assert BaseChannel._group_policy_allows('allowlist', in_allowlist=False, require_mention=True, was_mentioned=True) is False


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

    def test_skips_orphaned_tool_boundary_messages(self):
        from lemonclaw.session.manager import Session

        s = Session(key="test")
        s.messages = [
            {"role": "assistant", "content": "I will inspect it", "tool_calls": [{"id": "call1"}]},
            {"role": "tool", "tool_call_id": "call1", "name": "read_attachment", "content": "binary"},
            {"role": "user", "content": "real question"},
            {"role": "assistant", "content": "real answer"},
        ]

        history = s.get_history(max_messages=3)
        assert [m["role"] for m in history] == ["user", "assistant"]
        assert history[0]["content"] == "real question"

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
            result = asyncio.run(
                idx.upsert_entity("test", "body", AsyncMock())
            )
            assert result is False


@pytest.mark.asyncio
async def test_base_channel_rate_limits_repeated_messages():
    from lemonclaw.channels.base import BaseChannel

    class _Bus:
        def __init__(self):
            self.inbound = []

        async def publish_inbound(self, msg):
            self.inbound.append(msg)

        async def publish_outbound(self, msg):
            return None

    class _Cfg:
        allow_from = ['*']

    class _Channel:
        def __init__(self):
            self.config = _Cfg()
            self.name = 'test'
            self.bus = _Bus()
            self._pairing = None
            self._rate_limit_window_s = 30.0
            self._rate_limit_max_messages = 3
            self._rate_limit_hits = {}

        is_allowed = BaseChannel.is_allowed
        _is_rate_limited = BaseChannel._is_rate_limited
        _run_pairing_flow = BaseChannel._run_pairing_flow
        _handle_message = BaseChannel._handle_message

    ch = _Channel()
    for i in range(5):
        await ch._handle_message('u1', 'c1', f'msg-{i}')

    assert len(ch.bus.inbound) == 3
