from __future__ import annotations

from copy import deepcopy
from typing import Any

from lemonclaw.bus.events import OutboundMessage

DELIVERY_CONTEXT_KEY = "_delivery_context"


def build_delivery_context(
    *,
    channel: str,
    chat_id: str,
    session_key: str,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    meta = metadata or {}
    route: dict[str, Any] = {}

    if channel == "telegram":
        if meta.get("message_id") is not None:
            route["reply_to_message_id"] = meta.get("message_id")
        if meta.get("message_thread_id") is not None:
            route["message_thread_id"] = meta.get("message_thread_id")
    elif channel == "slack":
        if isinstance(slack_meta := meta.get("slack"), dict):
            thread_ts = slack_meta.get("thread_ts")
            channel_type = slack_meta.get("channel_type")
            if thread_ts:
                route["thread_ts"] = thread_ts
            if channel_type:
                route["channel_type"] = channel_type
    elif channel == "matrix":
        for key in ("event_id", "thread_root_event_id", "thread_reply_to_event_id"):
            if meta.get(key):
                route[key] = meta.get(key)
    elif channel == "discord":
        reply_to = meta.get("message_id") or meta.get("reply_to")
        if reply_to:
            route["reply_to"] = reply_to
    elif channel == "mochat":
        if meta.get("message_id"):
            route["reply_to"] = meta.get("message_id")
        if meta.get("group_id") or meta.get("groupId"):
            route["group_id"] = meta.get("group_id") or meta.get("groupId")
    elif channel == "email":
        if meta.get("message_id"):
            route["message_id"] = meta.get("message_id")
    elif channel == "feishu":
        for key in ("message_id", "chat_type", "msg_type", "parent_id", "root_id"):
            if meta.get(key):
                route[key] = meta.get(key)

    return {
        "source_channel": channel,
        "source_chat_id": str(chat_id),
        "session_key": session_key,
        "route": route,
    }


def attach_delivery_context(
    *,
    channel: str,
    chat_id: str,
    session_key: str,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    meta = dict(metadata or {})
    if DELIVERY_CONTEXT_KEY in meta:
        return meta
    meta[DELIVERY_CONTEXT_KEY] = build_delivery_context(
        channel=channel,
        chat_id=chat_id,
        session_key=session_key,
        metadata=meta,
    )
    return meta


def get_delivery_context(metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(metadata, dict):
        return None
    context = metadata.get(DELIVERY_CONTEXT_KEY)
    return context if isinstance(context, dict) else None


def _resolve_delivery_context(
    *,
    metadata: dict[str, Any] | None,
    channel: str,
    chat_id: str,
) -> dict[str, Any] | None:
    context = get_delivery_context(metadata)
    if not context:
        return None
    if context.get("source_channel") != channel:
        return None
    if str(context.get("source_chat_id", "")) != str(chat_id):
        return None
    return context


def resolve_delivery_route(
    *,
    metadata: dict[str, Any] | None,
    channel: str,
    chat_id: str,
) -> dict[str, Any]:
    context = _resolve_delivery_context(metadata=metadata, channel=channel, chat_id=chat_id)
    if not context:
        return {}
    route = context.get("route")
    return deepcopy(route) if isinstance(route, dict) else {}


def resolve_delivery_session_key(
    *,
    metadata: dict[str, Any] | None,
    channel: str,
    chat_id: str,
) -> str | None:
    context = _resolve_delivery_context(metadata=metadata, channel=channel, chat_id=chat_id)
    if not context:
        return None
    session_key = context.get("session_key")
    return str(session_key) if session_key else None


def apply_delivery_route(msg: OutboundMessage) -> None:
    metadata = dict(msg.metadata or {})
    route = resolve_delivery_route(
        metadata=metadata,
        channel=msg.channel,
        chat_id=msg.chat_id,
    )
    metadata.pop(DELIVERY_CONTEXT_KEY, None)
    if not route:
        msg.metadata = metadata
        return

    if msg.channel == "telegram":
        if route.get("reply_to_message_id") and "message_id" not in metadata:
            metadata["message_id"] = route["reply_to_message_id"]
        if route.get("message_thread_id") and "message_thread_id" not in metadata:
            metadata["message_thread_id"] = route["message_thread_id"]
    elif msg.channel == "slack":
        slack_meta = dict(metadata.get("slack") or {})
        if route.get("thread_ts") and "thread_ts" not in slack_meta:
            slack_meta["thread_ts"] = route["thread_ts"]
        if route.get("channel_type") and "channel_type" not in slack_meta:
            slack_meta["channel_type"] = route["channel_type"]
        if slack_meta:
            metadata["slack"] = slack_meta
    elif msg.channel == "matrix":
        for key in ("event_id", "thread_root_event_id", "thread_reply_to_event_id"):
            if route.get(key) and key not in metadata:
                metadata[key] = route[key]
    elif msg.channel == "discord":
        if route.get("reply_to") and not msg.reply_to:
            msg.reply_to = str(route["reply_to"])
    elif msg.channel == "mochat":
        if route.get("reply_to") and not msg.reply_to:
            msg.reply_to = str(route["reply_to"])
        if route.get("group_id") and "group_id" not in metadata and "groupId" not in metadata:
            metadata["group_id"] = route["group_id"]
    elif msg.channel == "email":
        if route.get("message_id") and "message_id" not in metadata:
            metadata["message_id"] = route["message_id"]
    elif msg.channel == "feishu":
        for key in ("message_id", "chat_type", "msg_type", "parent_id", "root_id"):
            if route.get(key) and key not in metadata:
                metadata[key] = route[key]

    msg.metadata = metadata
