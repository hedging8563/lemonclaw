from pathlib import Path

from lemonclaw.governance.kill_switch import load_kill_switch_state, save_kill_switch_state
from lemonclaw.governance import GovernanceRuntime


class DummyConfig:
    enabled = True
    default_autonomy_cap = "L1"
    token_ttl_seconds = 60
    kill_switch_file = ""
    audit_log_path = ""
    budgets = type("Budgets", (), {"default_task_usd": None})()
    capability_overrides = {}


def test_global_kill_switch_blocks_execution(tmp_path: Path):
    kill_path = tmp_path / "governance.json"
    audit_path = tmp_path / "audit.jsonl"
    state = load_kill_switch_state(kill_path)
    state["global"] = True
    state["epoch"] = 3
    save_kill_switch_state(kill_path, state)

    cfg = DummyConfig()
    cfg.kill_switch_file = str(kill_path)
    cfg.audit_log_path = str(audit_path)
    runtime = GovernanceRuntime(workspace=tmp_path, config=cfg, agent_id="default")
    token = runtime.issue_token(task_id="task_1")

    decision = runtime.authorize(
        capability_id="tool.read_file.default",
        tool_name="read_file",
        token=token,
    )

    assert decision.allowed is False
    assert "kill switch" in decision.reason
