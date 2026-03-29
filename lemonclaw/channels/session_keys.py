from __future__ import annotations


def build_channel_session_key(
    channel: str,
    chat_id: str,
    *,
    account_id: str | None = None,
    thread_id: str | int | None = None,
    topic_id: str | int | None = None,
    preserve_empty_account_slot: bool = False,
) -> str:
    """Build a stable session key with optional account/thread/topic dimensions.

    The current implementation keeps LemonClaw's existing compact session-key style
    while centralizing the ordering of dimensions:

    - channel
    - optional account
    - chat
    - optional thread/topic suffix
    """

    parts: list[str] = [str(channel)]
    if preserve_empty_account_slot:
        if account_id is not None:
            parts.append(str(account_id))
    elif account_id:
        parts.append(str(account_id))
    parts.append(str(chat_id))
    if thread_id is not None and thread_id != "":
        parts.append(str(thread_id))
    elif topic_id is not None and topic_id != "":
        parts.append(str(topic_id))
    return ":".join(parts)


def build_agentbridge_session_key(
    *,
    client_id: str,
    thread_id: str,
    workspace_id: str = "default",
) -> str:
    """Build the canonical AgentBridge session key."""

    return build_channel_session_key(
        "agentbridge",
        f"{client_id}:{workspace_id}:{thread_id}",
    )


def build_system_session_key(name: str) -> str:
    """Build the canonical session key for system-triggered work."""

    return build_channel_session_key("system", str(name))
