from pathlib import Path

from lemonclaw.governance import GovernanceRuntime
from lemonclaw.governance.types import ApprovalPolicy, CapabilityDefinition, RiskLevel


class DummyConfig:
    enabled = True
    default_autonomy_cap = "L1"
    token_ttl_seconds = 60
    kill_switch_file = ""
    audit_log_path = ""
    budgets = type("Budgets", (), {"default_task_usd": 2.5})()
    capability_overrides = {
        "dangerous.exec": {
            "approval_policy": "deny",
            "risk_level": "destructive",
        }
    }


def test_issue_token_defaults(tmp_path: Path):
    cfg = DummyConfig()
    cfg.kill_switch_file = str(tmp_path / "governance.json")
    cfg.audit_log_path = str(tmp_path / "audit.jsonl")
    runtime = GovernanceRuntime(workspace=tmp_path, config=cfg, agent_id="default")

    token = runtime.issue_token(task_id="task_1", mode="chat")

    assert token.task_id == "task_1"
    assert token.mode == "chat"
    assert token.allows("tool.read_file.default")


def test_authorize_denies_by_override(tmp_path: Path):
    cfg = DummyConfig()
    cfg.kill_switch_file = str(tmp_path / "governance.json")
    cfg.audit_log_path = str(tmp_path / "audit.jsonl")
    runtime = GovernanceRuntime(workspace=tmp_path, config=cfg, agent_id="default")

    token = runtime.issue_token(task_id="task_1", mode="operator")
    decision = runtime.authorize(
        capability_id="dangerous.exec",
        tool_name="exec",
        token=token,
        mode="operator",
    )

    assert decision.allowed is False
    assert decision.capability.approval_policy == ApprovalPolicy.DENY
    assert decision.capability.risk_level == RiskLevel.DESTRUCTIVE
