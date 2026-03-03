"""Player selection via Jaccard similarity matching."""

from __future__ import annotations

from lemonclaw.agent.types import AgentInfo, AgentStatus
from lemonclaw.conductor.types import SubTask


def jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard similarity coefficient between two sets."""
    if not a and not b:
        return 0.0
    intersection = a & b
    union = a | b
    return len(intersection) / len(union)


def rank_agents(
    subtask: SubTask,
    agents: list[AgentInfo],
) -> list[tuple[AgentInfo, float]]:
    """Rank agents by suitability for a subtask.

    Returns (agent, score) pairs sorted by descending score.
    Only active (non-retired) agents are considered.
    """
    required = set(subtask.required_skills)
    scored: list[tuple[AgentInfo, float]] = []

    for agent in agents:
        if agent.status == AgentStatus.RETIRED:
            continue
        agent_skills = set(agent.skills)
        sim = jaccard(required, agent_skills)
        # Bonus for agents with higher success rate
        score = sim * 0.8 + agent.success_rate * 0.2
        scored.append((agent, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def select_agent(
    subtask: SubTask,
    agents: list[AgentInfo],
    min_score: float = 0.0,
) -> AgentInfo | None:
    """Select the best agent for a subtask, or None if no suitable agent."""
    ranked = rank_agents(subtask, agents)
    if ranked and ranked[0][1] >= min_score:
        return ranked[0][0]
    return None
