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
        data["updated_at_ms"] = _now_ms()
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
