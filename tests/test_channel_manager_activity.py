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
