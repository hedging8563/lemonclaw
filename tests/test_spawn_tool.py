from __future__ import annotations

from types import SimpleNamespace

import pytest

from lemonclaw.agent.tools.spawn import SpawnTool


@pytest.mark.asyncio
async def test_spawn_prefers_per_call_default_context_over_instance_context() -> None:
    calls = []

    async def _spawn(**kwargs):
        calls.append(kwargs)
        return "ok"

    tool = SpawnTool(SimpleNamespace(spawn=_spawn))
    tool.set_context("old", "stale")

    result = await tool.execute(
        task="do work",
        _default_channel="fresh",
        _default_chat_id="target",
        _session_key="fresh:target:thread",
    )

    assert result == "ok"
    assert calls == [{
        "task": "do work",
        "label": None,
        "origin_channel": "fresh",
        "origin_chat_id": "target",
        "session_key": "fresh:target:thread",
    }]


@pytest.mark.asyncio
async def test_spawn_recomputes_session_key_from_per_call_context_when_key_missing() -> None:
    calls = []

    async def _spawn(**kwargs):
        calls.append(kwargs)
        return "ok"

    tool = SpawnTool(SimpleNamespace(spawn=_spawn))
    tool.set_context("old", "stale")

    result = await tool.execute(
        task="do work",
        _default_channel="fresh",
        _default_chat_id="target",
    )

    assert result == "ok"
    assert calls == [{
        "task": "do work",
        "label": None,
        "origin_channel": "fresh",
        "origin_chat_id": "target",
        "session_key": "fresh:target",
    }]


@pytest.mark.asyncio
async def test_spawn_falls_back_to_instance_context_when_no_overrides() -> None:
    calls = []

    async def _spawn(**kwargs):
        calls.append(kwargs)
        return "ok"

    tool = SpawnTool(SimpleNamespace(spawn=_spawn))
    tool.set_context("inst", "ctx")

    result = await tool.execute(task="do work")

    assert result == "ok"
    assert calls == [{
        "task": "do work",
        "label": None,
        "origin_channel": "inst",
        "origin_chat_id": "ctx",
        "session_key": "inst:ctx",
    }]


@pytest.mark.asyncio
async def test_spawn_ignores_partial_per_call_override_to_avoid_mixed_context() -> None:
    calls = []

    async def _spawn(**kwargs):
        calls.append(kwargs)
        return "ok"

    tool = SpawnTool(SimpleNamespace(spawn=_spawn))
    tool.set_context("inst", "ctx")

    result = await tool.execute(task="do work", _default_channel="fresh")

    assert result == "ok"
    assert calls == [{
        "task": "do work",
        "label": None,
        "origin_channel": "inst",
        "origin_chat_id": "ctx",
        "session_key": "inst:ctx",
    }]
