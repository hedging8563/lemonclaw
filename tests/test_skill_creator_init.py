import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = ROOT / "lemonclaw" / "skills" / "skill-creator" / "scripts" / "init_skill.py"


def test_init_skill_creates_benchmark_template_when_inferred(tmp_path) -> None:
    module_globals = runpy.run_path(str(SCRIPT_PATH), run_name="init_skill_test")
    init_skill = module_globals["init_skill"]

    output_dir = tmp_path / "repo" / "skills"
    skill_dir, benchmark_path = init_skill(
        "demo-skill",
        output_dir,
        resources=[],
        include_examples=False,
    )

    assert skill_dir == output_dir / "demo-skill"
    assert (skill_dir / "SKILL.md").exists()
    skill_text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    assert "pattern: tool-wrapper" in skill_text
    assert "## Runtime Boundary" in skill_text
    assert benchmark_path == tmp_path / "repo" / "benchmarks" / "skills" / "demo-skill.yaml"
    assert benchmark_path.exists()
    content = benchmark_path.read_text(encoding="utf-8")
    assert "skill: demo-skill" in content
    assert "expect_triggered: false" in content
    assert "# Optional advanced fields" in content
    assert "# expected_always_loaded: true" in content
    assert "#     prompt_must_match_regex:" in content


def test_init_skill_allows_benchmark_opt_out(tmp_path) -> None:
    module_globals = runpy.run_path(str(SCRIPT_PATH), run_name="init_skill_test")
    init_skill = module_globals["init_skill"]

    output_dir = tmp_path / "repo" / "skills"
    skill_dir, benchmark_path = init_skill(
        "demo-skill",
        output_dir,
        resources=[],
        include_examples=False,
        create_benchmark=False,
    )

    assert skill_dir.exists()
    assert benchmark_path is None
    assert not (tmp_path / "repo" / "benchmarks" / "skills" / "demo-skill.yaml").exists()
