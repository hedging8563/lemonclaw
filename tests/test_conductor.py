"""Tests for Conductor orchestration pipeline (P3 Phase 2)."""

import asyncio

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
