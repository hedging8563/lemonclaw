"""Tests for Conductor orchestration pipeline (P3 Phase 2)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lemonclaw.agent.types import AgentInfo, AgentStatus
from lemonclaw.conductor.types import (
    IntentAnalysis,
    OrchestrationPlan,
    SubTask,
    SubTaskStatus,
    TaskComplexity,
)


# ── Topological ordering (Kahn's algorithm) ───────────────────────────────


class TestTopologicalOrder:
    def test_empty(self):
        from lemonclaw.conductor.task_splitter import topological_order
        assert topological_order([]) == []

    def test_independent_tasks_single_wave(self):
        from lemonclaw.conductor.task_splitter import topological_order
        tasks = [
            SubTask(id="t1", description="A"),
            SubTask(id="t2", description="B"),
            SubTask(id="t3", description="C"),
        ]
        waves = topological_order(tasks)
        assert len(waves) == 1
        assert len(waves[0]) == 3

    def test_linear_chain(self):
        from lemonclaw.conductor.task_splitter import topological_order
        tasks = [
            SubTask(id="t1", description="A"),
            SubTask(id="t2", description="B", depends_on=["t1"]),
            SubTask(id="t3", description="C", depends_on=["t2"]),
        ]
        waves = topological_order(tasks)
        assert len(waves) == 3
        assert waves[0][0].id == "t1"
        assert waves[1][0].id == "t2"
        assert waves[2][0].id == "t3"

    def test_diamond_dependency(self):
        from lemonclaw.conductor.task_splitter import topological_order
        tasks = [
            SubTask(id="t1", description="root"),
            SubTask(id="t2", description="left", depends_on=["t1"]),
            SubTask(id="t3", description="right", depends_on=["t1"]),
            SubTask(id="t4", description="merge", depends_on=["t2", "t3"]),
        ]
        waves = topological_order(tasks)
        assert len(waves) == 3
        assert waves[0][0].id == "t1"
        assert {t.id for t in waves[1]} == {"t2", "t3"}
        assert waves[2][0].id == "t4"

    def test_cycle_raises(self):
        from lemonclaw.conductor.task_splitter import topological_order
        tasks = [
            SubTask(id="t1", description="A", depends_on=["t2"]),
            SubTask(id="t2", description="B", depends_on=["t1"]),
        ]
        with pytest.raises(ValueError, match="cycle"):
            topological_order(tasks)


class TestGetRunnable:
    def test_all_pending_no_deps(self):
        from lemonclaw.conductor.task_splitter import get_runnable
        tasks = [
            SubTask(id="t1", description="A"),
            SubTask(id="t2", description="B"),
        ]
        assert len(get_runnable(tasks)) == 2

    def test_blocked_by_dependency(self):
        from lemonclaw.conductor.task_splitter import get_runnable
        tasks = [
            SubTask(id="t1", description="A"),
            SubTask(id="t2", description="B", depends_on=["t1"]),
        ]
        runnable = get_runnable(tasks)
        assert len(runnable) == 1
        assert runnable[0].id == "t1"

    def test_unblocked_after_completion(self):
        from lemonclaw.conductor.task_splitter import get_runnable
        tasks = [
            SubTask(id="t1", description="A", status=SubTaskStatus.COMPLETED),
            SubTask(id="t2", description="B", depends_on=["t1"]),
        ]
        runnable = get_runnable(tasks)
        assert len(runnable) == 1
        assert runnable[0].id == "t2"


# ── Player selector (Jaccard similarity) ──────────────────────────────────


class TestJaccard:
    def test_identical_sets(self):
        from lemonclaw.conductor.player_selector import jaccard
        assert jaccard({"a", "b"}, {"a", "b"}) == 1.0

    def test_disjoint_sets(self):
        from lemonclaw.conductor.player_selector import jaccard
        assert jaccard({"a"}, {"b"}) == 0.0

    def test_partial_overlap(self):
        from lemonclaw.conductor.player_selector import jaccard
        assert jaccard({"a", "b"}, {"b", "c"}) == pytest.approx(1 / 3)

    def test_empty_sets(self):
        from lemonclaw.conductor.player_selector import jaccard
        assert jaccard(set(), set()) == 0.0


class TestRankAgents:
    def test_best_match_first(self):
        from lemonclaw.conductor.player_selector import rank_agents
        subtask = SubTask(id="t1", description="write code", required_skills=["coding", "python"])
        agents = [
            AgentInfo(agent_id="a1", role="writer", skills=["writing", "research"]),
            AgentInfo(agent_id="a2", role="coder", skills=["coding", "python", "testing"]),
        ]
        ranked = rank_agents(subtask, agents)
        assert ranked[0][0].agent_id == "a2"
        assert ranked[0][1] > ranked[1][1]

    def test_retired_excluded(self):
        from lemonclaw.conductor.player_selector import rank_agents
        subtask = SubTask(id="t1", description="task", required_skills=["coding"])
        agents = [
            AgentInfo(agent_id="a1", role="coder", skills=["coding"], status=AgentStatus.RETIRED),
        ]
        assert rank_agents(subtask, agents) == []

    def test_success_rate_bonus(self):
        from lemonclaw.conductor.player_selector import rank_agents
        subtask = SubTask(id="t1", description="task", required_skills=["coding"])
        a1 = AgentInfo(agent_id="a1", role="coder", skills=["coding"])
        a1.tasks_completed = 10
        a1.tasks_failed = 0
        a2 = AgentInfo(agent_id="a2", role="coder", skills=["coding"])
        a2.tasks_completed = 1
        a2.tasks_failed = 9
        ranked = rank_agents(subtask, [a1, a2])
        assert ranked[0][0].agent_id == "a1"


class TestSelectAgent:
    def test_returns_best(self):
        from lemonclaw.conductor.player_selector import select_agent
        subtask = SubTask(id="t1", description="task", required_skills=["coding"])
        agents = [
            AgentInfo(agent_id="a1", role="coder", skills=["coding"]),
        ]
        assert select_agent(subtask, agents).agent_id == "a1"

    def test_returns_none_below_threshold(self):
        from lemonclaw.conductor.player_selector import select_agent
        subtask = SubTask(id="t1", description="task", required_skills=["coding"])
        agents = [
            AgentInfo(agent_id="a1", role="writer", skills=["writing"]),
        ]
        assert select_agent(subtask, agents, min_score=0.5) is None


# ── OrchestrationPlan properties ──────────────────────────────────────────


class TestOrchestrationPlan:
    def test_is_complete(self):
        plan = OrchestrationPlan(
            request_id="r1",
            original_message="test",
            intent=IntentAnalysis(complexity=TaskComplexity.MODERATE, summary="test"),
            subtasks=[
                SubTask(id="t1", description="A", status=SubTaskStatus.COMPLETED),
                SubTask(id="t2", description="B", status=SubTaskStatus.FAILED),
            ],
        )
        assert plan.is_complete

    def test_not_complete(self):
        plan = OrchestrationPlan(
            request_id="r1",
            original_message="test",
            intent=IntentAnalysis(complexity=TaskComplexity.MODERATE, summary="test"),
            subtasks=[
                SubTask(id="t1", description="A", status=SubTaskStatus.COMPLETED),
                SubTask(id="t2", description="B", status=SubTaskStatus.PENDING),
            ],
        )
        assert not plan.is_complete

    def test_runnable_tasks(self):
        plan = OrchestrationPlan(
            request_id="r1",
            original_message="test",
            intent=IntentAnalysis(complexity=TaskComplexity.MODERATE, summary="test"),
            subtasks=[
                SubTask(id="t1", description="A", status=SubTaskStatus.COMPLETED),
                SubTask(id="t2", description="B", depends_on=["t1"]),
                SubTask(id="t3", description="C", depends_on=["t2"]),
            ],
        )
        runnable = plan.runnable_tasks
        assert len(runnable) == 1
        assert runnable[0].id == "t2"


class TestSwarmTemplates:
    def test_infers_seo_template(self):
        from lemonclaw.conductor.swarm_templates import infer_swarm_template

        template = infer_swarm_template(
            "Build an SEO content plan for this keyword cluster and article outline",
            ["research", "seo", "writing"],
        )
        assert template.id == "seo_content_studio"

    def test_falls_back_to_general_template(self):
        from lemonclaw.conductor.swarm_templates import infer_swarm_template

        template = infer_swarm_template("Help me think through this messy task", ["analysis"])
        assert template.id == "general_swarm"


@pytest.mark.asyncio
async def test_assign_creates_swarm_role_agents(tmp_path):
    from lemonclaw.agent.registry import AgentRegistry
    from lemonclaw.bus.queue import MessageBus
    from lemonclaw.conductor.orchestrator import Orchestrator

    provider = AsyncMock()
    bus = MessageBus()
    registry = AgentRegistry(bus, tmp_path)
    orch = Orchestrator(provider, bus, registry, model="gpt-5.4")

    plan = OrchestrationPlan(
        request_id="plan1",
        original_message="Create an SEO article workflow",
        intent=IntentAnalysis(complexity=TaskComplexity.MODERATE, summary="SEO workflow"),
        swarm_template_id="seo_content_studio",
        swarm_template_label="SEO Content Studio",
        swarm_goal="Create an SEO article workflow",
        subtasks=[
            SubTask(id="t1", description="Research the keyword and competitors", role_hint="researcher"),
            SubTask(id="t2", description="Draft the article", role_hint="writer"),
        ],
    )

    await orch._assign(plan)

    assert plan.subtasks[0].assigned_agent_id == "swarm-seo_content_studio-researcher"
    assert plan.subtasks[1].assigned_agent_id == "swarm-seo_content_studio-writer"
    assert registry.get_agent("swarm-seo_content_studio-researcher") is not None
    assert registry.get_agent("swarm-seo_content_studio-writer") is not None


@pytest.mark.asyncio
async def test_execute_subtask_uses_swarm_role_prompt_and_handoff(tmp_path):
    from lemonclaw.agent.registry import AgentRegistry
    from lemonclaw.bus.queue import MessageBus
    from lemonclaw.conductor.orchestrator import Orchestrator
    from lemonclaw.providers.base import LLMResponse

    provider = MagicMock()
    provider.chat = AsyncMock(return_value=LLMResponse(content="done"))
    bus = MessageBus()
    registry = AgentRegistry(bus, tmp_path)
    registry.create_agent(
        "swarm-general_swarm-maker",
        role="maker",
        model="gpt-5.4",
        system_prompt_override="You are the maker role.",
        config={"execution_mode": "direct"},
    )

    orch = Orchestrator(provider, bus, registry, model="gpt-5.4")
    plan = OrchestrationPlan(
        request_id="plan2",
        original_message="Ship a concrete deliverable",
        intent=IntentAnalysis(complexity=TaskComplexity.MODERATE, summary="Ship deliverable"),
        swarm_template_id="general_swarm",
        swarm_template_label="General Swarm",
        swarm_goal="Ship a concrete deliverable",
        subtasks=[
            SubTask(id="t1", description="Collect requirements", status=SubTaskStatus.COMPLETED, result="requirements ready"),
            SubTask(
                id="t2",
                description="Produce the final artifact",
                role_hint="maker",
                assigned_agent_id="swarm-general_swarm-maker",
                depends_on=["t1"],
                status=SubTaskStatus.RUNNING,
            ),
        ],
    )

    result = await orch._execute_subtask(plan, plan.subtasks[1])

    assert result == "done"
    subtask = plan.subtasks[1]
    assert subtask.generator.status == "completed"
    assert subtask.generator.mode == "direct"
    assert subtask.generator.details["output_kind"] == "text"
    assert subtask.evaluation.status in {"accepted", "needs_review"}
    assert len(subtask.artifacts) >= 1
    assert subtask.artifacts[0].artifact_id.endswith(":result")
    assert subtask.observability.trace_id
    assert subtask.observability.details["status"] == "completed"
    assert subtask.observability.duration_ms >= 0
    messages = provider.chat.await_args.kwargs["messages"]
    assert messages[0]["content"] == "You are the maker role."
    assert "Dependency handoff" in messages[1]["content"]
    assert "requirements ready" in messages[1]["content"]


@pytest.mark.asyncio
async def test_execute_subtask_failure_finishes_original_ledger_step(tmp_path):
    from lemonclaw.agent.registry import AgentRegistry
    from lemonclaw.bus.queue import MessageBus
    from lemonclaw.conductor.orchestrator import Orchestrator
    from lemonclaw.ledger.runtime import TaskLedger

    provider = MagicMock()
    provider.chat = AsyncMock(side_effect=RuntimeError("boom"))
    bus = MessageBus()
    registry = AgentRegistry(bus, tmp_path)
    ledger = TaskLedger(tmp_path)
    ledger.ensure_task(
        task_id="task_orch_1",
        session_key="cli:direct",
        agent_id="default",
        mode="chat",
        channel="cli",
        goal="orchestrate",
    )

    orch = Orchestrator(provider, bus, registry, model="gpt-5.4", max_retries=0, ledger=ledger)
    plan = OrchestrationPlan(
        request_id="plan3",
        original_message="Ship a concrete deliverable",
        intent=IntentAnalysis(complexity=TaskComplexity.MODERATE, summary="Ship deliverable"),
        subtasks=[
            SubTask(
                id="t_fail",
                description="Produce the final artifact",
                status=SubTaskStatus.RUNNING,
            ),
        ],
        metadata={"_ledger_task_id": "task_orch_1"},
    )

    result = await orch._execute_subtask(plan, plan.subtasks[0])

    assert result is None
    steps = ledger.materialize_steps("task_orch_1")
    assert len(steps) == 1
    assert steps[0]["name"] == "t_fail"
    assert steps[0]["status"] == "failed"


@pytest.mark.asyncio
async def test_handle_message_does_not_fallback_merge_when_dependency_failure_blocks_pending_subtask(tmp_path):
    from lemonclaw.agent.registry import AgentRegistry
    from lemonclaw.bus.events import InboundMessage
    from lemonclaw.bus.queue import MessageBus
    from lemonclaw.conductor.orchestrator import Orchestrator

    provider = MagicMock()
    bus = MessageBus()
    registry = AgentRegistry(bus, tmp_path)
    orch = Orchestrator(provider, bus, registry, model="gpt-5.4")
    orch._analyze = AsyncMock(return_value=IntentAnalysis(complexity=TaskComplexity.MODERATE, summary="complex"))  # type: ignore[method-assign]
    blocked_plan = OrchestrationPlan(
        request_id="plan-blocked",
        original_message="complex request",
        intent=IntentAnalysis(complexity=TaskComplexity.MODERATE, summary="complex"),
        subtasks=[
            SubTask(id="t1", description="upstream", status=SubTaskStatus.FAILED, result="boom"),
            SubTask(id="t2", description="downstream", status=SubTaskStatus.PENDING, depends_on=["t1"]),
        ],
    )
    orch._split = AsyncMock(return_value=blocked_plan)  # type: ignore[method-assign]
    orch._assign = AsyncMock(return_value=None)  # type: ignore[method-assign]
    orch._monitor = AsyncMock(return_value=None)  # type: ignore[method-assign]
    orch._merge = AsyncMock(return_value="should-not-merge")  # type: ignore[method-assign]

    result = await orch.handle_message(
        InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="complex request")
    )

    assert "couldn't safely finalize" in result.lower()
    orch._merge.assert_not_awaited()
    assert blocked_plan.merge.status == "failed"
    assert blocked_plan.evaluation.status == "failed"


@pytest.mark.asyncio
async def test_handle_message_blocks_merge_when_dependencies_fail_and_pending_remain(tmp_path):
    from lemonclaw.agent.registry import AgentRegistry
    from lemonclaw.bus.queue import MessageBus
    from lemonclaw.conductor.orchestrator import Orchestrator
    from lemonclaw.ledger.runtime import TaskLedger
    from lemonclaw.providers.base import LLMResponse

    provider = MagicMock()
    provider.chat = AsyncMock(return_value=LLMResponse(content="unused"))
    bus = MessageBus()
    registry = AgentRegistry(bus, tmp_path)
    ledger = TaskLedger(tmp_path)
    orch = Orchestrator(provider, bus, registry, model="gpt-5.4", ledger=ledger)

    intent = IntentAnalysis(
        complexity=TaskComplexity.MODERATE,
        summary="complex task",
        required_skills=["analysis"],
        reasoning="needs orchestration",
    )
    plan = OrchestrationPlan(
        request_id="plan-blocked",
        original_message="Do the complex task",
        intent=intent,
        subtasks=[
            SubTask(id="t1", description="root step", status=SubTaskStatus.FAILED),
            SubTask(id="t2", description="dependent step", depends_on=["t1"], status=SubTaskStatus.PENDING),
        ],
    )

    msg = type("Msg", (), {
        "content": "Do the complex task",
        "channel": "cli",
        "chat_id": "chat1",
        "sender_id": "user1",
        "session_key": "cli:chat1",
        "metadata": {"_task_id": "task_blocked"},
    })()

    with patch.object(orch, "_analyze", return_value=intent), \
        patch.object(orch, "_split", return_value=plan), \
        patch.object(orch, "_assign", return_value=None), \
        patch.object(orch, "_monitor", return_value=None), \
        patch.object(orch, "_merge", return_value="merged result") as merge_mock:
        result = await orch.handle_message(msg)

    assert "couldn't safely finalize" in result.lower()
    merge_mock.assert_not_called()
    task = ledger.read_task("task_blocked")
    assert task is not None
    assert task["status"] == "failed"
    assert task["current_stage"] == "blocked"
    assert task.get("completion_gate") is None
