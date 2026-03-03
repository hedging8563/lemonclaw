"""Task splitting and topological ordering for parallel execution."""

from collections import deque

from lemonclaw.conductor.types import SubTask, SubTaskStatus


def topological_order(subtasks: list[SubTask]) -> list[list[SubTask]]:
    """Return subtasks grouped into parallel execution waves using Kahn's algorithm.

    Each wave contains tasks whose dependencies are satisfied by all
    previous waves.  Tasks within the same wave can run concurrently.

    Returns:
        List of waves, where each wave is a list of SubTasks that can
        run in parallel.

    Raises:
        ValueError: If the dependency graph contains a cycle.
    """
    if not subtasks:
        return []

    task_map = {t.id: t for t in subtasks}
    in_degree: dict[str, int] = {t.id: 0 for t in subtasks}
    dependents: dict[str, list[str]] = {t.id: [] for t in subtasks}

    for t in subtasks:
        for dep_id in t.depends_on:
            if dep_id in task_map:
                in_degree[t.id] += 1
                dependents[dep_id].append(t.id)

    # Seed with zero-dependency tasks
    queue: deque[str] = deque(tid for tid, deg in in_degree.items() if deg == 0)
    waves: list[list[SubTask]] = []
    visited = 0

    while queue:
        wave = []
        next_queue: deque[str] = deque()
        while queue:
            tid = queue.popleft()
            wave.append(task_map[tid])
            visited += 1
            for dep_tid in dependents[tid]:
                in_degree[dep_tid] -= 1
                if in_degree[dep_tid] == 0:
                    next_queue.append(dep_tid)
        waves.append(wave)
        queue = next_queue

    if visited != len(subtasks):
        raise ValueError("Dependency cycle detected in subtask graph")

    return waves


def get_runnable(subtasks: list[SubTask]) -> list[SubTask]:
    """Return subtasks that are ready to run (pending + all deps completed)."""
    completed = {t.id for t in subtasks if t.status == SubTaskStatus.COMPLETED}
    return [
        t for t in subtasks
        if t.status == SubTaskStatus.PENDING
        and all(d in completed for d in t.depends_on)
    ]
