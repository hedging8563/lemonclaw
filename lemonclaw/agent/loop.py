"""Agent loop: the core processing engine."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import re
import time
import uuid
from contextlib import AsyncExitStack
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from loguru import logger

from lemonclaw.agent.context import ContextBuilder
from lemonclaw.agent.lemondata_runtime import build_lemondata_runtime_block
from lemonclaw.agent.locale import detect_lang, session_lang, t
from lemonclaw.agent.learning import SkillLearningService
from lemonclaw.agent.subagent import SubagentManager
from lemonclaw.agent.tools.coding import CodingTool
from lemonclaw.agent.tools.cron import CronTool
from lemonclaw.agent.tools.db import DBTool
from lemonclaw.agent.tools.filesystem import (
    EditFileTool,
    ListDirTool,
    AnalyzeImageTool,
    ReadAttachmentTool,
    ReadFileTool,
    WriteFileTool,
)
from lemonclaw.agent.tools.glob import GlobTool
from lemonclaw.agent.tools.grep import GrepTool
from lemonclaw.agent.tools.git_tool import GitTool
from lemonclaw.agent.tools.http_request import HTTPRequestTool
from lemonclaw.agent.tools.k8s import K8sTool
from lemonclaw.agent.tools.knowledge import KnowledgeSearchTool
from lemonclaw.agent.tools.lemondata_nonchat import LemonDataNonChatTool
from lemonclaw.agent.tools.message import MessageTool
from lemonclaw.agent.tools.notify import NotifyTool
from lemonclaw.agent.tools.task_checkpoint import TaskCheckpointTool
from lemonclaw.agent.tools.registry import ToolRegistry
from lemonclaw.agent.tools.shell import ExecTool
from lemonclaw.agent.tools.spawn import SpawnTool
from lemonclaw.agent.tools.web import WebFetchTool, WebSearchTool
from lemonclaw.bus.events import InboundMessage, OutboundMessage
from lemonclaw.bus.queue import MessageBus
from lemonclaw.channels.delivery_context import get_delivery_policy
from lemonclaw.gateway.webui.message_schema import serialize_ui_message
from lemonclaw.governance.redaction import (
    redact_sensitive_text,
    redact_sensitive_value,
)
from lemonclaw.providers.base import LLMProvider
from lemonclaw.providers.catalog import format_model_list, fuzzy_match, resolve_model_id
from lemonclaw.providers.registry import provider_family_for_model
from lemonclaw.session.manager import Session, SessionManager
from lemonclaw.telemetry.usage import TurnUsage, UsageTracker
from lemonclaw.utils.attachments import rewrite_text_paths
from lemonclaw.agent.prompting import infer_mode
from lemonclaw.memory.repo_change import load_repo_change_memory
from lemonclaw.governance import GovernanceRuntime
from lemonclaw.ledger.completion_gate import finalize_task
from lemonclaw.ledger.runtime import TaskLedger, build_task_resume_context
from lemonclaw.ledger.task_exports import (
    attach_trigger_context,
    build_task_bundle,
    render_task_bundle_markdown,
    render_task_export_markdown,
    render_task_postmortem_markdown,
)
from lemonclaw.triggers import TriggerRuntime

if TYPE_CHECKING:
    from lemonclaw.bus.activity import ActivityBus
    from lemonclaw.conductor.orchestrator import Orchestrator
    from lemonclaw.config.schema import (
        BrowserToolConfig,
        ChannelsConfig,
        CodingToolConfig,
        DBToolConfig,
        ExecToolConfig,
        GitToolConfig,
        HTTPRequestToolConfig,
        K8sToolConfig,
        NotifyToolConfig,
    )
    from lemonclaw.cron.service import CronService


_BUILTIN_TOOL_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "analyze_image": ("path",),
    "browser": ("command",),
    "coding": ("task",),
    "create_agent": ("agent_id", "role"),
    "cron": ("action",),
    "db": ("connection_profile", "query"),
    "edit_file": ("path", "old_text", "new_text"),
    "exec": ("command",),
    "get_agent_status": ("agent_id",),
    "git": ("action",),
    "glob": ("pattern",),
    "grep": ("pattern",),
    "http_request": ("method", "url"),
    "k8s": ("action",),
    "lemondata_nonchat": ("action", "category"),
    "list_agents": (),
    "list_dir": ("path",),
    "message": ("content",),
    "notify": ("target_type", "content"),
    "read_attachment": ("path",),
    "read_file": ("path",),
    "search_knowledge": ("query",),
    "send_to_agent": ("agent_id", "message"),
    "spawn": ("task",),
    "task_checkpoint": ("stage", "summary"),
    "web_fetch": ("url",),
    "web_search": ("query",),
    "write_file": ("path", "content"),
}
_GIT_AUTH_PROFILE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


class AgentLoop:
    """
    The agent loop is the core processing engine.

    It:
    1. Receives messages from the bus
    2. Builds context with history, memory, skills
    3. Calls the LLM
    4. Executes tool calls
    5. Sends responses back
    """

    _TOOL_RESULT_MAX_CHARS = 500
    _LLM_CALL_TIMEOUT = 300  # seconds: hard timeout for a single provider.chat() call
    _REFUSAL_RE = re.compile(
        r"(?:can['\u2019]?t\s+discuss|cannot\s+discuss|can['\u2019]?t\s+help"
        r"|cannot\s+help|not\s+able\s+to\s+help|i\s+(?:can['\u2019]?t|cannot)\s+(?:assist|provide))",
        re.IGNORECASE,
    )

    def __init__(
        self,
        bus: MessageBus,
        provider: LLMProvider,
        workspace: Path,
        model: str | None = None,
        agent_id: str = "default",
        max_iterations: int = 40,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        memory_window: int = 100,
        brave_api_key: str | None = None,
        web_search_max_results: int = 5,
        exec_config: ExecToolConfig | None = None,
        cron_service: CronService | None = None,
        session_manager: SessionManager | None = None,
        mcp_servers: dict | None = None,
        channels_config: ChannelsConfig | None = None,
        usage_tracker: UsageTracker | None = None,
        coding_config: CodingToolConfig | None = None,
        browser_config: BrowserToolConfig | None = None,
        http_config: HTTPRequestToolConfig | None = None,
        git_config: GitToolConfig | None = None,
        notify_config: NotifyToolConfig | None = None,
        db_config: DBToolConfig | None = None,
        k8s_config: K8sToolConfig | None = None,
        activity_bus: ActivityBus | None = None,
        default_timezone: str = "",
        system_prompt: str = "",
        disabled_skills: list[str] | None = None,
        governance_config: Any | None = None,
        learning_config: Any | None = None,
        trigger_runtime: TriggerRuntime | None = None,
        provider_factory: Callable[[str | None], LLMProvider] | None = None,
    ):
        from lemonclaw.config.schema import ExecToolConfig
        self.agent_id = agent_id
        self.bus = bus
        self.channels_config = channels_config
        self.default_timezone = default_timezone
        self.provider = provider
        self._provider_factory = provider_factory
        self.workspace = workspace
        self.model = model or provider.get_default_model()
        self.max_iterations = max_iterations
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.memory_window = memory_window
        self.brave_api_key = brave_api_key
        self.web_search_max_results = web_search_max_results
        self.exec_config = exec_config or ExecToolConfig()
        self.coding_config = coding_config
        self.browser_config = browser_config
        self.http_config = http_config
        self.git_config = git_config
        self.notify_config = notify_config
        self.db_config = db_config
        self.k8s_config = k8s_config
        self.activity_bus = activity_bus
        self.orchestrator: Orchestrator | None = None
        self.cron_service = cron_service
        self.context = ContextBuilder(workspace, system_prompt=system_prompt, disabled_skills=disabled_skills)
        self.context.memory.set_provider(provider)
        self.sessions = session_manager or SessionManager(workspace)
        self.ledger = TaskLedger(workspace)
        self.governance = GovernanceRuntime(
            workspace=workspace,
            config=governance_config,
            agent_id=agent_id,
        )
        self.trigger_runtime = trigger_runtime
        self.tools = ToolRegistry(governance=self.governance, ledger=self.ledger)
        self.subagents = SubagentManager(
            provider=provider,
            workspace=workspace,
            bus=bus,
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            brave_api_key=brave_api_key,
            exec_config=self.exec_config,
        )
        self.learning = SkillLearningService(
            workspace=workspace,
            ledger=self.ledger,
            provider_resolver=self._provider_for_model,
            governance=self.governance,
            agent_id=agent_id,
            builtin_skills_dir=self.context.skills.builtin_skills,
            config=learning_config,
        )

        self._running = False
        self._mcp_servers = mcp_servers or {}
        self.usage_tracker = usage_tracker or UsageTracker()
        self._mcp_stack: AsyncExitStack | None = None
        self._mcp_connected = False
        self._mcp_connecting = False
        self._consolidating: set[str] = set()  # Session keys with consolidation in progress
        self._consolidation_tasks: set[asyncio.Task] = set()  # Strong refs to in-flight tasks
        self._learning_tasks: set[asyncio.Task] = set()  # Strong refs to background learning promotions
        self._consolidation_locks: dict[str, asyncio.Lock] = {}
        self._consolidation_epochs: dict[str, int] = {}  # session_key -> supersede generation
        self._active_tasks: dict[str, list[asyncio.Task]] = {}  # session_key -> tasks
        self._active_task_ids: dict[str, set[str]] = {}  # session_key -> active ledger task_ids
        self._session_cancel_reasons: dict[str, str] = {}  # session_key -> cooperative cancel reason
        self._resume_tasks: dict[str, asyncio.Task] = {}  # task_id -> background resume task
        self._stop_events: dict[str, asyncio.Event] = {}  # session_key -> cooperative stop signal
        self._session_locks: dict[str, asyncio.Lock] = {}  # per-session processing locks
        self._session_lock_order: list[str] = []  # LRU tracking for session locks
        self._MAX_SESSION_LOCKS = 1000  # Upper bound to prevent unbounded growth
        self._register_default_tools()

    def _provider_for_model(self, model: str | None) -> LLMProvider:
        effective_model = resolve_model_id(model) or model or self.model
        if not effective_model or not self._provider_factory:
            return self.provider

        current_model = resolve_model_id(getattr(self.provider, "default_model", None) or self.model) or getattr(self.provider, "default_model", None) or self.model
        if provider_family_for_model(str(current_model or "")) == provider_family_for_model(effective_model):
            return self.provider

        try:
            resolved = self._provider_factory(effective_model)
        except Exception:
            logger.exception("Failed to resolve provider for model {}", effective_model)
            return self.provider
        return resolved or self.provider

    def _normalize_session_model(self, session: Session) -> str | None:
        current_model = str(session.metadata.get("current_model") or "").strip()
        if not current_model:
            return None
        resolved_model = resolve_model_id(current_model) or current_model
        if resolved_model != current_model:
            session.metadata["current_model"] = resolved_model
        return resolved_model

    def _track_background_task(self, task: asyncio.Task, *, bucket: set[asyncio.Task], label: str) -> None:
        """Keep a strong ref for background tasks and log failures consistently."""
        bucket.add(task)

        def _done(completed: asyncio.Task) -> None:
            bucket.discard(completed)
            try:
                exc = completed.exception()
            except asyncio.CancelledError:
                return
            if exc is not None:
                logger.opt(exception=exc).error("Background task failed [{}]", label)

        task.add_done_callback(_done)

    def _empty_tool_call_guidance(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None,
        result: Any,
        lang: str,
    ) -> str | None:
        """Return a fail-fast guidance message for empty invalid tool calls."""
        if arguments is not None and not isinstance(arguments, dict):
            return None
        if not isinstance(result, str) or not result.startswith("Error: Invalid parameters for tool"):
            return None
        missing_fields = self._missing_required_fields_for_tool(tool_name, arguments, result)
        if not missing_fields:
            return None
        if tool_name == "write_file":
            return t("tool_empty_args_write_file", lang)
        if tool_name == "exec":
            return t("tool_empty_args_exec", lang)
        if tool_name == "coding":
            return t("tool_empty_args_coding", lang)
        if tool_name == "browser":
            return t("tool_empty_args_browser", lang)
        return t("tool_empty_args_required", lang, name=tool_name, fields=", ".join(missing_fields))

    def _missing_required_fields_for_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None,
        result: str,
    ) -> list[str]:
        missing = [match.strip() for match in re.findall(r"missing required ([^;\n]+)", result)]
        if missing:
            return missing

        if arguments not in (None, {}):
            return []

        tool = self.tools.get(tool_name)
        if tool is not None and isinstance(tool.parameters, dict):
            required = tool.parameters.get("required", [])
            if isinstance(required, list) and required:
                return [str(field) for field in required]

        fallback = _BUILTIN_TOOL_REQUIRED_FIELDS.get(tool_name)
        if fallback:
            return [str(field) for field in fallback]
        return []

    @staticmethod
    def _clone_session(session: Session, *, messages: list[dict[str, Any]] | None = None, last_consolidated: int | None = None) -> Session:
        return Session(
            key=session.key,
            messages=copy.deepcopy(messages if messages is not None else session.messages),
            created_at=session.created_at,
            updated_at=session.updated_at,
            metadata=copy.deepcopy(session.metadata),
            last_consolidated=session.last_consolidated if last_consolidated is None else last_consolidated,
            version=session.version,
        )

    @staticmethod
    def _message_digest(message: dict[str, Any]) -> bytes:
        payload = json.dumps(message, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return hashlib.blake2b(payload, digest_size=16).digest()

    @classmethod
    def _history_prefix_digest(cls, messages: list[dict[str, Any]]) -> bytes:
        digest = hashlib.blake2b(digest_size=20)
        for message in messages:
            digest.update(cls._message_digest(message))
        return digest.digest()

    @classmethod
    def _history_prefix_matches(
        cls,
        live_messages: list[dict[str, Any]],
        original_messages: list[dict[str, Any]],
        *,
        original_digest: bytes | None = None,
    ) -> bool:
        if len(live_messages) < len(original_messages):
            return False
        live_digest = cls._history_prefix_digest(live_messages[: len(original_messages)])
        return live_digest == (original_digest or cls._history_prefix_digest(original_messages))

    async def _run_background_consolidation(self, session_key: str) -> None:
        """Consolidate a session snapshot without blocking the live session."""
        lock = self._consolidation_locks.setdefault(session_key, asyncio.Lock())
        try:
            async with lock:
                live = self.sessions.get_or_create(session_key)
                snapshot = self._clone_session(live)
                original_messages = snapshot.messages
                original_digest = self._history_prefix_digest(original_messages)
                epoch = self._consolidation_epochs.get(session_key, 0)

            if not original_messages:
                return

            consolidated = await self._consolidate_memory(
                snapshot,
                should_commit=lambda: self._consolidation_epochs.get(session_key, 0) == epoch,
            )
            if not consolidated:
                return

            async with lock:
                live = self.sessions.get_or_create(session_key)
                if not self._history_prefix_matches(live.messages, original_messages, original_digest=original_digest):
                    logger.debug("Skip applying stale consolidation snapshot for {}", session_key)
                    return

                if snapshot.messages == original_messages and snapshot.last_consolidated == live.last_consolidated:
                    return

                preserved_tail = copy.deepcopy(live.messages[len(original_messages):])
                live.messages = copy.deepcopy(snapshot.messages) + preserved_tail
                live.last_consolidated = snapshot.last_consolidated
                live.updated_at = datetime.now()
                self.sessions.save(live)
        finally:
            self._consolidating.discard(session_key)
            if not lock.locked():
                self._consolidation_locks.pop(session_key, None)

    def _schedule_background_consolidation(self, session_key: str) -> None:
        task = asyncio.create_task(self._run_background_consolidation(session_key))
        self._track_background_task(task, bucket=self._consolidation_tasks, label=f"session_consolidation:{session_key}")

    async def _run_learning_promotion(
        self,
        *,
        task_id: str,
        mode: str,
        actor_identity: str,
        preferred_surface: str | None = None,
    ) -> None:
        await self.learning.maybe_promote_for_task(
            task_id,
            preferred_surface=preferred_surface,
            mode=mode,
            actor_identity=actor_identity,
        )

    def _schedule_learning_promotion(
        self,
        *,
        task_id: str,
        mode: str,
        actor_identity: str,
        preferred_surface: str | None = None,
    ) -> None:
        if not task_id:
            return
        task = asyncio.create_task(
            self._run_learning_promotion(
                task_id=task_id,
                mode=mode,
                actor_identity=actor_identity,
                preferred_surface=preferred_surface,
            )
        )
        self._track_background_task(task, bucket=self._learning_tasks, label=f"task_learning:{task_id}")

    async def _archive_session_snapshot(self, session_key: str, snapshot: Session) -> None:
        """Persist a cleared session immediately, and archive memory in the background."""
        if not snapshot.messages:
            return
        ok = await self._consolidate_memory(snapshot, archive_all=True)
        if not ok:
            logger.warning("Background /new archival failed for {}", session_key)

    def _schedule_archive_snapshot(self, session_key: str, snapshot: Session) -> None:
        task = asyncio.create_task(self._archive_session_snapshot(session_key, snapshot))
        self._track_background_task(task, bucket=self._consolidation_tasks, label=f"session_archive:{session_key}")

    def _record_retrieval_meta(self, task_id: str, retrieval_meta: dict[str, Any]) -> None:
        task = self.ledger.read_task(task_id)
        if not task:
            return
        metadata = dict(task.get("metadata") or {})
        metadata["retrieval"] = dict(retrieval_meta)
        self.ledger.update_task(task_id, metadata=metadata)

    def _append_agentbridge_repo_change_memory(
        self,
        *,
        msg: InboundMessage,
        memory_ctx: str,
        retrieval_meta: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        metadata = dict(msg.metadata or {})
        agentbridge_meta = metadata.get("agentbridge")
        if msg.channel != "agentbridge" and not isinstance(agentbridge_meta, dict):
            return memory_ctx, retrieval_meta
        if not isinstance(agentbridge_meta, dict):
            return memory_ctx, retrieval_meta

        repo_change = load_repo_change_memory(
            self.workspace,
            client_id=str(agentbridge_meta.get("client_id") or ""),
            workspace_id=str(agentbridge_meta.get("workspace_id") or "default"),
            thread_id=str(agentbridge_meta.get("thread_id") or "default"),
            metadata=dict(agentbridge_meta.get("metadata") or {}) if isinstance(agentbridge_meta.get("metadata"), dict) else {},
        )
        if not repo_change:
            return memory_ctx, retrieval_meta

        context_block = str(repo_change.get("context") or "").strip()
        if context_block:
            memory_ctx = f"{memory_ctx}\n\n{context_block}".strip() if memory_ctx else context_block

        updated_meta = dict(retrieval_meta or {})
        structured = dict(updated_meta.get("structured") or {})
        repo_change_summary = str(repo_change.get("summary") or "").strip()
        if repo_change_summary and not structured.get("repo_change_summary"):
            structured["repo_change_summary"] = repo_change_summary
        fact_slots = list(structured.get("fact_slots") or [])
        seen_fact_keys = {
            (
                str(item.get("name") or ""),
                str(item.get("type") or ""),
                str(item.get("summary") or ""),
            )
            for item in fact_slots
            if isinstance(item, dict)
        }
        retrieval_objects = list(structured.get("retrieval_objects") or [])
        seen = {
            (
                str(item.get("kind") or ""),
                str(item.get("id") or ""),
                str(item.get("source") or ""),
            )
            for item in retrieval_objects
            if isinstance(item, dict)
        }
        added = 0
        for item in repo_change.get("retrieval_objects") or []:
            if not isinstance(item, dict):
                continue
            key = (
                str(item.get("kind") or ""),
                str(item.get("id") or ""),
                str(item.get("source") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            retrieval_objects.append(dict(item))
            added += 1
        fact_added = 0
        for item in repo_change.get("fact_slots") or []:
            if not isinstance(item, dict):
                continue
            key = (
                str(item.get("name") or ""),
                str(item.get("type") or ""),
                str(item.get("summary") or ""),
            )
            if key in seen_fact_keys:
                continue
            seen_fact_keys.add(key)
            fact_slots.append(dict(item))
            fact_added += 1
        if not added and not fact_added and not repo_change_summary:
            return memory_ctx, updated_meta

        if fact_slots:
            structured["fact_slots"] = fact_slots
        structured["retrieval_objects"] = retrieval_objects
        updated_meta["structured"] = structured
        if added or fact_added:
            updated_meta["hit_sources"] = list(dict.fromkeys([*list(updated_meta.get("hit_sources") or []), "repo_change_memory"]))
        updated_meta["repo_change_memory_count"] = int(updated_meta.get("repo_change_memory_count") or 0) + added
        updated_meta["repo_change_fact_slot_count"] = int(updated_meta.get("repo_change_fact_slot_count") or 0) + fact_added
        updated_meta["repo_change_memory_sources"] = list(
            dict.fromkeys([*list(updated_meta.get("repo_change_memory_sources") or []), str(repo_change.get("source") or "")])
        )
        return memory_ctx, updated_meta

    def update_defaults(
        self,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        memory_window: int | None = None,
        max_tool_iterations: int | None = None,
        system_prompt: str | None = None,
        disabled_skills: list[str] | None = None,
        learning_config: Any | None = None,
    ) -> None:
        """Hot-reload agent defaults. Only affects new sessions; existing sessions keep their overrides."""
        changed: list[str] = []
        if model is not None and model != self.model:
            self.model = model
            self.subagents.model = model
            if hasattr(self.provider, "default_model"):
                self.provider.default_model = model
            changed.append(f"model={model}")
        if temperature is not None and temperature != self.temperature:
            self.temperature = temperature
            changed.append(f"temperature={temperature}")
        if max_tokens is not None and max_tokens != self.max_tokens:
            self.max_tokens = max_tokens
            changed.append(f"max_tokens={max_tokens}")
        if memory_window is not None and memory_window != self.memory_window:
            self.memory_window = memory_window
            changed.append(f"memory_window={memory_window}")
        if max_tool_iterations is not None and max_tool_iterations != self.max_iterations:
            self.max_iterations = max_tool_iterations
            changed.append(f"max_iterations={max_tool_iterations}")
        if system_prompt is not None and system_prompt != self.context.system_prompt:
            self.context.system_prompt = system_prompt
            changed.append("system_prompt updated")
        if disabled_skills is not None and set(disabled_skills) != self.context.skills._disabled:
            self.context.skills._disabled = set(disabled_skills)
            changed.append(f"disabled_skills={disabled_skills}")
        if learning_config is not None:
            self.learning.update_config(learning_config)
            changed.append("learning_config updated")
        analyze_image_tool = self.tools.get("analyze_image")
        if analyze_image_tool is not None and hasattr(analyze_image_tool, "_default_model"):
            from lemonclaw.providers.catalog import get_runtime_default_model

            vision_model = get_runtime_default_model("vision")
            if getattr(analyze_image_tool, "_default_model", None) != vision_model:
                analyze_image_tool._default_model = vision_model
                changed.append(f"vision_model={vision_model}")
        if changed:
            logger.info("Agent defaults updated: {}", ", ".join(changed))

    def _register_default_tools(self) -> None:
        """Register the default set of tools."""
        for cls in (ReadFileTool, ReadAttachmentTool, WriteFileTool, EditFileTool, ListDirTool):
            self.tools.register(cls(workspace=self.workspace))
        self.tools.register(AnalyzeImageTool(provider=self.provider, workspace=self.workspace))
        self.tools.register(ExecTool(
            working_dir=str(self.workspace),
            timeout=self.exec_config.timeout,
            path_append=self.exec_config.path_append,
        ))
        self.tools.register(GrepTool(workspace=self.workspace))
        self.tools.register(GlobTool(workspace=self.workspace))
        self.tools.register(GitTool(
            working_dir=str(self.workspace),
            timeout=self.git_config.timeout if self.git_config else 20,
            max_output=self.git_config.max_output if self.git_config else 50_000,
            auth_profiles={
                name: profile.model_dump(by_alias=False)
                for name, profile in dict(self.git_config.auth_profiles or {}).items()
            } if self.git_config else {},
        ))
        self.tools.register(WebSearchTool(
            api_key=self.brave_api_key,
            max_results=self.web_search_max_results,
        ))
        self.tools.register(WebFetchTool())
        self.tools.register(LemonDataNonChatTool(workspace=self.workspace))
        self.tools.register(KnowledgeSearchTool(workspace=str(self.workspace)))
        if hasattr(self, "db_config") and self.db_config and self.db_config.enabled:
            self.tools.register(DBTool(
                timeout=self.db_config.timeout,
                sqlite_profiles=dict(self.db_config.sqlite_profiles or {}),
                postgres_profiles={
                    name: profile.model_dump(by_alias=False)
                    for name, profile in dict(self.db_config.postgres_profiles or {}).items()
                },
            ))
        if hasattr(self, "k8s_config") and self.k8s_config and self.k8s_config.enabled:
            self.tools.register(K8sTool(
                timeout=self.k8s_config.timeout,
                default_namespace=self.k8s_config.default_namespace,
                allowed_namespaces=list(self.k8s_config.allowed_namespaces or []),
                kubeconfig=self.k8s_config.kubeconfig,
                context=self.k8s_config.context,
                max_items=self.k8s_config.max_items,
                max_output=self.k8s_config.max_output,
            ))
        if hasattr(self, "http_config") and self.http_config and self.http_config.enabled:
            self.tools.register(HTTPRequestTool(
                timeout=self.http_config.timeout,
                allow_domains=list(self.http_config.allow_domains or []),
                auth_profiles=dict(self.http_config.auth_profiles or {}),
            ))
        self.tools.register(TaskCheckpointTool())
        self.tools.register(MessageTool(send_callback=self.bus.publish_outbound))
        if hasattr(self, "notify_config") and self.notify_config and self.notify_config.enabled:
            self.tools.register(NotifyTool(
                send_callback=self.bus.publish_outbound,
                timeout=self.notify_config.timeout,
                allow_webhook_domains=list(self.notify_config.allow_webhook_domains or []),
            ))
        self.tools.register(SpawnTool(manager=self.subagents))
        if self.cron_service:
            self.tools.register(CronTool(self.cron_service))
        if self.coding_config and self.coding_config.enabled:
            self.tools.register(CodingTool(
                working_dir=str(self.workspace),
                timeout=self.coding_config.timeout,
                api_key=self.coding_config.api_key,
                api_base=self.coding_config.api_base,
                model=self.coding_config.model,
            ))
        if self.browser_config and self.browser_config.enabled:
            from lemonclaw.agent.tools.browser import BrowserTool
            browser_tool = BrowserTool(
                timeout=self.browser_config.timeout,
                allowed_domains=self.browser_config.allowed_domains,
                session_name=self.browser_config.session_name or f"lc-{self.agent_id}",
                headed=self.browser_config.headed,
                content_boundaries=self.browser_config.content_boundaries,
                max_output=self.browser_config.max_output,
                workspace=self.workspace,
            )
            if browser_tool.available:
                self.tools.register(browser_tool)
            else:
                logger.warning("Browser tool enabled but agent-browser is not installed; skipping registration")

    async def _connect_mcp(self) -> None:
        """Connect to configured MCP servers (one-time, lazy)."""
        if self._mcp_connected or self._mcp_connecting or not self._mcp_servers:
            return
        self._mcp_connecting = True
        from lemonclaw.agent.tools.mcp import connect_mcp_servers
        try:
            self._mcp_stack = AsyncExitStack()
            await self._mcp_stack.__aenter__()
            await connect_mcp_servers(
                self._mcp_servers,
                self.tools,
                self._mcp_stack,
                workspace=self.workspace,
            )
            self._mcp_connected = True
        except Exception as e:
            logger.error("Failed to connect MCP servers (will retry next message): {}", e)
            if self._mcp_stack:
                try:
                    await self._mcp_stack.aclose()
                except Exception:
                    logger.debug("MCP stack close failed", exc_info=True)
                self._mcp_stack = None
        finally:
            self._mcp_connecting = False

    def _set_tool_context(
        self,
        channel: str,
        chat_id: str,
        message_id: str | None = None,
        delivery_context: dict[str, Any] | None = None,
        delivery_policy: dict[str, Any] | None = None,
        session_context: dict[str, Any] | None = None,
        session_key: str | None = None,
    ) -> None:
        """Update context for all tools that need routing info.

        *session_key* is forwarded verbatim to spawn/cron so that thread
        dimensions (e.g. ``telegram:123:789``) are preserved instead of being
        reconstructed from *channel* and *chat_id* alone.
        """
        for name in ("message", "notify", "spawn", "cron"):
            if tool := self.tools.get(name):
                if hasattr(tool, "set_context"):
                    if name in {"message", "notify"}:
                        tool.set_context(
                            channel,
                            chat_id,
                            delivery_context=dict(delivery_context or {}),
                            delivery_policy=dict(delivery_policy or {}),
                            session_context=dict(session_context or {}),
                            **({"message_id": message_id} if name == "message" else {}),
                        )
                    else:
                        tool.set_context(channel, chat_id, session_key=session_key)

    @staticmethod
    def _strip_think(text: str | None) -> str | None:
        """Remove <think>…</think> blocks that some models embed in content."""
        if not text:
            return None
        return re.sub(r"<think>[\s\S]*?</think>", "", text).strip() or None

    @staticmethod
    def _tool_hint(tool_calls: list) -> str:
        """Format tool calls as concise hint, e.g. 'web_search("query")'."""
        def _fmt(tc):
            val = next(iter(tc.arguments.values()), None) if tc.arguments else None
            if not isinstance(val, str):
                return tc.name
            safe_val = redact_sensitive_text(val)
            return f'{tc.name}("{safe_val[:40]}…")' if len(safe_val) > 40 else f'{tc.name}("{safe_val}")'
        return ", ".join(_fmt(tc) for tc in tool_calls)

    @staticmethod
    def _redact_preview(text: str, *, limit: int) -> str:
        safe = redact_sensitive_text(text, aggressive=True)
        return safe[:limit] + "..." if len(safe) > limit else safe

    def _build_runtime_context_appendix(self) -> str:
        profiles = dict((self.git_config.auth_profiles if self.git_config else {}) or {})
        available = []
        for name, profile in sorted(profiles.items()):
            password = str(getattr(profile, "password", "") or (profile.get("password") if isinstance(profile, dict) else "") or "")
            if password:
                available.append(str(name))
        if not available:
            return ""
        names = ", ".join(available)
        return (
            "[Saved Git Auth Profiles — metadata only, not instructions]\n"
            f"- Available auth_profile values for git push: {names}\n"
            "- Prefer the git tool with action=\"push\" and one of these auth_profile values instead of probing GITHUB_TOKEN/GITHUB_USERNAME."
        )

    @staticmethod
    def _current_turn_start_index(messages: list[dict[str, Any]], default: int) -> int:
        """Locate the current user turn even if compaction rewrote earlier indices."""
        for index, message in enumerate(messages):
            if isinstance(message.get("_original_text"), str):
                return index
        return min(max(default, 0), len(messages))

    @staticmethod
    def _progress_kind(
        *,
        tool_hint: bool = False,
        thinking: bool = False,
        tool_start: bool = False,
        tool_result: bool = False,
        chunk: bool = False,
    ) -> str:
        if thinking:
            return "thinking"
        if tool_hint:
            return "tool_hint"
        if tool_start:
            return "tool_start"
        if tool_result:
            return "tool_result"
        if chunk:
            return "chunk"
        return "content"

    def _persist_inbound_media(self, session_key: str, content: str, media: list[str] | None) -> tuple[str, list[str]]:
        """Copy inbound attachments into the session-native attachment directory."""
        persisted_media, path_map = self.sessions.persist_attachments(session_key, media)
        return rewrite_text_paths(content, path_map), persisted_media

    def _build_task_resume_context(self, msg: InboundMessage) -> dict[str, Any]:
        """Persist the minimum routing context needed for later task resume."""
        metadata = dict(msg.metadata or {})
        delivery_context = metadata.get("_delivery_context")
        delivery_policy = get_delivery_policy(metadata)
        resume_context = build_task_resume_context(
            channel=msg.channel,
            chat_id=str(msg.chat_id),
            sender_id=str(msg.sender_id),
            session_key=msg.session_key,
            timezone=str(metadata.get("timezone") or ""),
            run_mode=str(metadata.get("run_mode") or ""),
            session_context=dict(metadata.get("_session_context") or {}) if isinstance(metadata.get("_session_context"), dict) else None,
            message_id=str(metadata.get("message_id") or ""),
            delivery_context=dict(delivery_context) if isinstance(delivery_context, dict) else {},
            delivery_policy=dict(delivery_policy) if isinstance(delivery_policy, dict) else None,
        )
        runtime_correction = metadata.get("_runtime_correction")
        if isinstance(runtime_correction, dict) and runtime_correction:
            delivery_intent = runtime_correction.get("delivery_intent")
            resume_context["runtime_correction"] = {
                "kind": str(runtime_correction.get("kind") or ""),
                "supersedes_task_ids": [
                    str(item) for item in list(runtime_correction.get("supersedes_task_ids") or []) if str(item)
                ],
                "supersedes_task_stages": [
                    str(item) for item in list(runtime_correction.get("supersedes_task_stages") or []) if str(item)
                ],
                "continued_task_ids": [
                    str(item) for item in list(runtime_correction.get("continued_task_ids") or []) if str(item)
                ],
                "continued_task_stages": [
                    str(item) for item in list(runtime_correction.get("continued_task_stages") or []) if str(item)
                ],
                "interrupted_task_count": int(runtime_correction.get("interrupted_task_count") or 0),
                "continued_task_count": int(runtime_correction.get("continued_task_count") or 0),
                "requested_at_ms": int(runtime_correction.get("at_ms") or 0),
            }
            if isinstance(delivery_intent, dict) and delivery_intent:
                resume_context["runtime_correction"]["delivery_intent"] = dict(delivery_intent)
        return resume_context

    def _prepare_dispatch_metadata(self, msg: InboundMessage) -> dict[str, Any]:
        """Ensure tracked dispatch metadata exists before task orchestration decisions."""
        metadata = dict(msg.metadata or {})
        metadata.setdefault("_task_id", f"task_{uuid.uuid4().hex[:12]}")
        metadata.setdefault("_mode", self._infer_mode(msg))
        metadata.setdefault("run_mode", self._default_run_mode(channel=msg.channel, mode=str(metadata.get("_mode") or "")))
        metadata.setdefault("_agent_id", self.agent_id)
        msg.metadata = metadata
        return metadata

    def _session_has_running_work(
        self,
        session_key: str,
        *,
        exclude_task: asyncio.Task | None = None,
    ) -> bool:
        return any(
            task is not exclude_task and not task.done()
            for task in self._active_tasks.get(session_key, [])
        )

    @staticmethod
    def _is_command_message(content: str) -> bool:
        stripped = content.strip()
        return bool(stripped.startswith("/") and not stripped[1:2].isspace())

    @staticmethod
    def _default_run_mode(*, channel: str, mode: str) -> str:
        if mode in {"cron", "operator"} or channel in {"cron", "internal", "system"}:
            return "system"
        return "interactive"

    @staticmethod
    def _normalize_runtime_correction_content(content: str) -> tuple[str, str]:
        stripped = content.strip()
        lowered = stripped.lower()
        normalized = re.sub(r"\s+", " ", lowered)
        polite_prefixes = (
            "would you please",
            "could you please",
            "can you please",
            "can we please",
            "please",
            "pls",
            "kindly",
            "could you",
            "would you",
            "can you",
            "can we",
            "麻烦",
            "请",
            "帮我",
            "帮忙",
            "能否",
            "可以",
        )
        for _ in range(3):
            candidate = normalized
            for prefix in polite_prefixes:
                candidate = re.sub(
                    rf"^(?:{re.escape(prefix)})[\s,.;:!?，。！？、\-—]*",
                    "",
                    candidate,
                )
            candidate = candidate.lstrip(" \t\r\n,.;:!?，。！？、-—")
            if candidate == normalized:
                break
            normalized = candidate
        return normalized, lowered

    @staticmethod
    def _classify_runtime_correction(content: str) -> str:
        normalized, lowered = AgentLoop._normalize_runtime_correction_content(content)
        if not normalized:
            return "correction"

        interrupt_prefixes = (
            "stop",
            "cancel",
            "abort",
            "halt",
            "暂停",
            "停止",
            "取消",
            "先停",
        )
        if any(normalized.startswith(prefix) for prefix in interrupt_prefixes):
            return "interrupt"

        continue_prefixes = ("continue", "go on", "carry on", "继续", "接着")
        if any(normalized.startswith(prefix) for prefix in continue_prefixes):
            return "continue"

        constraint_markers = (
            "不要",
            "别",
            "先别",
            "只",
            "仅",
            "限制",
            "不要发",
            "不要提交",
            "不要推",
            "dry-run",
            "dry run",
            "don't",
            "do not",
            "only ",
            "without ",
            "skip ",
            "limit ",
        )
        if any(marker in lowered or marker in normalized for marker in constraint_markers):
            return "constraint_patch"

        correction_markers = (
            "改成",
            "改用",
            "换成",
            "换用",
            "改一下",
            "instead",
            "switch to",
            "change to",
            "replace with",
            "update to",
        )
        if any(marker in lowered or marker in normalized for marker in correction_markers):
            return "correction"

        return "correction"

    def _list_interruptible_session_tasks(
        self,
        session_key: str,
        *,
        exclude_task_id: str = "",
    ) -> list[dict[str, Any]]:
        active_ids = set(self._active_task_ids.get(session_key) or ())
        if active_ids:
            active_ids.discard(exclude_task_id)
            return [task for task_id in active_ids if (task := self.ledger.read_task(task_id))]

        active_statuses = {"pending", "running", "verifying", "waiting"}
        tasks = self.ledger.list_tasks(limit=20, session_key=session_key)
        visible: list[dict[str, Any]] = []
        for task in tasks:
            task_id = str(task.get("task_id") or "")
            if not task_id or task_id == exclude_task_id:
                continue
            if str(task.get("status") or "") not in active_statuses:
                continue
            visible.append(task)
        return visible

    async def _cancel_session_work(
        self,
        session_key: str,
        *,
        exclude_task: asyncio.Task | None = None,
        abandon_outbox: bool = False,
        outbox_source: str = "chat_command_stop",
        outbox_reason: str = "task stopped by /stop",
    ) -> int:
        """Cancel active tasks and subagents for a session without emitting UI copy."""
        stop_event = self._stop_events.get(session_key)
        if stop_event:
            stop_event.set()

        tasks = list(self._active_tasks.get(session_key, []))
        cancel_targets = [tk for tk in tasks if tk is not exclude_task]
        kept = [tk for tk in tasks if tk is exclude_task]
        if session_key in self._active_tasks:
            if kept:
                self._active_tasks[session_key] = kept
            else:
                self._active_tasks.pop(session_key, None)

        cancelled = sum(1 for tk in cancel_targets if not tk.done() and tk.cancel())
        for tk in cancel_targets:
            try:
                await tk
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.debug("Task ended with error during cancellation for session {}", session_key)
        sub_cancelled = await self.subagents.cancel_by_session(session_key)
        abandoned = 0
        if abandon_outbox:
            abandoned = len(
                self.ledger.abandon_outbox_events_for_session(
                    session_key,
                    source=outbox_source,
                    reason=outbox_reason,
                )
            )
        return cancelled + sub_cancelled + abandoned

    def _abandon_task_outbox_side_effects(
        self,
        task_id: str,
        *,
        session_key: str,
    ) -> int:
        """Terminalize queued side effects for a task that is being cancelled."""
        if not task_id:
            return 0

        source = self._session_cancel_reasons.get(session_key) or "task_cancelled"
        if source == "user_correction_interrupt":
            reason = "task interrupted by user correction"
        else:
            reason = "task cancelled"
        return len(
            self.ledger.abandon_outbox_events_for_task(
                task_id,
                source=source,
                reason=reason,
            )
        )

    def _annotate_runtime_correction(
        self,
        *,
        interrupted_tasks: list[dict[str, Any]],
        replacement_task_id: str,
        msg: InboundMessage,
        kind: str,
    ) -> None:
        if not interrupted_tasks:
            return

        preview = msg.content.strip()[:200]
        reason = f"user follow-up interrupted active task ({kind})"
        for task in interrupted_tasks:
            task_id = str(task.get("task_id") or "")
            if not task_id:
                continue
            metadata = dict(task.get("metadata") or {})
            details = {
                "kind": kind,
                "message_preview": preview,
                "replacement_task_id": replacement_task_id,
                "session_key": msg.session_key,
            }
            recovery = {
                "source": "session_user_correction",
                "reason": reason[:500],
                "requested_at_ms": int(time.time() * 1000),
                "action": "user_correction_interrupt",
                "manual_review_required": False,
                "correction_kind": kind,
                "replacement_task_id": replacement_task_id,
            }
            metadata["recovery"] = recovery
            self.ledger.append_recovery_history(
                metadata,
                source="session_user_correction",
                action="user_correction_interrupt",
                reason=reason,
                details=details,
            )
            self.ledger.update_task(task_id, metadata=metadata)

    @staticmethod
    def _collect_runtime_correction_stages(tasks: list[dict[str, Any]]) -> list[str]:
        stages: list[str] = []
        for task in tasks:
            stage = str(task.get("current_stage") or "").strip()
            if stage and stage not in stages:
                stages.append(stage)
        return stages

    @staticmethod
    def _build_runtime_correction_payload(
        *,
        kind: str,
        msg: InboundMessage,
        interrupted_tasks: list[dict[str, Any]],
        continued_tasks: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        continued_tasks = continued_tasks or []
        superseded_stages = AgentLoop._collect_runtime_correction_stages(interrupted_tasks)
        continued_stages = AgentLoop._collect_runtime_correction_stages(continued_tasks)
        payload = {
            "kind": kind,
            "message_preview": msg.content.strip()[:200],
            "supersedes_task_ids": [
                str(task.get("task_id") or "") for task in interrupted_tasks if task.get("task_id")
            ],
            "supersedes_task_stages": superseded_stages,
            "continued_task_ids": [
                str(task.get("task_id") or "") for task in continued_tasks if task.get("task_id")
            ],
            "continued_task_stages": continued_stages,
            "interrupted_task_count": len(interrupted_tasks),
            "continued_task_count": len(continued_tasks),
            "at_ms": int(time.time() * 1000),
        }
        delivery_policy = get_delivery_policy(msg.metadata)
        if isinstance(delivery_policy, dict) and delivery_policy:
            payload["delivery_intent"] = {"delivery_policy": dict(delivery_policy)}
        return payload

    def _append_runtime_correction_history(
        self,
        *,
        task_metadata: dict[str, Any],
        runtime_correction: dict[str, Any],
        session_key: str,
    ) -> dict[str, Any]:
        kind = str(runtime_correction.get("kind") or "").strip() or "correction"
        action = "runtime_correction_continue" if kind == "continue" else "runtime_correction_received"
        details = {
            "session_key": session_key,
            "correction_kind": kind,
            "interrupted_task_count": int(runtime_correction.get("interrupted_task_count") or 0),
            "continued_task_count": int(runtime_correction.get("continued_task_count") or 0),
            "supersedes_task_ids": [
                str(item) for item in list(runtime_correction.get("supersedes_task_ids") or []) if str(item)
            ],
            "supersedes_task_stages": [
                str(item) for item in list(runtime_correction.get("supersedes_task_stages") or []) if str(item)
            ],
            "continued_task_ids": [
                str(item) for item in list(runtime_correction.get("continued_task_ids") or []) if str(item)
            ],
            "continued_task_stages": [
                str(item) for item in list(runtime_correction.get("continued_task_stages") or []) if str(item)
            ],
        }
        if isinstance(runtime_correction.get("delivery_intent"), dict) and runtime_correction.get("delivery_intent"):
            details["delivery_intent"] = dict(runtime_correction["delivery_intent"])
        message_preview = str(runtime_correction.get("message_preview") or "").strip()
        reason = (
            f"user follow-up queued behind active task ({kind})"
            if kind == "continue"
            else f"user follow-up revised in-flight task ({kind})"
        )
        if message_preview:
            details["message_preview"] = message_preview
        self.ledger.append_recovery_history(
            task_metadata,
            source="session_user_correction",
            action=action,
            reason=reason,
            details=details,
            at_ms=int(runtime_correction.get("at_ms") or 0) or None,
        )
        return task_metadata

    async def _interrupt_active_session_for_correction(
        self,
        msg: InboundMessage,
        *,
        current_task: asyncio.Task | None = None,
    ) -> bool:
        """Turn an in-flight user follow-up into a lightweight correction interrupt."""
        if msg.channel in {"internal", "system"}:
            return False

        metadata = self._prepare_dispatch_metadata(msg)
        if bool(metadata.get("_resume_internal")):
            return False
        if self._is_command_message(msg.content):
            return False
        if not self._session_has_running_work(msg.session_key, exclude_task=current_task):
            return False

        interrupted_tasks = self._list_interruptible_session_tasks(
            msg.session_key,
            exclude_task_id=str(metadata.get("_task_id") or ""),
        )
        kind = self._classify_runtime_correction(msg.content)
        if kind == "continue":
            logger.info(
                "Runtime correction classified for session {}: kind={} queued_behind_tasks={}",
                msg.session_key,
                kind,
                len(interrupted_tasks),
            )
            metadata["_runtime_correction"] = self._build_runtime_correction_payload(
                kind=kind,
                msg=msg,
                interrupted_tasks=[],
                continued_tasks=interrupted_tasks,
            )
            msg.metadata = metadata
            return True
        self._session_cancel_reasons[msg.session_key] = "user_correction_interrupt"
        await self._cancel_session_work(
            msg.session_key,
            exclude_task=current_task,
            abandon_outbox=True,
            outbox_source="user_correction_interrupt",
            outbox_reason="task interrupted by user correction",
        )
        self._session_cancel_reasons.pop(msg.session_key, None)
        self._annotate_runtime_correction(
            interrupted_tasks=interrupted_tasks,
            replacement_task_id=str(metadata.get("_task_id") or ""),
            msg=msg,
            kind=kind,
        )
        logger.info(
            "Runtime correction classified for session {}: kind={} interrupted_tasks={}",
            msg.session_key,
            kind,
            len(interrupted_tasks),
        )
        metadata["_runtime_correction"] = self._build_runtime_correction_payload(
            kind=kind,
            msg=msg,
            interrupted_tasks=interrupted_tasks,
        )
        msg.metadata = metadata
        return True

    async def _dispatch_entry(self, msg: InboundMessage) -> None:
        current_task = asyncio.current_task()
        await self._interrupt_active_session_for_correction(msg, current_task=current_task)
        await self._dispatch(msg)

    def _spawn_dispatch_task(self, msg: InboundMessage) -> asyncio.Task:
        """Spawn a tracked dispatch task so /stop and recovery share the same path."""
        task = asyncio.create_task(self._dispatch_entry(msg))
        self._active_tasks.setdefault(msg.session_key, []).append(task)

        def _on_task_done(t: asyncio.Task, key: str = msg.session_key) -> None:
            try:
                if not t.cancelled():
                    exc = t.exception()
                    if exc is not None:
                        logger.opt(exception=exc).error(
                            "Dispatch task crashed before settlement (session={} channel={} sender={} chat={} preview={})",
                            key,
                            msg.channel,
                            msg.sender_id,
                            msg.chat_id,
                            self._redact_preview(msg.content, limit=120),
                        )
                        if self.trigger_runtime and isinstance(msg.metadata, dict):
                            trigger_id = str(msg.metadata.get("_trigger_id") or "")
                            if trigger_id:
                                self.trigger_runtime.finish_trigger(
                                    trigger_id,
                                    status="failed",
                                    error=str(exc)[:500],
                                    metadata={
                                        "session_key": key,
                                        "task_status": "dispatch_crashed",
                                        "task_stage": "dispatch_entry",
                                    },
                                )
            except Exception as callback_exc:  # pragma: no cover - defensive cleanup
                logger.opt(exception=callback_exc).error(
                    "Dispatch task completion callback failed (session={} channel={} sender={})",
                    key,
                    msg.channel,
                    msg.sender_id,
                )
            finally:
                tasks = self._active_tasks.get(key, [])
                if t in tasks:
                    tasks.remove(t)
                if not tasks and key in self._active_tasks:
                    del self._active_tasks[key]

        task.add_done_callback(_on_task_done)
        return task

    @staticmethod
    def _derive_chat_id_from_session_key(channel: str, session_key: str) -> str:
        prefix = f"{channel}:"
        if session_key.startswith(prefix):
            remainder = session_key[len(prefix):]
            return remainder.split(":", 1)[0] if ":" in remainder else remainder
        return session_key.split(":", 1)[-1] if ":" in session_key else session_key

    def _build_resume_prompt(self, task: dict[str, Any], candidate: dict[str, Any]) -> str:
        resume_step = candidate.get("resume_step") or {}
        step_name = str((resume_step or {}).get("name") or candidate.get("resume_from_step") or "task boundary")
        step_error = str((resume_step or {}).get("error") or task.get("error") or "").strip()
        checkpoint = str(((task.get("metadata") or {}).get("checkpoint_summary") or "")).strip()
        last_successful = str(task.get("last_successful_step") or "").strip()

        lines = [
            "System resume request: continue an interrupted task.",
            f"Original goal: {str(task.get('goal') or '').strip()}",
            f"Resume from step: {step_name}",
        ]
        if step_error:
            lines.append(f"Previous failure: {step_error}")
        if last_successful:
            lines.append(f"Last successful step: {last_successful}")
        if checkpoint:
            lines.append(f"Checkpoint summary: {checkpoint}")
        lines.extend([
            "Replayable failed steps were superseded before this resume. Do not repeat already-settled side effects.",
            "Continue from the failed point and finish the task.",
        ])
        return "\n".join(lines)

    async def execute_safe_resume(self, task_id: str, *, source: str) -> dict[str, Any] | None:
        """Execute a safe resume action, including real replay for replayable failed steps."""
        candidate = self.ledger.build_resume_candidate(task_id)
        if not candidate:
            return None
        if not candidate.get("safe_to_execute"):
            raise ValueError(str(candidate.get("reason") or "manual intervention required"))

        action = str(candidate.get("recommended_action") or "")
        if action != "replay_failed_steps":
            return self.ledger.execute_safe_resume(task_id, source=source)

        running = self._resume_tasks.get(task_id)
        if running is not None and not running.done():
            raise ValueError("resume already running for task")

        task = self.ledger.read_task(task_id)
        if not task:
            return None

        resume_context = dict(task.get("resume_context") or {})
        if not bool(resume_context.get("auto_resume_allowed", True)):
            raise ValueError(
                str(resume_context.get("resume_disabled_reason") or "automatic resume is disabled for this task")
            )
        delivery_context = resume_context.get("delivery_context")
        channel = str(resume_context.get("channel") or task.get("channel") or "")
        session_key = str(resume_context.get("session_key") or task.get("session_key") or "")
        chat_id = str(
            resume_context.get("chat_id")
            or (delivery_context.get("source_chat_id") if isinstance(delivery_context, dict) else "")
            or self._derive_chat_id_from_session_key(channel, session_key)
        )
        if not channel or not chat_id or not session_key:
            raise ValueError("resume executor lacks channel/chat/session context")

        prepared = self.ledger.prepare_replay_failed_steps(task_id, source=source)
        if not prepared:
            return None

        metadata: dict[str, Any] = {
            "_task_id": task_id,
            "_mode": str(task.get("mode") or "chat"),
            "_agent_id": str(task.get("agent_id") or self.agent_id),
            "_resume_internal": True,
            "_resume_source": source,
            "_resume_from_step": str(candidate.get("resume_from_step") or ""),
        }
        if isinstance(delivery_context, dict) and delivery_context:
            metadata["_delivery_context"] = dict(delivery_context)
        if resume_context.get("timezone"):
            metadata["timezone"] = str(resume_context["timezone"])
        if resume_context.get("run_mode"):
            metadata["run_mode"] = str(resume_context["run_mode"])
        if isinstance(resume_context.get("session_context"), dict) and resume_context.get("session_context"):
            metadata["_session_context"] = dict(resume_context["session_context"])
        if isinstance(resume_context.get("delivery_policy"), dict) and resume_context.get("delivery_policy"):
            metadata["_delivery_policy"] = dict(resume_context["delivery_policy"])
        if resume_context.get("message_id"):
            metadata["message_id"] = str(resume_context["message_id"])

        resume_msg = InboundMessage(
            channel=channel,
            sender_id=str(resume_context.get("sender_id") or "resume_executor"),
            chat_id=chat_id,
            content=self._build_resume_prompt(task, candidate),
            metadata=metadata,
            session_key_override=session_key,
        )
        try:
            dispatch_task = self._spawn_dispatch_task(resume_msg)
        except Exception as exc:
            self.ledger.rollback_prepared_replay_resume(
                task_id,
                source=source,
                reason=f"resume dispatch failed: {type(exc).__name__}: {exc}",
                superseded_steps=list(prepared.get("superseded_steps") or []),
            )
            raise ValueError(f"resume dispatch failed: {exc}") from exc
        self._resume_tasks[task_id] = dispatch_task

        def _clear_resume_task(t: asyncio.Task, resume_task_id: str = task_id) -> None:
            if self._resume_tasks.get(resume_task_id) is t:
                self._resume_tasks.pop(resume_task_id, None)

        dispatch_task.add_done_callback(_clear_resume_task)

        return {
            **candidate,
            "scheduled": True,
            "background": True,
            "superseded_steps": list(prepared.get("superseded_steps") or []),
            "reason": f"resume execution scheduled from {candidate.get('resume_from_step') or 'task boundary'}",
        }

    async def _run_agent_loop(
        self,
        initial_messages: list[dict],
        session_key: str = "",
        on_progress: Callable[..., Awaitable[None]] | None = None,
        on_chunk: Callable[..., Awaitable[None]] | None = None,
        on_tool_call: Callable[..., Awaitable[None]] | None = None,
        stop_event: asyncio.Event | None = None,
        session_model: str | None = None,
        lang: str = "en",
        tool_context_extra: dict | None = None,
    ) -> tuple[str | None, list[str], list[dict], TurnUsage]:
        """Run the agent iteration loop. Returns (final_content, tools_used, messages, turn_usage)."""
        _lang = lang
        effective_model = resolve_model_id(session_model or self.model) or session_model or self.model
        active_provider = self._provider_for_model(effective_model)
        messages = initial_messages
        turn_start_idx = self._current_turn_start_index(initial_messages, len(initial_messages))
        iteration = 0
        final_content = None
        tools_used: list[str] = []
        turn_usage = TurnUsage()
        _consecutive_errors: dict[str, int] = {}
        _refusal_count = 0
        max_refusals = 2  # track repeated tool errors
        max_consecutive_errors = 3

        while iteration < self.max_iterations:
            iteration += 1

            # Cooperative stop: check at the start of each iteration
            if stop_event and stop_event.is_set():
                final_content = final_content or t("task_stopped", _lang)
                break

            # Mid-loop compaction: tool calls can rapidly grow the context
            if iteration > 1:
                from lemonclaw.session.compaction import compact, needs_compaction
                if needs_compaction(messages, effective_model):
                    messages = await compact(messages, effective_model, active_provider)
                    turn_start_idx = self._current_turn_start_index(messages, turn_start_idx)

            try:
                response = await asyncio.wait_for(
                    active_provider.chat(
                        messages=messages,
                        tools=self.tools.get_definitions(),
                        model=effective_model,
                        temperature=self.temperature,
                        max_tokens=self.max_tokens,
                        on_chunk=on_chunk,
                    ),
                    timeout=self._LLM_CALL_TIMEOUT,
                )
            except asyncio.TimeoutError:
                logger.error("LLM call timed out after {}s (iteration {})", self._LLM_CALL_TIMEOUT, iteration)
                final_content = t("llm_timeout", _lang, timeout=self._LLM_CALL_TIMEOUT)
                break

            # Track token usage from this LLM call
            if response.usage:
                turn_usage.record(response.usage)

            if response.has_tool_calls:
                if on_progress:
                    # 6.1: Send thinking content before tool calls
                    if response.reasoning_content:
                        await on_progress(response.reasoning_content, thinking=True)
                    clean = self._strip_think(response.content)
                    if clean:
                        await on_progress(clean)
                    await on_progress(self._tool_hint(response.tool_calls), tool_hint=True)

                if on_tool_call:
                    await on_tool_call(response.tool_calls)

                tool_call_dicts = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments, ensure_ascii=False)
                        }
                    }
                    for tc in response.tool_calls
                ]
                messages = self.context.add_assistant_message(
                    messages, response.content, tool_call_dicts,
                    reasoning_content=response.reasoning_content,
                )

                # Cooperative stop: check before tool execution
                if stop_event and stop_event.is_set():
                    final_content = t("task_stopped", _lang)

                if final_content is None:
                    tool_ctx = dict(tool_context_extra or {})
                    if session_key:
                        tool_ctx["_session_key"] = session_key
                    tool_ctx["_react_iteration"] = iteration
                    if not tool_ctx:
                        tool_ctx = None

                    # Parallel execution when LLM returns multiple independent tool calls
                    if len(response.tool_calls) > 1:
                        # Log and send tool_start events for all calls
                        for tc in response.tool_calls:
                            tools_used.append(tc.name)
                            redacted_args = redact_sensitive_value(tc.arguments)
                            args_str = json.dumps(redacted_args, ensure_ascii=False)
                            logger.info("Tool call (parallel): {}({})", tc.name, args_str[:200])
                            if on_progress:
                                await on_progress(json.dumps({
                                    "name": tc.name, "arguments": redacted_args,
                                }, ensure_ascii=False), tool_start=True)

                        # Execute all in parallel
                        results = await asyncio.gather(*[
                            self.tools.execute(tc.name, tc.arguments, context=tool_ctx)
                            for tc in response.tool_calls
                        ], return_exceptions=True)

                        # Process results
                        successful_tool_names: set[str] = set()
                        cancel_requested = bool(stop_event and stop_event.is_set())
                        for tc, result in zip(response.tool_calls, results):
                            if isinstance(result, Exception):
                                result = f"Error executing {tc.name}: {result}"

                            empty_call_guidance = self._empty_tool_call_guidance(
                                tc.name,
                                tc.arguments,
                                result,
                                _lang,
                            )

                            if on_progress:
                                result_preview = self._redact_preview(str(result) if result else "", limit=500)
                                is_error = isinstance(result, str) and result.startswith("Error")
                                await on_progress(json.dumps({
                                    "name": tc.name, "result": result_preview, "error": is_error,
                                }, ensure_ascii=False), tool_result=True)

                            if isinstance(result, str) and result.startswith("Error"):
                                err_key = f"{tc.name}:{result[:80]}"
                                _consecutive_errors[err_key] = _consecutive_errors.get(err_key, 0) + 1
                                if empty_call_guidance:
                                    logger.warning(
                                        "Tool {} called with empty arguments; failing fast instead of retrying",
                                        tc.name,
                                    )
                                    final_content = empty_call_guidance
                                elif _consecutive_errors[err_key] >= max_consecutive_errors:
                                    logger.warning("Tool {} failed {} times with same error, breaking loop",
                                                   tc.name, max_consecutive_errors)
                                    final_content = t("tool_repeated_fail", _lang, name=tc.name)
                            else:
                                successful_tool_names.add(tc.name)

                            messages = self.context.add_tool_result(
                                messages, tc.id, tc.name, result
                            )
                        if successful_tool_names:
                            for key in list(_consecutive_errors.keys()):
                                if any(key.startswith(f"{name}:") for name in successful_tool_names):
                                    _consecutive_errors.pop(key, None)
                        if cancel_requested and final_content is None:
                            final_content = t("task_stopped", _lang)
                    else:
                        # Single tool call — sequential execution
                        for tool_call in response.tool_calls:
                            if stop_event and stop_event.is_set():
                                final_content = t("task_stopped", _lang)
                                break

                            tools_used.append(tool_call.name)
                            redacted_args = redact_sensitive_value(tool_call.arguments)
                            args_str = json.dumps(redacted_args, ensure_ascii=False)
                            logger.info("Tool call: {}({})", tool_call.name, args_str[:200])

                            if on_progress:
                                await on_progress(json.dumps({
                                    "name": tool_call.name,
                                    "arguments": redacted_args,
                                }, ensure_ascii=False), tool_start=True)

                            result = await self.tools.execute(
                                tool_call.name,
                                tool_call.arguments,
                                context=tool_ctx,
                            )

                            empty_call_guidance = self._empty_tool_call_guidance(
                                tool_call.name,
                                tool_call.arguments,
                                result,
                                _lang,
                            )

                            if on_progress:
                                result_preview = self._redact_preview(str(result) if result else "", limit=500)
                                is_error = isinstance(result, str) and result.startswith("Error")
                                await on_progress(json.dumps({
                                    "name": tool_call.name,
                                    "result": result_preview,
                                    "error": is_error,
                                }, ensure_ascii=False), tool_result=True)

                            if isinstance(result, str) and result.startswith("Error"):
                                err_key = f"{tool_call.name}:{result[:80]}"
                                _consecutive_errors[err_key] = _consecutive_errors.get(err_key, 0) + 1
                                if empty_call_guidance:
                                    logger.warning(
                                        "Tool {} called with empty arguments; failing fast instead of retrying",
                                        tool_call.name,
                                    )
                                    final_content = empty_call_guidance
                                elif _consecutive_errors[err_key] >= max_consecutive_errors:
                                    logger.warning("Tool {} failed {} times with same error, breaking loop",
                                                   tool_call.name, max_consecutive_errors)
                                    final_content = t("tool_repeated_fail", _lang, name=tool_call.name)
                            else:
                                _consecutive_errors.clear()

                            messages = self.context.add_tool_result(
                                messages, tool_call.id, tool_call.name, result
                            )

                if final_content is not None:
                    break
            else:
                # 6.1: Send thinking content for final response
                if on_progress and response.reasoning_content:
                    await on_progress(response.reasoning_content, thinking=True)

                clean = self._strip_think(response.content)
                # Detect model refusal loops: very short responses that refuse to engage
                if clean and len(clean) < 60 and self._REFUSAL_RE.search(clean):
                    _refusal_count += 1
                    if _refusal_count >= max_refusals:
                        # Stop retrying — return the refusal as-is
                        final_content = clean
                        break
                    # Inject a system nudge to break the refusal loop
                    messages.append({"role": "assistant", "content": clean})
                    messages.append({"role": "user", "content": (
                        "[System: The previous response was not helpful. "
                        "Please re-read the user's original message and provide a useful response.]"
                    )})
                    iteration += 1
                    continue  # Retry instead of returning the refusal

                if clean:
                    messages = self.context.add_assistant_message(
                        messages, clean, reasoning_content=response.reasoning_content,
                    )
                    final_content = clean
                else:
                    logger.warning(
                        "LLM returned empty non-tool response (model={} iteration={} session={})",
                        effective_model,
                        iteration,
                        session_key or "-",
                    )
                break

        if final_content is None and iteration >= self.max_iterations:
            logger.warning("Max iterations ({}) reached", self.max_iterations)
            final_content = t("max_iterations", _lang, n=self.max_iterations)

        # Fallback: extract last assistant text from messages if loop ended
        # without setting final_content (e.g. last iteration was tool_calls only).
        # Only consider assistant content generated during this turn; otherwise we
        # can accidentally replay a stale answer from earlier history.
        if final_content is None:
            turn_start_idx = self._current_turn_start_index(messages, turn_start_idx)
            for m in reversed(messages[turn_start_idx:]):
                if m.get("role") == "assistant" and m.get("content") and not m.get("tool_calls"):
                    candidate = self._strip_think(m["content"])
                    if candidate:
                        final_content = candidate
                        break

        return final_content, tools_used, messages, turn_usage

    async def run(self) -> None:
        """Run the agent loop, dispatching messages as tasks to stay responsive to /stop."""
        self._running = True
        await self._connect_mcp()
        logger.info("Agent loop started")

        while self._running:
            try:
                msg = await asyncio.wait_for(self.bus.consume_inbound(self.agent_id), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            if msg.content.strip().lower() == "/stop":
                await self._handle_stop(msg)
            else:
                self._spawn_dispatch_task(msg)

    async def _handle_stop(self, msg: InboundMessage) -> None:
        """Cancel all active tasks and subagents for the session."""
        total = await self._cancel_session_work(msg.session_key, abandon_outbox=True)
        lang = session_lang(self.sessions._load(msg.session_key))
        content = t("stop_tasks", lang, n=total) if total else t("stop_none", lang)
        await self.bus.publish_outbound(OutboundMessage(
            channel=msg.channel, chat_id=msg.chat_id, content=content,
            metadata=msg.metadata or {},
        ))

    async def stop_session(
        self,
        session_key: str,
        *,
        channel: str,
        chat_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Public helper for cooperative stop outside the inbound bus loop."""

        msg = InboundMessage(
            channel=channel,
            sender_id="operator",
            chat_id=chat_id,
            content="/stop",
            metadata=dict(metadata or {}),
            session_key_override=session_key,
        )
        await self._handle_stop(msg)
        tasks = self._active_tasks.get(session_key, [])
        return {
            "session_key": session_key,
            "running": sum(1 for task in tasks if not task.done()),
        }

    def _evict_idle_session_locks(self) -> None:
        """Remove oldest idle session locks when over the LRU limit."""
        evicted = 0
        max_scan = min(len(self._session_lock_order), 50)  # Cap scan to avoid O(n) sweep
        scanned = 0
        while len(self._session_locks) > self._MAX_SESSION_LOCKS and self._session_lock_order and scanned < max_scan:
            scanned += 1
            oldest = self._session_lock_order.pop(0)
            lock = self._session_locks.get(oldest)
            if lock and not lock.locked():
                del self._session_locks[oldest]
                self._stop_events.pop(oldest, None)
                self._consolidation_locks.pop(oldest, None)
                evicted += 1
            else:
                # Still in use, put it back at the end and keep scanning
                self._session_lock_order.append(oldest)
        if evicted:
            logger.debug("Evicted {} idle session locks (total: {})", evicted, len(self._session_locks))

    async def _dispatch(self, msg: InboundMessage) -> None:
        """Process a message under a per-session lock."""
        is_internal = msg.channel == "internal"
        request_id = (msg.metadata or {}).get("_request_id") if is_internal else None
        metadata = self._prepare_dispatch_metadata(msg)
        task_metadata = self._task_trigger_metadata(metadata)
        runtime_correction = metadata.get("_runtime_correction")
        if isinstance(runtime_correction, dict) and runtime_correction:
            task_metadata = {**task_metadata, "runtime_correction": dict(runtime_correction)}
            task_metadata = self._append_runtime_correction_history(
                task_metadata=task_metadata,
                runtime_correction=runtime_correction,
                session_key=msg.session_key,
            )
        task_id = str(metadata["_task_id"])
        self.ledger.ensure_task(
            task_id=task_id,
            session_key=msg.session_key,
            agent_id=self.agent_id,
            mode=str(metadata["_mode"]),
            channel=msg.channel,
            goal=msg.content[:500],
            current_stage="dispatch",
            resume_context=self._build_task_resume_context(msg),
            metadata=task_metadata or None,
        )
        self._link_trigger_task(metadata, task_id, msg.session_key)
        self._active_task_ids.setdefault(msg.session_key, set()).add(task_id)

        # Per-session lock: different sessions can run concurrently
        if msg.session_key not in self._session_locks:
            self._session_locks[msg.session_key] = asyncio.Lock()
            # LRU eviction: remove oldest idle locks when over limit
            if len(self._session_locks) > self._MAX_SESSION_LOCKS:
                self._evict_idle_session_locks()
        # Touch LRU order
        if msg.session_key in self._session_lock_order:
            self._session_lock_order.remove(msg.session_key)
        self._session_lock_order.append(msg.session_key)
        lock = self._session_locks[msg.session_key]

        # Create a fresh stop event for this dispatch
        stop_event = asyncio.Event()
        self._stop_events[msg.session_key] = stop_event

        try:
            async with lock:
                try:
                    response = await self._process_message(msg, stop_event=stop_event)
                    gate_result = finalize_task(self.ledger, str(metadata["_task_id"]))
                    self._finish_trigger_success(
                        metadata,
                        task_id=str(metadata["_task_id"]),
                        session_key=msg.session_key,
                        result_summary=(response.content if response else "")[:500],
                    )
                    if gate_result and gate_result.passed:
                        self._schedule_learning_promotion(
                            task_id=str(metadata["_task_id"]),
                            mode=str(metadata.get("_mode") or "chat"),
                            actor_identity=str(metadata.get("_actor_identity") or metadata.get("_agent_id") or self.agent_id),
                        )

                    # Internal request-response: resolve Future instead of outbound
                    if request_id:
                        content = response.content if response else ""
                        self.bus.resolve_response(request_id, content)
                        return

                    if response is not None:
                        # Ensure routing metadata (e.g. message_thread_id) propagates to outbound
                        if not response.metadata:
                            response.metadata = dict(msg.metadata or {})
                        # Use a copy for _final so we don't pollute the original metadata
                        if response.channel != "webui":
                            response.metadata = {**(response.metadata or {}), "_final": True}
                        await self.bus.publish_outbound(response)
                    else:
                        # MessageTool sent the reply directly — broadcast done to Activity Feed
                        if msg.channel != "webui" and self.activity_bus:
                            await self.activity_bus.broadcast({
                                "type": "done",
                                "session_key": msg.session_key,
                                "channel": msg.channel,
                                "role": "assistant",
                                "content": "",
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            })
                        if msg.channel == "cli":
                            await self.bus.publish_outbound(OutboundMessage(
                                channel=msg.channel, chat_id=msg.chat_id,
                                content="", metadata=msg.metadata or {},
                            ))
                except asyncio.CancelledError:
                    logger.info("Task cancelled for session {}", msg.session_key)
                    self._abandon_task_outbox_side_effects(
                        str(metadata["_task_id"]),
                        session_key=msg.session_key,
                    )
                    self.ledger.update_task(str(metadata["_task_id"]), status="abandoned", current_stage="cancelled")
                    self._finish_trigger_failure(
                        metadata,
                        task_id=str(metadata["_task_id"]),
                        session_key=msg.session_key,
                        error="cancelled",
                    )
                    if request_id:
                        self.bus.resolve_response(request_id, "[cancelled]")
                    if self._session_cancel_reasons.get(msg.session_key) == "user_correction_interrupt":
                        return None
                    raise
                except Exception as exc:
                    logger.exception("Error processing message for session {}", msg.session_key)
                    # Procedural memory: reflect on failure to learn from it
                    try:
                        active_model = resolve_model_id(self.sessions.get_or_create(msg.session_key).metadata.get("current_model") or self.model) or self.sessions.get_or_create(msg.session_key).metadata.get("current_model") or self.model
                        active_provider = self._provider_for_model(active_model)
                        await self.context.memory.procedural.reflect(
                            active_provider,
                            task_description=msg.content[:200],
                            error=str(exc)[:200],
                            model=active_model,
                        )
                    except Exception:
                        pass  # reflect is best-effort, never block error handling
                    self.ledger.update_task(
                        str(metadata["_task_id"]),
                        status="failed",
                        current_stage="error",
                        error=str(exc)[:500],
                    )
                    self._finish_trigger_failure(
                        metadata,
                        task_id=str(metadata["_task_id"]),
                        session_key=msg.session_key,
                        error=str(exc),
                    )
                    if request_id:
                        self.bus.resolve_response(request_id, "[error]")
                    else:
                        lang = session_lang(self.sessions._load(msg.session_key))
                        await self.bus.publish_outbound(OutboundMessage(
                            channel=msg.channel, chat_id=msg.chat_id,
                            content=t("error", lang),
                        ))
        finally:
            active_ids = self._active_task_ids.get(msg.session_key)
            if active_ids:
                active_ids.discard(task_id)
                if not active_ids:
                    self._active_task_ids.pop(msg.session_key, None)
            self._stop_events.pop(msg.session_key, None)

    @staticmethod
    def _infer_mode(msg: InboundMessage) -> str:
        return infer_mode(msg)

    def _build_tool_context_extra(
        self,
        *,
        channel: str,
        chat_id: str,
        metadata: dict[str, Any],
        message_turn_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build shared tool execution context for a message turn."""
        tool_context_extra = {
            "_task_id": metadata.get("_task_id"),
            "_mode": metadata.get("_mode", "chat"),
            "_agent_id": metadata.get("_agent_id", self.agent_id),
            "_tenant_id": str(metadata.get("_tenant_id", "")),
            "_actor_identity": str(metadata.get("_actor_identity", self.agent_id)),
            "_task_ledger": self.ledger,
            "_outbox_enabled": bool(getattr(self, "outbox_enabled", False)),
            "_default_channel": channel,
            "_default_chat_id": chat_id,
            "_default_message_id": metadata.get("message_id"),
            "_default_delivery_context": metadata.get("_delivery_context"),
            "_default_delivery_policy": get_delivery_policy(metadata),
            "_default_session_context": (
                dict(metadata.get("_session_context") or {})
                if isinstance(metadata.get("_session_context"), dict)
                else {}
            ),
            "_message_turn_state": message_turn_state,
        }
        outbound_sink = metadata.get("_outbound_sink")
        if outbound_sink:
            tool_context_extra["_outbound_sink"] = outbound_sink
        return tool_context_extra

    async def _resolve_lemondata_runtime_context(
        self,
        *,
        current_message: str,
        media: list[str] | None = None,
    ) -> str:
        return await asyncio.to_thread(build_lemondata_runtime_block, current_message, media)

    async def close_mcp(self) -> None:
        """Close MCP connections and tool resources."""
        if self._mcp_stack:
            try:
                await self._mcp_stack.aclose()
            except (RuntimeError, BaseExceptionGroup):
                pass  # MCP SDK cancel scope cleanup is noisy but harmless
            self._mcp_stack = None

        # Cleanup browser session if registered
        browser_tool = self.tools.get("browser")
        if browser_tool and hasattr(browser_tool, "cleanup"):
            await browser_tool.cleanup()

    async def _replace_tool(self, name: str, tool: Any | None, *, cleanup_old: bool = False) -> None:
        old_tool = self.tools.get(name)
        if cleanup_old and old_tool and hasattr(old_tool, "cleanup"):
            await old_tool.cleanup()
        self.tools.unregister(name)
        if tool is not None:
            self.tools.register(tool)

    def _build_exec_tool(self) -> ExecTool:
        return ExecTool(
            working_dir=str(self.workspace),
            timeout=self.exec_config.timeout,
            path_append=self.exec_config.path_append,
        )

    def _build_git_tool(self) -> GitTool:
        return GitTool(
            working_dir=str(self.workspace),
            timeout=self.git_config.timeout if self.git_config else 20,
            max_output=self.git_config.max_output if self.git_config else 50_000,
            auth_profiles={
                name: profile.model_dump(by_alias=False)
                for name, profile in dict(self.git_config.auth_profiles or {}).items()
            } if self.git_config else {},
        )

    def _build_web_search_tool(self) -> WebSearchTool:
        return WebSearchTool(
            api_key=self.brave_api_key,
            max_results=self.web_search_max_results,
        )

    def _build_http_tool(self) -> HTTPRequestTool | None:
        if not getattr(self, "http_config", None) or not self.http_config or not self.http_config.enabled:
            return None
        return HTTPRequestTool(
            timeout=self.http_config.timeout,
            allow_domains=list(self.http_config.allow_domains or []),
            auth_profiles=dict(self.http_config.auth_profiles or {}),
        )

    def _build_notify_tool(self) -> NotifyTool | None:
        if not getattr(self, "notify_config", None) or not self.notify_config or not self.notify_config.enabled:
            return None
        return NotifyTool(
            send_callback=self.bus.publish_outbound,
            timeout=self.notify_config.timeout,
            allow_webhook_domains=list(self.notify_config.allow_webhook_domains or []),
        )

    def _build_db_tool(self) -> DBTool | None:
        if not getattr(self, "db_config", None) or not self.db_config or not self.db_config.enabled:
            return None
        return DBTool(
            timeout=self.db_config.timeout,
            sqlite_profiles=dict(self.db_config.sqlite_profiles or {}),
            postgres_profiles={
                name: profile.model_dump(by_alias=False)
                for name, profile in dict(self.db_config.postgres_profiles or {}).items()
            },
        )

    def _build_k8s_tool(self) -> K8sTool | None:
        if not getattr(self, "k8s_config", None) or not self.k8s_config or not self.k8s_config.enabled:
            return None
        return K8sTool(
            timeout=self.k8s_config.timeout,
            default_namespace=self.k8s_config.default_namespace,
            allowed_namespaces=list(self.k8s_config.allowed_namespaces or []),
            kubeconfig=self.k8s_config.kubeconfig,
            context=self.k8s_config.context,
            max_items=self.k8s_config.max_items,
            max_output=self.k8s_config.max_output,
        )

    def _build_coding_tool(self) -> CodingTool | None:
        if not self.coding_config or not self.coding_config.enabled:
            return None
        return CodingTool(
            working_dir=str(self.workspace),
            timeout=self.coding_config.timeout,
            api_key=self.coding_config.api_key,
            api_base=self.coding_config.api_base,
            model=self.coding_config.model,
        )

    def _build_browser_tool(self) -> Any | None:
        if not self.browser_config or not self.browser_config.enabled:
            return None
        from lemonclaw.agent.tools.browser import BrowserTool

        browser_tool = BrowserTool(
            timeout=self.browser_config.timeout,
            allowed_domains=self.browser_config.allowed_domains,
            session_name=self.browser_config.session_name or f"lc-{self.agent_id}",
            headed=self.browser_config.headed,
            content_boundaries=self.browser_config.content_boundaries,
            max_output=self.browser_config.max_output,
            workspace=self.workspace,
        )
        if not browser_tool.available:
            logger.warning("Browser tool enabled but agent-browser is not installed; skipping registration")
            return None
        return browser_tool

    async def refresh_runtime_config(self, config: Any, *, changed_paths: list[str]) -> dict[str, dict[str, Any]]:
        self.channels_config = config.channels
        self.exec_config = config.tools.exec
        self.http_config = config.tools.http
        self.git_config = config.tools.git
        self.notify_config = config.tools.notify
        self.db_config = config.tools.db
        self.k8s_config = config.tools.k8s
        self.coding_config = config.tools.coding
        self.browser_config = config.tools.browser
        self.brave_api_key = config.tools.web.search.api_key or None
        self.web_search_max_results = config.tools.web.search.max_results

        changed_tool_groups: set[str] = set()
        if any(path.startswith("tools.web.search") for path in changed_paths):
            changed_tool_groups.add("web_search")
        for tool_name in ("exec", "http", "git", "notify", "db", "k8s", "coding", "browser"):
            if any(path == f"tools.{tool_name}" or path.startswith(f"tools.{tool_name}.") for path in changed_paths):
                changed_tool_groups.add(tool_name)

        results: dict[str, dict[str, Any]] = {}
        for tool_name in sorted(changed_tool_groups):
            try:
                if tool_name == "web_search":
                    await self._replace_tool("web_search", self._build_web_search_tool())
                    results[tool_name] = {"status": "reloaded", "enabled": True}
                elif tool_name == "exec":
                    await self._replace_tool("exec", self._build_exec_tool())
                    results[tool_name] = {"status": "reloaded", "enabled": True}
                elif tool_name == "http":
                    tool = self._build_http_tool()
                    await self._replace_tool("http_request", tool)
                    results[tool_name] = {"status": "reloaded" if tool else "disabled", "enabled": bool(tool)}
                elif tool_name == "git":
                    await self._replace_tool("git", self._build_git_tool())
                    results[tool_name] = {"status": "reloaded", "enabled": True}
                elif tool_name == "notify":
                    tool = self._build_notify_tool()
                    await self._replace_tool("notify", tool)
                    results[tool_name] = {"status": "reloaded" if tool else "disabled", "enabled": bool(tool)}
                elif tool_name == "db":
                    tool = self._build_db_tool()
                    await self._replace_tool("db", tool)
                    results[tool_name] = {"status": "reloaded" if tool else "disabled", "enabled": bool(tool)}
                elif tool_name == "k8s":
                    tool = self._build_k8s_tool()
                    await self._replace_tool("k8s", tool)
                    results[tool_name] = {"status": "reloaded" if tool else "disabled", "enabled": bool(tool)}
                elif tool_name == "coding":
                    tool = self._build_coding_tool()
                    await self._replace_tool("coding", tool)
                    results[tool_name] = {"status": "reloaded" if tool else "disabled", "enabled": bool(tool)}
                elif tool_name == "browser":
                    tool = self._build_browser_tool()
                    await self._replace_tool("browser", tool, cleanup_old=True)
                    results[tool_name] = {"status": "reloaded" if tool else "disabled", "enabled": bool(tool)}
            except Exception as exc:
                logger.error("Runtime tool refresh failed for {}: {}", tool_name, exc)
                results[tool_name] = {"status": "failed", "enabled": False, "error": str(exc)}
        return results

    def stop(self) -> None:
        """Stop the agent loop."""
        self._running = False
        logger.info("Agent loop stopping")

    async def _process_message(
        self,
        msg: InboundMessage,
        session_key: str | None = None,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
        on_chunk: Callable[..., Awaitable[None]] | None = None,
        stop_event: asyncio.Event | None = None,
    ) -> OutboundMessage | None:
        """Process a single inbound message and return the response."""
        # System messages: parse origin from chat_id ("channel:chat_id")
        if msg.channel == "system":
            channel, chat_id = (msg.chat_id.split(":", 1) if ":" in msg.chat_id
                                else ("cli", msg.chat_id))
            logger.info("Processing system message from {}", msg.sender_id)
            key = session_key or msg.session_key
            session = self.sessions.get_or_create(key)
            session_model = self._normalize_session_model(session)
            active_provider = self._provider_for_model(session_model or self.model)
            self.context.memory.set_provider(active_provider)
            self._set_tool_context(
                channel,
                chat_id,
                msg.metadata.get("message_id"),
                session_context=dict((msg.metadata or {}).get("_session_context") or {}),
                session_key=key,
            )
            history = session.get_history(max_messages=self.memory_window)
            memory_ctx, rules_ctx, retrieval_meta = await self.context.resolve_retrieval_context(msg.content)
            lemondata_ctx = await self._resolve_lemondata_runtime_context(
                current_message=msg.content,
                media=None,
            )
            logger.debug("Retrieval [{}]: {}", key, retrieval_meta)
            messages = self.context.build_messages(
                history=history,
                current_message=msg.content, channel=channel, chat_id=chat_id,
                timezone=msg.metadata.get("timezone") or self.default_timezone,
                memory_context_override=memory_ctx,
                rules_context_override=rules_ctx,
                runtime_context_appendix=self._build_runtime_context_appendix(),
                lemondata_context_override=lemondata_ctx,
                skip_local_retrieval=True,
            )
            # Token-level compaction for system messages too
            from lemonclaw.session.compaction import compact, needs_compaction
            if needs_compaction(messages, session_model or self.model):
                messages = await compact(messages, session_model or self.model, active_provider)
            metadata = dict(msg.metadata or {})
            tool_context_extra = self._build_tool_context_extra(
                channel=channel,
                chat_id=chat_id,
                metadata=metadata,
            )
            final_content, _, all_msgs, turn_usage = await self._run_agent_loop(
                messages, session_key=key, stop_event=stop_event, session_model=session_model,
                lang=session_lang(session), tool_context_extra=tool_context_extra,
            )
            self._save_turn(session, all_msgs, 1 + len(history))
            # Record usage for system messages
            if turn_usage.llm_calls:
                self.usage_tracker.record_turn(key, turn_usage, session.metadata)
            self.sessions.save(session)
            return OutboundMessage(
                channel=channel,
                chat_id=chat_id,
                content=final_content or t("bg_task_done", session_lang(session)),
                metadata={**dict(msg.metadata or {}), "_agentbridge_skip_session_persist": True},
            )

        key = session_key or msg.session_key
        task_id = str((msg.metadata or {}).get("_task_id", ""))
        resume_internal = bool((msg.metadata or {}).get("_resume_internal"))
        if task_id:
            self.ledger.update_task(
                task_id,
                current_stage="resume_execute" if resume_internal else "process_message",
                status="running",
            )
        if msg.media:
            msg.content, msg.media = self._persist_inbound_media(key, msg.content, list(msg.media or []))

        session = self.sessions.get_or_create(key)
        session_model = self._normalize_session_model(session)
        active_provider = self._provider_for_model(session_model or self.model)
        self.context.memory.set_provider(active_provider)

        # Auto-detect language from first message if not set
        if "lang" not in session.metadata:
            session.metadata["lang"] = detect_lang(msg.content)

        lang = session_lang(session)
        safe_user_content = redact_sensitive_text(msg.content)
        logger.info(
            "Processing message from {}:{}: {}",
            msg.channel,
            msg.sender_id,
            self._redact_preview(msg.content, limit=80),
        )

        if msg.channel != "webui" and self.activity_bus and not resume_internal:
            await self.activity_bus.broadcast({
                "type": "message",
                "session_key": key,
                "channel": msg.channel,
                "role": "user",
                "content": safe_user_content,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        # Empty message guard — don't waste tokens on blank input
        if not msg.content.strip():
            reply = self._command_reply(msg, t("empty_message", lang), kind="empty_message", level="warning")
            self._persist_simple_reply(session, msg.content, reply, kind="empty_message")
            return reply

        # Slash commands
        cmd = msg.content.strip().lower()
        if cmd == "/new":
            lock = self._consolidation_locks.setdefault(session.key, asyncio.Lock())
            try:
                async with lock:
                    snapshot_messages = copy.deepcopy(session.messages[session.last_consolidated :])
                    self._consolidation_epochs[session.key] = self._consolidation_epochs.get(session.key, 0) + 1
                    if snapshot_messages:
                        archive_snapshot = self._clone_session(
                            session,
                            messages=snapshot_messages,
                            last_consolidated=0,
                        )
                        self._schedule_archive_snapshot(session.key, archive_snapshot)

                    # Archive old session file so it remains visible in activity feed,
                    # then create a fresh session with the same key.
                    self.sessions.archive_session(session.key)
                    session.clear()
                    session.metadata.pop("current_model", None)
                    self.sessions.save(session)
                    self.sessions.invalidate(session.key)
            except Exception:
                logger.exception("/new archival setup failed for {}", session.key)
                return OutboundMessage(
                    channel=msg.channel, chat_id=msg.chat_id,
                    content=t("memory_archival_failed", lang),
                )
            finally:
                if not lock.locked():
                    self._consolidation_locks.pop(session.key, None)

            return self._command_reply(msg, t("new_session", lang), kind="new_session")
        if cmd == "/usage":
            reply = self._command_reply(msg, self.usage_tracker.format_session_usage(session.metadata), kind="usage")
            self._persist_simple_reply(session, msg.content, reply, kind="usage")
            return reply
        if cmd == "/help":
            reply = self._command_reply(msg, t("help", lang), kind="help")
            self._persist_simple_reply(session, msg.content, reply, kind="help")
            return reply
        if cmd == "/runtime" or cmd.startswith("/runtime "):
            reply = self._handle_runtime_command(msg, lang)
            self._persist_simple_reply(session, msg.content, reply, kind="runtime")
            return reply
        if cmd == "/channel" or cmd.startswith("/channel "):
            reply = await self._handle_channel_command(msg, lang)
            self._persist_simple_reply(session, msg.content, reply, kind="channel")
            return reply
        if cmd == "/tasks" or cmd.startswith("/tasks "):
            reply = self._handle_tasks_command(msg, lang)
            self._persist_simple_reply(session, msg.content, reply, kind="tasks")
            return reply
        if cmd == "/recovery" or cmd.startswith("/recovery "):
            reply = self._handle_recovery_command(msg, lang)
            self._persist_simple_reply(session, msg.content, reply, kind="recovery")
            return reply
        if cmd == "/resume" or cmd.startswith("/resume "):
            reply = await self._handle_resume_command(msg, lang)
            self._persist_simple_reply(session, msg.content, reply, kind="resume")
            return reply
        if cmd == "/retry-outbox" or cmd.startswith("/retry-outbox "):
            reply = await self._handle_retry_outbox_command(msg, lang)
            self._persist_simple_reply(session, msg.content, reply, kind="retry_outbox")
            return reply
        if cmd == "/recheck" or cmd.startswith("/recheck "):
            reply = await self._handle_recheck_command(msg, lang)
            self._persist_simple_reply(session, msg.content, reply, kind="recheck")
            return reply
        if cmd == "/abandon" or cmd.startswith("/abandon "):
            reply = self._handle_abandon_command(msg, lang)
            self._persist_simple_reply(session, msg.content, reply, kind="abandon")
            return reply
        if cmd == "/export" or cmd.startswith("/export "):
            reply = self._handle_export_command(msg, lang)
            self._persist_simple_reply(session, msg.content, reply, kind="export")
            return reply
        if cmd == "/bundle" or cmd.startswith("/bundle "):
            reply = self._handle_bundle_command(msg, lang)
            self._persist_simple_reply(session, msg.content, reply, kind="bundle")
            return reply
        if cmd == "/postmortem" or cmd.startswith("/postmortem "):
            reply = self._handle_postmortem_command(msg, lang)
            self._persist_simple_reply(session, msg.content, reply, kind="postmortem")
            return reply
        if cmd == "/kb" or cmd.startswith("/kb "):
            reply = self._handle_kb_command(msg, lang)
            self._persist_simple_reply(session, msg.content, reply, kind="kb_search")
            return reply
        if cmd == "/model" or cmd.startswith("/model "):
            reply = self._handle_model_command(msg, session, lang)
            self._persist_simple_reply(session, msg.content, reply, kind="model_list")
            return reply
        if cmd == "/git-auth" or cmd.startswith("/git-auth "):
            reply = self._handle_git_auth_command(msg, lang)
            self._persist_simple_reply(session, msg.content, reply, kind="git_auth")
            return reply
        # Unknown slash command guard
        if cmd.startswith("/") and not cmd[1:2].isspace():
            known = ("/new", "/usage", "/help", "/runtime", "/channel", "/tasks", "/recovery", "/resume", "/retry-outbox", "/recheck", "/abandon", "/export", "/bundle", "/postmortem", "/kb", "/model", "/git-auth", "/stop")
            first_word = cmd.split()[0]
            if first_word not in known:
                reply = self._command_reply(msg, t("unknown_command", lang, cmd=first_word), kind="unknown_command", level="warning")
                self._persist_simple_reply(session, msg.content, reply, kind="unknown_command")
                return reply

        # Orchestrator intercept: complex tasks get split & delegated
        if self.orchestrator and not msg.channel == "internal":
            try:
                orchestrated = await self.orchestrator.handle_message(msg)
                if orchestrated is not None:
                    # Complex task handled by Conductor — save result to session
                    session.messages.append({
                        "role": "user", "content": msg.content,
                        "timestamp": datetime.now().isoformat(),
                    })
                    session.messages.append({
                        "role": "assistant", "content": orchestrated,
                        "timestamp": datetime.now().isoformat(),
                    })
                    session.updated_at = datetime.now()
                    self.sessions.save(session)
                    return OutboundMessage(
                        channel=msg.channel, chat_id=msg.chat_id,
                        content=orchestrated, metadata=msg.metadata or {},
                    )
            except Exception as e:
                logger.warning("Orchestrator failed, falling back to single agent: {}", e)

        unconsolidated = len(session.messages) - session.last_consolidated
        if (unconsolidated >= self.memory_window and session.key not in self._consolidating):
            self._consolidating.add(session.key)
            self._schedule_background_consolidation(session.key)

        self._set_tool_context(
            msg.channel,
            msg.chat_id,
            msg.metadata.get("message_id"),
            delivery_context=dict((msg.metadata or {}).get("_delivery_context") or {}),
            delivery_policy=get_delivery_policy(msg.metadata),
            session_context=dict((msg.metadata or {}).get("_session_context") or {}),
            session_key=key,
        )
        message_turn_state: dict[str, Any] | None = None
        if message_tool := self.tools.get("message"):
            if isinstance(message_tool, MessageTool):
                message_turn_state = message_tool.start_turn()

        history = session.get_history(max_messages=self.memory_window)
        memory_ctx, rules_ctx, retrieval_meta = await self.context.resolve_retrieval_context(msg.content)
        memory_ctx, retrieval_meta = self._append_agentbridge_repo_change_memory(
            msg=msg,
            memory_ctx=memory_ctx,
            retrieval_meta=retrieval_meta,
        )
        lemondata_ctx = await self._resolve_lemondata_runtime_context(
            current_message=msg.content,
            media=msg.media if msg.media else None,
        )
        logger.debug("Retrieval [{}]: {}", key, retrieval_meta)
        if task_id:
            self._record_retrieval_meta(task_id, retrieval_meta)
        initial_messages = self.context.build_messages(
            history=history,
            current_message=msg.content,
            media=msg.media if msg.media else None,
            channel=msg.channel, chat_id=msg.chat_id,
            timezone=msg.metadata.get("timezone") or self.default_timezone,
            mode=str(msg.metadata.get("_mode", "chat")),
            session_prompt_override=str(session.metadata.get("system_prompt_override", "")),
            memory_context_override=memory_ctx,
            rules_context_override=rules_ctx,
            runtime_context_appendix=self._build_runtime_context_appendix(),
            lemondata_context_override=lemondata_ctx,
            skip_local_retrieval=True,
        )

        # Token-level compaction: summarize middle messages if over threshold
        from lemonclaw.session.compaction import compact, needs_compaction
        if needs_compaction(initial_messages, session_model or self.model):
            initial_messages = await compact(
                initial_messages, session_model or self.model, active_provider,
            )
        initial_message_count = len(initial_messages)

        async def _bus_progress(content: str, *, tool_hint: bool = False,
                                thinking: bool = False, tool_start: bool = False,
                                tool_result: bool = False) -> None:
            meta = dict(msg.metadata or {})
            meta["_progress"] = True
            meta["_progress_kind"] = self._progress_kind(
                tool_hint=tool_hint,
                thinking=thinking,
                tool_start=tool_start,
                tool_result=tool_result,
            )
            meta["_tool_hint"] = tool_hint
            meta["_thinking"] = thinking
            meta["_tool_start"] = tool_start
            meta["_tool_result"] = tool_result
            await self.bus.publish_outbound(OutboundMessage(
                channel=msg.channel, chat_id=msg.chat_id, content=content, metadata=meta,
            ))

        async def _bus_chunk(content: str, *, first: bool = False) -> None:
            meta = dict(msg.metadata or {})
            meta["_progress"] = True
            meta["_chunk"] = True
            meta["_progress_kind"] = self._progress_kind(chunk=True)
            if first:
                meta["_chunk_first"] = True
            await self.bus.publish_outbound(OutboundMessage(
                channel=msg.channel, chat_id=msg.chat_id, content=content, metadata=meta,
            ))

        async def _activity_tool_call(tool_calls: list) -> None:
            if msg.channel != "webui" and self.activity_bus:
                await self.activity_bus.broadcast({
                    "type": "tool_call",
                    "session_key": msg.session_key,
                    "channel": msg.channel,
                    "role": "assistant",
                    "content": self._tool_hint(tool_calls),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

        metadata = dict(msg.metadata or {})
        tool_context_extra = self._build_tool_context_extra(
            channel=msg.channel,
            chat_id=msg.chat_id,
            metadata=metadata,
            message_turn_state=message_turn_state,
        )

        final_content, _, all_msgs, turn_usage = await self._run_agent_loop(
            initial_messages, session_key=key, on_progress=on_progress or _bus_progress,
            on_chunk=on_chunk or _bus_chunk,
            on_tool_call=_activity_tool_call,
            stop_event=stop_event, session_model=session_model, lang=lang,
            tool_context_extra=tool_context_extra,
        )

        if final_content is None:
            final_content = t("no_response", lang)

        save_skip = initial_message_count if resume_internal else (1 + len(history))
        self._save_turn(session, all_msgs, save_skip, turn_media=list(msg.media or []))

        # Record usage and check budgets
        alerts: list[str] = []
        if turn_usage.llm_calls:
            alerts = self.usage_tracker.record_turn(key, turn_usage, session.metadata)
        self.sessions.save(session)

        # Send budget alerts as separate messages
        for alert in alerts:
            await self.bus.publish_outbound(OutboundMessage(
                channel=msg.channel, chat_id=msg.chat_id, content=alert,
            ))

        if isinstance(message_turn_state, dict) and message_turn_state.get("sent"):
            for sent in message_turn_state.get("messages", []):
                session.messages.append(serialize_ui_message({
                    "role": "assistant",
                    "content": sent.content,
                    "media": list(sent.media or []),
                    "timestamp": datetime.now().isoformat(),
                }))
            self.sessions.save(session)
            return None

        logger.info(
            "Response to {}:{}: {}",
            msg.channel,
            msg.sender_id,
            self._redact_preview(final_content, limit=120),
        )
        return OutboundMessage(
            channel=msg.channel, chat_id=msg.chat_id, content=final_content,
            metadata=msg.metadata or {},
        )

    def _session_has_messages(self, session: Session) -> bool:
        return bool(session and session.messages)

    def _requires_new_session_for_model_switch(self, session: Session, target_model: str) -> bool:
        current_model = self._normalize_session_model(session) or self.model
        if not current_model or not self._session_has_messages(session):
            return False
        resolved_target = resolve_model_id(target_model) or target_model
        return provider_family_for_model(current_model) != provider_family_for_model(resolved_target)

    def _reset_session_context(self, session: Session) -> None:
        session.messages = []
        session.last_consolidated = 0

    def _handle_model_command(self, msg: InboundMessage, session: Session, lang: str = "en") -> OutboundMessage:
        """Handle /model [name] — list models or switch the session model."""
        arg = msg.content.strip()[6:].strip()  # strip "/model" prefix

        if not arg:
            current = self._normalize_session_model(session) or self.model
            if current and session.metadata.get("current_model") != current:
                session.metadata["current_model"] = current
                self.sessions.save(session)
            return self._command_reply(msg, format_model_list(current), kind="model_list", extra_meta={"_command": "model_list", "_current_model": current})

        match = fuzzy_match(arg)
        if not match:
            return self._command_reply(msg, t("no_model_match", lang, arg=arg), kind="model_error", level="warning")

        reset_context = self._requires_new_session_for_model_switch(session, match.id)
        if reset_context:
            self._reset_session_context(session)

        session.metadata["current_model"] = match.id
        self.sessions.save(session)

        # Also update global default (D5/R7: /model = same as Settings tab)
        self.update_defaults(model=match.id)
        # Persist to config.json so it survives restart
        self._persist_model_default(match.id)

        reply_key = "model_switched_new_context" if reset_context else "model_switched"
        return self._command_reply(msg, t(reply_key, lang, label=match.label, id=match.id, desc=match.description), kind="model_switched", extra_meta={"_command": "model_switched", "_current_model": match.id})

    def _handle_git_auth_command(self, msg: InboundMessage, lang: str = "en") -> OutboundMessage:
        raw = msg.content.strip()[9:].strip()
        if not raw:
            return self._command_reply(msg, t("git_auth_usage", lang), kind="git_auth_help", level="warning")

        lowered = raw.lower()
        if lowered == "list" or lowered.startswith("list "):
            return self._command_reply(msg, self._git_auth_list_sync(lang=lang), kind="git_auth_list")
        if lowered.startswith("show "):
            payload = raw[5:].strip()
            result, level = self._git_auth_show_sync(payload, lang=lang)
            return self._command_reply(msg, result, kind="git_auth_show", level=level)
        if lowered.startswith("delete ") or lowered.startswith("remove "):
            payload = raw.split(" ", 1)[1].strip() if " " in raw else ""
            result, level = self._git_auth_delete_sync(payload, lang=lang)
            return self._command_reply(msg, result, kind="git_auth_delete", level=level)
        if lowered.startswith("set ") or lowered.startswith("save ") or lowered.startswith("add "):
            payload = raw.split(" ", 1)[1].strip() if " " in raw else ""
            result, level = self._git_auth_set_sync(payload, lang=lang)
            return self._command_reply(msg, result, kind="git_auth_set", level=level)
        return self._command_reply(msg, t("git_auth_usage", lang), kind="git_auth_help", level="warning")

    def _handle_tasks_command(self, msg: InboundMessage, lang: str = "en") -> OutboundMessage:
        raw = msg.content.strip()[6:].strip()
        limit = 5
        if raw:
            try:
                limit = min(max(int(raw), 1), 10)
            except ValueError:
                return self._command_reply(msg, t("tasks_usage", lang), kind="tasks_help", level="warning")

        tasks = self.ledger.list_tasks(limit=20, session_key=msg.session_key)
        if not tasks:
            return self._command_reply(msg, t("tasks_empty", lang), kind="tasks", level="warning")

        lines = [t("tasks_header", lang)]
        for task in tasks[:limit]:
            task_id = str(task.get("task_id") or "")
            if not task_id:
                continue
            candidate = self.ledger.build_resume_candidate(task_id) or {}
            reason = str(candidate.get("reason") or "no recovery hint")
            if len(reason) > 120:
                reason = reason[:117] + "..."
            lines.append(
                t(
                    "tasks_item",
                    lang,
                    task_id=task_id,
                    status=str(task.get("status") or "unknown"),
                    stage=str(task.get("current_stage") or "unknown"),
                    action=str(candidate.get("recommended_action") or "manual_review"),
                    safe="yes" if candidate.get("safe_to_execute") else "no",
                    reason=reason,
                )
            )
        return self._command_reply(msg, "\n".join(lines), kind="tasks")

    def _handle_recovery_command(self, msg: InboundMessage, lang: str = "en") -> OutboundMessage:
        raw = msg.content.strip()[9:].strip()
        limit = 5
        manual_only = False
        if raw:
            tokens = raw.split()
            for token in tokens:
                lowered = token.lower()
                if lowered in {"manual", "manual-only", "manual_review"}:
                    manual_only = True
                    continue
                try:
                    limit = min(max(int(token), 1), 10)
                except ValueError:
                    return self._command_reply(msg, t("recovery_usage", lang), kind="recovery_help", level="warning")

        recovery_tasks = [
            task
            for task in self.ledger.list_recovery_tasks(limit=500, manual_review_only=manual_only)
            if str(task.get("session_key") or "") == msg.session_key
        ]
        if not recovery_tasks:
            return self._command_reply(msg, t("recovery_empty", lang), kind="recovery", level="warning")

        visible = [
            item
            for item in self.ledger.list_operator_queue_view(limit=500, manual_review_only=manual_only)
            if str(item.get("session_key") or "") == msg.session_key
        ][:limit]
        summary = self.ledger.summarize_recovery_tasks(recovery_tasks)
        lines = [
            t("recovery_header", lang),
            t(
                "recovery_summary",
                lang,
                tasks=summary.get("tasks_with_recovery", 0),
                manual_review=summary.get("manual_review_required", 0),
                stale_failed=summary.get("stale_recovery_failed", 0),
                waiting_manual=summary.get("waiting_manual_review", 0),
            ),
        ]
        for task in visible:
            queue = dict(task.get("queue") or {})
            reason = str(queue.get("reason") or task.get("error") or "no recovery hint")
            if len(reason) > 120:
                reason = reason[:117] + "..."
            lines.append(
                t(
                    "tasks_item",
                    lang,
                    task_id=str(task.get("task_id") or ""),
                    status=str(task.get("status") or "unknown"),
                    stage=str(task.get("current_stage") or "unknown"),
                    action=str(queue.get("recommended_action") or "manual_review"),
                    safe="yes" if queue.get("safe_to_execute") else "no",
                    reason=reason,
                )
            )
        return self._command_reply(msg, "\n".join(lines), kind="recovery")

    def _resolve_session_task(
        self,
        msg: InboundMessage,
        *,
        raw_task_id: str = "",
    ) -> tuple[str | None, dict[str, Any] | None, dict[str, Any] | None]:
        requested = raw_task_id.strip()
        if requested and any(ch.isspace() for ch in requested):
            requested = requested.split()[0]
        if requested.lower() == "latest":
            requested = ""

        if requested:
            task = self.ledger.read_task(requested)
            if not task or str(task.get("session_key") or "") != msg.session_key:
                return None, None, None
            return requested, task, self.ledger.build_resume_candidate(requested)

        for task in self.ledger.list_tasks(limit=20, session_key=msg.session_key):
            task_id = str(task.get("task_id") or "")
            if not task_id:
                continue
            return task_id, task, self.ledger.build_resume_candidate(task_id)
        return None, None, None

    @staticmethod
    def _parse_task_artifact_args(raw: str) -> tuple[str, str | None]:
        payload = raw.strip()
        if not payload:
            return "", None
        parts = payload.split()
        export_format: str | None = None
        if parts and parts[-1].lower() in {"md", "json"}:
            export_format = parts.pop().lower()
        return " ".join(parts).strip(), export_format

    def _render_task_artifact(
        self,
        *,
        task_id: str,
        payload: dict[str, Any],
        artifact: str,
        export_format: str,
    ) -> str:
        if artifact == "export":
            if export_format == "json":
                return json.dumps(payload, ensure_ascii=False, indent=2)
            return render_task_export_markdown(payload, task_id)
        if artifact == "bundle":
            if export_format == "json":
                return json.dumps(payload, ensure_ascii=False, indent=2)
            return render_task_bundle_markdown(payload, task_id)
        if export_format == "json":
            return json.dumps(payload, ensure_ascii=False, indent=2)
        return render_task_postmortem_markdown(payload, task_id)

    def _format_task_artifact_for_chat(
        self,
        *,
        task_id: str,
        payload: dict[str, Any],
        artifact: str,
        export_format: str,
        lang: str,
    ) -> str:
        rendered = self._render_task_artifact(
            task_id=task_id,
            payload=payload,
            artifact=artifact,
            export_format=export_format,
        )
        if export_format == "json":
            return t(
                "artifact_exported",
                lang,
                artifact=artifact,
                task_id=task_id,
                format=export_format,
            ) + f"\n```json\n{rendered}\n```"
        return rendered

    async def _handle_resume_command(self, msg: InboundMessage, lang: str = "en") -> OutboundMessage:
        raw = msg.content.strip()[7:].strip()
        if raw.lower() == "help":
            return self._command_reply(msg, t("resume_usage", lang), kind="resume_help", level="warning")

        task_id, task, candidate = self._resolve_session_task(msg, raw_task_id=raw)
        if not task or not task_id:
            return self._command_reply(
                msg,
                t("resume_not_found", lang, task_id=raw or "latest"),
                kind="resume",
                level="warning",
            )
        if not candidate:
            return self._command_reply(
                msg,
                t("resume_not_found", lang, task_id=task_id),
                kind="resume",
                level="warning",
            )
        if not candidate.get("safe_to_execute"):
            return self._command_reply(
                msg,
                t(
                    "resume_unsafe",
                    lang,
                    task_id=task_id,
                    action=str(candidate.get("recommended_action") or "manual_resume"),
                    reason=str(candidate.get("reason") or "manual intervention required"),
                ),
                kind="resume",
                level="warning",
            )

        try:
            result = await self.execute_safe_resume(task_id, source="chat_command_resume")
        except Exception as exc:
            return self._command_reply(
                msg,
                t("resume_failed", lang, task_id=task_id, error=str(exc)[:200]),
                kind="resume",
                level="warning",
            )

        payload = result or candidate
        key = "resume_scheduled" if payload.get("scheduled") else "resume_executed"
        return self._command_reply(
            msg,
            t(
                key,
                lang,
                task_id=task_id,
                action=str(payload.get("recommended_action") or candidate.get("recommended_action") or "resume"),
                reason=str(payload.get("reason") or candidate.get("reason") or ""),
            ),
            kind="resume",
        )

    async def _handle_retry_outbox_command(self, msg: InboundMessage, lang: str = "en") -> OutboundMessage:
        raw = msg.content.strip()[13:].strip()
        if raw.lower() == "help":
            return self._command_reply(msg, t("retry_outbox_usage", lang), kind="retry_outbox_help", level="warning")
        task_id, task, candidate = self._resolve_session_task(msg, raw_task_id=raw)
        if not task or not task_id or not candidate:
            return self._command_reply(msg, t("resume_not_found", lang, task_id=raw or "latest"), kind="retry_outbox", level="warning")
        if str(candidate.get("recommended_action") or "") != "retry_outbox" or not candidate.get("safe_to_execute"):
            return self._command_reply(
                msg,
                t(
                    "retry_outbox_unsafe",
                    lang,
                    task_id=task_id,
                    action=str(candidate.get("recommended_action") or "manual_resume"),
                    reason=str(candidate.get("reason") or "manual intervention required"),
                ),
                kind="retry_outbox",
                level="warning",
            )
        result = await self.execute_safe_resume(task_id, source="chat_command_retry_outbox")
        payload = result or candidate
        return self._command_reply(
            msg,
            t("retry_outbox_done", lang, task_id=task_id, reason=str(payload.get("reason") or candidate.get("reason") or "")),
            kind="retry_outbox",
        )

    async def _handle_recheck_command(self, msg: InboundMessage, lang: str = "en") -> OutboundMessage:
        raw = msg.content.strip()[8:].strip()
        if raw.lower() == "help":
            return self._command_reply(msg, t("recheck_usage", lang), kind="recheck_help", level="warning")
        task_id, task, candidate = self._resolve_session_task(msg, raw_task_id=raw)
        if not task or not task_id or not candidate:
            return self._command_reply(msg, t("resume_not_found", lang, task_id=raw or "latest"), kind="recheck", level="warning")
        if str(candidate.get("recommended_action") or "") != "recheck" or not candidate.get("safe_to_execute"):
            return self._command_reply(
                msg,
                t(
                    "recheck_unsafe",
                    lang,
                    task_id=task_id,
                    action=str(candidate.get("recommended_action") or "manual_resume"),
                    reason=str(candidate.get("reason") or "manual intervention required"),
                ),
                kind="recheck",
                level="warning",
            )
        result = await self.execute_safe_resume(task_id, source="chat_command_recheck")
        payload = result or candidate
        return self._command_reply(
            msg,
            t("recheck_done", lang, task_id=task_id, reason=str(payload.get("reason") or candidate.get("reason") or "")),
            kind="recheck",
        )

    def _handle_abandon_command(self, msg: InboundMessage, lang: str = "en") -> OutboundMessage:
        from lemonclaw.ledger.types import OUTBOX_TERMINAL_STATUSES

        raw = msg.content.strip()[8:].strip()
        if raw.lower() == "help":
            return self._command_reply(msg, t("abandon_usage", lang), kind="abandon_help", level="warning")
        task_id, task, _candidate = self._resolve_session_task(msg, raw_task_id=raw)
        if not task or not task_id:
            return self._command_reply(msg, t("abandon_not_found", lang, task_id=raw or "latest"), kind="abandon", level="warning")

        event_id = ""
        for event in reversed(self.ledger.materialize_outbox_events_for_task(task_id)):
            if str(event.get("status") or "") in OUTBOX_TERMINAL_STATUSES:
                continue
            event_id = str(event.get("event_id") or "")
            if event_id:
                break
        if not event_id:
            return self._command_reply(msg, t("abandon_not_found", lang, task_id=task_id), kind="abandon", level="warning")

        updated = self.ledger.abandon_outbox_event(
            event_id,
            source="chat_command_abandon",
            reason="chat command abandon",
        )
        return self._command_reply(
            msg,
            t(
                "abandon_done",
                lang,
                task_id=task_id,
                event_id=str((updated or {}).get("event_id") or event_id),
                reason=str((updated or {}).get("error") or "chat command abandon"),
            ),
            kind="abandon",
        )

    def _handle_export_command(self, msg: InboundMessage, lang: str = "en") -> OutboundMessage:
        raw = msg.content.strip()[7:].strip()
        if raw.lower() == "help":
            return self._command_reply(msg, t("export_usage", lang), kind="export_help", level="warning")
        raw_task_id, export_format = self._parse_task_artifact_args(raw)
        task_id, task, _candidate = self._resolve_session_task(msg, raw_task_id=raw_task_id)
        if not task or not task_id:
            return self._command_reply(msg, t("export_not_found", lang, task_id=raw_task_id or "latest"), kind="export", level="warning")
        export_view = self.ledger.build_task_export_view(task_id)
        if not export_view:
            return self._command_reply(msg, t("export_not_found", lang, task_id=task_id), kind="export", level="warning")
        chosen_format = export_format or "md"
        export_view = attach_trigger_context(export_view, self.trigger_runtime)
        return self._command_reply(
            msg,
            self._format_task_artifact_for_chat(
                task_id=task_id,
                payload=export_view,
                artifact="export",
                export_format=chosen_format,
                lang=lang,
            ),
            kind="export",
        )

    def _handle_bundle_command(self, msg: InboundMessage, lang: str = "en") -> OutboundMessage:
        raw = msg.content.strip()[7:].strip()
        if raw.lower() == "help":
            return self._command_reply(msg, t("bundle_usage", lang), kind="bundle_help", level="warning")
        raw_task_id, export_format = self._parse_task_artifact_args(raw)
        task_id, task, candidate = self._resolve_session_task(msg, raw_task_id=raw_task_id)
        if not task or not task_id:
            return self._command_reply(msg, t("bundle_not_found", lang, task_id=raw_task_id or "latest"), kind="bundle", level="warning")
        export_view = self.ledger.build_task_export_view(task_id)
        if not export_view:
            return self._command_reply(msg, t("bundle_not_found", lang, task_id=task_id), kind="bundle", level="warning")
        if export_format:
            bundle = build_task_bundle(self.ledger, task_id, trigger_runtime=self.trigger_runtime)
            if not bundle:
                return self._command_reply(msg, t("bundle_not_found", lang, task_id=task_id), kind="bundle", level="warning")
            return self._command_reply(
                msg,
                self._format_task_artifact_for_chat(
                    task_id=task_id,
                    payload=bundle,
                    artifact="bundle",
                    export_format=export_format,
                    lang=lang,
                ),
                kind="bundle",
            )

        summary = dict(export_view.get("summary") or {})
        display_state = dict(summary.get("display_state") or {})
        verification = dict(summary.get("verification") or {})
        retrieval = dict(summary.get("retrieval") or {})
        conductor = dict(export_view.get("conductor") or {})
        outbox_events = list(export_view.get("outbox_events") or [])

        lines = [
            t("bundle_header", lang, task_id=task_id),
            t(
                "bundle_state",
                lang,
                status=str(task.get("status") or "unknown"),
                stage=str(task.get("current_stage") or "unknown"),
                display=str(display_state.get("key") or "unknown"),
                action=str((candidate or {}).get("recommended_action") or "manual_resume"),
                safe="yes" if (candidate or {}).get("safe_to_execute") else "no",
            ),
            t(
                "bundle_verification",
                lang,
                verification_status=str(verification.get("status") or "none"),
                evidence_count=int(verification.get("evidence_count") or 0),
            ),
            t(
                "bundle_retrieval",
                lang,
                strategy=str(retrieval.get("strategy") or "none"),
                cards=int(retrieval.get("card_count") or 0),
                rules=int(retrieval.get("rule_count") or 0),
                knowledge=int(retrieval.get("knowledge_count") or 0),
            ),
            t(
                "bundle_outbox",
                lang,
                total=len(outbox_events),
                active=int((summary.get("outbox_active_count") or 0)),
                terminal=int((summary.get("outbox_terminal_count") or 0)),
                failed=int((candidate or {}).get("failed_outbox_count") or 0),
            ),
            t(
                "bundle_conductor",
                lang,
                template=str(conductor.get("swarm_template_id") or "none"),
                subtasks=int(conductor.get("subtask_count") or 0),
                accepted=int(conductor.get("accepted_count") or 0),
                failed=int(conductor.get("failed_count") or 0),
            ),
        ]
        return self._command_reply(msg, "\n".join(lines), kind="bundle")

    def _handle_postmortem_command(self, msg: InboundMessage, lang: str = "en") -> OutboundMessage:
        raw = msg.content.strip()[11:].strip()
        if raw.lower() == "help":
            return self._command_reply(msg, t("postmortem_usage", lang), kind="postmortem_help", level="warning")
        raw_task_id, export_format = self._parse_task_artifact_args(raw)
        task_id, task, candidate = self._resolve_session_task(msg, raw_task_id=raw_task_id)
        if not task or not task_id:
            return self._command_reply(msg, t("postmortem_not_found", lang, task_id=raw_task_id or "latest"), kind="postmortem", level="warning")
        postmortem = self.ledger.build_task_postmortem_view(task_id)
        if not postmortem:
            return self._command_reply(msg, t("postmortem_not_found", lang, task_id=task_id), kind="postmortem", level="warning")
        if export_format:
            postmortem = attach_trigger_context(postmortem, self.trigger_runtime)
            return self._command_reply(
                msg,
                self._format_task_artifact_for_chat(
                    task_id=task_id,
                    payload=postmortem,
                    artifact="postmortem",
                    export_format=export_format,
                    lang=lang,
                ),
                kind="postmortem",
            )
        summary = dict(postmortem.get("summary") or {})
        display_state = dict(summary.get("display_state") or {})
        recovery = dict(summary.get("recovery") or {})
        outbox = dict((postmortem.get("outbox") or {}).get("lifecycle") or {})
        lines = [
            t("postmortem_header", lang, task_id=task_id),
            t(
                "postmortem_state",
                lang,
                status=str(task.get("status") or "unknown"),
                stage=str(task.get("current_stage") or "unknown"),
                display=str(display_state.get("key") or "unknown"),
                action=str((candidate or {}).get("recommended_action") or "manual_resume"),
                safe="yes" if (candidate or {}).get("safe_to_execute") else "no",
            ),
            t(
                "postmortem_recovery",
                lang,
                source=str(recovery.get("source") or "none"),
                recovery_action=str(recovery.get("action") or "none"),
                reason=str(recovery.get("reason") or task.get("error") or "none"),
            ),
            t(
                "postmortem_outbox",
                lang,
                failed=int((candidate or {}).get("failed_outbox_count") or 0),
                active=int(outbox.get("active_count") or 0),
                terminal=int(outbox.get("terminal_count") or 0),
            ),
            t(
                "postmortem_steps",
                lang,
                steps=int(summary.get("step_count") or 0),
                last_successful_step=str(task.get("last_successful_step") or "none"),
            ),
        ]
        return self._command_reply(msg, "\n".join(lines), kind="postmortem")

    async def _handle_channel_command(self, msg: InboundMessage, lang: str = "en") -> OutboundMessage:
        raw = msg.content.strip()[8:].strip()
        if not raw or raw.lower() == "help":
            return self._command_reply(msg, t("channel_usage", lang), kind="channel_help", level="warning")

        parts = raw.split()
        action = parts[0].lower()
        channel_name = parts[1].lower() if len(parts) > 1 else ""
        channel_manager = getattr(self, "channel_manager", None)

        if action == "status":
            if channel_manager is None or not hasattr(channel_manager, "get_channel_status"):
                return self._command_reply(msg, t("channel_unavailable", lang), kind="channel", level="warning")
            statuses = dict(channel_manager.get_channel_status() or {})
            if channel_name:
                status = dict(statuses.get(channel_name) or {})
                if not status:
                    return self._command_reply(msg, t("channel_not_found", lang, channel=channel_name), kind="channel", level="warning")
                lines = [
                    t("channel_status_header", lang, channel=channel_name),
                    t(
                        "channel_status_line",
                        lang,
                        channel=channel_name,
                        enabled="yes" if status.get("configured_enabled") else "no",
                        available="yes" if status.get("available") else "no",
                        running="yes" if status.get("running") else "no",
                        error=str(status.get("error") or "none"),
                    ),
                ]
                return self._command_reply(msg, "\n".join(lines), kind="channel")
            lines = [t("channel_status_all_header", lang)]
            for name, status in sorted(statuses.items()):
                if not status.get("configured_enabled"):
                    continue
                lines.append(
                    t(
                        "channel_status_line",
                        lang,
                        channel=name,
                        enabled="yes" if status.get("configured_enabled") else "no",
                        available="yes" if status.get("available") else "no",
                        running="yes" if status.get("running") else "no",
                        error=str(status.get("error") or "none"),
                    )
                )
            if len(lines) == 1:
                lines.append(t("channel_none_configured", lang))
            return self._command_reply(msg, "\n".join(lines), kind="channel")

        if action not in {"restart", "repair"} or not channel_name:
            return self._command_reply(msg, t("channel_usage", lang), kind="channel_help", level="warning")

        if action == "repair" and channel_name == "whatsapp":
            try:
                from lemonclaw.channels.whatsapp_bridge_runtime import restart_whatsapp_pairing
                from lemonclaw.config.loader import get_config_path, load_config
            except Exception as exc:
                return self._command_reply(msg, t("channel_repair_failed", lang, channel=channel_name, error=str(exc)[:200]), kind="channel", level="warning")

            config_path = getattr(self, "config_path", None) or get_config_path()
            try:
                runtime_config = load_config(config_path)
                state = await asyncio.to_thread(restart_whatsapp_pairing, runtime_config.channels.whatsapp, wait_timeout=20.0)
            except Exception as exc:
                return self._command_reply(msg, t("channel_repair_failed", lang, channel=channel_name, error=str(exc)[:200]), kind="channel", level="warning")
            return self._command_reply(
                msg,
                t(
                    "channel_repair_done",
                    lang,
                    channel=channel_name,
                    status=str(state.get("status") or "unknown"),
                    running="yes" if state.get("running") else "no",
                ),
                kind="channel",
            )

        if action == "repair" and channel_name == "weixin":
            try:
                from lemonclaw.channels.weixin import WeixinChannel
                from lemonclaw.channels.weixin_bridge_runtime import get_weixin_pairing_state
                from lemonclaw.config.loader import get_config_path, load_config
            except Exception as exc:
                return self._command_reply(msg, t("channel_repair_failed", lang, channel=channel_name, error=str(exc)[:200]), kind="channel", level="warning")

            config_path = getattr(self, "config_path", None) or get_config_path()
            try:
                runtime_config = load_config(config_path)
                state = await asyncio.to_thread(
                    get_weixin_pairing_state,
                    runtime_config.channels.weixin,
                    start_if_needed=True,
                    wait_timeout=5.0,
                )
                if channel_manager is not None and hasattr(channel_manager, "get_channel") and hasattr(channel_manager, "ensure_channel"):
                    existing = channel_manager.get_channel("weixin")
                    if existing is None and (state.get("status") == "connected" or state.get("accounts")):
                        await channel_manager.ensure_channel(
                            "weixin",
                            WeixinChannel(
                                runtime_config.channels.weixin,
                                channel_manager.bus,
                                trigger_runtime=getattr(channel_manager, "trigger_runtime", None),
                            ),
                        )
            except Exception as exc:
                return self._command_reply(msg, t("channel_repair_failed", lang, channel=channel_name, error=str(exc)[:200]), kind="channel", level="warning")
            return self._command_reply(
                msg,
                t(
                    "channel_repair_done",
                    lang,
                    channel=channel_name,
                    status=str(state.get("status") or "unknown"),
                    running="yes" if state.get("running") else "no",
                ),
                kind="channel",
            )

        if channel_manager is None or not hasattr(channel_manager, "restart_channel"):
            return self._command_reply(msg, t("channel_unavailable", lang), kind="channel", level="warning")

        try:
            result = await channel_manager.restart_channel(
                channel_name,
                reason=f"chat command {action}",
                source=f"chat_command_{action}",
            )
        except KeyError:
            return self._command_reply(msg, t("channel_not_found", lang, channel=channel_name), kind="channel", level="warning")
        except Exception as exc:
            key = "channel_restart_failed" if action == "restart" else "channel_repair_failed"
            return self._command_reply(msg, t(key, lang, channel=channel_name, error=str(exc)[:200]), kind="channel", level="warning")

        key = "channel_restart_done" if action == "restart" else "channel_repair_done"
        return self._command_reply(
            msg,
            t(
                key,
                lang,
                channel=channel_name,
                status=str(result.get("last_restart_result") or result.get("running") or "unknown"),
                running="yes" if result.get("running") else "no",
            ),
            kind="channel",
        )

    def _handle_runtime_command(self, msg: InboundMessage, lang: str = "en") -> OutboundMessage:
        raw = msg.content.strip()[8:].strip().lower()
        mode = raw or "summary"
        if mode not in {"summary", "inventory", "mcp", "health", "recovery"}:
            return self._command_reply(msg, t("runtime_usage", lang), kind="runtime_help", level="warning")

        lines: list[str] = []
        if mode in {"summary", "inventory"}:
            from lemonclaw.gateway.webui.settings import _derive_runtime_inventory

            inventory = _derive_runtime_inventory()
            prefixes = list(inventory.get("persistent_prefixes") or [])
            binaries = dict(inventory.get("binary_inventory") or {})
            mounted = sum(1 for item in prefixes if item.get("mounted"))
            missing_prefixes = [str(item.get("path") or "") for item in prefixes if not item.get("mounted")]
            installed = sum(1 for item in binaries.values() if item.get("installed"))
            missing_binaries = [name for name, item in binaries.items() if not item.get("installed")]

            if mode == "summary":
                lines.append(t("runtime_summary_header", lang))
                lines.append(
                    t(
                        "runtime_inventory_summary",
                        lang,
                        mounted=mounted,
                        total=len(prefixes),
                        missing_prefixes=", ".join(missing_prefixes) if missing_prefixes else "none",
                        installed=installed,
                        binary_total=len(binaries),
                        missing_binaries=", ".join(missing_binaries) if missing_binaries else "none",
                    )
                )
            else:
                lines.append(t("runtime_inventory_detail_header", lang))
                for item in prefixes:
                    lines.append(
                        t(
                            "runtime_inventory_prefix_line",
                            lang,
                            path=str(item.get("path") or "unknown"),
                            mounted="yes" if item.get("mounted") else "no",
                            fs_type=str(item.get("fs_type") or "n/a"),
                            source=str(item.get("source") or "n/a"),
                        )
                    )
                for name, item in sorted(binaries.items()):
                    lines.append(
                        t(
                            "runtime_inventory_binary_line",
                            lang,
                            name=name,
                            installed="yes" if item.get("installed") else "no",
                            command=str(item.get("command") or ""),
                            path=str(item.get("binary") or "n/a"),
                        )
                    )

        if mode in {"summary", "mcp"}:
            servers = list(self._mcp_servers.keys())
            mcp_tools = sorted(name for name in self.tools.tool_names if name.startswith("mcp_"))
            if mode == "summary":
                lines.append(
                    t(
                        "runtime_mcp_summary",
                        lang,
                        connected="yes" if self._mcp_connected else "no",
                        servers=", ".join(servers) if servers else "none",
                        tools=len(mcp_tools),
                    )
                )
            else:
                lines.append(t("runtime_mcp_detail_header", lang))
                for name in servers:
                    cfg = self._mcp_servers.get(name)
                    mode_name = "stdio" if str(getattr(cfg, "command", "") or (cfg.get("command") if isinstance(cfg, dict) else "")).strip() else "http"
                    lines.append(t("runtime_mcp_server_line", lang, name=name, mode=mode_name))
                lines.append(t("runtime_mcp_tool_line", lang, tools=", ".join(mcp_tools) if mcp_tools else "none"))

        if mode in {"summary", "health", "recovery"}:
            from lemonclaw.config.loader import get_config_path
            from lemonclaw.config.loader import load_config
            from lemonclaw.gateway.runtime_state import derive_runtime_state_view, load_runtime_state

            watchdog = getattr(self, "watchdog", None)
            channel_manager = getattr(self, "channel_manager", None)
            snapshot = watchdog.snapshot() if watchdog and hasattr(watchdog, "snapshot") else {}
            config_path = getattr(self, "config_path", None) or get_config_path()
            restart_state = derive_runtime_state_view(load_runtime_state(config_path))
            runtime_config = None
            if mode == "recovery":
                try:
                    runtime_config = load_config(config_path)
                except Exception:
                    runtime_config = None
            channels = {}
            if isinstance(snapshot.get("channels"), dict):
                channels = dict(snapshot.get("channels") or {})
            elif channel_manager and hasattr(channel_manager, "get_channel_status"):
                channels = dict(channel_manager.get_channel_status() or {})
            total_channels = len(channels)
            running_channels = sum(1 for item in channels.values() if item.get("running"))
            blocked_channels = sum(1 for item in channels.values() if item.get("enabled") and not item.get("available"))
            watchdog_running = bool(snapshot.get("running")) if snapshot else False
            stale_tasks = int(((snapshot.get("task_stuck") or {}).get("count")) or 0) if snapshot else 0
            state = dict(snapshot.get("state") or {}) if snapshot else {}
            if mode == "summary":
                lines.append(
                    t(
                        "runtime_health_summary",
                        lang,
                        watchdog="yes" if watchdog_running else "no",
                        stale_tasks=stale_tasks,
                        recent_errors=int(state.get("recent_error_count") or 0),
                        soft=int(state.get("total_soft_recoveries") or 0),
                        hard=int(state.get("total_hard_restarts") or 0),
                        running=running_channels,
                        total=total_channels,
                        blocked=blocked_channels,
                    )
                )
                if restart_state:
                    lines.append(
                        t(
                            "runtime_restart_summary",
                            lang,
                            status=str(restart_state.get("status") or "unknown"),
                            fields=", ".join(restart_state.get("restart_fields") or []) if restart_state.get("restart_fields") else "none",
                            requested_at=str(restart_state.get("last_restart_requested_at_ms") or "n/a"),
                            completed_at=str(restart_state.get("last_restart_completed_at_ms") or "n/a"),
                            result=str(restart_state.get("last_restart_result") or "unknown"),
                        )
                    )
            elif mode == "health":
                lines.append(t("runtime_health_detail_header", lang))
                lines.append(
                    t(
                        "runtime_health_summary",
                        lang,
                        watchdog="yes" if watchdog_running else "no",
                        stale_tasks=stale_tasks,
                        recent_errors=int(state.get("recent_error_count") or 0),
                        soft=int(state.get("total_soft_recoveries") or 0),
                        hard=int(state.get("total_hard_restarts") or 0),
                        running=running_channels,
                        total=total_channels,
                        blocked=blocked_channels,
                    )
                )
                if restart_state:
                    lines.append(
                        t(
                            "runtime_restart_summary",
                            lang,
                            status=str(restart_state.get("status") or "unknown"),
                            fields=", ".join(restart_state.get("restart_fields") or []) if restart_state.get("restart_fields") else "none",
                            requested_at=str(restart_state.get("last_restart_requested_at_ms") or "n/a"),
                            completed_at=str(restart_state.get("last_restart_completed_at_ms") or "n/a"),
                            result=str(restart_state.get("last_restart_result") or "unknown"),
                        )
                    )
                for name, item in sorted(channels.items()):
                    lines.append(
                        t(
                            "runtime_health_channel_line",
                            lang,
                            name=name,
                            enabled="yes" if item.get("enabled") or item.get("configured_enabled") else "no",
                            available="yes" if item.get("available") else "no",
                            running="yes" if item.get("running") else "no",
                            error=str(item.get("error") or "none"),
                        )
                    )
            else:
                from lemonclaw.gateway.webui.settings import _derive_channel_runtime

                lines.append(t("runtime_recovery_header", lang))
                lines.append(
                    t(
                        "runtime_health_summary",
                        lang,
                        watchdog="yes" if watchdog_running else "no",
                        stale_tasks=stale_tasks,
                        recent_errors=int(state.get("recent_error_count") or 0),
                        soft=int(state.get("total_soft_recoveries") or 0),
                        hard=int(state.get("total_hard_restarts") or 0),
                        running=running_channels,
                        total=total_channels,
                        blocked=blocked_channels,
                    )
                )
                if restart_state:
                    lines.append(
                        t(
                            "runtime_restart_summary",
                            lang,
                            status=str(restart_state.get("status") or "unknown"),
                            fields=", ".join(restart_state.get("restart_fields") or []) if restart_state.get("restart_fields") else "none",
                            requested_at=str(restart_state.get("last_restart_requested_at_ms") or "n/a"),
                            completed_at=str(restart_state.get("last_restart_completed_at_ms") or "n/a"),
                            result=str(restart_state.get("last_restart_result") or "unknown"),
                        )
                    )

                for task in self.ledger.list_tasks(limit=3, session_key=msg.session_key):
                    task_id = str(task.get("task_id") or "")
                    if not task_id:
                        continue
                    candidate = self.ledger.build_resume_candidate(task_id) or {}
                    reason = str(candidate.get("reason") or "no recovery hint")
                    if len(reason) > 120:
                        reason = reason[:117] + "..."
                    lines.append(
                        t(
                            "runtime_recovery_task_line",
                            lang,
                            task_id=task_id,
                            status=str(task.get("status") or "unknown"),
                            stage=str(task.get("current_stage") or "unknown"),
                            action=str(candidate.get("recommended_action") or "manual_review"),
                            safe="yes" if candidate.get("safe_to_execute") else "no",
                            reason=reason,
                        )
                    )

                if runtime_config is not None:
                    for channel_name, entry in sorted(_derive_channel_runtime(runtime_config).items()):
                        if str(entry.get("effective_dm_policy") or "") != "pairing":
                            continue
                        lines.append(
                            t(
                                "runtime_recovery_pairing_line",
                                lang,
                                channel=channel_name,
                                approved=str(entry.get("approved_count") or 0),
                                pending=str(entry.get("pending_count") or 0),
                                owner=str(entry.get("owner") or "none"),
                            )
                        )

        return self._command_reply(msg, "\n".join(lines), kind="runtime")

    def _handle_kb_command(self, msg: InboundMessage, lang: str = "en") -> OutboundMessage:
        raw = msg.content.strip()[3:].strip()
        if not raw:
            return self._command_reply(msg, t("kb_usage", lang), kind="kb_help", level="warning")

        lowered = raw.lower()
        if lowered == "list" or lowered.startswith("list "):
            limit_arg = raw[4:].strip()
            limit = 8
            if limit_arg:
                try:
                    limit = min(max(int(limit_arg), 1), 20)
                except ValueError:
                    return self._command_reply(msg, t("kb_usage", lang), kind="kb_help", level="warning")
            result = self._knowledge_list_sync(limit=limit, lang=lang)
            level = "warning" if result == t("kb_list_empty", lang) else "info"
            return self._command_reply(msg, result, kind="kb_list", level=level)

        if lowered == "add" or lowered.startswith("add "):
            payload = raw[3:].strip()
            if not payload:
                return self._command_reply(msg, t("kb_add_usage", lang), kind="kb_add", level="warning")
            result, level = self._knowledge_add_sync(msg, payload, lang)
            return self._command_reply(msg, result, kind="kb_add", level=level)

        if lowered == "retry-failed" or lowered.startswith("retry-failed "):
            limit_arg = raw[len("retry-failed"):].strip()
            limit = 20
            if limit_arg:
                try:
                    limit = min(max(int(limit_arg), 1), 50)
                except ValueError:
                    return self._command_reply(msg, t("kb_usage", lang), kind="kb_help", level="warning")
            result, level = self._knowledge_retry_failed_sync(limit=limit, lang=lang)
            return self._command_reply(msg, result, kind="kb_retry_failed", level=level)

        if lowered == "refresh-due" or lowered.startswith("refresh-due "):
            limit_arg = raw[len("refresh-due"):].strip()
            limit = 20
            if limit_arg:
                try:
                    limit = min(max(int(limit_arg), 1), 50)
                except ValueError:
                    return self._command_reply(msg, t("kb_usage", lang), kind="kb_help", level="warning")
            result, level = self._knowledge_refresh_due_sync(limit=limit, lang=lang)
            return self._command_reply(msg, result, kind="kb_refresh_due", level=level)

        if lowered == "ingest-pending" or lowered.startswith("ingest-pending "):
            limit_arg = raw[len("ingest-pending"):].strip()
            limit = 20
            if limit_arg:
                try:
                    limit = min(max(int(limit_arg), 1), 50)
                except ValueError:
                    return self._command_reply(msg, t("kb_usage", lang), kind="kb_help", level="warning")
            result, level = self._knowledge_ingest_pending_sync(limit=limit, lang=lang)
            return self._command_reply(msg, result, kind="kb_ingest_pending", level=level)

        if lowered == "show" or lowered.startswith("show "):
            payload = raw[4:].strip()
            result, level = self._knowledge_show_sync(payload, lang=lang)
            return self._command_reply(msg, result, kind="kb_show", level=level)

        if lowered == "pin" or lowered.startswith("pin "):
            payload = raw[3:].strip()
            result, level = self._knowledge_pin_sync(payload, pinned=True, lang=lang)
            return self._command_reply(msg, result, kind="kb_pin", level=level)

        if lowered == "unpin" or lowered.startswith("unpin "):
            payload = raw[5:].strip()
            result, level = self._knowledge_pin_sync(payload, pinned=False, lang=lang)
            return self._command_reply(msg, result, kind="kb_unpin", level=level)

        tool = self.tools.get("search_knowledge")
        if tool is None:
            return self._command_reply(msg, t("kb_empty", lang, query=raw), kind="kb_search", level="warning")
        # Knowledge search is local and synchronous from the user's perspective.
        result = self._knowledge_search_sync(raw)
        if result.startswith("No knowledge hits"):
            return self._command_reply(msg, t("kb_empty", lang, query=raw), kind="kb_search", level="warning")
        return self._command_reply(msg, result, kind="kb_search")

    def _git_auth_list_sync(self, *, lang: str = "en") -> str:
        profiles = dict((self.git_config.auth_profiles if self.git_config else {}) or {})
        if not profiles:
            return t("git_auth_list_empty", lang)
        lines = [t("git_auth_list_header", lang)]
        for name, profile in sorted(profiles.items()):
            username = str(getattr(profile, "username", "") or (profile.get("username") if isinstance(profile, dict) else "") or "x-access-token")
            has_password = bool(getattr(profile, "password", "") or (profile.get("password") if isinstance(profile, dict) else ""))
            lines.append(
                t(
                    "git_auth_list_item",
                    lang,
                    name=name,
                    username=username,
                    status=t("git_auth_status_ready", lang) if has_password else t("git_auth_status_missing", lang),
                )
            )
        return "\n".join(lines)

    def _git_auth_show_sync(self, payload: str, *, lang: str = "en") -> tuple[str, str]:
        profile_name = str(payload or "").strip()
        if not profile_name:
            return t("git_auth_usage", lang), "warning"
        profiles = dict((self.git_config.auth_profiles if self.git_config else {}) or {})
        profile = profiles.get(profile_name)
        if not profile:
            return t("git_auth_not_found", lang, name=profile_name), "warning"
        username = str(getattr(profile, "username", "") or (profile.get("username") if isinstance(profile, dict) else "") or "x-access-token")
        password = str(getattr(profile, "password", "") or (profile.get("password") if isinstance(profile, dict) else "") or "")
        password_status = redact_sensitive_text(password) if password else t("git_auth_status_missing", lang)
        return t("git_auth_show", lang, name=profile_name, username=username, password=password_status), "info"

    def _git_auth_delete_sync(self, payload: str, *, lang: str = "en") -> tuple[str, str]:
        profile_name = str(payload or "").strip()
        if not profile_name:
            return t("git_auth_usage", lang), "warning"
        profiles = dict((self.git_config.auth_profiles if self.git_config else {}) or {})
        if profile_name not in profiles:
            return t("git_auth_not_found", lang, name=profile_name), "warning"
        try:
            config = self._load_runtime_config()
            profiles = dict(config.tools.git.auth_profiles or {})
            profiles.pop(profile_name, None)
            config.tools.git.auth_profiles = profiles
            self._save_runtime_config(config)
            self._refresh_git_tool_from_config(config.tools.git)
        except Exception as exc:
            return t("git_auth_save_failed", lang, error=str(exc)[:160]), "warning"
        return t("git_auth_deleted", lang, name=profile_name), "info"

    def _git_auth_set_sync(self, payload: str, *, lang: str = "en") -> tuple[str, str]:
        parts = [part.strip() for part in payload.split("::")]
        if len(parts) == 2:
            profile_name, password = parts
            username = "x-access-token"
        elif len(parts) == 3:
            profile_name, username, password = parts
        else:
            return t("git_auth_usage", lang), "warning"
        if not profile_name or not password:
            return t("git_auth_usage", lang), "warning"
        if not _GIT_AUTH_PROFILE_NAME_RE.match(profile_name):
            return t("git_auth_invalid_name", lang, name=profile_name), "warning"
        if not username:
            username = "x-access-token"
        try:
            from lemonclaw.config.schema import GitAuthProfileConfig

            config = self._load_runtime_config()
            profiles = dict(config.tools.git.auth_profiles or {})
            profiles[profile_name] = GitAuthProfileConfig(username=username, password=password)
            config.tools.git.auth_profiles = profiles
            self._save_runtime_config(config)
            self._refresh_git_tool_from_config(config.tools.git)
        except Exception as exc:
            return t("git_auth_save_failed", lang, error=str(exc)[:160]), "warning"
        return t("git_auth_saved", lang, name=profile_name, username=username), "info"

    @staticmethod
    def _load_runtime_config():
        from lemonclaw.config import get_config_path, load_config

        return load_config(get_config_path())

    @staticmethod
    def _save_runtime_config(config: Any) -> None:
        from lemonclaw.config import get_config_path
        from lemonclaw.config.loader import save_config

        save_config(config, get_config_path())

    def _refresh_git_tool_from_config(self, git_config: Any | None) -> None:
        self.git_config = git_config
        self.tools.unregister("git")
        self.tools.register(self._build_git_tool())

    def _knowledge_search_sync(self, query: str) -> str:
        from lemonclaw.knowledge import KnowledgeStore

        store = KnowledgeStore(self.workspace)
        hits = store.search(query, limit=5)
        if not hits:
            return f"No knowledge hits for: {query}"
        lines = [f"Knowledge hits for: {query}\n"]
        for idx, item in enumerate(hits, 1):
            lines.append(f"{idx}. {item.get('title') or item.get('doc_id')}")
            lines.append(f"   type={item.get('result_type') or 'chunk'} source={item.get('source') or '—'}")
            if item.get("snippet"):
                lines.append(f"   {item['snippet']}")
        return "\n".join(lines)

    def _knowledge_list_sync(self, *, limit: int = 8, lang: str = "en") -> str:
        from lemonclaw.knowledge import KnowledgeStore

        store = KnowledgeStore(self.workspace)
        docs = store.list_documents()
        if not docs:
            return t("kb_list_empty", lang)

        summary = store.summarize()
        lines = [f"Knowledge documents ({summary['total']} total, {summary.get('due_count', 0)} due)\n"]
        for idx, doc in enumerate(docs[:limit], 1):
            next_refresh = int(doc.get("next_refresh_at_ms") or 0)
            next_refresh_text = "due" if store._is_due_document(doc) else ("—" if next_refresh <= 0 else "scheduled")
            pin_prefix = "[PIN] " if doc.get("pinned") else ""
            lines.append(f"{idx}. {pin_prefix}{doc.get('title') or doc.get('doc_id')}")
            lines.append(
                "   "
                f"id={doc.get('doc_id')} "
                f"type={doc.get('source_type') or '—'} "
                f"status={doc.get('status') or '—'} "
                f"chunks={int(doc.get('chunk_count') or 0)} "
                f"facts={int(doc.get('fact_count') or 0)} "
                f"hits={int(doc.get('retrieval_count') or 0)}"
            )
            lines.append(
                "   "
                f"refresh={int(doc.get('refresh_interval_hours') or 0)}h "
                f"next={next_refresh_text} "
                f"source={doc.get('source') or '—'}"
            )
        return "\n".join(lines)

    def _knowledge_add_sync(self, msg: InboundMessage, payload: str, lang: str = "en") -> tuple[str, str]:
        from lemonclaw.knowledge import KnowledgeStore

        title, content = self._parse_kb_add_payload(payload)
        if not content:
            return t("kb_add_usage", lang), "warning"

        source_suffix = uuid.uuid4().hex[:8]
        source = f"manual://chat/{source_suffix}"
        store = KnowledgeStore(self.workspace)
        try:
            doc = store.create_document(
                source_type="manual",
                source=source,
                title=title,
                content=content,
                note=f"Added from chat command on {msg.channel}:{msg.chat_id}",
            )
            store.ingest_document(str(doc.get("doc_id") or ""))
        except Exception as exc:
            return t("kb_add_failed", lang, error=str(exc)[:200]), "warning"
        return t("kb_added", lang, title=doc.get("title") or doc.get("doc_id"), doc_id=doc.get("doc_id")), "info"

    def _knowledge_retry_failed_sync(self, *, limit: int = 20, lang: str = "en") -> tuple[str, str]:
        from lemonclaw.knowledge import KnowledgeStore

        store = KnowledgeStore(self.workspace)
        result = store.retry_failed(limit=limit)
        updated = int(result.get("updated") or 0)
        failed = int(result.get("failed") or 0)
        lines = [t("kb_retry_failed_done", lang, updated=updated, failed=failed)]
        for item in list(result.get("errors") or [])[:5]:
            if not isinstance(item, dict):
                continue
            doc_id = str(item.get("doc_id") or "unknown")
            error = str(item.get("error") or "unknown error")
            lines.append(f"- {doc_id}: {error}")
        return "\n".join(lines), ("warning" if failed > 0 else "info")

    def _knowledge_refresh_due_sync(self, *, limit: int = 20, lang: str = "en") -> tuple[str, str]:
        from lemonclaw.knowledge import KnowledgeStore

        store = KnowledgeStore(self.workspace)
        result = store.refresh_due(limit=limit)
        updated = int(result.get("updated") or 0)
        failed = int(result.get("failed") or 0)
        lines = [t("kb_refresh_due_done", lang, updated=updated, failed=failed)]
        for item in list(result.get("errors") or [])[:5]:
            if not isinstance(item, dict):
                continue
            doc_id = str(item.get("doc_id") or "unknown")
            error = str(item.get("error") or "unknown error")
            lines.append(f"- {doc_id}: {error}")
        return "\n".join(lines), ("warning" if failed > 0 else "info")

    def _knowledge_ingest_pending_sync(self, *, limit: int = 20, lang: str = "en") -> tuple[str, str]:
        from lemonclaw.knowledge import KnowledgeStore

        store = KnowledgeStore(self.workspace)
        result = store.ingest_pending(limit=limit)
        updated = int(result.get("updated") or 0)
        failed = int(result.get("failed") or 0)
        lines = [t("kb_ingest_pending_done", lang, updated=updated, failed=failed)]
        for item in list(result.get("errors") or [])[:5]:
            if not isinstance(item, dict):
                continue
            doc_id = str(item.get("doc_id") or "unknown")
            error = str(item.get("error") or "unknown error")
            lines.append(f"- {doc_id}: {error}")
        return "\n".join(lines), ("warning" if failed > 0 else "info")

    def _knowledge_show_sync(self, payload: str, *, lang: str = "en") -> tuple[str, str]:
        from lemonclaw.knowledge import KnowledgeStore

        doc_id = str(payload or "").strip()
        if not doc_id:
            return t("kb_show_usage", lang), "warning"

        store = KnowledgeStore(self.workspace)
        try:
            doc = store.read_document(doc_id)
            chunks = store.list_chunks(doc_id)
            facts = store.list_facts(doc_id)
        except ValueError:
            return t("kb_show_usage", lang), "warning"
        if not doc:
            return t("kb_pin_not_found", lang, doc_id=doc_id), "warning"

        lines = [f"Knowledge document: {doc.get('title') or doc_id}\n"]
        lines.append(
            " ".join([
                f"id={doc.get('doc_id')}",
                f"type={doc.get('source_type') or '—'}",
                f"status={doc.get('status') or '—'}",
                f"pinned={bool(doc.get('pinned'))}",
                f"chunks={int(doc.get('chunk_count') or 0)}",
                f"facts={int(doc.get('fact_count') or 0)}",
                f"hits={int(doc.get('retrieval_count') or 0)}",
            ])
        )
        lines.append(f"source={doc.get('source') or '—'}")
        if doc.get("last_hit_query"):
            lines.append(f"last_query={doc.get('last_hit_query')}")
        if doc.get("note"):
            lines.append(f"\nnote: {doc.get('note')}")
        if chunks:
            first_chunk = chunks[0]
            page = f" [{first_chunk.get('page_label')}]" if first_chunk.get("page_label") else ""
            lines.append(f"\nchunk{page}: {str(first_chunk.get('text') or '')[:280]}")
        if facts:
            first_fact = facts[0]
            page = f" [{first_fact.get('page_label')}]" if first_fact.get("page_label") else ""
            lines.append(f"fact{page}: {str(first_fact.get('claim') or '')[:220]}")
        return "\n".join(lines), "info"

    def _knowledge_pin_sync(self, payload: str, *, pinned: bool, lang: str = "en") -> tuple[str, str]:
        from lemonclaw.knowledge import KnowledgeStore

        doc_id = str(payload or "").strip()
        if not doc_id:
            return t("kb_pin_usage", lang), "warning"

        store = KnowledgeStore(self.workspace)
        try:
            doc = store.update_document(doc_id, pinned=pinned)
        except ValueError:
            return t("kb_pin_usage", lang), "warning"
        except KeyError:
            return t("kb_pin_not_found", lang, doc_id=doc_id), "warning"

        title = doc.get("title") or doc.get("doc_id") or doc_id
        key = "kb_pinned" if pinned else "kb_unpinned"
        return t(key, lang, title=title, doc_id=doc_id), "info"

    @staticmethod
    def _parse_kb_add_payload(payload: str) -> tuple[str, str]:
        text = str(payload or "").strip()
        if not text:
            return "", ""
        if "::" in text:
            title, content = text.split("::", 1)
            title = title.strip()
            content = content.strip()
            if content:
                resolved_title = title[:200] or content[:80]
                return resolved_title, content
        fallback = text[:200]
        return fallback, text

    def _should_persist_control_reply(self, kind: str) -> bool:
        """Decide whether a slash/system reply should be stored in session history."""
        return kind not in {"new_session", "stop_tasks", "stop_none"}

    def _persist_simple_reply(self, session: Session, user_content: str, reply: OutboundMessage, *, kind: str | None = None) -> None:
        if kind and not self._should_persist_control_reply(kind):
            return
        session.messages.append(serialize_ui_message({
            "role": "user",
            "content": user_content,
            "timestamp": datetime.now().isoformat(),
        }))
        session.messages.append(serialize_ui_message({
            "role": "assistant",
            "content": reply.content,
            "media": list(reply.media or []),
            "metadata": reply.metadata or {},
            "timestamp": datetime.now().isoformat(),
        }))
        session.updated_at = datetime.now()
        self.sessions.save(session)

    def _command_reply(self, msg: InboundMessage, content: str, *, kind: str = "command", level: str = "info", extra_meta: dict | None = None) -> OutboundMessage:
        metadata = {**(msg.metadata or {}), "_ui_notice_text": msg.content.strip() or kind, "_ui_notice_kind": kind, "_ui_notice_level": level}
        if extra_meta:
            metadata.update(extra_meta)
        return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content=content, metadata=metadata)

    def _persist_model_default(self, model: str) -> None:
        """Persist model change to config.json (D5: /model = same as Settings tab)."""
        try:
            from lemonclaw.config import get_config_path, load_config
            from lemonclaw.config.loader import save_config
            path = get_config_path()
            config = load_config(path)
            if config.agents.defaults.model != model:
                config.agents.defaults.model = model
                save_config(config, path)
                logger.info("/model: persisted default model to config.json: {}", model)
        except Exception:
            logger.warning("/model: failed to persist to config.json (ephemeral only)")

    def _save_turn(self, session: Session, messages: list[dict], skip: int, *, turn_media: list[str] | None = None) -> None:
        """Save new-turn messages into session, truncating large tool results."""
        _media_injected = False
        effective_skip = self._current_turn_start_index(messages, skip)
        for m in messages[effective_skip:]:
            entry = {k: v for k, v in m.items() if k != "reasoning_content"}
            role, content = entry.get("role"), entry.get("content")
            if role == "tool" and isinstance(content, str) and len(content) > self._TOOL_RESULT_MAX_CHARS:
                entry["content"] = content[:self._TOOL_RESULT_MAX_CHARS] + "\n... (truncated)"
            elif role == "user":
                original = m.get("_original_text")
                if isinstance(original, str):
                    entry["content"] = original
                    entry.pop("_original_text", None)
                elif isinstance(content, str) and content.startswith(ContextBuilder._RUNTIME_CONTEXT_TAG):
                    _media_injected = True
                    continue
                elif isinstance(content, list):
                    entry["content"] = [
                        {"type": "text", "text": "[image]"} if (
                            c.get("type") == "image_url"
                            and c.get("image_url", {}).get("url", "").startswith("data:image/")
                        ) else c for c in content
                    ]
                if not _media_injected and turn_media:
                    entry["media"] = turn_media
                    _media_injected = True
            elif role == "assistant":
                if (
                    not entry.get("tool_calls")
                    and not entry.get("media")
                    and (
                        content is None
                        or (isinstance(content, str) and not content.strip())
                    )
                ):
                    continue
            entry.setdefault("timestamp", datetime.now().isoformat())
            if role in ("user", "assistant", "system"):
                session.messages.append(serialize_ui_message(entry))
            else:
                session.messages.append(entry)
        session.updated_at = datetime.now()

    async def _consolidate_memory(
        self,
        session,
        archive_all: bool = False,
        *,
        should_commit: Callable[[], bool] | None = None,
    ) -> bool:
        """Delegate to MemoryStore.consolidate() with provider resolved for the consolidation model."""
        from lemonclaw.config.defaults import DEFAULT_CONSOLIDATION_MODEL
        active_provider = self._provider_for_model(DEFAULT_CONSOLIDATION_MODEL)
        return await self.context.memory.consolidate(
            session, active_provider, DEFAULT_CONSOLIDATION_MODEL,
            archive_all=archive_all, memory_window=self.memory_window,
            should_commit=should_commit,
        )

    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
        on_progress: Callable[[str], Awaitable[None]] | None = None,
        on_chunk: Callable[..., Awaitable[None]] | None = None,
        metadata: dict | None = None,
        media: list[str] | None = None,
        outbound_sink: Callable[[OutboundMessage], Awaitable[None]] | None = None,
    ) -> str:
        """Process a message directly (for CLI or cron usage)."""
        await self._connect_mcp()
        stop_event = asyncio.Event()
        self._stop_events[session_key] = stop_event
        current_task = asyncio.current_task()
        if current_task is not None:
            self._active_tasks.setdefault(session_key, []).append(current_task)
        if session_key not in self._session_locks:
            self._session_locks[session_key] = asyncio.Lock()
            if len(self._session_locks) > self._MAX_SESSION_LOCKS:
                self._evict_idle_session_locks()
        if session_key in self._session_lock_order:
            self._session_lock_order.remove(session_key)
        self._session_lock_order.append(session_key)
        try:
            async with self._session_locks[session_key]:
                direct_metadata = dict(metadata or {})
                delivery_policy = get_delivery_policy(direct_metadata)
                direct_metadata.setdefault("_task_id", f"task_{uuid.uuid4().hex[:12]}")
                direct_metadata.setdefault("_mode", "chat" if channel not in {"system", "internal", "cron"} else ("cron" if channel == "cron" else "operator"))
                direct_metadata.setdefault("run_mode", self._default_run_mode(channel=channel, mode=str(direct_metadata.get("_mode") or "")))
                direct_metadata.setdefault("_agent_id", self.agent_id)
                task_metadata = self._task_trigger_metadata(direct_metadata)
                self.ledger.ensure_task(
                    task_id=str(direct_metadata["_task_id"]),
                    session_key=session_key,
                    agent_id=self.agent_id,
                    mode=str(direct_metadata["_mode"]),
                    channel=channel,
                    goal=content[:500],
                    current_stage="dispatch",
                    resume_context=build_task_resume_context(
                        channel=channel,
                        chat_id=str(chat_id),
                        sender_id="user",
                        session_key=session_key,
                        timezone=str(direct_metadata.get("timezone") or self.default_timezone or ""),
                        run_mode=str(direct_metadata.get("run_mode") or ""),
                        session_context=dict(direct_metadata.get("_session_context") or {}) if isinstance(direct_metadata.get("_session_context"), dict) else None,
                        message_id=str(direct_metadata.get("message_id") or ""),
                        delivery_context=dict(direct_metadata.get("_delivery_context") or {}),
                        delivery_policy=dict(delivery_policy) if isinstance(delivery_policy, dict) else None,
                    ),
                    metadata=task_metadata or None,
                )
                self._link_trigger_task(direct_metadata, str(direct_metadata["_task_id"]), session_key)
                if outbound_sink:
                    direct_metadata["_outbound_sink"] = outbound_sink
                msg = InboundMessage(channel=channel, sender_id="user", chat_id=chat_id, content=content,
                                     metadata=direct_metadata, media=media or [])
                try:
                    response = await self._process_message(
                        msg,
                        session_key=session_key,
                        on_progress=on_progress,
                        on_chunk=on_chunk,
                        stop_event=stop_event,
                    )
                    gate_result = finalize_task(self.ledger, str(direct_metadata["_task_id"]))
                    self._finish_trigger_success(
                        direct_metadata,
                        task_id=str(direct_metadata["_task_id"]),
                        session_key=session_key,
                        result_summary=(response.content if response else "")[:500],
                    )
                    if gate_result and gate_result.passed:
                        self._schedule_learning_promotion(
                            task_id=str(direct_metadata["_task_id"]),
                            mode=str(direct_metadata.get("_mode") or "chat"),
                            actor_identity=str(direct_metadata.get("_actor_identity") or direct_metadata.get("_agent_id") or self.agent_id),
                        )
                except asyncio.CancelledError:
                    self._abandon_task_outbox_side_effects(
                        str(direct_metadata["_task_id"]),
                        session_key=session_key,
                    )
                    self.ledger.update_task(
                        str(direct_metadata["_task_id"]),
                        status="abandoned",
                        current_stage="cancelled",
                        error="cancelled",
                    )
                    self._finish_trigger_failure(
                        direct_metadata,
                        task_id=str(direct_metadata["_task_id"]),
                        session_key=session_key,
                        error="cancelled",
                    )
                    raise
                except Exception as exc:
                    self.ledger.update_task(
                        str(direct_metadata["_task_id"]),
                        status="failed",
                        current_stage="error",
                        error=str(exc)[:500],
                    )
                    self._finish_trigger_failure(
                        direct_metadata,
                        task_id=str(direct_metadata["_task_id"]),
                        session_key=session_key,
                        error=str(exc),
                    )
                    raise
            return response.content if response else ""
        finally:
            self._stop_events.pop(session_key, None)
            if current_task is not None:
                tasks = self._active_tasks.get(session_key, [])
                if current_task in tasks:
                    tasks.remove(current_task)
                if not tasks and session_key in self._active_tasks:
                    del self._active_tasks[session_key]

    @staticmethod
    def _task_trigger_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
        trigger_id = str(metadata.get("_trigger_id") or "")
        if not trigger_id:
            return {}
        return {
            "trigger": {
                "trigger_id": trigger_id,
                "source": str(metadata.get("_trigger_source") or ""),
                "kind": str(metadata.get("_trigger_kind") or ""),
            }
        }

    def _link_trigger_task(self, metadata: dict[str, Any], task_id: str, session_key: str) -> None:
        if not self.trigger_runtime:
            return
        trigger_id = str(metadata.get("_trigger_id") or "")
        if not trigger_id:
            return
        self.trigger_runtime.link_task(
            trigger_id,
            task_id=task_id,
            session_key=session_key,
            status="dispatching",
            metadata={"mode": str(metadata.get("_mode") or "chat")},
        )

    def _finish_trigger_success(
        self,
        metadata: dict[str, Any],
        *,
        task_id: str,
        session_key: str,
        result_summary: str,
    ) -> None:
        if not self.trigger_runtime:
            return
        trigger_id = str(metadata.get("_trigger_id") or "")
        if not trigger_id:
            return
        task = self.ledger.read_task(task_id) or {}
        self.trigger_runtime.finish_trigger(
            trigger_id,
            status="completed",
            result_summary=result_summary,
            metadata={
                "task_id": task_id,
                "session_key": session_key,
                "task_status": str(task.get("status") or ""),
                "task_stage": str(task.get("current_stage") or ""),
            },
        )

    def _finish_trigger_failure(
        self,
        metadata: dict[str, Any],
        *,
        task_id: str,
        session_key: str,
        error: str,
    ) -> None:
        if not self.trigger_runtime:
            return
        trigger_id = str(metadata.get("_trigger_id") or "")
        if not trigger_id:
            return
        task = self.ledger.read_task(task_id) or {}
        self.trigger_runtime.finish_trigger(
            trigger_id,
            status="failed",
            error=error[:500],
            metadata={
                "task_id": task_id,
                "session_key": session_key,
                "task_status": str(task.get("status") or "failed"),
                "task_stage": str(task.get("current_stage") or "error"),
            },
        )
