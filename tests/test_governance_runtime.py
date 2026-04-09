from pathlib import Path

from lemonclaw.agent.tools.shell import ExecTool
from lemonclaw.governance import GovernanceRuntime
from lemonclaw.governance.types import ApprovalPolicy, CapabilityDefinition, RiskLevel


class DummyConfig:
    enabled = True
    default_autonomy_cap = "L1"
    token_ttl_seconds = 60
    kill_switch_file = ""
    audit_log_path = ""
    budgets = type("Budgets", (), {"default_task_usd": 2.5})()
    secret_profiles = {
        "ops-http": type("SecretProfile", (), {"kind": "headers", "values": {"Authorization": "Bearer secret"}, "description": "ops"})(),
    }
    sandbox_profiles = {
        "runtime-default": type("SandboxProfile", (), {
            "allowed_domains": ["api.example.com"],
            "allowed_paths": ["/tmp"],
            "blocked_commands": ["rm -rf"],
            "max_timeout_seconds": 30,
            "allow_headed_browser": False,
            "require_content_boundaries": True,
        })(),
    }
    identity_defaults = type("IdentityDefaults", (), {"interactive": "service_account", "automation": "instance_identity"})()
    capability_overrides = {
        "dangerous.exec": {
            "approval_policy": "deny",
            "risk_level": "destructive",
        },
        "http.write": {
            "secret_profile": "ops-http",
            "sandbox_profile": "runtime-default",
        },
    }


def test_issue_token_defaults(tmp_path: Path):
    cfg = DummyConfig()
    cfg.kill_switch_file = str(tmp_path / "governance.json")
    cfg.audit_log_path = str(tmp_path / "audit.jsonl")
    runtime = GovernanceRuntime(workspace=tmp_path, config=cfg, agent_id="default")

    token = runtime.issue_token(task_id="task_1", mode="chat")

    assert token.task_id == "task_1"
    assert token.mode == "chat"
    assert token.allowed_capabilities == []
    assert token.approval_state == "pending"


def test_issue_token_scoped_auto_capability_defaults_to_approved(tmp_path: Path):
    cfg = DummyConfig()
    cfg.kill_switch_file = str(tmp_path / "governance.json")
    cfg.audit_log_path = str(tmp_path / "audit.jsonl")
    runtime = GovernanceRuntime(workspace=tmp_path, config=cfg, agent_id="default")

    token = runtime.issue_token(task_id="task_1", mode="chat", allowed_capabilities=["git.read"])

    assert token.allowed_capabilities == ["git.read"]
    assert token.approval_state == "approved"


def test_authorize_denies_by_override(tmp_path: Path):
    cfg = DummyConfig()
    cfg.kill_switch_file = str(tmp_path / "governance.json")
    cfg.audit_log_path = str(tmp_path / "audit.jsonl")
    runtime = GovernanceRuntime(workspace=tmp_path, config=cfg, agent_id="default")

    token = runtime.issue_token(task_id="task_1", mode="operator", allowed_capabilities=["dangerous.exec"])
    decision = runtime.authorize(
        capability_id="dangerous.exec",
        tool_name="exec",
        token=token,
        mode="operator",
    )

    assert decision.allowed is False
    assert decision.capability.approval_policy == ApprovalPolicy.DENY
    assert decision.capability.risk_level == RiskLevel.DESTRUCTIVE


def test_authorize_requires_explicit_approval_for_confirm_gated_capabilities(tmp_path: Path):
    cfg = DummyConfig()
    cfg.kill_switch_file = str(tmp_path / "governance.json")
    cfg.audit_log_path = str(tmp_path / "audit.jsonl")
    runtime = GovernanceRuntime(workspace=tmp_path, config=cfg, agent_id="default")

    pending_token = runtime.issue_token(
        task_id="task_1",
        mode="operator",
        allowed_capabilities=["exec.system"],
    )
    denied = runtime.authorize(
        capability_id="exec.system",
        tool_name="exec",
        token=pending_token,
        mode="operator",
    )
    assert denied.allowed is False
    assert denied.reason == "approval required"

    approved_token = runtime.issue_token(
        task_id="task_1",
        mode="operator",
        allowed_capabilities=["exec.system"],
        approval_state="approved",
    )
    approved = runtime.authorize(
        capability_id="exec.system",
        tool_name="exec",
        token=approved_token,
        mode="operator",
    )
    assert approved.allowed is True


def test_governance_overview_surfaces_profiles_and_unbound_counts(tmp_path: Path):
    cfg = DummyConfig()
    cfg.kill_switch_file = str(tmp_path / "governance.json")
    cfg.audit_log_path = str(tmp_path / "audit.jsonl")
    runtime = GovernanceRuntime(workspace=tmp_path, config=cfg, agent_id="default")

    overview = runtime.get_governance_overview()
    capabilities = runtime.list_capabilities_view()

    assert overview["secret_profiles"]["count"] == 1
    assert overview["sandbox_profiles"]["count"] == 1
    assert overview["capabilities"]["total"] >= 1
    http_write = next(item for item in capabilities if item["capability_id"] == "http.write")
    assert http_write["secret_profile_status"]["state"] == "configured"
    assert http_write["sandbox_profile_status"]["state"] == "configured"
    exec_system = next(item for item in capabilities if item["capability_id"] == "exec.system")
    assert "unbound_sandbox_profile" in exec_system["warnings"]


def test_record_audit_includes_governance_fields(tmp_path: Path):
    cfg = DummyConfig()
    cfg.kill_switch_file = str(tmp_path / "governance.json")
    cfg.audit_log_path = str(tmp_path / "audit.jsonl")
    runtime = GovernanceRuntime(workspace=tmp_path, config=cfg, agent_id="default")
    token = runtime.issue_token(task_id="task_1", mode="operator", allowed_capabilities=["http.write"])
    decision = runtime.authorize(
        capability_id="http.write",
        tool_name="http_request",
        token=token,
        mode="operator",
    )

    runtime.record_audit(
        capability=decision.capability,
        token=token,
        task_id="task_1",
        mode="operator",
        actor_identity="instance:test3",
        started_at=1.0,
        ended_at=2.0,
        params={"url": "https://api.example.com", "headers": {"Authorization": "Bearer secret"}},
        result_status="ok",
        warnings=decision.warnings,
    )

    records = runtime.list_audit_view(limit=10)
    assert records[0]["secret_profile"] == "ops-http"
    assert records[0]["sandbox_profile"] == "runtime-default"
    assert records[0]["approval_policy"] == "auto"
    assert records[0]["warnings"] == []
    assert records[0]["actor_identity"] == "instance:test3"


def test_validate_tool_call_enforces_bound_exec_sandbox(tmp_path: Path):
    cfg = DummyConfig()
    cfg.capability_overrides = {
        "exec.system": {
            "sandbox_profile": "runtime-default",
        }
    }
    cfg.kill_switch_file = str(tmp_path / "governance.json")
    cfg.audit_log_path = str(tmp_path / "audit.jsonl")
    runtime = GovernanceRuntime(workspace=tmp_path, config=cfg, agent_id="default")
    tool = ExecTool(timeout=120)
    token = runtime.issue_token(
        task_id="task_1",
        mode="operator",
        allowed_capabilities=["exec.system"],
        approval_state="approved",
    )
    decision = runtime.authorize(
        capability_id="exec.system",
        tool_name="exec",
        token=token,
        mode="operator",
    )

    allowed, reason = runtime.validate_tool_call(
        capability=decision.capability,
        params={"command": "rm -rf /tmp/demo"},
        tool=tool,
    )

    assert allowed is False
    assert "sandbox profile" in reason


def test_redaction_uses_latest_secret_profiles_and_masks_substrings(tmp_path: Path):
    cfg = DummyConfig()
    cfg.kill_switch_file = str(tmp_path / "governance.json")
    cfg.audit_log_path = str(tmp_path / "audit.jsonl")
    runtime = GovernanceRuntime(workspace=tmp_path, config=cfg, agent_id="default")

    runtime.secret_profiles["ops-http"] = type(
        "SecretProfile",
        (),
        {"kind": "headers", "values": {"Authorization": "Bearer rotated-secret"}, "description": "rotated"},
    )()

    payload = runtime.redact_payload({
        "note": "prefix Bearer rotated-secret suffix",
        "secret_profile": "ops-http",
    })

    assert payload["note"] == "prefix [redacted] suffix"
    assert payload["secret_profile"] == "ops-http"
