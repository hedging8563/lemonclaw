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


def patch_kill_switch_state(path: Path, patch: dict[str, Any]) -> dict[str, Any]:
    state = load_kill_switch_state(path)
    changed = False
    for key in ("global",):
        if key in patch:
            next_value = bool(patch.get(key))
            if state.get(key) != next_value:
                state[key] = next_value
                changed = True
    for key in ("categories", "capabilities", "agents", "tenants"):
        if key not in patch:
            continue
        raw = patch.get(key) or {}
        if not isinstance(raw, dict):
            continue
        next_map = {str(name): bool(value) for name, value in raw.items()}
        if state.get(key) != next_map:
            state[key] = next_map
            changed = True
    if changed:
        state["epoch"] = int(state.get("epoch", 0)) + 1
        save_kill_switch_state(path, state)
    return state


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
