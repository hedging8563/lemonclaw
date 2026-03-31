"""Completion gate for durable task finalization."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

from lemonclaw.ledger.types import (
    CompletionGateResult,
    OUTBOX_ABANDONED_STATUSES,
    OUTBOX_ACTIVE_STATUSES,
    OUTBOX_FAILURE_STATUSES,
    summarize_verification_metadata,
)

if TYPE_CHECKING:
    from lemonclaw.ledger.runtime import TaskLedger


_OPEN_STEP_STATUSES = {"pending", "running", "waiting", "retrying"}
_OUTBOX_WAITING_STEP_STATUSES = {"waiting_outbox"}
_FAILED_STEP_STATUSES = {"failed"}
_OPEN_OUTBOX_STATUSES = set(OUTBOX_ACTIVE_STATUSES)
_FAILED_OUTBOX_STATUSES = {"failed"}
_EXPIRED_OUTBOX_STATUSES = {"expired"}
_ABANDONED_OUTBOX_STATUSES = set(OUTBOX_ABANDONED_STATUSES)
_VERIFICATION_ACCEPTED_STATUSES = {"accepted", "complete", "completed", "passed", "ok", "recorded"}


def _build_acceptance_evidence_summary(verification: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(verification, dict):
        return {}

    acceptance_evidence = [dict(item) for item in list(verification.get("acceptance_evidence") or []) if isinstance(item, dict)]
    status_counts: dict[str, int] = {}
    kind_counts: dict[str, int] = {}
    accepted_count = 0
    for item in acceptance_evidence:
        status = str(item.get("status") or "recorded").strip().lower()
        kind = str(item.get("kind") or "").strip()
        status_counts[status] = status_counts.get(status, 0) + 1
        if kind:
            kind_counts[kind] = kind_counts.get(kind, 0) + 1
        if status in _VERIFICATION_ACCEPTED_STATUSES:
            accepted_count += 1

    return {
        "count": len(acceptance_evidence),
        "accepted_count": accepted_count,
        "status_counts": status_counts,
        "kind_counts": kind_counts,
    }


def _build_surface_replay_pointer(verification: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(verification, dict):
        return {}

    pointer = verification.get("ui_channel_replay")
    if not isinstance(pointer, dict):
        pointer = verification.get("replay_pointer")
    if not isinstance(pointer, dict):
        return {}

    normalized: dict[str, Any] = {}
    for field, limit in (
        ("kind", 80),
        ("channel", 80),
        ("chat_id", 120),
        ("thread_id", 120),
        ("message_id", 120),
        ("task_id", 120),
        ("step_id", 120),
        ("url", 500),
        ("note", 300),
    ):
        value = pointer.get(field)
        if value in (None, "", []):
            continue
        text = str(value).strip()[:limit]
        if text:
            normalized[field] = text
    for field in ("source",):
        value = pointer.get(field)
        if value not in (None, "", []):
            normalized[field] = value
    for field in ("at_ms",):
        value = pointer.get(field)
        if value not in (None, "", []):
            normalized[field] = value
    return normalized


def evaluate_completion(
    *,
    task_id: str,
    steps: list[dict[str, Any]],
    outbox_events: list[dict[str, Any]],
    checked_at_ms: int,
    verification: dict[str, Any] | None = None,
) -> CompletionGateResult:
    """Evaluate whether a task is safe to mark completed."""
    verification_summary = summarize_verification_metadata(verification, steps=steps)
    if verification_summary:
        evidence_summary = _build_acceptance_evidence_summary(verification)
        if evidence_summary:
            verification_summary["acceptance_evidence_summary"] = evidence_summary
        surface_replay_pointer = _build_surface_replay_pointer(verification)
        if surface_replay_pointer:
            verification_summary["surface_replay_pointer"] = surface_replay_pointer
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
            verification=verification_summary,
        )

    abandoned_outbox = [str(event.get("event_id") or "") for event in outbox_events if event.get("status") in _ABANDONED_OUTBOX_STATUSES]
    if abandoned_outbox:
        return CompletionGateResult(
            task_id=task_id,
            passed=False,
            reason=f"abandoned outbox events remain: {', '.join(abandoned_outbox[:5])}",
            next_status="abandoned",
            next_stage="abandoned",
            checked_at_ms=checked_at_ms,
            open_outbox=abandoned_outbox[:20],
            verification=verification_summary,
        )

    expired_outbox = [str(event.get("event_id") or "") for event in outbox_events if event.get("status") in _EXPIRED_OUTBOX_STATUSES]
    if expired_outbox:
        return CompletionGateResult(
            task_id=task_id,
            passed=False,
            reason=f"expired outbox events remain: {', '.join(expired_outbox[:5])}",
            next_status="failed",
            next_stage="error",
            checked_at_ms=checked_at_ms,
            open_outbox=expired_outbox[:20],
            verification=verification_summary,
        )

    failed_outbox = [str(event.get("event_id") or "") for event in outbox_events if event.get("status") in _FAILED_OUTBOX_STATUSES]
    if failed_outbox:
        # Failed outbox does not immediately fail the whole task: the task stays
        # blocked in waiting_outbox so a dispatcher / compensator can retry or
        # reconcile the side effect without the agent declaring success early.
        return CompletionGateResult(
            task_id=task_id,
            passed=False,
            reason=f"failed outbox events remain: {', '.join(failed_outbox[:5])}",
            next_status="waiting",
            next_stage="waiting_outbox",
            checked_at_ms=checked_at_ms,
            open_outbox=failed_outbox[:20],
            verification=verification_summary,
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
            verification=verification_summary,
        )

    waiting_outbox_steps = [str(step.get("step_id") or step.get("name") or "") for step in steps if step.get("status") in _OUTBOX_WAITING_STEP_STATUSES]
    if waiting_outbox_steps:
        return CompletionGateResult(
            task_id=task_id,
            passed=False,
            reason=f"waiting outbox steps remain: {', '.join(waiting_outbox_steps[:5])}",
            next_status="waiting",
            next_stage="waiting_outbox",
            checked_at_ms=checked_at_ms,
            open_steps=waiting_outbox_steps[:20],
            verification=verification_summary,
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
            verification=verification_summary,
        )

    if verification_summary.get("required") and verification_summary.get("missing_requirements"):
        missing = [str(item) for item in verification_summary.get("missing_requirements") or [] if str(item)]
        return CompletionGateResult(
            task_id=task_id,
            passed=False,
            reason=f"verification requirements remain: {', '.join(missing[:5])}",
            next_status="running",
            next_stage="verify",
            checked_at_ms=checked_at_ms,
            verification=verification_summary,
        )

    return CompletionGateResult(
        task_id=task_id,
        passed=True,
        reason="all known steps and outbox events are settled",
        next_status="completed",
        next_stage="done",
        checked_at_ms=checked_at_ms,
        verification=verification_summary,
    )


def finalize_task(ledger: "TaskLedger", task_id: str) -> CompletionGateResult | None:
    """Move a task through verifying and persist the gate decision."""
    task = ledger.read_task(task_id)
    if not task:
        logger.warning("Completion gate skipped missing task {}", task_id)
        return None

    ledger.update_task(task_id, status="verifying", current_stage="verify")
    try:
        result = evaluate_completion(
            task_id=task_id,
            steps=ledger.materialize_steps(task_id),
            outbox_events=ledger.materialize_outbox_events_for_task(task_id),
            checked_at_ms=ledger.now_ms(),
            verification=((task.get("metadata") or {}).get("verification") or {}),
        )
    except Exception as exc:
        logger.exception("Completion gate evaluation failed for {}", task_id)
        result = CompletionGateResult(
            task_id=task_id,
            passed=False,
            reason=f"completion gate evaluation failed: {type(exc).__name__}: {exc}"[:500],
            next_status="failed",
            next_stage="error",
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
