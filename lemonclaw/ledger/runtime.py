"""Task ledger runtime facade and JSON-backed store."""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from lemonclaw.channels.delivery_context import normalize_delivery_policy
from lemonclaw.governance.redaction import redact_sensitive_value
from lemonclaw.ledger.types import (
    OutboxEventRecord,
    StepRecord,
    TaskRecord,
    OUTBOX_ABANDONED_STATUSES,
    OUTBOX_ACTIVE_STATUSES,
    OUTBOX_EFFECT_SPECS,
    OUTBOX_FAILURE_STATUSES,
    OUTBOX_SUCCESS_STATUSES,
    OUTBOX_TERMINAL_STATUSES,
    VERIFICATION_ACCEPTED_STATUSES,
    describe_outbox_effect_type,
    infer_delivery_outcome,
    is_supported_outbox_effect_type,
    summarize_verification_metadata,
)


def _now_ms() -> int:
    return int(time.time() * 1000)


_SAFE_TASK_ID = re.compile(r"^task_[A-Za-z0-9_-]{1,64}$")
_SAFE_OUTBOX_ID = re.compile(r"^ob_[A-Za-z0-9_-]{1,64}$")
_SAFE_STEP_ID = re.compile(r"^step_[A-Za-z0-9_-]{1,64}$")
_SENSITIVE_EXPORT_KEY = re.compile(r"(^|[_-])(authorization|token|secret|password|api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret)($|[_-])", re.IGNORECASE)
_OUTBOX_MANUAL_RETRY_DEBOUNCE_MS = 1500
_OUTBOX_CLAIM_STALE_AFTER_MS = 30_000


def build_task_resume_context(
    *,
    channel: str,
    chat_id: str,
    session_key: str,
    sender_id: str = "",
    timezone: str = "",
    run_mode: str = "",
    session_context: dict[str, Any] | None = None,
    message_id: str = "",
    delivery_context: dict[str, Any] | None = None,
    delivery_policy: dict[str, Any] | None = None,
    auto_resume_allowed: bool = True,
    resume_disabled_reason: str = "",
) -> dict[str, Any]:
    """Build a stable resume context payload for later task recovery."""
    normalized_session_context = dict(session_context or {})
    if not normalized_session_context:
        normalized_session_context = {
            "session_key": str(session_key),
            "identity": {
                "channel": str(channel),
                "account": "",
                "chat": str(chat_id),
                "thread": "",
                "topic": "",
            },
            "timezone": str(timezone or ""),
            "run_mode": str(run_mode or ""),
        }
    return {
        "channel": str(channel),
        "chat_id": str(chat_id),
        "sender_id": str(sender_id or ""),
        "session_key": str(session_key),
        "timezone": str(timezone or ""),
        "run_mode": str(run_mode or ""),
        "session_context": normalized_session_context,
        "message_id": str(message_id or ""),
        "delivery_context": dict(delivery_context or {}),
        "delivery_policy": normalize_delivery_policy(delivery_policy or {}),
        "auto_resume_allowed": bool(auto_resume_allowed),
        "resume_disabled_reason": str(resume_disabled_reason or ""),
    }


class TaskLedgerSharedMixin:
    """Shared ledger behavior that is backend-agnostic."""

    @staticmethod
    def _humanize_code(value: Any) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        return re.sub(r"\s+", " ", re.sub(r"[_-]+", " ", raw)).strip()

    @staticmethod
    def _build_session_runtime_summary(task: dict[str, Any]) -> dict[str, Any]:
        resume_context = dict(task.get("resume_context") or {})
        session_context = dict(resume_context.get("session_context") or {})
        identity = dict(session_context.get("identity") or {})
        delivery_context = dict(resume_context.get("delivery_context") or {})
        route = dict(delivery_context.get("route") or {}) if isinstance(delivery_context.get("route"), dict) else {}
        delivery_policy = dict(resume_context.get("delivery_policy") or {})

        return {
            "session_key": str(resume_context.get("session_key") or task.get("session_key") or ""),
            "identity": {
                "channel": str(identity.get("channel") or resume_context.get("channel") or task.get("channel") or ""),
                "account": str(identity.get("account") or ""),
                "chat": str(identity.get("chat") or resume_context.get("chat_id") or ""),
                "thread": str(identity.get("thread") or ""),
                "topic": str(identity.get("topic") or ""),
            },
            "runtime": {
                "timezone": str(session_context.get("timezone") or resume_context.get("timezone") or ""),
                "run_mode": str(session_context.get("run_mode") or resume_context.get("run_mode") or ""),
            },
            "delivery": {
                "mode": str(delivery_policy.get("mode") or ""),
                "preserve_message_identity": bool(delivery_policy.get("preserve_message_identity")),
                "message_id": str(resume_context.get("message_id") or route.get("message_id") or ""),
                "reply_to_message_id": str(route.get("reply_to_message_id") or ""),
                "message_thread_id": str(route.get("message_thread_id") or ""),
            },
        }

    @classmethod
    def _build_progress_read_model(
        cls,
        task: dict[str, Any],
        *,
        display_state: dict[str, Any] | None,
        verification: dict[str, Any] | None,
        outbox_lifecycle: dict[str, Any] | None,
        conductor: dict[str, Any] | None,
        candidate: dict[str, Any] | None,
        steps: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        metadata = dict(task.get("metadata") or {})
        verification_map = dict(verification or {})
        outbox_map = dict(outbox_lifecycle or {})
        conductor_map = dict(conductor or {})
        display = dict(display_state or {})
        candidate_map = dict(candidate or {})
        step_list = list(steps or [])
        task_status = str(task.get("status") or "").strip()
        task_stage = str(task.get("current_stage") or "").strip()
        conductor_phase = str(dict(conductor_map.get("observability") or {}).get("phase") or "").strip()
        task_settled = task_status in {"completed", "abandoned"} or task_stage in {"done", "abandoned"}
        task_terminal = task_settled or task_status == "failed" or task_stage in {"error", "hard_recovery", "stale_recovery"}

        phase = (task_stage or task_status) if task_terminal else (conductor_phase or task_stage or task_status)
        headline = (
            str(dict(conductor_map.get("generator") or {}).get("summary") or "").strip()
            or str(dict(conductor_map.get("planner") or {}).get("summary") or "").strip()
            or str(display.get("detail") or "").strip()
            or str(task.get("goal") or "").strip()[:180]
        )

        completed_items: list[str] = []
        for item in list(conductor_map.get("subtasks") or []):
            if not isinstance(item, dict) or str(item.get("status") or "") != "completed":
                continue
            summary = str(item.get("description") or item.get("id") or "").strip()
            if summary and summary not in completed_items:
                completed_items.append(summary[:160])
            if len(completed_items) >= 5:
                break
        if len(completed_items) < 5:
            for item in list(verification_map.get("acceptance_evidence") or []):
                if not isinstance(item, dict):
                    continue
                status = str(item.get("status") or "").strip().lower()
                if status not in VERIFICATION_ACCEPTED_STATUSES:
                    continue
                summary = str(item.get("summary") or item.get("kind") or "").strip()
                if summary and summary not in completed_items:
                    completed_items.append(summary[:160])
                if len(completed_items) >= 5:
                    break
        if len(completed_items) < 5 and task.get("last_successful_step"):
            completed_items.append(str(task.get("last_successful_step") or "")[:160])

        waiting_on: list[str] = []
        missing = [str(item) for item in list(verification_map.get("missing_requirements") or []) if str(item)]
        for item in missing:
            if item not in waiting_on:
                waiting_on.append(item)
        active_outbox = int(outbox_map.get("active_count") or 0)
        if active_outbox > 0:
            waiting_on.append(f"outbox:{active_outbox}")
        recovery = dict(metadata.get("recovery") or {})
        if recovery.get("manual_review_required"):
            waiting_on.append("manual_review")
        state_key = str(display.get("key") or "").strip()
        if state_key == "resume_requested":
            waiting_on.append("resume_queue")
        if state_key == "resume_dispatch_failed":
            waiting_on.append("resume_dispatch")
        if candidate_map.get("recommended_action") == "wait_outbox":
            waiting_on.append("delivery_retry")

        current_blocker = ""
        if missing:
            current_blocker = f"verification requirements: {', '.join(missing[:3])}"
        elif active_outbox > 0:
            current_blocker = f"waiting on outbox delivery ({active_outbox})"
        elif recovery.get("manual_review_required"):
            current_blocker = str(recovery.get("reason") or "manual review required")
        elif state_key in {"resume_dispatch_failed", "resume_manual_only", "waiting_outbox", "failed", "waiting"}:
            current_blocker = str(display.get("detail") or task.get("error") or "")

        explicit_next_action = str(metadata.get("next_action") or "").strip()
        candidate_action = str(candidate_map.get("recommended_action") or "").strip().lower()
        if candidate_action == "noop":
            candidate_next_action = "no action needed"
        elif task_settled:
            candidate_next_action = ""
        else:
            candidate_next_action = cls._humanize_code(candidate_action)
        next_action = (
            explicit_next_action
            or ("no action needed" if task_settled else "")
            or candidate_next_action
            or ("collect missing verification evidence" if missing else "")
            or ("retry delivery / outbox" if active_outbox > 0 else "")
            or ("review queued resume" if state_key == "resume_requested" else "")
            or str(display.get("label") or "").strip()
        )

        latest_artifacts: list[dict[str, Any]] = []
        artifacts_block = dict(conductor_map.get("artifacts") or {})
        for item in list(artifacts_block.get("items") or []):
            if not isinstance(item, dict):
                continue
            latest_artifacts.append(
                {
                    "artifact_id": str(item.get("artifact_id") or item.get("id") or ""),
                    "kind": str(item.get("kind") or ""),
                    "title": str(item.get("title") or item.get("label") or ""),
                    "source": str(item.get("source") or ""),
                }
            )
            if len(latest_artifacts) >= 4:
                break
        if len(latest_artifacts) < 4:
            for item in list(verification_map.get("acceptance_evidence") or []):
                if not isinstance(item, dict):
                    continue
                artifact_id = str(item.get("artifact_id") or "").strip()
                if not artifact_id:
                    continue
                latest_artifacts.append(
                    {
                        "artifact_id": artifact_id,
                        "kind": str(item.get("kind") or ""),
                        "title": str(item.get("summary") or artifact_id)[:160],
                        "source": "verification",
                    }
                )
                if len(latest_artifacts) >= 4:
                    break

        return {
            "phase": phase,
            "headline": headline,
            "completed_items": completed_items[:5],
            "current_blocker": current_blocker[:240],
            "next_action": next_action[:200],
            "latest_artifacts": latest_artifacts,
            "waiting_on": waiting_on[:6],
            "last_updated_ms": int(task.get("updated_at_ms") or 0),
            "session_runtime": cls._build_session_runtime_summary(task),
            "step_trace_count": len(step_list),
            "tool_trace_count": int(verification_map.get("tool_trace_count") or 0),
        }

    @staticmethod
    def _build_retry_outbox_reason(*, failed_count: int, expired_count: int) -> str:
        if failed_count and expired_count:
            return f"{failed_count} failed and {expired_count} expired outbox event(s) can be retried safely"
        if failed_count:
            return f"{failed_count} failed outbox event(s) can be retried safely"
        return f"{expired_count} expired outbox event(s) can be retried safely"

    def _retryable_outbox_events(
        self,
        outbox_events: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        failed_outbox = [event for event in outbox_events if str(event.get("status") or "") == "failed"]
        expired_outbox = [event for event in outbox_events if str(event.get("status") or "") == "expired"]
        retryable_outbox = [event for event in outbox_events if str(event.get("status") or "") in OUTBOX_FAILURE_STATUSES]
        open_outbox = [event for event in outbox_events if str(event.get("status") or "") in OUTBOX_ACTIVE_STATUSES]
        return failed_outbox, expired_outbox, retryable_outbox, open_outbox

    def abandon_outbox_events_for_session(
        self,
        session_key: str,
        *,
        source: str,
        reason: str,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Terminalize active outbox work for every task in a session."""
        abandoned: list[dict[str, Any]] = []
        for task in self.list_tasks(limit=max(1, int(limit)), session_key=session_key):
            task_id = str(task.get("task_id") or "")
            if not task_id:
                continue
            abandoned.extend(
                self.abandon_outbox_events_for_task(
                    task_id,
                    source=source,
                    reason=reason,
                )
            )
        return abandoned

    def abandon_outbox_events_for_task(
        self,
        task_id: str,
        *,
        source: str,
        reason: str,
    ) -> list[dict[str, Any]]:
        """Terminalize active outbox work for a single task."""
        if not task_id or not self.is_valid_task_id(task_id):
            return []

        abandoned: list[dict[str, Any]] = []
        for event in self.materialize_outbox_events_for_task(task_id):
            if str(event.get("status") or "") not in OUTBOX_ACTIVE_STATUSES:
                continue
            updated = self.abandon_outbox_event(
                str(event["event_id"]),
                source=source,
                reason=reason,
            )
            if updated is not None:
                abandoned.append(updated)
        return abandoned

    def _execute_retry_outbox_recovery(
        self,
        task_id: str,
        *,
        source: str,
        failed_count: int,
        expired_count: int,
    ) -> dict[str, Any] | None:
        retried = 0
        for event in self.materialize_outbox_events_for_task(task_id):
            if str(event.get("status") or "") not in OUTBOX_FAILURE_STATUSES:
                continue
            updated = self.request_outbox_retry(str(event["event_id"]), source=source)
            if updated is not None:
                retried += 1
        task = self.read_task(task_id)
        if task:
            metadata = dict(task.get("metadata") or {})
            self._append_recovery_history(
                metadata,
                source=source,
                action="safe_resume_execute",
                reason=self._build_retry_outbox_reason(
                    failed_count=failed_count,
                    expired_count=expired_count,
                ),
                details={
                    "task_id": task_id,
                    "retried_outbox_count": retried,
                    "failed_outbox_count": failed_count,
                    "expired_outbox_count": expired_count,
                },
            )
            self.update_task(task_id, metadata=metadata)
        return self.build_resume_candidate(task_id)

    def reclaim_stale_claimed_outbox_events(
        self,
        *,
        stale_after_ms: int = _OUTBOX_CLAIM_STALE_AFTER_MS,
        source: str,
        now_ms: int | None = None,
    ) -> list[dict[str, Any]]:
        now = now_ms if now_ms is not None else _now_ms()
        threshold = max(1, int(stale_after_ms))
        reclaimed: list[dict[str, Any]] = []
        for event in self.materialize_outbox_events():
            if str(event.get("status") or "") != "claimed":
                continue
            metadata = dict(event.get("metadata") or {})
            claimed_at_ms = int(metadata.get("claimed_at_ms") or 0)
            if claimed_at_ms <= 0 or (now - claimed_at_ms) < threshold:
                continue
            updated = self.request_outbox_retry(
                str(event["event_id"]),
                source=source,
                delay_ms=0,
            )
            if updated is not None:
                reclaimed.append(updated)
        return reclaimed

    def materialize_steps(self, task_id: str) -> list[dict[str, Any]]:
        """Collapse step event history into the latest state per step_id."""
        latest_by_step: dict[str, dict[str, Any]] = {}
        for event in self.read_steps(task_id):
            step_id = str(event.get("step_id", "")).strip()
            if not step_id:
                continue
            latest_by_step[step_id] = event
        return sorted(
            latest_by_step.values(),
            key=lambda item: (
                int(item.get("started_at_ms") or 0),
                int(item.get("ended_at_ms") or 0),
            ),
        )

    def get_recovery_summary(self) -> dict[str, int]:
        """Return aggregate counters for recovery-oriented observability."""
        tasks = self.list_recovery_tasks(limit=500)
        return self.summarize_recovery_tasks(tasks)

    @staticmethod
    def _derive_recovery_ref(details: dict[str, Any] | None) -> dict[str, Any] | None:
        detail_map = dict(details or {})
        ref: dict[str, Any] = {}
        if detail_map.get("step_id"):
            ref["step_id"] = str(detail_map["step_id"])
        elif detail_map.get("resume_from_step"):
            ref["step_id"] = str(detail_map["resume_from_step"])
        if detail_map.get("event_id"):
            ref["outbox_event_id"] = str(detail_map["event_id"])
        elif detail_map.get("outbox_event_id"):
            ref["outbox_event_id"] = str(detail_map["outbox_event_id"])
        if isinstance(detail_map.get("step_ids"), list):
            step_ids = [str(item) for item in detail_map.get("step_ids") or [] if item]
            if step_ids:
                ref["step_ids"] = step_ids
        if isinstance(detail_map.get("superseded_steps"), list):
            step_ids = [str(item) for item in detail_map.get("superseded_steps") or [] if item]
            if step_ids:
                ref["step_ids"] = step_ids
        if isinstance(detail_map.get("restored_steps"), list):
            step_ids = [str(item) for item in detail_map.get("restored_steps") or [] if item]
            if step_ids:
                ref["step_ids"] = step_ids
        if isinstance(detail_map.get("outbox_event_ids"), list):
            event_ids = [str(item) for item in detail_map.get("outbox_event_ids") or [] if item]
            if event_ids:
                ref["outbox_event_ids"] = event_ids
        return ref or None

    @staticmethod
    def _append_recovery_history(
        metadata: dict[str, Any],
        *,
        source: str,
        action: str,
        reason: str = "",
        details: dict[str, Any] | None = None,
        at_ms: int | None = None,
    ) -> dict[str, Any]:
        history = list(metadata.get("recovery_history") or [])
        entry = {
            "recovery_id": f"rc_{uuid.uuid4().hex[:10]}",
            "source": source,
            "action": action,
            "reason": reason[:500],
            "details": dict(details or {}),
            "at_ms": at_ms or _now_ms(),
        }
        ref = TaskLedgerSharedMixin._derive_recovery_ref(details)
        if ref:
            entry["ref"] = ref
        history.append(entry)
        metadata["recovery_history"] = history[-20:]
        return metadata

    @staticmethod
    def append_recovery_history(
        metadata: dict[str, Any],
        *,
        source: str,
        action: str,
        reason: str = "",
        details: dict[str, Any] | None = None,
        at_ms: int | None = None,
    ) -> dict[str, Any]:
        """Public wrapper for appending structured recovery history entries."""
        return TaskLedgerSharedMixin._append_recovery_history(
            metadata,
            source=source,
            action=action,
            reason=reason,
            details=details,
            at_ms=at_ms,
        )

    @staticmethod
    def summarize_recovery_tasks(tasks: list[dict[str, Any]]) -> dict[str, int]:
        """Aggregate counters for a preloaded recovery task list."""
        summary = {
            "tasks_with_recovery": len(tasks),
            "manual_review_required": 0,
            "stale_recovery_failed": 0,
            "waiting_manual_review": 0,
        }
        for task in tasks:
            recovery = (task.get("metadata") or {}).get("recovery") or {}
            status = str(task.get("status") or "")
            stage = str(task.get("current_stage") or "")
            if recovery.get("manual_review_required"):
                summary["manual_review_required"] += 1
            if status == "failed" and stage == "stale_recovery":
                summary["stale_recovery_failed"] += 1
            if status == "waiting" and recovery.get("manual_review_required"):
                summary["waiting_manual_review"] += 1
        return summary

    @staticmethod
    def _sanitize_export_value(value: Any) -> Any:
        return redact_sensitive_value(value)

    @staticmethod
    def _append_outbox_history(
        metadata: dict[str, Any],
        *,
        action: str,
        status: str,
        at_ms: int | None = None,
        result: dict[str, Any] | None = None,
        error: str = "",
        source: str = "",
    ) -> dict[str, Any]:
        history = list(metadata.get("delivery_history") or [])
        entry = {
            "action": str(action or ""),
            "status": str(status or ""),
            "at_ms": int(at_ms or _now_ms()),
            "source": str(source or ""),
        }
        outcome = infer_delivery_outcome(status=status, metadata=metadata, error=error)
        if outcome:
            entry["delivery_outcome"] = outcome
        if result:
            entry["result"] = redact_sensitive_value(result)
        if error:
            entry["error"] = str(error)[:500]
        history.append(entry)
        metadata["delivery_history"] = history[-10:]
        return metadata

    @staticmethod
    def summarize_outbox_lifecycle(events: list[dict[str, Any]]) -> dict[str, Any]:
        effect_type_counts: dict[str, int] = {}
        status_counts: dict[str, int] = {}
        delivery_outcome_counts: dict[str, int] = {}
        active_count = 0
        terminal_count = 0
        for event in events:
            effect_type = str(event.get("effect_type") or "unknown")
            status = str(event.get("status") or "unknown")
            effect_type_counts[effect_type] = effect_type_counts.get(effect_type, 0) + 1
            status_counts[status] = status_counts.get(status, 0) + 1
            outcome = infer_delivery_outcome(
                status=status,
                metadata=dict(event.get("metadata") or {}),
                error=str(event.get("error") or ""),
            )
            kind = str(outcome.get("kind") or "")
            if kind:
                delivery_outcome_counts[kind] = delivery_outcome_counts.get(kind, 0) + 1
            if status in OUTBOX_ACTIVE_STATUSES:
                active_count += 1
            if status in OUTBOX_TERMINAL_STATUSES:
                terminal_count += 1
        return {
            "effect_type_counts": effect_type_counts,
            "status_counts": status_counts,
            "delivery_outcome_counts": delivery_outcome_counts,
            "active_count": active_count,
            "terminal_count": terminal_count,
        }

    @classmethod
    def enrich_outbox_event_for_observer(cls, event: dict[str, Any]) -> dict[str, Any]:
        item = dict(event or {})
        metadata = dict(item.get("metadata") or {})
        sanitized_metadata = redact_sensitive_value(metadata)
        item["effect"] = describe_outbox_effect_type(str(item.get("effect_type") or ""))
        item["payload"] = redact_sensitive_value(dict(item.get("payload") or {}))
        item["metadata"] = sanitized_metadata
        item["lifecycle"] = {
            "active": str(item.get("status") or "") in OUTBOX_ACTIVE_STATUSES,
            "terminal": str(item.get("status") or "") in OUTBOX_TERMINAL_STATUSES,
            "terminal_kind": (
                "success"
                if str(item.get("status") or "") in OUTBOX_SUCCESS_STATUSES
                else "failure"
                if str(item.get("status") or "") in OUTBOX_FAILURE_STATUSES
                else "abandoned"
                if str(item.get("status") or "") in OUTBOX_ABANDONED_STATUSES
                else "active"
            ),
            "next_attempt_at_ms": item.get("next_attempt_at_ms"),
            "expires_at_ms": item.get("expires_at_ms"),
            "terminal_at_ms": item.get("terminal_at_ms"),
            "delivery_outcome": infer_delivery_outcome(
                status=str(item.get("status") or ""),
                metadata=metadata,
                error=str(item.get("error") or ""),
            ),
            "last_delivery_result": redact_sensitive_value(metadata.get("delivery_result") or metadata.get("last_delivery_result") or {}),
            "delivery_history": redact_sensitive_value(list(metadata.get("delivery_history") or [])),
        }
        return item

    def build_task_postmortem_view(self, task_id: str) -> dict[str, Any] | None:
        task_view = self.read_task_view(task_id)
        if not task_view:
            return None
        outbox_events = [self.enrich_outbox_event_for_observer(event) for event in self.materialize_outbox_events_for_task(task_id)]
        summary = dict(task_view.get("summary") or {})
        conductor = dict(summary.get("conductor") or {})
        learning = dict((((task_view.get("task") or {}).get("metadata") or {}).get("learning") or {}))
        postmortem = {
            "task": task_view.get("task"),
            "summary": summary,
            "candidate": self.build_resume_candidate(task_id),
            "conductor": conductor,
            "learning": learning,
            "outbox": {
                "events": outbox_events,
                "lifecycle": self.summarize_outbox_lifecycle(outbox_events),
            },
            "checked_at_ms": _now_ms(),
        }
        return self._sanitize_export_value(postmortem)

    def build_operator_queue_item(
        self,
        task: dict[str, Any],
        *,
        candidate: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        enriched = self.enrich_task_for_observer(task, candidate=candidate) or task
        recovery = ((enriched.get("metadata") or {}).get("recovery") or {}) if isinstance(enriched, dict) else {}
        resume_context = dict(enriched.get("resume_context") or {}) if isinstance(enriched, dict) else {}
        queued_at_ms = int(
            recovery.get("requested_at_ms")
            or recovery.get("detected_at_ms")
            or enriched.get("updated_at_ms")
            or 0
        )
        channel = str(resume_context.get("channel") or enriched.get("channel") or "")
        chat_id = str(resume_context.get("chat_id") or "")
        route = f"{channel}:{chat_id}" if channel and chat_id else str(enriched.get("session_key") or "")
        queue = {
            "queued_at_ms": queued_at_ms,
            "source": str(recovery.get("source") or ""),
            "reason": str(recovery.get("reason") or enriched.get("error") or ""),
            "manual_review_required": bool(recovery.get("manual_review_required")),
            "recommended_action": str((candidate or {}).get("recommended_action") or ""),
            "safe_to_execute": bool((candidate or {}).get("safe_to_execute")),
            "failed_outbox_count": int((candidate or {}).get("failed_outbox_count") or 0),
            "last_successful_step": str(enriched.get("last_successful_step") or ""),
            "route": route,
        }
        item = dict(enriched)
        item["queue"] = queue
        item["progress_read_model"] = self._build_progress_read_model(
            task,
            display_state=dict(enriched.get("display_state") or {}),
            verification=dict(enriched.get("verification") or {}),
            outbox_lifecycle=dict(enriched.get("outbox_lifecycle") or {}),
            conductor=dict(((enriched.get("metadata") or {}).get("conductor") or {})),
            candidate=candidate,
            steps=[],
        )
        return item

    def list_operator_queue_view(
        self,
        *,
        limit: int = 50,
        manual_review_only: bool = False,
    ) -> list[dict[str, Any]]:
        all_tasks = self.list_recovery_tasks(limit=500, manual_review_only=manual_review_only)
        queue_items = [self.build_operator_queue_item(task) for task in all_tasks]
        queue_items.sort(key=lambda task: int(((task.get("queue") or {}).get("queued_at_ms") or task.get("updated_at_ms") or 0)), reverse=True)
        visible: list[dict[str, Any]] = []
        for task in queue_items[:max(1, int(limit))]:
            candidate = self.build_resume_candidate(str(task.get("task_id") or ""))
            visible.append(self.build_operator_queue_item(task, candidate=candidate))
        return visible

    def build_task_export_view(self, task_id: str) -> dict[str, Any] | None:
        task_view = self.read_task_view(task_id)
        if not task_view:
            return None
        learning = dict((((task_view.get("task") or {}).get("metadata") or {}).get("learning") or {}))
        export = {
            "task": task_view.get("task"),
            "summary": task_view.get("summary"),
            "steps": task_view.get("steps") or [],
            "outbox_events": [self.enrich_outbox_event_for_observer(event) for event in self.materialize_outbox_events_for_task(task_id)],
            "candidate": self.build_resume_candidate(task_id),
            "conductor": dict(((task_view.get("summary") or {}).get("conductor") or {})),
            "learning": learning,
            "postmortem": self.build_task_postmortem_view(task_id),
            "exported_at_ms": _now_ms(),
        }
        return self._sanitize_export_value(export)

    @staticmethod
    def describe_task_display_state(task: dict[str, Any]) -> dict[str, str]:
        """Return a UI-friendly task state descriptor from ledger state."""
        status = str(task.get("status") or "")
        stage = str(task.get("current_stage") or "")
        recovery = (task.get("metadata") or {}).get("recovery") or {}
        resume_context = dict(task.get("resume_context") or {})

        if str(recovery.get("action") or "") == "resume_dispatch_failed":
            return {
                "key": "resume_dispatch_failed",
                "label": "Resume Dispatch Failed",
                "tone": "error",
                "detail": str(recovery.get("reason") or task.get("error") or "Resume dispatch could not be scheduled."),
            }

        if stage == "resume_requested":
            return {
                "key": "resume_requested",
                "label": "Manual Resume Queued",
                "tone": "warning",
                "detail": "Queued for operator follow-up before any replay resume is attempted.",
            }
        if stage == "resume_queued":
            return {
                "key": "resume_queued",
                "label": "Resume Queued",
                "tone": "accent",
                "detail": "Waiting for the resume executor to pick up this task.",
            }
        if stage == "resume_execute" and status == "running":
            return {
                "key": "resume_running",
                "label": "Resume Running",
                "tone": "accent",
                "detail": "A resumed execution is currently in progress.",
            }
        if recovery.get("manual_review_required"):
            return {
                "key": "manual_review",
                "label": "Needs Review",
                "tone": "warning",
                "detail": str(recovery.get("reason") or "Manual review is required before resume."),
            }
        if not bool(resume_context.get("auto_resume_allowed", True)) and status in {"failed", "waiting"}:
            return {
                "key": "resume_manual_only",
                "label": "Manual Resume Only",
                "tone": "warning",
                "detail": str(
                    resume_context.get("resume_disabled_reason")
                    or "Automatic resume is disabled for this task; operator action is required."
                ),
            }
        if stage == "waiting_outbox" or (status == "waiting" and stage == "waiting_outbox"):
            return {
                "key": "waiting_outbox",
                "label": "Waiting Outbox",
                "tone": "warning",
                "detail": "Delivery or retry is still pending in the outbox.",
            }
        if status == "completed":
            return {
                "key": "completed",
                "label": "Completed",
                "tone": "success",
                "detail": "All known steps and outbox events are settled.",
            }
        if status == "failed":
            return {
                "key": "failed",
                "label": "Failed",
                "tone": "error",
                "detail": str(task.get("error") or "Task execution failed."),
            }
        if status == "verifying":
            return {
                "key": "verifying",
                "label": "Verifying",
                "tone": "accent",
                "detail": "Completion gate is still evaluating the task state.",
            }
        if status == "waiting":
            return {
                "key": "waiting",
                "label": "Waiting",
                "tone": "warning",
                "detail": "Task is blocked on an external dependency or operator action.",
            }
        if status == "running":
            return {
                "key": "running",
                "label": "Running",
                "tone": "accent",
                "detail": "Task execution is currently in progress.",
            }
        if status == "abandoned":
            return {
                "key": "abandoned",
                "label": "Abandoned",
                "tone": "muted",
                "detail": "Task was intentionally abandoned or superseded.",
            }
        return {
            "key": status or "unknown",
            "label": (status or "unknown").replace("_", " ").title(),
            "tone": "muted",
            "detail": "",
        }

    def enrich_task_for_observer(
        self,
        task: dict[str, Any] | None,
        *,
        verification: dict[str, Any] | None = None,
        outbox_lifecycle: dict[str, Any] | None = None,
        candidate: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Add observer-friendly derived fields without mutating stored task data."""
        if not task:
            return None
        enriched = dict(task)
        display_state = self.describe_task_display_state(task)
        metadata = dict((task.get("metadata") or {}))
        conductor = dict(metadata.get("conductor") or {})
        verification_map = (
            dict(verification)
            if isinstance(verification, dict)
            else summarize_verification_metadata((task.get("metadata") or {}).get("verification"))
        )
        outbox_lifecycle_map = dict(outbox_lifecycle) if isinstance(outbox_lifecycle, dict) else {}
        enriched["display_state"] = display_state
        enriched["retrieval"] = dict((task.get("metadata") or {}).get("retrieval") or {})
        enriched["verification"] = verification_map
        enriched["outbox_lifecycle"] = outbox_lifecycle_map
        enriched["session_runtime"] = self._build_session_runtime_summary(task)
        enriched["progress_read_model"] = self._build_progress_read_model(
            task,
            display_state=display_state,
            verification=verification_map,
            outbox_lifecycle=outbox_lifecycle_map,
            conductor=conductor,
            candidate=candidate,
            steps=[],
        )
        return enriched

    def mark_task_stale(
        self,
        task_id: str,
        *,
        source: str,
        reason: str,
        stale_after_ms: int,
    ) -> dict[str, Any] | None:
        """Annotate stale-task recovery state and fail closed when safe to do so."""
        self._require_valid_task_id(task_id)
        task = self.read_task(task_id)
        if not task:
            return None

        previous_status = str(task.get("status") or "")
        previous_stage = str(task.get("current_stage") or "")
        metadata = dict(task.get("metadata") or {})
        detected_at_ms = _now_ms()
        metadata["recovery"] = {
            "source": source,
            "reason": reason[:500],
            "detected_at_ms": detected_at_ms,
            "stale_after_ms": stale_after_ms,
            "previous_status": previous_status,
            "previous_stage": previous_stage,
            "action": "mark_failed" if previous_status in {"running", "verifying"} else "manual_review",
            "manual_review_required": previous_status == "waiting",
        }
        self._append_recovery_history(
            metadata,
            source=source,
            action=str(metadata["recovery"]["action"]),
            reason=reason,
            details={"stale_after_ms": stale_after_ms, "previous_status": previous_status, "previous_stage": previous_stage},
            at_ms=detected_at_ms,
        )

        updates: dict[str, Any] = {"metadata": metadata}
        if previous_status in {"running", "verifying"}:
            updates.update(
                status="failed",
                current_stage="stale_recovery",
                error=reason[:500],
            )

        self.update_task(task_id, **updates)
        return self.read_task(task_id)

    def mark_tasks_for_process_restart(
        self,
        *,
        source: str,
        reason: str,
        statuses: tuple[str, ...] = ("running", "verifying", "waiting"),
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Annotate active tasks before a hard process restart."""
        marked: list[dict[str, Any]] = []
        for status in statuses:
            for task in self.list_tasks(limit=limit, status=status):
                task_id = str(task.get("task_id") or "")
                if not task_id:
                    continue
                metadata = dict(task.get("metadata") or {})
                recovery = dict(metadata.get("recovery") or {})
                detected_at_ms = _now_ms()
                recovery.update({
                    "source": source,
                    "reason": reason[:500],
                    "detected_at_ms": detected_at_ms,
                    "previous_status": str(task.get("status") or ""),
                    "previous_stage": str(task.get("current_stage") or ""),
                    "action": "process_restart_review" if status == "waiting" else "mark_failed",
                    "manual_review_required": status == "waiting",
                })
                metadata["recovery"] = recovery
                self._append_recovery_history(
                    metadata,
                    source=source,
                    action=str(recovery["action"]),
                    reason=reason,
                    details={"previous_status": recovery["previous_status"], "previous_stage": recovery["previous_stage"]},
                    at_ms=detected_at_ms,
                )
                updates: dict[str, Any] = {"metadata": metadata}
                if status in {"running", "verifying"}:
                    updates.update(status="failed", current_stage="hard_recovery", error=reason[:500])
                self.update_task(task_id, **updates)
                updated = self.read_task(task_id)
                if updated:
                    marked.append(updated)
        return marked

    def read_task_view(self, task_id: str) -> dict[str, Any] | None:
        """Return task + materialized steps + summary for observer UIs."""
        task = self.read_task(task_id)
        if not task:
            return None

        steps = self.materialize_steps(task_id)
        display_state = self.describe_task_display_state(task)
        status_counts: dict[str, int] = {}
        for step in steps:
            status = str(step.get("status") or "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1

        outbox = self.materialize_outbox_events_for_task(task_id)
        outbox_lifecycle = self.summarize_outbox_lifecycle(outbox)
        metadata = dict(task.get("metadata") or {})
        conductor = dict(metadata.get("conductor") or {})
        verification = summarize_verification_metadata(metadata.get("verification"), steps=steps)
        candidate = self.build_resume_candidate(task_id)
        progress_read_model = self._build_progress_read_model(
            task,
            display_state=display_state,
            verification=verification,
            outbox_lifecycle=outbox_lifecycle,
            conductor=conductor,
            candidate=candidate,
            steps=steps,
        )

        return {
            "task": self.enrich_task_for_observer(task, verification=verification, outbox_lifecycle=outbox_lifecycle, candidate=candidate),
            "steps": steps,
            "summary": {
                "step_count": len(steps),
                "status_counts": status_counts,
                "last_successful_step": task.get("last_successful_step"),
                "resume_from_step": task.get("resume_from_step"),
                "current_stage": task.get("current_stage"),
                "display_state": display_state,
                "outbox_count": len(outbox),
                "outbox_status_counts": outbox_lifecycle["status_counts"],
                "outbox_effect_type_counts": outbox_lifecycle["effect_type_counts"],
                "outbox_delivery_outcome_counts": outbox_lifecycle["delivery_outcome_counts"],
                "outbox_terminal_count": outbox_lifecycle["terminal_count"],
                "outbox_active_count": outbox_lifecycle["active_count"],
                "completion_gate": task.get("completion_gate"),
                "recovery": metadata.get("recovery"),
                "recovery_history": list(metadata.get("recovery_history") or []),
                "recovery_history_count": len(metadata.get("recovery_history") or []),
                "retrieval": dict(metadata.get("retrieval") or {}),
                "conductor": conductor,
                "verification": verification,
                "session_runtime": self._build_session_runtime_summary(task),
                "progress_read_model": progress_read_model,
            },
        }

    def infer_resume_from_step(self, task_id: str) -> str | None:
        """Infer the safest step boundary to resume from for a task."""
        self._require_valid_task_id(task_id)
        steps = self.materialize_steps(task_id)
        for status in ("waiting_outbox", "failed", "waiting", "retrying", "running", "pending"):
            for step in reversed(steps):
                if str(step.get("status") or "") == status:
                    return str(step.get("step_id") or "")
        return None

    def request_task_resume(
        self,
        task_id: str,
        *,
        source: str,
    ) -> dict[str, Any] | None:
        """Mark a task as awaiting resume from the inferred step boundary."""
        self._require_valid_task_id(task_id)
        task = self.read_task(task_id)
        if not task:
            return None

        resume_from_step = self.infer_resume_from_step(task_id)
        metadata = dict(task.get("metadata") or {})
        recovery = dict(metadata.get("recovery") or {})
        now = _now_ms()
        recovery.update({
            "source": source,
            "action": "resume_requested",
            "manual_review_required": False,
            "requested_at_ms": now,
        })
        metadata["recovery"] = recovery
        self._append_recovery_history(
            metadata,
            source=source,
            action="resume_requested",
            reason=f"resume requested from {resume_from_step or 'task boundary'}",
            details={"resume_from_step": resume_from_step or "", "previous_status": str(task.get('status') or "")},
            at_ms=now,
        )
        self.update_task(
            task_id,
            status="waiting",
            current_stage="resume_requested",
            resume_from_step=resume_from_step,
            metadata=metadata,
            error=None,
        )
        return self.read_task(task_id)

    def build_resume_candidate(self, task_id: str) -> dict[str, Any] | None:
        """Describe the safest next recovery action for a task."""
        self._require_valid_task_id(task_id)
        task = self.read_task(task_id)
        if not task:
            return None

        steps = self.materialize_steps(task_id)
        outbox_events = self.materialize_outbox_events_for_task(task_id)
        resume_context = dict(task.get("resume_context") or {})
        status = str(task.get("status") or "")
        current_stage = str(task.get("current_stage") or "")
        resume_from_step = str(task.get("resume_from_step") or self.infer_resume_from_step(task_id) or "")
        resume_step = next((step for step in steps if str(step.get("step_id") or "") == resume_from_step), None)
        failed_outbox, expired_outbox, retryable_outbox, open_outbox = self._retryable_outbox_events(outbox_events)
        replayable_failed = [step for step in steps if str(step.get("status") or "") == "failed" and step.get("replayable", True)]
        non_replayable_failed = [step for step in steps if str(step.get("status") or "") == "failed" and not step.get("replayable", True)]

        recommended_action = "manual_resume"
        safe_to_execute = False
        reason = "manual intervention required"
        if status in {"completed", "abandoned"}:
            recommended_action = "noop"
            safe_to_execute = False
            reason = "task already settled"
        elif retryable_outbox:
            recommended_action = "retry_outbox"
            safe_to_execute = True
            reason = self._build_retry_outbox_reason(
                failed_count=len(failed_outbox),
                expired_count=len(expired_outbox),
            )
        elif non_replayable_failed:
            recommended_action = "manual_resume"
            safe_to_execute = False
            reason = f"{len(non_replayable_failed)} failed step(s) have side effects and cannot be replayed automatically"
        elif replayable_failed and not open_outbox:
            if not bool(resume_context.get("auto_resume_allowed", True)):
                recommended_action = "manual_resume"
                safe_to_execute = False
                reason = str(
                    resume_context.get("resume_disabled_reason")
                    or "Automatic resume is disabled for this task; operator action is required."
                )
            else:
                recommended_action = "replay_failed_steps"
                safe_to_execute = True
                reason = (
                    f"{len(replayable_failed)} failed step(s) are replayable and can be resumed safely. "
                    "A dedicated resume executor will supersede those failed steps and continue the task in-place."
                )
        elif not open_outbox and status in {"waiting", "verifying"}:
            recommended_action = "recheck"
            safe_to_execute = True
            reason = "task can be safely rechecked through CompletionGate"
        elif open_outbox:
            recommended_action = "wait_outbox"
            safe_to_execute = False
            reason = "outbox delivery is still in progress"

        return {
            "task_id": task_id,
            "status": status,
            "current_stage": current_stage,
            "resume_from_step": resume_from_step or None,
            "resume_step": dict(resume_step or {}) if resume_step else None,
            "failed_outbox_count": len(failed_outbox),
            "expired_outbox_count": len(expired_outbox),
            "open_outbox_count": len(open_outbox),
            "replayable_failed_count": len(replayable_failed),
            "non_replayable_failed_count": len(non_replayable_failed),
            "recommended_action": recommended_action,
            "safe_to_execute": safe_to_execute,
            "reason": reason,
        }

    def execute_safe_resume(
        self,
        task_id: str,
        *,
        source: str,
    ) -> dict[str, Any] | None:
        """Execute the current safe recovery action when one exists."""
        candidate = self.build_resume_candidate(task_id)
        if not candidate:
            return None
        action = str(candidate.get("recommended_action") or "")
        if not candidate.get("safe_to_execute"):
            raise ValueError(str(candidate.get("reason") or "manual intervention required"))

        if action == "retry_outbox":
            return self._execute_retry_outbox_recovery(
                task_id,
                source=source,
                failed_count=int(candidate.get("failed_outbox_count") or 0),
                expired_count=int(candidate.get("expired_outbox_count") or 0),
            )

        if action == "replay_failed_steps":
            raise ValueError("replay_failed_steps is not executable until a dedicated resume executor is wired")

        if action == "recheck":
            from lemonclaw.ledger.completion_gate import finalize_task

            result = finalize_task(self, task_id)
            task = self.read_task(task_id)
            if task:
                metadata = dict(task.get("metadata") or {})
                self._append_recovery_history(
                    metadata,
                    source=source,
                    action="safe_resume_execute",
                    reason=str((result.to_dict() if result else {}).get("reason") or ""),
                    details={"task_id": task_id, "mode": "recheck"},
                )
                self.update_task(task_id, metadata=metadata)
            return self.build_resume_candidate(task_id)

        raise ValueError(f"unsupported safe resume action: {action}")

    def materialize_outbox_events_for_task(self, task_id: str) -> list[dict[str, Any]]:
        self._require_valid_task_id(task_id)
        return [event for event in self.materialize_outbox_events() if event.get("task_id") == task_id]

    def list_outbox_events(
        self,
        *,
        limit: int = 50,
        status: str | None = None,
        task_id: str | None = None,
    ) -> list[dict[str, Any]]:
        events = self.materialize_outbox_events()
        if status:
            events = [event for event in events if event.get("status") == status]
        if task_id:
            events = [event for event in events if event.get("task_id") == task_id]
        return events[:max(1, int(limit))]

    def claim_due_outbox_events(
        self,
        *,
        limit: int = 20,
        now_ms: int | None = None,
        claim_owner: str = "outbox_dispatcher",
    ) -> list[dict[str, Any]]:
        """Claim due pending/retrying outbox events for delivery.

        `attempts` counts total delivery attempts, so it increments when an
        event is claimed for a real send attempt, not when it is rescheduled.
        """
        with self._outbox_lock:
            now = now_ms if now_ms is not None else _now_ms()
            due: list[dict[str, Any]] = []
            for event in self._materialize_outbox_events_unlocked():
                status = str(event.get("status") or "")
                if status not in {"pending", "retrying"}:
                    continue
                next_attempt = event.get("next_attempt_at_ms")
                if next_attempt is not None and int(next_attempt) > now:
                    continue
                due.append(event)

            due.sort(key=lambda item: (
                int(item.get("next_attempt_at_ms") or item.get("created_at_ms") or 0),
                int(item.get("updated_at_ms") or 0),
            ))

            claimed: list[dict[str, Any]] = []
            for event in due[:max(1, int(limit))]:
                metadata = dict(event.get("metadata") or {})
                metadata["claimed_by"] = claim_owner
                metadata["claimed_at_ms"] = now
                updated = self._update_outbox_event_unlocked(
                    str(event["event_id"]),
                    status="claimed",
                    attempts=int(event.get("attempts") or 0) + 1,
                    next_attempt_at_ms=None,
                    error=None,
                    metadata=metadata,
                )
                if updated:
                    claimed.append(updated)
            return claimed

    def mark_outbox_sent(
        self,
        event_id: str,
        *,
        result: dict[str, Any] | None = None,
        source: str = "dispatcher",
    ) -> dict[str, Any] | None:
        """Mark a claimed outbox event as accepted by the target delivery adapter."""
        self._require_valid_outbox_id(event_id)
        current = self.read_outbox_event(event_id)
        if not current:
            return None
        now = _now_ms()
        metadata = dict(current.get("metadata") or {})
        metadata["sent_at_ms"] = now
        if result is not None:
            metadata["delivery_result"] = result
            metadata["last_delivery_result"] = result
        delivery_state = str((result or {}).get("delivery_state") or "delivered")
        metadata["terminal"] = True
        metadata["terminal_reason"] = delivery_state
        metadata["terminal_source"] = source
        self._append_outbox_history(
            metadata,
            action=delivery_state,
            status="sent",
            at_ms=now,
            result=result,
            source=source,
        )
        return self.update_outbox_event(
            event_id,
            status="sent",
            next_attempt_at_ms=None,
            terminal_at_ms=now,
            error=None,
            metadata=metadata,
        )

    def mark_outbox_retry(
        self,
        event_id: str,
        *,
        error: str,
        retry_at_ms: int,
        max_attempts: int | None = None,
        result: dict[str, Any] | None = None,
        source: str = "dispatcher",
    ) -> dict[str, Any] | None:
        """Reschedule an outbox event or mark it terminally failed.

        `max_attempts` is the maximum total delivery attempts, not "retries
        after the first attempt". Once the current claimed attempt reaches the
        cap, the event becomes terminally failed.
        """
        self._require_valid_outbox_id(event_id)
        current = self.read_outbox_event(event_id)
        if not current:
            return None

        now = _now_ms()
        attempts = int(current.get("attempts") or 0)
        terminal = bool(max_attempts and max_attempts > 0 and attempts >= max_attempts)
        metadata = dict(current.get("metadata") or {})
        metadata["last_error_at_ms"] = now
        metadata["last_claimed_by"] = metadata.get("claimed_by")
        if result is not None:
            metadata["last_delivery_result"] = result
        if terminal:
            metadata["terminal"] = True
            metadata["terminal_reason"] = "retry budget exhausted"
            metadata["terminal_source"] = source
        self._append_outbox_history(
            metadata,
            action="expired" if terminal else "retry_scheduled",
            status="expired" if terminal else "retrying",
            at_ms=now,
            result=result,
            error=error,
            source=source,
        )

        return self.update_outbox_event(
            event_id,
            status="expired" if terminal else "retrying",
            next_attempt_at_ms=None if terminal else int(retry_at_ms),
            terminal_at_ms=now if terminal else None,
            error=error[:500],
            metadata=metadata,
        )

    def mark_outbox_failed(
        self,
        event_id: str,
        *,
        error: str,
        result: dict[str, Any] | None = None,
        source: str = "dispatcher",
    ) -> dict[str, Any] | None:
        """Mark an outbox event as terminally failed without retry."""
        self._require_valid_outbox_id(event_id)
        current = self.read_outbox_event(event_id)
        if not current:
            return None

        now = _now_ms()
        metadata = dict(current.get("metadata") or {})
        metadata["last_error_at_ms"] = now
        metadata["last_claimed_by"] = metadata.get("claimed_by")
        metadata["terminal"] = True
        metadata["terminal_reason"] = error[:500]
        metadata["terminal_source"] = source
        if result is not None:
            metadata["last_delivery_result"] = result
        self._append_outbox_history(
            metadata,
            action="failed",
            status="failed",
            at_ms=now,
            result=result,
            error=error,
            source=source,
        )

        return self.update_outbox_event(
            event_id,
            status="failed",
            next_attempt_at_ms=None,
            terminal_at_ms=now,
            error=error[:500],
            metadata=metadata,
        )

    def request_outbox_retry(
        self,
        event_id: str,
        *,
        source: str,
        delay_ms: int = 0,
    ) -> dict[str, Any] | None:
        """Manually reschedule an outbox event and clear manual-review state."""
        self._require_valid_outbox_id(event_id)
        current = self.read_outbox_event(event_id)
        if not current:
            return None

        status = str(current.get("status") or "")
        if status in {"sent", "abandoned", "compensated"}:
            raise ValueError("cannot retry a sent outbox event")

        now = _now_ms()
        metadata = dict(current.get("metadata") or {})
        last_manual_retry = int(metadata.get("manual_retry_requested_at_ms") or 0)
        if (
            status in {"pending", "retrying", "claimed"}
            and last_manual_retry
            and (now - last_manual_retry) < _OUTBOX_MANUAL_RETRY_DEBOUNCE_MS
        ):
            return current
        metadata.pop("terminal", None)
        metadata.pop("terminal_reason", None)
        metadata.pop("terminal_source", None)
        metadata["manual_retry_requested_at_ms"] = now
        metadata["manual_retry_source"] = source
        self._append_outbox_history(
            metadata,
            action="manual_retry_requested",
            status="retrying" if int(current.get("attempts") or 0) > 0 else "pending",
            at_ms=now,
            source=source,
        )

        updated = self.update_outbox_event(
            event_id,
            status="retrying" if int(current.get("attempts") or 0) > 0 else "pending",
            next_attempt_at_ms=now + max(0, int(delay_ms)),
            expires_at_ms=None if int(current.get("expires_at_ms") or 0) <= now else current.get("expires_at_ms"),
            terminal_at_ms=None,
            error=None,
            metadata=metadata,
        )

        task_id = str(current.get("task_id") or "")
        if updated and task_id and self.is_valid_task_id(task_id):
            task = self.read_task(task_id)
            if task:
                task_metadata = dict(task.get("metadata") or {})
                recovery = dict(task_metadata.get("recovery") or {})
                recovery["action"] = "manual_retry_requested"
                recovery["manual_review_required"] = False
                recovery["requested_at_ms"] = now
                recovery["source"] = source
                task_metadata["recovery"] = recovery
                self._append_recovery_history(
                    task_metadata,
                    source=source,
                    action="manual_retry_requested",
                    reason="manual outbox retry requested",
                    details={"event_id": event_id, "status": status},
                    at_ms=now,
                )
                self.update_task(
                    task_id,
                    status="waiting",
                    current_stage="waiting_outbox",
                    error=None,
                    metadata=task_metadata,
                )
            step_id = str(current.get("step_id") or "")
            if step_id and self.is_valid_step_id(step_id):
                self.update_step_state(
                    task_id,
                    step_id,
                    status="waiting_outbox",
                    error=None,
                )
        return updated

    def abandon_outbox_event(
        self,
        event_id: str,
        *,
        source: str,
        reason: str,
    ) -> dict[str, Any] | None:
        self._require_valid_outbox_id(event_id)
        current = self.read_outbox_event(event_id)
        if not current:
            return None

        now = _now_ms()
        metadata = dict(current.get("metadata") or {})
        metadata["terminal"] = True
        metadata["terminal_reason"] = reason[:500]
        metadata["terminal_source"] = source
        self._append_outbox_history(
            metadata,
            action="abandoned",
            status="abandoned",
            at_ms=now,
            error=reason,
            source=source,
        )
        updated = self.update_outbox_event(
            event_id,
            status="abandoned",
            next_attempt_at_ms=None,
            terminal_at_ms=now,
            error=reason[:500],
            metadata=metadata,
        )
        task_id = str(current.get("task_id") or "")
        step_id = str(current.get("step_id") or "")
        if task_id and self.is_valid_task_id(task_id):
            if step_id and self.is_valid_step_id(step_id):
                self.update_step_state(task_id, step_id, status="abandoned", error=reason[:500])
            from lemonclaw.ledger.completion_gate import finalize_task

            finalize_task(self, task_id)
        return updated

    def expire_due_outbox_events(
        self,
        *,
        now_ms: int | None = None,
        source: str = "retention",
    ) -> list[dict[str, Any]]:
        now = int(now_ms if now_ms is not None else _now_ms())
        expired: list[dict[str, Any]] = []
        for event in self.materialize_outbox_events():
            status = str(event.get("status") or "")
            expires_at_ms = int(event.get("expires_at_ms") or 0)
            if status not in OUTBOX_ACTIVE_STATUSES or expires_at_ms <= 0 or expires_at_ms > now:
                continue
            event_id = str(event.get("event_id") or "")
            if not event_id:
                continue
            metadata = dict(event.get("metadata") or {})
            metadata["terminal"] = True
            metadata["terminal_reason"] = "expired"
            metadata["terminal_source"] = source
            self._append_outbox_history(
                metadata,
                action="expired",
                status="expired",
                at_ms=now,
                error="expired by retention policy",
                source=source,
            )
            updated = self.update_outbox_event(
                event_id,
                status="expired",
                next_attempt_at_ms=None,
                terminal_at_ms=now,
                error="expired by retention policy",
                metadata=metadata,
            )
            if updated:
                expired.append(updated)
                task_id = str(event.get("task_id") or "")
                step_id = str(event.get("step_id") or "")
                if task_id and self.is_valid_task_id(task_id):
                    if step_id and self.is_valid_step_id(step_id):
                        self.update_step_state(task_id, step_id, status="failed", error="outbox expired")
                    from lemonclaw.ledger.completion_gate import finalize_task

                    finalize_task(self, task_id)
        return expired

    def prepare_replay_failed_steps(
        self,
        task_id: str,
        *,
        source: str,
    ) -> dict[str, Any] | None:
        """Supersede replayable failed steps before a real resume execution."""
        self._require_valid_task_id(task_id)
        candidate = self.build_resume_candidate(task_id)
        if not candidate:
            return None
        if str(candidate.get("recommended_action") or "") != "replay_failed_steps" or not candidate.get("safe_to_execute"):
            raise ValueError(str(candidate.get("reason") or "manual intervention required"))

        steps = self.materialize_steps(task_id)
        superseded_steps: list[dict[str, Any]] = []
        for step in steps:
            if str(step.get("status") or "") != "failed":
                continue
            if not step.get("replayable", True):
                continue
            step_id = str(step.get("step_id") or "")
            if not step_id:
                continue
            updated = self.update_step_state(
                task_id,
                step_id,
                status="abandoned",
                error="superseded by replay resume",
            )
            if updated:
                superseded_steps.append({
                    "step_id": step_id,
                    "name": str(step.get("name") or ""),
                    "error": str(step.get("error") or ""),
                })

        if not superseded_steps:
            raise ValueError("no replayable failed steps remain to resume")

        task = self.read_task(task_id)
        if not task:
            return None

        now = _now_ms()
        metadata = dict(task.get("metadata") or {})
        recovery = dict(metadata.get("recovery") or {})
        recovery.update({
            "source": source,
            "action": "resume_execute_requested",
            "manual_review_required": False,
            "requested_at_ms": now,
        })
        metadata["recovery"] = recovery
        self._append_recovery_history(
            metadata,
            source=source,
            action="resume_execute_requested",
            reason=f"resume execution requested for {len(superseded_steps)} replayable failed step(s)",
            details={
                "task_id": task_id,
                "mode": "replay_failed_steps",
                "resume_from_step": str(candidate.get("resume_from_step") or ""),
                "superseded_steps": [step["step_id"] for step in superseded_steps[:20]],
            },
            at_ms=now,
        )
        self.update_task(
            task_id,
            status="running",
            current_stage="resume_queued",
            error=None,
            metadata=metadata,
        )
        return {
            "task_id": task_id,
            "resume_from_step": candidate.get("resume_from_step"),
            "superseded_steps": superseded_steps,
            "task": self.read_task(task_id),
        }

    def rollback_prepared_replay_resume(
        self,
        task_id: str,
        *,
        source: str,
        reason: str,
        superseded_steps: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        """Rollback a prepared replay resume when dispatch could not be scheduled."""
        self._require_valid_task_id(task_id)
        restored_steps: list[str] = []
        for step in list(superseded_steps or []):
            step_id = str(step.get("step_id") or "")
            if not step_id:
                continue
            updated = self.update_step_state(
                task_id,
                step_id,
                status="failed",
                error=str(step.get("error") or "") or "replay resume rollback",
            )
            if updated:
                restored_steps.append(step_id)

        task = self.read_task(task_id)
        if not task:
            return None

        metadata = dict(task.get("metadata") or {})
        recovery = dict(metadata.get("recovery") or {})
        recovery.update({
            "source": source,
            "action": "resume_dispatch_failed",
            "manual_review_required": False,
            "reason": reason[:500],
        })
        metadata["recovery"] = recovery
        self._append_recovery_history(
            metadata,
            source=source,
            action="resume_dispatch_failed",
            reason=reason,
            details={"task_id": task_id, "restored_steps": restored_steps[:20]},
        )
        self.update_task(
            task_id,
            status="failed",
            current_stage="error",
            error=reason[:500],
            metadata=metadata,
        )
        return self.read_task(task_id)

    @staticmethod
    def is_valid_task_id(task_id: str) -> bool:
        return bool(_SAFE_TASK_ID.match(task_id))

    @staticmethod
    def now_ms() -> int:
        return _now_ms()

    def _require_valid_task_id(self, task_id: str) -> None:
        if not self.is_valid_task_id(task_id):
            raise ValueError("invalid task_id")

    @staticmethod
    def is_valid_outbox_id(event_id: str) -> bool:
        return bool(_SAFE_OUTBOX_ID.match(event_id))

    def _require_valid_outbox_id(self, event_id: str) -> None:
        if not self.is_valid_outbox_id(event_id):
            raise ValueError("invalid event_id")

    @staticmethod
    def is_valid_step_id(step_id: str) -> bool:
        return bool(_SAFE_STEP_ID.match(step_id))

    def _require_valid_step_id(self, step_id: str) -> None:
        if not self.is_valid_step_id(step_id):
            raise ValueError("invalid step_id")


class JsonTaskLedger(TaskLedgerSharedMixin):
    """Simple JSON-backed task and step ledger."""

    def __init__(self, workspace: Path):
        self._state_dir = workspace / ".lemonclaw-state" / "tasks"
        self._outbox_lock = threading.RLock()

    def ensure_task(
        self,
        *,
        task_id: str,
        session_key: str,
        agent_id: str,
        mode: str,
        channel: str,
        goal: str,
        status: str = "running",
        current_stage: str = "dispatch",
        resume_context: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._require_valid_task_id(task_id)
        path = self._task_path(task_id)
        if path.exists():
            return
        now = _now_ms()
        record = TaskRecord(
            task_id=task_id,
            session_key=session_key,
            agent_id=agent_id,
            mode=mode,
            channel=channel,
            goal=goal,
            status=status,
            current_stage=current_stage,
            created_at_ms=now,
            updated_at_ms=now,
            resume_context=resume_context or {},
            metadata=metadata or {},
        )
        self._write_json(path, record.to_dict())

    def update_task(self, task_id: str, **updates: Any) -> None:
        self._require_valid_task_id(task_id)
        path = self._task_path(task_id)
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        data.update(updates)
        next_updated = _now_ms()
        previous_updated = int(data.get("updated_at_ms") or 0)
        # Preserve a monotonic ordering key for local observer UIs even when
        # multiple updates land in the same millisecond or the system clock shifts.
        data["updated_at_ms"] = max(next_updated, previous_updated + 1)
        self._write_json(path, data)

    def start_step(self, task_id: str, *, step_type: str, name: str, input_summary: str = "", replayable: bool = True) -> StepRecord:
        self._require_valid_task_id(task_id)
        step = StepRecord(
            task_id=task_id,
            step_id=f"step_{uuid.uuid4().hex[:10]}",
            step_type=step_type,
            name=name,
            status="running",
            started_at_ms=_now_ms(),
            input_summary=input_summary[:500],
            replayable=replayable,
        )
        self._append_jsonl(self._steps_path(task_id), step.to_dict())
        return step

    def finish_step(self, step: StepRecord, *, status: str, error: str | None = None) -> None:
        step.status = status
        step.ended_at_ms = _now_ms() if status in {"completed", "failed", "abandoned", "compensated"} else None
        step.error = error
        self._append_jsonl(self._steps_path(step.task_id), step.to_dict())
        if status == "completed":
            self.update_task(step.task_id, last_successful_step=step.name)

    def update_step_state(
        self,
        task_id: str,
        step_id: str,
        *,
        status: str,
        error: str | None = None,
    ) -> dict[str, Any] | None:
        """Append a new state event for an existing step."""
        self._require_valid_task_id(task_id)
        self._require_valid_step_id(step_id)
        current = next((step for step in self.materialize_steps(task_id) if str(step.get("step_id")) == step_id), None)
        if not current:
            return None
        updated = dict(current)
        updated["status"] = status
        updated["error"] = error
        updated["ended_at_ms"] = _now_ms() if status in {"completed", "failed", "abandoned", "compensated"} else None
        self._append_jsonl(self._steps_path(task_id), updated)
        if status == "completed":
            self.update_task(task_id, last_successful_step=str(updated.get("name") or ""))
        return updated

    def task_exists(self, task_id: str) -> bool:
        return self._task_path(task_id).exists()

    def read_task(self, task_id: str) -> dict[str, Any] | None:
        path = self._task_path(task_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def read_steps(self, task_id: str) -> list[dict[str, Any]]:
        path = self._steps_path(task_id)
        if not path.exists():
            return []
        # TODO: stream JSONL when long-running tasks accumulate large step logs.
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def materialize_steps(self, task_id: str) -> list[dict[str, Any]]:
        """Collapse step event history into the latest state per step_id."""
        latest_by_step: dict[str, dict[str, Any]] = {}
        for event in self.read_steps(task_id):
            step_id = str(event.get("step_id", "")).strip()
            if not step_id:
                continue
            latest_by_step[step_id] = event
        return sorted(
            latest_by_step.values(),
            key=lambda item: (
                int(item.get("started_at_ms") or 0),
                int(item.get("ended_at_ms") or 0),
            ),
        )

    def list_tasks(
        self,
        *,
        limit: int = 50,
        session_key: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """List persisted tasks ordered by most recently updated."""
        tasks: list[dict[str, Any]] = []
        if not self._state_dir.exists():
            return tasks

        # TODO: replace the full directory scan with an index / retention policy
        # once task volume grows beyond the current single-instance scale.
        for path in self._state_dir.glob("task_*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if session_key and data.get("session_key") != session_key:
                continue
            if status and data.get("status") != status:
                continue
            tasks.append(data)

        tasks.sort(key=lambda item: int(item.get("updated_at_ms") or 0), reverse=True)
        return tasks[:max(1, int(limit))]

    def list_stale_tasks(
        self,
        *,
        stale_after_ms: int,
        statuses: tuple[str, ...] = ("running", "verifying", "waiting"),
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List tasks that have not been updated within the allowed threshold."""
        if stale_after_ms <= 0 or not self._state_dir.exists():
            return []

        cutoff = _now_ms() - stale_after_ms
        allowed = {status for status in statuses if status}
        tasks: list[dict[str, Any]] = []

        for path in self._state_dir.glob("task_*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if allowed and str(data.get("status") or "") not in allowed:
                continue
            updated_at_ms = int(data.get("updated_at_ms") or 0)
            if updated_at_ms and updated_at_ms <= cutoff:
                tasks.append(data)

        tasks.sort(key=lambda item: int(item.get("updated_at_ms") or 0))
        return tasks[:max(1, int(limit))]

    def list_recovery_tasks(
        self,
        *,
        limit: int = 50,
        manual_review_only: bool = False,
    ) -> list[dict[str, Any]]:
        """List tasks that carry recovery metadata, newest first."""
        tasks: list[dict[str, Any]] = []
        if not self._state_dir.exists():
            return tasks

        for path in self._state_dir.glob("task_*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            recovery = (data.get("metadata") or {}).get("recovery")
            if not isinstance(recovery, dict):
                continue
            if manual_review_only and not recovery.get("manual_review_required"):
                continue
            tasks.append(data)

        tasks.sort(key=lambda item: int(item.get("updated_at_ms") or 0), reverse=True)
        return tasks[:max(1, int(limit))]

    def get_recovery_summary(self) -> dict[str, int]:
        """Return aggregate counters for recovery-oriented observability."""
        tasks = self.list_recovery_tasks(limit=500)
        return self.summarize_recovery_tasks(tasks)

    @staticmethod
    def _append_recovery_history(
        metadata: dict[str, Any],
        *,
        source: str,
        action: str,
        reason: str = "",
        details: dict[str, Any] | None = None,
        at_ms: int | None = None,
    ) -> dict[str, Any]:
        return TaskLedgerSharedMixin._append_recovery_history(
            metadata,
            source=source,
            action=action,
            reason=reason,
            details=details,
            at_ms=at_ms,
        )

    @staticmethod
    def append_recovery_history(
        metadata: dict[str, Any],
        *,
        source: str,
        action: str,
        reason: str = "",
        details: dict[str, Any] | None = None,
        at_ms: int | None = None,
    ) -> dict[str, Any]:
        """Public wrapper for appending structured recovery history entries."""
        return JsonTaskLedger._append_recovery_history(
            metadata,
            source=source,
            action=action,
            reason=reason,
            details=details,
            at_ms=at_ms,
        )

    @staticmethod
    def summarize_recovery_tasks(tasks: list[dict[str, Any]]) -> dict[str, int]:
        """Aggregate counters for a preloaded recovery task list."""
        summary = {
            "tasks_with_recovery": len(tasks),
            "manual_review_required": 0,
            "stale_recovery_failed": 0,
            "waiting_manual_review": 0,
        }
        for task in tasks:
            recovery = (task.get("metadata") or {}).get("recovery") or {}
            status = str(task.get("status") or "")
            stage = str(task.get("current_stage") or "")
            if recovery.get("manual_review_required"):
                summary["manual_review_required"] += 1
            if status == "failed" and stage == "stale_recovery":
                summary["stale_recovery_failed"] += 1
            if status == "waiting" and recovery.get("manual_review_required"):
                summary["waiting_manual_review"] += 1
        return summary

    @staticmethod
    def describe_task_display_state(task: dict[str, Any]) -> dict[str, str]:
        """Return a UI-friendly task state descriptor from ledger state."""
        status = str(task.get("status") or "")
        stage = str(task.get("current_stage") or "")
        recovery = (task.get("metadata") or {}).get("recovery") or {}
        resume_context = dict(task.get("resume_context") or {})

        if str(recovery.get("action") or "") == "resume_dispatch_failed":
            return {
                "key": "resume_dispatch_failed",
                "label": "Resume Dispatch Failed",
                "tone": "error",
                "detail": str(recovery.get("reason") or task.get("error") or "Resume dispatch could not be scheduled."),
            }

        if stage == "resume_requested":
            return {
                "key": "resume_requested",
                "label": "Manual Resume Queued",
                "tone": "warning",
                "detail": "Queued for operator follow-up before any replay resume is attempted.",
            }
        if stage == "resume_queued":
            return {
                "key": "resume_queued",
                "label": "Resume Queued",
                "tone": "accent",
                "detail": "Waiting for the resume executor to pick up this task.",
            }
        if stage == "resume_execute" and status == "running":
            return {
                "key": "resume_running",
                "label": "Resume Running",
                "tone": "accent",
                "detail": "A resumed execution is currently in progress.",
            }
        if recovery.get("manual_review_required"):
            return {
                "key": "manual_review",
                "label": "Needs Review",
                "tone": "warning",
                "detail": str(recovery.get("reason") or "Manual review is required before resume."),
            }
        if not bool(resume_context.get("auto_resume_allowed", True)) and status in {"failed", "waiting"}:
            return {
                "key": "resume_manual_only",
                "label": "Manual Resume Only",
                "tone": "warning",
                "detail": str(
                    resume_context.get("resume_disabled_reason")
                    or "Automatic resume is disabled for this task; operator action is required."
                ),
            }
        if stage == "waiting_outbox" or (status == "waiting" and stage == "waiting_outbox"):
            return {
                "key": "waiting_outbox",
                "label": "Waiting Outbox",
                "tone": "warning",
                "detail": "Delivery or retry is still pending in the outbox.",
            }
        if status == "completed":
            return {
                "key": "completed",
                "label": "Completed",
                "tone": "success",
                "detail": "All known steps and outbox events are settled.",
            }
        if status == "failed":
            return {
                "key": "failed",
                "label": "Failed",
                "tone": "error",
                "detail": str(task.get("error") or "Task execution failed."),
            }
        if status == "verifying":
            return {
                "key": "verifying",
                "label": "Verifying",
                "tone": "accent",
                "detail": "Completion gate is still evaluating the task state.",
            }
        if status == "waiting":
            return {
                "key": "waiting",
                "label": "Waiting",
                "tone": "warning",
                "detail": "Task is blocked on an external dependency or operator action.",
            }
        if status == "running":
            return {
                "key": "running",
                "label": "Running",
                "tone": "accent",
                "detail": "Task execution is currently in progress.",
            }
        if status == "abandoned":
            return {
                "key": "abandoned",
                "label": "Abandoned",
                "tone": "muted",
                "detail": "Task was intentionally abandoned or superseded.",
            }
        return {
            "key": status or "unknown",
            "label": (status or "unknown").replace("_", " ").title(),
            "tone": "muted",
            "detail": "",
        }

    def enrich_task_for_observer(
        self,
        task: dict[str, Any] | None,
        *,
        verification: dict[str, Any] | None = None,
        outbox_lifecycle: dict[str, Any] | None = None,
        candidate: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Add observer-friendly derived fields without mutating stored task data."""
        if not task:
            return None
        enriched = dict(task)
        display_state = self.describe_task_display_state(task)
        metadata = dict((task.get("metadata") or {}))
        conductor = dict(metadata.get("conductor") or {})
        verification_map = (
            dict(verification)
            if isinstance(verification, dict)
            else summarize_verification_metadata((task.get("metadata") or {}).get("verification"))
        )
        outbox_lifecycle_map = dict(outbox_lifecycle) if isinstance(outbox_lifecycle, dict) else {}
        enriched["display_state"] = display_state
        enriched["retrieval"] = dict((task.get("metadata") or {}).get("retrieval") or {})
        enriched["verification"] = verification_map
        enriched["outbox_lifecycle"] = outbox_lifecycle_map
        enriched["session_runtime"] = self._build_session_runtime_summary(task)
        enriched["progress_read_model"] = self._build_progress_read_model(
            task,
            display_state=display_state,
            verification=verification_map,
            outbox_lifecycle=outbox_lifecycle_map,
            conductor=conductor,
            candidate=candidate,
            steps=[],
        )
        return enriched

    def mark_task_stale(
        self,
        task_id: str,
        *,
        source: str,
        reason: str,
        stale_after_ms: int,
    ) -> dict[str, Any] | None:
        """Annotate stale-task recovery state and fail closed when safe to do so."""
        self._require_valid_task_id(task_id)
        task = self.read_task(task_id)
        if not task:
            return None

        previous_status = str(task.get("status") or "")
        previous_stage = str(task.get("current_stage") or "")
        metadata = dict(task.get("metadata") or {})
        detected_at_ms = _now_ms()
        metadata["recovery"] = {
            "source": source,
            "reason": reason[:500],
            "detected_at_ms": detected_at_ms,
            "stale_after_ms": stale_after_ms,
            "previous_status": previous_status,
            "previous_stage": previous_stage,
            "action": "mark_failed" if previous_status in {"running", "verifying"} else "manual_review",
            "manual_review_required": previous_status == "waiting",
        }
        self._append_recovery_history(
            metadata,
            source=source,
            action=str(metadata["recovery"]["action"]),
            reason=reason,
            details={"stale_after_ms": stale_after_ms, "previous_status": previous_status, "previous_stage": previous_stage},
            at_ms=detected_at_ms,
        )

        updates: dict[str, Any] = {"metadata": metadata}
        if previous_status in {"running", "verifying"}:
            updates.update(
                status="failed",
                current_stage="stale_recovery",
                error=reason[:500],
            )

        self.update_task(task_id, **updates)
        return self.read_task(task_id)

    def mark_tasks_for_process_restart(
        self,
        *,
        source: str,
        reason: str,
        statuses: tuple[str, ...] = ("running", "verifying", "waiting"),
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Annotate active tasks before a hard process restart."""
        marked: list[dict[str, Any]] = []
        for status in statuses:
            for task in self.list_tasks(limit=limit, status=status):
                task_id = str(task.get("task_id") or "")
                if not task_id:
                    continue
                metadata = dict(task.get("metadata") or {})
                recovery = dict(metadata.get("recovery") or {})
                detected_at_ms = _now_ms()
                recovery.update({
                    "source": source,
                    "reason": reason[:500],
                    "detected_at_ms": detected_at_ms,
                    "previous_status": str(task.get("status") or ""),
                    "previous_stage": str(task.get("current_stage") or ""),
                    "action": "process_restart_review" if status == "waiting" else "mark_failed",
                    "manual_review_required": status == "waiting",
                })
                metadata["recovery"] = recovery
                self._append_recovery_history(
                    metadata,
                    source=source,
                    action=str(recovery["action"]),
                    reason=reason,
                    details={"previous_status": recovery["previous_status"], "previous_stage": recovery["previous_stage"]},
                    at_ms=detected_at_ms,
                )
                updates: dict[str, Any] = {"metadata": metadata}
                if status in {"running", "verifying"}:
                    updates.update(status="failed", current_stage="hard_recovery", error=reason[:500])
                self.update_task(task_id, **updates)
                updated = self.read_task(task_id)
                if updated:
                    marked.append(updated)
        return marked

    def read_task_view(self, task_id: str) -> dict[str, Any] | None:
        """Return task + materialized steps + summary for observer UIs."""
        return super().read_task_view(task_id)

    def infer_resume_from_step(self, task_id: str) -> str | None:
        """Infer the best step boundary to resume from for a task."""
        return super().infer_resume_from_step(task_id)

    def request_task_resume(
        self,
        task_id: str,
        *,
        source: str,
    ) -> dict[str, Any] | None:
        """Mark a task as awaiting resume from the inferred step boundary."""
        return super().request_task_resume(task_id, source=source)

    def build_resume_candidate(self, task_id: str) -> dict[str, Any] | None:
        """Describe the safest next recovery action for a task."""
        return super().build_resume_candidate(task_id)

    def execute_safe_resume(
        self,
        task_id: str,
        *,
        source: str,
    ) -> dict[str, Any] | None:
        """Execute the current safe recovery action when one exists."""
        return super().execute_safe_resume(task_id, source=source)

    def enqueue_outbox(
        self,
        *,
        task_id: str,
        step_id: str,
        effect_type: str,
        target: str,
        payload: dict[str, Any],
        status: str = "pending",
        attempts: int = 0,
        next_attempt_at_ms: int | None = None,
        expires_at_ms: int | None = None,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # Best-effort durable outbox: the event is persisted before delivery,
        # but delivery itself is still asynchronous and non-transactional.
        self._require_valid_task_id(task_id)
        self._require_valid_step_id(step_id)
        if not is_supported_outbox_effect_type(effect_type):
            raise ValueError("unsupported effect_type")
        with self._outbox_lock:
            now = _now_ms()
            event_metadata = dict(metadata or {})
            event_metadata.setdefault("effect", describe_outbox_effect_type(effect_type))
            event_metadata.setdefault("delivery_history", [])
            event = OutboxEventRecord(
                event_id=f"ob_{uuid.uuid4().hex[:12]}",
                task_id=task_id,
                step_id=step_id,
                effect_type=effect_type,
                target=target,
                payload=payload,
                status=status,
                attempts=attempts,
                created_at_ms=now,
                updated_at_ms=now,
                next_attempt_at_ms=next_attempt_at_ms,
                expires_at_ms=expires_at_ms,
                error=error,
                metadata=event_metadata,
            )
            self._append_jsonl(self._outbox_path(), event.to_dict())
            return event.to_dict()

    def update_outbox_event(self, event_id: str, **updates: Any) -> dict[str, Any] | None:
        self._require_valid_outbox_id(event_id)
        with self._outbox_lock:
            return self._update_outbox_event_unlocked(event_id, **updates)

    def materialize_outbox_events(self) -> list[dict[str, Any]]:
        with self._outbox_lock:
            return self._materialize_outbox_events_unlocked()

    def materialize_outbox_events_for_task(self, task_id: str) -> list[dict[str, Any]]:
        self._require_valid_task_id(task_id)
        return [event for event in self.materialize_outbox_events() if event.get("task_id") == task_id]

    def read_outbox_events(self) -> list[dict[str, Any]]:
        with self._outbox_lock:
            return self._read_outbox_events_unlocked()

    def compact_outbox(
        self,
        *,
        keep_terminal: int = 200,
        min_terminal_age_ms: int = 24 * 60 * 60 * 1000,
        now_ms: int | None = None,
    ) -> dict[str, int]:
        """Rewrite outbox.jsonl with only the latest retained event states."""
        with self._outbox_lock:
            events = self._materialize_outbox_events_unlocked()
            if not events:
                return {"before": 0, "after": 0, "dropped": 0}

            now = now_ms if now_ms is not None else _now_ms()
            cutoff = now - max(0, int(min_terminal_age_ms))
            terminal_statuses = set(OUTBOX_TERMINAL_STATUSES)
            non_terminal = [event for event in events if str(event.get("status") or "") not in terminal_statuses]
            terminal = [event for event in events if str(event.get("status") or "") in terminal_statuses]
            terminal.sort(key=lambda item: int(item.get("updated_at_ms") or 0), reverse=True)
            kept_terminal = [
                event
                for event in terminal
                if int(event.get("updated_at_ms") or 0) >= cutoff
            ]
            kept_ids = {str(e.get("event_id") or "") for e in kept_terminal}
            for event in terminal:
                eid = str(event.get("event_id") or "")
                if eid in kept_ids:
                    continue
                if len(kept_terminal) >= max(0, int(keep_terminal)):
                    break
                kept_terminal.append(event)
                kept_ids.add(eid)
            if len(kept_terminal) > max(0, int(keep_terminal)):
                kept_terminal = kept_terminal[:max(0, int(keep_terminal))]
            kept: list[dict[str, Any]] = non_terminal + kept_terminal

            kept.sort(key=lambda item: (
                int(item.get("created_at_ms") or 0),
                int(item.get("updated_at_ms") or 0),
            ))
            payload = "\n".join(json.dumps(event, ensure_ascii=False) for event in kept)
            path = self._outbox_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".compact.tmp")
            tmp.write_text((payload + "\n") if payload else "", encoding="utf-8")
            tmp.replace(path)
            return {
                "before": len(events),
                "after": len(kept),
                "dropped": max(0, len(events) - len(kept)),
            }

    def list_outbox_events(
        self,
        *,
        limit: int = 50,
        status: str | None = None,
        task_id: str | None = None,
    ) -> list[dict[str, Any]]:
        events = self.materialize_outbox_events()
        if status:
            events = [event for event in events if event.get("status") == status]
        if task_id:
            events = [event for event in events if event.get("task_id") == task_id]
        return events[:max(1, int(limit))]

    def claim_due_outbox_events(
        self,
        *,
        limit: int = 20,
        now_ms: int | None = None,
        claim_owner: str = "outbox_dispatcher",
    ) -> list[dict[str, Any]]:
        """Claim due pending/retrying outbox events for delivery.

        `attempts` counts total delivery attempts, so it increments when an
        event is claimed for a real send attempt, not when it is rescheduled.
        """
        with self._outbox_lock:
            now = now_ms if now_ms is not None else _now_ms()
            due: list[dict[str, Any]] = []
            for event in self._materialize_outbox_events_unlocked():
                status = str(event.get("status") or "")
                if status not in {"pending", "retrying"}:
                    continue
                next_attempt = event.get("next_attempt_at_ms")
                if next_attempt is not None and int(next_attempt) > now:
                    continue
                due.append(event)

            due.sort(key=lambda item: (
                int(item.get("next_attempt_at_ms") or item.get("created_at_ms") or 0),
                int(item.get("updated_at_ms") or 0),
            ))

            claimed: list[dict[str, Any]] = []
            for event in due[:max(1, int(limit))]:
                metadata = dict(event.get("metadata") or {})
                metadata["claimed_by"] = claim_owner
                metadata["claimed_at_ms"] = now
                updated = self._update_outbox_event_unlocked(
                    str(event["event_id"]),
                    status="claimed",
                    attempts=int(event.get("attempts") or 0) + 1,
                    next_attempt_at_ms=None,
                    error=None,
                    metadata=metadata,
                )
                if updated:
                    claimed.append(updated)
            return claimed

    def mark_outbox_sent(
        self,
        event_id: str,
        *,
        result: dict[str, Any] | None = None,
        source: str = "dispatcher",
    ) -> dict[str, Any] | None:
        """Mark a claimed outbox event as accepted by the target delivery adapter."""
        self._require_valid_outbox_id(event_id)
        current = self.read_outbox_event(event_id)
        if not current:
            return None
        now = _now_ms()
        metadata = dict(current.get("metadata") or {})
        metadata["sent_at_ms"] = now
        if result is not None:
            metadata["delivery_result"] = result
            metadata["last_delivery_result"] = result
        delivery_state = str((result or {}).get("delivery_state") or "delivered")
        metadata["terminal"] = True
        metadata["terminal_reason"] = delivery_state
        metadata["terminal_source"] = source
        self._append_outbox_history(
            metadata,
            action=delivery_state,
            status="sent",
            at_ms=now,
            result=result,
            source=source,
        )
        return self.update_outbox_event(
            event_id,
            status="sent",
            next_attempt_at_ms=None,
            terminal_at_ms=now,
            error=None,
            metadata=metadata,
        )

    def mark_outbox_retry(
        self,
        event_id: str,
        *,
        error: str,
        retry_at_ms: int,
        max_attempts: int | None = None,
        result: dict[str, Any] | None = None,
        source: str = "dispatcher",
    ) -> dict[str, Any] | None:
        """Reschedule an outbox event or mark it terminally failed.

        `max_attempts` is the maximum total delivery attempts, not "retries
        after the first attempt". Once the current claimed attempt reaches the
        cap, the event becomes terminally failed.
        """
        self._require_valid_outbox_id(event_id)
        current = self.read_outbox_event(event_id)
        if not current:
            return None

        now = _now_ms()
        attempts = int(current.get("attempts") or 0)
        terminal = bool(max_attempts and max_attempts > 0 and attempts >= max_attempts)
        metadata = dict(current.get("metadata") or {})
        metadata["last_error_at_ms"] = now
        metadata["last_claimed_by"] = metadata.get("claimed_by")
        if result is not None:
            metadata["last_delivery_result"] = result
        if terminal:
            metadata["terminal"] = True
            metadata["terminal_reason"] = "retry budget exhausted"
            metadata["terminal_source"] = source
        self._append_outbox_history(
            metadata,
            action="expired" if terminal else "retry_scheduled",
            status="expired" if terminal else "retrying",
            at_ms=now,
            result=result,
            error=error,
            source=source,
        )

        return self.update_outbox_event(
            event_id,
            status="expired" if terminal else "retrying",
            next_attempt_at_ms=None if terminal else int(retry_at_ms),
            terminal_at_ms=now if terminal else None,
            error=error[:500],
            metadata=metadata,
        )

    def mark_outbox_failed(
        self,
        event_id: str,
        *,
        error: str,
        result: dict[str, Any] | None = None,
        source: str = "dispatcher",
    ) -> dict[str, Any] | None:
        """Mark an outbox event as terminally failed without retry."""
        self._require_valid_outbox_id(event_id)
        current = self.read_outbox_event(event_id)
        if not current:
            return None

        now = _now_ms()
        metadata = dict(current.get("metadata") or {})
        metadata["last_error_at_ms"] = now
        metadata["last_claimed_by"] = metadata.get("claimed_by")
        metadata["terminal"] = True
        metadata["terminal_reason"] = error[:500]
        metadata["terminal_source"] = source
        if result is not None:
            metadata["last_delivery_result"] = result
        self._append_outbox_history(
            metadata,
            action="failed",
            status="failed",
            at_ms=now,
            result=result,
            error=error,
            source=source,
        )

        return self.update_outbox_event(
            event_id,
            status="failed",
            next_attempt_at_ms=None,
            terminal_at_ms=now,
            error=error[:500],
            metadata=metadata,
        )

    def request_outbox_retry(
        self,
        event_id: str,
        *,
        source: str,
        delay_ms: int = 0,
    ) -> dict[str, Any] | None:
        """Manually reschedule an outbox event and clear manual-review state."""
        self._require_valid_outbox_id(event_id)
        current = self.read_outbox_event(event_id)
        if not current:
            return None

        status = str(current.get("status") or "")
        if status in {"sent", "abandoned", "compensated"}:
            raise ValueError("cannot retry a sent outbox event")

        now = _now_ms()
        metadata = dict(current.get("metadata") or {})
        last_manual_retry = int(metadata.get("manual_retry_requested_at_ms") or 0)
        if (
            status in {"pending", "retrying", "claimed"}
            and last_manual_retry
            and (now - last_manual_retry) < _OUTBOX_MANUAL_RETRY_DEBOUNCE_MS
        ):
            return current
        metadata.pop("terminal", None)
        metadata.pop("terminal_reason", None)
        metadata.pop("terminal_source", None)
        metadata["manual_retry_requested_at_ms"] = now
        metadata["manual_retry_source"] = source
        self._append_outbox_history(
            metadata,
            action="manual_retry_requested",
            status="retrying" if int(current.get("attempts") or 0) > 0 else "pending",
            at_ms=now,
            source=source,
        )

        updated = self.update_outbox_event(
            event_id,
            status="retrying" if int(current.get("attempts") or 0) > 0 else "pending",
            next_attempt_at_ms=now + max(0, int(delay_ms)),
            expires_at_ms=None if int(current.get("expires_at_ms") or 0) <= now else current.get("expires_at_ms"),
            terminal_at_ms=None,
            error=None,
            metadata=metadata,
        )

        task_id = str(current.get("task_id") or "")
        if updated and task_id and self.is_valid_task_id(task_id):
            task = self.read_task(task_id)
            if task:
                task_metadata = dict(task.get("metadata") or {})
                recovery = dict(task_metadata.get("recovery") or {})
                recovery["action"] = "manual_retry_requested"
                recovery["manual_review_required"] = False
                recovery["requested_at_ms"] = now
                recovery["source"] = source
                task_metadata["recovery"] = recovery
                self._append_recovery_history(
                    task_metadata,
                    source=source,
                    action="manual_retry_requested",
                    reason="manual outbox retry requested",
                    details={"event_id": event_id, "status": status},
                    at_ms=now,
                )
                self.update_task(
                    task_id,
                    status="waiting",
                    current_stage="waiting_outbox",
                    error=None,
                    metadata=task_metadata,
                )
            step_id = str(current.get("step_id") or "")
            if step_id and self.is_valid_step_id(step_id):
                self.update_step_state(
                    task_id,
                    step_id,
                    status="waiting_outbox",
                    error=None,
                )
        return updated

    def prepare_replay_failed_steps(
        self,
        task_id: str,
        *,
        source: str,
    ) -> dict[str, Any] | None:
        """Supersede replayable failed steps before a real resume execution."""
        self._require_valid_task_id(task_id)
        candidate = self.build_resume_candidate(task_id)
        if not candidate:
            return None
        if str(candidate.get("recommended_action") or "") != "replay_failed_steps" or not candidate.get("safe_to_execute"):
            raise ValueError(str(candidate.get("reason") or "manual intervention required"))

        steps = self.materialize_steps(task_id)
        superseded_steps: list[dict[str, Any]] = []
        for step in steps:
            if str(step.get("status") or "") != "failed":
                continue
            if not step.get("replayable", True):
                continue
            step_id = str(step.get("step_id") or "")
            if not step_id:
                continue
            updated = self.update_step_state(
                task_id,
                step_id,
                status="abandoned",
                error="superseded by replay resume",
            )
            if updated:
                superseded_steps.append({
                    "step_id": step_id,
                    "name": str(step.get("name") or ""),
                    "error": str(step.get("error") or ""),
                })

        if not superseded_steps:
            raise ValueError("no replayable failed steps remain to resume")

        task = self.read_task(task_id)
        if not task:
            return None

        now = _now_ms()
        metadata = dict(task.get("metadata") or {})
        recovery = dict(metadata.get("recovery") or {})
        recovery.update({
            "source": source,
            "action": "resume_execute_requested",
            "manual_review_required": False,
            "requested_at_ms": now,
        })
        metadata["recovery"] = recovery
        self._append_recovery_history(
            metadata,
            source=source,
            action="resume_execute_requested",
            reason=f"resume execution requested for {len(superseded_steps)} replayable failed step(s)",
            details={
                "task_id": task_id,
                "mode": "replay_failed_steps",
                "resume_from_step": str(candidate.get("resume_from_step") or ""),
                "superseded_steps": [step["step_id"] for step in superseded_steps[:20]],
            },
            at_ms=now,
        )
        self.update_task(
            task_id,
            status="running",
            current_stage="resume_queued",
            error=None,
            metadata=metadata,
        )
        return {
            "task_id": task_id,
            "resume_from_step": candidate.get("resume_from_step"),
            "superseded_steps": superseded_steps,
            "task": self.read_task(task_id),
        }

    def rollback_prepared_replay_resume(
        self,
        task_id: str,
        *,
        source: str,
        reason: str,
        superseded_steps: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        """Rollback a prepared replay resume when dispatch could not be scheduled."""
        self._require_valid_task_id(task_id)
        restored_steps: list[str] = []
        for step in list(superseded_steps or []):
            step_id = str(step.get("step_id") or "")
            if not step_id:
                continue
            updated = self.update_step_state(
                task_id,
                step_id,
                status="failed",
                error=str(step.get("error") or "") or "replay resume rollback",
            )
            if updated:
                restored_steps.append(step_id)

        task = self.read_task(task_id)
        if not task:
            return None

        metadata = dict(task.get("metadata") or {})
        recovery = dict(metadata.get("recovery") or {})
        recovery.update({
            "source": source,
            "action": "resume_dispatch_failed",
            "manual_review_required": False,
            "reason": reason[:500],
        })
        metadata["recovery"] = recovery
        self._append_recovery_history(
            metadata,
            source=source,
            action="resume_dispatch_failed",
            reason=reason,
            details={"task_id": task_id, "restored_steps": restored_steps[:20]},
        )
        self.update_task(
            task_id,
            status="failed",
            current_stage="error",
            error=reason[:500],
            metadata=metadata,
        )
        return self.read_task(task_id)

    def read_outbox_event(self, event_id: str) -> dict[str, Any] | None:
        self._require_valid_outbox_id(event_id)
        with self._outbox_lock:
            return self._read_outbox_event_unlocked(event_id)

    @staticmethod
    def is_valid_task_id(task_id: str) -> bool:
        return bool(_SAFE_TASK_ID.match(task_id))

    @staticmethod
    def now_ms() -> int:
        return _now_ms()

    def _require_valid_task_id(self, task_id: str) -> None:
        if not self.is_valid_task_id(task_id):
            raise ValueError("invalid task_id")

    @staticmethod
    def is_valid_outbox_id(event_id: str) -> bool:
        return bool(_SAFE_OUTBOX_ID.match(event_id))

    def _require_valid_outbox_id(self, event_id: str) -> None:
        if not self.is_valid_outbox_id(event_id):
            raise ValueError("invalid event_id")

    @staticmethod
    def is_valid_step_id(step_id: str) -> bool:
        return bool(_SAFE_STEP_ID.match(step_id))

    def _require_valid_step_id(self, step_id: str) -> None:
        if not self.is_valid_step_id(step_id):
            raise ValueError("invalid step_id")

    def _task_path(self, task_id: str) -> Path:
        self._require_valid_task_id(task_id)
        return self._state_dir / f"{task_id}.json"

    def _steps_path(self, task_id: str) -> Path:
        self._require_valid_task_id(task_id)
        return self._state_dir / f"{task_id}.steps.jsonl"

    def _outbox_path(self) -> Path:
        # TODO: split this global append-only log by task_id or add an index /
        # retention policy once outbox volume outgrows the current local scale.
        return self._state_dir / "outbox.jsonl"

    def _read_outbox_events_unlocked(self) -> list[dict[str, Any]]:
        path = self._outbox_path()
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _materialize_outbox_events_unlocked(self) -> list[dict[str, Any]]:
        latest_by_event: dict[str, dict[str, Any]] = {}
        for event in self._read_outbox_events_unlocked():
            event_id = str(event.get("event_id", "")).strip()
            if not event_id:
                continue
            latest_by_event[event_id] = event
        return sorted(
            latest_by_event.values(),
            key=lambda item: int(item.get("updated_at_ms") or 0),
            reverse=True,
        )

    def _read_outbox_event_unlocked(self, event_id: str) -> dict[str, Any] | None:
        latest: dict[str, Any] | None = None
        for event in self._read_outbox_events_unlocked():
            if event.get("event_id") == event_id:
                latest = event
        return latest

    def _update_outbox_event_unlocked(self, event_id: str, **updates: Any) -> dict[str, Any] | None:
        current = self._read_outbox_event_unlocked(event_id)
        if not current:
            return None
        current.update(updates)
        next_updated = _now_ms()
        previous_updated = int(current.get("updated_at_ms") or 0)
        current["updated_at_ms"] = max(next_updated, previous_updated + 1)
        self._append_jsonl(self._outbox_path(), current)
        return current

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    @staticmethod
    def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


class TaskLedger:
    """Facade that selects a concrete ledger backend."""

    _DELEGATED_METHOD_NAMES = (
        "ensure_task",
        "update_task",
        "start_step",
        "finish_step",
        "update_step_state",
        "task_exists",
        "read_task",
        "read_steps",
        "materialize_steps",
        "list_tasks",
        "enrich_task_for_observer",
        "list_stale_tasks",
        "list_recovery_tasks",
        "list_operator_queue_view",
        "get_recovery_summary",
        "mark_task_stale",
        "mark_tasks_for_process_restart",
        "read_task_view",
        "build_task_export_view",
        "infer_resume_from_step",
        "request_task_resume",
        "build_resume_candidate",
        "execute_safe_resume",
        "abandon_outbox_events_for_task",
        "abandon_outbox_events_for_session",
        "enqueue_outbox",
        "update_outbox_event",
        "materialize_outbox_events",
        "materialize_outbox_events_for_task",
        "read_outbox_events",
        "enrich_outbox_event_for_observer",
        "compact_outbox",
        "list_outbox_events",
        "claim_due_outbox_events",
        "reclaim_stale_claimed_outbox_events",
        "mark_outbox_sent",
        "mark_outbox_retry",
        "mark_outbox_failed",
        "request_outbox_retry",
        "abandon_outbox_event",
        "expire_due_outbox_events",
        "build_task_postmortem_view",
        "prepare_replay_failed_steps",
        "rollback_prepared_replay_resume",
        "read_outbox_event",
    )

    def __init__(self, workspace: Path, backend: str = "auto"):
        resolved = self._resolve_backend(workspace, backend)
        if resolved == "sqlite":
            from lemonclaw.ledger.sqlite_store import SQLiteTaskLedger

            self._impl = SQLiteTaskLedger(workspace)
        else:
            self._impl = JsonTaskLedger(workspace)
        self.backend = resolved
        for name in self._DELEGATED_METHOD_NAMES:
            setattr(self, name, getattr(self._impl, name))

    @property
    def impl(self) -> TaskLedgerSharedMixin:
        return self._impl

    @staticmethod
    def _resolve_backend(workspace: Path, backend: str) -> str:
        normalized = str(backend or "auto").strip().lower()
        if normalized not in {"auto", "json", "sqlite"}:
            raise ValueError("invalid ledger backend")
        if normalized != "auto":
            return normalized

        state_dir = workspace / ".lemonclaw-state" / "tasks"
        sqlite_path = state_dir / "ledger.sqlite3"
        if sqlite_path.exists():
            return "sqlite"
        if state_dir.exists():
            has_json_state = any(
                any(state_dir.glob(pattern))
                for pattern in ("task_*.json", "*.steps.jsonl", "outbox.jsonl")
            )
            if has_json_state:
                return "json"
        return "sqlite"

    @staticmethod
    def describe_task_display_state(task: dict[str, Any]) -> dict[str, str]:
        return JsonTaskLedger.describe_task_display_state(task)

    @staticmethod
    def summarize_recovery_tasks(tasks: list[dict[str, Any]]) -> dict[str, int]:
        return JsonTaskLedger.summarize_recovery_tasks(tasks)

    @staticmethod
    def append_recovery_history(
        metadata: dict[str, Any],
        *,
        source: str,
        action: str,
        reason: str = "",
        details: dict[str, Any] | None = None,
        at_ms: int | None = None,
    ) -> dict[str, Any]:
        return JsonTaskLedger.append_recovery_history(
            metadata,
            source=source,
            action=action,
            reason=reason,
            details=details,
            at_ms=at_ms,
        )

    @staticmethod
    def is_valid_task_id(task_id: str) -> bool:
        return JsonTaskLedger.is_valid_task_id(task_id)

    @staticmethod
    def is_valid_outbox_id(event_id: str) -> bool:
        return JsonTaskLedger.is_valid_outbox_id(event_id)

    @staticmethod
    def is_valid_step_id(step_id: str) -> bool:
        return JsonTaskLedger.is_valid_step_id(step_id)

    @staticmethod
    def now_ms() -> int:
        return JsonTaskLedger.now_ms()

    def _task_path(self, task_id: str) -> Path:
        return self._impl._task_path(task_id)

    def _steps_path(self, task_id: str) -> Path:
        return self._impl._steps_path(task_id)

    def _outbox_path(self) -> Path:
        return self._impl._outbox_path()

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        JsonTaskLedger._write_json(path, payload)

    @staticmethod
    def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
        JsonTaskLedger._append_jsonl(path, payload)
