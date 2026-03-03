"""Agent registry for multi-agent lifecycle management."""

import json
import time
from pathlib import Path
from typing import Any

from loguru import logger

from lemonclaw.agent.types import AgentInfo, AgentStatus
from lemonclaw.bus.queue import MessageBus


class AgentRegistry:
    """Registry that tracks all agents in a LemonClaw instance.

    Agents are stored in memory and optionally persisted to
    ``workspace/agents.json`` so they survive restarts.
    """

    def __init__(self, bus: MessageBus, workspace: Path):
        self._bus = bus
        self._workspace = workspace
        self._agents: dict[str, AgentInfo] = {}
        self._persist_path = workspace / "agents.json"

    # ── CRUD ──────────────────────────────────────────────────────────────

    def create_agent(
        self,
        agent_id: str,
        role: str,
        model: str = "",
        skills: list[str] | None = None,
        system_prompt_override: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> AgentInfo:
        """Register a new agent and create its bus queue."""
        if agent_id in self._agents:
            raise ValueError(f"Agent '{agent_id}' already exists")

        info = AgentInfo(
            agent_id=agent_id,
            role=role,
            model=model,
            skills=skills or [],
            system_prompt_override=system_prompt_override,
            config=config or {},
            created_at_ms=int(time.time() * 1000),
        )
        self._agents[agent_id] = info
        self._bus.register_agent(agent_id)
        self._persist()
        logger.info("Registry: created agent '{}' (role={})", agent_id, role)
        return info

    def get_agent(self, agent_id: str) -> AgentInfo | None:
        return self._agents.get(agent_id)

    def list_agents(self, include_retired: bool = False) -> list[AgentInfo]:
        agents = list(self._agents.values())
        if not include_retired:
            agents = [a for a in agents if a.status != AgentStatus.RETIRED]
        return agents

    def retire_agent(self, agent_id: str) -> bool:
        """Mark an agent as retired and remove its bus queue."""
        info = self._agents.get(agent_id)
        if not info:
            return False
        info.status = AgentStatus.RETIRED
        self._bus.unregister_agent(agent_id)
        self._persist()
        logger.info("Registry: retired agent '{}'", agent_id)
        return True

    def update_status(self, agent_id: str, status: AgentStatus) -> None:
        info = self._agents.get(agent_id)
        if info and info.status != AgentStatus.RETIRED:
            info.status = status

    def record_task_result(self, agent_id: str, success: bool) -> None:
        info = self._agents.get(agent_id)
        if info:
            if success:
                info.tasks_completed += 1
            else:
                info.tasks_failed += 1
            self._persist()

    # ── Persistence ───────────────────────────────────────────────────────

    def _persist(self) -> None:
        try:
            data = []
            for a in self._agents.values():
                data.append({
                    "agent_id": a.agent_id,
                    "role": a.role,
                    "model": a.model,
                    "status": a.status.value,
                    "skills": a.skills,
                    "system_prompt_override": a.system_prompt_override,
                    "config": a.config,
                    "tasks_completed": a.tasks_completed,
                    "tasks_failed": a.tasks_failed,
                    "created_at_ms": a.created_at_ms,
                })
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._persist_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
            tmp.rename(self._persist_path)
        except Exception:
            logger.exception("Registry: failed to persist agents")

    def load(self) -> None:
        """Load agents from disk and re-register active ones on the bus."""
        if not self._persist_path.exists():
            return
        try:
            data = json.loads(self._persist_path.read_text())
            for item in data:
                info = AgentInfo(
                    agent_id=item["agent_id"],
                    role=item["role"],
                    model=item.get("model", ""),
                    status=AgentStatus(item.get("status", "idle")),
                    skills=item.get("skills", []),
                    system_prompt_override=item.get("system_prompt_override"),
                    config=item.get("config", {}),
                    tasks_completed=item.get("tasks_completed", 0),
                    tasks_failed=item.get("tasks_failed", 0),
                    created_at_ms=item.get("created_at_ms", 0),
                )
                self._agents[info.agent_id] = info
                if info.status != AgentStatus.RETIRED:
                    self._bus.register_agent(info.agent_id)
            logger.info("Registry: loaded {} agents from disk", len(self._agents))
        except Exception:
            logger.exception("Registry: failed to load agents")
