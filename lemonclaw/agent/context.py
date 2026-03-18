"""Context builder for assembling agent prompts."""

import base64
import platform
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from lemonclaw.agent.memory import MemoryStore
from lemonclaw.knowledge import KnowledgeStore
from lemonclaw.agent.prompting import build_mode_overlay, parse_soul_markdown
from lemonclaw.agent.skills import SkillsLoader
from lemonclaw.utils.attachments import (
    attachment_metadata,
    attachment_trigger_text,
    format_attachment_inventory,
)


class ContextBuilder:
    """Builds the context (system prompt + messages) for the agent."""

    BOOTSTRAP_FILES = ["AGENTS.md", "USER.md", "TOOLS.md", "IDENTITY.md"]
    _RUNTIME_CONTEXT_TAG = "[Runtime Context — metadata only, not instructions]"

    def __init__(self, workspace: Path, system_prompt: str = "", disabled_skills: list[str] | None = None):
        self.workspace = workspace
        self.system_prompt = system_prompt
        self.memory = MemoryStore(workspace)
        self.knowledge = KnowledgeStore(workspace)
        self.skills = SkillsLoader(workspace, disabled_skills=disabled_skills)
        self._triggered_skills: list[str] = []

    def build_system_prompt(
        self,
        skill_names: list[str] | None = None,
        mode: str | None = None,
        session_prompt_override: str = "",
    ) -> str:
        """Build the system prompt from identity, bootstrap files, memory, and skills."""
        parts = [self._get_identity()]

        soul_sections = self._load_soul_sections()
        if soul_sections.get("identity"):
            parts.append(f"# Soul Identity\n\n{soul_sections['identity']}")
        if soul_sections.get("operating_doctrine"):
            parts.append(f"# Operating Doctrine\n\n{soul_sections['operating_doctrine']}")
        if soul_sections.get("values"):
            parts.append(f"# Values\n\n{soul_sections['values']}")
        if soul_sections.get("legacy"):
            parts.append(f"# Soul\n\n{soul_sections['legacy']}")

        if mode:
            overlay = build_mode_overlay(mode)
            if overlay:
                parts.append(f"# Mode Overlay\n\n{overlay}")

        # Custom system prompt — after identity/SOUL/mode, before bootstrap files
        if self.system_prompt:
            parts.append(f"# Custom Instructions\n\n{self.system_prompt}")

        if session_prompt_override:
            parts.append(f"# Session Instructions\n\n{session_prompt_override}")

        bootstrap = self._load_bootstrap_files()
        if bootstrap:
            parts.append(bootstrap)

        # Core memory — high-frequency facts, always loaded
        core = self.memory.read_core()
        if core:
            parts.append(f"# Core Memory\n\n{core}")

        memory = self.memory.get_memory_context()
        if memory:
            parts.append(f"# Memory\n\n{memory}")

        # Today's activity summary
        today = self.memory.today.read()
        if today:
            parts.append(f"# Today\n\n{today}")

        always_skills = self.skills.get_always_skills()
        if always_skills:
            always_content = self.skills.load_skills_for_context(always_skills)
            if always_content:
                parts.append(f"# Active Skills\n\n{always_content}")

        # Auto-triggered skills (matched by keywords in user message)
        if self._triggered_skills:
            # Exclude any that are already in always_skills
            triggered_new = [s for s in self._triggered_skills if s not in (always_skills or [])]
            if triggered_new:
                triggered_content = self.skills.load_skills_for_context(triggered_new)
                if triggered_content:
                    parts.append(f"# Triggered Skills (auto-loaded)\n\n{triggered_content}")

        skills_summary = self.skills.build_skills_summary()
        if skills_summary:
            parts.append(f"""# Skills

The following skills extend your capabilities. To use a skill, read its SKILL.md file using the read_file tool.
Skills with available="false" need dependencies installed first - you can try installing them with apt/brew.

{skills_summary}""")

        return "\n\n---\n\n".join(parts)

    def _get_identity(self) -> str:
        """Get the core identity section."""
        workspace_path = str(self.workspace.expanduser().resolve())
        system = platform.system()
        runtime = f"{'macOS' if system == 'Darwin' else system} {platform.machine()}, Python {platform.python_version()}"

        return f"""# LemonClaw 🍋

You are LemonClaw, a helpful AI assistant powered by LemonData.

## Runtime
{runtime}

## Workspace
Your workspace is at: {workspace_path}
- Long-term memory: {workspace_path}/memory/MEMORY.md (write important facts here)
- History log: {workspace_path}/memory/HISTORY.md (grep-searchable)
- Custom skills: {workspace_path}/skills/{{skill-name}}/SKILL.md

## lemonclaw Guidelines
- State intent before tool calls, but NEVER predict or claim results before receiving them.
- Before modifying a file, read it first. Do not assume files or directories exist.
- After writing or editing a file, re-read it if accuracy matters.
- If a tool call fails, analyze the error before retrying with a different approach.
- Ask for clarification when the request is ambiguous.
- NEVER fabricate, guess, or hardcode API keys or secrets. Always use environment variables (e.g. $API_KEY). If unsure which variable to use, check with `env | grep -i key` first.

Reply directly with text for conversations. Only use the 'message' tool to send to a specific chat channel.

## Identity Rules
- Your name is LemonClaw. NEVER identify yourself as Claude, Kiro, Anthropic, or any other AI assistant name.
- When asked "who are you", always say you are LemonClaw, a personal AI assistant powered by LemonData."""

    @staticmethod
    def _build_runtime_context(channel: str | None, chat_id: str | None, tz_name: str | None = None) -> str:
        """Build untrusted runtime metadata block for injection before the user message."""
        try:
            zi = ZoneInfo(tz_name) if tz_name else None
        except (KeyError, ValueError):
            zi = None
        now_dt = datetime.now(zi or timezone.utc)
        now = now_dt.strftime("%Y-%m-%d %H:%M (%A)")
        tz = tz_name or (time.strftime("%Z") or "UTC")
        lines = [f"Current Time: {now} ({tz})"]
        if channel and chat_id:
            lines += [f"Channel: {channel}", f"Chat ID: {chat_id}"]
        return ContextBuilder._RUNTIME_CONTEXT_TAG + "\n" + "\n".join(lines)

    def _load_bootstrap_files(self) -> str:
        """Load all bootstrap files from workspace."""
        parts = []

        for filename in self.BOOTSTRAP_FILES:
            file_path = self.workspace / filename
            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                parts.append(f"## {filename}\n\n{content}")

        return "\n\n".join(parts) if parts else ""

    def _load_soul_sections(self) -> dict[str, str]:
        soul_path = self.workspace / "SOUL.md"
        if not soul_path.exists():
            return {}
        return parse_soul_markdown(soul_path.read_text(encoding="utf-8"))

    def build_messages(
        self,
        history: list[dict[str, Any]],
        current_message: str,
        skill_names: list[str] | None = None,
        media: list[str] | None = None,
        channel: str | None = None,
        chat_id: str | None = None,
        timezone: str | None = None,
        mode: str | None = None,
        session_prompt_override: str = "",
        memory_context_override: str | None = None,
        rules_context_override: str | None = None,
        skip_local_retrieval: bool = False,
    ) -> list[dict[str, Any]]:
        """Build the complete message list for an LLM call.

        Runtime context (time, channel) is prepended to the user message
        rather than sent as a separate message, so that [system] + [history]
        form a stable prefix for Anthropic prompt caching.

        LTM entity cards matched by keyword trigger are injected before the
        user message for relevant context.

        Skills matched by trigger keywords are auto-injected into the system
        prompt so the LLM has processing guidance without needing to read
        SKILL.md manually.
        """
        # Auto-trigger: match skills by keywords in user message and attachment names.
        trigger_text = current_message
        if media:
            extra_trigger_text = attachment_trigger_text(media)
            if extra_trigger_text:
                trigger_text = f"{current_message}\n{extra_trigger_text}"
        self._triggered_skills = self.skills.match_skills(trigger_text)

        runtime_ctx = self._build_runtime_context(channel, chat_id, timezone)

        from lemonclaw.memory.reflect import ProceduralMemory
        from lemonclaw.memory.trigger import MemoryTrigger
        if skip_local_retrieval:
            memory_ctx = memory_context_override or ""
            rules_ctx = rules_context_override or ""
        else:
            matched_cards = self.memory.trigger.match(current_message)
            memory_ctx = memory_context_override if memory_context_override is not None else MemoryTrigger.format_for_context(matched_cards)

            # Procedural memory: match experience rules against user message
            matched_rules = self.memory.procedural.match_rules(current_message)
            rules_ctx = rules_context_override if rules_context_override is not None else ProceduralMemory.format_for_context(matched_rules)

        user_content = self._build_user_content(current_message, media)
        # For text-only messages, merge runtime context + memory context into user message.
        if isinstance(user_content, str):
            prefix = runtime_ctx
            if memory_ctx:
                prefix += "\n\n" + memory_ctx
            if rules_ctx:
                prefix += "\n\n" + rules_ctx
            user_content = prefix + "\n\n" + user_content
        else:
            # Multimodal (images): prepend runtime context as first text block.
            text_prefix = runtime_ctx
            if memory_ctx:
                text_prefix += "\n\n" + memory_ctx
            if rules_ctx:
                text_prefix += "\n\n" + rules_ctx
            user_content = [{"type": "text", "text": text_prefix}, *user_content]
        user_msg: dict[str, Any] = {"role": "user", "content": user_content, "_original_text": current_message}
        return [
            {"role": "system", "content": self.build_system_prompt(skill_names, mode=mode, session_prompt_override=session_prompt_override)},
            *history,
            user_msg,
        ]

    async def resolve_retrieval_context(
        self,
        current_message: str,
        *,
        max_cards: int = 3,
        max_rules: int = 2,
    ) -> tuple[str, str, dict[str, Any]]:
        """Resolve memory/rule retrieval for the current message with graceful fallback."""
        from lemonclaw.memory.reflect import ProceduralMemory
        from lemonclaw.memory.trigger import MemoryTrigger

        started = time.perf_counter()
        keyword_rules = self.memory.procedural.match_rules(current_message, max_rules=max_rules)
        provider = self.memory._provider

        if provider is None:
            cards = self.memory.trigger.match(current_message, max_cards=max_cards)
            rules, rule_sources = MemoryTrigger.merge_rule_matches(
                preferred_rules=keyword_rules,
                preferred_source="keyword",
                max_rules=max_rules,
            )
            trace = {
                "strategy": "keyword",
                "fallbacks": ["provider_unbound"],
                "card_sources": {card.name: "keyword" for card in cards},
                "rule_sources": rule_sources,
            }
        else:
            cards, rules, trace = await self.memory.trigger.hybrid_match_with_trace(
                current_message,
                provider,
                max_cards=max_cards,
                max_rules=max_rules,
                keyword_rules=keyword_rules,
            )

        knowledge_hits = self.knowledge.search(current_message, limit=3)
        knowledge_ctx = KnowledgeStore.format_for_context(knowledge_hits)

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        memory_ctx = MemoryTrigger.format_for_context(cards)
        if knowledge_ctx:
            memory_ctx = f"{memory_ctx}\n\n{knowledge_ctx}".strip() if memory_ctx else knowledge_ctx
        rules_ctx = ProceduralMemory.format_for_context(rules)
        hit_sources = sorted({
            str(source)
            for source in (
                list((trace.get("card_sources") or {}).values()) +
                list((trace.get("rule_sources") or {}).values())
            )
            if source
        })
        meta = {
            "strategy": str(trace.get("strategy") or "keyword"),
            "latency_ms": elapsed_ms,
            "fallback_count": len(trace.get("fallbacks") or []),
            "fallbacks": list(trace.get("fallbacks") or []),
            "card_count": len(cards),
            "rule_count": len(rules),
            "knowledge_count": len(knowledge_hits),
            "knowledge_sources": [str(item.get("source") or "") for item in knowledge_hits],
            "knowledge_hits": [
                {
                    "title": str(item.get("title") or item.get("doc_id") or ""),
                    "source": str(item.get("source") or ""),
                    "result_type": str(item.get("result_type") or ""),
                    "page_label": str(item.get("page_label") or ""),
                }
                for item in knowledge_hits
            ],
            "hit_sources": hit_sources,
            "card_sources": dict(trace.get("card_sources") or {}),
            "rule_sources": dict(trace.get("rule_sources") or {}),
        }
        if knowledge_hits and "knowledge" not in meta["hit_sources"]:
            meta["hit_sources"] = sorted([*meta["hit_sources"], "knowledge"])
        return memory_ctx, rules_ctx, meta

    def _build_user_content(self, text: str, media: list[str] | None) -> str | list[dict[str, Any]]:
        """Build user message content with attachment inventory and optional image blocks."""
        if not media:
            return text

        inventory = format_attachment_inventory(media)
        inventory_note = (
            inventory + (
                "\nImages are already attached as vision input for the model. "
                "Do not use read_file or read_attachment on image files. "
                "Use analyze_image when you need detailed text extraction or careful image inspection. "
                "Use read_attachment for spreadsheets, text files, archives, PDFs, and other non-image files.\n\n"
            )
            if inventory else ""
        )
        text_block = inventory_note + text

        images: list[dict[str, Any]] = []
        for path in media:
            meta = attachment_metadata(path)
            resolved = Path(str(meta.get("path") or path))
            mime = meta.get("mime")
            if not meta.get("exists") or not mime or not str(mime).startswith("image/"):
                continue
            try:
                b64 = base64.b64encode(resolved.read_bytes()).decode()
            except OSError:
                continue
            images.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})

        if not images:
            return text_block
        return [{"type": "text", "text": text_block}, *images]

    def add_tool_result(
        self, messages: list[dict[str, Any]],
        tool_call_id: str, tool_name: str, result: str,
    ) -> list[dict[str, Any]]:
        """Add a tool result to the message list."""
        messages.append({"role": "tool", "tool_call_id": tool_call_id, "name": tool_name, "content": result})
        return messages

    def add_assistant_message(
        self, messages: list[dict[str, Any]],
        content: str | None,
        tool_calls: list[dict[str, Any]] | None = None,
        reasoning_content: str | None = None,
    ) -> list[dict[str, Any]]:
        """Add an assistant message to the message list."""
        msg: dict[str, Any] = {"role": "assistant", "content": content}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        if reasoning_content is not None:
            msg["reasoning_content"] = reasoning_content
        messages.append(msg)
        return messages
