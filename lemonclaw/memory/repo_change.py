"""Repository change memory sidecar for repo-aware coding sessions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _normalize_text_list(value: Any, *, limit: int = 6, item_limit: int = 160) -> list[str]:
    if isinstance(value, str):
        raw_items = [line.strip(" -*\t") for line in value.splitlines()]
    elif isinstance(value, list):
        raw_items = [str(item or "").strip() for item in value]
    else:
        return []

    normalized: list[str] = []
    for item in raw_items:
        if not item:
            continue
        clipped = item[:item_limit]
        if clipped not in normalized:
            normalized.append(clipped)
        if len(normalized) >= limit:
            break
    return normalized


def _read_sidecar(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def load_repo_change_memory(
    workspace: Path,
    *,
    client_id: str,
    workspace_id: str,
    thread_id: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Load lightweight repo-change guidance for AgentBridge sessions."""
    sidecar_dir = workspace / ".lemonclaw-state" / "repo-change-memory"
    sidecar_payload: dict[str, Any] = {}
    for name in (
        f"{client_id}__{workspace_id}__{thread_id}.json",
        f"{client_id}__{workspace_id}.json",
        f"{workspace_id}.json",
    ):
        candidate = sidecar_dir / name
        if candidate.exists():
            sidecar_payload = _read_sidecar(candidate)
            if sidecar_payload:
                break

    inline_payload = metadata.get("repo_change_memory") if isinstance(metadata, dict) else {}
    if not isinstance(inline_payload, dict):
        inline_payload = {}

    payload = {**sidecar_payload, **inline_payload}
    if not payload:
        return None

    summary = str(payload.get("summary") or "").strip()[:240]
    preferred_internal_apis = _normalize_text_list(payload.get("preferred_internal_apis"))
    path_conventions = _normalize_text_list(payload.get("path_conventions"))
    historical_patch_patterns = _normalize_text_list(payload.get("historical_patch_patterns"))
    if not any((summary, preferred_internal_apis, path_conventions, historical_patch_patterns)):
        return None

    if not summary:
        summary_parts: list[str] = []
        if preferred_internal_apis:
            summary_parts.append(f"preferred APIs: {', '.join(preferred_internal_apis[:3])}")
        if path_conventions:
            summary_parts.append(f"paths: {', '.join(path_conventions[:3])}")
        if historical_patch_patterns:
            summary_parts.append(f"patch patterns: {', '.join(historical_patch_patterns[:3])}")
        summary = "; ".join(summary_parts)[:240]

    context_lines = ["Repository change memory:"]
    if summary:
        context_lines.append(f"- Summary: {summary}")
    if preferred_internal_apis:
        context_lines.append(f"- Preferred internal APIs: {', '.join(preferred_internal_apis)}")
    if path_conventions:
        context_lines.append(f"- Path conventions: {', '.join(path_conventions)}")
    if historical_patch_patterns:
        context_lines.append(f"- Historical patch patterns: {', '.join(historical_patch_patterns)}")

    title = str(payload.get("title") or f"Repo Change Memory ({workspace_id})").strip()[:120]
    source = str(payload.get("source") or "memory.repo_change").strip() or "memory.repo_change"
    retrieval_object = {
        "kind": "repo_change_memory",
        "id": f"{client_id}:{workspace_id}:{thread_id}",
        "title": title,
        "source": source,
        "summary": summary,
        "client_id": client_id,
        "workspace_id": workspace_id,
        "thread_id": thread_id,
        "preferred_internal_apis": preferred_internal_apis,
        "path_conventions": path_conventions,
        "historical_patch_patterns": historical_patch_patterns,
    }
    return {
        "context": "\n".join(context_lines),
        "retrieval_objects": [retrieval_object],
        "source": source,
    }
