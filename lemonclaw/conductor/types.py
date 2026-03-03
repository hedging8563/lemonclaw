"""Types for the Conductor orchestration pipeline."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class OrchestratorPhase(str, Enum):
    IDLE = "idle"
    ANALYZING = "analyzing"
    SPLITTING = "splitting"
    ASSIGNING = "assigning"
    MONITORING = "monitoring"
    MERGING = "merging"


class TaskComplexity(str, Enum):
    SIMPLE = "simple"      # Conductor handles directly
    MODERATE = "moderate"  # 1-2 players
    COMPLEX = "complex"    # 3+ players, dependencies


class SubTaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class SubTask:
    """A unit of work produced by task splitting."""

    id: str
    description: str
    required_skills: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)  # IDs of prerequisite subtasks
    assigned_agent_id: str | None = None
    status: SubTaskStatus = SubTaskStatus.PENDING
    result: str | None = None


@dataclass
class IntentAnalysis:
    """Result of analyzing user intent."""

    complexity: TaskComplexity
    summary: str  # One-line summary of what the user wants
    required_skills: list[str] = field(default_factory=list)
    reasoning: str = ""  # Why this complexity level


@dataclass
class OrchestrationPlan:
    """A complete plan for executing a complex task."""

    request_id: str
    original_message: str
    intent: IntentAnalysis
    subtasks: list[SubTask] = field(default_factory=list)
    phase: OrchestratorPhase = OrchestratorPhase.IDLE
    merged_result: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_complete(self) -> bool:
        return all(t.status in (SubTaskStatus.COMPLETED, SubTaskStatus.FAILED)
                   for t in self.subtasks)

    @property
    def failed_tasks(self) -> list[SubTask]:
        return [t for t in self.subtasks if t.status == SubTaskStatus.FAILED]

    @property
    def runnable_tasks(self) -> list[SubTask]:
        """Tasks whose dependencies are all completed."""
        completed_ids = {t.id for t in self.subtasks if t.status == SubTaskStatus.COMPLETED}
        return [
            t for t in self.subtasks
            if t.status == SubTaskStatus.PENDING
            and all(dep in completed_ids for dep in t.depends_on)
        ]
