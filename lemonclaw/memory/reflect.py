"""Procedural memory — experience learning from task failures."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from lemonclaw.providers.base import LLMProvider

_REFLECT_PROMPT = """\
You are an experience analyst. A task just failed or produced an unexpected result.
Analyze the root cause and generate a structured rule to prevent this from happening again.

Respond with ONLY a JSON object (no markdown fences):
{"trigger": "short keyword/topic that would match future similar tasks",
 "lesson": "what went wrong and why",
 "action": "what to do differently next time",
 "source": "brief description of the failing task"}"""

_RULE_RE = re.compile(r"^## Rule #(\d+)", re.MULTILINE)


class ProceduralMemory:
    """Manages memory/rules.md — structured rules learned from failures."""

    MAX_RULES = 50  # Hard cap to prevent unbounded growth

    def __init__(self, memory_dir: Path):
        self._file = memory_dir / "rules.md"
        self._dir = memory_dir

    def read_rules(self) -> str:
        if self._file.exists():
            return self._file.read_text(encoding="utf-8")
        return ""

    def list_rules(self) -> list[dict[str, str]]:
        """Parse rules.md into a list of rule dicts."""
        text = self.read_rules()
        if not text.strip():
            return []
        rules = []
        # Split by rule headers
        parts = re.split(r"(?=^## Rule #\d+)", text, flags=re.MULTILINE)
        for part in parts:
            part = part.strip()
            if not part.startswith("## Rule"):
                continue
            rule: dict[str, str] = {}
            for line in part.splitlines():
                line = line.strip()
                if line.startswith("## Rule"):
                    rule["header"] = line
                elif line.startswith("- trigger:"):
                    rule["trigger"] = line[len("- trigger:"):].strip()
                elif line.startswith("- lesson:"):
                    rule["lesson"] = line[len("- lesson:"):].strip()
                elif line.startswith("- action:"):
                    rule["action"] = line[len("- action:"):].strip()
                elif line.startswith("- source:"):
                    rule["source"] = line[len("- source:"):].strip()
            if rule.get("trigger"):
                rules.append(rule)
        return rules

    def _next_rule_id(self) -> int:
        text = self.read_rules()
        ids = [int(m.group(1)) for m in _RULE_RE.finditer(text)]
        return max(ids, default=0) + 1

    def add_rule(self, trigger: str, lesson: str, action: str, source: str) -> int:
        """Add a rule manually. Returns the rule number.

        Enforces MAX_RULES cap and deduplicates by trigger similarity.
        """
        rules = self.list_rules()

        # Dedup: skip if a rule with very similar trigger already exists
        trigger_lower = trigger.lower()
        for existing in rules:
            if existing.get("trigger", "").lower() == trigger_lower:
                logger.debug("Procedural memory: duplicate trigger '{}', skipping", trigger[:40])
                return int(existing.get("header", "# 0").split("#")[-1].split("—")[0].strip() or "0")

        # Cap: drop oldest rules if at limit
        if len(rules) >= self.MAX_RULES:
            self._trim_oldest(len(rules) - self.MAX_RULES + 1)

        self._dir.mkdir(parents=True, exist_ok=True)
        rule_id = self._next_rule_id()
        entry = (
            f"\n## Rule #{rule_id} — {date.today()}\n"
            f"- trigger: {trigger}\n"
            f"- lesson: {lesson}\n"
            f"- action: {action}\n"
            f"- source: {source}\n"
        )
        with open(self._file, "a", encoding="utf-8") as f:
            f.write(entry)
        logger.info("Procedural memory: added Rule #{}", rule_id)
        return rule_id

    def _trim_oldest(self, count: int) -> None:
        """Remove the oldest N rules from rules.md."""
        rules_text = self.read_rules()
        if not rules_text.strip():
            return
        parts = re.split(r"(?=^## Rule #\d+)", rules_text, flags=re.MULTILINE)
        # parts[0] may be empty or preamble, rule parts start from index where "## Rule" begins
        preamble_parts = []
        rule_parts = []
        for p in parts:
            if p.strip().startswith("## Rule"):
                rule_parts.append(p)
            else:
                preamble_parts.append(p)
        if count >= len(rule_parts):
            rule_parts = []
        else:
            rule_parts = rule_parts[count:]
        self._file.write_text("".join(preamble_parts) + "".join(rule_parts), encoding="utf-8")
        logger.info("Procedural memory: trimmed {} oldest rules", count)

    def match_rules(self, message: str, *, max_rules: int = 2) -> list[dict[str, str]]:
        """Find rules whose trigger keywords appear in the message."""
        msg_lower = message.lower()
        scored: list[tuple[int, dict[str, str]]] = []
        for rule in self.list_rules():
            trigger = rule.get("trigger", "")
            # Count how many trigger words appear in the message
            words = [w.strip() for w in trigger.lower().split() if len(w.strip()) > 1]
            hits = sum(1 for w in words if w in msg_lower)
            if hits > 0:
                scored.append((hits, rule))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored[:max_rules]]

    @staticmethod
    def format_for_context(rules: list[dict[str, str]]) -> str:
        """Format matched rules as context block for injection."""
        if not rules:
            return ""
        parts = ["## Experience Rules (auto-loaded)"]
        for rule in rules:
            parts.append(
                f"\n**{rule.get('trigger', '?')}**: {rule.get('lesson', '')} "
                f"→ {rule.get('action', '')}"
            )
        return "\n".join(parts)

    async def reflect(
        self,
        provider: LLMProvider,
        task_description: str,
        error: str,
        context: str = "",
        model: str | None = None,
    ) -> int | None:
        """Analyze a failure and generate a rule. Returns rule ID or None on failure."""
        import json
        from lemonclaw.utils.helpers import strip_fences

        user_content = (
            f"Task: {task_description}\n"
            f"Error: {error}\n"
        )
        if context:
            user_content += f"Context: {context}\n"

        try:
            response = await provider.chat(
                messages=[
                    {"role": "system", "content": _REFLECT_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                model=model,
                temperature=0.1,
                max_tokens=256,
            )
            data = json.loads(strip_fences(response.content or ""))
            return self.add_rule(
                trigger=data.get("trigger", task_description[:50]),
                lesson=data.get("lesson", error[:100]),
                action=data.get("action", "Review and fix"),
                source=data.get("source", task_description[:50]),
            )
        except Exception as e:
            logger.warning("Procedural reflect failed: {}", e)
            # Don't write low-quality fallback rules — they pollute memory
            return None
