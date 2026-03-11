"""Skills loader for agent capabilities."""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# Default builtin skills directory (relative to this file)
BUILTIN_SKILLS_DIR = Path(__file__).parent.parent / "skills"
_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---(?:\n|$)", re.DOTALL)


@dataclass
class _SkillCacheEntry:
    mtime_ns: int
    size: int
    content: str
    metadata: dict[str, Any] | None


def _parse_frontmatter(content: str) -> dict[str, Any] | None:
    """Parse YAML frontmatter from a skill file."""
    if not content.startswith("---"):
        return None

    match = _FRONTMATTER_RE.match(content)
    if not match:
        return None

    try:
        data = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return None

    return data if isinstance(data, dict) else None


class SkillsLoader:
    """
    Loader for agent skills.

    Skills are markdown files (SKILL.md) that teach the agent how to use
    specific tools or perform certain tasks.
    """

    def __init__(self, workspace: Path, builtin_skills_dir: Path | None = None, disabled_skills: list[str] | None = None):
        self.workspace = workspace
        self.workspace_skills = workspace / "skills"
        self.builtin_skills = builtin_skills_dir or BUILTIN_SKILLS_DIR
        self._disabled: set[str] = set(disabled_skills or [])
        # TODO: Consider an LRU or size cap if workspace skill counts grow materially.
        self._skill_cache: dict[str, _SkillCacheEntry] = {}

    def list_skills(self, filter_unavailable: bool = True) -> list[dict[str, str]]:
        """
        List all available skills.

        Args:
            filter_unavailable: If True, filter out skills with unmet requirements.

        Returns:
            List of skill info dicts with 'name', 'path', 'source'.
        """
        skills: list[dict[str, str]] = []
        seen: set[str] = set()

        # Workspace skills (highest priority)
        if self.workspace_skills.exists():
            for skill_dir in sorted(self.workspace_skills.iterdir(), key=lambda p: p.name):
                if not skill_dir.is_dir():
                    continue
                skill_file = skill_dir / "SKILL.md"
                if skill_file.exists():
                    skills.append({"name": skill_dir.name, "path": str(skill_file), "source": "workspace"})
                    seen.add(skill_dir.name)

        # Built-in skills
        if self.builtin_skills and self.builtin_skills.exists():
            for skill_dir in sorted(self.builtin_skills.iterdir(), key=lambda p: p.name):
                if not skill_dir.is_dir() or skill_dir.name in seen:
                    continue
                skill_file = skill_dir / "SKILL.md"
                if skill_file.exists():
                    skills.append({"name": skill_dir.name, "path": str(skill_file), "source": "builtin"})

        if filter_unavailable:
            return [s for s in skills if self._check_requirements(self._get_skill_meta(s["name"]))]
        return skills

    def load_skill(self, name: str) -> str | None:
        """
        Load a skill by name.

        Args:
            name: Skill name (directory name).

        Returns:
            Skill content or None if not found.
        """
        entry = self._load_skill_entry(name)
        return entry.content if entry else None

    def load_skills_for_context(self, skill_names: list[str]) -> str:
        """
        Load specific skills for inclusion in agent context.

        Args:
            skill_names: List of skill names to load.

        Returns:
            Formatted skills content.
        """
        parts = []
        for name in skill_names:
            content = self.load_skill(name)
            if content:
                content = self._strip_frontmatter(content)
                parts.append(f"### Skill: {name}\n\n{content}")

        return "\n\n---\n\n".join(parts) if parts else ""

    def build_skills_summary(self) -> str:
        """
        Build a summary of all skills (name, description, path, availability).

        This is used for progressive loading - the agent can read the full
        skill content using read_file when needed.

        Returns:
            XML-formatted skills summary.
        """
        all_skills = self.list_skills(filter_unavailable=False)
        if not all_skills:
            return ""

        def escape_xml(s: str) -> str:
            return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        lines = ["<skills>"]
        for s in all_skills:
            name = escape_xml(s["name"])
            if s["name"] in self._disabled:
                continue
            path = s["path"]
            desc = escape_xml(self._get_skill_description(s["name"]))
            skill_meta = self._get_skill_meta(s["name"])
            available = self._check_requirements(skill_meta)

            lines.append(f"  <skill available=\"{str(available).lower()}\">")
            lines.append(f"    <name>{name}</name>")
            lines.append(f"    <description>{desc}</description>")
            lines.append(f"    <location>{path}</location>")

            if not available:
                missing = self._get_missing_requirements(skill_meta)
                if missing:
                    lines.append(f"    <requires>{escape_xml(missing)}</requires>")

            lines.append("  </skill>")
        lines.append("</skills>")

        return "\n".join(lines)

    def _resolve_skill_file(self, name: str) -> Path | None:
        """Resolve a skill name to its SKILL.md path."""
        workspace_skill = self.workspace_skills / name / "SKILL.md"
        if workspace_skill.exists():
            return workspace_skill

        if self.builtin_skills:
            builtin_skill = self.builtin_skills / name / "SKILL.md"
            if builtin_skill.exists():
                return builtin_skill

        return None

    def _load_skill_entry(self, name: str) -> _SkillCacheEntry | None:
        """Load and cache skill content + parsed frontmatter by file mtime."""
        skill_file = self._resolve_skill_file(name)
        if not skill_file:
            return None

        try:
            stat = skill_file.stat()
        except OSError:
            return None

        cache_key = str(skill_file.resolve())
        cached = self._skill_cache.get(cache_key)
        if cached and cached.mtime_ns == stat.st_mtime_ns and cached.size == stat.st_size:
            return cached

        content = skill_file.read_text(encoding="utf-8")
        entry = _SkillCacheEntry(
            mtime_ns=stat.st_mtime_ns,
            size=stat.st_size,
            content=content,
            metadata=_parse_frontmatter(content),
        )
        self._skill_cache[cache_key] = entry
        return entry

    def _get_missing_requirements(self, skill_meta: dict[str, Any]) -> str:
        """Get a description of missing requirements."""
        missing = []
        requires = skill_meta.get("requires", {})
        for b in requires.get("bins", []):
            if not shutil.which(b):
                missing.append(f"CLI: {b}")
        for env in requires.get("env", []):
            if not os.environ.get(env):
                missing.append(f"ENV: {env}")
        return ", ".join(missing)

    def _get_skill_description(self, name: str) -> str:
        """Get the description of a skill from its frontmatter."""
        meta = self.get_skill_metadata(name)
        if meta and meta.get("description"):
            return str(meta["description"])
        return name

    def _strip_frontmatter(self, content: str) -> str:
        """Remove YAML frontmatter from markdown content."""
        match = _FRONTMATTER_RE.match(content)
        if match:
            return content[match.end():].strip()
        return content

    def _parse_skill_metadata(self, raw: Any) -> dict[str, Any]:
        """Parse skill metadata from either dict or JSON string."""
        if isinstance(raw, dict):
            data = raw
        elif isinstance(raw, str):
            raw = raw.strip()
            if not raw:
                return {}
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                try:
                    data = yaml.safe_load(raw) or {}
                except yaml.YAMLError:
                    return {}
        else:
            return {}

        if not isinstance(data, dict):
            return {}
        if isinstance(data.get("lemonclaw"), dict):
            return data["lemonclaw"]
        if isinstance(data.get("openclaw"), dict):
            return data["openclaw"]
        return data

    def _check_requirements(self, skill_meta: dict[str, Any]) -> bool:
        """Check if skill requirements are met (bins, env vars)."""
        requires = skill_meta.get("requires", {})
        for b in requires.get("bins", []):
            if not shutil.which(b):
                return False
        for env in requires.get("env", []):
            if not os.environ.get(env):
                return False
        return True

    def _get_skill_meta(self, name: str) -> dict[str, Any]:
        """Get normalized skill metadata used by the availability checks."""
        meta = self.get_skill_metadata(name) or {}
        normalized = self._parse_skill_metadata(meta.get("metadata", {}))
        # Runtime-specific metadata.lemonclaw values win over top-level frontmatter.
        for key in ("always", "requires", "os", "install", "tier", "dependencies", "tested_on"):
            if key in meta and key not in normalized:
                normalized[key] = meta[key]
        return normalized

    def match_skills(self, message: str) -> list[str]:
        """Match skills by triggers against user message."""
        msg_lower = message.lower()
        matched: list[str] = []
        always = set(self.get_always_skills())

        _wb_cache: dict[str, re.Pattern[str]] = {}

        def _trigger_matches(trigger: str) -> bool:
            if not trigger.isascii() or not trigger.replace("-", "").replace("_", "").isalpha():
                return trigger in msg_lower
            if trigger not in _wb_cache:
                _wb_cache[trigger] = re.compile(rf"\b{re.escape(trigger)}\b", re.IGNORECASE)
            return _wb_cache[trigger].search(msg_lower) is not None

        for s in self.list_skills(filter_unavailable=True):
            name = s["name"]
            if name in self._disabled or name in always:
                continue
            meta = self.get_skill_metadata(name) or {}
            raw_triggers = meta.get("triggers", "")
            if not raw_triggers:
                continue
            if isinstance(raw_triggers, list):
                triggers = [str(t).strip().lower() for t in raw_triggers if str(t).strip()]
            else:
                triggers = [t.strip().lower() for t in str(raw_triggers).split(",") if t.strip()]
            if any(_trigger_matches(t) for t in triggers):
                matched.append(name)

        return matched

    def get_always_skills(self) -> list[str]:
        """Get skills marked as always=true that meet requirements and are not disabled."""
        result = []
        for s in self.list_skills(filter_unavailable=True):
            if s["name"] in self._disabled:
                continue
            meta = self.get_skill_metadata(s["name"]) or {}
            skill_meta = self._get_skill_meta(s["name"])
            if skill_meta.get("always") or meta.get("always"):
                result.append(s["name"])
        return result

    def get_skill_metadata(self, name: str) -> dict[str, Any] | None:
        """
        Get metadata from a skill's frontmatter.

        Args:
            name: Skill name.

        Returns:
            Metadata dict or None.
        """
        entry = self._load_skill_entry(name)
        return entry.metadata if entry else None
