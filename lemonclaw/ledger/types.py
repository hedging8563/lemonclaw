"""Task ledger data types."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


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
