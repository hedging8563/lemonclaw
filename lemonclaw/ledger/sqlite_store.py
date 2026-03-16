"""SQLite-backed ledger store."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any

from lemonclaw.ledger.runtime import (
    _OUTBOX_MANUAL_RETRY_DEBOUNCE_MS,
    _SAFE_OUTBOX_ID,
    _SAFE_STEP_ID,
    _SAFE_TASK_ID,
    _now_ms,
    JsonTaskLedger,
)
from lemonclaw.ledger.types import OutboxEventRecord, StepRecord, TaskRecord


class SQLiteTaskLedger(JsonTaskLedger):
    """SQLite-backed ledger and outbox persistence."""

    def __init__(self, workspace: Path):
        self._state_dir = workspace / ".lemonclaw-state" / "tasks"
        self._db_path = self._state_dir / "ledger.sqlite3"
        self._outbox_lock = threading.RLock()
        self._db_lock = threading.RLock()
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._init_db()

    def _init_db(self) -> None:
        with self._db_lock, self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    session_key TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    goal TEXT NOT NULL,
                    status TEXT NOT NULL,
                    current_stage TEXT NOT NULL,
                    created_at_ms INTEGER NOT NULL,
                    updated_at_ms INTEGER NOT NULL,
                    last_successful_step TEXT,
                    resume_from_step TEXT,
                    resume_context_json TEXT NOT NULL,
                    error TEXT,
                    metadata_json TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_updated_at ON tasks(updated_at_ms DESC);
                CREATE INDEX IF NOT EXISTS idx_tasks_status_updated ON tasks(status, updated_at_ms DESC);
                CREATE INDEX IF NOT EXISTS idx_tasks_session_updated ON tasks(session_key, updated_at_ms DESC);

                CREATE TABLE IF NOT EXISTS step_events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    step_id TEXT NOT NULL,
                    step_type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at_ms INTEGER NOT NULL,
                    ended_at_ms INTEGER,
                    input_summary TEXT NOT NULL,
                    error TEXT,
                    replayable INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_step_events_task ON step_events(task_id, seq ASC);
                CREATE INDEX IF NOT EXISTS idx_step_events_step ON step_events(step_id, seq ASC);

                CREATE TABLE IF NOT EXISTS outbox_events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    step_id TEXT NOT NULL,
                    effect_type TEXT NOT NULL,
                    target TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL,
                    created_at_ms INTEGER NOT NULL,
                    updated_at_ms INTEGER NOT NULL,
                    next_attempt_at_ms INTEGER,
                    error TEXT,
                    metadata_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_outbox_event_id_seq ON outbox_events(event_id, seq DESC);
                CREATE INDEX IF NOT EXISTS idx_outbox_status_due ON outbox_events(status, next_attempt_at_ms, updated_at_ms);
                CREATE INDEX IF NOT EXISTS idx_outbox_task_seq ON outbox_events(task_id, seq DESC);
                """
            )
            columns = {
                row["name"]
                for row in self._conn.execute("PRAGMA table_info(tasks)").fetchall()
            }
            if "payload_json" not in columns:
                self._conn.execute("ALTER TABLE tasks ADD COLUMN payload_json TEXT NOT NULL DEFAULT '{}'")

    @staticmethod
    def _dump_json(value: dict[str, Any] | list[Any]) -> str:
        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    def _loads_json(value: str | None) -> Any:
        if not value:
            return {}
        return json.loads(value)

    @classmethod
    def _task_to_row(cls, payload: dict[str, Any]) -> tuple[Any, ...]:
        return (
            payload["task_id"],
            payload["session_key"],
            payload["agent_id"],
            payload["mode"],
            payload["channel"],
            payload["goal"],
            payload["status"],
            payload["current_stage"],
            int(payload["created_at_ms"]),
            int(payload["updated_at_ms"]),
            payload.get("last_successful_step"),
            payload.get("resume_from_step"),
            cls._dump_json(dict(payload.get("resume_context") or {})),
            payload.get("error"),
            cls._dump_json(dict(payload.get("metadata") or {})),
            cls._dump_json(payload),
        )

    @classmethod
    def _row_to_task(cls, row: sqlite3.Row) -> dict[str, Any]:
        payload_json = row["payload_json"] if "payload_json" in row.keys() else None
        if payload_json:
            return json.loads(payload_json)
        return {
            "task_id": row["task_id"],
            "session_key": row["session_key"],
            "agent_id": row["agent_id"],
            "mode": row["mode"],
            "channel": row["channel"],
            "goal": row["goal"],
            "status": row["status"],
            "current_stage": row["current_stage"],
            "created_at_ms": int(row["created_at_ms"]),
            "updated_at_ms": int(row["updated_at_ms"]),
            "last_successful_step": row["last_successful_step"],
            "resume_from_step": row["resume_from_step"],
            "resume_context": cls._loads_json(row["resume_context_json"]),
            "error": row["error"],
            "metadata": cls._loads_json(row["metadata_json"]),
        }

    @staticmethod
    def _row_to_step(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "task_id": row["task_id"],
            "step_id": row["step_id"],
            "step_type": row["step_type"],
            "name": row["name"],
            "status": row["status"],
            "started_at_ms": int(row["started_at_ms"]),
            "ended_at_ms": int(row["ended_at_ms"]) if row["ended_at_ms"] is not None else None,
            "input_summary": row["input_summary"] or "",
            "error": row["error"],
            "replayable": bool(row["replayable"]),
        }

    @classmethod
    def _row_to_outbox(cls, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "event_id": row["event_id"],
            "task_id": row["task_id"],
            "step_id": row["step_id"],
            "effect_type": row["effect_type"],
            "target": row["target"],
            "payload": cls._loads_json(row["payload_json"]),
            "status": row["status"],
            "attempts": int(row["attempts"]),
            "created_at_ms": int(row["created_at_ms"]),
            "updated_at_ms": int(row["updated_at_ms"]),
            "next_attempt_at_ms": int(row["next_attempt_at_ms"]) if row["next_attempt_at_ms"] is not None else None,
            "error": row["error"],
            "metadata": cls._loads_json(row["metadata_json"]),
        }

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
        resume_context: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._require_valid_task_id(task_id)
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
            resume_context=resume_context or {},
            metadata=metadata or {},
        ).to_dict()
        with self._db_lock, self._conn:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO tasks (
                    task_id, session_key, agent_id, mode, channel, goal, status, current_stage,
                    created_at_ms, updated_at_ms, last_successful_step, resume_from_step,
                    resume_context_json, error, metadata_json, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._task_to_row(record),
            )

    def update_task(self, task_id: str, **updates: Any) -> None:
        self._require_valid_task_id(task_id)
        current = self.read_task(task_id)
        if not current:
            return
        current.update(updates)
        next_updated = _now_ms()
        previous_updated = int(current.get("updated_at_ms") or 0)
        current["updated_at_ms"] = max(next_updated, previous_updated + 1)
        with self._db_lock, self._conn:
            self._conn.execute(
                """
                UPDATE tasks
                SET session_key=?, agent_id=?, mode=?, channel=?, goal=?, status=?, current_stage=?,
                    created_at_ms=?, updated_at_ms=?, last_successful_step=?, resume_from_step=?,
                    resume_context_json=?, error=?, metadata_json=?, payload_json=?
                WHERE task_id=?
                """,
                (
                    current["session_key"],
                    current["agent_id"],
                    current["mode"],
                    current["channel"],
                    current["goal"],
                    current["status"],
                    current["current_stage"],
                    int(current["created_at_ms"]),
                    int(current["updated_at_ms"]),
                    current.get("last_successful_step"),
                    current.get("resume_from_step"),
                    self._dump_json(dict(current.get("resume_context") or {})),
                    current.get("error"),
                    self._dump_json(dict(current.get("metadata") or {})),
                    self._dump_json(current),
                    task_id,
                ),
            )

    def start_step(self, task_id: str, *, step_type: str, name: str, input_summary: str = "", replayable: bool = True) -> StepRecord:
        self._require_valid_task_id(task_id)
        step = StepRecord(
            task_id=task_id,
            step_id=f"step_{uuid.uuid4().hex[:10]}",
            step_type=step_type,
            name=name,
            status="running",
            started_at_ms=_now_ms(),
            input_summary=input_summary[:500],
            replayable=replayable,
        )
        self._insert_step_event(step.to_dict())
        return step

    def finish_step(self, step: StepRecord, *, status: str, error: str | None = None) -> None:
        step.status = status
        step.ended_at_ms = _now_ms() if status in {"completed", "failed", "abandoned", "compensated"} else None
        step.error = error
        self._insert_step_event(step.to_dict())
        if status == "completed":
            self.update_task(step.task_id, last_successful_step=step.name)

    def update_step_state(
        self,
        task_id: str,
        step_id: str,
        *,
        status: str,
        error: str | None = None,
    ) -> dict[str, Any] | None:
        self._require_valid_task_id(task_id)
        self._require_valid_step_id(step_id)
        current = next((step for step in self.materialize_steps(task_id) if str(step.get("step_id")) == step_id), None)
        if not current:
            return None
        updated = dict(current)
        updated["status"] = status
        updated["error"] = error
        updated["ended_at_ms"] = _now_ms() if status in {"completed", "failed", "abandoned", "compensated"} else None
        self._insert_step_event(updated)
        if status == "completed":
            self.update_task(task_id, last_successful_step=str(updated.get("name") or ""))
        return updated

    def task_exists(self, task_id: str) -> bool:
        self._require_valid_task_id(task_id)
        with self._db_lock:
            row = self._conn.execute("SELECT 1 FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        return row is not None

    def read_task(self, task_id: str) -> dict[str, Any] | None:
        self._require_valid_task_id(task_id)
        with self._db_lock:
            row = self._conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        return self._row_to_task(row) if row else None

    def read_steps(self, task_id: str) -> list[dict[str, Any]]:
        self._require_valid_task_id(task_id)
        with self._db_lock:
            rows = self._conn.execute(
                "SELECT * FROM step_events WHERE task_id = ? ORDER BY seq ASC",
                (task_id,),
            ).fetchall()
        return [self._row_to_step(row) for row in rows]

    def list_tasks(
        self,
        *,
        limit: int = 50,
        session_key: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM tasks"
        clauses: list[str] = []
        params: list[Any] = []
        if session_key:
            clauses.append("session_key = ?")
            params.append(session_key)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY updated_at_ms DESC LIMIT ?"
        params.append(max(1, int(limit)))
        with self._db_lock:
            rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_task(row) for row in rows]

    def list_stale_tasks(
        self,
        *,
        stale_after_ms: int,
        statuses: tuple[str, ...] = ("running", "verifying", "waiting"),
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        if stale_after_ms <= 0:
            return []
        cutoff = _now_ms() - stale_after_ms
        allowed = [status for status in statuses if status]
        query = "SELECT * FROM tasks WHERE updated_at_ms <= ?"
        params: list[Any] = [cutoff]
        if allowed:
            placeholders = ",".join("?" for _ in allowed)
            query += f" AND status IN ({placeholders})"
            params.extend(allowed)
        query += " ORDER BY updated_at_ms ASC LIMIT ?"
        params.append(max(1, int(limit)))
        with self._db_lock:
            rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_task(row) for row in rows]

    def list_recovery_tasks(
        self,
        *,
        limit: int = 50,
        manual_review_only: bool = False,
    ) -> list[dict[str, Any]]:
        with self._db_lock:
            rows = self._conn.execute(
                "SELECT * FROM tasks ORDER BY updated_at_ms DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        tasks = [self._row_to_task(row) for row in rows]
        result: list[dict[str, Any]] = []
        for task in tasks:
            recovery = (task.get("metadata") or {}).get("recovery")
            if not isinstance(recovery, dict):
                continue
            if manual_review_only and not recovery.get("manual_review_required"):
                continue
            result.append(task)
        return result

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
        ).to_dict()
        with self._outbox_lock:
            self._insert_outbox_event(event)
        return event

    def update_outbox_event(self, event_id: str, **updates: Any) -> dict[str, Any] | None:
        self._require_valid_outbox_id(event_id)
        with self._outbox_lock:
            return self._update_outbox_event_unlocked(event_id, **updates)

    def materialize_outbox_events(self) -> list[dict[str, Any]]:
        with self._outbox_lock:
            return self._materialize_outbox_events_unlocked()

    def read_outbox_events(self) -> list[dict[str, Any]]:
        with self._outbox_lock:
            return self._read_outbox_events_unlocked()

    def compact_outbox(
        self,
        *,
        keep_terminal: int = 200,
        min_terminal_age_ms: int = 24 * 60 * 60 * 1000,
        now_ms: int | None = None,
    ) -> dict[str, int]:
        with self._outbox_lock:
            events = self._materialize_outbox_events_unlocked()
            if not events:
                return {"before": 0, "after": 0, "dropped": 0}

            now = now_ms if now_ms is not None else _now_ms()
            cutoff = now - max(0, int(min_terminal_age_ms))
            terminal_statuses = {"sent", "failed", "compensated"}
            non_terminal = [event for event in events if str(event.get("status") or "") not in terminal_statuses]
            terminal = [event for event in events if str(event.get("status") or "") in terminal_statuses]
            terminal.sort(key=lambda item: int(item.get("updated_at_ms") or 0), reverse=True)
            kept_terminal = [
                event
                for event in terminal
                if int(event.get("updated_at_ms") or 0) >= cutoff
            ]
            kept_ids = {str(e.get("event_id") or "") for e in kept_terminal}
            for event in terminal:
                eid = str(event.get("event_id") or "")
                if eid in kept_ids:
                    continue
                if len(kept_terminal) >= max(0, int(keep_terminal)):
                    break
                kept_terminal.append(event)
                kept_ids.add(eid)
            if len(kept_terminal) > max(0, int(keep_terminal)):
                kept_terminal = kept_terminal[:max(0, int(keep_terminal))]
            kept: list[dict[str, Any]] = non_terminal + kept_terminal
            kept.sort(key=lambda item: (
                int(item.get("created_at_ms") or 0),
                int(item.get("updated_at_ms") or 0),
            ))

            with self._db_lock, self._conn:
                self._conn.execute("DELETE FROM outbox_events")
                for event in kept:
                    self._insert_outbox_event(event, commit=False)
            return {
                "before": len(events),
                "after": len(kept),
                "dropped": max(0, len(events) - len(kept)),
            }

    def read_outbox_event(self, event_id: str) -> dict[str, Any] | None:
        self._require_valid_outbox_id(event_id)
        with self._outbox_lock:
            return self._read_outbox_event_unlocked(event_id)

    def _insert_step_event(self, event: dict[str, Any], *, commit: bool = True) -> None:
        with self._db_lock:
            if commit:
                with self._conn:
                    self._conn.execute(
                        """
                        INSERT INTO step_events (
                            task_id, step_id, step_type, name, status,
                            started_at_ms, ended_at_ms, input_summary, error, replayable
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            event["task_id"],
                            event["step_id"],
                            event["step_type"],
                            event["name"],
                            event["status"],
                            int(event["started_at_ms"]),
                            int(event["ended_at_ms"]) if event.get("ended_at_ms") is not None else None,
                            event.get("input_summary") or "",
                            event.get("error"),
                            1 if event.get("replayable", True) else 0,
                        ),
                    )
            else:
                self._conn.execute(
                    """
                    INSERT INTO step_events (
                        task_id, step_id, step_type, name, status,
                        started_at_ms, ended_at_ms, input_summary, error, replayable
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event["task_id"],
                        event["step_id"],
                        event["step_type"],
                        event["name"],
                        event["status"],
                        int(event["started_at_ms"]),
                        int(event["ended_at_ms"]) if event.get("ended_at_ms") is not None else None,
                        event.get("input_summary") or "",
                        event.get("error"),
                        1 if event.get("replayable", True) else 0,
                    ),
                )

    def _insert_outbox_event(self, event: dict[str, Any], *, commit: bool = True) -> None:
        params = (
            event["event_id"],
            event["task_id"],
            event["step_id"],
            event["effect_type"],
            event["target"],
            self._dump_json(dict(event.get("payload") or {})),
            event["status"],
            int(event.get("attempts") or 0),
            int(event["created_at_ms"]),
            int(event["updated_at_ms"]),
            int(event["next_attempt_at_ms"]) if event.get("next_attempt_at_ms") is not None else None,
            event.get("error"),
            self._dump_json(dict(event.get("metadata") or {})),
        )
        with self._db_lock:
            if commit:
                with self._conn:
                    self._conn.execute(
                        """
                        INSERT INTO outbox_events (
                            event_id, task_id, step_id, effect_type, target, payload_json,
                            status, attempts, created_at_ms, updated_at_ms, next_attempt_at_ms,
                            error, metadata_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        params,
                    )
            else:
                self._conn.execute(
                    """
                    INSERT INTO outbox_events (
                        event_id, task_id, step_id, effect_type, target, payload_json,
                        status, attempts, created_at_ms, updated_at_ms, next_attempt_at_ms,
                        error, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    params,
                )

    def clear_all(self) -> None:
        with self._db_lock, self._conn:
            self._conn.execute("DELETE FROM outbox_events")
            self._conn.execute("DELETE FROM step_events")
            self._conn.execute("DELETE FROM tasks")

    def has_any_data(self) -> bool:
        with self._db_lock:
            for table in ("tasks", "step_events", "outbox_events"):
                row = self._conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
                if row is not None:
                    return True
        return False

    def import_task_payload(self, payload: dict[str, Any]) -> None:
        self._require_valid_task_id(str(payload.get("task_id") or ""))
        task = dict(payload)
        task.setdefault("resume_context", {})
        task.setdefault("metadata", {})
        with self._db_lock, self._conn:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO tasks (
                    task_id, session_key, agent_id, mode, channel, goal, status, current_stage,
                    created_at_ms, updated_at_ms, last_successful_step, resume_from_step,
                    resume_context_json, error, metadata_json, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._task_to_row(task),
            )

    def import_step_event(self, event: dict[str, Any]) -> None:
        self._require_valid_task_id(str(event.get("task_id") or ""))
        self._require_valid_step_id(str(event.get("step_id") or ""))
        payload = dict(event)
        payload.setdefault("input_summary", "")
        payload.setdefault("replayable", True)
        self._insert_step_event(payload)

    def import_outbox_event(self, event: dict[str, Any]) -> None:
        self._require_valid_task_id(str(event.get("task_id") or ""))
        self._require_valid_outbox_id(str(event.get("event_id") or ""))
        self._require_valid_step_id(str(event.get("step_id") or ""))
        payload = dict(event)
        payload.setdefault("payload", {})
        payload.setdefault("metadata", {})
        self._insert_outbox_event(payload)

    def _read_outbox_events_unlocked(self) -> list[dict[str, Any]]:
        with self._db_lock:
            rows = self._conn.execute("SELECT * FROM outbox_events ORDER BY seq ASC").fetchall()
        return [self._row_to_outbox(row) for row in rows]

    def _materialize_outbox_events_unlocked(self) -> list[dict[str, Any]]:
        latest_by_event: dict[str, dict[str, Any]] = {}
        for event in self._read_outbox_events_unlocked():
            event_id = str(event.get("event_id", "")).strip()
            if not event_id:
                continue
            latest_by_event[event_id] = event
        return sorted(
            latest_by_event.values(),
            key=lambda item: int(item.get("updated_at_ms") or 0),
            reverse=True,
        )

    def _read_outbox_event_unlocked(self, event_id: str) -> dict[str, Any] | None:
        with self._db_lock:
            row = self._conn.execute(
                "SELECT * FROM outbox_events WHERE event_id = ? ORDER BY seq DESC LIMIT 1",
                (event_id,),
            ).fetchone()
        return self._row_to_outbox(row) if row else None

    def _update_outbox_event_unlocked(self, event_id: str, **updates: Any) -> dict[str, Any] | None:
        current = self._read_outbox_event_unlocked(event_id)
        if not current:
            return None
        current.update(updates)
        next_updated = _now_ms()
        previous_updated = int(current.get("updated_at_ms") or 0)
        current["updated_at_ms"] = max(next_updated, previous_updated + 1)
        self._insert_outbox_event(current)
        return current

    def _task_path(self, task_id: str) -> Path:
        self._require_valid_task_id(task_id)
        return self._state_dir / f"{task_id}.json"

    def _steps_path(self, task_id: str) -> Path:
        self._require_valid_task_id(task_id)
        return self._state_dir / f"{task_id}.steps.jsonl"

    def _outbox_path(self) -> Path:
        return self._state_dir / "outbox.jsonl"
