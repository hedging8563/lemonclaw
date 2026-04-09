"""Task checkpoint tool for writing explicit task progress to the ledger."""

from __future__ import annotations

from typing import Any

from lemonclaw.agent.tools.base import Tool
from lemonclaw.ledger.runtime import TaskLedger


_VERIFICATION_EVIDENCE_STATUSES = ("recorded", "accepted", "complete", "completed", "passed", "ok", "blocked", "rejected")


def _normalize_text(value: Any, *, limit: int = 500) -> str:
    return str(value or "").strip()[:limit]


def _normalize_acceptance_evidence(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []

    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = _normalize_text(item.get("kind"), limit=80)
        if not kind:
            continue
        summary = _normalize_text(item.get("summary") or item.get("note"), limit=500)
        status = _normalize_text(item.get("status") or "recorded", limit=40).lower()
        if status not in _VERIFICATION_EVIDENCE_STATUSES:
            status = "recorded"
        normalized_item = {
            "kind": kind,
            "status": status,
        }
        for field in ("summary", "note", "task_id", "step_id", "message_id", "evidence_id", "artifact_id"):
            text = _normalize_text(item.get(field), limit=500 if field in {"summary", "note"} else 120)
            if text:
                normalized_item[field] = text
        key = (
            kind,
            status,
            normalized_item.get("task_id", ""),
            normalized_item.get("step_id", ""),
            normalized_item.get("message_id", ""),
        )
        if key in seen:
            continue
        seen.add(key)
        if summary and "summary" not in normalized_item:
            normalized_item["summary"] = summary
        normalized.append(normalized_item)
    return normalized


def _normalize_replay_pointer(pointer: Any) -> dict[str, Any]:
    if not isinstance(pointer, dict):
        return {}

    normalized: dict[str, Any] = {}
    for field, limit in (
        ("kind", 80),
        ("channel", 80),
        ("chat_id", 120),
        ("thread_id", 120),
        ("message_id", 120),
        ("task_id", 120),
        ("step_id", 120),
        ("url", 500),
        ("note", 300),
    ):
        text = _normalize_text(pointer.get(field), limit=limit)
        if text:
            normalized[field] = text
    for field in ("at_ms", "source"):
        value = pointer.get(field)
        if value not in (None, "", []):
            normalized[field] = value
    return normalized


class TaskCheckpointTool(Tool):
    """Persist explicit task progress into the local task ledger."""

    @property
    def name(self) -> str:
        return "task_checkpoint"

    @property
    def description(self) -> str:
        return (
            "Write an explicit checkpoint for the current task. "
            "Use this to persist the current stage, what succeeded, what is blocked, "
            "and what should happen next."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "stage": {
                    "type": "string",
                    "description": "Current stage name, e.g. 'execute' or 'verify'.",
                    "minLength": 1,
                    "maxLength": 80,
                },
                "summary": {
                    "type": "string",
                    "description": "Brief summary of current task progress.",
                    "minLength": 1,
                    "maxLength": 500,
                },
                "last_successful_step": {
                    "type": "string",
                    "description": "Optional last step that completed successfully.",
                    "maxLength": 120,
                },
                "next_action": {
                    "type": "string",
                    "description": "Optional next action to take.",
                    "maxLength": 200,
                },
                "verification_status": {
                    "type": "string",
                    "description": "Optional verification status to record alongside the checkpoint.",
                    "enum": ["recorded", "accepted", "blocked", "rejected", "pending"],
                },
                "acceptance_evidence": {
                    "type": "array",
                    "description": "Optional acceptance evidence entries to append under metadata.verification.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string", "minLength": 1, "maxLength": 80},
                            "status": {"type": "string", "enum": list(_VERIFICATION_EVIDENCE_STATUSES)},
                            "summary": {"type": "string", "maxLength": 500},
                            "note": {"type": "string", "maxLength": 500},
                            "task_id": {"type": "string", "maxLength": 120},
                            "step_id": {"type": "string", "maxLength": 120},
                            "message_id": {"type": "string", "maxLength": 120},
                            "evidence_id": {"type": "string", "maxLength": 120},
                            "artifact_id": {"type": "string", "maxLength": 120},
                        },
                        "required": ["kind"],
                    },
                },
                "replay_pointer": {
                    "type": "object",
                    "description": "Optional replay pointer for later recovery or verification.",
                    "properties": {
                        "kind": {"type": "string", "maxLength": 80},
                        "channel": {"type": "string", "maxLength": 80},
                        "chat_id": {"type": "string", "maxLength": 120},
                        "thread_id": {"type": "string", "maxLength": 120},
                        "message_id": {"type": "string", "maxLength": 120},
                        "task_id": {"type": "string", "maxLength": 120},
                        "step_id": {"type": "string", "maxLength": 120},
                        "url": {"type": "string", "maxLength": 500},
                        "note": {"type": "string", "maxLength": 300},
                    },
                    "additionalProperties": True,
                },
                "status": {
                    "type": "string",
                    "description": "Optional task status override.",
                    "enum": ["running", "waiting", "verifying", "failed", "abandoned"],
                },
                "task_id": {
                    "type": "string",
                    "description": "Optional explicit task id override when a tracked task context already exists.",
                },
            },
            "required": ["stage", "summary"],
        }

    def resolve_capability(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> str:
        return "task.checkpoint.write"

    async def execute(
        self,
        stage: str,
        summary: str,
        last_successful_step: str | None = None,
        next_action: str | None = None,
        verification_status: str | None = None,
        acceptance_evidence: list[dict[str, Any]] | None = None,
        replay_pointer: dict[str, Any] | None = None,
        status: str | None = None,
        task_id: str | None = None,
        _task_id: str | None = None,
        _task_ledger: TaskLedger | None = None,
        **kwargs: Any,
    ) -> str:
        resolved_task_id = str(task_id or _task_id or "").strip()
        if not resolved_task_id:
            return "Error: No active task id in context. task_checkpoint only works inside a tracked LemonClaw task."
        if not _task_ledger:
            return "Error: Task ledger not available. task_checkpoint only works inside a tracked LemonClaw task."

        task = _task_ledger.read_task(resolved_task_id) or {}
        metadata = dict(task.get("metadata") or {})
        verification = dict(metadata.get("verification") or {})
        if verification_status:
            verification["verification_status"] = _normalize_text(verification_status, limit=40)
        normalized_evidence = _normalize_acceptance_evidence(acceptance_evidence)
        if normalized_evidence:
            existing_evidence = [
                item for item in list(verification.get("acceptance_evidence") or [])
                if isinstance(item, dict)
            ]
            merged: list[dict[str, Any]] = []
            seen: set[tuple[str, str, str, str, str]] = set()
            for item in [*existing_evidence, *normalized_evidence]:
                kind = _normalize_text(item.get("kind"), limit=80)
                status_value = _normalize_text(item.get("status") or "recorded", limit=40).lower()
                key = (
                    kind,
                    status_value,
                    _normalize_text(item.get("task_id"), limit=120),
                    _normalize_text(item.get("step_id"), limit=120),
                    _normalize_text(item.get("message_id"), limit=120),
                )
                if not kind or key in seen:
                    continue
                seen.add(key)
                merged.append(dict(item))
            verification["acceptance_evidence"] = merged[-50:]
        normalized_replay_pointer = _normalize_replay_pointer(replay_pointer)
        if normalized_replay_pointer:
            verification["replay_pointer"] = normalized_replay_pointer
            verification["ui_channel_replay"] = dict(normalized_replay_pointer)
        if verification:
            metadata["verification"] = verification

        metadata["checkpoint_summary"] = summary
        metadata["next_action"] = next_action or ""

        updates: dict[str, Any] = {
            "current_stage": stage,
            "status": status or "running",
            "metadata": metadata,
        }
        if last_successful_step:
            updates["last_successful_step"] = last_successful_step

        _task_ledger.update_task(resolved_task_id, **updates)
        extra = []
        if verification_status:
            extra.append(f"verification={verification_status}")
        if normalized_evidence:
            extra.append(f"evidence={len(normalized_evidence)}")
        if normalized_replay_pointer:
            extra.append("replay_pointer=yes")
        suffix = f" ({', '.join(extra)})" if extra else ""
        return f"Checkpoint saved for {resolved_task_id}: {summary}{suffix}"
