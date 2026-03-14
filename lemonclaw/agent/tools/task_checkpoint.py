"""Task checkpoint tool for writing explicit task progress to the ledger."""

from __future__ import annotations

from typing import Any

from lemonclaw.agent.tools.base import Tool
from lemonclaw.ledger.runtime import TaskLedger


class TaskCheckpointTool(Tool):
    """Persist explicit task progress into the local task ledger."""

    @property
    def name(self) -> str:
        return "task_checkpoint"

    @property
    def description(self) -> str:
        return (
            "Write an explicit checkpoint for the current task. "
            "Use this to persist the current stage, what succeeded, what is blocked, "
            "and what should happen next."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "stage": {
                    "type": "string",
                    "description": "Current stage name, e.g. 'execute' or 'verify'.",
                    "minLength": 1,
                    "maxLength": 80,
                },
                "summary": {
                    "type": "string",
                    "description": "Brief summary of current task progress.",
                    "minLength": 1,
                    "maxLength": 500,
                },
                "last_successful_step": {
                    "type": "string",
                    "description": "Optional last step that completed successfully.",
                    "maxLength": 120,
                },
                "next_action": {
                    "type": "string",
                    "description": "Optional next action to take.",
                    "maxLength": 200,
                },
                "status": {
                    "type": "string",
                    "description": "Optional task status override.",
                    "enum": ["running", "waiting", "verifying", "failed", "abandoned"],
                },
            },
            "required": ["stage", "summary"],
        }

    def resolve_capability(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> str:
        return "task.checkpoint.write"

    async def execute(
        self,
        stage: str,
        summary: str,
        last_successful_step: str | None = None,
        next_action: str | None = None,
        status: str | None = None,
        _task_id: str | None = None,
        _task_ledger: TaskLedger | None = None,
        **kwargs: Any,
    ) -> str:
        if not _task_id:
            return "Error: No active task id in context"
        if not _task_ledger:
            return "Error: Task ledger not available"

        updates: dict[str, Any] = {
            "current_stage": stage,
            "status": status or "running",
            "metadata": {
                "checkpoint_summary": summary,
                "next_action": next_action or "",
            },
        }
        if last_successful_step:
            updates["last_successful_step"] = last_successful_step

        _task_ledger.update_task(_task_id, **updates)
        return f"Checkpoint saved for {_task_id}: {summary}"
