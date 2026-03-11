#!/usr/bin/env python3
"""Create a new LemonClaw skill skeleton."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

VALID_RESOURCES = ("scripts", "references", "assets")
MAX_NAME_LENGTH = 64
SKILL_TEMPLATE = """---
name: {skill_name}
description: "TODO: Describe what this skill does and exactly when it should trigger."
---

# {title}

## Overview

TODO: Explain the skill's purpose in 1-2 sentences.

## Workflow

1. TODO: Describe the first step.
2. TODO: Add the key decision points.
3. TODO: Reference bundled scripts, references, or assets when useful.

## Notes

- TODO: Add important constraints, gotchas, or conventions.
"""

EXAMPLE_SCRIPT = """#!/usr/bin/env python3
\"\"\"Example helper script for {skill_name}.\"\"\"

from __future__ import annotations


def main() -> None:
    print("Replace this example with real automation for {skill_name}.")


if __name__ == "__main__":
    main()
"""

EXAMPLE_REFERENCE = """# Example Reference

Use this file for the detailed information that would otherwise bloat `SKILL.md`.

Suggested contents:
- API or schema notes
- Decision tables
- Troubleshooting playbooks
"""

EXAMPLE_ASSET = """This placeholder marks where templates, images, or boilerplate files belong."""


def normalize_skill_name(raw: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", raw.strip().lower()).strip("-")
    normalized = re.sub(r"-{2,}", "-", normalized)
    return normalized


def validate_skill_name(name: str) -> None:
    if not name:
        raise ValueError("skill name cannot be empty")
    if len(name) > MAX_NAME_LENGTH:
        raise ValueError(f"skill name must be <= {MAX_NAME_LENGTH} characters")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
        raise ValueError("skill name must use lowercase letters, digits, and hyphens only")


def parse_resources(raw: str | None) -> list[str]:
    if not raw:
        return []
    requested = []
    for item in raw.split(","):
        name = item.strip()
        if not name:
            continue
        if name not in VALID_RESOURCES:
            allowed = ", ".join(VALID_RESOURCES)
            raise ValueError(f"unknown resource '{name}', allowed: {allowed}")
        if name not in requested:
            requested.append(name)
    return requested


def create_examples(skill_dir: Path, skill_name: str, resources: list[str], include_examples: bool) -> None:
    if "scripts" in resources:
        scripts_dir = skill_dir / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        if include_examples:
            example = scripts_dir / "example.py"
            example.write_text(EXAMPLE_SCRIPT.format(skill_name=skill_name), encoding="utf-8")

    if "references" in resources:
        references_dir = skill_dir / "references"
        references_dir.mkdir(parents=True, exist_ok=True)
        if include_examples:
            example = references_dir / "guide.md"
            example.write_text(EXAMPLE_REFERENCE, encoding="utf-8")

    if "assets" in resources:
        assets_dir = skill_dir / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        if include_examples:
            example = assets_dir / "README.txt"
            example.write_text(EXAMPLE_ASSET, encoding="utf-8")


def init_skill(skill_name: str, output_path: Path, resources: list[str], include_examples: bool) -> Path:
    skill_dir = output_path / skill_name
    if skill_dir.exists():
        raise FileExistsError(f"destination already exists: {skill_dir}")

    skill_dir.mkdir(parents=True, exist_ok=False)
    title = " ".join(part.capitalize() for part in skill_name.split("-"))
    (skill_dir / "SKILL.md").write_text(
        SKILL_TEMPLATE.format(skill_name=skill_name, title=title),
        encoding="utf-8",
    )
    create_examples(skill_dir, skill_name, resources, include_examples)
    return skill_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize a new LemonClaw skill")
    parser.add_argument("skill_name", help="Skill folder name (lowercase hyphen-case)")
    parser.add_argument("--path", required=True, help="Directory that will contain the new skill")
    parser.add_argument(
        "--resources",
        help="Comma-separated resource directories to create: scripts,references,assets",
    )
    parser.add_argument(
        "--examples",
        action="store_true",
        help="Create placeholder example files inside each requested resource directory",
    )
    args = parser.parse_args()

    try:
        skill_name = normalize_skill_name(args.skill_name)
        validate_skill_name(skill_name)
        resources = parse_resources(args.resources)
        output_dir = Path(args.path).expanduser().resolve()
        skill_dir = init_skill(skill_name, output_dir, resources, args.examples)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Created skill: {skill_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
