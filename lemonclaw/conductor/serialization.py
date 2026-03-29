"""Serialization helpers for conductor plans and subtasks."""

from __future__ import annotations

from typing import Any

from lemonclaw.conductor.types import (
    ArtifactRef,
    ObservabilitySnapshot,
    OrchestrationPlan,
    PipelineStage,
    SubTask,
    SubTaskStatus,
)


def _state_bucket(task: SubTask, completed_ids: set[str]) -> str:
    status = task.status.value
    if status == "pending" and any(dep not in completed_ids for dep in task.depends_on):
        return "blocked"
    if status == "pending":
        return "ready"
    return status


def _serialize_stage(stage: PipelineStage | dict[str, Any] | None) -> dict[str, Any]:
    if stage is None:
        return {}
    if hasattr(stage, "to_dict"):
        return stage.to_dict()
    return dict(stage or {})


def _serialize_observability(snapshot: ObservabilitySnapshot | dict[str, Any] | None) -> dict[str, Any]:
    if snapshot is None:
        return {}
    if hasattr(snapshot, "to_dict"):
        data = snapshot.to_dict()
    else:
        data = dict(snapshot or {})
    if data.get("completed_at_ms") is None and data.get("ended_at_ms") is not None:
        data["completed_at_ms"] = data.get("ended_at_ms")
    if data.get("attempt_count") is None and data.get("attempts") is not None:
        data["attempt_count"] = data.get("attempts")
    return data


def _serialize_artifact(artifact: ArtifactRef | dict[str, Any]) -> dict[str, Any]:
    if hasattr(artifact, "to_dict"):
        return artifact.to_dict()
    return dict(artifact or {})


def serialize_subtask(task: SubTask, *, completed_ids: set[str], subtask_map: dict[str, SubTask], role_map: dict[str, Any]) -> dict[str, Any]:
    role = role_map.get(task.role_hint or "")
    generator = _serialize_stage(task.generator)
    evaluation = _serialize_stage(task.evaluation)
    artifacts = [_serialize_artifact(artifact) for artifact in task.artifacts]
    observability = _serialize_observability(task.observability)
    return {
        "id": task.id,
        "description": task.description[:100],
        "role_hint": task.role_hint,
        "role_label": getattr(role, "label", None),
        "status": task.status.value,
        "state_bucket": _state_bucket(task, completed_ids),
        "assigned_agent": task.assigned_agent_id,
        "depends_on": list(task.depends_on),
        "dependency_descriptions": [
            subtask_map[dep_id].description[:100]
            for dep_id in task.depends_on
            if dep_id in subtask_map
        ],
        "result_preview": (task.result or "")[:160] or None,
        "planner": {
            "summary": task.description[:140],
            "role_hint": task.role_hint,
            "depends_on_count": len(task.depends_on),
        },
        "generator": {
            "status": generator.get("status"),
            "mode": generator.get("mode"),
            "agent_id": generator.get("agent_id") or generator.get("details", {}).get("agent_id"),
            "attempt": generator.get("attempt") or generator.get("details", {}).get("attempt"),
            "output_kind": generator.get("output_kind") or generator.get("details", {}).get("output_kind"),
            "summary": generator.get("summary"),
            "preview": generator.get("preview") or generator.get("details", {}).get("preview"),
        },
        "evaluation": {
            "status": evaluation.get("status"),
            "score": evaluation.get("score"),
            "confidence": evaluation.get("details", {}).get("confidence") or evaluation.get("confidence"),
            "summary": evaluation.get("summary") or evaluation.get("reason"),
            "reason": evaluation.get("reason") or evaluation.get("rationale"),
            "warnings": list(evaluation.get("details", {}).get("issues") or evaluation.get("issues") or []),
        },
        "artifacts": artifacts,
        "artifact_count": len(artifacts),
        "observability": {
            "trace_id": observability.get("trace_id"),
            "execution_mode": observability.get("execution_mode"),
            "attempt_count": observability.get("attempt_count"),
            "duration_ms": observability.get("duration_ms"),
            "agent_id": observability.get("agent_id"),
            "started_at_ms": observability.get("started_at_ms"),
            "completed_at_ms": observability.get("completed_at_ms"),
            "error": observability.get("error"),
        },
    }


def serialize_plan(plan: OrchestrationPlan, template: Any | None = None) -> dict[str, Any]:
    subtasks = list(plan.subtasks or [])
    completed_ids = {task.id for task in subtasks if task.status == SubTaskStatus.COMPLETED}
    subtask_map = {task.id: task for task in subtasks}
    role_map = {role.id: role for role in getattr(template, "roles", ())}

    serialized_subtasks = [
        serialize_subtask(task, completed_ids=completed_ids, subtask_map=subtask_map, role_map=role_map)
        for task in subtasks
    ]
    plan_evaluation = _serialize_stage(plan.evaluation)
    plan_merge = _serialize_stage(plan.merge)
    plan_observability = _serialize_observability(plan.observability)
    all_artifacts = [_serialize_artifact(artifact) for artifact in plan.artifacts]
    for task in serialized_subtasks:
        all_artifacts.extend(list(task.get("artifacts") or []))
    accepted_count = sum(1 for task in serialized_subtasks if str(task.get("evaluation", {}).get("status") or "") == "accepted")
    warning_count = sum(
        1
        for task in serialized_subtasks
        if str(task.get("evaluation", {}).get("status") or "") in {"warning", "review", "needs_review"}
    )
    failed_count = sum(1 for task in serialized_subtasks if str(task.get("evaluation", {}).get("status") or "") == "failed")
    progress = (
        sum(1 for task in subtasks if task.status.value in ("completed", "failed"))
        / max(len(subtasks), 1)
    )

    return {
        "request_id": plan.request_id,
        "phase": plan.phase.value,
        "message": plan.original_message[:200],
        "complexity": plan.intent.complexity.value,
        "swarm_template_id": plan.swarm_template_id,
        "swarm_template_label": plan.swarm_template_label,
        "swarm_goal": plan.swarm_goal,
        "planner": {
            "status": "completed",
            "mode": "orchestrator",
            "summary": plan.intent.summary,
            "complexity": plan.intent.complexity.value,
            "reasoning": plan.intent.reasoning,
            "required_skills": list(plan.intent.required_skills or []),
        },
        "generator": {
            "status": "running" if plan.phase.value == "monitoring" else "completed" if plan.is_complete else "pending",
            "subtask_count": len(subtasks),
            "completed_count": sum(1 for task in subtasks if task.status == SubTaskStatus.COMPLETED),
            "failed_count": sum(1 for task in subtasks if task.status == SubTaskStatus.FAILED),
            "running_count": sum(1 for task in subtasks if task.status == SubTaskStatus.RUNNING),
        },
        "merge": {
            "status": (
                plan_merge.get("status")
                if plan_merge.get("status") not in {None, "", "idle"}
                else ("completed" if plan.merged_result else "pending")
            ),
            "summary": plan_merge.get("summary") or ("Merged subtask outputs into the response." if plan.merged_result else "Waiting for merge."),
            "score": plan_merge.get("score"),
            "result_preview": (plan.merged_result or "")[:200] or None,
            "artifact_count": len(list(plan.artifacts or [])),
        },
        "evaluator": {
            "plan_status": plan_evaluation.get("status"),
            "summary": plan_evaluation.get("summary"),
            "score": plan_evaluation.get("score"),
            "accepted_count": accepted_count,
            "warning_count": warning_count,
            "failed_count": failed_count,
        },
        "artifacts": {
            "count": len(all_artifacts),
            "items": all_artifacts,
        },
        "observability": {
            **plan_observability,
            "phase": plan.phase.value,
            "progress": progress,
        },
        "team_roles": [
            {"id": role.id, "label": role.label}
            for role in getattr(template, "roles", ())
        ],
        "subtasks": serialized_subtasks,
        "progress": progress,
        "merged_result_preview": (plan.merged_result or "")[:200] or None,
    }
