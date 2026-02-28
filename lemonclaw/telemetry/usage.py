"""Token usage tracking and budget alerts.

Tracks per-session and instance-level token consumption from LiteLLM responses.
Provides budget alerting when configured thresholds are exceeded.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from loguru import logger


@dataclass
class TurnUsage:
    """Token usage for a single agent turn (one or more LLM calls)."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    llm_calls: int = 0

    def record(self, usage: dict[str, int]) -> None:
        """Accumulate usage from a single LLM response."""
        prompt = usage.get("prompt_tokens", 0)
        completion = usage.get("completion_tokens", 0)
        total = usage.get("total_tokens", 0)
        # Fallback: if provider doesn't return total_tokens, compute it
        if total == 0 and (prompt or completion):
            total = prompt + completion
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.total_tokens += total
        self.llm_calls += 1

    def to_dict(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "llm_calls": self.llm_calls,
        }


class UsageTracker:
    """Instance-level usage tracker.

    Aggregates per-session usage stats and provides budget alerting.
    Session stats are persisted via session.metadata["usage_stats"].
    """

    def __init__(
        self,
        token_budget_per_session: int | None = None,
        cost_budget_per_day: float | None = None,
    ) -> None:
        self.token_budget_per_session = token_budget_per_session
        self.cost_budget_per_day = cost_budget_per_day  # TODO: cost tracking requires model pricing data from Orchestrator
        self._start_time = time.monotonic()
        # Instance-level cumulative counters (reset on restart)
        self._instance_totals: dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "llm_calls": 0,
        }

    def record_turn(self, session_key: str, turn: TurnUsage, session_metadata: dict[str, Any]) -> list[str]:
        """Record a completed turn's usage. Returns list of alert messages (empty if none)."""
        alerts: list[str] = []

        # Update session-level stats in metadata (persisted to JSONL)
        stats = session_metadata.setdefault("usage_stats", {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "llm_calls": 0,
        })
        for k in ("prompt_tokens", "completion_tokens", "total_tokens", "llm_calls"):
            stats[k] = stats.get(k, 0) + getattr(turn, k)

        # Update instance-level totals
        for k in ("prompt_tokens", "completion_tokens", "total_tokens", "llm_calls"):
            self._instance_totals[k] += getattr(turn, k)

        # Budget check: session token limit
        if self.token_budget_per_session and stats["total_tokens"] > self.token_budget_per_session:
            msg = (
                f"⚠️ Token budget exceeded: {stats['total_tokens']:,} / "
                f"{self.token_budget_per_session:,} tokens in this session."
            )
            alerts.append(msg)
            logger.warning("Session {} exceeded token budget: {}/{}", session_key, stats["total_tokens"], self.token_budget_per_session)

        return alerts

    def get_session_summary(self, session_metadata: dict[str, Any]) -> dict[str, Any]:
        """Get usage summary for a single session from its metadata."""
        stats = session_metadata.get("usage_stats", {})
        return {
            "prompt_tokens": stats.get("prompt_tokens", 0),
            "completion_tokens": stats.get("completion_tokens", 0),
            "total_tokens": stats.get("total_tokens", 0),
            "llm_calls": stats.get("llm_calls", 0),
        }

    def get_instance_summary(self) -> dict[str, Any]:
        """Get instance-level usage summary (since last restart)."""
        return {
            "uptime_s": round(time.monotonic() - self._start_time, 1),
            **self._instance_totals,
            "budgets": {
                "token_budget_per_session": self.token_budget_per_session,
                "cost_budget_per_day": self.cost_budget_per_day,
            },
        }

    def format_session_usage(self, session_metadata: dict[str, Any]) -> str:
        """Format session usage as a human-readable string for /usage command."""
        s = self.get_session_summary(session_metadata)
        lines = [
            "📊 Token Usage (this session)",
            f"  Input:  {s['prompt_tokens']:,}",
            f"  Output: {s['completion_tokens']:,}",
            f"  Total:  {s['total_tokens']:,}",
            f"  LLM calls: {s['llm_calls']}",
        ]
        if self.token_budget_per_session and self.token_budget_per_session > 0:
            pct = round(s["total_tokens"] / self.token_budget_per_session * 100, 1)
            lines.append(f"  Budget: {s['total_tokens']:,} / {self.token_budget_per_session:,} ({pct}%)")
        return "\n".join(lines)
