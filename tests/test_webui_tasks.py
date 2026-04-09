from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from starlette.testclient import TestClient

from lemonclaw.config.loader import save_config
from lemonclaw.config.schema import Config
from lemonclaw.gateway.server import create_app
from lemonclaw.gateway.webui.auth import create_session_cookie
from lemonclaw.ledger.runtime import TaskLedger
from lemonclaw.session.manager import SessionManager
from lemonclaw.triggers import TriggerRuntime
from lemonclaw.watchdog.service import WatchdogService


def _build_app(tmp_path, *, auth_token=None, watchdog=None, ledger=None, channel_manager=None, agent_loop=None):
    config_path = tmp_path / "config.json"
    save_config(Config(), config_path)
    ledger = ledger or TaskLedger(tmp_path)
    agent_loop = agent_loop or SimpleNamespace(workspace=tmp_path, ledger=ledger)
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
    assert tasks[0]["display_state"]["key"] == "completed"
    assert tasks[1]["display_state"]["key"] == "running"

    resp = client.get("/api/tasks", params={"session_key": "telegram:123"})
    assert resp.status_code == 200
    tasks = resp.json()["tasks"]
    assert [item["task_id"] for item in tasks] == ["task_a"]


def test_tasks_api_accepts_bearer_auth_token(tmp_path):
    app, ledger = _build_app(tmp_path, auth_token="secret-token")
    ledger.ensure_task(
        task_id="task_a",
        session_key="telegram:123",
        agent_id="default",
        mode="chat",
        channel="telegram",
        goal="alpha",
        current_stage="dispatch",
    )

    client = TestClient(app)
    resp = client.get("/api/tasks", headers={"Authorization": "Bearer secret-token"})

    assert resp.status_code == 200
    assert resp.json()["tasks"][0]["task_id"] == "task_a"


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
        metadata={
            "retrieval": {
                "strategy": "hybrid",
                "latency_ms": 9,
                "hit_sources": ["hybrid"],
                "structured": {
                    "session_summary": "hybrid trace",
                    "fact_slots": [{"name": "tech", "value": "python"}],
                    "retrieval_objects": [{"kind": "entity_card", "name": "tech"}],
                },
            }
        },
    )
    step = ledger.start_step("task_1", step_type="tool_call", name="read_file", input_summary='{"path":"x"}')
    ledger.finish_step(step, status="completed")
    task = ledger.read_task("task_1")
    assert task is not None
    metadata = dict(task.get("metadata") or {})
    ledger.append_recovery_history(
        metadata,
        source="unit_test",
        action="task_recheck",
        reason="verified by test",
        details={"step_id": step.step_id},
    )
    ledger.update_task("task_1", metadata=metadata, resume_from_step=step.step_id)
    ledger.update_task("task_1", status="completed", current_stage="done")

    client = TestClient(app)
    resp = client.get("/api/tasks/task_1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["task"]["task_id"] == "task_1"
    assert data["task"]["display_state"]["key"] == "completed"
    assert data["task"]["retrieval"]["strategy"] == "hybrid"
    assert data["task"]["retrieval"]["structured"]["session_summary"] == "hybrid trace"
    assert data["summary"]["step_count"] == 1
    assert data["summary"]["status_counts"]["completed"] == 1
    assert data["summary"]["display_state"]["key"] == "completed"
    assert data["summary"]["last_successful_step"] == "read_file"
    assert data["summary"]["resume_from_step"] == step.step_id
    assert data["summary"]["recovery_history"][-1]["source"] == "unit_test"
    assert data["summary"]["recovery_history"][-1]["recovery_id"].startswith("rc_")
    assert data["summary"]["recovery_history"][-1]["ref"]["step_id"] == step.step_id
    assert data["summary"]["retrieval"]["latency_ms"] == 9
    assert data["summary"]["retrieval"]["structured"]["fact_slots"][0]["name"] == "tech"


def test_tasks_api_exposes_runtime_correction_metadata(tmp_path):
    app, ledger = _build_app(tmp_path)
    ledger.ensure_task(
        task_id="task_old",
        session_key="telegram:123",
        agent_id="default",
        mode="chat",
        channel="telegram",
        goal="draft answer",
        status="abandoned",
        current_stage="cancelled",
    )
    old_metadata = dict((ledger.read_task("task_old") or {}).get("metadata") or {})
    ledger.append_recovery_history(
        old_metadata,
        source="agent_loop",
        action="user_correction_interrupt",
        reason="follow-up replaced the in-flight task",
        details={"superseded_by_task_id": "task_new"},
    )
    ledger.update_task("task_old", metadata=old_metadata)

    ledger.ensure_task(
        task_id="task_new",
        session_key="telegram:123",
        agent_id="default",
        mode="chat",
        channel="telegram",
        goal="actually, correct that",
        metadata={
            "runtime_correction": {
                "kind": "user_follow_up",
                "message_preview": "actually, correct that",
                "supersedes_task_ids": ["task_old"],
                "supersedes_task_stages": ["dispatch"],
                "interrupted_task_count": 1,
                "delivery_intent": {
                    "delivery_policy": {
                        "mode": "replace",
                        "preserve_message_identity": True,
                    }
                },
            }
        },
    )

    client = TestClient(app)

    old_resp = client.get("/api/tasks/task_old")
    assert old_resp.status_code == 200
    old_data = old_resp.json()
    assert old_data["task"]["metadata"]["recovery_history"][-1]["action"] == "user_correction_interrupt"

    new_resp = client.get("/api/tasks/task_new")
    assert new_resp.status_code == 200
    new_data = new_resp.json()
    runtime_correction = new_data["task"]["metadata"]["runtime_correction"]
    assert runtime_correction["kind"] == "user_follow_up"
    assert runtime_correction["message_preview"] == "actually, correct that"
    assert runtime_correction["supersedes_task_ids"] == ["task_old"]
    assert runtime_correction["supersedes_task_stages"] == ["dispatch"]
    assert runtime_correction["interrupted_task_count"] == 1
    assert runtime_correction["delivery_intent"]["delivery_policy"]["mode"] == "replace"


def test_tasks_api_exposes_runtime_correction_resume_context_and_history(tmp_path):
    app, ledger = _build_app(tmp_path)
    metadata = {
        "runtime_correction": {
            "kind": "constraint_patch",
            "message_preview": "please only patch this file",
            "supersedes_task_ids": ["task_old"],
            "supersedes_task_stages": ["dispatch"],
            "interrupted_task_count": 1,
            "at_ms": 123456,
            "delivery_intent": {
                "delivery_policy": {
                    "mode": "final_only",
                    "preserve_message_identity": True,
                }
            },
        }
    }
    ledger.append_recovery_history(
        metadata,
        source="session_user_correction",
        action="runtime_correction_received",
        reason="user follow-up revised in-flight task (constraint_patch)",
        details={
            "session_key": "telegram:123",
            "correction_kind": "constraint_patch",
            "supersedes_task_ids": ["task_old"],
            "supersedes_task_stages": ["dispatch"],
            "delivery_intent": {
                "delivery_policy": {
                    "mode": "final_only",
                    "preserve_message_identity": True,
                }
            },
        },
        at_ms=123456,
    )
    ledger.ensure_task(
        task_id="task_runtime_context",
        session_key="telegram:123",
        agent_id="default",
        mode="chat",
        channel="telegram",
        goal="apply constraint patch",
        resume_context={
            "channel": "telegram",
            "chat_id": "123",
            "sender_id": "u1",
            "session_key": "telegram:123",
            "timezone": "Asia/Shanghai",
            "message_id": "",
            "delivery_context": {},
            "auto_resume_allowed": True,
            "resume_disabled_reason": "",
            "runtime_correction": {
                "kind": "constraint_patch",
                "supersedes_task_ids": ["task_old"],
                "supersedes_task_stages": ["dispatch"],
                "continued_task_ids": [],
                "continued_task_stages": [],
                "interrupted_task_count": 1,
                "continued_task_count": 0,
                "requested_at_ms": 123456,
                "delivery_intent": {
                    "delivery_policy": {
                        "mode": "final_only",
                        "preserve_message_identity": True,
                    }
                },
            },
        },
        metadata=metadata,
    )

    client = TestClient(app)
    resp = client.get("/api/tasks/task_runtime_context")
    assert resp.status_code == 200
    data = resp.json()
    assert data["task"]["resume_context"]["runtime_correction"]["kind"] == "constraint_patch"
    assert data["task"]["resume_context"]["runtime_correction"]["supersedes_task_ids"] == ["task_old"]
    assert data["task"]["resume_context"]["runtime_correction"]["supersedes_task_stages"] == ["dispatch"]
    assert data["task"]["resume_context"]["runtime_correction"]["delivery_intent"]["delivery_policy"]["mode"] == "final_only"
    assert data["task"]["metadata"]["runtime_correction"]["delivery_intent"]["delivery_policy"]["preserve_message_identity"] is True
    assert data["task"]["metadata"]["runtime_correction"]["supersedes_task_stages"] == ["dispatch"]
    assert data["task"]["metadata"]["recovery_history"][-1]["details"]["supersedes_task_stages"] == ["dispatch"]
    assert data["task"]["metadata"]["recovery_history"][-1]["details"]["delivery_intent"]["delivery_policy"]["mode"] == "final_only"
    assert data["task"]["metadata"]["recovery_history"][-1]["action"] == "runtime_correction_received"


def test_tasks_api_exposes_verification_summary(tmp_path):
    app, ledger = _build_app(tmp_path)
    ledger.ensure_task(
        task_id="task_verify",
        session_key="telegram:123",
        agent_id="default",
        mode="chat",
        channel="telegram",
        goal="verify detail",
        metadata={
            "verification": {
                "requirements": {
                    "min_tool_traces": 1,
                    "required_evidence": ["artifact_bundle"],
                },
                "tool_trace": [
                    {
                        "tool_name": "read_file",
                        "status": "completed",
                        "ok": True,
                    }
                ],
                "acceptance_evidence": [
                    {
                        "kind": "artifact_bundle",
                        "status": "accepted",
                    }
                ],
                "ui_channel_replay": {
                    "channel": "telegram",
                    "chat_id": "123",
                },
            }
        },
    )
    ledger.update_task("task_verify", status="completed", current_stage="done")

    client = TestClient(app)
    resp = client.get("/api/tasks/task_verify")
    assert resp.status_code == 200
    data = resp.json()
    assert data["task"]["verification"]["acceptance_evidence_summary"]["count"] == 1
    assert data["task"]["verification"]["surface_replay_pointer"]["channel"] == "telegram"
    verification = data["summary"]["verification"]
    assert verification["required"] is True
    assert verification["tool_trace_count"] == 1
    assert verification["accepted_evidence_count"] == 1
    assert verification["ui_channel_replay_available"] is True
    assert verification["missing_requirements"] == []
    assert verification["acceptance_evidence_summary"]["count"] == 1
    assert verification["acceptance_evidence_summary"]["accepted_count"] == 1
    assert verification["surface_replay_pointer"]["channel"] == "telegram"
    assert verification["surface_replay_pointer"]["chat_id"] == "123"

    export_json = client.get("/api/tasks/task_verify/export", params={"format": "json"})
    assert export_json.status_code == 200
    assert export_json.json()["task"]["verification"]["acceptance_evidence_summary"]["accepted_count"] == 1
    assert export_json.json()["summary"]["verification"]["surface_replay_pointer"]["channel"] == "telegram"

    pm_json = client.get("/api/tasks/task_verify/postmortem", params={"format": "json"})
    assert pm_json.status_code == 200
    assert pm_json.json()["task"]["verification"]["acceptance_evidence_summary"]["count"] == 1
    assert pm_json.json()["summary"]["verification"]["surface_replay_pointer"]["chat_id"] == "123"


def test_info_api_includes_channel_status_snapshot(tmp_path):
    channel_manager = SimpleNamespace(
        get_channel_status=lambda: {
            "telegram": {
                "configured_enabled": True,
                "registered": True,
                "running": True,
                "available": True,
                "error": "",
            },
            "wecom": {
                "configured_enabled": True,
                "registered": False,
                "running": False,
                "available": False,
                "error": "missing dependency",
            },
        }
    )
    app, _ledger = _build_app(tmp_path, channel_manager=channel_manager)
    client = TestClient(app)

    resp = client.get("/api/info")
    assert resp.status_code == 200
    data = resp.json()
    assert data["channels"]["telegram"]["running"] is True
    assert data["channels"]["wecom"]["available"] is False
    assert data["channels"]["wecom"]["error"] == "missing dependency"


def test_memory_api_includes_search_index_status(tmp_path):
    app, _ledger = _build_app(tmp_path)
    client = TestClient(app)

    resp = client.get("/api/memory")
    assert resp.status_code == 200
    data = resp.json()
    assert "search_index" in data
    assert "available" in data["search_index"]
    assert "last_operation" in data["search_index"]


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
    assert data["task"]["display_state"]["key"] == "resume_requested"
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


def test_safe_resume_execute_api_retries_expired_outbox(tmp_path):
    app, ledger = _build_app(tmp_path)
    ledger.ensure_task(
        task_id="task_1",
        session_key="telegram:123",
        agent_id="default",
        mode="chat",
        channel="telegram",
        goal="resume expired outbox",
        status="waiting",
        current_stage="waiting_outbox",
    )
    step = ledger.start_step("task_1", step_type="tool_call", name="notify")
    ledger.finish_step(step, status="waiting_outbox", error="expired")
    event = ledger.enqueue_outbox(
        task_id="task_1",
        step_id=step.step_id,
        effect_type="outbound_message",
        target="telegram:123",
        payload={"content": "hello"},
        status="expired",
        attempts=1,
        error="expired by retention policy",
    )

    client = TestClient(app)
    resp = client.post("/api/tasks/task_1/resume/execute")
    assert resp.status_code == 200
    data = resp.json()
    assert data["candidate"]["recommended_action"] in {"wait_outbox", "manual_resume"}
    updated = ledger.read_outbox_event(event["event_id"])
    assert updated is not None
    assert updated["status"] == "retrying"


def test_safe_resume_execute_api_uses_agent_loop_resume_executor_when_available(tmp_path):
    ledger = TaskLedger(tmp_path, backend="json")
    agent_loop = SimpleNamespace(
        workspace=tmp_path,
        ledger=ledger,
        execute_safe_resume=AsyncMock(return_value={
            "task_id": "task_1",
            "recommended_action": "replay_failed_steps",
            "safe_to_execute": True,
            "scheduled": True,
        }),
    )
    app, ledger = _build_app(tmp_path, ledger=ledger, agent_loop=agent_loop)
    ledger.ensure_task(
        task_id="task_1",
        session_key="telegram:123",
        agent_id="default",
        mode="chat",
        channel="telegram",
        goal="resume me",
        status="failed",
        current_stage="error",
        resume_context={"channel": "telegram", "chat_id": "123", "session_key": "telegram:123"},
    )
    step = ledger.start_step("task_1", step_type="tool_call", name="read_file", replayable=True)
    ledger.finish_step(step, status="failed", error="boom")

    client = TestClient(app)
    resp = client.post("/api/tasks/task_1/resume/execute")

    assert resp.status_code == 200
    agent_loop.execute_safe_resume.assert_awaited_once_with("task_1", source="webui_safe_resume_execute")
    data = resp.json()
    assert data["candidate"]["recommended_action"] == "replay_failed_steps"
    assert data["candidate"]["scheduled"] is True


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
    assert data["tasks"][0]["queue"]["source"] == "watchdog_soft_recovery"
    assert data["tasks"][0]["queue"]["manual_review_required"] is False
    assert data["tasks"][0]["queue"]["queued_at_ms"] > 0
    assert "next_step" not in data["tasks"][0]["queue"]


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
    assert data["tasks"][0]["queue"]["manual_review_required"] is True
    assert data["tasks"][0]["queue"]["recommended_action"] in {"recheck", "wait_outbox", "manual_resume", "retry_outbox"}


def test_operator_queue_alias_returns_recovery_queue(tmp_path):
    app, ledger = _build_app(tmp_path)
    ledger.ensure_task(
        task_id="task_q",
        session_key="telegram:123",
        agent_id="default",
        mode="chat",
        channel="telegram",
        goal="queue me",
        status="waiting",
        current_stage="resume_requested",
        metadata={"recovery": {"source": "webui", "manual_review_required": True, "requested_at_ms": 123}},
    )

    client = TestClient(app)
    resp = client.get("/api/operator-queue", params={"manual_review_only": "true"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["tasks"][0]["task_id"] == "task_q"
    assert data["tasks"][0]["queue"]["source"] == "webui"


def test_task_export_api_redacts_sensitive_payload_and_supports_markdown(tmp_path):
    app, ledger = _build_app(tmp_path)
    ledger.ensure_task(
        task_id="task_export",
        session_key="telegram:123",
        agent_id="default",
        mode="chat",
        channel="telegram",
        goal="export me",
        current_stage="waiting_outbox",
    )
    step = ledger.start_step("task_export", step_type="tool_call", name="notify", input_summary='{"path":"x"}')
    ledger.finish_step(step, status="waiting_outbox", error="boom")
    ledger.enqueue_outbox(
        task_id="task_export",
        step_id=step.step_id,
        effect_type="webhook_json",
        target="https://example.com/hook",
        payload={"Authorization": "Bearer secret-token", "body": {"api_key": "abc", "ok": True}},
        metadata={"secret": "top-secret"},
        status="failed",
        error="boom",
    )

    client = TestClient(app)
    json_resp = client.get("/api/tasks/task_export/export", params={"format": "json"})
    assert json_resp.status_code == 200
    data = json_resp.json()
    assert data["outbox_events"][0]["payload"]["Authorization"] == "[redacted]"
    assert data["outbox_events"][0]["payload"]["body"]["api_key"] == "[redacted]"
    assert data["outbox_events"][0]["metadata"]["secret"] == "[redacted]"

    md_resp = client.get("/api/tasks/task_export/export", params={"format": "md"})
    assert md_resp.status_code == 200
    assert "## Recovery History" in md_resp.text
    assert "## Outbox Postmortem" in md_resp.text


def test_task_export_and_postmortem_include_trigger_bundle(tmp_path):
    trigger_runtime = TriggerRuntime(tmp_path)
    trigger = trigger_runtime.record_trigger(
        source="cron",
        kind="agent_turn",
        payload_summary="run export",
        session_key="telegram:123",
        channel="telegram",
        chat_id="123",
    )
    app, ledger = _build_app(
        tmp_path,
        agent_loop=SimpleNamespace(workspace=tmp_path, ledger=TaskLedger(tmp_path), trigger_runtime=trigger_runtime),
        ledger=TaskLedger(tmp_path),
    )
    ledger.ensure_task(
        task_id="task_bundle",
        session_key="telegram:123",
        agent_id="default",
        mode="chat",
        channel="telegram",
        goal="bundle me",
        metadata={"trigger": {"trigger_id": trigger["trigger_id"], "source": trigger["source"], "kind": trigger["kind"]}},
    )

    client = TestClient(app)
    export_json = client.get("/api/tasks/task_bundle/export", params={"format": "json"})
    assert export_json.status_code == 200
    assert export_json.json()["trigger"]["trigger_id"] == trigger["trigger_id"]

    export_md = client.get("/api/tasks/task_bundle/export", params={"format": "md"})
    assert export_md.status_code == 200
    assert "## Trigger" in export_md.text

    pm_json = client.get("/api/tasks/task_bundle/postmortem", params={"format": "json"})
    assert pm_json.status_code == 200
    assert pm_json.json()["trigger"]["kind"] == "agent_turn"

    pm_md = client.get("/api/tasks/task_bundle/postmortem", params={"format": "md"})
    assert pm_md.status_code == 200
    assert "## Trigger" in pm_md.text

    bundle_json = client.get("/api/tasks/task_bundle/bundle", params={"format": "json"})
    assert bundle_json.status_code == 200
    assert bundle_json.json()["trigger"]["trigger_id"] == trigger["trigger_id"]
    assert bundle_json.json()["postmortem"]["task"]["task_id"] == "task_bundle"

    bundle_md = client.get("/api/tasks/task_bundle/bundle", params={"format": "md"})
    assert bundle_md.status_code == 200
    assert "## Trigger" in bundle_md.text
    assert "## Postmortem" in bundle_md.text


def test_task_markdown_exports_include_retrieval_trace(tmp_path):
    app, ledger = _build_app(tmp_path)
    ledger.ensure_task(
        task_id="task_retrieval_export",
        session_key="telegram:123",
        agent_id="default",
        mode="chat",
        channel="telegram",
        goal="trace me",
        metadata={
            "retrieval": {
                "strategy": "hybrid",
                "latency_ms": 12,
                "fallback_count": 0,
                "card_count": 1,
                "rule_count": 1,
                "knowledge_count": 1,
                "hit_sources": ["hybrid", "knowledge"],
                "card_hits": [{"name": "tech-stack", "type": "tech", "source": "hybrid"}],
                "rule_hits": [{"trigger": "deploy", "source": "hybrid"}],
                "knowledge_hits": [{"title": "Deploy Notes", "source": "manual://deploy", "result_type": "fact", "page_label": "p.1"}],
                "structured": {
                    "session_summary": "deploy trace",
                    "fact_slots": [{"name": "tech-stack", "value": "Python 3.13"}],
                    "retrieval_objects": [{"kind": "knowledge_hit", "title": "Deploy Notes"}],
                },
            }
        },
    )

    client = TestClient(app)
    export_json = client.get("/api/tasks/task_retrieval_export/export", params={"format": "json"})
    assert export_json.status_code == 200
    assert export_json.json()["task"]["metadata"]["retrieval"]["structured"]["session_summary"] == "deploy trace"

    export_md = client.get("/api/tasks/task_retrieval_export/export", params={"format": "md"})
    assert export_md.status_code == 200
    # Markdown renderers use the same retrieval payload; this fixture keeps
    # the structured subtree in place so it will surface as soon as the
    # renderer starts emitting it.
    assert "## Retrieval" in export_md.text
    assert "Card: tech-stack" in export_md.text
    assert "Rule: deploy" in export_md.text
    assert "Knowledge: Deploy Notes [p.1]" in export_md.text

    bundle_json = client.get("/api/tasks/task_retrieval_export/bundle", params={"format": "json"})
    assert bundle_json.status_code == 200
    assert bundle_json.json()["summary"]["retrieval"]["structured"]["fact_slots"][0]["name"] == "tech-stack"

    bundle_md = client.get("/api/tasks/task_retrieval_export/bundle", params={"format": "md"})
    assert bundle_md.status_code == 200
    assert "## Retrieval" in bundle_md.text

    pm_json = client.get("/api/tasks/task_retrieval_export/postmortem", params={"format": "json"})
    assert pm_json.status_code == 200
    assert pm_json.json()["task"]["metadata"]["retrieval"]["structured"]["retrieval_objects"][0]["kind"] == "knowledge_hit"

    pm_md = client.get("/api/tasks/task_retrieval_export/postmortem", params={"format": "md"})
    assert pm_md.status_code == 200
    assert "## Retrieval" in pm_md.text


def test_task_exports_surface_repo_change_memory_objects(tmp_path):
    app, ledger = _build_app(tmp_path)
    ledger.ensure_task(
        task_id="task_repo_change",
        session_key="agentbridge:codex:default:demo",
        agent_id="default",
        mode="chat",
        channel="agentbridge",
        goal="repo aware task",
        metadata={
            "retrieval": {
                "strategy": "hybrid",
                "latency_ms": 5,
                "hit_sources": ["repo_change_memory"],
                "repo_change_memory_count": 1,
                "structured": {
                    "session_summary": "repo aware trace",
                    "repo_change_summary": "prefer service adapters",
                    "fact_slots": [
                        {
                            "name": "repo_change_focus",
                            "type": "repo_change_memory",
                            "summary": "prefer service adapters",
                            "keywords": ["service.adapters.run"],
                        }
                    ],
                    "retrieval_objects": [
                        {
                            "kind": "repo_change_memory",
                            "title": "Repo Change Memory (default)",
                            "summary": "prefer service adapters",
                            "preferred_internal_apis": ["service.adapters.run"],
                        }
                    ],
                },
            }
        },
    )

    client = TestClient(app)
    export_json = client.get("/api/tasks/task_repo_change/export", params={"format": "json"})
    assert export_json.status_code == 200
    assert export_json.json()["task"]["metadata"]["retrieval"]["structured"]["repo_change_summary"] == "prefer service adapters"
    assert export_json.json()["task"]["metadata"]["retrieval"]["structured"]["fact_slots"][0]["name"] == "repo_change_focus"
    retrieval_objects = export_json.json()["summary"]["retrieval"]["structured"]["retrieval_objects"]
    assert retrieval_objects[0]["kind"] == "repo_change_memory"

    postmortem_json = client.get("/api/tasks/task_repo_change/postmortem", params={"format": "json"})
    assert postmortem_json.status_code == 200
    assert postmortem_json.json()["summary"]["retrieval"]["repo_change_memory_count"] == 1


def test_task_exports_include_conductor_chain(tmp_path):
    app, ledger = _build_app(tmp_path)
    ledger.ensure_task(
        task_id="task_conductor_export",
        session_key="telegram:123",
        agent_id="conductor",
        mode="operator",
        channel="telegram",
        goal="ship the campaign package",
        metadata={
            "conductor": {
                "planner": {"complexity": "complex", "summary": "Ship campaign package"},
                "generator": {"subtask_count": 2, "completed_count": 1, "failed_count": 0, "running_count": 1},
                "evaluator": {"plan_status": "accepted", "accepted_count": 1, "warning_count": 1, "failed_count": 0},
                "artifacts": {
                    "count": 2,
                    "items": [
                        {"artifact_id": "t1:result", "kind": "subtask_result", "label": "Risk audit"},
                        {"artifact_id": "plan:merged_result", "kind": "merged_result", "label": "Campaign package"},
                    ],
                },
                "observability": {"phase": "monitoring", "progress": 0.5, "duration_ms": 42},
                "subtasks": [
                    {
                        "id": "t1",
                        "description": "Audit the current funnel",
                        "status": "completed",
                        "generator": {"mode": "direct", "agent_id": "swarm-marketing_campaign_room-strategist"},
                        "evaluation": {"status": "accepted"},
                        "artifacts": [{"artifact_id": "t1:result"}],
                    },
                    {
                        "id": "t2",
                        "description": "Draft the landing page copy package",
                        "status": "running",
                        "generator": {"mode": "direct", "agent_id": "swarm-marketing_campaign_room-copywriter"},
                        "evaluation": {"status": "warning"},
                        "artifacts": [],
                    },
                ],
            }
        },
    )

    client = TestClient(app)
    export_json = client.get("/api/tasks/task_conductor_export/export", params={"format": "json"})
    assert export_json.status_code == 200
    assert export_json.json()["summary"]["conductor"]["planner"]["summary"] == "Ship campaign package"
    assert export_json.json()["conductor"]["artifacts"]["count"] == 2

    bundle_md = client.get("/api/tasks/task_conductor_export/bundle", params={"format": "md"})
    assert bundle_md.status_code == 200
    assert "## Conductor Chain" in bundle_md.text
    assert "### Subtasks" in bundle_md.text

    pm_json = client.get("/api/tasks/task_conductor_export/postmortem", params={"format": "json"})
    assert pm_json.status_code == 200
    assert pm_json.json()["conductor"]["evaluator"]["plan_status"] == "accepted"

    pm_md = client.get("/api/tasks/task_conductor_export/postmortem", params={"format": "md"})
    assert pm_md.status_code == 200
    assert "## Conductor Chain" in pm_md.text


def test_task_postmortem_api_includes_outbox_lifecycle(tmp_path):
    app, ledger = _build_app(tmp_path)
    ledger.ensure_task(
        task_id="task_pm",
        session_key="telegram:123",
        agent_id="default",
        mode="chat",
        channel="telegram",
        goal="postmortem me",
        current_stage="waiting_outbox",
    )
    step = ledger.start_step("task_pm", step_type="tool_call", name="notify")
    ledger.finish_step(step, status="waiting_outbox", error="boom")
    ledger.enqueue_outbox(
        task_id="task_pm",
        step_id=step.step_id,
        effect_type="webhook_json",
        target="https://example.com/hook",
        payload={"content": "hello"},
    )
    event = ledger.materialize_outbox_events_for_task("task_pm")[-1]
    ledger.mark_outbox_failed(
        event["event_id"],
        error="boom",
        result={"delivery_outcome": "permanent_error", "status_code": 500},
    )

    client = TestClient(app)
    task_resp = client.get("/api/tasks/task_pm")
    assert task_resp.status_code == 200
    task_data = task_resp.json()
    assert task_data["summary"]["outbox_delivery_outcome_counts"]["permanent_error"] == 1
    assert task_data["task"]["outbox_lifecycle"]["delivery_outcome_counts"]["permanent_error"] == 1

    resp = client.get("/api/tasks/task_pm/postmortem")
    assert resp.status_code == 200
    data = resp.json()
    assert data["outbox"]["lifecycle"]["status_counts"]["failed"] == 1
    assert data["outbox"]["lifecycle"]["delivery_outcome_counts"]["permanent_error"] == 1
    assert data["outbox"]["events"][0]["effect"]["category"] == "webhook"
    assert data["outbox"]["events"][0]["lifecycle"]["delivery_outcome"]["kind"] == "permanent_error"
    assert data["outbox"]["events"][0]["lifecycle"]["delivery_history"][-1]["delivery_outcome"]["kind"] == "permanent_error"

    md_resp = client.get("/api/tasks/task_pm/postmortem", params={"format": "md"})
    assert md_resp.status_code == 200
    assert "## Outbox Lifecycle" in md_resp.text
    assert "## Outbox Events" in md_resp.text


def test_task_postmortem_api_surfaces_replaced_delivery_outcome(tmp_path):
    app, ledger = _build_app(tmp_path)
    ledger.ensure_task(
        task_id="task_pm_replaced",
        session_key="telegram:123",
        agent_id="default",
        mode="chat",
        channel="telegram",
        goal="replaced me",
        current_stage="waiting_outbox",
    )
    step = ledger.start_step("task_pm_replaced", step_type="tool_call", name="notify")
    ledger.finish_step(step, status="waiting_outbox", error="superseded")
    event = ledger.enqueue_outbox(
        task_id="task_pm_replaced",
        step_id=step.step_id,
        effect_type="outbound_message",
        target="telegram:123",
        payload={"content": "hello"},
        status="pending",
    )
    ledger.abandon_outbox_event(
        event["event_id"],
        source="test",
        reason="superseded by newer work",
    )

    client = TestClient(app)
    resp = client.get("/api/tasks/task_pm_replaced/postmortem")
    assert resp.status_code == 200
    data = resp.json()
    assert data["task"]["outbox_lifecycle"]["delivery_outcome_counts"]["replaced"] == 1
    assert data["outbox"]["lifecycle"]["delivery_outcome_counts"]["replaced"] == 1
    assert data["outbox"]["events"][0]["lifecycle"]["delivery_outcome"]["kind"] == "replaced"
    assert data["outbox"]["events"][0]["lifecycle"]["delivery_history"][-1]["delivery_outcome"]["kind"] == "replaced"


def test_outbox_abandon_api_marks_event_and_task_abandoned(tmp_path):
    app, ledger = _build_app(tmp_path)
    ledger.ensure_task(
        task_id="task_ab",
        session_key="telegram:123",
        agent_id="default",
        mode="chat",
        channel="telegram",
        goal="abandon me",
        status="waiting",
        current_stage="waiting_outbox",
    )
    step = ledger.start_step("task_ab", step_type="tool_call", name="notify")
    ledger.finish_step(step, status="waiting_outbox")
    event = ledger.enqueue_outbox(
        task_id="task_ab",
        step_id=step.step_id,
        effect_type="outbound_message",
        target="telegram:123",
        payload={"content": "hello"},
        status="retrying",
    )

    client = TestClient(app)
    resp = client.post(f"/api/outbox/{event['event_id']}/abandon", json={"reason": "operator stop"})
    assert resp.status_code == 200
    assert resp.json()["event"]["status"] == "abandoned"
    assert resp.json()["task"]["status"] == "abandoned"


def test_outbox_abandon_api_uses_to_thread(tmp_path, monkeypatch):
    app, ledger = _build_app(tmp_path)
    ledger.ensure_task(
        task_id="task_ab",
        session_key="telegram:123",
        agent_id="default",
        mode="chat",
        channel="telegram",
        goal="abandon me",
        status="waiting",
        current_stage="waiting_outbox",
    )
    step = ledger.start_step("task_ab", step_type="tool_call", name="notify")
    ledger.finish_step(step, status="waiting_outbox")
    event = ledger.enqueue_outbox(
        task_id="task_ab",
        step_id=step.step_id,
        effect_type="outbound_message",
        target="telegram:123",
        payload={"content": "hello"},
        status="retrying",
    )

    calls = []

    async def _fake_to_thread(func, *args, **kwargs):
        calls.append(getattr(func, "__name__", repr(func)))
        return func(*args, **kwargs)

    monkeypatch.setattr("lemonclaw.gateway.webui.routes.asyncio.to_thread", _fake_to_thread)

    client = TestClient(app)
    resp = client.post(f"/api/outbox/{event['event_id']}/abandon", json={"reason": "operator stop"})

    assert resp.status_code == 200
    assert "abandon_outbox_event" in calls


def test_watchdog_api_returns_runtime_snapshot(tmp_path):
    ledger = TaskLedger(tmp_path, backend="json")
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
