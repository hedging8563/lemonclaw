from __future__ import annotations

import re
from pathlib import Path

from lemonclaw.agent.skills import SkillsLoader

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "lemonclaw" / "skills"
README_PATH = SKILLS_DIR / "README.md"
README_ROW_RE = re.compile(r"^\| `([^`]+)` \|")
RESOURCE_LINK_RE = re.compile(r"\(([^)`]*(?:scripts|references|assets)/[^)`]+)\)")


def _builtin_skill_names() -> list[str]:
    return sorted(path.name for path in SKILLS_DIR.iterdir() if path.is_dir())


def _readme_skill_names() -> list[str]:
    names = []
    for line in README_PATH.read_text(encoding="utf-8").splitlines():
        match = README_ROW_RE.match(line.strip())
        if match:
            names.append(match.group(1))
    return sorted(names)


def test_skills_readme_matches_builtin_directories() -> None:
    assert _readme_skill_names() == _builtin_skill_names()


def test_skill_creator_support_files_exist() -> None:
    skill_creator_dir = SKILLS_DIR / "skill-creator"
    required_paths = [
        "scripts/init_skill.py",
        "scripts/quick_validate.py",
        "scripts/package_skill.py",
        "references/workflows.md",
        "references/output-patterns.md",
    ]
    for rel in required_paths:
        assert (skill_creator_dir / rel).exists(), rel


def test_markdown_resource_links_point_to_real_files() -> None:
    for skill_dir in sorted(path for path in SKILLS_DIR.iterdir() if path.is_dir()):
        content = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        for ref in RESOURCE_LINK_RE.findall(content):
            if "`" in ref:
                continue
            assert (skill_dir / ref).exists(), f"{skill_dir.name}: missing {ref}"


def test_skills_loader_parses_nested_metadata_and_always_flags(tmp_path, monkeypatch) -> None:
    builtin_dir = tmp_path / "builtin"
    workspace = tmp_path / "workspace"
    skill_dir = builtin_dir / "demo-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: demo-skill
description: Demo skill for loader tests.
always: true
metadata:
  lemonclaw:
    requires:
      env:
        - DEMO_KEY
triggers: "demo"
---

# Demo Skill
""",
        encoding="utf-8",
    )

    loader = SkillsLoader(workspace=workspace, builtin_skills_dir=builtin_dir)
    assert loader.list_skills(filter_unavailable=True) == []

    monkeypatch.setenv("DEMO_KEY", "test-key")
    assert [skill["name"] for skill in loader.list_skills(filter_unavailable=True)] == ["demo-skill"]
    assert loader.get_always_skills() == ["demo-skill"]
    assert loader._get_skill_meta("demo-skill")["requires"]["env"] == ["DEMO_KEY"]


def test_yt_dlp_declares_runtime_requirements(tmp_path) -> None:
    loader = SkillsLoader(workspace=tmp_path, builtin_skills_dir=SKILLS_DIR)
    skill_meta = loader._get_skill_meta("yt-dlp")
    assert skill_meta["requires"]["bins"] == ["yt-dlp", "ffmpeg"]
