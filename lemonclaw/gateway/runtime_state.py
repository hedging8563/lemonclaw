"""Persistent runtime restart state for WebUI and chat-plane observability."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


def get_runtime_state_path(config_path: Path) -> Path:
    return Path(config_path).with_name("runtime-state.json")


def load_runtime_state(config_path: Path | None) -> dict[str, Any]:
    if not config_path:
        return {}
    path = get_runtime_state_path(Path(config_path))
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}


def _write_runtime_state(config_path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    path = get_runtime_state_path(Path(config_path))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(path)
    return payload


def _append_history(payload: dict[str, Any], event: dict[str, Any]) -> None:
    history = list(payload.get("history") or [])
    history.append(event)
    payload["history"] = history[-20:]


def _derive_chat_id_from_session_key(channel: str, session_key: str) -> str:
    prefix = f"{channel}:"
    if session_key.startswith(prefix):
        remainder = session_key[len(prefix):]
        return remainder.split(":", 1)[0] if ":" in remainder else remainder
    return session_key.split(":", 1)[-1] if ":" in session_key else session_key


def _append_unique_notify_target(
    targets: list[dict[str, str]],
    seen: set[tuple[str, str]],
    *,
    channel: str,
    chat_id: str,
    session_key: str,
    source: str,
) -> None:
    normalized_channel = str(channel or "").strip()
    normalized_chat_id = str(chat_id or "").strip()
    normalized_session_key = str(session_key or "").strip()
    if not normalized_channel or not normalized_chat_id or not normalized_session_key:
        return
    dedupe = (normalized_channel, normalized_chat_id)
    if dedupe in seen:
        return
    seen.add(dedupe)
    targets.append({
        "session_key": normalized_session_key,
        "channel": normalized_channel,
        "chat_id": normalized_chat_id,
        "source": source,
    })


def derive_recent_notify_targets(
    session_manager: Any | None,
    *,
    max_targets: int = 3,
    max_age_s: int = 2 * 60 * 60,
) -> list[dict[str, str]]:
    if session_manager is None or not hasattr(session_manager, "list_sessions"):
        return []
    now = datetime.now()
    cutoff = now - timedelta(seconds=max_age_s)
    targets: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in session_manager.list_sessions():
        key = str(item.get("key") or "").strip()
        if not key or ":" not in key:
            continue
        channel = key.split(":", 1)[0]
        if channel in {"webui", "system", "internal", "cli", "agentbridge"}:
            continue
        updated_at = str(item.get("updated_at") or "").strip()
        if updated_at:
            try:
                parsed = datetime.fromisoformat(updated_at)
                if parsed < cutoff:
                    continue
            except ValueError:
                pass
        chat_id = _derive_chat_id_from_session_key(channel, key)
        _append_unique_notify_target(
            targets,
            seen,
            channel=channel,
            chat_id=chat_id,
            session_key=key,
            source="recent_session",
        )
        if len(targets) >= max_targets:
            break
    return targets


def derive_restart_notify_targets(
    session_manager: Any | None,
    *,
    config: Any | None = None,
    max_recent_targets: int = 3,
    max_age_s: int = 2 * 60 * 60,
) -> list[dict[str, str]]:
    targets = derive_recent_notify_targets(
        session_manager,
        max_targets=max_recent_targets,
        max_age_s=max_age_s,
    )
    seen = {
        (str(item.get("channel") or "").strip(), str(item.get("chat_id") or "").strip())
        for item in targets
        if str(item.get("channel") or "").strip() and str(item.get("chat_id") or "").strip()
    }

    if config is None:
        return targets

    try:
        from lemonclaw.channels.auto_pairing import AutoPairing
        from lemonclaw.utils.helpers import get_data_path
    except Exception:
        return targets

    data_path = get_data_path()

    def _uses_pairing(channel_name: str) -> bool:
        channels = getattr(config, "channels", None)
        if channels is None:
            return False
        if channel_name == "slack":
            slack_cfg = getattr(channels, "slack", None)
            slack_dm = getattr(slack_cfg, "dm", None)
            return bool(getattr(slack_cfg, "enabled", False) and str(getattr(slack_dm, "policy", "") or "").strip() == "pairing")
        if channel_name == "whatsapp":
            return bool(getattr(getattr(channels, "whatsapp", None), "enabled", False) and getattr(channels, "auto_pairing", False))
        channel_cfg = getattr(channels, channel_name, None)
        if not getattr(channel_cfg, "enabled", False):
            return False
        raw_policy = str(getattr(channel_cfg, "dm_policy", "") or "").strip()
        if raw_policy:
            return raw_policy == "pairing"
        return bool(getattr(channels, "auto_pairing", False))

    for channel_name in ("telegram", "discord", "feishu", "matrix", "weixin", "whatsapp", "slack"):
        if not _uses_pairing(channel_name):
            continue
        pairing = AutoPairing(channel_name, data_path)
        owner_target = str(pairing.owner_notify_target or "").strip()
        if not owner_target:
            continue
        _append_unique_notify_target(
            targets,
            seen,
            channel=channel_name,
            chat_id=owner_target,
            session_key=f"{channel_name}:{owner_target}",
            source="pairing_owner",
        )
    return targets


def mark_restart_requested(
    config_path: Path,
    *,
    restart_fields: list[str],
    runtime_errors: list[str],
    source: str = "settings_apply",
    notify_targets: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    now_ms = int(time.time() * 1000)
    payload = load_runtime_state(config_path)
    payload.update({
        "status": "submitted",
        "updated_at_ms": now_ms,
        "last_restart_requested_at_ms": now_ms,
        "last_restart_started_at_ms": payload.get("last_restart_started_at_ms"),
        "last_restart_completed_at_ms": payload.get("last_restart_completed_at_ms"),
        "last_restart_result": "submitted",
        "restart_fields": list(restart_fields),
        "runtime_errors": list(runtime_errors),
        "source": source,
        "notify_targets": list(notify_targets or payload.get("notify_targets") or []),
    })
    _append_history(payload, {
        "state": "submitted",
        "at_ms": now_ms,
        "source": source,
        "restart_fields": list(restart_fields),
        "runtime_errors": list(runtime_errors),
    })
    return _write_runtime_state(config_path, payload)


def mark_restart_in_progress(
    config_path: Path,
    *,
    source: str = "settings_apply",
) -> dict[str, Any]:
    now_ms = int(time.time() * 1000)
    payload = load_runtime_state(config_path)
    payload.update({
        "status": "restarting",
        "updated_at_ms": now_ms,
        "last_restart_started_at_ms": now_ms,
        "last_restart_result": "restarting",
        "source": source,
    })
    _append_history(payload, {
        "state": "restarting",
        "at_ms": now_ms,
        "source": source,
        "restart_fields": list(payload.get("restart_fields") or []),
        "runtime_errors": list(payload.get("runtime_errors") or []),
    })
    return _write_runtime_state(config_path, payload)


def mark_runtime_failed(
    config_path: Path,
    *,
    runtime_errors: list[str],
    source: str,
) -> dict[str, Any]:
    now_ms = int(time.time() * 1000)
    payload = load_runtime_state(config_path)
    payload.update({
        "status": "failed",
        "updated_at_ms": now_ms,
        "last_restart_result": "failed",
        "runtime_errors": list(runtime_errors),
        "source": source,
    })
    _append_history(payload, {
        "state": "failed",
        "at_ms": now_ms,
        "source": source,
        "runtime_errors": list(runtime_errors),
    })
    return _write_runtime_state(config_path, payload)


def mark_runtime_notification_sent(
    config_path: Path,
    *,
    stage: str,
    at_ms: int,
) -> dict[str, Any]:
    payload = load_runtime_state(config_path)
    notifications = dict(payload.get("notifications") or {})
    notifications[stage] = at_ms
    payload["notifications"] = notifications
    payload["updated_at_ms"] = int(time.time() * 1000)
    return _write_runtime_state(config_path, payload)


def set_runtime_notify_targets(
    config_path: Path,
    *,
    notify_targets: list[dict[str, str]],
) -> dict[str, Any]:
    payload = load_runtime_state(config_path)
    payload["notify_targets"] = list(notify_targets)
    payload["updated_at_ms"] = int(time.time() * 1000)
    return _write_runtime_state(config_path, payload)


def mark_runtime_healthy(
    config_path: Path,
    *,
    version: str,
    model: str = "",
    instance_id: str = "",
) -> dict[str, Any]:
    now_ms = int(time.time() * 1000)
    payload = load_runtime_state(config_path)
    previous_status = str(payload.get("status") or "")
    payload.update({
        "status": "healthy",
        "updated_at_ms": now_ms,
        "last_restart_result": "healthy",
        "last_restart_completed_at_ms": now_ms,
        "runtime_errors": [],
        "version": version,
        "model": model,
        "instance_id": instance_id,
        "pid": os.getpid(),
    })
    if previous_status in {"submitted", "restarting"}:
        _append_history(payload, {
            "state": "healthy",
            "at_ms": now_ms,
            "source": "startup",
            "version": version,
            "model": model,
            "instance_id": instance_id,
        })
    return _write_runtime_state(config_path, payload)
