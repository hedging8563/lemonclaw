#!/usr/bin/env python3
"""Validate a LemonClaw skill folder."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import yaml

MAX_NAME_LENGTH = 64
ALLOWED_FRONTMATTER_KEYS = {
    "name",
    "description",
    "author",
    "dependencies",
    "homepage",
    "install",
    "metadata",
    "os",
    "tier",
    "tested_on",
    "triggers",
    "version",
    "always",
}
RESOURCE_LINK_RE = re.compile(r"\(([^)`]*(?:scripts|references|assets)/[^)`]+)\)")


def parse_frontmatter(content: str) -> dict[str, Any]:
    match = re.match(r"^---\n(.*?)\n---(?:\n|$)", content, re.DOTALL)
    if not match:
        raise ValueError("missing or malformed YAML frontmatter")

    data = yaml.safe_load(match.group(1)) or {}
    if not isinstance(data, dict):
        raise ValueError("frontmatter must be a YAML mapping")
    return data


def validate_references(skill_dir: Path, content: str) -> list[str]:
    errors = []
    seen: set[str] = set()
    for ref in RESOURCE_LINK_RE.findall(content):
        ref = ref.strip()
        if not ref or "`" in ref or ref in seen or ref.startswith("http"):
            continue
        seen.add(ref)
        if not (skill_dir / ref).exists():
            errors.append(f"referenced path does not exist: {ref}")
    return errors


def validate_skill(skill_dir: Path) -> list[str]:
    errors: list[str] = []
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return ["SKILL.md not found"]

    content = skill_md.read_text(encoding="utf-8")
    try:
        frontmatter = parse_frontmatter(content)
    except Exception as exc:
        return [str(exc)]

    unexpected = sorted(set(frontmatter) - ALLOWED_FRONTMATTER_KEYS)
    if unexpected:
        errors.append(f"unexpected frontmatter keys: {', '.join(unexpected)}")

    name = frontmatter.get("name")
    if not isinstance(name, str) or not name.strip():
        errors.append("frontmatter.name must be a non-empty string")
    else:
        normalized = name.strip()
        if len(normalized) > MAX_NAME_LENGTH:
            errors.append(f"frontmatter.name must be <= {MAX_NAME_LENGTH} characters")
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", normalized):
            errors.append("frontmatter.name must use lowercase letters, digits, and hyphens only")
        if normalized != skill_dir.name:
            errors.append(f"folder name '{skill_dir.name}' does not match frontmatter.name '{normalized}'")

    description = frontmatter.get("description")
    if not isinstance(description, str) or not description.strip():
        errors.append("frontmatter.description must be a non-empty string")

    errors.extend(validate_references(skill_dir, content))
    return errors


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: quick_validate.py <path/to/skill-folder>", file=sys.stderr)
        return 1

    skill_dir = Path(sys.argv[1]).expanduser().resolve()
    if not skill_dir.exists():
        print(f"Error: skill directory not found: {skill_dir}", file=sys.stderr)
        return 1

    errors = validate_skill(skill_dir)
    if errors:
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(f"Skill is valid: {skill_dir.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
