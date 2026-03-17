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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
