"""Agent types for multi-agent support."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AgentStatus(str, Enum):
    IDLE = "idle"
    THINKING = "thinking"
    TOOL_CALLING = "tool_calling"
    ERROR = "error"
    RETIRED = "retired"


@dataclass
class AgentInfo:
    """Metadata for a registered agent."""

    agent_id: str
    role: str  # "conductor", "player", "default"
    model: str = ""
    status: AgentStatus = AgentStatus.IDLE
    skills: list[str] = field(default_factory=list)
    system_prompt_override: str | None = None
    config: dict[str, Any] = field(default_factory=dict)
    # Stats
    tasks_completed: int = 0
    tasks_failed: int = 0
    created_at_ms: int = 0

    @property
    def success_rate(self) -> float:
        total = self.tasks_completed + self.tasks_failed
        return self.tasks_completed / total if total > 0 else 1.0
