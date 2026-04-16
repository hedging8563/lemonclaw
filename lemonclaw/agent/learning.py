"""Managed skill learning runtime built from completed task truth."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

import yaml
from loguru import logger

from lemonclaw.agent.skill_eval import (
    SkillBenchmark,
    SkillBenchmarkCase,
    evaluate_skill_benchmark,
)
from lemonclaw.agent.skills import SkillsLoader
from lemonclaw.governance.redaction import redact_sensitive_text, redact_sensitive_value
from lemonclaw.ledger.types import merge_verification_metadata
from lemonclaw.utils.helpers import strip_fences

_SAFE_SLUG_RE = re.compile(r"[^a-z0-9]+")
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", re.DOTALL)
_TOOL_TOKEN_RE = re.compile(r"`([A-Za-z][A-Za-z0-9_:-]{1,64})`")
_TERMINAL_LEARNING_STATUSES = {"promoted", "discarded", "promotion_skipped", "ineligible"}
_IGNORED_TRACE_TOOLS = {"message", "notify", "task_checkpoint"}
_REPO_EVIDENCE_TOOLS = {"read_file", "write_file", "edit_file", "list_dir", "glob", "grep", "git", "coding"}
_DEFAULT_SURFACES = ("chat", "conductor", "cron", "heartbeat")
_DEFAULT_EVALUATOR_MODEL = "gpt-5.4-pro"
_DEFAULT_RENDERER_MODEL = ""
_DEFAULT_PREFIX = "lc-auto--"


def _now_ms() -> int:
    return int(time.time() * 1000)


def _obj_get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        if key in value:
            return value.get(key, default)
        camel = re.sub(r"_([a-z])", lambda match: match.group(1).upper(), key)
        return value.get(camel, default)
    return getattr(value, key, default)


def _normalize_scope(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in {"workspace", "repo"} else "workspace"


def _normalize_status(value: str | None) -> str:
    return str(value or "").strip().lower()


def _truncate(text: str | None, *, limit: int = 500) -> str:
    safe = redact_sensitive_text(str(text or ""), aggressive=True)
    return safe[:limit]


def _ensure_mapping(value: Any) -> dict[str, Any]:
    return dict(value or {}) if isinstance(value, dict) else {}


def _normalize_triggers(value: Any) -> list[str]:
    if isinstance(value, list):
        raw = value
    elif value is None:
        raw = []
    else:
        raw = str(value).split(",")
    return [str(item).strip() for item in raw if str(item).strip()]


def _normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def _parse_frontmatter_markdown(markdown: str) -> tuple[dict[str, Any], str]:
    match = _FRONTMATTER_RE.match(markdown or "")
    if not match:
        return {}, str(markdown or "")
    try:
        parsed = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return {}, str(markdown or "")
    meta = parsed if isinstance(parsed, dict) else {}
    return meta, str(markdown or "")[match.end():]


def _extract_markdown_sections(markdown: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current = ""
    for raw_line in str(markdown or "").splitlines():
        line = raw_line.rstrip()
        if line.startswith("## "):
            current = line[3:].strip().lower()
            sections.setdefault(current, [])
            continue
        if current:
            sections.setdefault(current, []).append(line)
    return sections


class SkillLearningService:
    """Extract, evaluate, and promote managed workspace skills from task truth."""

    def __init__(
        self,
        *,
        workspace: Path,
        ledger: Any,
        provider_resolver: Callable[[str | None], Any],
        governance: Any | None = None,
        agent_id: str = "default",
        builtin_skills_dir: Path | None = None,
        config: Any | None = None,
    ) -> None:
        self.workspace = workspace
        self.ledger = ledger
        self._provider_resolver = provider_resolver
        self._governance = governance
        self.agent_id = agent_id
        self.builtin_skills_dir = builtin_skills_dir
        self.update_config(config)

    def update_config(self, config: Any | None) -> None:
        self.enabled = bool(_obj_get(config, "enabled", False)) if config is not None else False
        raw_surfaces = list(_obj_get(config, "surfaces", list(_DEFAULT_SURFACES)) or list(_DEFAULT_SURFACES))
        normalized_surfaces = {
            str(item).strip().lower()
            for item in raw_surfaces
            if str(item).strip().lower() in _DEFAULT_SURFACES
        }
        self.surfaces = normalized_surfaces or set(_DEFAULT_SURFACES)
        self.record_react_trace = bool(_obj_get(config, "record_react_trace", True))
        self.auto_promote = bool(_obj_get(config, "auto_promote", True))
        self.require_replay = bool(_obj_get(config, "require_replay", True))
        self.promotion_scope = _normalize_scope(_obj_get(config, "promotion_scope", "workspace"))
        evaluator_model = str(_obj_get(config, "evaluator_model", _DEFAULT_EVALUATOR_MODEL) or "").strip()
        self.evaluator_model = evaluator_model or _DEFAULT_EVALUATOR_MODEL
        renderer_model = str(_obj_get(config, "renderer_model", _DEFAULT_RENDERER_MODEL) or "").strip()
        self.renderer_model = renderer_model
        self.allow_llm_render = bool(_obj_get(config, "allow_llm_render", True))
        managed_prefix = str(_obj_get(config, "managed_skill_prefix", _DEFAULT_PREFIX) or "").strip()
        self.managed_skill_prefix = managed_prefix if re.match(r"^[a-z0-9][a-z0-9-]{2,31}$", managed_prefix) else _DEFAULT_PREFIX
        try:
            min_steps = int(_obj_get(config, "min_tool_steps_for_extraction", 2) or 2)
        except (TypeError, ValueError):
            min_steps = 2
        self.min_tool_steps_for_extraction = max(1, min_steps)

    async def maybe_promote_for_task(
        self,
        task_id: str,
        *,
        preferred_surface: str | None = None,
        mode: str = "chat",
        actor_identity: str | None = None,
    ) -> dict[str, Any] | None:
        if not self.enabled or not self.auto_promote or not task_id:
            return None

        task = self.ledger.read_task(task_id)
        if not task:
            return None
        metadata = _ensure_mapping(task.get("metadata"))
        existing = _ensure_mapping(metadata.get("learning"))
        if _normalize_status(existing.get("status")) in _TERMINAL_LEARNING_STATUSES:
            return existing

        surface = self._derive_surface(task, preferred_surface=preferred_surface)
        if surface not in self.surfaces:
            return self._persist_learning_state(
                task_id,
                task,
                {
                    "status": "promotion_skipped",
                    "surface": surface,
                    "reason": f"surface_disabled:{surface}",
                    "updated_at_ms": _now_ms(),
                },
            )

        completion_gate = _ensure_mapping(task.get("completion_gate"))
        if _normalize_status(task.get("status")) != "completed" or not bool(completion_gate.get("passed")):
            return self._persist_learning_state(
                task_id,
                task,
                {
                    "status": "promotion_skipped",
                    "surface": surface,
                    "reason": "task_not_completed",
                    "updated_at_ms": _now_ms(),
                },
            )

        export_view = self.ledger.build_task_export_view(task_id) or {}
        bundle = self._build_task_bundle(task_id) or {}
        react_trace = self._build_react_trace(task, export_view)
        eligibility = self._evaluate_eligibility(task, export_view, bundle, react_trace, surface=surface)
        learning_payload: dict[str, Any] = {
            "surface": surface,
            "react_trace": react_trace if self.record_react_trace else [],
            "eligibility": eligibility,
            "updated_at_ms": _now_ms(),
        }
        if not eligibility.get("eligible"):
            learning_payload["status"] = "ineligible"
            learning_payload["reason"] = str(eligibility.get("reason") or "not_eligible")
            return self._persist_learning_state(task_id, task, learning_payload)

        candidate = self._extract_candidate(task, export_view, bundle, react_trace, surface=surface)
        if not candidate:
            learning_payload["status"] = "promotion_skipped"
            learning_payload["reason"] = "candidate_extraction_failed"
            return self._persist_learning_state(task_id, task, learning_payload)
        learning_payload["candidate"] = candidate

        render_result = await self._render_with_fallback(candidate, bundle=bundle)
        learning_payload["renderer"] = render_result["renderer"]
        learning_payload["render_validation"] = render_result["render_validation"]
        learning_payload["rendered_skill_markdown"] = render_result["rendered_skill_markdown"]
        candidate["renderer"] = dict(render_result["renderer"])
        candidate["render_validation"] = dict(render_result["render_validation"])
        candidate["rendered_skill_markdown"] = render_result["rendered_skill_markdown"]

        replay = self._replay_candidate(candidate)
        learning_payload["replay"] = replay
        self._append_learning_verification(
            task_id,
            acceptance_evidence=[
                {
                    "kind": "managed_skill_replay",
                    "status": "accepted" if replay.get("passed") else "rejected",
                    "summary": f"managed skill replay {'passed' if replay.get('passed') else 'failed'} for {candidate.get('skill_name')}",
                    "task_id": task_id,
                    "artifact_id": str(candidate.get("skill_name") or ""),
                }
            ],
        )
        if self.require_replay and not replay.get("passed"):
            learning_payload["status"] = "discarded"
            learning_payload["reason"] = "replay_failed"
            return self._persist_learning_state(task_id, task, learning_payload)

        evaluator = await self._evaluate_candidate(candidate, bundle=bundle, replay=replay)
        learning_payload["evaluator"] = evaluator
        self._append_learning_verification(
            task_id,
            acceptance_evidence=[
                {
                    "kind": "managed_skill_evaluator",
                    "status": "accepted" if evaluator.get("accepted") else "rejected",
                    "summary": str(evaluator.get("reason") or f"managed skill evaluator {'accepted' if evaluator.get('accepted') else 'rejected'}"),
                    "task_id": task_id,
                    "artifact_id": str(candidate.get("skill_name") or ""),
                }
            ],
        )
        if evaluator.get("status") == "promotion_skipped":
            learning_payload["status"] = "promotion_skipped"
            learning_payload["reason"] = str(evaluator.get("reason") or "evaluator_unavailable")
            return self._persist_learning_state(task_id, task, learning_payload)
        if not evaluator.get("accepted"):
            learning_payload["status"] = "discarded"
            learning_payload["reason"] = str(evaluator.get("reason") or "evaluator_rejected")
            return self._persist_learning_state(task_id, task, learning_payload)

        scope_override = _normalize_scope(evaluator.get("scope_override"))
        candidate["scope"] = scope_override if scope_override in {"workspace", "repo"} else candidate["scope"]

        promoted = self._promote_skill(
            candidate,
            task_id=task_id,
            surface=surface,
            mode=mode,
            actor_identity=str(actor_identity or self.agent_id),
            replay=replay,
            evaluator=evaluator,
        )
        learning_payload["promoted_skill"] = promoted
        learning_payload["status"] = _normalize_status(promoted.get("status")) or "promotion_skipped"
        learning_payload["reason"] = str(promoted.get("reason") or "")
        return self._persist_learning_state(task_id, task, learning_payload)

    def _append_learning_verification(
        self,
        task_id: str,
        *,
        acceptance_evidence: list[dict[str, Any]],
    ) -> None:
        task = self.ledger.read_task(task_id)
        if not task:
            return
        metadata = _ensure_mapping(task.get("metadata"))
        verification = merge_verification_metadata(
            metadata.get("verification"),
            acceptance_evidence=acceptance_evidence,
        )
        metadata["verification"] = verification
        self.ledger.update_task(task_id, metadata=metadata)

    def _build_task_bundle(self, task_id: str) -> dict[str, Any] | None:
        from lemonclaw.ledger.task_exports import build_task_bundle

        return build_task_bundle(self.ledger, task_id)

    def _derive_surface(self, task: dict[str, Any], *, preferred_surface: str | None = None) -> str:
        preferred = str(preferred_surface or "").strip().lower()
        if preferred in _DEFAULT_SURFACES:
            return preferred

        metadata = _ensure_mapping(task.get("metadata"))
        trigger = _ensure_mapping(metadata.get("trigger"))
        trigger_source = str(trigger.get("source") or "").strip().lower()
        if trigger_source == "heartbeat":
            return "heartbeat"
        if trigger_source == "cron" or _normalize_status(task.get("mode")) == "cron" or str(task.get("agent_id") or "") == "cron":
            return "cron"
        if metadata.get("conductor") or str(task.get("agent_id") or "") == "conductor":
            return "conductor"
        return "chat"

    def _build_react_trace(self, task: dict[str, Any], export_view: dict[str, Any]) -> list[dict[str, Any]]:
        verification = _ensure_mapping((_ensure_mapping(export_view.get("summary")).get("verification")))
        raw_trace = [dict(item) for item in list(verification.get("tool_trace") or []) if isinstance(item, dict)]
        trace: list[dict[str, Any]] = []
        for item in raw_trace:
            tool_name = str(item.get("tool_name") or "").strip()
            if not tool_name:
                continue
            trace.append(
                {
                    "iteration_index": int(item.get("iteration_index") or 0),
                    "tool_name": tool_name,
                    "tool_arguments_summary": _truncate(item.get("params_summary"), limit=500),
                    "observation_summary": _truncate(item.get("result_summary"), limit=500),
                    "artifact_refs": [str(ref) for ref in list(item.get("artifact_refs") or []) if str(ref)],
                    "result_state": str(item.get("status") or ("completed" if item.get("ok") else "failed") or "").strip() or "unknown",
                    "replayable": bool(item.get("replayable")),
                }
            )
        return trace

    def _evaluate_eligibility(
        self,
        task: dict[str, Any],
        export_view: dict[str, Any],
        bundle: dict[str, Any],
        react_trace: list[dict[str, Any]],
        *,
        surface: str,
    ) -> dict[str, Any]:
        useful_trace = [item for item in react_trace if item.get("tool_name") not in _IGNORED_TRACE_TOOLS]
        conductor = _ensure_mapping(export_view.get("conductor") or bundle.get("conductor"))
        conductor_evaluator = _ensure_mapping(conductor.get("evaluator"))
        conductor_artifacts = _ensure_mapping(conductor.get("artifacts"))
        conductor_subtasks = [dict(item) for item in list(conductor.get("subtasks") or []) if isinstance(item, dict)]
        conductor_accepted = str(conductor_evaluator.get("plan_status") or "").strip().lower() == "accepted"
        conductor_artifact_count = int(conductor_artifacts.get("count") or 0)
        conductor_completed = sum(1 for item in conductor_subtasks if str(item.get("status") or "") == "completed")
        artifact_refs = {
            str(ref)
            for item in useful_trace
            for ref in list(item.get("artifact_refs") or [])
            if str(ref)
        }
        has_repo_evidence = self._has_repo_evidence(task, useful_trace, bundle)

        if len(useful_trace) >= self.min_tool_steps_for_extraction:
            return {
                "eligible": True,
                "reason": "tool_trace_sufficient",
                "tool_step_count": len(useful_trace),
                "artifact_ref_count": len(artifact_refs),
                "repo_evidence": has_repo_evidence,
            }
        if surface == "conductor" and conductor_accepted and (conductor_artifact_count > 0 or conductor_completed > 0):
            return {
                "eligible": True,
                "reason": "conductor_artifacts_available",
                "tool_step_count": len(useful_trace),
                "artifact_ref_count": len(artifact_refs),
                "repo_evidence": has_repo_evidence,
            }
        if surface in {"cron", "heartbeat"} and useful_trace and artifact_refs:
            return {
                "eligible": True,
                "reason": "automation_trace_with_artifacts",
                "tool_step_count": len(useful_trace),
                "artifact_ref_count": len(artifact_refs),
                "repo_evidence": has_repo_evidence,
            }
        return {
            "eligible": False,
            "reason": "insufficient_learning_signal",
            "tool_step_count": len(useful_trace),
            "artifact_ref_count": len(artifact_refs),
            "repo_evidence": has_repo_evidence,
        }

    def _has_repo_evidence(self, task: dict[str, Any], react_trace: list[dict[str, Any]], bundle: dict[str, Any]) -> bool:
        metadata = _ensure_mapping(task.get("metadata"))
        retrieval = _ensure_mapping((_ensure_mapping(bundle.get("summary")).get("retrieval")) or metadata.get("retrieval"))
        hit_sources = {str(item) for item in list(retrieval.get("hit_sources") or []) if str(item)}
        if "repo_change_memory" in hit_sources or int(retrieval.get("repo_change_memory_count") or 0) > 0:
            return True
        for item in react_trace:
            if str(item.get("tool_name") or "") in _REPO_EVIDENCE_TOOLS:
                return True
        return (self.workspace / ".git").exists()

    def _extract_candidate(
        self,
        task: dict[str, Any],
        export_view: dict[str, Any],
        bundle: dict[str, Any],
        react_trace: list[dict[str, Any]],
        *,
        surface: str,
    ) -> dict[str, Any] | None:
        useful_trace = [item for item in react_trace if item.get("tool_name") not in _IGNORED_TRACE_TOOLS]
        if not useful_trace:
            conductor = _ensure_mapping(export_view.get("conductor") or bundle.get("conductor"))
            if not conductor:
                return None
        goal = _truncate(task.get("goal"), limit=240) or f"{surface} task"
        title = goal[:120]
        slug_base = _SAFE_SLUG_RE.sub("-", title.lower()).strip("-")
        if not slug_base:
            slug_base = f"{surface}-{str(task.get('task_id') or '')[-8:] or 'auto'}"
        slug_base = slug_base[:36].rstrip("-")
        workflow_fingerprint, workflow_signature = self._build_workflow_identity(
            task,
            export_view,
            bundle,
            useful_trace,
        )
        skill_name = f"{self.managed_skill_prefix}{slug_base}-{workflow_fingerprint}"

        steps: list[str] = []
        for index, item in enumerate(useful_trace, start=1):
            tool_name = str(item.get("tool_name") or "").strip()
            param_summary = str(item.get("tool_arguments_summary") or "").strip()
            observation = str(item.get("observation_summary") or "").strip()
            if param_summary and observation:
                summary = f"Use `{tool_name}` with {param_summary} and confirm {observation}."
            elif observation:
                summary = f"Use `{tool_name}` and confirm {observation}."
            else:
                summary = f"Use `{tool_name}` as part of the task flow."
            steps.append(f"{index}. {summary[:260]}")

        if not steps:
            conductor = _ensure_mapping(export_view.get("conductor") or bundle.get("conductor"))
            subtasks = [dict(item) for item in list(conductor.get("subtasks") or []) if isinstance(item, dict)]
            for index, item in enumerate(subtasks[:5], start=1):
                summary = _truncate(item.get("description"), limit=220) or f"complete subtask {index}"
                steps.append(f"{index}. {summary}")

        verification_steps = [
            "Confirm the task settles through CompletionGate with no open outbox or failed steps.",
            "Confirm the replay benchmark passes before reusing this skill.",
        ]
        conductor = _ensure_mapping(export_view.get("conductor") or bundle.get("conductor"))
        conductor_artifacts = _ensure_mapping(conductor.get("artifacts"))
        if int(conductor_artifacts.get("count") or 0) > 0:
            verification_steps.append("Confirm the expected conductor artifacts are present in the task bundle.")

        failure_signals = []
        for item in react_trace:
            if _normalize_status(item.get("result_state")) in {"failed", "error"}:
                summary = _truncate(item.get("observation_summary"), limit=200)
                if summary and summary not in failure_signals:
                    failure_signals.append(summary)
        if not failure_signals:
            failure_signals = [
                "The replay benchmark fails to trigger or inject the generated skill.",
                "The task bundle is missing expected artifacts or verification signals.",
            ]

        trigger_examples = []
        for candidate in (goal, title.lower(), " ".join(title.lower().split()[:6])):
            value = str(candidate or "").strip()
            if value and value not in trigger_examples:
                trigger_examples.append(value[:120])
        if not trigger_examples:
            trigger_examples = [title]

        required_inputs = ["A user request matching the task intent."]
        if self.promotion_scope == "repo" and self._has_repo_evidence(task, useful_trace, bundle):
            scope = "repo"
        else:
            scope = "workspace"

        tool_names = list(dict.fromkeys(
            str(item.get("tool_name") or "").strip()
            for item in useful_trace
            if str(item.get("tool_name") or "").strip()
        ))
        benchmark = self._build_candidate_benchmark(
            skill_name,
            trigger_examples,
            tool_names,
            verification_steps,
        )
        template_skill_markdown = self._render_skill_markdown_template(
            skill_name=skill_name,
            title=title,
            description=f"Managed auto-generated skill distilled from task execution: {title}",
            trigger_examples=trigger_examples,
            scope=scope,
            steps=steps,
            verification_steps=verification_steps,
            failure_signals=failure_signals[:8],
        )
        return {
            "slug": slug_base,
            "skill_name": skill_name,
            "title": title,
            "description": f"Managed auto-generated skill distilled from task execution: {title}",
            "pattern": "pipeline",
            "trigger_examples": trigger_examples,
            "required_inputs": required_inputs,
            "steps": steps,
            "tool_names": tool_names,
            "verification_steps": verification_steps,
            "failure_signals": failure_signals[:8],
            "source_task_ids": [str(task.get("task_id") or "")],
            "scope": scope,
            "workflow_fingerprint": workflow_fingerprint,
            "workflow_signature": workflow_signature,
            "benchmark": benchmark,
            "template_skill_markdown": template_skill_markdown,
            "skill_markdown": template_skill_markdown,
        }

    def _build_workflow_identity(
        self,
        task: dict[str, Any],
        export_view: dict[str, Any],
        bundle: dict[str, Any],
        useful_trace: list[dict[str, Any]],
    ) -> tuple[str, dict[str, Any]]:
        conductor = _ensure_mapping(export_view.get("conductor") or bundle.get("conductor"))
        conductor_subtasks = [dict(item) for item in list(conductor.get("subtasks") or []) if isinstance(item, dict)]
        signature = {
            "tools": [
                {
                    "tool_name": str(item.get("tool_name") or "").strip(),
                    "iteration_index": int(item.get("iteration_index") or 0),
                    "artifact_count": len([ref for ref in list(item.get("artifact_refs") or []) if str(ref)]),
                    "result_state": _normalize_status(item.get("result_state")),
                    "replayable": bool(item.get("replayable")),
                }
                for item in useful_trace[:8]
                if str(item.get("tool_name") or "").strip()
            ],
            "conductor_subtasks": [
                _truncate(item.get("description"), limit=120).lower()
                for item in conductor_subtasks[:5]
                if _truncate(item.get("description"), limit=120)
            ],
            "conductor_artifact_count": int(_ensure_mapping(conductor.get("artifacts")).get("count") or 0),
            "repo_evidence": self._has_repo_evidence(task, useful_trace, bundle),
        }
        digest = hashlib.sha1(
            json.dumps(signature, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:10]
        return digest, signature

    def _build_candidate_benchmark(
        self,
        skill_name: str,
        trigger_examples: list[str],
        tool_names: list[str],
        verification_steps: list[str],
    ) -> dict[str, Any]:
        positive = trigger_examples[0]
        runtime_loader = SkillsLoader(self.workspace, builtin_skills_dir=self.builtin_skills_dir)
        workspace_skill_names = {
            skill["name"]
            for skill in runtime_loader.list_skills(filter_unavailable=True)
            if skill.get("source") == "workspace" and skill["name"] != skill_name
        }
        conflict_skills = sorted(
            {
                matched
                for sample in trigger_examples[:3]
                for matched in runtime_loader.match_skills(sample)
                if matched in workspace_skill_names
            }
        )
        prompt_must_not_contain = [f"### Skill: {name}" for name in conflict_skills[:3]]
        prompt_must_contain = [f"`{tool_name}`" for tool_name in tool_names[:2]]
        if verification_steps:
            prompt_must_contain.append(verification_steps[0][:120])
        neighbor_cases: list[dict[str, Any]] = []
        seen_samples = {sample.lower() for sample in trigger_examples}
        candidate_names = conflict_skills + [
            name for name in sorted(workspace_skill_names)
            if name not in conflict_skills
        ]
        for other_name in candidate_names:
            triggers = _normalize_triggers((_ensure_mapping(runtime_loader.get_skill_metadata(other_name))).get("triggers"))
            sample = next((item for item in triggers if item.lower() not in seen_samples), "")
            if not sample:
                continue
            seen_samples.add(sample.lower())
            neighbor_cases.append(
                {
                    "name": f"neighbor-{len(neighbor_cases) + 1}",
                    "message": sample[:240],
                    "expect_triggered": False,
                    "required_skills": [other_name],
                }
            )
            if len(neighbor_cases) >= 4:
                break
        return {
            "skill": skill_name,
            "mode": "chat",
            "ignore_requirements": False,
            "cases": [
                {
                    "name": "source-task",
                    "message": positive,
                    "expect_triggered": True,
                    "prompt_must_contain": prompt_must_contain,
                    "prompt_must_not_contain": prompt_must_not_contain,
                    "conflict_skills": conflict_skills,
                },
                *neighbor_cases,
                {
                    "name": "negative-control",
                    "message": "Tell me a joke about rainbows.",
                    "expect_triggered": False,
                },
            ],
        }

    def _render_skill_markdown_template(
        self,
        *,
        skill_name: str,
        title: str,
        description: str,
        trigger_examples: list[str],
        scope: str,
        steps: list[str],
        verification_steps: list[str],
        failure_signals: list[str],
    ) -> str:
        frontmatter = {
            "name": skill_name,
            "description": description,
            "triggers": trigger_examples,
            "metadata": {
                "lemonclaw": {
                    "pattern": "pipeline",
                    "managed": True,
                    "scope": scope,
                }
            },
        }
        parts = [
            "---",
            yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).strip(),
            "---",
            "",
            f"# Managed Auto Skill: {title}",
            "",
            "Use this skill when the user request closely matches the examples below.",
            "",
            "## Trigger Examples",
        ]
        parts.extend(f"- {item}" for item in trigger_examples)
        parts.extend(["", "## Required Inputs"])
        parts.append("- A user request matching the task intent.")
        parts.extend(["", "## Pipeline"])
        parts.extend(f"- {item}" for item in steps)
        parts.extend(["", "## Verification"])
        parts.extend(f"- {item}" for item in verification_steps)
        parts.extend(["", "## Failure Signals"])
        parts.extend(f"- {item}" for item in failure_signals)
        return "\n".join(parts).strip() + "\n"

    async def _render_with_fallback(
        self,
        candidate: dict[str, Any],
        *,
        bundle: dict[str, Any],
    ) -> dict[str, Any]:
        template_markdown = str(candidate.get("template_skill_markdown") or candidate.get("skill_markdown") or "")
        if not template_markdown:
            return {
                "renderer": {
                    "strategy": "template_fallback",
                    "model": "",
                    "reason": "missing_template_markdown",
                },
                "render_validation": {
                    "passed": False,
                    "failures": ["missing_template_markdown"],
                    "used_fallback": True,
                },
                "rendered_skill_markdown": "",
            }

        if not self.allow_llm_render:
            return {
                "renderer": {
                    "strategy": "template_only",
                    "model": "",
                    "reason": "llm_render_disabled",
                },
                "render_validation": {
                    "passed": True,
                    "failures": [],
                    "used_fallback": False,
                },
                "rendered_skill_markdown": template_markdown,
            }

        rendered = await self._render_skill_markdown_llm(candidate, bundle=bundle)
        if not rendered:
            return {
                "renderer": {
                    "strategy": "template_fallback",
                    "model": self.renderer_model or self.evaluator_model,
                    "reason": "renderer_unavailable",
                },
                "render_validation": {
                    "passed": False,
                    "failures": ["renderer_unavailable"],
                    "used_fallback": True,
                },
                "rendered_skill_markdown": template_markdown,
            }

        validation = self._validate_rendered_skill(rendered, candidate)
        if not validation["passed"]:
            return {
                "renderer": {
                    "strategy": "template_fallback",
                    "model": self.renderer_model or self.evaluator_model,
                    "reason": "render_validation_failed",
                },
                "render_validation": {
                    **validation,
                    "used_fallback": True,
                },
                "rendered_skill_markdown": template_markdown,
            }

        return {
            "renderer": {
                "strategy": "llm",
                "model": self.renderer_model or self.evaluator_model,
                "reason": "rendered",
            },
            "render_validation": {
                **validation,
                "used_fallback": False,
            },
            "rendered_skill_markdown": rendered,
        }

    async def _render_skill_markdown_llm(
        self,
        candidate: dict[str, Any],
        *,
        bundle: dict[str, Any],
    ) -> str | None:
        model = str(self.renderer_model or self.evaluator_model or "").strip()
        provider = None
        try:
            provider = self._provider_resolver(model)
        except Exception:
            logger.exception("Skill learning: failed to resolve renderer provider for {}", model)
            return None
        if provider is None:
            return None

        render_payload = {
            "candidate": {
                "skill_name": candidate.get("skill_name"),
                "title": candidate.get("title"),
                "description": candidate.get("description"),
                "scope": candidate.get("scope"),
                "trigger_examples": candidate.get("trigger_examples"),
                "required_inputs": candidate.get("required_inputs"),
                "steps": candidate.get("steps"),
                "tool_names": candidate.get("tool_names"),
                "verification_steps": candidate.get("verification_steps"),
                "failure_signals": candidate.get("failure_signals"),
                "workflow_fingerprint": candidate.get("workflow_fingerprint"),
            },
            "template_skill_markdown": candidate.get("template_skill_markdown"),
            "bundle_summary": {
                "task": {
                    "goal": _ensure_mapping(bundle.get("task")).get("goal"),
                    "status": _ensure_mapping(bundle.get("task")).get("status"),
                },
                "summary": _ensure_mapping(bundle.get("summary")),
                "conductor": _ensure_mapping(bundle.get("conductor")),
            },
        }
        prompt = (
            "Rewrite the provided managed skill markdown so it reads more naturally and clearly, but do not change the underlying facts.\n"
            "Rules:\n"
            "1. Keep YAML frontmatter valid.\n"
            "2. Preserve name, triggers, managed=true, pattern=pipeline, and scope.\n"
            "3. Keep every verification bullet, failure-signal bullet, and required-input bullet verbatim.\n"
            "4. You may rewrite the title, introduction, and pipeline bullet wording.\n"
            "5. Every pipeline bullet must still mention its original tool in backticks.\n"
            "6. Do not introduce any new tool names or new high-risk actions.\n"
            "7. Return ONLY the full markdown document."
        )
        try:
            response = await provider.chat(
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": json.dumps(redact_sensitive_value(render_payload), ensure_ascii=False)},
                ],
                model=model,
                temperature=0.2,
                max_tokens=2048,
            )
        except Exception:
            logger.exception("Skill learning: renderer failed for {}", candidate.get("skill_name"))
            return None
        rendered = strip_fences(response.content or "").strip()
        return rendered or None

    def _validate_rendered_skill(
        self,
        rendered_markdown: str,
        candidate: dict[str, Any],
    ) -> dict[str, Any]:
        failures: list[str] = []
        meta, _body = _parse_frontmatter_markdown(rendered_markdown)
        if not meta:
            return {"passed": False, "failures": ["invalid_frontmatter"]}

        if str(meta.get("name") or "").strip() != str(candidate.get("skill_name") or ""):
            failures.append("name_mismatch")

        rendered_triggers = _normalize_triggers(meta.get("triggers"))
        expected_triggers = [str(item).strip() for item in list(candidate.get("trigger_examples") or []) if str(item).strip()]
        if any(trigger not in rendered_triggers for trigger in expected_triggers):
            failures.append("trigger_examples_changed")

        lemonclaw_meta = _ensure_mapping(_ensure_mapping(meta.get("metadata")).get("lemonclaw"))
        if str(lemonclaw_meta.get("pattern") or "").strip() != "pipeline":
            failures.append("pattern_mismatch")
        if str(lemonclaw_meta.get("scope") or "").strip() != str(candidate.get("scope") or "").strip():
            failures.append("scope_mismatch")

        sections = _extract_markdown_sections(rendered_markdown)
        for heading in ("trigger examples", "required inputs", "pipeline", "verification", "failure signals"):
            if heading not in sections:
                failures.append(f"missing_section:{heading}")

        normalized_markdown = _normalize_text(rendered_markdown)
        for item in list(candidate.get("required_inputs") or []):
            if _normalize_text(str(item)) not in normalized_markdown:
                failures.append(f"required_input_missing:{item}")
        for item in list(candidate.get("verification_steps") or []):
            if _normalize_text(str(item)) not in normalized_markdown:
                failures.append(f"verification_missing:{item}")
        for item in list(candidate.get("failure_signals") or []):
            if _normalize_text(str(item)) not in normalized_markdown:
                failures.append(f"failure_signal_missing:{item}")

        pipeline_lines = [
            line for line in sections.get("pipeline", [])
            if line.strip().startswith(("- ", "* ", "+ ")) or re.match(r"^\d+\.\s+", line.strip())
        ]
        if len(pipeline_lines) < len(list(candidate.get("steps") or [])):
            failures.append("pipeline_step_count_reduced")

        candidate_tool_names = {
            str(item).strip()
            for item in list(candidate.get("tool_names") or [])
            if str(item).strip()
        }
        rendered_tool_names = {token for token in _TOOL_TOKEN_RE.findall(rendered_markdown) if "_" in token or "-" in token}
        for tool_name in candidate_tool_names:
            if f"`{tool_name}`" not in rendered_markdown:
                failures.append(f"tool_anchor_missing:{tool_name}")
        extra_tool_names = sorted(tool_name for tool_name in rendered_tool_names if tool_name not in candidate_tool_names)
        if extra_tool_names:
            failures.append(f"unexpected_tools:{', '.join(extra_tool_names[:5])}")

        return {"passed": not failures, "failures": failures}

    def _replay_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        benchmark_payload = dict(candidate.get("benchmark") or {})
        with tempfile.TemporaryDirectory(prefix="lc_skill_replay_") as tmp:
            temp_root = Path(tmp)
            workspace = temp_root / "workspace"
            source_skills_root = self.workspace / "skills"
            replay_skills_root = workspace / "skills"
            if source_skills_root.exists():
                shutil.copytree(
                    source_skills_root,
                    replay_skills_root,
                    dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("archive"),
                )
            skill_dir = replay_skills_root / str(candidate["skill_name"])
            skill_dir.mkdir(parents=True, exist_ok=True)
            skill_markdown = str(
                candidate.get("rendered_skill_markdown")
                or candidate.get("template_skill_markdown")
                or candidate.get("skill_markdown")
                or ""
            )
            (skill_dir / "SKILL.md").write_text(skill_markdown, encoding="utf-8")

            benchmark = SkillBenchmark(
                skill=str(benchmark_payload.get("skill") or candidate["skill_name"]),
                mode=str(benchmark_payload.get("mode") or "chat"),
                ignore_requirements=bool(benchmark_payload.get("ignore_requirements", True)),
                cases=[
                    SkillBenchmarkCase(
                        name=str(case.get("name") or f"case-{index}"),
                        message=str(case.get("message") or ""),
                        expect_triggered=bool(case.get("expect_triggered", True)),
                        required_skills=[str(item) for item in list(case.get("required_skills") or []) if str(item)],
                        conflict_skills=[str(item) for item in list(case.get("conflict_skills") or []) if str(item)],
                        prompt_must_contain=[str(item) for item in list(case.get("prompt_must_contain") or []) if str(item)],
                        prompt_must_not_contain=[str(item) for item in list(case.get("prompt_must_not_contain") or []) if str(item)],
                    )
                    for index, case in enumerate(list(benchmark_payload.get("cases") or []), start=1)
                    if isinstance(case, dict)
                ],
            )
            report = evaluate_skill_benchmark(
                benchmark,
                workspace=workspace,
                builtin_skills_dir=self.builtin_skills_dir,
            )
            return {
                "passed": bool(report.passed),
                "score": int(report.score),
                "max_score": int(report.max_score),
                "case_reports": report.to_dict().get("case_reports", []),
                "generated_at_ms": _now_ms(),
            }

    async def _evaluate_candidate(
        self,
        candidate: dict[str, Any],
        *,
        bundle: dict[str, Any],
        replay: dict[str, Any],
    ) -> dict[str, Any]:
        provider = None
        try:
            provider = self._provider_resolver(self.evaluator_model)
        except Exception:
            logger.exception("Skill learning: failed to resolve evaluator provider for {}", self.evaluator_model)
        if provider is None:
            return {
                "status": "promotion_skipped",
                "reason": "promotion_skipped:evaluator_unavailable",
                "accepted": False,
                "score": 0.0,
                "risks": ["evaluator_unavailable"],
            }

        system_prompt = (
            "You are a strict skill promotion evaluator. Review the candidate managed skill, "
            "the task bundle summary, and the deterministic replay result. "
            "Return ONLY valid JSON with keys: accepted (bool), score (float 0-1), "
            "risks (string list), reason (string), scope_override (optional string: workspace|repo)."
        )
        user_payload = {
            "candidate": {
                "skill_name": candidate.get("skill_name"),
                "description": candidate.get("description"),
                "scope": candidate.get("scope"),
                "steps": candidate.get("steps"),
                "verification_steps": candidate.get("verification_steps"),
                "failure_signals": candidate.get("failure_signals"),
                "skill_markdown": candidate.get("rendered_skill_markdown") or candidate.get("template_skill_markdown") or candidate.get("skill_markdown"),
            },
            "bundle": {
                "task": _ensure_mapping(bundle.get("task")),
                "summary": _ensure_mapping(bundle.get("summary")),
                "conductor": _ensure_mapping(bundle.get("conductor")),
            },
            "replay": replay,
        }
        try:
            response = await provider.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(redact_sensitive_value(user_payload), ensure_ascii=False)},
                ],
                model=self.evaluator_model,
                temperature=0.1,
                max_tokens=512,
            )
            parsed = json.loads(strip_fences(response.content or ""))
        except Exception:
            logger.exception("Skill learning: evaluator failed for {}", candidate.get("skill_name"))
            return {
                "status": "promotion_skipped",
                "reason": "promotion_skipped:evaluator_unavailable",
                "accepted": False,
                "score": 0.0,
                "risks": ["evaluator_unavailable"],
            }

        accepted = bool(parsed.get("accepted"))
        try:
            score = float(parsed.get("score") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        risks = [str(item) for item in list(parsed.get("risks") or []) if str(item)]
        return {
            "status": "evaluated",
            "accepted": accepted,
            "score": score,
            "risks": risks,
            "reason": _truncate(parsed.get("reason"), limit=500),
            "scope_override": _normalize_scope(parsed.get("scope_override")),
            "model": self.evaluator_model,
            "checked_at_ms": _now_ms(),
        }

    def _promote_skill(
        self,
        candidate: dict[str, Any],
        *,
        task_id: str,
        surface: str,
        mode: str,
        actor_identity: str,
        replay: dict[str, Any],
        evaluator: dict[str, Any],
    ) -> dict[str, Any]:
        capability_id = "skill.write.managed"
        capability = None
        token = None
        warnings: list[str] = []
        started_at = time.time()
        if self._governance is not None:
            token = self._governance.issue_token(
                task_id=task_id,
                mode=mode,
                allowed_capabilities=[capability_id],
            )
            decision = self._governance.authorize(
                capability_id=capability_id,
                tool_name="skill_learning",
                token=token,
                mode=mode,
            )
            capability = decision.capability
            warnings = list(decision.warnings or [])
            if not decision.allowed:
                self._governance.record_audit(
                    capability=capability,
                    token=token,
                    task_id=task_id,
                    mode=mode,
                    actor_identity=actor_identity,
                    started_at=started_at,
                    ended_at=time.time(),
                    params={"skill_name": candidate.get("skill_name"), "surface": surface},
                    result_status="error",
                    warnings=[*warnings, f"denied:{decision.reason}"],
                )
                return {"status": "promotion_skipped", "reason": f"governance_denied:{decision.reason}"}

        skill_name = str(candidate["skill_name"])
        skill_dir = self.workspace / "skills" / skill_name
        sidecar_path = skill_dir / "skill.asset.json"
        skill_path = skill_dir / "SKILL.md"
        archive_dir = skill_dir / "archive"
        if skill_dir.exists() and not sidecar_path.exists():
            return {"status": "promotion_skipped", "reason": "managed_conflict"}

        existing_score = None
        existing_sidecar: dict[str, Any] | None = None
        if sidecar_path.exists():
            try:
                existing_sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
                existing_score = float(_ensure_mapping(existing_sidecar.get("evaluator")).get("score") or 0.0)
            except Exception:
                existing_sidecar = None
                existing_score = None
        new_score = float(evaluator.get("score") or 0.0)
        if existing_score is not None and new_score <= existing_score:
            if self._governance is not None and capability is not None:
                self._governance.record_audit(
                    capability=capability,
                    token=token,
                    task_id=task_id,
                    mode=mode,
                    actor_identity=actor_identity,
                    started_at=started_at,
                    ended_at=time.time(),
                    params={"skill_name": skill_name, "surface": surface},
                    result_status="error",
                    warnings=[*warnings, "discarded:existing_score_higher"],
                )
            return {"status": "discarded", "reason": "existing_score_higher"}

        skill_dir.mkdir(parents=True, exist_ok=True)
        history: list[dict[str, Any]] = []
        if existing_sidecar:
            history = [dict(item) for item in list(existing_sidecar.get("replacement_history") or []) if isinstance(item, dict)]
        if skill_path.exists() or sidecar_path.exists():
            archived_at_ms = _now_ms()
            current_archive = archive_dir / str(archived_at_ms)
            current_archive.mkdir(parents=True, exist_ok=True)
            if skill_path.exists():
                shutil.copy2(skill_path, current_archive / "SKILL.md")
            if sidecar_path.exists():
                shutil.copy2(sidecar_path, current_archive / "skill.asset.json")
            history.append(
                {
                    "archived_at_ms": archived_at_ms,
                    "path": str(current_archive),
                    "previous_score": existing_score,
                }
            )

        skill_markdown = str(
            candidate.get("rendered_skill_markdown")
            or candidate.get("template_skill_markdown")
            or candidate.get("skill_markdown")
            or ""
        )
        skill_path.write_text(skill_markdown, encoding="utf-8")
        sidecar = {
            "version": 1,
            "skill_name": skill_name,
            "source_task_ids": [task_id],
            "source_surface": surface,
            "scope": candidate.get("scope"),
            "workflow_fingerprint": candidate.get("workflow_fingerprint"),
            "workflow_signature": candidate.get("workflow_signature"),
            "status": "approved",
            "renderer": dict(candidate.get("renderer") or {}),
            "render_validation": dict(candidate.get("render_validation") or {}),
            "replay": replay,
            "evaluator": evaluator,
            "promoted_at_ms": _now_ms(),
            "replacement_history": history[-20:],
        }
        sidecar_path.write_text(json.dumps(sidecar, ensure_ascii=False, indent=2), encoding="utf-8")

        if self._governance is not None and capability is not None:
            self._governance.record_audit(
                capability=capability,
                token=token,
                task_id=task_id,
                mode=mode,
                actor_identity=actor_identity,
                started_at=started_at,
                ended_at=time.time(),
                params={"skill_name": skill_name, "surface": surface, "scope": candidate.get("scope")},
                result_status="ok",
                artifact_refs=[str(skill_path), str(sidecar_path)],
                warnings=warnings,
            )
        return {
            "status": "promoted",
            "reason": "promoted",
            "name": skill_name,
            "path": str(skill_path),
            "sidecar_path": str(sidecar_path),
        }

    def _persist_learning_state(self, task_id: str, task: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        latest_task = self.ledger.read_task(task_id) or task
        metadata = _ensure_mapping(latest_task.get("metadata"))
        learning = _ensure_mapping(metadata.get("learning"))
        learning.update(payload)
        learning["updated_at_ms"] = int(payload.get("updated_at_ms") or _now_ms())
        metadata["learning"] = learning
        self.ledger.update_task(task_id, metadata=metadata)
        return learning
