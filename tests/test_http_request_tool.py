from __future__ import annotations

import json

import pytest

from lemonclaw.agent.tools.http_request import HTTPRequestTool
from lemonclaw.config.schema import HTTPRequestToolConfig
from lemonclaw.governance.runtime import GovernanceRuntime


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
