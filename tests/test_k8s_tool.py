from __future__ import annotations

import json

import pytest

from lemonclaw.agent.tools.k8s import K8sTool
from lemonclaw.governance.runtime import GovernanceRuntime


class DummyProcess:
    def __init__(self, *, stdout: str = "", stderr: str = "", returncode: int = 0):
        self._stdout = stdout.encode("utf-8")
        self._stderr = stderr.encode("utf-8")
        self.returncode = returncode
        self.killed = False

    async def communicate(self):
        return self._stdout, self._stderr

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> int:
        return self.returncode


@pytest.mark.asyncio
async def test_k8s_get_returns_structured_json(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    async def _fake_create_subprocess_exec(*args, **kwargs):
        calls.append((args, kwargs))
        payload = {"items": [{"metadata": {"name": "claw-a"}}, {"metadata": {"name": "claw-b"}}]}
        return DummyProcess(stdout=json.dumps(payload))

    monkeypatch.setattr("asyncio.create_subprocess_exec", _fake_create_subprocess_exec)

    tool = K8sTool(default_namespace="claw", allowed_namespaces=["claw"])
    result = await tool.execute(action="get", resource_type="deployment", limit=1)

    assert result["ok"] is True
    assert result["raw"]["item_count"] == 2
    assert result["raw"]["truncated_count"] == 1
    assert len(result["raw"]["body"]["items"]) == 1
    assert calls[0][0] == ("kubectl", "-n", "claw", "get", "deployment", "-o", "json")


@pytest.mark.asyncio
async def test_k8s_restart_builds_rollout_command(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    async def _fake_create_subprocess_exec(*args, **kwargs):
        calls.append((args, kwargs))
        return DummyProcess(stdout="deployment.apps/claw-a restarted\n")

    monkeypatch.setattr("asyncio.create_subprocess_exec", _fake_create_subprocess_exec)

    tool = K8sTool(default_namespace="claw")
    first = await tool.execute(action="restart", resource_type="deployment", name="claw-a", _task_id="task-1")
    assert first["ok"] is False
    assert first["raw"]["confirmation_required"] is True

    result = await tool.execute(
        action="restart",
        resource_type="deployment",
        name="claw-a",
        confirm_token=first["raw"]["confirm_token"],
        _task_id="task-1",
    )

    assert result["ok"] is True
    assert result["summary"] == "deployment.apps/claw-a restarted"
    assert calls[0][0] == ("kubectl", "-n", "claw", "rollout", "restart", "deployment/claw-a")


@pytest.mark.asyncio
async def test_k8s_describe_builds_describe_command(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    async def _fake_create_subprocess_exec(*args, **kwargs):
        calls.append((args, kwargs))
        return DummyProcess(stdout="Name: claw-a\nNamespace: claw\n")

    monkeypatch.setattr("asyncio.create_subprocess_exec", _fake_create_subprocess_exec)

    tool = K8sTool(default_namespace="claw")
    result = await tool.execute(action="describe", resource_type="deployment", name="claw-a")

    assert result["ok"] is True
    assert result["summary"] == "Name: claw-a"
    assert calls[0][0] == ("kubectl", "-n", "claw", "describe", "deployment", "claw-a")


@pytest.mark.asyncio
async def test_k8s_scale_builds_scale_command(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    async def _fake_create_subprocess_exec(*args, **kwargs):
        calls.append((args, kwargs))
        return DummyProcess(stdout="deployment.apps/claw-a scaled\n")

    monkeypatch.setattr("asyncio.create_subprocess_exec", _fake_create_subprocess_exec)

    tool = K8sTool(default_namespace="claw")
    first = await tool.execute(action="scale", resource_type="deployment", name="claw-a", replicas=2)
    assert first["ok"] is False
    assert first["raw"]["confirmation_required"] is True

    result = await tool.execute(
        action="scale",
        resource_type="deployment",
        name="claw-a",
        replicas=2,
        confirm_token=first["raw"]["confirm_token"],
    )

    assert result["ok"] is True
    assert result["summary"] == "deployment.apps/claw-a scaled"
    assert calls[0][0] == ("kubectl", "-n", "claw", "scale", "deployment/claw-a", "--replicas=2")


@pytest.mark.asyncio
async def test_k8s_blocks_namespace_outside_allowlist():
    tool = K8sTool(allowed_namespaces=["claw"])
    result = await tool.execute(action="get", resource_type="pod", namespace="kube-system")
    assert result["ok"] is False
    assert "not allowed" in result["summary"]


@pytest.mark.asyncio
async def test_k8s_rejects_invalid_confirmation_token():
    tool = K8sTool(default_namespace="claw")
    result = await tool.execute(
        action="restart",
        resource_type="deployment",
        name="claw-a",
        confirm_token="bad-token",
    )
    assert result["ok"] is False
    assert "Invalid or expired" in result["summary"]


def test_k8s_resolves_capability_by_action():
    tool = K8sTool()
    assert tool.resolve_capability({"action": "get"}) == "k8s.read"
    assert tool.resolve_capability({"action": "restart"}) == "k8s.rollout.restart"
    assert tool.resolve_capability({"action": "scale"}) == "k8s.scale"


def test_governance_marks_k8s_restart_as_destructive(tmp_path):
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
    decision = runtime.authorize(capability_id="k8s.rollout.restart", tool_name="k8s", token=token, mode="operator")
    assert decision.capability.risk_level.value == "destructive"


def test_governance_marks_k8s_scale_as_destructive(tmp_path):
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
    decision = runtime.authorize(capability_id="k8s.scale", tool_name="k8s", token=token, mode="operator")
    assert decision.capability.risk_level.value == "destructive"
