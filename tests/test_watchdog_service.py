from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from lemonclaw.ledger.runtime import TaskLedger
from lemonclaw.session.manager import Session, SessionManager
from lemonclaw.triggers import TriggerRuntime
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


def _seed_stale_session_file(manager: SessionManager, *, key: str, updated_at: datetime) -> None:
    session = Session(
        key=key,
        messages=[{"role": "user", "content": "hello", "timestamp": updated_at.isoformat()}],
        created_at=updated_at,
        updated_at=updated_at,
    )
    manager._atomic_save(manager._get_session_path(key), session)


def test_watchdog_detects_stale_tasks_from_ledger(tmp_path: Path):
    ledger = TaskLedger(tmp_path, backend="json")
    _seed_stale_task(ledger, task_id="task_1", status="running", current_stage="execute")
    watchdog = WatchdogService(task_ledger=ledger, task_stuck_threshold_s=1)

    check = watchdog._check_task_stuck()

    assert check == HealthCheck("task_stuck", False, "1 stale task(s): task_1")


def test_watchdog_detects_stale_cached_sessions_without_disk_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    sessions = SessionManager(tmp_path)
    live = sessions.get_or_create("telegram:live")
    live.add_message("user", "hello")
    live.updated_at = datetime.now() - timedelta(seconds=10)
    sessions.save(live)

    archived_at = datetime.now() - timedelta(seconds=10)
    _seed_stale_session_file(sessions, key="telegram:archived", updated_at=archived_at)

    monkeypatch.setattr("lemonclaw.watchdog.service.SESSION_STUCK_THRESHOLD", 1)
    watchdog = WatchdogService(session_manager=sessions)

    check = watchdog._check_session_stuck()

    assert check == HealthCheck("session_stuck", False, "1 stuck session(s)")
    assert [item["key"] for item in sessions.list_cached_sessions()] == ["telegram:live"]


@pytest.mark.asyncio
async def test_watchdog_soft_recovery_marks_running_task_failed(tmp_path: Path):
    ledger = TaskLedger(tmp_path, backend="json")
    _seed_stale_task(ledger, task_id="task_1", status="running", current_stage="execute")
    watchdog = WatchdogService(task_ledger=ledger, task_stuck_threshold_s=1)

    await watchdog._soft_recovery([HealthCheck("task_stuck", False, "1 stale task(s): task_1")])

    task = ledger.read_task("task_1")
    assert task is not None
    assert task["status"] == "failed"
    assert task["current_stage"] == "stale_recovery"
    assert task["metadata"]["recovery"]["source"] == "watchdog_soft_recovery"


@pytest.mark.asyncio
async def test_watchdog_soft_recovery_only_invalidates_cached_stale_sessions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    sessions = SessionManager(tmp_path)
    live = sessions.get_or_create("telegram:live")
    live.add_message("user", "hello")
    live.updated_at = datetime.now() - timedelta(seconds=10)
    sessions.save(live)

    archived_at = datetime.now() - timedelta(seconds=10)
    _seed_stale_session_file(sessions, key="telegram:archived", updated_at=archived_at)

    monkeypatch.setattr("lemonclaw.watchdog.service.SESSION_STUCK_THRESHOLD", 1)
    watchdog = WatchdogService(session_manager=sessions)

    invalidated: list[str] = []
    original_invalidate = sessions.invalidate

    def _record_invalidate(key: str) -> None:
        invalidated.append(key)
        original_invalidate(key)

    monkeypatch.setattr(sessions, "invalidate", _record_invalidate)

    await watchdog._soft_recovery([HealthCheck("session_stuck", False, "1 stuck session(s)")])

    assert invalidated == ["telegram:live"]


@pytest.mark.asyncio
async def test_watchdog_soft_recovery_keeps_waiting_task_in_manual_review(tmp_path: Path):
    ledger = TaskLedger(tmp_path, backend="json")
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
    ledger = TaskLedger(tmp_path, backend="json")
    watchdog = WatchdogService(task_ledger=ledger, task_stuck_threshold_s=1)
    to_thread = AsyncMock(return_value=0)

    monkeypatch.setattr("lemonclaw.watchdog.service.asyncio.to_thread", to_thread)
    monkeypatch.setattr(watchdog, "_setup_alarm", lambda: None)

    await watchdog.start()
    watchdog.stop()
    await __import__("asyncio").sleep(0)

    to_thread.assert_awaited_once()


def test_watchdog_detects_down_channels():
    manager = type("Mgr", (), {"get_status": lambda self: {"telegram": {"enabled": True, "available": True, "running": False}}})()
    watchdog = WatchdogService(channel_manager=manager)

    check = watchdog._check_channels()

    assert check == HealthCheck("channel_down", False, "down: telegram")


def test_watchdog_ignores_unavailable_channels_with_config_errors():
    manager = type("Mgr", (), {
        "get_status": lambda self: {
            "telegram": {
                "enabled": True,
                "available": False,
                "running": False,
                "error": "token rejected by upstream",
            },
        },
    })()
    watchdog = WatchdogService(channel_manager=manager)

    check = watchdog._check_channels()

    assert check.healthy is True
    assert check.name == "channel_down"
    assert "blocked:" in check.detail


@pytest.mark.asyncio
async def test_watchdog_soft_recovery_restarts_down_channels():
    manager = type("Mgr", (), {
        "get_status": lambda self: {"telegram": {"enabled": True, "available": True, "running": False}},
        "restart_channel": AsyncMock(return_value={"channel": "telegram", "running": True, "task_done": False}),
    })()
    watchdog = WatchdogService(channel_manager=manager)

    await watchdog._soft_recovery([HealthCheck("channel_down", False, "down: telegram")])

    manager.restart_channel.assert_awaited_once_with(
        "telegram", reason="channel_down detected", source="watchdog",
    )


@pytest.mark.asyncio
async def test_watchdog_soft_recovery_skips_unavailable_channels():
    manager = type("Mgr", (), {
        "get_status": lambda self: {"telegram": {"enabled": True, "available": False, "running": False, "error": "token rejected"}},
        "restart_channel": AsyncMock(return_value={"channel": "telegram", "running": True, "task_done": False}),
    })()
    watchdog = WatchdogService(channel_manager=manager)

    await watchdog._soft_recovery([HealthCheck("channel_down", False, "down: telegram")])

    manager.restart_channel.assert_not_awaited()


@pytest.mark.asyncio
async def test_watchdog_hard_recovery_marks_active_tasks_before_exit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    ledger = TaskLedger(tmp_path, backend="json")
    _seed_stale_task(ledger, task_id="task_1", status="running", current_stage="execute")
    watchdog = WatchdogService(task_ledger=ledger)

    async def _sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("lemonclaw.watchdog.service.asyncio.sleep", _sleep)
    monkeypatch.setattr("lemonclaw.watchdog.service.os.kill", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("lemonclaw.watchdog.service.os._exit", lambda _code: (_ for _ in ()).throw(SystemExit(_code)))

    with pytest.raises(SystemExit):
        await watchdog._hard_recovery([HealthCheck("memory", False, "RSS high")])

    task = ledger.read_task("task_1")
    assert task is not None
    assert task["status"] == "failed"
    assert task["current_stage"] == "hard_recovery"
    assert task["metadata"]["recovery"]["source"] == "watchdog_hard_recovery"


@pytest.mark.asyncio
async def test_watchdog_records_trigger_runtime_entries(tmp_path: Path):
    ledger = TaskLedger(tmp_path, backend="json")
    trigger_runtime = TriggerRuntime(tmp_path)
    watchdog = WatchdogService(task_ledger=ledger, task_stuck_threshold_s=1, trigger_runtime=trigger_runtime)

    await watchdog._soft_recovery([HealthCheck("task_stuck", False, "1 stale task(s): task_1")])

    records = trigger_runtime.list_triggers(limit=10)
    assert any(item["source"] == "watchdog" and item["kind"] == "watchdog.soft_recovery" for item in records)
    assert any(item["source"] == "alert.watchdog" and item["kind"] == "soft.task_stuck" for item in records)
