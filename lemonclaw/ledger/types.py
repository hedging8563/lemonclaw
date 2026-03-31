"""Task ledger data types."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

OUTBOX_EFFECT_SPECS: dict[str, dict[str, str]] = {
    "outbound_message": {
        "category": "messaging",
        "target_kind": "channel",
        "description": "Structured outbound chat delivery through the message bus.",
    },
    "webhook_json": {
        "category": "webhook",
        "target_kind": "url",
        "description": "Structured webhook JSON delivery to a trusted endpoint.",
    },
    "http_json": {
        "category": "http",
        "target_kind": "url",
        "description": "Structured HTTP JSON request replayed through the HTTP tool runtime.",
    },
    "email_send": {
        "category": "email",
        "target_kind": "address",
        "description": "SMTP-backed email delivery.",
    },
}

OUTBOX_ACTIVE_STATUSES = frozenset({"pending", "claimed", "retrying"})
OUTBOX_SUCCESS_STATUSES = frozenset({"sent", "compensated"})
OUTBOX_FAILURE_STATUSES = frozenset({"failed", "expired"})
OUTBOX_ABANDONED_STATUSES = frozenset({"abandoned"})
OUTBOX_TERMINAL_STATUSES = OUTBOX_SUCCESS_STATUSES | OUTBOX_FAILURE_STATUSES | OUTBOX_ABANDONED_STATUSES
_VERIFICATION_ACCEPTED_STATUSES = frozenset({"accepted", "complete", "completed", "passed", "ok", "recorded"})


def is_supported_outbox_effect_type(effect_type: str) -> bool:
    return effect_type in OUTBOX_EFFECT_SPECS


def describe_outbox_effect_type(effect_type: str) -> dict[str, str]:
    return {
        "effect_type": effect_type,
        **OUTBOX_EFFECT_SPECS.get(
            effect_type,
            {
                "category": "unknown",
                "target_kind": "opaque",
                "description": "Unknown outbox effect type.",
            },
        ),
    }


def build_acceptance_evidence_summary(verification: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(verification, dict):
        return {}

    acceptance_evidence = [dict(item) for item in list(verification.get("acceptance_evidence") or []) if isinstance(item, dict)]
    status_counts: dict[str, int] = {}
    kind_counts: dict[str, int] = {}
    accepted_count = 0
    for item in acceptance_evidence:
        status = str(item.get("status") or "recorded").strip().lower()
        kind = str(item.get("kind") or "").strip()
        status_counts[status] = status_counts.get(status, 0) + 1
        if kind:
            kind_counts[kind] = kind_counts.get(kind, 0) + 1
        if status in _VERIFICATION_ACCEPTED_STATUSES:
            accepted_count += 1

    return {
        "count": len(acceptance_evidence),
        "accepted_count": accepted_count,
        "status_counts": status_counts,
        "kind_counts": kind_counts,
    }


def build_surface_replay_pointer(verification: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(verification, dict):
        return {}

    pointer = verification.get("ui_channel_replay")
    if not isinstance(pointer, dict):
        pointer = verification.get("replay_pointer")
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
        value = pointer.get(field)
        if value in (None, "", []):
            continue
        text = str(value).strip()[:limit]
        if text:
            normalized[field] = text
    for field in ("source",):
        value = pointer.get(field)
        if value not in (None, "", []):
            normalized[field] = value
    for field in ("at_ms",):
        value = pointer.get(field)
        if value not in (None, "", []):
            normalized[field] = value
    return normalized


@dataclass(slots=True)
class TaskRecord:
    task_id: str
    session_key: str
    agent_id: str
    mode: str
    channel: str
    goal: str
    status: str
    current_stage: str
    created_at_ms: int
    updated_at_ms: int
    last_successful_step: str | None = None
    resume_from_step: str | None = None
    resume_context: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class StepRecord:
    task_id: str
    step_id: str
    step_type: str
    name: str
    status: str
    started_at_ms: int
    ended_at_ms: int | None = None
    input_summary: str = ""
    error: str | None = None
    replayable: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class OutboxEventRecord:
    event_id: str
    task_id: str
    step_id: str
    effect_type: str
    target: str
    payload: dict[str, Any]
    status: str
    attempts: int
    created_at_ms: int
    updated_at_ms: int
    next_attempt_at_ms: int | None = None
    expires_at_ms: int | None = None
    terminal_at_ms: int | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CompletionGateResult:
    task_id: str
    passed: bool
    reason: str
    next_status: str
    next_stage: str
    checked_at_ms: int
    open_steps: list[str] = field(default_factory=list)
    open_outbox: list[str] = field(default_factory=list)
    verification: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def summarize_verification_metadata(
    verification: dict[str, Any] | None,
    *,
    steps: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload = dict(verification or {}) if isinstance(verification, dict) else {}
    if not payload:
        return {}

    requirements = dict(payload.get("requirements") or {}) if isinstance(payload.get("requirements"), dict) else {}
    tool_trace = [dict(item) for item in list(payload.get("tool_trace") or []) if isinstance(item, dict)]
    acceptance_evidence = [dict(item) for item in list(payload.get("acceptance_evidence") or []) if isinstance(item, dict)]
    required_evidence = [
        str(item).strip()
        for item in list(requirements.get("required_evidence") or [])
        if str(item).strip()
    ]
    min_tool_traces = 0
    if requirements.get("require_tool_trace"):
        min_tool_traces = 1
    if requirements.get("min_tool_traces") is not None:
        try:
            min_tool_traces = max(min_tool_traces, int(requirements.get("min_tool_traces") or 0))
        except (TypeError, ValueError):
            min_tool_traces = max(min_tool_traces, 0)

    accepted_evidence = []
    accepted_kinds: set[str] = set()
    for item in acceptance_evidence:
        kind = str(item.get("kind") or "").strip()
        status = str(item.get("status") or "accepted").strip().lower()
        if not kind:
            continue
        if status in _VERIFICATION_ACCEPTED_STATUSES:
            accepted_evidence.append(item)
            accepted_kinds.add(kind)

    missing_requirements: list[str] = []
    if min_tool_traces and len(tool_trace) < min_tool_traces:
        missing_requirements.append("tool_trace")
    for kind in required_evidence:
        if kind not in accepted_kinds:
            missing_requirements.append(f"evidence:{kind}")

    summary = {
        "enabled": True,
        "required": bool(min_tool_traces or required_evidence),
        "step_trace_count": len(steps or []),
        "tool_trace_count": len(tool_trace),
        "acceptance_evidence_count": len(acceptance_evidence),
        "accepted_evidence_count": len(accepted_evidence),
        "requirements": {
            "min_tool_traces": min_tool_traces,
            "required_evidence": required_evidence,
        },
        "missing_requirements": missing_requirements,
        "ui_channel_replay_available": bool(payload.get("ui_channel_replay_available") or payload.get("ui_channel_replay")),
        "ui_channel_replay": dict(payload.get("ui_channel_replay") or {}) if isinstance(payload.get("ui_channel_replay"), dict) else {},
        "tool_trace": tool_trace,
        "acceptance_evidence": acceptance_evidence,
    }
    evidence_summary = build_acceptance_evidence_summary(payload)
    if evidence_summary:
        summary["acceptance_evidence_summary"] = evidence_summary
    surface_replay_pointer = build_surface_replay_pointer(payload)
    if surface_replay_pointer:
        summary["surface_replay_pointer"] = surface_replay_pointer
    return summary
