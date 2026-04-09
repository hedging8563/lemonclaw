"""Helpers for proactive runtime restart notifications."""

from __future__ import annotations

from typing import Any

from lemonclaw.agent.locale import session_lang, t
from lemonclaw.bus.events import OutboundMessage


def _build_notice_text(stage: str, *, lang: str, state: dict[str, Any]) -> str:
    fields = ", ".join(state.get("restart_fields") or []) if state.get("restart_fields") else "none"
    errors = "; ".join(str(item) for item in list(state.get("runtime_errors") or []) if str(item)) or "none"
    if stage == "submitted":
        return t("runtime_notice_submitted", lang, fields=fields)
    if stage == "restarting":
        return t("runtime_notice_restarting", lang, fields=fields)
    if stage == "healthy":
        return t("runtime_notice_healthy", lang, version=str(state.get("version") or "unknown"))
    if stage == "failed":
        return t("runtime_notice_failed", lang, errors=errors)
    return t("runtime_notice_submitted", lang, fields=fields)


async def broadcast_restart_notice(
    agent_loop: Any,
    *,
    stage: str,
    state: dict[str, Any],
) -> int:
    bus = getattr(agent_loop, "bus", None)
    sessions = getattr(agent_loop, "sessions", None)
    targets = list(state.get("notify_targets") or [])
    if bus is None or sessions is None or not targets:
        return 0

    sent = 0
    for target in targets:
        session_key = str(target.get("session_key") or "")
        channel = str(target.get("channel") or "")
        chat_id = str(target.get("chat_id") or "")
        if not session_key or not channel or not chat_id:
            continue
        session = sessions._load(session_key) if hasattr(sessions, "_load") else None
        lang = session_lang(session)
        content = _build_notice_text(stage, lang=lang, state=state)
        await bus.publish_outbound(
            OutboundMessage(
                channel=channel,
                chat_id=chat_id,
                content=content,
                metadata={
                    "_agentbridge_skip_session_persist": True,
                    "_ui_notice_text": content,
                    "_ui_notice_kind": "runtime_restart",
                    "_ui_notice_level": "warning" if stage == "failed" else "info",
                },
            )
        )
        sent += 1
    return sent
