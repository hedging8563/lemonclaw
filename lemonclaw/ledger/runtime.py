"""Local JSON-backed task ledger runtime."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from lemonclaw.ledger.types import StepRecord, TaskRecord


def _now_ms() -> int:
    return int(time.time() * 1000)


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
        path = self._task_path(task_id)
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        data.update(updates)
        next_updated = _now_ms()
        previous_updated = int(data.get("updated_at_ms") or 0)
        data["updated_at_ms"] = max(next_updated, previous_updated + 1)
        self._write_json(path, data)

    def start_step(self, task_id: str, *, step_type: str, name: str, input_summary: str = "") -> StepRecord:
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
            },
        }

    def _task_path(self, task_id: str) -> Path:
        return self._state_dir / f"{task_id}.json"

    def _steps_path(self, task_id: str) -> Path:
        return self._state_dir / f"{task_id}.steps.jsonl"

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
