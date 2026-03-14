from __future__ import annotations

from lemonclaw.bus.events import OutboundMessage
from lemonclaw.channels.delivery_context import (
    DELIVERY_CONTEXT_KEY,
    apply_delivery_route,
    attach_delivery_context,
    build_delivery_context,
    get_delivery_context,
    resolve_delivery_route,
    resolve_delivery_session_key,
)


def test_build_delivery_context_for_telegram_maps_reply_fields() -> None:
    context = build_delivery_context(
        channel="telegram",
        chat_id="12345",
        session_key="telegram:12345:456",
        metadata={"message_id": 321, "message_thread_id": 456},
    )

    assert context["source_channel"] == "telegram"
    assert context["source_chat_id"] == "12345"
    assert context["session_key"] == "telegram:12345:456"
    assert context["route"] == {"reply_to_message_id": 321, "message_thread_id": 456}


def test_attach_delivery_context_is_idempotent() -> None:
    metadata = attach_delivery_context(
        channel="email",
        chat_id="alice@example.com",
        session_key="email:alice@example.com",
        metadata={"message_id": "<m1@example.com>"},
    )
    attached = attach_delivery_context(
        channel="email",
        chat_id="alice@example.com",
        session_key="email:alice@example.com",
        metadata=metadata,
    )

    assert attached == metadata
    assert get_delivery_context(attached)["route"]["message_id"] == "<m1@example.com>"


def test_resolve_delivery_route_rejects_cross_channel_or_chat() -> None:
    metadata = attach_delivery_context(
        channel="slack",
        chat_id="C123",
        session_key="slack:C123:ts1",
        metadata={"slack": {"thread_ts": "ts1", "channel_type": "channel"}},
    )

    assert resolve_delivery_route(metadata=metadata, channel="telegram", chat_id="C123") == {}
    assert resolve_delivery_route(metadata=metadata, channel="slack", chat_id="C999") == {}


def test_resolve_delivery_session_key_rejects_cross_channel_or_chat() -> None:
    metadata = attach_delivery_context(
        channel="telegram",
        chat_id="12345",
        session_key="telegram:12345:456",
        metadata={"message_id": 321, "message_thread_id": 456},
    )

    assert resolve_delivery_session_key(metadata=metadata, channel="telegram", chat_id="12345") == "telegram:12345:456"
    assert resolve_delivery_session_key(metadata=metadata, channel="telegram", chat_id="99999") is None


def test_apply_delivery_route_mutates_outbound_message_in_place() -> None:
    msg = OutboundMessage(
        channel="telegram",
        chat_id="12345",
        content="hello",
        metadata={
            DELIVERY_CONTEXT_KEY: {
                "source_channel": "telegram",
                "source_chat_id": "12345",
                "session_key": "telegram:12345:456",
                "route": {"reply_to_message_id": 321, "message_thread_id": 456},
            }
        },
    )

    result = apply_delivery_route(msg)

    assert result is None
    assert msg.metadata["message_id"] == 321
    assert msg.metadata["message_thread_id"] == 456
    assert DELIVERY_CONTEXT_KEY not in msg.metadata


def test_apply_delivery_route_sets_reply_to_for_discord() -> None:
    msg = OutboundMessage(
        channel="discord",
        chat_id="chan1",
        content="hello",
        metadata={
            DELIVERY_CONTEXT_KEY: {
                "source_channel": "discord",
                "source_chat_id": "chan1",
                "session_key": "discord:chan1",
                "route": {"reply_to": "msg123"},
            }
        },
    )

    apply_delivery_route(msg)

    assert msg.reply_to == "msg123"
    assert DELIVERY_CONTEXT_KEY not in msg.metadata
