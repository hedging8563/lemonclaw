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
_OUTBOX_MANUAL_RETRY_DEBOUNCE_MS = 1500


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

    def list_recovery_tasks(
        self,
        *,
        limit: int = 50,
        manual_review_only: bool = False,
    ) -> list[dict[str, Any]]:
        """List tasks that carry recovery metadata, newest first."""
        tasks: list[dict[str, Any]] = []
        if not self._state_dir.exists():
            return tasks

        for path in self._state_dir.glob("task_*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            recovery = (data.get("metadata") or {}).get("recovery")
            if not isinstance(recovery, dict):
                continue
            if manual_review_only and not recovery.get("manual_review_required"):
                continue
            tasks.append(data)

        tasks.sort(key=lambda item: int(item.get("updated_at_ms") or 0), reverse=True)
        return tasks[:max(1, int(limit))]

    def get_recovery_summary(self) -> dict[str, int]:
        """Return aggregate counters for recovery-oriented observability."""
        tasks = self.list_recovery_tasks(limit=500)
        return self.summarize_recovery_tasks(tasks)

    @staticmethod
    def summarize_recovery_tasks(tasks: list[dict[str, Any]]) -> dict[str, int]:
        """Aggregate counters for a preloaded recovery task list."""
        summary = {
            "tasks_with_recovery": len(tasks),
            "manual_review_required": 0,
            "stale_recovery_failed": 0,
            "waiting_manual_review": 0,
        }
        for task in tasks:
            recovery = (task.get("metadata") or {}).get("recovery") or {}
            status = str(task.get("status") or "")
            stage = str(task.get("current_stage") or "")
            if recovery.get("manual_review_required"):
                summary["manual_review_required"] += 1
            if status == "failed" and stage == "stale_recovery":
                summary["stale_recovery_failed"] += 1
            if status == "waiting" and recovery.get("manual_review_required"):
                summary["waiting_manual_review"] += 1
        return summary

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

    def mark_tasks_for_process_restart(
        self,
        *,
        source: str,
        reason: str,
        statuses: tuple[str, ...] = ("running", "verifying", "waiting"),
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Annotate active tasks before a hard process restart."""
        marked: list[dict[str, Any]] = []
        for status in statuses:
            for task in self.list_tasks(limit=limit, status=status):
                task_id = str(task.get("task_id") or "")
                if not task_id:
                    continue
                metadata = dict(task.get("metadata") or {})
                recovery = dict(metadata.get("recovery") or {})
                recovery.update({
                    "source": source,
                    "reason": reason[:500],
                    "detected_at_ms": _now_ms(),
                    "previous_status": str(task.get("status") or ""),
                    "previous_stage": str(task.get("current_stage") or ""),
                    "action": "process_restart_review" if status == "waiting" else "mark_failed",
                    "manual_review_required": status == "waiting",
                })
                metadata["recovery"] = recovery
                updates: dict[str, Any] = {"metadata": metadata}
                if status in {"running", "verifying"}:
                    updates.update(status="failed", current_stage="hard_recovery", error=reason[:500])
                self.update_task(task_id, **updates)
                updated = self.read_task(task_id)
                if updated:
                    marked.append(updated)
        return marked

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

    def compact_outbox(
        self,
        *,
        keep_terminal: int = 200,
        min_terminal_age_ms: int = 24 * 60 * 60 * 1000,
        now_ms: int | None = None,
    ) -> dict[str, int]:
        """Rewrite outbox.jsonl with only the latest retained event states."""
        events = self.materialize_outbox_events()
        if not events:
            return {"before": 0, "after": 0, "dropped": 0}

        now = now_ms if now_ms is not None else _now_ms()
        cutoff = now - max(0, int(min_terminal_age_ms))
        terminal_statuses = {"sent", "failed", "compensated"}

        kept: list[dict[str, Any]] = []
        terminal_kept = 0
        for event in events:
            status = str(event.get("status") or "")
            updated_at_ms = int(event.get("updated_at_ms") or 0)
            is_terminal = status in terminal_statuses
            keep_event = not is_terminal
            if is_terminal and updated_at_ms >= cutoff:
                keep_event = True
            elif is_terminal and terminal_kept < max(0, int(keep_terminal)):
                keep_event = True
            if keep_event:
                kept.append(event)
                if is_terminal and updated_at_ms < cutoff:
                    terminal_kept += 1

        kept.sort(key=lambda item: (
            int(item.get("created_at_ms") or 0),
            int(item.get("updated_at_ms") or 0),
        ))
        payload = "\n".join(json.dumps(event, ensure_ascii=False) for event in kept)
        path = self._outbox_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".compact.tmp")
        tmp.write_text((payload + "\n") if payload else "", encoding="utf-8")
        tmp.replace(path)
        return {
            "before": len(events),
            "after": len(kept),
            "dropped": max(0, len(events) - len(kept)),
        }

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

    def claim_due_outbox_events(
        self,
        *,
        limit: int = 20,
        now_ms: int | None = None,
        claim_owner: str = "outbox_dispatcher",
    ) -> list[dict[str, Any]]:
        """Claim due pending/retrying outbox events for delivery.

        `attempts` counts total delivery attempts, so it increments when an
        event is claimed for a real send attempt, not when it is rescheduled.
        """
        now = now_ms if now_ms is not None else _now_ms()
        due: list[dict[str, Any]] = []
        for event in self.materialize_outbox_events():
            status = str(event.get("status") or "")
            if status not in {"pending", "retrying"}:
                continue
            next_attempt = event.get("next_attempt_at_ms")
            if next_attempt is not None and int(next_attempt) > now:
                continue
            due.append(event)

        due.sort(key=lambda item: (
            int(item.get("next_attempt_at_ms") or item.get("created_at_ms") or 0),
            int(item.get("updated_at_ms") or 0),
        ))

        claimed: list[dict[str, Any]] = []
        for event in due[:max(1, int(limit))]:
            metadata = dict(event.get("metadata") or {})
            metadata["claimed_by"] = claim_owner
            metadata["claimed_at_ms"] = now
            updated = self.update_outbox_event(
                str(event["event_id"]),
                status="claimed",
                attempts=int(event.get("attempts") or 0) + 1,
                next_attempt_at_ms=None,
                error=None,
                metadata=metadata,
            )
            if updated:
                claimed.append(updated)
        return claimed

    def mark_outbox_sent(
        self,
        event_id: str,
        *,
        result: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Mark a claimed outbox event as delivered."""
        self._require_valid_outbox_id(event_id)
        current = self.read_outbox_event(event_id)
        if not current:
            return None
        metadata = dict(current.get("metadata") or {})
        metadata["sent_at_ms"] = _now_ms()
        if result is not None:
            metadata["delivery_result"] = result
        return self.update_outbox_event(
            event_id,
            status="sent",
            next_attempt_at_ms=None,
            error=None,
            metadata=metadata,
        )

    def mark_outbox_retry(
        self,
        event_id: str,
        *,
        error: str,
        retry_at_ms: int,
        max_attempts: int | None = None,
    ) -> dict[str, Any] | None:
        """Reschedule an outbox event or mark it terminally failed.

        `max_attempts` is the maximum total delivery attempts, not "retries
        after the first attempt". Once the current claimed attempt reaches the
        cap, the event becomes terminally failed.
        """
        self._require_valid_outbox_id(event_id)
        current = self.read_outbox_event(event_id)
        if not current:
            return None

        attempts = int(current.get("attempts") or 0)
        terminal = bool(max_attempts and max_attempts > 0 and attempts >= max_attempts)
        metadata = dict(current.get("metadata") or {})
        metadata["last_error_at_ms"] = _now_ms()
        metadata["last_claimed_by"] = metadata.get("claimed_by")

        return self.update_outbox_event(
            event_id,
            status="failed" if terminal else "retrying",
            next_attempt_at_ms=None if terminal else int(retry_at_ms),
            error=error[:500],
            metadata=metadata,
        )

    def mark_outbox_failed(
        self,
        event_id: str,
        *,
        error: str,
    ) -> dict[str, Any] | None:
        """Mark an outbox event as terminally failed without retry."""
        self._require_valid_outbox_id(event_id)
        current = self.read_outbox_event(event_id)
        if not current:
            return None

        metadata = dict(current.get("metadata") or {})
        metadata["last_error_at_ms"] = _now_ms()
        metadata["last_claimed_by"] = metadata.get("claimed_by")
        metadata["terminal"] = True

        return self.update_outbox_event(
            event_id,
            status="failed",
            next_attempt_at_ms=None,
            error=error[:500],
            metadata=metadata,
        )

    def request_outbox_retry(
        self,
        event_id: str,
        *,
        source: str,
        delay_ms: int = 0,
    ) -> dict[str, Any] | None:
        """Manually reschedule an outbox event and clear manual-review state."""
        self._require_valid_outbox_id(event_id)
        current = self.read_outbox_event(event_id)
        if not current:
            return None

        status = str(current.get("status") or "")
        if status == "sent":
            raise ValueError("cannot retry a sent outbox event")

        now = _now_ms()
        metadata = dict(current.get("metadata") or {})
        last_manual_retry = int(metadata.get("manual_retry_requested_at_ms") or 0)
        if (
            status in {"pending", "retrying"}
            and last_manual_retry
            and (now - last_manual_retry) < _OUTBOX_MANUAL_RETRY_DEBOUNCE_MS
        ):
            return current
        metadata.pop("terminal", None)
        metadata["manual_retry_requested_at_ms"] = now
        metadata["manual_retry_source"] = source

        updated = self.update_outbox_event(
            event_id,
            status="retrying" if int(current.get("attempts") or 0) > 0 else "pending",
            next_attempt_at_ms=now + max(0, int(delay_ms)),
            error=None,
            metadata=metadata,
        )

        task_id = str(current.get("task_id") or "")
        if updated and task_id and self.is_valid_task_id(task_id):
            task = self.read_task(task_id)
            if task:
                task_metadata = dict(task.get("metadata") or {})
                recovery = dict(task_metadata.get("recovery") or {})
                recovery["action"] = "manual_retry_requested"
                recovery["manual_review_required"] = False
                recovery["requested_at_ms"] = now
                recovery["source"] = source
                task_metadata["recovery"] = recovery
                self.update_task(
                    task_id,
                    status="waiting",
                    current_stage="waiting_outbox",
                    error=None,
                    metadata=task_metadata,
                )
        return updated

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
