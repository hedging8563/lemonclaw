from lemonclaw.bus.events import OutboundMessage
from lemonclaw.channels.manager import ChannelManager


def test_activity_session_key_includes_message_thread_id() -> None:
    msg = OutboundMessage(
        channel="telegram",
        chat_id="-100123",
        content="hello",
        metadata={"message_thread_id": 456},
    )

    assert ChannelManager._activity_session_key(msg) == "telegram:-100123:456"


def test_telegram_progress_and_final_are_skipped_from_manager_broadcast() -> None:
    progress = OutboundMessage(
        channel="telegram",
        chat_id="12345",
        content="partial",
        metadata={"_progress": True, "_chunk": True},
    )
    final = OutboundMessage(
        channel="telegram",
        chat_id="12345",
        content="final",
        metadata={"_final": True},
    )
    regular = OutboundMessage(
        channel="telegram",
        chat_id="12345",
        content="regular",
        metadata={},
    )

    assert ChannelManager._should_skip_activity_broadcast(progress) is True
    assert ChannelManager._should_skip_activity_broadcast(final) is True
    assert ChannelManager._should_skip_activity_broadcast(regular) is False


def test_thinking_is_skipped_from_manager_broadcast() -> None:
    thinking = OutboundMessage(
        channel="feishu",
        chat_id="ou_xxx",
        content="internal reasoning",
        metadata={"_progress": True, "_thinking": True},
    )

    assert ChannelManager._should_skip_activity_broadcast(thinking) is True


def test_thinking_and_chunk_are_internal_messages() -> None:
    thinking = OutboundMessage(channel="discord", chat_id="1", content="thinking", metadata={"_progress": True, "_thinking": True})
    chunk = OutboundMessage(channel="discord", chat_id="1", content="chunk", metadata={"_progress": True, "_chunk": True})

    assert ChannelManager._is_internal_message(thinking) is True
    assert ChannelManager._is_internal_message(chunk) is True


def test_tool_start_and_result_are_internal_messages() -> None:
    tool_start = OutboundMessage(channel="feishu", chat_id="ou_xxx", content='{"name":"web_search"}', metadata={"_progress": True, "_tool_start": True})
    tool_result = OutboundMessage(channel="feishu", chat_id="ou_xxx", content='{"name":"web_search","result":"ok"}', metadata={"_progress": True, "_tool_result": True})

    assert ChannelManager._is_internal_message(tool_start) is True
    assert ChannelManager._is_internal_message(tool_result) is True
