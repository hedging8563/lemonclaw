"""Local kill-switch state for governance controls."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_DEFAULT_STATE = {
    "epoch": 0,
    "global": False,
    "tenants": {},
    "categories": {},
    "agents": {},
    "capabilities": {},
}


def load_kill_switch_state(path: Path) -> dict[str, Any]:
    try:
        if not path.exists():
            return dict(_DEFAULT_STATE)
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return dict(_DEFAULT_STATE)
        return {**_DEFAULT_STATE, **data}
    except Exception:
        return dict(_DEFAULT_STATE)


def save_kill_switch_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def is_kill_switched(
    state: dict[str, Any],
    *,
    capability_id: str,
    category: str,
    tenant_id: str = "",
    agent_id: str = "",
) -> bool:
    if state.get("global"):
        return True
    if tenant_id and state.get("tenants", {}).get(tenant_id):
        return True
    if category and state.get("categories", {}).get(category):
        return True
    if agent_id and state.get("agents", {}).get(agent_id):
        return True
    if state.get("capabilities", {}).get(capability_id):
        return True
    return False
