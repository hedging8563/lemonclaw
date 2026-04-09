"""Persistent runtime restart state for WebUI and chat-plane observability."""

from __future__ import annotations

import json
import os
import time
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


def mark_restart_requested(
    config_path: Path,
    *,
    restart_fields: list[str],
    runtime_errors: list[str],
    source: str = "settings_apply",
) -> dict[str, Any]:
    now_ms = int(time.time() * 1000)
    payload = load_runtime_state(config_path)
    payload.update({
        "status": "restarting",
        "updated_at_ms": now_ms,
        "last_restart_requested_at_ms": now_ms,
        "last_restart_completed_at_ms": payload.get("last_restart_completed_at_ms"),
        "last_restart_result": "restarting",
        "restart_fields": list(restart_fields),
        "runtime_errors": list(runtime_errors),
        "source": source,
    })
    _append_history(payload, {
        "state": "restarting",
        "at_ms": now_ms,
        "source": source,
        "restart_fields": list(restart_fields),
        "runtime_errors": list(runtime_errors),
    })
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
    if previous_status == "restarting":
        _append_history(payload, {
            "state": "healthy",
            "at_ms": now_ms,
            "source": "startup",
            "version": version,
            "model": model,
            "instance_id": instance_id,
        })
    return _write_runtime_state(config_path, payload)
