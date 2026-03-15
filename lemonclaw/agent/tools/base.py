"""Base class for agent tools."""

from abc import ABC, abstractmethod
from typing import Any


class Tool(ABC):
    """
    Abstract base class for agent tools.
    
    Tools are capabilities that the agent can use to interact with
    the environment, such as reading files, executing commands, etc.
    """
    
    _TYPE_MAP = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "array": list,
        "object": dict,
    }
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Tool name used in function calls."""
        pass
    
    @property
    @abstractmethod
    def description(self) -> str:
        """Description of what the tool does."""
        pass
    
    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for tool parameters."""
        pass
    
    @abstractmethod
    async def execute(self, **kwargs: Any) -> str:
        """
        Execute the tool with given parameters.
        
        Args:
            **kwargs: Tool-specific parameters.
        
        Returns:
            String result of the tool execution.
        """
        pass

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        """Validate tool parameters against JSON schema. Returns error list (empty if valid)."""
        schema = self.parameters or {}
        if schema.get("type", "object") != "object":
            raise ValueError(f"Schema must be object type, got {schema.get('type')!r}")
        return self._validate(params, {**schema, "type": "object"}, "")

    def _validate(self, val: Any, schema: dict[str, Any], path: str) -> list[str]:
        t, label = schema.get("type"), path or "parameter"
        if t in self._TYPE_MAP and not isinstance(val, self._TYPE_MAP[t]):
            return [f"{label} should be {t}"]
        
        errors = []
        if "enum" in schema and val not in schema["enum"]:
            errors.append(f"{label} must be one of {schema['enum']}")
        if t in ("integer", "number"):
            if "minimum" in schema and val < schema["minimum"]:
                errors.append(f"{label} must be >= {schema['minimum']}")
            if "maximum" in schema and val > schema["maximum"]:
                errors.append(f"{label} must be <= {schema['maximum']}")
        if t == "string":
            if "minLength" in schema and len(val) < schema["minLength"]:
                errors.append(f"{label} must be at least {schema['minLength']} chars")
            if "maxLength" in schema and len(val) > schema["maxLength"]:
                errors.append(f"{label} must be at most {schema['maxLength']} chars")
        if t == "object":
            props = schema.get("properties", {})
            for k in schema.get("required", []):
                if k not in val:
                    errors.append(f"missing required {path + '.' + k if path else k}")
            for k, v in val.items():
                if k in props:
                    errors.extend(self._validate(v, props[k], path + '.' + k if path else k))
        if t == "array" and "items" in schema:
            for i, item in enumerate(val):
                errors.extend(self._validate(item, schema["items"], f"{path}[{i}]" if path else f"[{i}]"))
        return errors
    
    def to_schema(self) -> dict[str, Any]:
        """Convert tool to OpenAI function schema format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            }
        }

    def resolve_capability(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> str:
        """Resolve this tool call to a capability id."""
        return f"tool.{self.name}.default"

    # Tools whose default capability is inherently non-replayable (side effects).
    _NON_REPLAYABLE_TOOLS = frozenset({"exec", "spawn", "cron", "message", "browser"})

    def is_replayable(self, capability_id: str) -> bool:
        """Whether a step using this capability can be safely replayed.

        External writes (http.write, notify.*, db.write, k8s.write, etc.) are
        not replayable because replaying them would duplicate the side effect.
        Tools with inherent side effects (exec, spawn, cron, message, browser)
        are also non-replayable regardless of capability id.
        Read-only operations and pure computations are safe to replay.
        """
        if ".write" in capability_id or capability_id.startswith("notify."):
            return False
        # Check if the tool name (second segment of tool.{name}.xxx) is inherently non-replayable
        parts = capability_id.split(".")
        if len(parts) >= 2 and parts[1] in self._NON_REPLAYABLE_TOOLS:
            return False
        return True

    def normalize_result(self, raw: Any) -> dict[str, Any]:
        """Normalize a tool result for governance/audit purposes."""
        if isinstance(raw, dict):
            return {
                "ok": bool(raw.get("ok", True)),
                "summary": str(raw.get("summary", raw)),
                "raw": raw.get("raw", raw),
                "artifacts": raw.get("artifacts", []),
                "step_status": raw.get("step_status"),
            }
        if isinstance(raw, str):
            return {
                "ok": not raw.startswith("Error"),
                "summary": raw,
                "raw": raw,
                "artifacts": [],
                "step_status": None,
            }
        return {
            "ok": True,
            "summary": str(raw),
            "raw": raw,
            "artifacts": [],
            "step_status": None,
        }
