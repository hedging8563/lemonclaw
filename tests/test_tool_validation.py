import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from lemonclaw.agent.tools.base import Tool
from lemonclaw.agent.tools.mcp import MCPToolWrapper, _MCPBinding
from lemonclaw.agent.tools.registry import ToolRegistry
from lemonclaw.ledger.runtime import TaskLedger


class SampleTool(Tool):
    @property
    def name(self) -> str:
        return "sample"

    @property
    def description(self) -> str:
        return "sample tool"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 2},
                "count": {"type": "integer", "minimum": 1, "maximum": 10},
                "mode": {"type": "string", "enum": ["fast", "full"]},
                "meta": {
                    "type": "object",
                    "properties": {
                        "tag": {"type": "string"},
                        "flags": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["tag"],
                },
            },
            "required": ["query", "count"],
        }

    async def execute(self, **kwargs: Any) -> str:
        return "ok"


class ExplodingTool(Tool):
    @property
    def name(self) -> str:
        return "explode"

    @property
    def description(self) -> str:
        return "raises during execution"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"query": {"type": "string"}},
        }

    async def execute(self, **kwargs: Any) -> str:
        raise RuntimeError("boom")


class CombinedSchemaTool(Tool):
    @property
    def name(self) -> str:
        return "combined"

    @property
    def description(self) -> str:
        return "combined schema tool"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "value": {
                    "allOf": [
                        {"type": "number"},
                        {"minimum": 3},
                    ],
                },
                "union": {
                    "type": ["string", "number"],
                },
            },
        }

    async def execute(self, **kwargs: Any) -> str:
        return "ok"


class ExplicitContextTool(Tool):
    def __init__(self) -> None:
        self.last_context: dict[str, Any] | None = None

    @property
    def name(self) -> str:
        return "explicit_context"

    @property
    def description(self) -> str:
        return "captures declared internal context"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        }

    async def execute(
        self,
        query: str,
        _task_id: str | None = None,
        _task_ledger: Any | None = None,
        **kwargs: Any,
    ) -> str:
        self.last_context = {
            "query": query,
            "_task_id": _task_id,
            "_task_ledger": _task_ledger,
            "extra": dict(kwargs),
        }
        return "ok"


def test_validate_params_missing_required() -> None:
    tool = SampleTool()
    errors = tool.validate_params({"query": "hi"})
    assert "missing required count" in "; ".join(errors)


def test_validate_params_type_and_range() -> None:
    tool = SampleTool()
    errors = tool.validate_params({"query": "hi", "count": 0})
    assert any("count must be >= 1" in e for e in errors)

    errors = tool.validate_params({"query": "hi", "count": "2"})
    assert any("count should be integer" in e for e in errors)


def test_validate_params_enum_and_min_length() -> None:
    tool = SampleTool()
    errors = tool.validate_params({"query": "h", "count": 2, "mode": "slow"})
    assert any("query must be at least 2 chars" in e for e in errors)
    assert any("mode must be one of" in e for e in errors)


def test_validate_params_nested_object_and_array() -> None:
    tool = SampleTool()
    errors = tool.validate_params(
        {
            "query": "hi",
            "count": 2,
            "meta": {"flags": [1, "ok"]},
        }
    )
    assert any("missing required meta.tag" in e for e in errors)
    assert any("meta.flags[0] should be string" in e for e in errors)


def test_validate_params_ignores_unknown_fields() -> None:
    tool = SampleTool()
    errors = tool.validate_params({"query": "hi", "count": 2, "extra": "x"})
    assert errors == []


def test_validate_params_allof_keeps_outer_rules() -> None:
    tool = CombinedSchemaTool()
    errors = tool.validate_params({"value": 1})
    assert any("value must be >= 3" in e for e in errors)


def test_validate_params_multi_type_accepts_matching_branch() -> None:
    tool = CombinedSchemaTool()
    assert tool.validate_params({"union": 3}) == []
    assert tool.validate_params({"union": "ok"}) == []


async def test_registry_returns_validation_error() -> None:
    reg = ToolRegistry()
    reg.register(SampleTool())
    result = await reg.execute("sample", {"query": "hi"})
    assert "Invalid parameters" in result


async def test_registry_marks_existing_step_failed_when_tool_raises(tmp_path: Path) -> None:
    ledger = TaskLedger(tmp_path)
    ledger.ensure_task(
        task_id="task_1",
        session_key="cli:direct",
        agent_id="default",
        mode="chat",
        channel="cli",
        goal="explode",
    )
    reg = ToolRegistry(ledger=ledger)
    reg.register(ExplodingTool())

    result = await reg.execute("explode", {"query": "hi"}, context={"_task_id": "task_1"})

    assert "Error executing explode: boom" in result
    steps = ledger.materialize_steps("task_1")
    assert len(steps) == 1
    assert steps[0]["status"] == "failed"
    assert steps[0]["error"] == "boom"


async def test_registry_appends_tool_trace_to_verification_metadata(tmp_path: Path) -> None:
    ledger = TaskLedger(tmp_path)
    ledger.ensure_task(
        task_id="task_1",
        session_key="cli:direct",
        agent_id="default",
        mode="chat",
        channel="cli",
        goal="trace tool",
    )
    reg = ToolRegistry(ledger=ledger)
    reg.register(SampleTool())

    result = await reg.execute("sample", {"query": "hello", "count": 1}, context={"_task_id": "task_1"})

    assert result == "ok"
    task = ledger.read_task("task_1")
    assert task is not None
    verification = dict(task.get("metadata") or {}).get("verification") or {}
    tool_trace = verification.get("tool_trace") or []
    assert len(tool_trace) == 1
    assert tool_trace[0]["tool_name"] == "sample"
    assert tool_trace[0]["status"] == "completed"
    assert tool_trace[0]["ok"] is True


async def test_registry_does_not_forward_internal_context_to_mcp_wrappers(tmp_path: Path) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    class FakeSession:
        async def call_tool(self, name: str, arguments: dict[str, Any]) -> SimpleNamespace:
            calls.append((name, arguments))
            return SimpleNamespace(content=["ok"])

    wrapper = MCPToolWrapper(
        _MCPBinding(session=FakeSession(), reconnect=None),
        "Notion_API",
        SimpleNamespace(
            name="post-search",
            description="search notion",
            inputSchema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        ),
    )
    reg = ToolRegistry()
    reg.register(wrapper)
    ledger = TaskLedger(tmp_path)

    result = await reg.execute(
        wrapper.name,
        {"query": "release notes"},
        context={
            "_task_id": "task_1",
            "_task_ledger": ledger,
            "_session_key": "session_1",
        },
    )

    assert result == "ok"
    assert calls == [("post-search", {"query": "release notes"})]


async def test_registry_keeps_declared_internal_context_for_context_aware_tools(tmp_path: Path) -> None:
    ledger = TaskLedger(tmp_path)
    tool = ExplicitContextTool()
    reg = ToolRegistry()
    reg.register(tool)

    result = await reg.execute(
        "explicit_context",
        {"query": "hello"},
        context={
            "_task_id": "task_1",
            "_task_ledger": ledger,
            "_session_key": "session_1",
        },
    )

    assert result == "ok"
    assert tool.last_context == {
        "query": "hello",
        "_task_id": "task_1",
        "_task_ledger": ledger,
        "extra": {},
    }


def test_private_tool_context_keys_must_be_explicit_execute_params() -> None:
    tools_dir = Path(__file__).resolve().parents[1] / "lemonclaw" / "agent" / "tools"
    violations: list[str] = []

    for path in sorted(tools_dir.glob("*.py")):
        module = ast.parse(path.read_text(encoding="utf-8"))
        for node in module.body:
            if not isinstance(node, ast.ClassDef):
                continue
            for item in node.body:
                if not isinstance(item, ast.AsyncFunctionDef) or item.name != "execute":
                    continue
                explicit_private_params = {
                    arg.arg
                    for arg in [*item.args.posonlyargs, *item.args.args, *item.args.kwonlyargs]
                    if arg.arg.startswith("_")
                }
                for child in ast.walk(item):
                    key: str | None = None
                    if (
                        isinstance(child, ast.Call)
                        and isinstance(child.func, ast.Attribute)
                        and isinstance(child.func.value, ast.Name)
                        and child.func.value.id == "kwargs"
                        and child.func.attr in {"get", "pop"}
                        and child.args
                        and isinstance(child.args[0], ast.Constant)
                        and isinstance(child.args[0].value, str)
                    ):
                        key = child.args[0].value
                    elif (
                        isinstance(child, ast.Subscript)
                        and isinstance(child.value, ast.Name)
                        and child.value.id == "kwargs"
                        and isinstance(child.slice, ast.Constant)
                        and isinstance(child.slice.value, str)
                    ):
                        key = child.slice.value
                    if key and key.startswith("_") and key not in explicit_private_params:
                        violations.append(
                            f"{path.name}:{node.name}.execute accesses private context key {key!r} via kwargs"
                        )

    assert violations == []
