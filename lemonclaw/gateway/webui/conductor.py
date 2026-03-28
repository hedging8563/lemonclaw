"""Conductor panel routes: agent list + orchestration status."""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from lemonclaw.conductor.types import SubTaskStatus

if TYPE_CHECKING:
    from lemonclaw.agent.registry import AgentRegistry
    from lemonclaw.conductor.orchestrator import Orchestrator


def get_conductor_routes(
    *,
    orchestrator: Orchestrator | None = None,
    registry: AgentRegistry | None = None,
    auth_token: str | None = None,
) -> list[Route]:
    """Build Conductor panel REST routes."""

    from lemonclaw.gateway.webui.auth import COOKIE_NAME, verify_session_cookie

    def _check_auth(request: Request) -> bool:
        if not auth_token:
            return True
        cookie = request.cookies.get(COOKIE_NAME, "")
        valid, _ = verify_session_cookie(cookie, auth_token)
        return valid

    async def api_agents(request: Request) -> JSONResponse:
        if not _check_auth(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        if not registry:
            return JSONResponse({"agents": []})
        agents = registry.list_agents()
        return JSONResponse({
            "agents": [
                {
                    "id": a.agent_id,
                    "role": a.role,
                    "model": a.model,
                    "status": a.status.value if hasattr(a.status, "value") else str(a.status),
                    "skills": a.skills,
                    "task_count": a.task_count,
                    "success_rate": round(a.success_rate, 2) if hasattr(a, "success_rate") else 0,
                    "last_active_ms": a.last_active_ms,
                    "created_at_ms": a.created_at_ms,
                }
                for a in agents
            ]
        })

    async def api_plans(request: Request) -> JSONResponse:
        if not _check_auth(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        if not orchestrator:
            return JSONResponse({"plans": []})
        from lemonclaw.conductor.swarm_templates import get_swarm_template

        plans = orchestrator.active_plans
        return JSONResponse({
            "plans": [
                _serialize_plan(p, get_swarm_template(p.swarm_template_id))
                for p in plans
            ]
        })

    async def api_templates(request: Request) -> JSONResponse:
        if not _check_auth(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        from lemonclaw.conductor.swarm_templates import list_swarm_templates

        templates = list_swarm_templates()
        return JSONResponse({
            "templates": [
                {
                    "id": template.id,
                    "label": template.label,
                    "keywords": list(template.keywords),
                    "roles": [
                        {
                            "id": role.id,
                            "label": role.label,
                            "skills": list(role.skills),
                        }
                        for role in template.roles
                    ],
                }
                for template in templates
            ]
        })

    return [
        Route("/api/conductor/agents", api_agents),
        Route("/api/conductor/plans", api_plans),
        Route("/api/conductor/templates", api_templates),
    ]


def _serialize_plan(plan, template) -> dict:
    subtasks = list(plan.subtasks or [])
    completed_ids = {task.id for task in subtasks if task.status == SubTaskStatus.COMPLETED}
    subtask_map = {task.id: task for task in subtasks}
    role_map = {role.id: role for role in getattr(template, "roles", ())}

    def _state_bucket(task) -> str:
        status = task.status.value
        if status == "pending" and any(dep not in completed_ids for dep in task.depends_on):
            return "blocked"
        if status == "pending":
            return "ready"
        return status

    return {
        "request_id": plan.request_id,
        "phase": plan.phase.value,
        "message": plan.original_message[:200],
        "complexity": plan.intent.complexity.value,
        "swarm_template_id": plan.swarm_template_id,
        "swarm_template_label": plan.swarm_template_label,
        "swarm_goal": plan.swarm_goal,
        "team_roles": [
            {"id": role.id, "label": role.label}
            for role in getattr(template, "roles", ())
        ],
        "subtasks": [
            {
                "id": task.id,
                "description": task.description[:100],
                "role_hint": task.role_hint,
                "role_label": role_map.get(task.role_hint).label if task.role_hint in role_map else None,
                "status": task.status.value,
                "state_bucket": _state_bucket(task),
                "assigned_agent": task.assigned_agent_id,
                "depends_on": list(task.depends_on),
                "dependency_descriptions": [
                    subtask_map[dep_id].description[:100]
                    for dep_id in task.depends_on
                    if dep_id in subtask_map
                ],
                "result_preview": (task.result or "")[:160] or None,
            }
            for task in subtasks
        ],
        "progress": (
            sum(1 for task in subtasks if task.status.value in ("completed", "failed"))
            / max(len(subtasks), 1)
        ),
    }
