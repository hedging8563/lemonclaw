"""Intent analysis — determine task complexity and required skills."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from loguru import logger

from lemonclaw.conductor.types import IntentAnalysis, TaskComplexity
from lemonclaw.utils.helpers import strip_fences

if TYPE_CHECKING:
    from lemonclaw.providers.base import LLMProvider

_ANALYSIS_PROMPT = """\
You are a task complexity analyzer. Given a user message, determine:
1. complexity: "simple" (single-step, conversational), "moderate" (2-3 steps, 1-2 specialists), or "complex" (4+ steps, multiple specialists with dependencies)
2. summary: one-line description of what the user wants
3. required_skills: list of skill categories needed (e.g. ["coding", "research", "writing"])
4. reasoning: brief explanation of your assessment

Respond with ONLY a JSON object, no markdown fences:
{"complexity": "simple|moderate|complex", "summary": "...", "required_skills": ["..."], "reasoning": "..."}

Most messages are "simple". Only classify as "moderate" or "complex" when the task genuinely requires multiple independent work streams that benefit from parallel execution."""


async def analyze_intent(
    provider: LLMProvider,
    message: str,
    model: str | None = None,
) -> IntentAnalysis:
    """Analyze user message to determine task complexity.

    Falls back to SIMPLE on any parsing failure — safe default.
    """
    try:
        response = await provider.chat(
            messages=[
                {"role": "system", "content": _ANALYSIS_PROMPT},
                {"role": "user", "content": message},
            ],
            model=model,
            temperature=0.0,
            max_tokens=256,
        )
        data = json.loads(strip_fences(response.content or ""))
        return IntentAnalysis(
            complexity=TaskComplexity(data.get("complexity", "simple")),
            summary=data.get("summary", message[:80]),
            required_skills=data.get("required_skills", []),
            reasoning=data.get("reasoning", ""),
        )
    except Exception as e:
        logger.debug("Intent analysis fallback to SIMPLE: {}", e)
        return IntentAnalysis(
            complexity=TaskComplexity.SIMPLE,
            summary=message[:80],
            reasoning=f"Fallback: {e}",
        )
