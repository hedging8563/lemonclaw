from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from lemonclaw.bus.queue import MessageBus
from lemonclaw.channels.mochat import (
    MochatChannel,
    build_buffered_body,
    extract_mention_ids,
    resolve_require_mention,
    resolve_was_mentioned,
)
from lemonclaw.config.schema import MochatConfig, MochatGroupRule, MochatMentionConfig


def test_extract_mention_ids_handles_strings_and_dicts() -> None:
    assert extract_mention_ids(["u1", {"userId": "u2"}, {"id": "u3"}, {"_id": "u4"}]) == ["u1", "u2", "u3", "u4"]


def test_resolve_was_mentioned_prefers_meta_and_text_fallback() -> None:
    payload = {"meta": {"mentions": [{"userId": "bot1"}]}, "content": "hello"}
    assert resolve_was_mentioned(payload, "bot1") is True
    assert resolve_was_mentioned({"content": "@bot1 hello"}, "bot1") is True
    assert resolve_was_mentioned({"content": "hello"}, "bot1") is False


def test_resolve_require_mention_prefers_group_then_session_then_wildcard() -> None:
    config = MochatConfig(
        groups={
            "groupA": MochatGroupRule(require_mention=True),
            "sessionA": MochatGroupRule(require_mention=False),
            "*": MochatGroupRule(require_mention=True),
        },
        mention=MochatMentionConfig(require_in_groups=False),
    )
    assert resolve_require_mention(config, "sessionA", "groupA") is True
    assert resolve_require_mention(config, "sessionA", "") is False
    assert resolve_require_mention(config, "unknown", "unknown") is True


def test_build_buffered_body_labels_group_entries() -> None:
    body = build_buffered_body(
        [
            SimpleNamespace(raw_body="hello", sender_name="Alice", sender_username="", author="u1"),
            SimpleNamespace(raw_body="world", sender_name="", sender_username="bob", author="u2"),
        ],
        is_group=True,
    )
    assert "Alice: hello" in body
    assert "bob: world" in body


@pytest.mark.asyncio
async def test_mochat_warns_when_require_mention_without_agent_user_id(tmp_path) -> None:
    config = MochatConfig(
        claw_token="token",
        mention=MochatMentionConfig(require_in_groups=True),
        groups={"group1": MochatGroupRule(require_mention=True)},
        agent_user_id="",
        allow_from=["*"],
    )
    channel = MochatChannel(config, MessageBus())
    channel._handle_message = AsyncMock()

    payload = {
        "messageId": "m1",
        "author": "user1",
        "content": "hello",
        "meta": {},
        "groupId": "group1",
        "authorInfo": {"nickname": "Alice"},
    }
    event = {"type": "message.add", "payload": payload, "timestamp": "2026-03-17T00:00:00Z"}

    await channel._process_inbound_event("panel1", event, "panel")

    channel._handle_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_mochat_warns_only_once_when_agent_user_id_missing(tmp_path, monkeypatch) -> None:
    config = MochatConfig(
        claw_token="token",
        mention=MochatMentionConfig(require_in_groups=True),
        groups={"group1": MochatGroupRule(require_mention=True)},
        agent_user_id="",
        allow_from=["*"],
    )
    channel = MochatChannel(config, MessageBus())
    channel._handle_message = AsyncMock()

    warnings: list[str] = []
    monkeypatch.setattr("lemonclaw.channels.mochat.logger.warning", lambda msg, *args: warnings.append(msg.format(*args)))

    payload = {
        "messageId": "m1",
        "author": "user1",
        "content": "hello",
        "meta": {},
        "groupId": "group1",
        "authorInfo": {"nickname": "Alice"},
    }
    event = {"type": "message.add", "payload": payload, "timestamp": "2026-03-17T00:00:00Z"}

    await channel._process_inbound_event("panel1", event, "panel")
    await channel._process_inbound_event("panel1", event, "panel")

    assert len(warnings) == 1
