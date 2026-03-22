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

BENCHMARK_TEMPLATE = """skill: {skill_name}
cases:
  - name: positive-primary
    message: "TODO: Add a request that should trigger {skill_name}."
  - name: negative-primary
    message: "TODO: Add a request that should NOT trigger {skill_name}."
    expect_triggered: false

# Optional advanced fields when the simple cases are not enough:
# expected_always_loaded: true
# conflict_skills:
#   - other-skill
# cases:
#   - name: weighted-case
#     weight: 2
#     prompt_must_contain:
#       - "Expected prompt text"
#     prompt_must_match_regex:
#       - "^### Skill:"
"""


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


def infer_benchmark_dir(output_path: Path) -> Path | None:
    current = output_path
    while True:
        if current.name == "skills":
            return current.parent / "benchmarks" / "skills"
        if current.parent == current:
            return None
        current = current.parent


def create_benchmark_template(skill_name: str, benchmark_dir: Path) -> Path:
    benchmark_dir.mkdir(parents=True, exist_ok=True)
    benchmark_path = benchmark_dir / f"{skill_name}.yaml"
    if benchmark_path.exists():
        raise FileExistsError(f"benchmark already exists: {benchmark_path}")
    benchmark_path.write_text(BENCHMARK_TEMPLATE.format(skill_name=skill_name), encoding="utf-8")
    return benchmark_path


def init_skill(
    skill_name: str,
    output_path: Path,
    resources: list[str],
    include_examples: bool,
    benchmark_dir: Path | None = None,
    create_benchmark: bool = True,
) -> tuple[Path, Path | None]:
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
    benchmark_path = None
    if create_benchmark:
        resolved_benchmark_dir = benchmark_dir or infer_benchmark_dir(output_path)
        if resolved_benchmark_dir is not None:
            benchmark_path = create_benchmark_template(skill_name, resolved_benchmark_dir)
    return skill_dir, benchmark_path


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
    parser.add_argument(
        "--benchmark-dir",
        help="Optional directory for benchmark YAML templates. Defaults to a sibling benchmarks/skills when inferred.",
    )
    parser.add_argument(
        "--no-benchmark",
        action="store_true",
        help="Skip creating benchmarks/skills/<skill>.yaml",
    )
    args = parser.parse_args()

    try:
        skill_name = normalize_skill_name(args.skill_name)
        validate_skill_name(skill_name)
        resources = parse_resources(args.resources)
        output_dir = Path(args.path).expanduser().resolve()
        benchmark_dir = (
            Path(args.benchmark_dir).expanduser().resolve()
            if args.benchmark_dir
            else None
        )
        skill_dir, benchmark_path = init_skill(
            skill_name,
            output_dir,
            resources,
            args.examples,
            benchmark_dir=benchmark_dir,
            create_benchmark=not args.no_benchmark,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Created skill: {skill_dir}")
    if benchmark_path is not None:
        print(f"Created benchmark: {benchmark_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
