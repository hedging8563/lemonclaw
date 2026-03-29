"""Types for the Conductor orchestration pipeline."""

from __future__ import annotations

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
class PipelineStage:
    """Structured summary for one planner/generator/evaluator stage."""

    status: str = "idle"
    mode: str | None = None
    summary: str | None = None
    score: float | None = None
    rationale: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "mode": self.mode,
            "summary": self.summary,
            "score": self.score,
            "rationale": self.rationale,
            "details": dict(self.details or {}),
        }


@dataclass
class ArtifactRef:
    """Structured artifact emitted by planner/generator/merge stages."""

    artifact_id: str
    kind: str
    title: str
    preview: str | None = None
    uri: str | None = None
    mime_type: str | None = None
    source: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "kind": self.kind,
            "title": self.title,
            "preview": self.preview,
            "uri": self.uri,
            "mime_type": self.mime_type,
            "source": self.source,
            "metadata": dict(self.metadata or {}),
        }


@dataclass
class ObservabilitySnapshot:
    """Lightweight execution trace metadata for one plan/subtask."""

    trace_id: str | None = None
    execution_mode: str | None = None
    attempt_count: int = 0
    duration_ms: int | None = None
    started_at_ms: int | None = None
    completed_at_ms: int | None = None
    agent_id: str | None = None
    error_count: int = 0
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "execution_mode": self.execution_mode,
            "attempt_count": self.attempt_count,
            "duration_ms": self.duration_ms,
            "started_at_ms": self.started_at_ms,
            "completed_at_ms": self.completed_at_ms,
            "agent_id": self.agent_id,
            "error_count": self.error_count,
            "error": self.error,
            "details": dict(self.details or {}),
        }


# Backward-compatible aliases for helper modules that already use these names.
SubTaskGenerator = PipelineStage
SubTaskEvaluation = PipelineStage
SubTaskArtifact = ArtifactRef
SubTaskObservability = ObservabilitySnapshot


@dataclass
class SubTask:
    """A unit of work produced by task splitting."""

    id: str
    description: str
    required_skills: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    role_hint: str | None = None
    assigned_agent_id: str | None = None
    status: SubTaskStatus = SubTaskStatus.PENDING
    result: str | None = None
    generator: PipelineStage = field(default_factory=PipelineStage)
    evaluation: PipelineStage = field(default_factory=lambda: PipelineStage(status="not_run"))
    artifacts: list[ArtifactRef] = field(default_factory=list)
    observability: ObservabilitySnapshot = field(default_factory=ObservabilitySnapshot)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "required_skills": list(self.required_skills or []),
            "depends_on": list(self.depends_on or []),
            "role_hint": self.role_hint,
            "assigned_agent_id": self.assigned_agent_id,
            "status": self.status.value if hasattr(self.status, "value") else str(self.status),
            "result": self.result,
            "generator": self.generator.to_dict(),
            "evaluation": self.evaluation.to_dict(),
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "observability": self.observability.to_dict(),
        }


@dataclass
class IntentAnalysis:
    """Result of analyzing user intent."""

    complexity: TaskComplexity
    summary: str
    required_skills: list[str] = field(default_factory=list)
    reasoning: str = ""


@dataclass
class OrchestrationPlan:
    """A complete plan for executing a complex task."""

    request_id: str
    original_message: str
    intent: IntentAnalysis
    subtasks: list[SubTask] = field(default_factory=list)
    phase: OrchestratorPhase = OrchestratorPhase.IDLE
    merged_result: str | None = None
    swarm_template_id: str | None = None
    swarm_template_label: str | None = None
    swarm_goal: str | None = None
    planner: PipelineStage = field(default_factory=PipelineStage)
    merge: PipelineStage = field(default_factory=PipelineStage)
    evaluation: PipelineStage = field(default_factory=lambda: PipelineStage(status="not_run"))
    artifacts: list[ArtifactRef] = field(default_factory=list)
    observability: ObservabilitySnapshot = field(default_factory=ObservabilitySnapshot)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "original_message": self.original_message,
            "intent": {
                "complexity": self.intent.complexity.value if hasattr(self.intent.complexity, "value") else str(self.intent.complexity),
                "summary": self.intent.summary,
                "required_skills": list(self.intent.required_skills or []),
                "reasoning": self.intent.reasoning,
            },
            "phase": self.phase.value if hasattr(self.phase, "value") else str(self.phase),
            "merged_result": self.merged_result,
            "swarm_template_id": self.swarm_template_id,
            "swarm_template_label": self.swarm_template_label,
            "swarm_goal": self.swarm_goal,
            "planner": self.planner.to_dict(),
            "merge": self.merge.to_dict(),
            "evaluation": self.evaluation.to_dict(),
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "observability": self.observability.to_dict(),
            "metadata": dict(self.metadata or {}),
            "subtasks": [task.to_dict() for task in self.subtasks],
        }

    @property
    def is_complete(self) -> bool:
        return all(
            task.status in (SubTaskStatus.COMPLETED, SubTaskStatus.FAILED)
            for task in self.subtasks
        )

    @property
    def failed_tasks(self) -> list[SubTask]:
        return [task for task in self.subtasks if task.status == SubTaskStatus.FAILED]

    @property
    def runnable_tasks(self) -> list[SubTask]:
        """Tasks whose dependencies are all completed."""
        completed_ids = {task.id for task in self.subtasks if task.status == SubTaskStatus.COMPLETED}
        return [
            task
            for task in self.subtasks
            if task.status == SubTaskStatus.PENDING
            and all(dep in completed_ids for dep in task.depends_on)
        ]
