"""Merge results from multiple players into a coherent response."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from loguru import logger

from lemonclaw.conductor.types import OrchestrationPlan, SubTask

if TYPE_CHECKING:
    from lemonclaw.providers.base import LLMProvider

_MERGE_PROMPT = """\
You are a result synthesizer. Multiple AI agents worked on subtasks of a larger request.
Combine their results into a single, coherent response for the user.

Do NOT mention agents, subtasks, or the orchestration process.
Write as if you completed the entire task yourself.
Be concise and well-structured."""


async def merge_results(
    provider: LLMProvider,
    plan: OrchestrationPlan,
    model: str | None = None,
) -> str:
    """Merge completed subtask results into a unified response."""
    completed = [t for t in plan.subtasks if t.result]
    if not completed:
        return "No results were produced."
    if len(completed) == 1:
        return completed[0].result or ""

    subtask_summary = "\n\n".join(
        f"### Task: {t.description}\n{t.result}" for t in completed
    )
    failed = plan.failed_tasks
    fail_note = ""
    if failed:
        fail_note = "\n\nNote: these subtasks failed:\n" + "\n".join(
            f"- {t.description}: {t.result or 'no output'}" for t in failed
        )

    try:
        response = await provider.chat(
            messages=[
                {"role": "system", "content": _MERGE_PROMPT},
                {"role": "user", "content": (
                    f"Original request: {plan.original_message}\n\n"
                    f"Subtask results:\n{subtask_summary}{fail_note}"
                )},
            ],
            model=model,
            temperature=0.3,
            max_tokens=4096,
        )
        return response.content or ""
    except Exception as e:
        logger.error("Result merge failed, concatenating: {}", e)
        return "\n\n---\n\n".join(t.result for t in completed if t.result)
