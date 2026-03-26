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
