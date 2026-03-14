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
