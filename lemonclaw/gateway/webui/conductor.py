"""Conductor panel routes: agent list + orchestration status."""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

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
        return verify_session_cookie(cookie, auth_token)

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
        plans = orchestrator.active_plans
        return JSONResponse({
            "plans": [
                {
                    "request_id": p.request_id,
                    "phase": p.phase.value,
                    "message": p.original_message[:200],
                    "complexity": p.intent.complexity.value,
                    "subtasks": [
                        {
                            "id": t.id,
                            "description": t.description[:100],
                            "status": t.status.value,
                            "assigned_agent": t.assigned_agent_id,
                            "depends_on": t.depends_on,
                        }
                        for t in p.subtasks
                    ],
                    "progress": (
                        sum(1 for t in p.subtasks if t.status.value in ("completed", "failed"))
                        / max(len(p.subtasks), 1)
                    ),
                }
                for p in plans
            ]
        })

    return [
        Route("/api/conductor/agents", api_agents),
        Route("/api/conductor/plans", api_plans),
    ]
