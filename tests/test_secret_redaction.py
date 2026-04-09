from __future__ import annotations

import json

import pytest

from lemonclaw.bus.events import InboundMessage
from lemonclaw.governance.redaction import contains_sensitive_credential, redact_sensitive_text
from lemonclaw.providers.base import LLMResponse
from lemonclaw.session.manager import SessionManager


def test_redact_sensitive_text_redacts_github_pat_and_direct_token():
    text = "export GITHUB_TOKEN=github_pat_1234567890ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    assert "github_pat_" not in redact_sensitive_text(text)
    assert "[REDACTED]" in redact_sensitive_text(text)
    assert contains_sensitive_credential("Qq5lRL0uytLwD5VRiTfBqALRDvl24XNWGYRPO2YiC2xo")
    recovery = "Use /pairing break-glass lc_recovery_ABCDEFGH1234567890TOKEN"
    assert "lc_recovery_" not in redact_sensitive_text(recovery)
    assert "[REDACTED]" in redact_sensitive_text(recovery)


def test_session_manager_save_redacts_persisted_messages(tmp_path):
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("weixin:test")
    session.messages.extend([
        {
            "role": "user",
            "content": "github_pat_1234567890ABCDEFGHIJKLMNOPQRSTUVWXYZ",
            "timestamp": "2026-04-09T00:00:00",
        },
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "exec",
                        "arguments": json.dumps({
                            "command": "export GITHUB_TOKEN=github_pat_1234567890ABCDEFGHIJKLMNOPQRSTUVWXYZ && git push origin main",
                        }, ensure_ascii=False),
                    },
                }
            ],
            "timestamp": "2026-04-09T00:00:01",
        },
    ])

    manager.save(session)
    session_path = manager._get_session_path("weixin:test")
    persisted = session_path.read_text(encoding="utf-8")
    assert "github_pat_" not in persisted
    assert "[REDACTED]" in persisted


@pytest.mark.asyncio
async def test_process_message_allows_chat_delivered_credentials_but_redacts_persistence(make_agent_loop, echo_provider):
    echo_provider.responses = [LLMResponse(content="Echo response")]
    loop, _bus = make_agent_loop()
    msg = InboundMessage(
        channel="weixin",
        sender_id="u1",
        chat_id="chat1",
        content="export GITHUB_TOKEN=github_pat_1234567890ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    )

    response = await loop._process_message(msg)

    assert response is not None
    assert response.content == "Echo response"
    assert echo_provider._call_count == 1

    session = loop.sessions.get_or_create("weixin:chat1")
    assert len(session.messages) == 2
    assert "github_pat_" not in session.messages[0]["content"]
    assert "[REDACTED]" in session.messages[0]["content"]


@pytest.mark.asyncio
async def test_git_auth_command_saves_profile_for_runtime_use(make_agent_loop):
    loop, _bus = make_agent_loop()
    msg = InboundMessage(
        channel="weixin",
        sender_id="u1",
        chat_id="chat1",
        content="/git-auth set origin :: github_pat_1234567890ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    )

    response = await loop._process_message(msg)

    assert response is not None
    assert "auth_profile=`origin`" in response.content
    git_tool = loop.tools.get("git")
    assert git_tool is not None
    assert git_tool.auth_profiles["origin"]["password"] == "github_pat_1234567890ABCDEFGHIJKLMNOPQRSTUVWXYZ"

    session = loop.sessions.get_or_create("weixin:chat1")
    assert "github_pat_" not in session.messages[0]["content"]
    assert "[REDACTED]" in session.messages[0]["content"]
