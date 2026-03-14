from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from lemonclaw.ledger.runtime import TaskLedger
from lemonclaw.watchdog.service import HealthCheck, WatchdogService


def _seed_stale_task(
    ledger: TaskLedger,
    *,
    task_id: str,
    status: str,
    current_stage: str,
) -> None:
    ledger.ensure_task(
        task_id=task_id,
        session_key="cli:direct",
        agent_id="default",
        mode="chat",
        channel="cli",
        goal="demo",
        status=status,
        current_stage=current_stage,
    )
    task = ledger.read_task(task_id)
    assert task is not None
    task["updated_at_ms"] = 1
    ledger._write_json(ledger._task_path(task_id), task)


def test_watchdog_detects_stale_tasks_from_ledger(tmp_path: Path):
    ledger = TaskLedger(tmp_path)
    _seed_stale_task(ledger, task_id="task_1", status="running", current_stage="execute")
    watchdog = WatchdogService(task_ledger=ledger, task_stuck_threshold_s=1)

    check = watchdog._check_task_stuck()

    assert check == HealthCheck("task_stuck", False, "1 stale task(s): task_1")


@pytest.mark.asyncio
async def test_watchdog_soft_recovery_marks_running_task_failed(tmp_path: Path):
    ledger = TaskLedger(tmp_path)
    _seed_stale_task(ledger, task_id="task_1", status="running", current_stage="execute")
    watchdog = WatchdogService(task_ledger=ledger, task_stuck_threshold_s=1)

    await watchdog._soft_recovery([HealthCheck("task_stuck", False, "1 stale task(s): task_1")])

    task = ledger.read_task("task_1")
    assert task is not None
    assert task["status"] == "failed"
    assert task["current_stage"] == "stale_recovery"
    assert task["metadata"]["recovery"]["source"] == "watchdog_soft_recovery"


@pytest.mark.asyncio
async def test_watchdog_soft_recovery_keeps_waiting_task_in_manual_review(tmp_path: Path):
    ledger = TaskLedger(tmp_path)
    _seed_stale_task(ledger, task_id="task_1", status="waiting", current_stage="waiting_outbox")
    watchdog = WatchdogService(task_ledger=ledger, task_stuck_threshold_s=1)

    await watchdog._soft_recovery([HealthCheck("task_stuck", False, "1 stale task(s): task_1")])

    task = ledger.read_task("task_1")
    assert task is not None
    assert task["status"] == "waiting"
    assert task["current_stage"] == "waiting_outbox"
    assert task["metadata"]["recovery"]["action"] == "manual_review"
    assert task["metadata"]["recovery"]["manual_review_required"] is True
    assert watchdog._check_task_stuck() == HealthCheck("task_stuck", True)


@pytest.mark.asyncio
async def test_watchdog_start_offloads_startup_scan_to_thread(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    ledger = TaskLedger(tmp_path)
    watchdog = WatchdogService(task_ledger=ledger, task_stuck_threshold_s=1)
    to_thread = AsyncMock(return_value=0)

    monkeypatch.setattr("lemonclaw.watchdog.service.asyncio.to_thread", to_thread)
    monkeypatch.setattr(watchdog, "_setup_alarm", lambda: None)

    await watchdog.start()
    watchdog.stop()
    await __import__("asyncio").sleep(0)

    to_thread.assert_awaited_once()
