"""Helpers for proactive runtime restart notifications."""

from __future__ import annotations

from typing import Any

from lemonclaw.agent.locale import session_lang, t
from lemonclaw.bus.events import OutboundMessage
from lemonclaw.gateway.runtime_state import (
    derive_runtime_state_view,
    derive_restart_notify_targets,
    load_runtime_state,
    mark_runtime_notification_sent,
    set_runtime_notify_targets,
)


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


def _channel_runtime_usable(agent_loop: Any) -> bool:
    channel_manager = getattr(agent_loop, "channel_manager", None)
    if channel_manager is None or not hasattr(channel_manager, "get_channel_status"):
        return True
    try:
        channel_status = channel_manager.get_channel_status() or {}
    except Exception:
        return False
    configured = [
        status for status in channel_status.values()
        if bool((status or {}).get("configured_enabled"))
    ]
    if not configured:
        return True
    for status in configured:
        item = dict(status or {})
        if not bool(item.get("configured_complete", True)):
            return False
        if not bool(item.get("registered", False)):
            return False
        if not bool(item.get("available", False)):
            return False
        if not bool(item.get("running", False)):
            return False
        if str(item.get("error") or "").strip():
            return False
    return True


async def maybe_broadcast_startup_restart_notice(
    agent_loop: Any,
    *,
    config_path: Any,
    config: Any | None = None,
) -> int:
    state = derive_runtime_state_view(load_runtime_state(config_path))
    if str(state.get("status") or "") != "healthy":
        return 0

    completed_at_ms = int(state.get("last_restart_completed_at_ms") or 0)
    sent_at_ms = int(((state.get("notifications") or {}).get("healthy")) or 0)
    if not completed_at_ms or sent_at_ms == completed_at_ms:
        return 0
    if not bool(state.get("restart_state_healthy")):
        return 0
    if not _channel_runtime_usable(agent_loop):
        return 0

    merged_targets = list(state.get("notify_targets") or [])
    seen = {
        (str(item.get("channel") or "").strip(), str(item.get("chat_id") or "").strip())
        for item in merged_targets
        if str(item.get("channel") or "").strip() and str(item.get("chat_id") or "").strip()
    }
    for item in derive_restart_notify_targets(getattr(agent_loop, "sessions", None), config=config):
        key = (str(item.get("channel") or "").strip(), str(item.get("chat_id") or "").strip())
        if not key[0] or not key[1] or key in seen:
            continue
        seen.add(key)
        merged_targets.append(dict(item))

    if merged_targets != list(state.get("notify_targets") or []):
        set_runtime_notify_targets(config_path, notify_targets=merged_targets)
        state["notify_targets"] = merged_targets

    if not merged_targets:
        return 0

    sent = await broadcast_restart_notice(agent_loop, stage="healthy", state=state)
    if sent:
        mark_runtime_notification_sent(
            config_path,
            stage="healthy",
            at_ms=completed_at_ms,
        )
    return sent
