"""Completion gate for durable task finalization."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from lemonclaw.ledger.types import CompletionGateResult

if TYPE_CHECKING:
    from lemonclaw.ledger.runtime import TaskLedger


_OPEN_STEP_STATUSES = {"pending", "running", "waiting", "retrying"}
_FAILED_STEP_STATUSES = {"failed"}
_OPEN_OUTBOX_STATUSES = {"pending", "claimed", "retrying"}
_FAILED_OUTBOX_STATUSES = {"failed"}


def evaluate_completion(
    *,
    task_id: str,
    steps: list[dict[str, Any]],
    outbox_events: list[dict[str, Any]],
    checked_at_ms: int,
) -> CompletionGateResult:
    """Evaluate whether a task is safe to mark completed."""
    failed_steps = [str(step.get("step_id") or step.get("name") or "") for step in steps if step.get("status") in _FAILED_STEP_STATUSES]
    if failed_steps:
        return CompletionGateResult(
            task_id=task_id,
            passed=False,
            reason=f"failed steps remain: {', '.join(failed_steps[:5])}",
            next_status="failed",
            next_stage="error",
            checked_at_ms=checked_at_ms,
            open_steps=failed_steps[:20],
        )

    open_steps = [str(step.get("step_id") or step.get("name") or "") for step in steps if step.get("status") in _OPEN_STEP_STATUSES]
    if open_steps:
        return CompletionGateResult(
            task_id=task_id,
            passed=False,
            reason=f"unfinished steps remain: {', '.join(open_steps[:5])}",
            next_status="running",
            next_stage="verify",
            checked_at_ms=checked_at_ms,
            open_steps=open_steps[:20],
        )

    failed_outbox = [str(event.get("event_id") or "") for event in outbox_events if event.get("status") in _FAILED_OUTBOX_STATUSES]
    if failed_outbox:
        return CompletionGateResult(
            task_id=task_id,
            passed=False,
            reason=f"failed outbox events remain: {', '.join(failed_outbox[:5])}",
            next_status="waiting",
            next_stage="waiting_outbox",
            checked_at_ms=checked_at_ms,
            open_outbox=failed_outbox[:20],
        )

    open_outbox = [str(event.get("event_id") or "") for event in outbox_events if event.get("status") in _OPEN_OUTBOX_STATUSES]
    if open_outbox:
        return CompletionGateResult(
            task_id=task_id,
            passed=False,
            reason=f"pending outbox events remain: {', '.join(open_outbox[:5])}",
            next_status="waiting",
            next_stage="waiting_outbox",
            checked_at_ms=checked_at_ms,
            open_outbox=open_outbox[:20],
        )

    return CompletionGateResult(
        task_id=task_id,
        passed=True,
        reason="all known steps and outbox events are settled",
        next_status="completed",
        next_stage="done",
        checked_at_ms=checked_at_ms,
    )


def finalize_task(ledger: "TaskLedger", task_id: str) -> CompletionGateResult | None:
    """Move a task through verifying and persist the gate decision."""
    task = ledger.read_task(task_id)
    if not task:
        return None

    ledger.update_task(task_id, status="verifying", current_stage="verify")
    result = evaluate_completion(
        task_id=task_id,
        steps=ledger.materialize_steps(task_id),
        outbox_events=ledger.materialize_outbox_events_for_task(task_id),
        checked_at_ms=ledger.now_ms(),
    )
    updates: dict[str, Any] = {
        "status": result.next_status,
        "current_stage": result.next_stage,
        "completion_gate": result.to_dict(),
    }
    if result.passed:
        updates["error"] = None
    elif result.next_status == "failed":
        updates["error"] = result.reason[:500]
    ledger.update_task(task_id, **updates)
    return result
