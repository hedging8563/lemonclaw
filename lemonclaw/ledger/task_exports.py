"""Shared task export/bundle/postmortem rendering helpers.

These helpers are intentionally UI-agnostic so WebUI routes and chat-plane
commands can render the same task truth without duplicating formatting logic.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from lemonclaw.ledger.runtime import TaskLedger
    from lemonclaw.triggers import TriggerRuntime


def attach_trigger_context(
    payload: dict[str, Any] | None,
    trigger_runtime: TriggerRuntime | None = None,
) -> dict[str, Any]:
    if not payload:
        return {}
    if trigger_runtime is None:
        return dict(payload)

    task = dict(payload.get("task") or {})
    trigger_meta = dict((task.get("metadata") or {}).get("trigger") or {})
    trigger_id = str(trigger_meta.get("trigger_id") or "")
    if not trigger_id:
        return dict(payload)
    trigger = trigger_runtime.read_trigger(trigger_id)
    if not trigger:
        return dict(payload)
    enriched = dict(payload)
    enriched["trigger"] = trigger
    return enriched


def build_task_bundle(
    ledger: TaskLedger | Any,
    task_id: str,
    *,
    trigger_runtime: TriggerRuntime | None = None,
) -> dict[str, Any] | None:
    export_view = ledger.build_task_export_view(task_id)
    if not export_view:
        return None
    export_view = attach_trigger_context(export_view, trigger_runtime)
    postmortem = ledger.build_task_postmortem_view(task_id) or {}
    postmortem = attach_trigger_context(postmortem, trigger_runtime) if postmortem else {}
    trigger = export_view.get("trigger") or postmortem.get("trigger") or {}
    return {
        "generated_at_ms": int(time.time() * 1000),
        "task": export_view.get("task") or {},
        "summary": export_view.get("summary") or {},
        "candidate": export_view.get("candidate") or {},
        "conductor": export_view.get("conductor") or postmortem.get("conductor") or {},
        "postmortem": postmortem,
        "trigger": trigger,
    }


def append_retrieval_markdown(lines: list[str], retrieval: dict[str, Any] | None) -> None:
    lines.extend(["", "## Retrieval"])
    if not retrieval:
        lines.append("- none")
        return
    lines.extend([
        f"- Strategy: {retrieval.get('strategy') or '—'}",
        f"- Latency: {retrieval.get('latency_ms') if retrieval.get('latency_ms') is not None else '—'}",
        f"- Fallbacks: {retrieval.get('fallback_count') if retrieval.get('fallback_count') is not None else '—'}",
        f"- Hits: cards={retrieval.get('card_count') or 0} · rules={retrieval.get('rule_count') or 0} · knowledge={retrieval.get('knowledge_count') or 0}",
    ])
    hit_sources = [str(item) for item in (retrieval.get("hit_sources") or []) if item]
    if hit_sources:
        lines.append(f"- Hit Sources: {', '.join(hit_sources)}")
    for card in list(retrieval.get("card_hits") or []):
        lines.append(f"- Card: {card.get('name') or '—'} · {card.get('type') or '—'} · {card.get('source') or '—'}")
    for rule in list(retrieval.get("rule_hits") or []):
        lines.append(f"- Rule: {rule.get('trigger') or '—'} · {rule.get('source') or '—'}")
    for item in list(retrieval.get("knowledge_hits") or []):
        page = f" [{item.get('page_label')}]" if item.get("page_label") else ""
        lines.append(f"- Knowledge: {item.get('title') or '—'}{page} · {item.get('result_type') or '—'} · {item.get('source') or '—'}")
    structured = dict(retrieval.get("structured") or {})
    session_summary = str(structured.get("session_summary") or "").strip()
    if session_summary:
        lines.extend(["", "### Session Summary", session_summary])

    fact_slots = list(structured.get("fact_slots") or [])
    if fact_slots:
        lines.append("")
        lines.append("### Fact Slots")
        for item in fact_slots:
            name = str(item.get("name") or "—")
            slot_type = str(item.get("type") or "—")
            summary = str(item.get("summary") or "").strip()
            lines.append(f"- {name} · {slot_type}")
            if summary:
                lines.append(f"  - {summary}")

    retrieval_objects = list(structured.get("retrieval_objects") or [])
    if retrieval_objects:
        lines.append("")
        lines.append("### Retrieval Objects")
        for item in retrieval_objects:
            kind = str(item.get("kind") or "—")
            title = str(item.get("title") or item.get("id") or "—")
            source = str(item.get("source") or "—")
            lines.append(f"- {kind} · {title} · {source}")


def append_conductor_markdown(lines: list[str], conductor: dict[str, Any] | None) -> None:
    lines.extend(["", "## Conductor Chain"])
    if not conductor:
        lines.append("- none")
        return
    planner = dict(conductor.get("planner") or {})
    generator = dict(conductor.get("generator") or {})
    evaluator = dict(conductor.get("evaluator") or {})
    artifacts = dict(conductor.get("artifacts") or {})
    observability = dict(conductor.get("observability") or {})
    lines.extend([
        f"- Planner: {planner.get('summary') or '—'}",
        f"- Complexity: {planner.get('complexity') or '—'}",
        f"- Generator: completed={generator.get('completed_count') or 0} · failed={generator.get('failed_count') or 0} · running={generator.get('running_count') or 0}",
        f"- Evaluator: status={evaluator.get('plan_status') or '—'} · accepted={evaluator.get('accepted_count') or 0} · warning={evaluator.get('warning_count') or 0} · failed={evaluator.get('failed_count') or 0}",
        f"- Artifacts: {artifacts.get('count') or 0}",
        f"- Observability: phase={observability.get('phase') or '—'} · progress={observability.get('progress') if observability.get('progress') is not None else '—'}",
    ])
    subtasks = list(conductor.get("subtasks") or [])
    if subtasks:
        lines.append("")
        lines.append("### Subtasks")
        for item in subtasks:
            evaluation = dict(item.get("evaluation") or {})
            generator_meta = dict(item.get("generator") or {})
            subtask_observability = dict(item.get("observability") or {})
            artifact_count = len(list(item.get("artifacts") or []))
            lines.append(
                f"- {item.get('id') or '—'} · {item.get('status') or '—'} · {item.get('description') or '—'}"
            )
            lines.append(
                f"  - generator={generator_meta.get('status') or '—'}:{subtask_observability.get('agent_id') or item.get('assigned_agent_id') or '—'} · evaluator={evaluation.get('status') or '—'} · artifacts={artifact_count}"
            )


def render_task_export_markdown(export_view: dict[str, Any], task_id: str) -> str:
    summary = export_view.get("summary") or {}
    task = export_view.get("task") or {}
    retrieval = summary.get("retrieval") or task.get("retrieval") or {}
    lines = [
        f"# Task Export: {task.get('task_id') or task_id}",
        "",
        f"- Goal: {task.get('goal') or ''}",
        f"- Status: {task.get('status') or ''}",
        f"- Stage: {task.get('current_stage') or ''}",
        f"- Last Successful Step: {summary.get('last_successful_step') or '—'}",
        f"- Resume From Step: {summary.get('resume_from_step') or '—'}",
        "",
        "## Trigger",
    ]
    trigger = export_view.get("trigger") or {}
    if trigger:
        lines.extend([
            f"- Source: {trigger.get('source') or '—'}",
            f"- Kind: {trigger.get('kind') or '—'}",
            f"- Trigger ID: {trigger.get('trigger_id') or '—'}",
        ])
    else:
        lines.append("- none")
    append_retrieval_markdown(lines, retrieval)
    append_conductor_markdown(lines, export_view.get("conductor") or summary.get("conductor"))
    lines.extend([
        "",
        "## Recovery History",
    ])
    recovery_history = list(summary.get("recovery_history") or [])
    if recovery_history:
        for item in recovery_history:
            lines.append(f"- {item.get('action') or 'unknown'} · {item.get('source') or '—'} · {item.get('reason') or '—'}")
    else:
        lines.append("- none")
    lines.extend([
        "",
        "## Candidate",
        "",
        "```json",
        json.dumps(export_view.get("candidate") or {}, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Outbox Postmortem",
        "",
        "```json",
        json.dumps((export_view.get("postmortem") or {}).get("outbox") or {}, ensure_ascii=False, indent=2),
        "```",
    ])
    return "\n".join(lines)


def render_task_bundle_markdown(bundle: dict[str, Any], task_id: str) -> str:
    task = bundle.get("task") or {}
    summary = bundle.get("summary") or {}
    trigger = bundle.get("trigger") or {}
    postmortem = bundle.get("postmortem") or {}
    retrieval = summary.get("retrieval") or task.get("retrieval") or {}
    lines = [
        f"# Task Bundle: {task.get('task_id') or task_id}",
        "",
        f"- Goal: {task.get('goal') or ''}",
        f"- Status: {task.get('status') or ''}",
        f"- Stage: {task.get('current_stage') or ''}",
        f"- Last Successful Step: {summary.get('last_successful_step') or '—'}",
        f"- Resume From Step: {summary.get('resume_from_step') or '—'}",
        "",
        "## Trigger",
    ]
    if trigger:
        lines.extend([
            f"- Source: {trigger.get('source') or '—'}",
            f"- Kind: {trigger.get('kind') or '—'}",
            f"- Trigger ID: {trigger.get('trigger_id') or '—'}",
        ])
    else:
        lines.append("- none")
    append_retrieval_markdown(lines, retrieval)
    append_conductor_markdown(lines, bundle.get("conductor") or summary.get("conductor"))
    lines.extend([
        "",
        "## Candidate",
        "",
        "```json",
        json.dumps(bundle.get("candidate") or {}, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Recovery History",
    ])
    recovery_history = list(summary.get("recovery_history") or [])
    if recovery_history:
        for item in recovery_history:
            lines.append(f"- {item.get('action') or 'unknown'} · {item.get('source') or '—'} · {item.get('reason') or '—'}")
    else:
        lines.append("- none")
    lines.extend([
        "",
        "## Postmortem",
        "",
        "```json",
        json.dumps(postmortem, ensure_ascii=False, indent=2),
        "```",
    ])
    return "\n".join(lines)


def render_task_postmortem_markdown(postmortem: dict[str, Any], task_id: str) -> str:
    task = postmortem.get("task") or {}
    outbox = postmortem.get("outbox") or {}
    lifecycle = dict(outbox.get("lifecycle") or {})
    trigger = postmortem.get("trigger") or {}
    retrieval = dict((task.get("metadata") or {}).get("retrieval") or {})
    lines = [
        f"# Task Postmortem: {task.get('task_id') or task_id}",
        "",
        f"- Goal: {task.get('goal') or ''}",
        f"- Status: {task.get('status') or ''}",
        f"- Stage: {task.get('current_stage') or ''}",
        "",
        "## Trigger",
    ]
    if trigger:
        lines.extend([
            f"- Source: {trigger.get('source') or '—'}",
            f"- Kind: {trigger.get('kind') or '—'}",
            f"- Trigger ID: {trigger.get('trigger_id') or '—'}",
        ])
    else:
        lines.append("- none")
    append_retrieval_markdown(lines, retrieval)
    append_conductor_markdown(lines, postmortem.get("conductor") or postmortem.get("summary", {}).get("conductor"))
    lines.extend([
        "",
        "## Outbox Lifecycle",
        "",
        f"- Active Count: {lifecycle.get('active_count') or 0}",
        f"- Terminal Count: {lifecycle.get('terminal_count') or 0}",
        "",
        "```json",
        json.dumps(lifecycle, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Outbox Events",
        "",
        "```json",
        json.dumps(outbox.get('events') or [], ensure_ascii=False, indent=2),
        "```",
    ])
    return "\n".join(lines)
