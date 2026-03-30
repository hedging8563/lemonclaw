from __future__ import annotations

from typing import Any

SESSION_CONTEXT_KEY = "_session_context"
_VALID_RUN_MODES = {"interactive", "detached", "system"}


def _normalize_run_mode(value: Any) -> str:
    mode = str(value or "interactive").strip().lower()
    return mode if mode in _VALID_RUN_MODES else "interactive"


def _derive_account(meta: dict[str, Any]) -> str:
    for key in ("account_id", "account", "bot_id", "tenant_id"):
        value = meta.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _derive_thread_and_topic(*, channel: str, meta: dict[str, Any]) -> tuple[str, str]:
    thread = str(meta.get("thread_id") or "")
    topic = str(meta.get("topic_id") or "")

    if channel == "telegram":
        marker = str(meta.get("message_thread_id") or "")
        if marker:
            thread = thread or marker
            topic = topic or marker
    elif channel == "slack":
        slack_meta = meta.get("slack")
        if isinstance(slack_meta, dict):
            thread = thread or str(slack_meta.get("thread_ts") or "")
    elif channel == "matrix":
        thread = thread or str(meta.get("thread_root_event_id") or "")
    elif channel == "agentbridge":
        bridge_meta = meta.get("agentbridge")
        if isinstance(bridge_meta, dict):
            thread = thread or str(bridge_meta.get("thread_id") or "")
    return thread, topic


def build_session_context(
    *,
    channel: str,
    chat_id: str,
    session_key: str,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    meta = dict(metadata or {})
    thread, topic = _derive_thread_and_topic(channel=channel, meta=meta)
    return {
        "session_key": str(session_key),
        "identity": {
            "channel": str(channel),
            "account": _derive_account(meta),
            "chat": str(chat_id),
            "thread": thread,
            "topic": topic,
        },
        "timezone": str(meta.get("timezone") or "").strip(),
        "run_mode": _normalize_run_mode(meta.get("run_mode")),
    }


def attach_session_context(
    *,
    channel: str,
    chat_id: str,
    session_key: str,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    meta = dict(metadata or {})
    if SESSION_CONTEXT_KEY in meta:
        return meta
    meta[SESSION_CONTEXT_KEY] = build_session_context(
        channel=channel,
        chat_id=chat_id,
        session_key=session_key,
        metadata=meta,
    )
    return meta


def get_session_context(metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(metadata, dict):
        return None
    context = metadata.get(SESSION_CONTEXT_KEY)
    return context if isinstance(context, dict) else None
