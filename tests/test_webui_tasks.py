from __future__ import annotations

from types import SimpleNamespace

from starlette.testclient import TestClient

from lemonclaw.config.loader import save_config
from lemonclaw.config.schema import Config
from lemonclaw.gateway.server import create_app
from lemonclaw.gateway.webui.auth import create_session_cookie
from lemonclaw.ledger.runtime import TaskLedger
from lemonclaw.session.manager import SessionManager


def _build_app(tmp_path, *, auth_token=None):
    config_path = tmp_path / "config.json"
    save_config(Config(), config_path)
    ledger = TaskLedger(tmp_path)
    agent_loop = SimpleNamespace(workspace=tmp_path, ledger=ledger)
    session_manager = SessionManager(tmp_path)
    app = create_app(
        config_path=config_path,
        auth_token=auth_token,
        agent_loop=agent_loop,
        session_manager=session_manager,
        webui_enabled=True,
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
