"""Shared fixtures for LemonClaw tests."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lemonclaw.agent.tools.base import Tool
from lemonclaw.bus.queue import MessageBus
from lemonclaw.providers.base import LLMResponse, ToolCallRequest


class EchoProvider:
    """Mock provider that echoes back the user message or executes scripted responses."""

    def __init__(self):
        self.responses: list[LLMResponse] = []
        self._call_count = 0

    def get_default_model(self) -> str:
        return "test-model"

    async def chat(self, messages: list, **kwargs: Any) -> LLMResponse:
        if self.responses:
            idx = min(self._call_count, len(self.responses) - 1)
            self._call_count += 1
            return self.responses[idx]
        # Default: echo last user message
        last_user = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                content = m.get("content", "")
                if isinstance(content, str):
                    last_user = content
                break
        return LLMResponse(
            content=f"Echo: {last_user}",
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )


@pytest.fixture
def echo_provider():
    return EchoProvider()


@pytest.fixture
def tmp_workspace(tmp_path):
    """Create a temporary workspace with required structure."""
    (tmp_path / "skills").mkdir()
    (tmp_path / "memory").mkdir()
    (tmp_path / "sessions").mkdir()
    return tmp_path


@pytest.fixture
def make_agent_loop(tmp_workspace, echo_provider):
    """Factory fixture to create AgentLoop with mocked dependencies."""
    def _make(**overrides):
        from lemonclaw.agent.loop import AgentLoop

        bus = MessageBus()
        defaults = dict(
            bus=bus,
            provider=echo_provider,
            workspace=tmp_workspace,
            model="test-model",
            max_iterations=10,
            memory_window=20,
        )
        defaults.update(overrides)

        with patch("lemonclaw.agent.loop.SubagentManager") as MockSub:
            MockSub.return_value.cancel_by_session = AsyncMock(return_value=0)
            loop = AgentLoop(**defaults)

        return loop, bus

    return _make
