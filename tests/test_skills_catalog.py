from __future__ import annotations

import re
import runpy
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


def test_package_skill_is_importable_without_cwd_dependency() -> None:
    script_path = SKILLS_DIR / "skill-creator" / "scripts" / "package_skill.py"
    module_globals = runpy.run_path(str(script_path), run_name="package_skill_test")
    assert callable(module_globals["package_skill"])


def test_quick_validate_accepts_os_and_install_frontmatter(tmp_path) -> None:
    script_path = SKILLS_DIR / "skill-creator" / "scripts" / "quick_validate.py"
    module_globals = runpy.run_path(str(script_path), run_name="quick_validate_test")
    validate_skill = module_globals["validate_skill"]

    skill_dir = tmp_path / "validated-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        """---
name: validated-skill
description: Validation smoke test.
os:
  - linux
install:
  - apt install demo
---

# Validated Skill
""",
        encoding="utf-8",
    )

    assert validate_skill(skill_dir) == []


def test_skills_loader_promotes_os_and_install_frontmatter(tmp_path) -> None:
    builtin_dir = tmp_path / "builtin"
    workspace = tmp_path / "workspace"
    skill_dir = builtin_dir / "tooling-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: tooling-skill
description: Tooling skill.
os:
  - darwin
install:
  - brew install demo
---

# Tooling Skill
""",
        encoding="utf-8",
    )

    loader = SkillsLoader(workspace=workspace, builtin_skills_dir=builtin_dir)
    skill_meta = loader._get_skill_meta("tooling-skill")
    assert skill_meta["os"] == ["darwin"]
    assert skill_meta["install"] == ["brew install demo"]
