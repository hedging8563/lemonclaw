"""Ledger migration helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lemonclaw.ledger.runtime import TaskLedger
from lemonclaw.ledger.sqlite_store import SQLiteTaskLedger


def migrate_json_to_sqlite(workspace: Path, *, force: bool = False) -> dict[str, Any]:
    """Copy legacy JSON ledger state into the SQLite backend."""
    json_ledger = TaskLedger(workspace, backend="json")
    sqlite_ledger = TaskLedger(workspace, backend="sqlite")
    sqlite_impl = getattr(sqlite_ledger, "_impl", None)
    json_impl = getattr(json_ledger, "_impl", None)
    if not isinstance(sqlite_impl, SQLiteTaskLedger):
        raise RuntimeError("sqlite backend is not available")

    state_dir = getattr(json_impl, "_state_dir", workspace / ".lemonclaw-state" / "tasks")
    task_paths = sorted(state_dir.glob("task_*.json"))
    if not task_paths and not (state_dir / "outbox.jsonl").exists():
        return {"tasks": 0, "step_events": 0, "outbox_events": 0, "skipped": True}

    if sqlite_impl.has_any_data():
        if not force:
            raise RuntimeError("sqlite ledger already contains data; rerun with force=True to overwrite")
        sqlite_impl.clear_all()

    migrated_tasks = 0
    migrated_step_events = 0
    migrated_outbox_events = 0

    for path in task_paths:
        task_id = path.stem
        task = json_ledger.read_task(task_id)
        if not task:
            continue
        sqlite_impl.import_task_payload(task)
        migrated_tasks += 1
        for step in json_ledger.read_steps(task_id):
            sqlite_impl.import_step_event(step)
            migrated_step_events += 1

    for event in json_ledger.read_outbox_events():
        sqlite_impl.import_outbox_event(event)
        migrated_outbox_events += 1

    return {
        "tasks": migrated_tasks,
        "step_events": migrated_step_events,
        "outbox_events": migrated_outbox_events,
        "skipped": False,
    }
