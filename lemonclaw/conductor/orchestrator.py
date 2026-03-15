"""Orchestrator — 5-phase pipeline for multi-agent task coordination.

Phases: ANALYZING → SPLITTING → ASSIGNING → MONITORING → MERGING

Simple tasks bypass the pipeline entirely (fast path).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import TYPE_CHECKING

from json_repair import repair_json
from loguru import logger

from lemonclaw.utils.helpers import strip_fences

from lemonclaw.conductor.types import (
    IntentAnalysis,
    OrchestrationPlan,
    OrchestratorPhase,
    SubTask,
    SubTaskStatus,
    TaskComplexity,
)
from lemonclaw.ledger.completion_gate import finalize_task
from lemonclaw.ledger.runtime import TaskLedger, build_task_resume_context

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
        plan_timeout: int = 1800,  # 30 min overall plan timeout
        subtask_timeout: int = 300,  # 5 min per subtask
        max_retries: int = 1,  # retry failed subtasks once
        ledger: TaskLedger | None = None,
    ):
        self._provider = provider
        self._bus = bus
        self._registry = registry
        self._model = model
        self._llm_semaphore = asyncio.Semaphore(max_concurrent_llm)
        self._active_plans: dict[str, OrchestrationPlan] = {}
        self._plan_timeout = plan_timeout
        self._subtask_timeout = subtask_timeout
        self._max_retries = max_retries
        self._ledger = ledger

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

        task_id = str((msg.metadata or {}).get("_task_id") or f"task_orch_{uuid.uuid4().hex[:12]}")
        if self._ledger:
            self._ledger.ensure_task(
                task_id=task_id,
                session_key=msg.session_key,
                agent_id="conductor",
                mode="operator",
                channel=msg.channel,
                goal=msg.content[:500],
                current_stage=OrchestratorPhase.ANALYZING.value,
                resume_context=build_task_resume_context(
                    channel=msg.channel,
                    chat_id=str(msg.chat_id),
                    sender_id=str(msg.sender_id),
                    session_key=msg.session_key,
                    timezone=str((msg.metadata or {}).get("timezone") or ""),
                    message_id=str((msg.metadata or {}).get("message_id") or ""),
                    delivery_context=dict((msg.metadata or {}).get("_delivery_context") or {}),
                ),
                metadata={"source": "orchestrator"},
            )

        # Phase 2: SPLITTING
        plan = await self._split(msg.content, intent)
        plan.metadata["_ledger_task_id"] = task_id
        self._active_plans[plan.request_id] = plan

        try:
            if self._ledger:
                self._ledger.update_task(task_id, current_stage=OrchestratorPhase.SPLITTING.value)
            # Phase 3: ASSIGNING
            await self._assign(plan)
            if self._ledger:
                self._ledger.update_task(task_id, current_stage=OrchestratorPhase.ASSIGNING.value)

            # Phase 4: MONITORING
            await self._monitor(plan)
            if self._ledger:
                self._ledger.update_task(task_id, current_stage=OrchestratorPhase.MONITORING.value)

            # Check if all subtasks failed — degrade to single-agent direct processing
            all_failed = all(st.status == SubTaskStatus.FAILED for st in plan.subtasks)
            if all_failed:
                logger.warning("Orchestrator: all {} subtasks failed, degrading to single-agent",
                               len(plan.subtasks))
                if self._ledger:
                    self._ledger.update_task(task_id, status="failed", current_stage="degraded", error="all subtasks failed")
                return None  # Caller handles directly as single agent

            # Phase 5: MERGING
            if self._ledger:
                self._ledger.update_task(task_id, current_stage=OrchestratorPhase.MERGING.value)
            result = await self._merge(plan)
            if self._ledger:
                finalize_task(self._ledger, task_id)
            return result
        except Exception as e:
            if self._ledger:
                self._ledger.update_task(task_id, status="failed", current_stage="error", error=str(e)[:500])
            raise
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
            raw = strip_fences(response.content)
            try:
                tasks_data = json.loads(raw)
            except json.JSONDecodeError:
                tasks_data = json.loads(repair_json(raw))
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

        plan.phase = OrchestratorPhase.MONITORING
        logger.info("Orchestrator: MONITORING")

        pending_futures: dict[str, asyncio.Task[str | None]] = {}
        monitor_timeout = self._plan_timeout
        loop = asyncio.get_running_loop()
        deadline = loop.time() + monitor_timeout

        while not plan.is_complete:
            # Hard timeout guard
            remaining = deadline - loop.time()
            if remaining <= 0:
                logger.error("Orchestrator: MONITORING timeout ({}s), aborting", monitor_timeout)
                for tid, t in pending_futures.items():
                    t.cancel()
                for st in plan.subtasks:
                    if st.status in (SubTaskStatus.PENDING, SubTaskStatus.RUNNING):
                        st.status = SubTaskStatus.FAILED
                        st.result = st.result or "Monitoring timeout"
                break

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

            # Wait for at least one to finish (with timeout guard)
            done, _ = await asyncio.wait(
                pending_futures.values(),
                timeout=min(remaining, 300),
                return_when=asyncio.FIRST_COMPLETED,
            )

            # Remove finished futures
            finished_ids = [
                tid for tid, t in pending_futures.items() if t in done
            ]
            for tid in finished_ids:
                pending_futures.pop(tid)

        logger.info(
            "Orchestrator: MONITORING complete — {}/{} succeeded",
            sum(1 for t in plan.subtasks if t.status == SubTaskStatus.COMPLETED),
            len(plan.subtasks),
        )

    async def _execute_subtask(
        self, plan: OrchestrationPlan, subtask: SubTask,
    ) -> str | None:
        """Execute a single subtask with retry on failure.

        If the assigned agent has a registered bus queue, route through the
        bus with request-response.  Otherwise fall back to a direct LLM call.
        Retries up to self._max_retries times with exponential backoff.
        """
        import uuid as _uuid
        from lemonclaw.bus.events import InboundMessage
        from lemonclaw.agent.types import AgentStatus

        agent_id = subtask.assigned_agent_id or "default"
        last_error: Exception | None = None
        task_id = str(plan.metadata.get("_ledger_task_id", ""))

        for attempt in range(1 + self._max_retries):
            if attempt > 0:
                backoff = min(2 ** attempt, 30)
                logger.info("Orchestrator: retrying '{}' (attempt {}/{}) after {}s",
                            subtask.id, attempt + 1, 1 + self._max_retries, backoff)
                await asyncio.sleep(backoff)

            logger.info("Orchestrator: executing '{}' on agent '{}'", subtask.id, agent_id)
            self._registry.update_status(agent_id, AgentStatus.THINKING)

            try:
                step = self._ledger.start_step(task_id, step_type="subtask", name=subtask.id, input_summary=subtask.description[:500]) if self._ledger and task_id else None
                if agent_id != "default" and agent_id in self._bus.registered_agents:
                    request_id = f"orch-{plan.request_id}-{subtask.id}-{_uuid.uuid4().hex[:6]}"
                    fut = self._bus.expect_response(request_id)

                    msg = InboundMessage(
                        channel="internal",
                        sender_id="conductor",
                        chat_id=agent_id,
                        content=(
                            f"Context: {plan.original_message}\n\n"
                            f"Your specific task: {subtask.description}"
                        ),
                        target_agent_id=agent_id,
                        metadata={"_request_id": request_id},
                        session_key_override=f"internal:{agent_id}:{subtask.id}",
                    )
                    await self._bus.publish_inbound(msg)

                    try:
                        result = await asyncio.wait_for(fut, timeout=self._subtask_timeout)
                    except asyncio.TimeoutError:
                        self._bus.cancel_response(request_id)
                        raise TimeoutError(f"Agent '{agent_id}' did not respond within {self._subtask_timeout}s")
                else:
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
                    result = response.content

                subtask.result = result
                subtask.status = SubTaskStatus.COMPLETED
                self._registry.record_task_result(agent_id, success=True)
                self._registry.update_status(agent_id, AgentStatus.IDLE)
                if step:
                    self._ledger.finish_step(step, status="completed")
                return result

            except Exception as e:
                last_error = e
                logger.warning("Orchestrator: subtask '{}' attempt {} failed: {}",
                               subtask.id, attempt + 1, e)
                if self._ledger and task_id:
                    failed_step = self._ledger.start_step(task_id, step_type="subtask", name=subtask.id, input_summary=subtask.description[:500])
                    self._ledger.finish_step(failed_step, status="failed", error=str(e)[:500])

        # All retries exhausted
        logger.error("Orchestrator: subtask '{}' failed after {} attempts: {}",
                     subtask.id, 1 + self._max_retries, last_error)
        subtask.result = str(last_error)
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
