#!/usr/bin/env python3
"""Package a LemonClaw skill folder into a distributable .skill archive."""

from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent


def _load_validate_skill():
    """Load the sibling quick_validate module without depending on cwd/sys.path."""
    module_path = SCRIPT_DIR / "quick_validate.py"
    spec = importlib.util.spec_from_file_location("lc_skill_quick_validate", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load validator module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.validate_skill


validate_skill = _load_validate_skill()


def package_skill(skill_dir: Path, output_dir: Path) -> Path:
    errors = validate_skill(skill_dir)
    if errors:
        raise ValueError("\n".join(errors))

    output_dir.mkdir(parents=True, exist_ok=True)
    temp_root = Path(tempfile.mkdtemp(prefix="lc-skill-"))
    try:
        staging_dir = temp_root / skill_dir.name
        shutil.copytree(skill_dir, staging_dir)
        archive_base = output_dir / skill_dir.name
        archive_path = shutil.make_archive(str(archive_base), "zip", root_dir=temp_root, base_dir=skill_dir.name)
        final_path = output_dir / f"{skill_dir.name}.skill"
        Path(archive_path).replace(final_path)
        return final_path
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def main() -> int:
    if len(sys.argv) not in {2, 3}:
        print("Usage: package_skill.py <path/to/skill-folder> [output-directory]", file=sys.stderr)
        return 1

    skill_dir = Path(sys.argv[1]).expanduser().resolve()
    output_dir = Path(sys.argv[2]).expanduser().resolve() if len(sys.argv) == 3 else skill_dir.parent

    if not skill_dir.exists():
        print(f"Error: skill directory not found: {skill_dir}", file=sys.stderr)
        return 1

    try:
        archive = package_skill(skill_dir, output_dir)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Created package: {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
