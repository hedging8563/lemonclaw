from __future__ import annotations

import json

import pytest

from lemonclaw.agent.tools.http_request import HTTPRequestTool
from lemonclaw.agent.tools.registry import ToolRegistry
from lemonclaw.config.schema import HTTPRequestToolConfig
from lemonclaw.governance.runtime import GovernanceRuntime
from lemonclaw.ledger.runtime import TaskLedger


class DummyResponse:
    def __init__(self, status_code=200, headers=None, text="ok", payload=None):
        self.status_code = status_code
        self.headers = headers or {"content-type": "application/json"}
        self.text = text
        self._payload = payload if payload is not None else {"ok": True}

    def json(self):
        return self._payload


class DummyClient:
    def __init__(self, response: DummyResponse):
        self._response = response
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def request(self, method, url, headers=None, params=None, json=None):
        self.calls.append((method, url, headers or {}, params or {}, json or {}))
        return self._response


@pytest.mark.asyncio
async def test_http_request_blocks_domain_outside_allowlist():
    tool = HTTPRequestTool(allow_domains=["api.example.com"])
    result = await tool.execute("GET", "https://example.com/data")
    assert result["ok"] is False
    assert "allow_domains" in result["summary"]


def test_http_request_resolves_capability_by_method():
    tool = HTTPRequestTool()
    assert tool.resolve_capability({"method": "GET", "url": "https://example.com"}) == "http.read"
    assert tool.resolve_capability({"method": "POST", "url": "https://example.com"}) == "http.write"


@pytest.mark.asyncio
async def test_http_request_applies_auth_profile(monkeypatch: pytest.MonkeyPatch):
    response = DummyResponse(payload={"hello": "world"})
    client = DummyClient(response)
    monkeypatch.setattr("lemonclaw.agent.tools.http_request._validate_url", lambda url: (True, "", "1.2.3.4"))
    monkeypatch.setattr("httpx.AsyncClient", lambda **kwargs: client)

    tool = HTTPRequestTool(
        allow_domains=["example.com"],
        auth_profiles={"svc": {"Authorization": "Bearer token"}},
    )
    result = await tool.execute("GET", "https://example.com/data", auth_profile="svc")

    assert result["ok"] is True
    method, _url, headers, _params, _json = client.calls[0]
    assert method == "GET"
    assert headers["Authorization"] == "Bearer token"


@pytest.mark.asyncio
async def test_http_request_write_enqueues_outbox_when_enabled(tmp_path, monkeypatch: pytest.MonkeyPatch):
    ledger = TaskLedger(tmp_path)
    ledger.ensure_task(
        task_id="task_1",
        session_key="cli:direct",
        agent_id="default",
        mode="chat",
        channel="cli",
        goal="demo",
    )
    monkeypatch.setattr("lemonclaw.agent.tools.http_request._validate_url", lambda url: (True, "", "1.2.3.4"))

    tool = HTTPRequestTool(allow_domains=["example.com"])
    result = await tool.execute(
        "POST",
        "https://example.com/data",
        body={"hello": "world"},
        _task_id="task_1",
        _task_ledger=ledger,
        _step_id="step_http_1",
        _outbox_enabled=True,
    )

    assert result["ok"] is True
    assert result["raw"]["queued"] is True
    assert result["step_status"] == "waiting_outbox"
    events = ledger.list_outbox_events()
    assert len(events) == 1
    assert events[0]["effect_type"] == "http_json"
    assert events[0]["payload"]["method"] == "POST"


@pytest.mark.asyncio
async def test_tool_registry_passes_step_id_to_http_request_outbox(tmp_path, monkeypatch: pytest.MonkeyPatch):
    ledger = TaskLedger(tmp_path)
    ledger.ensure_task(
        task_id="task_1",
        session_key="cli:direct",
        agent_id="default",
        mode="chat",
        channel="cli",
        goal="demo",
    )
    monkeypatch.setattr("lemonclaw.agent.tools.http_request._validate_url", lambda url: (True, "", "1.2.3.4"))
    registry = ToolRegistry(ledger=ledger)
    registry.register(HTTPRequestTool(allow_domains=["example.com"]))

    result = await registry.execute(
        "http_request",
        {"method": "POST", "url": "https://example.com/data", "body": {"hello": "world"}},
        context={"_task_id": "task_1", "_task_ledger": ledger, "_outbox_enabled": True},
    )

    assert '"queued": true' in result.lower()
    steps = ledger.materialize_steps("task_1")
    assert len(steps) == 1
    assert steps[0]["status"] == "waiting_outbox"


def test_governance_marks_http_write_as_external_write(tmp_path):
    cfg = type("Cfg", (), {
        "enabled": True,
        "default_autonomy_cap": "L1",
        "token_ttl_seconds": 60,
        "kill_switch_file": str(tmp_path / "governance.json"),
        "audit_log_path": str(tmp_path / "audit.jsonl"),
        "budgets": type("Budgets", (), {"default_task_usd": None})(),
        "capability_overrides": {},
    })()
    runtime = GovernanceRuntime(workspace=tmp_path, config=cfg, agent_id="default")
    token = runtime.issue_token(task_id="task_1")
    decision = runtime.authorize(capability_id="http.write", tool_name="http_request", token=token, mode="operator")
    assert decision.capability.risk_level.value == "external_write"
