"""Agent loop: the core processing engine."""

from __future__ import annotations

import asyncio
import json
import re
from contextlib import AsyncExitStack
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from loguru import logger

from lemonclaw.agent.context import ContextBuilder
from lemonclaw.agent.locale import detect_lang, session_lang, t
from lemonclaw.agent.memory import MemoryStore
from lemonclaw.agent.subagent import SubagentManager
from lemonclaw.agent.tools.cron import CronTool
from lemonclaw.agent.tools.filesystem import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from lemonclaw.agent.tools.message import MessageTool
from lemonclaw.agent.tools.registry import ToolRegistry
from lemonclaw.agent.tools.coding import CodingTool
from lemonclaw.agent.tools.shell import ExecTool
from lemonclaw.agent.tools.spawn import SpawnTool
from lemonclaw.agent.tools.web import WebFetchTool, WebSearchTool
from lemonclaw.bus.events import InboundMessage, OutboundMessage
from lemonclaw.bus.queue import MessageBus
from lemonclaw.providers.base import LLMProvider
from lemonclaw.providers.catalog import MODEL_MAP, fuzzy_match, format_model_list
from lemonclaw.session.manager import Session, SessionManager
from lemonclaw.telemetry.usage import TurnUsage, UsageTracker

if TYPE_CHECKING:
    from lemonclaw.bus.activity import ActivityBus
    from lemonclaw.conductor.orchestrator import Orchestrator
    from lemonclaw.config.schema import ChannelsConfig, CodingToolConfig, ExecToolConfig
    from lemonclaw.cron.service import CronService


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
        exec_config: ExecToolConfig | None = None,
        cron_service: CronService | None = None,
        restrict_to_workspace: bool = False,
        session_manager: SessionManager | None = None,
        mcp_servers: dict | None = None,
        channels_config: ChannelsConfig | None = None,
        usage_tracker: UsageTracker | None = None,
        coding_config: CodingToolConfig | None = None,
        activity_bus: ActivityBus | None = None,
        default_timezone: str = "",
        system_prompt: str = "",
        disabled_skills: list[str] | None = None,
    ):
        from lemonclaw.config.schema import ExecToolConfig
        self.agent_id = agent_id
        self.bus = bus
        self.channels_config = channels_config
        self.default_timezone = default_timezone
        self.provider = provider
        self.workspace = workspace
        self.model = model or provider.get_default_model()
        self.max_iterations = max_iterations
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.memory_window = memory_window
        self.brave_api_key = brave_api_key
        self.exec_config = exec_config or ExecToolConfig()
        self.coding_config = coding_config
        self.activity_bus = activity_bus
        self.orchestrator: Orchestrator | None = None
        self.cron_service = cron_service
        self.restrict_to_workspace = restrict_to_workspace

        self.context = ContextBuilder(workspace, system_prompt=system_prompt, disabled_skills=disabled_skills)
        self.context.memory.set_provider(provider)
        self.sessions = session_manager or SessionManager(workspace)
        self.tools = ToolRegistry()
        self.subagents = SubagentManager(
            provider=provider,
            workspace=workspace,
            bus=bus,
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            brave_api_key=brave_api_key,
            exec_config=self.exec_config,
            restrict_to_workspace=restrict_to_workspace,
        )

        self._running = False
        self._mcp_servers = mcp_servers or {}
        self.usage_tracker = usage_tracker or UsageTracker()
        self._mcp_stack: AsyncExitStack | None = None
        self._mcp_connected = False
        self._mcp_connecting = False
        self._consolidating: set[str] = set()  # Session keys with consolidation in progress
        self._consolidation_tasks: set[asyncio.Task] = set()  # Strong refs to in-flight tasks
        self._consolidation_locks: dict[str, asyncio.Lock] = {}
        self._active_tasks: dict[str, list[asyncio.Task]] = {}  # session_key -> tasks
        self._stop_events: dict[str, asyncio.Event] = {}  # session_key -> cooperative stop signal
        self._session_locks: dict[str, asyncio.Lock] = {}  # per-session processing locks
        self._session_lock_order: list[str] = []  # LRU tracking for session locks
        self._MAX_SESSION_LOCKS = 1000  # Upper bound to prevent unbounded growth
        self._register_default_tools()

    def update_defaults(
        self,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        memory_window: int | None = None,
        max_tool_iterations: int | None = None,
        system_prompt: str | None = None,
        disabled_skills: list[str] | None = None,
    ) -> None:
        """Hot-reload agent defaults. Only affects new sessions; existing sessions keep their overrides."""
        changed: list[str] = []
        if model is not None and model != self.model:
            self.model = model
            self.subagents.model = model
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
        if changed:
            logger.info("Agent defaults updated: {}", ", ".join(changed))

    def _register_default_tools(self) -> None:
        """Register the default set of tools."""
        allowed_dir = self.workspace if self.restrict_to_workspace else None
        for cls in (ReadFileTool, WriteFileTool, EditFileTool, ListDirTool):
            self.tools.register(cls(workspace=self.workspace, allowed_dir=allowed_dir))
        self.tools.register(ExecTool(
            working_dir=str(self.workspace),
            timeout=self.exec_config.timeout,
            restrict_to_workspace=self.restrict_to_workspace,
            path_append=self.exec_config.path_append,
        ))
        self.tools.register(WebSearchTool(api_key=self.brave_api_key))
        self.tools.register(WebFetchTool())
        self.tools.register(MessageTool(send_callback=self.bus.publish_outbound))
        self.tools.register(SpawnTool(manager=self.subagents))
        if self.cron_service:
            self.tools.register(CronTool(self.cron_service))
        if self.coding_config and self.coding_config.enabled:
            self.tools.register(CodingTool(
                working_dir=str(self.workspace),
                timeout=self.coding_config.timeout,
                api_key=self.coding_config.api_key,
                api_base=self.coding_config.api_base,
                restrict_to_workspace=self.restrict_to_workspace,
            ))

    async def _connect_mcp(self) -> None:
        """Connect to configured MCP servers (one-time, lazy)."""
        if self._mcp_connected or self._mcp_connecting or not self._mcp_servers:
            return
        self._mcp_connecting = True
        from lemonclaw.agent.tools.mcp import connect_mcp_servers
        try:
            self._mcp_stack = AsyncExitStack()
            await self._mcp_stack.__aenter__()
            await connect_mcp_servers(self._mcp_servers, self.tools, self._mcp_stack)
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

    def _set_tool_context(self, channel: str, chat_id: str, message_id: str | None = None) -> None:
        """Update context for all tools that need routing info."""
        for name in ("message", "spawn", "cron"):
            if tool := self.tools.get(name):
                if hasattr(tool, "set_context"):
                    tool.set_context(channel, chat_id, *([message_id] if name == "message" else []))

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
            return f'{tc.name}("{val[:40]}…")' if len(val) > 40 else f'{tc.name}("{val}")'
        return ", ".join(_fmt(tc) for tc in tool_calls)

    async def _run_agent_loop(
        self,
        initial_messages: list[dict],
        on_progress: Callable[..., Awaitable[None]] | None = None,
        on_chunk: Callable[..., Awaitable[None]] | None = None,
        on_tool_call: Callable[..., Awaitable[None]] | None = None,
        stop_event: asyncio.Event | None = None,
        session_model: str | None = None,
        lang: str = "en",
    ) -> tuple[str | None, list[str], list[dict], TurnUsage]:
        """Run the agent iteration loop. Returns (final_content, tools_used, messages, turn_usage)."""
        _lang = lang
        effective_model = session_model or self.model
        messages = initial_messages
        iteration = 0
        final_content = None
        tools_used: list[str] = []
        turn_usage = TurnUsage()
        _consecutive_errors: dict[str, int] = {}
        _refusal_count = 0
        _MAX_REFUSALS = 2  # track repeated tool errors
        _MAX_CONSECUTIVE_ERRORS = 3

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
                    messages = await compact(messages, effective_model, self.provider)

            try:
                response = await asyncio.wait_for(
                    self.provider.chat(
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

                for tool_call in response.tool_calls:
                    # Cooperative stop: check between tool executions
                    if stop_event and stop_event.is_set():
                        final_content = t("task_stopped", _lang)
                        break

                    tools_used.append(tool_call.name)
                    args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                    logger.info("Tool call: {}({})", tool_call.name, args_str[:200])

                    # 6.2: Send tool_start event with arguments
                    if on_progress:
                        await on_progress(json.dumps({
                            "name": tool_call.name,
                            "arguments": tool_call.arguments,
                        }, ensure_ascii=False), tool_start=True)

                    result = await self.tools.execute(tool_call.name, tool_call.arguments)

                    # 6.2: Send tool_result event
                    if on_progress:
                        result_preview = str(result)[:500] if result else ""
                        is_error = isinstance(result, str) and result.startswith("Error")
                        await on_progress(json.dumps({
                            "name": tool_call.name,
                            "result": result_preview,
                            "error": is_error,
                        }, ensure_ascii=False), tool_result=True)

                    # Detect repeated tool errors (e.g. LLM keeps calling read_file({}))
                    if isinstance(result, str) and result.startswith("Error"):
                        err_key = f"{tool_call.name}:{result[:80]}"
                        _consecutive_errors[err_key] = _consecutive_errors.get(err_key, 0) + 1
                        if _consecutive_errors[err_key] >= _MAX_CONSECUTIVE_ERRORS:
                            logger.warning("Tool {} failed {} times with same error, breaking loop",
                                           tool_call.name, _MAX_CONSECUTIVE_ERRORS)
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
                    if _refusal_count >= _MAX_REFUSALS:
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

                messages = self.context.add_assistant_message(
                    messages, clean, reasoning_content=response.reasoning_content,
                )
                final_content = clean
                break

        if final_content is None and iteration >= self.max_iterations:
            logger.warning("Max iterations ({}) reached", self.max_iterations)
            final_content = t("max_iterations", _lang, n=self.max_iterations)

        # Fallback: extract last assistant text from messages if loop ended
        # without setting final_content (e.g. last iteration was tool_calls only)
        if final_content is None:
            for m in reversed(messages):
                if m.get("role") == "assistant" and m.get("content"):
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
                task = asyncio.create_task(self._dispatch(msg))
                self._active_tasks.setdefault(msg.session_key, []).append(task)

                def _on_task_done(t: asyncio.Task, key: str = msg.session_key) -> None:
                    tasks = self._active_tasks.get(key, [])
                    if t in tasks:
                        tasks.remove(t)
                    # Clean up empty list to prevent unbounded dict growth
                    if not tasks and key in self._active_tasks:
                        del self._active_tasks[key]

                task.add_done_callback(_on_task_done)

    async def _handle_stop(self, msg: InboundMessage) -> None:
        """Cancel all active tasks and subagents for the session."""
        # Signal cooperative stop first (graceful)
        stop_event = self._stop_events.get(msg.session_key)
        if stop_event:
            stop_event.set()

        tasks = self._active_tasks.pop(msg.session_key, [])
        cancelled = sum(1 for tk in tasks if not tk.done() and tk.cancel())
        for tk in tasks:
            try:
                await tk
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.debug("Task ended with error during stop for session {}", msg.session_key)
        sub_cancelled = await self.subagents.cancel_by_session(msg.session_key)
        total = cancelled + sub_cancelled
        lang = session_lang(self.sessions._load(msg.session_key))
        content = t("stop_tasks", lang, n=total) if total else t("stop_none", lang)
        await self.bus.publish_outbound(OutboundMessage(
            channel=msg.channel, chat_id=msg.chat_id, content=content,
            metadata=msg.metadata or {},
        ))

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

        async with lock:
            try:
                response = await self._process_message(msg, stop_event=stop_event)

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
                if request_id:
                    self.bus.resolve_response(request_id, "[cancelled]")
                raise
            except Exception as exc:
                logger.exception("Error processing message for session {}", msg.session_key)
                # Procedural memory: reflect on failure to learn from it
                try:
                    await self.context.memory.procedural.reflect(
                        self.provider,
                        task_description=msg.content[:200],
                        error=str(exc)[:200],
                        model=self.model,
                    )
                except Exception:
                    pass  # reflect is best-effort, never block error handling
                if request_id:
                    self.bus.resolve_response(request_id, "[error]")
                else:
                    lang = session_lang(self.sessions._load(msg.session_key))
                    await self.bus.publish_outbound(OutboundMessage(
                        channel=msg.channel, chat_id=msg.chat_id,
                        content=t("error", lang),
                    ))
            finally:
                self._stop_events.pop(msg.session_key, None)

    async def close_mcp(self) -> None:
        """Close MCP connections."""
        if self._mcp_stack:
            try:
                await self._mcp_stack.aclose()
            except (RuntimeError, BaseExceptionGroup):
                pass  # MCP SDK cancel scope cleanup is noisy but harmless
            self._mcp_stack = None

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
            key = f"{channel}:{chat_id}"
            session = self.sessions.get_or_create(key)
            session_model = session.metadata.get("current_model")
            self._set_tool_context(channel, chat_id, msg.metadata.get("message_id"))
            history = session.get_history(max_messages=self.memory_window)
            messages = self.context.build_messages(
                history=history,
                current_message=msg.content, channel=channel, chat_id=chat_id,
                timezone=msg.metadata.get("timezone") or self.default_timezone,
            )
            # Token-level compaction for system messages too
            from lemonclaw.session.compaction import compact, needs_compaction
            if needs_compaction(messages, session_model or self.model):
                messages = await compact(messages, session_model or self.model, self.provider)
            final_content, _, all_msgs, turn_usage = await self._run_agent_loop(
                messages, stop_event=stop_event, session_model=session_model,
                lang=session_lang(session),
            )
            self._save_turn(session, all_msgs, 1 + len(history))
            # Record usage for system messages
            if turn_usage.llm_calls:
                self.usage_tracker.record_turn(key, turn_usage, session.metadata)
            self.sessions.save(session)
            return OutboundMessage(channel=channel, chat_id=chat_id,
                                  content=final_content or t("bg_task_done", session_lang(session)))

        preview = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content
        logger.info("Processing message from {}:{}: {}", msg.channel, msg.sender_id, preview)

        # Broadcast inbound user message to Activity Feed
        if msg.channel != "webui" and self.activity_bus:
            await self.activity_bus.broadcast({
                "type": "message",
                "session_key": msg.session_key,
                "channel": msg.channel,
                "role": "user",
                "content": msg.content,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        key = session_key or msg.session_key
        session = self.sessions.get_or_create(key)

        # Auto-detect language from first message if not set
        if "lang" not in session.metadata:
            session.metadata["lang"] = detect_lang(msg.content)

        lang = session_lang(session)

        # Empty message guard — don't waste tokens on blank input
        if not msg.content.strip():
            return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                  content=t("empty_message", lang))

        # Slash commands
        cmd = msg.content.strip().lower()
        if cmd == "/new":
            lock = self._consolidation_locks.setdefault(session.key, asyncio.Lock())
            self._consolidating.add(session.key)
            try:
                async with lock:
                    snapshot = session.messages[session.last_consolidated:]
                    if snapshot:
                        temp = Session(key=session.key)
                        temp.messages = list(snapshot)
                        if not await self._consolidate_memory(temp, archive_all=True):
                            return OutboundMessage(
                                channel=msg.channel, chat_id=msg.chat_id,
                                content=t("memory_archival_failed", lang),
                            )
            except Exception:
                logger.exception("/new archival failed for {}", session.key)
                return OutboundMessage(
                    channel=msg.channel, chat_id=msg.chat_id,
                    content=t("memory_archival_failed", lang),
                )
            finally:
                self._consolidating.discard(session.key)
                if not lock.locked():
                    self._consolidation_locks.pop(session.key, None)

            session.clear()
            self.sessions.save(session)
            self.sessions.invalidate(session.key)
            return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                  content=t("new_session", lang))
        if cmd == "/usage":
            return OutboundMessage(
                channel=msg.channel, chat_id=msg.chat_id,
                content=self.usage_tracker.format_session_usage(session.metadata),
            )
        if cmd == "/help":
            return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                  content=t("help", lang))
        if cmd == "/model" or cmd.startswith("/model "):
            return self._handle_model_command(msg, session, lang)
        # Unknown slash command guard
        if cmd.startswith("/") and not cmd[1:2].isspace():
            known = ("/new", "/usage", "/help", "/model", "/stop")
            first_word = cmd.split()[0]
            if first_word not in known:
                return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                      content=t("unknown_command", lang, cmd=first_word))

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
            lock = self._consolidation_locks.setdefault(session.key, asyncio.Lock())

            async def _consolidate_and_unlock():
                try:
                    async with lock:
                        if await self._consolidate_memory(session):
                            # Save after consolidation — messages may have been truncated
                            self.sessions.save(session)
                finally:
                    self._consolidating.discard(session.key)
                    if not lock.locked():
                        self._consolidation_locks.pop(session.key, None)
                    _task = asyncio.current_task()
                    if _task is not None:
                        self._consolidation_tasks.discard(_task)

            _task = asyncio.create_task(_consolidate_and_unlock())
            self._consolidation_tasks.add(_task)

        self._set_tool_context(msg.channel, msg.chat_id, msg.metadata.get("message_id"))
        if message_tool := self.tools.get("message"):
            if isinstance(message_tool, MessageTool):
                message_tool.start_turn()

        # Per-session model override
        session_model = session.metadata.get("current_model")

        history = session.get_history(max_messages=self.memory_window)
        initial_messages = self.context.build_messages(
            history=history,
            current_message=msg.content,
            media=msg.media if msg.media else None,
            channel=msg.channel, chat_id=msg.chat_id,
            timezone=msg.metadata.get("timezone") or self.default_timezone,
        )

        # 6.3: Per-session system prompt override — append to system message
        session_system_prompt = session.metadata.get("system_prompt_override")
        if session_system_prompt and initial_messages and initial_messages[0].get("role") == "system":
            initial_messages[0]["content"] += (
                f"\n\n# Session Instructions\n\n{session_system_prompt}"
            )

        # Token-level compaction: summarize middle messages if over threshold
        from lemonclaw.session.compaction import compact, needs_compaction
        if needs_compaction(initial_messages, session_model or self.model):
            initial_messages = await compact(
                initial_messages, session_model or self.model, self.provider,
            )

        async def _bus_progress(content: str, *, tool_hint: bool = False,
                                thinking: bool = False, tool_start: bool = False,
                                tool_result: bool = False) -> None:
            meta = dict(msg.metadata or {})
            meta["_progress"] = True
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

        final_content, _, all_msgs, turn_usage = await self._run_agent_loop(
            initial_messages, on_progress=on_progress or _bus_progress,
            on_chunk=on_chunk or _bus_chunk,
            on_tool_call=_activity_tool_call,
            stop_event=stop_event, session_model=session_model, lang=lang,
        )

        if final_content is None:
            final_content = t("no_response", lang)

        self._save_turn(session, all_msgs, 1 + len(history))

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

        if (mt := self.tools.get("message")) and isinstance(mt, MessageTool) and mt._sent_in_turn:
            return None

        preview = final_content[:120] + "..." if len(final_content) > 120 else final_content
        logger.info("Response to {}:{}: {}", msg.channel, msg.sender_id, preview)
        return OutboundMessage(
            channel=msg.channel, chat_id=msg.chat_id, content=final_content,
            metadata=msg.metadata or {},
        )

    def _handle_model_command(self, msg: InboundMessage, session: Session, lang: str = "en") -> OutboundMessage:
        """Handle /model [name] — list models or switch the session model."""
        arg = msg.content.strip()[6:].strip()  # strip "/model" prefix

        if not arg:
            current = session.metadata.get("current_model") or self.model
            return OutboundMessage(
                channel=msg.channel, chat_id=msg.chat_id,
                content=format_model_list(current),
            )

        match = fuzzy_match(arg)
        if not match:
            return OutboundMessage(
                channel=msg.channel, chat_id=msg.chat_id,
                content=t("no_model_match", lang, arg=arg),
            )

        session.metadata["current_model"] = match.id
        self.sessions.save(session)

        # Also update global default (D5/R7: /model = same as Settings tab)
        self.update_defaults(model=match.id)
        # Persist to config.json so it survives restart
        self._persist_model_default(match.id)

        return OutboundMessage(
            channel=msg.channel, chat_id=msg.chat_id,
            content=t("model_switched", lang, label=match.label, id=match.id, desc=match.description),
        )

    def _persist_model_default(self, model: str) -> None:
        """Persist model change to config.json (D5: /model = same as Settings tab)."""
        try:
            from lemonclaw.config import load_config, get_config_path
            from lemonclaw.config.loader import save_config
            path = get_config_path()
            config = load_config(path)
            if config.agents.defaults.model != model:
                config.agents.defaults.model = model
                save_config(config, path)
                logger.info("/model: persisted default model to config.json: {}", model)
        except Exception:
            logger.warning("/model: failed to persist to config.json (ephemeral only)")

    def _save_turn(self, session: Session, messages: list[dict], skip: int) -> None:
        """Save new-turn messages into session, truncating large tool results."""
        for m in messages[skip:]:
            entry = {k: v for k, v in m.items() if k != "reasoning_content"}
            role, content = entry.get("role"), entry.get("content")
            if role == "tool" and isinstance(content, str) and len(content) > self._TOOL_RESULT_MAX_CHARS:
                entry["content"] = content[:self._TOOL_RESULT_MAX_CHARS] + "\n... (truncated)"
            elif role == "user":
                if isinstance(content, str) and content.startswith(ContextBuilder._RUNTIME_CONTEXT_TAG):
                    # Strip runtime context prefix — save only the user's actual message.
                    # build_messages() stores original text in _original_text key.
                    original = m.get("_original_text")
                    if original:
                        entry["content"] = original
                        entry.pop("_original_text", None)
                    else:
                        continue
                if isinstance(content, list):
                    entry["content"] = [
                        {"type": "text", "text": "[image]"} if (
                            c.get("type") == "image_url"
                            and c.get("image_url", {}).get("url", "").startswith("data:image/")
                        ) else c for c in content
                    ]
            entry.setdefault("timestamp", datetime.now().isoformat())
            session.messages.append(entry)
        session.updated_at = datetime.now()

    async def _consolidate_memory(self, session, archive_all: bool = False) -> bool:
        """Delegate to MemoryStore.consolidate(). Uses Groq for speed + cost."""
        from lemonclaw.config.defaults import DEFAULT_CONSOLIDATION_MODEL
        return await self.context.memory.consolidate(
            session, self.provider, DEFAULT_CONSOLIDATION_MODEL,
            archive_all=archive_all, memory_window=self.memory_window,
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
    ) -> str:
        """Process a message directly (for CLI or cron usage)."""
        await self._connect_mcp()
        if session_key not in self._session_locks:
            self._session_locks[session_key] = asyncio.Lock()
            if len(self._session_locks) > self._MAX_SESSION_LOCKS:
                self._evict_idle_session_locks()
        if session_key in self._session_lock_order:
            self._session_lock_order.remove(session_key)
        self._session_lock_order.append(session_key)
        async with self._session_locks[session_key]:
            msg = InboundMessage(channel=channel, sender_id="user", chat_id=chat_id, content=content,
                                 metadata=metadata or {}, media=media or [])
            response = await self._process_message(msg, session_key=session_key, on_progress=on_progress, on_chunk=on_chunk)
        return response.content if response else ""
