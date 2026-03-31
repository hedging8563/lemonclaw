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

    def _session_summary_snippet(self) -> str:
        today = self.memory.today.read().strip()
        if not today:
            return ""
        entries: list[list[str]] = []
        current: list[str] = []

        for raw_line in today.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("# "):
                continue
            if line.startswith("## "):
                if current:
                    entries.append(current)
                current = []
                title = line[3:].strip()
                if " — " in title:
                    title = title.split(" — ", 1)[1].strip()
                if title:
                    current.append(title)
                continue
            for prefix in ("- ", "* ", "+ ", "• "):
                if line.startswith(prefix):
                    line = line[len(prefix):].strip()
                    break
            if line:
                current.append(line)

        if current:
            entries.append(current)
        if not entries:
            return ""

        recent_lines: list[str] = []
        seen: set[str] = set()
        for entry in reversed(entries):
            for line in entry:
                if line in seen:
                    continue
                seen.add(line)
                recent_lines.append(line)
                if len(recent_lines) >= 3:
                    break
            if len(recent_lines) >= 3:
                break

        return "\n".join(recent_lines[:3])[:240]

    @staticmethod
    def _compact_summary(text: str, *, limit: int = 160) -> str:
        lines: list[str] = []
        for raw_line in str(text or "").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            for prefix in ("- ", "* ", "+ ", "• "):
                if line.startswith(prefix):
                    line = line[len(prefix):].strip()
                    break
            if line and line not in lines:
                lines.append(line)
        if not lines:
            return str(text or "").strip()[:limit]
        return " ".join(lines)[:limit]

    @staticmethod
    def _build_structured_retrieval_objects(
        *,
        cards: list[Any],
        rules: list[dict[str, Any]],
        knowledge_hits: list[dict[str, Any]],
        session_summary: str = "",
    ) -> dict[str, Any]:
        normalized_cards: list[dict[str, Any]] = []
        for card in cards:
            name = str(getattr(card, "name", "") or "").strip()
            if not name:
                continue
            raw_meta = getattr(card, "meta", {}) or {}
            card_meta = dict(raw_meta) if isinstance(raw_meta, dict) else {}
            card_type = str(card_meta.get("type", "") or "").strip()
            summary = ContextBuilder._compact_summary(str(getattr(card, "body", "") or ""), limit=160)
            keywords = [
                keyword
                for keyword in dict.fromkeys(
                    str(keyword or "").strip()
                    for keyword in list(getattr(card, "keywords", []) or [])
                    if str(keyword or "").strip()
                )
            ]
            normalized_cards.append({
                "name": name,
                "type": card_type,
                "summary": summary,
                "keywords": keywords,
            })
        normalized_cards.sort(key=lambda item: (item["name"].casefold(), item["type"].casefold(), item["summary"].casefold()))

        fact_slots: list[dict[str, Any]] = []
        retrieval_objects: list[dict[str, Any]] = []
        seen_card_names: set[str] = set()
        for item in normalized_cards:
            card_key = item["name"].casefold()
            if card_key in seen_card_names:
                continue
            seen_card_names.add(card_key)
            fact_slots.append(item)
            retrieval_objects.append({
                "kind": "entity_card",
                "id": item["name"],
                "title": item["name"],
                "source": "memory.entities",
                "summary": item["summary"],
                "keywords": item["keywords"],
            })

        normalized_rules: list[dict[str, Any]] = []
        for rule in rules:
            trigger = str(rule.get("trigger") or "").strip()
            if not trigger:
                continue
            source = str(rule.get("source") or "memory.rules").strip() or "memory.rules"
            lesson = str(rule.get("lesson") or "").strip()
            action = str(rule.get("action") or "").strip()
            summary = " ".join(part for part in (lesson, action) if part)
            normalized_rules.append({
                "trigger": trigger,
                "id": str(rule.get("header") or trigger).strip() or trigger,
                "source": source,
                "summary": ContextBuilder._compact_summary(summary, limit=160),
                "lesson": lesson,
                "action": action,
            })
        normalized_rules.sort(key=lambda item: (item["trigger"].casefold(), item["source"].casefold(), item["summary"].casefold()))

        seen_rule_keys: set[tuple[str, str]] = set()
        for item in normalized_rules:
            rule_key = (item["trigger"].casefold(), item["source"].casefold())
            if rule_key in seen_rule_keys:
                continue
            seen_rule_keys.add(rule_key)
            retrieval_objects.append({
                "kind": "procedural_rule",
                "id": item["id"],
                "title": item["trigger"],
                "source": item["source"],
                "summary": item["summary"],
                "lesson": item["lesson"],
                "action": item["action"],
            })

        normalized_hits: list[dict[str, Any]] = []
        for item in knowledge_hits:
            doc_id = str(item.get("doc_id") or "").strip()
            if not doc_id:
                continue
            title = str(item.get("title") or doc_id or "").strip()
            source = str(item.get("source") or "").strip()
            page_label = str(item.get("page_label") or "").strip()
            result_type = str(item.get("result_type") or "").strip()
            summary = ContextBuilder._compact_summary(str(item.get("snippet") or item.get("summary") or ""), limit=160)
            normalized_hits.append({
                "kind": "knowledge_hit",
                "id": doc_id,
                "title": title or doc_id,
                "source": source,
                "summary": summary,
                "result_type": result_type,
                "page_label": page_label,
            })
        normalized_hits.sort(key=lambda item: (item["source"].casefold(), item["title"].casefold(), item["id"].casefold(), item["summary"].casefold()))

        seen_hit_keys: set[tuple[str, str, str]] = set()
        for item in normalized_hits:
            hit_key = (item["id"].casefold(), item["source"].casefold(), item["title"].casefold())
            if hit_key in seen_hit_keys:
                continue
            seen_hit_keys.add(hit_key)
            retrieval_objects.append(item)

        fact_slot_summary = ContextBuilder._build_fact_slot_summary_object(fact_slots=fact_slots)
        retrieval_surface_summary = ContextBuilder._build_retrieval_surface_summary_object(
            rules=normalized_rules,
            knowledge_hits=normalized_hits,
        )

        summary_text = str(session_summary or "").strip()
        summary_object = {
            "kind": "session_summary",
            "id": "session_summary",
            "title": "Session Summary",
            "source": "memory.today",
            "summary": summary_text,
            "session_summary": summary_text,
            "status": "present" if summary_text else "empty",
        }

        return {
            "session_summary": summary_text,
            "fact_slots": fact_slots,
            "fact_slot_summary": fact_slot_summary,
            "retrieval_objects": [summary_object, retrieval_surface_summary, fact_slot_summary, *retrieval_objects],
        }

    @staticmethod
    def _build_fact_slot_summary_object(*, fact_slots: list[dict[str, Any]]) -> dict[str, Any]:
        names: list[str] = []
        summaries: list[str] = []
        keywords: list[str] = []
        seen_keywords: set[str] = set()
        for item in fact_slots:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            summary = str(item.get("summary") or "").strip()
            if name:
                names.append(name)
            if summary:
                summaries.append(summary)
            for keyword in list(item.get("keywords") or []):
                keyword_text = str(keyword or "").strip()
                if not keyword_text or keyword_text in seen_keywords:
                    continue
                seen_keywords.add(keyword_text)
                keywords.append(keyword_text)

        summary_parts: list[str] = []
        if names:
            summary_parts.append(f"{len(names)} fact slot(s)")
            summary_parts.append(", ".join(names[:3]))
        if summaries:
            summary_parts.append(" | ".join(summaries[:2]))

        summary = "; ".join(part for part in summary_parts if part).strip()
        return {
            "kind": "fact_slot_summary",
            "id": "fact_slot_summary",
            "title": "Fact Slot Summary",
            "source": "memory.entities",
            "summary": summary,
            "status": "present" if summary else "empty",
            "fact_slot_count": len(names),
            "fact_slot_names": names[:4],
            "fact_slot_summaries": summaries[:4],
            "keywords": keywords[:6],
        }

    @staticmethod
    def _build_retrieval_surface_summary_object(
        *,
        rules: list[dict[str, Any]],
        knowledge_hits: list[dict[str, Any]],
    ) -> dict[str, Any]:
        rule_triggers: list[str] = []
        seen_rule_keys: set[tuple[str, str]] = set()
        for item in rules:
            trigger = str(item.get("trigger") or "").strip()
            source = str(item.get("source") or "").strip()
            if not trigger:
                continue
            key = (trigger.casefold(), source.casefold())
            if key in seen_rule_keys:
                continue
            seen_rule_keys.add(key)
            rule_triggers.append(trigger)

        knowledge_titles: list[str] = []
        seen_hit_keys: set[tuple[str, str, str]] = set()
        for item in knowledge_hits:
            doc_id = str(item.get("id") or "").strip()
            source = str(item.get("source") or "").strip()
            title = str(item.get("title") or item.get("id") or "").strip()
            if not doc_id or not title:
                continue
            key = (doc_id.casefold(), source.casefold(), title.casefold())
            if key in seen_hit_keys:
                continue
            seen_hit_keys.add(key)
            knowledge_titles.append(title)

        summary_parts: list[str] = []
        if rule_triggers:
            summary_parts.append(f"{len(rule_triggers)} procedural rule(s)")
        if knowledge_titles:
            summary_parts.append(f"{len(knowledge_titles)} knowledge hit(s)")

        summary = "; ".join(summary_parts)
        return {
            "kind": "retrieval_surface_summary",
            "id": "retrieval_surface_summary",
            "title": "Retrieval Surface Summary",
            "source": "memory.retrieval",
            "summary": summary,
            "status": "present" if summary_parts else "empty",
            "procedural_rule_count": len(rule_triggers),
            "knowledge_hit_count": len(knowledge_titles),
            "procedural_rules": rule_triggers[:4],
            "knowledge_titles": knowledge_titles[:4],
        }

    @staticmethod
    def _build_retrieval_diagnostics_object(meta: dict[str, Any]) -> dict[str, Any] | None:
        fallback_count = int(meta.get("fallback_count") or 0)
        fallbacks = [str(item) for item in list(meta.get("fallbacks") or []) if str(item)]
        hit_sources = [str(item) for item in list(meta.get("hit_sources") or []) if str(item)]
        if fallback_count <= 0 and not fallbacks:
            return None

        structured = dict(meta.get("structured") or {})
        return {
            "kind": "retrieval_diagnostics",
            "id": f"retrieval:{str(meta.get('strategy') or 'unknown')}:{fallback_count}",
            "title": "Retrieval Diagnostics",
            "source": "memory.failsoft",
            "summary": (
                f"{str(meta.get('strategy') or 'unknown')} retrieval "
                f"with {fallback_count} fallback(s)"
            ),
            "fallback_count": fallback_count,
            "fallbacks": fallbacks,
            "hit_sources": hit_sources,
            "card_count": int(meta.get("card_count") or 0),
            "rule_count": int(meta.get("rule_count") or 0),
            "knowledge_count": int(meta.get("knowledge_count") or 0),
            "session_summary": str(structured.get("session_summary") or "").strip(),
            "status": "fail_soft" if fallback_count > 0 else "healthy",
        }

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
        retrieval_fallbacks: list[str] = []
        try:
            keyword_rules = self.memory.procedural.match_rules(current_message, max_rules=max_rules)
        except Exception as exc:
            keyword_rules = []
            retrieval_fallbacks.append(f"procedural_rules_error:{type(exc).__name__}")
        provider = self.memory._provider

        if provider is None:
            try:
                cards = self.memory.trigger.match(current_message, max_cards=max_cards)
            except Exception as exc:
                cards = []
                retrieval_fallbacks.append(f"memory_trigger_error:{type(exc).__name__}")
            rules, rule_sources = MemoryTrigger.merge_rule_matches(
                preferred_rules=keyword_rules,
                preferred_source="keyword",
                max_rules=max_rules,
            )
            trace = {
                "strategy": "keyword",
                "fallbacks": ["provider_unbound", *retrieval_fallbacks],
                "card_sources": {card.name: "keyword" for card in cards},
                "rule_sources": rule_sources,
            }
        else:
            try:
                cards, rules, trace = await self.memory.trigger.hybrid_match_with_trace(
                    current_message,
                    provider,
                    max_cards=max_cards,
                    max_rules=max_rules,
                    keyword_rules=keyword_rules,
                )
            except Exception as exc:
                retrieval_fallbacks.append(f"hybrid_retrieval_error:{type(exc).__name__}")
                try:
                    cards = self.memory.trigger.match(current_message, max_cards=max_cards)
                except Exception as nested_exc:
                    cards = []
                    retrieval_fallbacks.append(f"memory_trigger_error:{type(nested_exc).__name__}")
                rules, rule_sources = MemoryTrigger.merge_rule_matches(
                    preferred_rules=keyword_rules,
                    preferred_source="keyword",
                    max_rules=max_rules,
                )
                trace = {
                    "strategy": "keyword",
                    "fallbacks": retrieval_fallbacks,
                    "card_sources": {card.name: "keyword" for card in cards},
                    "rule_sources": rule_sources,
                }

        try:
            knowledge_hits = self.knowledge.search(current_message, limit=3)
        except Exception as exc:
            knowledge_hits = []
            retrieval_fallbacks.append(f"knowledge_search_error:{type(exc).__name__}")
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
            "fallback_count": len({*list(trace.get("fallbacks") or []), *retrieval_fallbacks}),
            "fallbacks": list(dict.fromkeys([*list(trace.get("fallbacks") or []), *retrieval_fallbacks])),
            "card_count": len(cards),
            "rule_count": len(rules),
            "card_hits": [
                {
                    "name": str(card.name or ""),
                    "type": str((((getattr(card, "meta", {}) or {})) if isinstance(getattr(card, "meta", {}) or {}, dict) else {}).get("type", "") or ""),
                    "source": str((trace.get("card_sources") or {}).get(card.name) or ""),
                    "preview": str(card.body or "").strip()[:160],
                }
                for card in cards
            ],
            "rule_hits": [
                {
                    "trigger": str(rule.get("trigger") or ""),
                    "lesson": str(rule.get("lesson") or ""),
                    "action": str(rule.get("action") or ""),
                    "source": str(
                        (trace.get("rule_sources") or {}).get(rule.get("header", ""))
                        or (trace.get("rule_sources") or {}).get(rule.get("trigger", ""))
                        or ""
                    ),
                }
                for rule in rules
            ],
            "knowledge_count": len(knowledge_hits),
            "knowledge_sources": [str(item.get("source") or "") for item in knowledge_hits],
            "knowledge_hits": [
                {
                    "doc_id": str(item.get("doc_id") or ""),
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
        meta["structured"] = self._build_structured_retrieval_objects(
            cards=cards,
            rules=rules,
            knowledge_hits=knowledge_hits,
            session_summary=self._session_summary_snippet(),
        )
        diagnostics = self._build_retrieval_diagnostics_object(meta)
        if diagnostics:
            meta["structured"]["retrieval_objects"].append(diagnostics)
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
