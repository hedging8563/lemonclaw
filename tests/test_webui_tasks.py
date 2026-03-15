from __future__ import annotations

from types import SimpleNamespace

from starlette.testclient import TestClient

from lemonclaw.config.loader import save_config
from lemonclaw.config.schema import Config
from lemonclaw.gateway.server import create_app
from lemonclaw.gateway.webui.auth import create_session_cookie
from lemonclaw.ledger.runtime import TaskLedger
from lemonclaw.session.manager import SessionManager
from lemonclaw.watchdog.service import WatchdogService


def _build_app(tmp_path, *, auth_token=None, watchdog=None, ledger=None, channel_manager=None):
    config_path = tmp_path / "config.json"
    save_config(Config(), config_path)
    ledger = ledger or TaskLedger(tmp_path)
    agent_loop = SimpleNamespace(workspace=tmp_path, ledger=ledger)
    session_manager = SessionManager(tmp_path)
    app = create_app(
        config_path=config_path,
        auth_token=auth_token,
        channel_manager=channel_manager,
        agent_loop=agent_loop,
        session_manager=session_manager,
        webui_enabled=True,
        watchdog=watchdog,
    )
    return app, ledger


def test_tasks_api_lists_tasks_and_filters_by_session(tmp_path):
    app, ledger = _build_app(tmp_path)
    ledger.ensure_task(
        task_id="task_a",
        session_key="telegram:123",
        agent_id="default",
        mode="chat",
        channel="telegram",
        goal="alpha",
        current_stage="dispatch",
    )
    ledger.ensure_task(
        task_id="task_b",
        session_key="webui:abc",
        agent_id="default",
        mode="chat",
        channel="webui",
        goal="beta",
        current_stage="execute",
    )
    ledger.update_task("task_b", status="completed", current_stage="done")

    client = TestClient(app)

    resp = client.get("/api/tasks")
    assert resp.status_code == 200
    tasks = resp.json()["tasks"]
    assert [item["task_id"] for item in tasks] == ["task_b", "task_a"]

    resp = client.get("/api/tasks", params={"session_key": "telegram:123"})
    assert resp.status_code == 200
    tasks = resp.json()["tasks"]
    assert [item["task_id"] for item in tasks] == ["task_a"]


def test_tasks_api_returns_materialized_task_detail(tmp_path):
    app, ledger = _build_app(tmp_path)
    ledger.ensure_task(
        task_id="task_1",
        session_key="telegram:123",
        agent_id="default",
        mode="chat",
        channel="telegram",
        goal="say hello",
        current_stage="execute",
    )
    step = ledger.start_step("task_1", step_type="tool_call", name="read_file", input_summary='{"path":"x"}')
    ledger.finish_step(step, status="completed")
    ledger.update_task("task_1", status="completed", current_stage="done")

    client = TestClient(app)
    resp = client.get("/api/tasks/task_1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["task"]["task_id"] == "task_1"
    assert data["summary"]["step_count"] == 1
    assert data["summary"]["status_counts"]["completed"] == 1
    assert data["summary"]["last_successful_step"] == "read_file"


def test_tasks_api_rejects_invalid_task_id(tmp_path):
    app, _ledger = _build_app(tmp_path)
    client = TestClient(app)

    resp = client.get("/api/tasks/not-a-task")
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid task_id"


def test_task_recheck_api_reruns_completion_gate(tmp_path):
    app, ledger = _build_app(tmp_path)
    ledger.ensure_task(
        task_id="task_1",
        session_key="telegram:123",
        agent_id="default",
        mode="chat",
        channel="telegram",
        goal="say hello",
        status="waiting",
        current_stage="waiting_outbox",
        metadata={
            "recovery": {
                "action": "manual_retry_requested",
                "manual_review_required": False,
                "source": "webui_manual_retry",
            }
        },
    )

    client = TestClient(app)
    resp = client.post("/api/tasks/task_1/recheck")
    assert resp.status_code == 200
    data = resp.json()
    assert data["result"]["passed"] is True
    assert data["task"]["status"] == "completed"
    assert data["summary"]["completion_gate"]["passed"] is True
    assert data["task"]["metadata"]["recovery_history"][-1]["action"] == "task_recheck"


def test_task_resume_api_sets_resume_from_step(tmp_path):
    app, ledger = _build_app(tmp_path)
    ledger.ensure_task(
        task_id="task_1",
        session_key="telegram:123",
        agent_id="default",
        mode="chat",
        channel="telegram",
        goal="resume me",
        status="failed",
        current_stage="execute",
    )
    step = ledger.start_step("task_1", step_type="tool_call", name="notify")
    ledger.finish_step(step, status="failed", error="boom")

    client = TestClient(app)
    resp = client.post("/api/tasks/task_1/resume")
    assert resp.status_code == 200
    data = resp.json()
    assert data["task"]["status"] == "waiting"
    assert data["task"]["current_stage"] == "resume_requested"
    assert data["task"]["resume_from_step"] == step.step_id
    assert data["summary"]["resume_from_step"] == step.step_id


def test_resume_candidate_api_reports_safe_retry_outbox(tmp_path):
    app, ledger = _build_app(tmp_path)
    ledger.ensure_task(
        task_id="task_1",
        session_key="telegram:123",
        agent_id="default",
        mode="chat",
        channel="telegram",
        goal="resume me",
        status="waiting",
        current_stage="waiting_outbox",
    )
    step = ledger.start_step("task_1", step_type="tool_call", name="notify")
    ledger.finish_step(step, status="waiting_outbox", error="boom")
    ledger.enqueue_outbox(
        task_id="task_1",
        step_id=step.step_id,
        effect_type="outbound_message",
        target="telegram:123",
        payload={"content": "hello"},
        status="failed",
        error="boom",
    )

    client = TestClient(app)
    resp = client.get("/api/tasks/task_1/resume-candidate")
    assert resp.status_code == 200
    data = resp.json()["candidate"]
    assert data["recommended_action"] == "retry_outbox"
    assert data["safe_to_execute"] is True


def test_safe_resume_execute_api_retries_failed_outbox(tmp_path):
    app, ledger = _build_app(tmp_path)
    ledger.ensure_task(
        task_id="task_1",
        session_key="telegram:123",
        agent_id="default",
        mode="chat",
        channel="telegram",
        goal="resume me",
        status="waiting",
        current_stage="waiting_outbox",
    )
    step = ledger.start_step("task_1", step_type="tool_call", name="notify")
    ledger.finish_step(step, status="waiting_outbox", error="boom")
    event = ledger.enqueue_outbox(
        task_id="task_1",
        step_id=step.step_id,
        effect_type="outbound_message",
        target="telegram:123",
        payload={"content": "hello"},
        status="failed",
        attempts=1,
        error="boom",
    )

    client = TestClient(app)
    resp = client.post("/api/tasks/task_1/resume/execute")
    assert resp.status_code == 200
    data = resp.json()
    assert data["candidate"]["recommended_action"] in {"wait_outbox", "manual_resume"}
    updated = ledger.read_outbox_event(event["event_id"])
    assert updated is not None
    assert updated["status"] == "retrying"


def test_tasks_api_requires_auth_when_token_enabled(tmp_path):
    app, ledger = _build_app(tmp_path, auth_token="secret-token")
    ledger.ensure_task(
        task_id="task_a",
        session_key="telegram:123",
        agent_id="default",
        mode="chat",
        channel="telegram",
        goal="alpha",
    )
    client = TestClient(app)

    resp = client.get("/api/tasks")
    assert resp.status_code == 401

    cookie = create_session_cookie("secret-token")
    client.cookies.set("lc_session", cookie)
    resp = client.get("/api/tasks")
    assert resp.status_code == 200


def test_outbox_api_lists_and_reads_events(tmp_path):
    app, ledger = _build_app(tmp_path)
    ledger.ensure_task(
        task_id="task_a",
        session_key="telegram:123",
        agent_id="default",
        mode="chat",
        channel="telegram",
        goal="alpha",
    )
    event = ledger.enqueue_outbox(
        task_id="task_a",
        step_id="step_notify",
        effect_type="outbound_message",
        target="telegram:123",
        payload={"content": "hello"},
    )

    client = TestClient(app)

    resp = client.get("/api/outbox")
    assert resp.status_code == 200
    assert [item["event_id"] for item in resp.json()["events"]] == [event["event_id"]]

    resp = client.get(f"/api/outbox/{event['event_id']}")
    assert resp.status_code == 200
    assert resp.json()["event"]["target"] == "telegram:123"


def test_outbox_api_rejects_invalid_ids(tmp_path):
    app, _ledger = _build_app(tmp_path)
    client = TestClient(app)

    resp = client.get("/api/outbox/not-an-event")
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid event_id"

    resp = client.get("/api/outbox", params={"task_id": "not-a-task"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid task_id"


def test_outbox_compact_api_rewrites_retained_state(tmp_path):
    app, ledger = _build_app(tmp_path)
    ledger.ensure_task(
        task_id="task_a",
        session_key="telegram:123",
        agent_id="default",
        mode="chat",
        channel="telegram",
        goal="alpha",
    )
    old_event = ledger.enqueue_outbox(
        task_id="task_a",
        step_id="step_notify",
        effect_type="outbound_message",
        target="telegram:123",
        payload={"content": "old"},
    )
    ledger.update_outbox_event(old_event["event_id"], status="sent")
    old_record = ledger.read_outbox_event(old_event["event_id"])
    old_record["updated_at_ms"] = 1
    ledger._append_jsonl(ledger._outbox_path(), old_record)

    pending = ledger.enqueue_outbox(
        task_id="task_a",
        step_id="step_notify",
        effect_type="outbound_message",
        target="telegram:123",
        payload={"content": "pending"},
        status="retrying",
        next_attempt_at_ms=9_999,
    )

    client = TestClient(app)
    resp = client.post("/api/outbox/compact", json={"keep_terminal": 0, "min_terminal_age_ms": 1000})
    assert resp.status_code == 200
    data = resp.json()
    assert data["result"]["before"] == 2
    assert data["result"]["after"] == 1
    assert [item["event_id"] for item in data["events"]] == [pending["event_id"]]


def test_recovery_api_lists_tasks_with_recovery_metadata(tmp_path):
    app, ledger = _build_app(tmp_path)
    ledger.ensure_task(
        task_id="task_a",
        session_key="telegram:123",
        agent_id="default",
        mode="chat",
        channel="telegram",
        goal="alpha",
        status="running",
        current_stage="execute",
    )
    ledger.mark_task_stale(
        "task_a",
        source="watchdog_soft_recovery",
        reason="no task ledger update for >1s",
        stale_after_ms=1000,
    )

    client = TestClient(app)
    resp = client.get("/api/recovery")
    assert resp.status_code == 200
    data = resp.json()
    assert data["summary"]["tasks_with_recovery"] == 1
    assert data["summary"]["stale_recovery_failed"] == 1
    assert [item["task_id"] for item in data["tasks"]] == ["task_a"]


def test_recovery_api_can_filter_manual_review_tasks_without_changing_summary(tmp_path):
    app, ledger = _build_app(tmp_path)
    ledger.ensure_task(
        task_id="task_waiting",
        session_key="telegram:123",
        agent_id="default",
        mode="chat",
        channel="telegram",
        goal="waiting review",
        status="waiting",
        current_stage="waiting_outbox",
    )
    ledger.mark_task_stale(
        "task_waiting",
        source="watchdog_soft_recovery",
        reason="no task ledger update for >1s",
        stale_after_ms=1000,
    )
    ledger.ensure_task(
        task_id="task_failed",
        session_key="telegram:123",
        agent_id="default",
        mode="chat",
        channel="telegram",
        goal="failed recovery",
        status="running",
        current_stage="execute",
    )
    ledger.mark_task_stale(
        "task_failed",
        source="watchdog_soft_recovery",
        reason="no task ledger update for >1s",
        stale_after_ms=1000,
    )

    client = TestClient(app)
    resp = client.get("/api/recovery", params={"manual_review_only": "true"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["summary"]["tasks_with_recovery"] == 2
    assert data["summary"]["manual_review_required"] == 1
    assert [item["task_id"] for item in data["tasks"]] == ["task_waiting"]


def test_watchdog_api_returns_runtime_snapshot(tmp_path):
    ledger = TaskLedger(tmp_path)
    watchdog = WatchdogService(task_ledger=ledger, task_stuck_threshold_s=1)
    app, _ = _build_app(tmp_path, watchdog=watchdog, ledger=ledger)
    ledger.ensure_task(
        task_id="task_a",
        session_key="telegram:123",
        agent_id="default",
        mode="chat",
        channel="telegram",
        goal="alpha",
        status="running",
        current_stage="execute",
    )
    task = ledger.read_task("task_a")
    assert task is not None
    task["updated_at_ms"] = 1
    ledger._write_json(ledger._task_path("task_a"), task)

    client = TestClient(app)
    resp = client.get("/api/watchdog")
    assert resp.status_code == 200
    data = resp.json()["watchdog"]
    assert data["config"]["task_stuck_threshold_s"] == 1
    assert data["task_stuck"]["count"] == 1
    assert data["task_stuck"]["task_ids"] == ["task_a"]


def test_outbox_retry_api_reschedules_event_and_clears_manual_review(tmp_path):
    app, ledger = _build_app(tmp_path)
    ledger.ensure_task(
        task_id="task_a",
        session_key="telegram:123",
        agent_id="default",
        mode="chat",
        channel="telegram",
        goal="alpha",
        status="waiting",
        current_stage="waiting_outbox",
        metadata={
            "recovery": {
                "action": "manual_review",
                "manual_review_required": True,
                "source": "watchdog_soft_recovery",
            }
        },
    )
    event = ledger.enqueue_outbox(
        task_id="task_a",
        step_id="step_notify",
        effect_type="outbound_message",
        target="telegram:123",
        payload={"content": "hello"},
        status="failed",
        error="temporary failure",
    )

    client = TestClient(app)
    resp = client.post(f"/api/outbox/{event['event_id']}/retry")
    assert resp.status_code == 200
    data = resp.json()
    assert data["event"]["status"] == "pending"
    assert data["task"]["metadata"]["recovery"]["action"] == "manual_retry_requested"
    assert data["task"]["metadata"]["recovery"]["manual_review_required"] is False


def test_outbox_retry_api_rejects_sent_event(tmp_path):
    app, ledger = _build_app(tmp_path)
    ledger.ensure_task(
        task_id="task_a",
        session_key="telegram:123",
        agent_id="default",
        mode="chat",
        channel="telegram",
        goal="alpha",
    )
    event = ledger.enqueue_outbox(
        task_id="task_a",
        step_id="step_notify",
        effect_type="outbound_message",
        target="telegram:123",
        payload={"content": "hello"},
        status="sent",
    )

    client = TestClient(app)
    resp = client.post(f"/api/outbox/{event['event_id']}/retry")
    assert resp.status_code == 409
    assert resp.json()["error"] == "cannot retry a sent outbox event"


def test_channel_restart_api_calls_manager(tmp_path):
    manager = SimpleNamespace(
        restart_channel=__import__("unittest").mock.AsyncMock(return_value={"channel": "telegram", "running": True, "task_done": False}),
        get_status=lambda: {"telegram": {"enabled": True, "running": True}},
    )
    app, _ledger = _build_app(tmp_path, channel_manager=manager)

    client = TestClient(app)
    resp = client.post("/api/channels/telegram/restart")
    assert resp.status_code == 200
    data = resp.json()
    assert data["result"]["channel"] == "telegram"
    manager.restart_channel.assert_awaited_once_with("telegram", reason="", source="webui")
