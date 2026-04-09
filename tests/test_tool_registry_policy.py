from pathlib import Path

from lemonclaw.agent.tools.base import Tool
from lemonclaw.agent.tools.registry import ToolRegistry
from lemonclaw.governance import GovernanceRuntime


class DummyConfig:
    enabled = True
    default_autonomy_cap = "L1"
    token_ttl_seconds = 60
    kill_switch_file = ""
    audit_log_path = ""
    budgets = type("Budgets", (), {"default_task_usd": None})()
    capability_overrides = {
        "custom.deny": {
            "approval_policy": "deny",
        }
    }


class DummyTool(Tool):
    @property
    def name(self) -> str:
        return "dummy"

    @property
    def description(self) -> str:
        return "dummy tool"

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "value": {"type": "string"},
            },
            "required": ["value"],
        }

    def resolve_capability(self, params, context=None) -> str:
        return "custom.deny"

    async def execute(self, **kwargs):
        return f"ok:{kwargs['value']}"


class ScopedTokenTool(Tool):
    @property
    def name(self) -> str:
        return "scoped_token"

    @property
    def description(self) -> str:
        return "inspect minted capability tokens"

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "value": {"type": "string"},
            },
            "required": ["value"],
        }

    def resolve_capability(self, params, context=None) -> str:
        return "git.read"

    async def execute(self, value, _capability_token=None, **kwargs):
        del kwargs
        return f"{value}:{','.join(_capability_token.allowed_capabilities)}:{_capability_token.approval_state}"


class ConfirmTool(Tool):
    @property
    def name(self) -> str:
        return "confirm_tool"

    @property
    def description(self) -> str:
        return "confirm gated tool"

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "value": {"type": "string"},
            },
            "required": ["value"],
        }

    def resolve_capability(self, params, context=None) -> str:
        return "git.write.remote"

    async def execute(self, **kwargs):
        return f"unexpected:{kwargs['value']}"


def test_registry_blocks_when_capability_is_denied(tmp_path: Path):
    cfg = DummyConfig()
    cfg.kill_switch_file = str(tmp_path / "governance.json")
    cfg.audit_log_path = str(tmp_path / "audit.jsonl")
    governance = GovernanceRuntime(workspace=tmp_path, config=cfg, agent_id="default")
    registry = ToolRegistry(governance=governance)
    registry.register(DummyTool())

    token = governance.issue_token(task_id="task_1", allowed_capabilities=["custom.deny"])
    result = __import__("asyncio").run(
        registry.execute(
            "dummy",
            {"value": "x"},
            context={"_task_id": "task_1", "_mode": "chat", "_capability_token": token},
        )
    )

    assert "Governance denied tool 'dummy'" in result
    audit_path = Path(cfg.audit_log_path)
    assert audit_path.exists()
    assert "custom.deny" in audit_path.read_text(encoding="utf-8")
    assert "denied:" in audit_path.read_text(encoding="utf-8")


def test_registry_mints_scoped_token_for_tools(tmp_path: Path):
    cfg = DummyConfig()
    cfg.kill_switch_file = str(tmp_path / "governance.json")
    cfg.audit_log_path = str(tmp_path / "audit.jsonl")
    governance = GovernanceRuntime(workspace=tmp_path, config=cfg, agent_id="default")
    registry = ToolRegistry(governance=governance)
    registry.register(ScopedTokenTool())

    result = __import__("asyncio").run(
        registry.execute(
            "scoped_token",
            {"value": "probe"},
            context={"_task_id": "task_1", "_mode": "chat"},
        )
    )

    assert result == "probe:git.read:approved"


def test_registry_blocks_confirm_gated_tools_without_explicit_approval(tmp_path: Path):
    cfg = DummyConfig()
    cfg.kill_switch_file = str(tmp_path / "governance.json")
    cfg.audit_log_path = str(tmp_path / "audit.jsonl")
    governance = GovernanceRuntime(workspace=tmp_path, config=cfg, agent_id="default")
    registry = ToolRegistry(governance=governance)
    registry.register(ConfirmTool())

    result = __import__("asyncio").run(
        registry.execute(
            "confirm_tool",
            {"value": "x"},
            context={"_task_id": "task_1", "_mode": "chat"},
        )
    )

    assert "Governance denied tool 'confirm_tool': approval required" in result
