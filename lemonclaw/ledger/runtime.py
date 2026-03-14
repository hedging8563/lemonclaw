"""Local JSON-backed task ledger runtime."""

from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

from lemonclaw.ledger.types import OutboxEventRecord, StepRecord, TaskRecord


def _now_ms() -> int:
    return int(time.time() * 1000)


_SAFE_TASK_ID = re.compile(r"^task_[A-Za-z0-9_-]{1,64}$")
_SAFE_OUTBOX_ID = re.compile(r"^ob_[A-Za-z0-9_-]{1,64}$")
_SAFE_STEP_ID = re.compile(r"^step_[A-Za-z0-9_-]{1,64}$")


class TaskLedger:
    """Simple JSON-backed task and step ledger."""

    def __init__(self, workspace: Path):
        self._state_dir = workspace / ".lemonclaw-state" / "tasks"

    def ensure_task(
        self,
        *,
        task_id: str,
        session_key: str,
        agent_id: str,
        mode: str,
        channel: str,
        goal: str,
        status: str = "running",
        current_stage: str = "dispatch",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._require_valid_task_id(task_id)
        path = self._task_path(task_id)
        if path.exists():
            return
        now = _now_ms()
        record = TaskRecord(
            task_id=task_id,
            session_key=session_key,
            agent_id=agent_id,
            mode=mode,
            channel=channel,
            goal=goal,
            status=status,
            current_stage=current_stage,
            created_at_ms=now,
            updated_at_ms=now,
            metadata=metadata or {},
        )
        self._write_json(path, record.to_dict())

    def update_task(self, task_id: str, **updates: Any) -> None:
        self._require_valid_task_id(task_id)
        path = self._task_path(task_id)
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        data.update(updates)
        next_updated = _now_ms()
        previous_updated = int(data.get("updated_at_ms") or 0)
        # Preserve a monotonic ordering key for local observer UIs even when
        # multiple updates land in the same millisecond or the system clock shifts.
        data["updated_at_ms"] = max(next_updated, previous_updated + 1)
        self._write_json(path, data)

    def start_step(self, task_id: str, *, step_type: str, name: str, input_summary: str = "") -> StepRecord:
        self._require_valid_task_id(task_id)
        step = StepRecord(
            task_id=task_id,
            step_id=f"step_{uuid.uuid4().hex[:10]}",
            step_type=step_type,
            name=name,
            status="running",
            started_at_ms=_now_ms(),
            input_summary=input_summary[:500],
        )
        self._append_jsonl(self._steps_path(task_id), step.to_dict())
        return step

    def finish_step(self, step: StepRecord, *, status: str, error: str | None = None) -> None:
        step.status = status
        step.ended_at_ms = _now_ms()
        step.error = error
        self._append_jsonl(self._steps_path(step.task_id), step.to_dict())
        if status == "completed":
            self.update_task(step.task_id, last_successful_step=step.name)

    def task_exists(self, task_id: str) -> bool:
        return self._task_path(task_id).exists()

    def read_task(self, task_id: str) -> dict[str, Any] | None:
        path = self._task_path(task_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def read_steps(self, task_id: str) -> list[dict[str, Any]]:
        path = self._steps_path(task_id)
        if not path.exists():
            return []
        # TODO: stream JSONL when long-running tasks accumulate large step logs.
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def materialize_steps(self, task_id: str) -> list[dict[str, Any]]:
        """Collapse step event history into the latest state per step_id."""
        latest_by_step: dict[str, dict[str, Any]] = {}
        for event in self.read_steps(task_id):
            step_id = str(event.get("step_id", "")).strip()
            if not step_id:
                continue
            latest_by_step[step_id] = event
        return sorted(
            latest_by_step.values(),
            key=lambda item: (
                int(item.get("started_at_ms") or 0),
                int(item.get("ended_at_ms") or 0),
            ),
        )

    def list_tasks(
        self,
        *,
        limit: int = 50,
        session_key: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """List persisted tasks ordered by most recently updated."""
        tasks: list[dict[str, Any]] = []
        if not self._state_dir.exists():
            return tasks

        # TODO: replace the full directory scan with an index / retention policy
        # once task volume grows beyond the current single-instance scale.
        for path in self._state_dir.glob("task_*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if session_key and data.get("session_key") != session_key:
                continue
            if status and data.get("status") != status:
                continue
            tasks.append(data)

        tasks.sort(key=lambda item: int(item.get("updated_at_ms") or 0), reverse=True)
        return tasks[:max(1, int(limit))]

    def list_stale_tasks(
        self,
        *,
        stale_after_ms: int,
        statuses: tuple[str, ...] = ("running", "verifying", "waiting"),
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List tasks that have not been updated within the allowed threshold."""
        if stale_after_ms <= 0 or not self._state_dir.exists():
            return []

        cutoff = _now_ms() - stale_after_ms
        allowed = {status for status in statuses if status}
        tasks: list[dict[str, Any]] = []

        for path in self._state_dir.glob("task_*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if allowed and str(data.get("status") or "") not in allowed:
                continue
            updated_at_ms = int(data.get("updated_at_ms") or 0)
            if updated_at_ms and updated_at_ms <= cutoff:
                tasks.append(data)

        tasks.sort(key=lambda item: int(item.get("updated_at_ms") or 0))
        return tasks[:max(1, int(limit))]

    def mark_task_stale(
        self,
        task_id: str,
        *,
        source: str,
        reason: str,
        stale_after_ms: int,
    ) -> dict[str, Any] | None:
        """Annotate stale-task recovery state and fail closed when safe to do so."""
        self._require_valid_task_id(task_id)
        task = self.read_task(task_id)
        if not task:
            return None

        previous_status = str(task.get("status") or "")
        previous_stage = str(task.get("current_stage") or "")
        metadata = dict(task.get("metadata") or {})
        metadata["recovery"] = {
            "source": source,
            "reason": reason[:500],
            "detected_at_ms": _now_ms(),
            "stale_after_ms": stale_after_ms,
            "previous_status": previous_status,
            "previous_stage": previous_stage,
            "action": "mark_failed" if previous_status in {"running", "verifying"} else "manual_review",
            "manual_review_required": previous_status == "waiting",
        }

        updates: dict[str, Any] = {"metadata": metadata}
        if previous_status in {"running", "verifying"}:
            updates.update(
                status="failed",
                current_stage="stale_recovery",
                error=reason[:500],
            )

        self.update_task(task_id, **updates)
        return self.read_task(task_id)

    def read_task_view(self, task_id: str) -> dict[str, Any] | None:
        """Return task + materialized steps + summary for observer UIs."""
        task = self.read_task(task_id)
        if not task:
            return None

        steps = self.materialize_steps(task_id)
        status_counts: dict[str, int] = {}
        for step in steps:
            key = str(step.get("status") or "unknown")
            status_counts[key] = status_counts.get(key, 0) + 1

        return {
            "task": task,
            "steps": steps,
            "summary": {
                "step_count": len(steps),
                "status_counts": status_counts,
                "last_successful_step": task.get("last_successful_step"),
                "current_stage": task.get("current_stage"),
                "completion_gate": task.get("completion_gate"),
                "recovery": (task.get("metadata") or {}).get("recovery"),
            },
        }

    def enqueue_outbox(
        self,
        *,
        task_id: str,
        step_id: str,
        effect_type: str,
        target: str,
        payload: dict[str, Any],
        status: str = "pending",
        attempts: int = 0,
        next_attempt_at_ms: int | None = None,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require_valid_task_id(task_id)
        self._require_valid_step_id(step_id)
        now = _now_ms()
        event = OutboxEventRecord(
            event_id=f"ob_{uuid.uuid4().hex[:12]}",
            task_id=task_id,
            step_id=step_id,
            effect_type=effect_type,
            target=target,
            payload=payload,
            status=status,
            attempts=attempts,
            created_at_ms=now,
            updated_at_ms=now,
            next_attempt_at_ms=next_attempt_at_ms,
            error=error,
            metadata=metadata or {},
        )
        self._append_jsonl(self._outbox_path(), event.to_dict())
        return event.to_dict()

    def update_outbox_event(self, event_id: str, **updates: Any) -> dict[str, Any] | None:
        self._require_valid_outbox_id(event_id)
        current = self.read_outbox_event(event_id)
        if not current:
            return None
        current.update(updates)
        next_updated = _now_ms()
        previous_updated = int(current.get("updated_at_ms") or 0)
        current["updated_at_ms"] = max(next_updated, previous_updated + 1)
        self._append_jsonl(self._outbox_path(), current)
        return current

    def materialize_outbox_events(self) -> list[dict[str, Any]]:
        latest_by_event: dict[str, dict[str, Any]] = {}
        for event in self.read_outbox_events():
            event_id = str(event.get("event_id", "")).strip()
            if not event_id:
                continue
            latest_by_event[event_id] = event
        return sorted(
            latest_by_event.values(),
            key=lambda item: int(item.get("updated_at_ms") or 0),
            reverse=True,
        )

    def materialize_outbox_events_for_task(self, task_id: str) -> list[dict[str, Any]]:
        self._require_valid_task_id(task_id)
        return [event for event in self.materialize_outbox_events() if event.get("task_id") == task_id]

    def read_outbox_events(self) -> list[dict[str, Any]]:
        path = self._outbox_path()
        if not path.exists():
            return []
        # TODO: stream JSONL once outbox volume is large enough to matter.
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def list_outbox_events(
        self,
        *,
        limit: int = 50,
        status: str | None = None,
        task_id: str | None = None,
    ) -> list[dict[str, Any]]:
        events = self.materialize_outbox_events()
        if status:
            events = [event for event in events if event.get("status") == status]
        if task_id:
            events = [event for event in events if event.get("task_id") == task_id]
        return events[:max(1, int(limit))]

    def read_outbox_event(self, event_id: str) -> dict[str, Any] | None:
        self._require_valid_outbox_id(event_id)
        path = self._outbox_path()
        if not path.exists():
            return None

        latest: dict[str, Any] | None = None
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                event = json.loads(line)
                if event.get("event_id") == event_id:
                    latest = event
        return latest

    @staticmethod
    def is_valid_task_id(task_id: str) -> bool:
        return bool(_SAFE_TASK_ID.match(task_id))

    @staticmethod
    def now_ms() -> int:
        return _now_ms()

    def _require_valid_task_id(self, task_id: str) -> None:
        if not self.is_valid_task_id(task_id):
            raise ValueError("invalid task_id")

    @staticmethod
    def is_valid_outbox_id(event_id: str) -> bool:
        return bool(_SAFE_OUTBOX_ID.match(event_id))

    def _require_valid_outbox_id(self, event_id: str) -> None:
        if not self.is_valid_outbox_id(event_id):
            raise ValueError("invalid event_id")

    @staticmethod
    def is_valid_step_id(step_id: str) -> bool:
        return bool(_SAFE_STEP_ID.match(step_id))

    def _require_valid_step_id(self, step_id: str) -> None:
        if not self.is_valid_step_id(step_id):
            raise ValueError("invalid step_id")

    def _task_path(self, task_id: str) -> Path:
        self._require_valid_task_id(task_id)
        return self._state_dir / f"{task_id}.json"

    def _steps_path(self, task_id: str) -> Path:
        self._require_valid_task_id(task_id)
        return self._state_dir / f"{task_id}.steps.jsonl"

    def _outbox_path(self) -> Path:
        # TODO: split this global append-only log by task_id or add an index /
        # retention policy once outbox volume outgrows the current local scale.
        return self._state_dir / "outbox.jsonl"

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    @staticmethod
    def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
