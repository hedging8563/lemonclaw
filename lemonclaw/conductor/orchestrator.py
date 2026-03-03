"""Orchestrator — 5-phase pipeline for multi-agent task coordination.

Phases: ANALYZING → SPLITTING → ASSIGNING → MONITORING → MERGING

Simple tasks bypass the pipeline entirely (fast path).
"""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING

from loguru import logger

from lemonclaw.conductor.types import (
    IntentAnalysis,
    OrchestrationPlan,
    OrchestratorPhase,
    SubTask,
    SubTaskStatus,
    TaskComplexity,
)

if TYPE_CHECKING:
    from lemonclaw.agent.registry import AgentRegistry
    from lemonclaw.bus.events import InboundMessage
    from lemonclaw.bus.queue import MessageBus
    from lemonclaw.providers.base import LLMProvider


class Orchestrator:
    """Conductor orchestration engine.

    Receives a user message, analyzes complexity, and either handles it
    directly (simple) or splits into subtasks and delegates to players.
    """

    def __init__(
        self,
        provider: LLMProvider,
        bus: MessageBus,
        registry: AgentRegistry,
        model: str | None = None,
        max_concurrent_llm: int = 3,
    ):
        self._provider = provider
        self._bus = bus
        self._registry = registry
        self._model = model
        self._llm_semaphore = asyncio.Semaphore(max_concurrent_llm)
        self._active_plans: dict[str, OrchestrationPlan] = {}

    # ── Public API ────────────────────────────────────────────────────────

    async def handle_message(self, msg: InboundMessage) -> str | None:
        """Process a message through the orchestration pipeline.

        Returns:
            The final response string, or None if the message was
            handled as a simple pass-through (caller should process
            it normally).
        """
        # Phase 1: ANALYZING
        intent = await self._analyze(msg.content)

        if intent.complexity == TaskComplexity.SIMPLE:
            logger.debug("Orchestrator: SIMPLE — pass-through")
            return None  # Caller handles directly

        # Phase 2: SPLITTING
        plan = await self._split(msg.content, intent)
        self._active_plans[plan.request_id] = plan

        try:
            # Phase 3: ASSIGNING
            await self._assign(plan)

            # Phase 4: MONITORING
            await self._monitor(plan)

            # Phase 5: MERGING
            result = await self._merge(plan)
            return result
        finally:
            self._active_plans.pop(plan.request_id, None)

    @property
    def active_plans(self) -> list[OrchestrationPlan]:
        return list(self._active_plans.values())

    # ── Phase 1: ANALYZING ────────────────────────────────────────────────

    async def _analyze(self, message: str) -> IntentAnalysis:
        from lemonclaw.conductor.intent_analyzer import analyze_intent

        logger.info("Orchestrator: ANALYZING")
        async with self._llm_semaphore:
            return await analyze_intent(self._provider, message, self._model)

    # ── Phase 2: SPLITTING ────────────────────────────────────────────────

    async def _split(
        self, message: str, intent: IntentAnalysis,
    ) -> OrchestrationPlan:
        """Split a complex task into subtasks via LLM."""
        import json

        logger.info("Orchestrator: SPLITTING (complexity={})", intent.complexity.value)

        plan = OrchestrationPlan(
            request_id=uuid.uuid4().hex[:8],
            original_message=message,
            intent=intent,
            phase=OrchestratorPhase.SPLITTING,
        )

        prompt = (
            "Break this task into independent subtasks that can be worked on in parallel "
            "where possible. For each subtask provide:\n"
            '- id: short unique id (e.g. "t1", "t2")\n'
            "- description: what needs to be done\n"
            "- required_skills: list of skill categories\n"
            '- depends_on: list of subtask ids this depends on (empty if independent)\n\n'
            "Respond with ONLY a JSON array, no markdown fences:\n"
            '[{"id": "t1", "description": "...", "required_skills": ["..."], "depends_on": []}]'
        )

        try:
            async with self._llm_semaphore:
                response = await self._provider.chat(
                    messages=[
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": message},
                    ],
                    model=self._model,
                    temperature=0.1,
                    max_tokens=1024,
                )
            tasks_data = json.loads(response.content)
            for td in tasks_data:
                plan.subtasks.append(SubTask(
                    id=td["id"],
                    description=td["description"],
                    required_skills=td.get("required_skills", []),
                    depends_on=td.get("depends_on", []),
                ))
        except Exception as e:
            logger.error("Orchestrator: SPLITTING failed, single-task fallback: {}", e)
            plan.subtasks = [SubTask(
                id="t1",
                description=message,
                required_skills=intent.required_skills,
            )]

        logger.info("Orchestrator: split into {} subtasks", len(plan.subtasks))
        return plan

    # ── Phase 3: ASSIGNING ────────────────────────────────────────────────

    async def _assign(self, plan: OrchestrationPlan) -> None:
        """Assign subtasks to available players."""
        from lemonclaw.conductor.player_selector import select_agent

        plan.phase = OrchestratorPhase.ASSIGNING
        logger.info("Orchestrator: ASSIGNING {} subtasks", len(plan.subtasks))

        agents = self._registry.list_agents()

        for subtask in plan.subtasks:
            agent = select_agent(subtask, agents)
            if agent:
                subtask.assigned_agent_id = agent.agent_id
                logger.debug(
                    "Orchestrator: assigned '{}' → agent '{}'",
                    subtask.id, agent.agent_id,
                )
            else:
                # No suitable agent — assign to default
                subtask.assigned_agent_id = "default"
                logger.debug(
                    "Orchestrator: no match for '{}', assigned to default",
                    subtask.id,
                )

    # ── Phase 4: MONITORING ───────────────────────────────────────────────

    async def _monitor(self, plan: OrchestrationPlan) -> None:
        """Execute subtasks respecting dependency order, monitor completion."""
        from lemonclaw.conductor.task_splitter import get_runnable
        from lemonclaw.bus.events import InboundMessage

        plan.phase = OrchestratorPhase.MONITORING
        logger.info("Orchestrator: MONITORING")

        pending_futures: dict[str, asyncio.Task[str | None]] = {}

        while not plan.is_complete:
            # Launch runnable tasks
            for subtask in get_runnable(plan.subtasks):
                if subtask.id in pending_futures:
                    continue
                subtask.status = SubTaskStatus.RUNNING
                task = asyncio.create_task(
                    self._execute_subtask(plan, subtask)
                )
                pending_futures[subtask.id] = task

            if not pending_futures:
                # No tasks running and not complete — deadlock or all failed
                logger.warning("Orchestrator: no runnable tasks, breaking")
                break

            # Wait for at least one to finish
            done, _ = await asyncio.wait(
                pending_futures.values(),
                return_when=asyncio.FIRST_COMPLETED,
            )

            for future in done:
                # Find which subtask this was
                finished_id = None
                for tid, t in pending_futures.items():
                    if t is future:
                        finished_id = tid
                        break
                if finished_id:
                    pending_futures.pop(finished_id)

        logger.info(
            "Orchestrator: MONITORING complete — {}/{} succeeded",
            sum(1 for t in plan.subtasks if t.status == SubTaskStatus.COMPLETED),
            len(plan.subtasks),
        )

    async def _execute_subtask(
        self, plan: OrchestrationPlan, subtask: SubTask,
    ) -> str | None:
        """Execute a single subtask by sending it to the assigned agent."""
        from lemonclaw.bus.events import InboundMessage
        from lemonclaw.agent.types import AgentStatus

        agent_id = subtask.assigned_agent_id or "default"
        logger.info("Orchestrator: executing '{}' on agent '{}'", subtask.id, agent_id)

        self._registry.update_status(agent_id, AgentStatus.THINKING)

        try:
            # For now, use the provider directly (single-turn LLM call).
            # In the future, this will route through the agent's own loop.
            async with self._llm_semaphore:
                response = await self._provider.chat(
                    messages=[
                        {"role": "system", "content": (
                            "You are a specialist agent. Complete the assigned task "
                            "thoroughly and concisely. Focus only on this specific task."
                        )},
                        {"role": "user", "content": (
                            f"Context: {plan.original_message}\n\n"
                            f"Your specific task: {subtask.description}"
                        )},
                    ],
                    model=self._model,
                    temperature=0.3,
                    max_tokens=4096,
                )
            subtask.result = response.content
            subtask.status = SubTaskStatus.COMPLETED
            self._registry.record_task_result(agent_id, success=True)
            self._registry.update_status(agent_id, AgentStatus.IDLE)
            return response.content

        except Exception as e:
            logger.error("Orchestrator: subtask '{}' failed: {}", subtask.id, e)
            subtask.result = str(e)
            subtask.status = SubTaskStatus.FAILED
            self._registry.record_task_result(agent_id, success=False)
            self._registry.update_status(agent_id, AgentStatus.ERROR)
            return None

    # ── Phase 5: MERGING ──────────────────────────────────────────────────

    async def _merge(self, plan: OrchestrationPlan) -> str:
        from lemonclaw.conductor.result_merger import merge_results

        plan.phase = OrchestratorPhase.MERGING
        logger.info("Orchestrator: MERGING")

        async with self._llm_semaphore:
            result = await merge_results(self._provider, plan, self._model)

        plan.merged_result = result
        plan.phase = OrchestratorPhase.IDLE
        return result
