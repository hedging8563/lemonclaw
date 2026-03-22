import json
from pathlib import Path

from typer.testing import CliRunner

from lemonclaw.agent.skill_eval import (
    evaluate_skill_benchmark,
    evaluate_skill_benchmark_suite,
    load_skill_benchmark,
)
from lemonclaw.cli.commands import app
from lemonclaw.utils.helpers import sync_workspace_templates

runner = CliRunner()
ROOT = Path(__file__).resolve().parent.parent


def _write_skill(
    root,
    name: str,
    *,
    description: str,
    triggers: str,
    body: str,
    always: bool = False,
) -> None:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    always_line = "always: true\n" if always else ""
    (skill_dir / "SKILL.md").write_text(
        f"""---
name: {name}
description: {description}
triggers: "{triggers}"
{always_line}---

# {name}

{body}
""",
        encoding="utf-8",
    )


def test_evaluate_skill_benchmark_checks_trigger_and_prompt(tmp_path) -> None:
    builtin_dir = tmp_path / "builtin-skills"
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    _write_skill(
        builtin_dir,
        "content-writer",
        description="Write human-sounding long-form content.",
        triggers="write article,blog post,写文章",
        body="The core enemy is statistical uniformity.",
    )
    _write_skill(
        builtin_dir,
        "weather",
        description="Weather forecasts and conditions.",
        triggers="weather,forecast",
        body="Use weather data and forecasts.",
    )

    benchmark_path = tmp_path / "content-writer-benchmark.yaml"
    benchmark_path.write_text(
        """skill: content-writer
cases:
  - name: long-form-request
    message: Write a blog post about GPU agents for AI research.
    prompt_must_contain:
      - The core enemy is statistical uniformity.
  - name: unrelated-request
    message: What's the weather in Shanghai today?
    expect_triggered: false
    forbidden_skills:
      - content-writer
    prompt_must_not_contain:
      - "### Skill: content-writer"
""",
        encoding="utf-8",
    )

    bench = load_skill_benchmark(benchmark_path)
    report = evaluate_skill_benchmark(bench, workspace=workspace, builtin_skills_dir=builtin_dir)

    assert report.passed is True
    assert report.score == report.max_score
    assert report.case_reports[0].triggered_skills == ["content-writer"]
    assert report.case_reports[1].triggered_skills == ["weather"]


def test_evaluate_skill_benchmark_reports_failures(tmp_path) -> None:
    builtin_dir = tmp_path / "builtin-skills"
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    _write_skill(
        builtin_dir,
        "content-writer",
        description="Write human-sounding long-form content.",
        triggers="write article,blog post,写文章",
        body="The core enemy is statistical uniformity.",
    )

    benchmark_path = tmp_path / "broken-benchmark.yaml"
    benchmark_path.write_text(
        """skill: content-writer
cases:
  - name: missing-snippet
    message: Write a blog post about GPU agents.
    prompt_must_contain:
      - This snippet does not exist.
""",
        encoding="utf-8",
    )

    bench = load_skill_benchmark(benchmark_path)
    report = evaluate_skill_benchmark(bench, workspace=workspace, builtin_skills_dir=builtin_dir)

    assert report.passed is False
    assert report.case_reports[0].passed is False
    assert "This snippet does not exist." in report.case_reports[0].failures[0]


def test_evaluate_skill_benchmark_supports_weights_regex_and_conflicts(tmp_path) -> None:
    builtin_dir = tmp_path / "builtin-skills"
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    _write_skill(
        builtin_dir,
        "alpha-skill",
        description="Alpha skill.",
        triggers="hello",
        body="Alpha instructions.",
    )
    _write_skill(
        builtin_dir,
        "beta-skill",
        description="Beta skill.",
        triggers="hello",
        body="Beta instructions.",
    )

    benchmark_path = tmp_path / "alpha.yaml"
    benchmark_path.write_text(
        """skill: alpha-skill
conflict_skills:
  - beta-skill
cases:
  - name: weighted-conflict
    message: hello there
    weight: 3
    prompt_must_match_regex:
      - "### Skill: alpha-skill"
""",
        encoding="utf-8",
    )

    bench = load_skill_benchmark(benchmark_path)
    report = evaluate_skill_benchmark(bench, workspace=workspace, builtin_skills_dir=builtin_dir)

    assert report.passed is False
    assert report.case_reports[0].max_score == 12
    assert any("conflict skill 'beta-skill'" in item for item in report.case_reports[0].failures)


def test_evaluate_skill_benchmark_supports_expected_always_loaded(tmp_path) -> None:
    builtin_dir = tmp_path / "builtin-skills"
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    _write_skill(
        builtin_dir,
        "memory-skill",
        description="Always-loaded memory skill.",
        triggers="remember",
        body="Use persistent memory.",
        always=True,
    )

    benchmark_path = tmp_path / "memory.yaml"
    benchmark_path.write_text(
        """skill: memory-skill
expected_always_loaded: true
cases:
  - name: ambient-memory
    message: hello there
    expect_triggered: false
    prompt_must_contain:
      - "### Skill: memory-skill"
""",
        encoding="utf-8",
    )

    bench = load_skill_benchmark(benchmark_path)
    report = evaluate_skill_benchmark(bench, workspace=workspace, builtin_skills_dir=builtin_dir)

    assert report.passed is True
    assert report.case_reports[0].triggered_skills == []


def test_skill_eval_command_outputs_json_report(tmp_path) -> None:
    builtin_dir = tmp_path / "builtin-skills"
    _write_skill(
        builtin_dir,
        "content-writer",
        description="Write human-sounding long-form content.",
        triggers="write article,blog post,写文章",
        body="The core enemy is statistical uniformity.",
    )

    benchmark_path = tmp_path / "content-writer-benchmark.yaml"
    benchmark_path.write_text(
        """skill: content-writer
cases:
  - name: cli-case
    message: Write a blog post about GPU agents.
    prompt_must_contain:
      - The core enemy is statistical uniformity.
""",
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        ["skill-eval", str(benchmark_path), "--builtin-skills-dir", str(builtin_dir), "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["passed"] is True
    assert payload["skill"] == "content-writer"
    assert payload["case_reports"][0]["triggered_skills"] == ["content-writer"]


def test_skill_eval_command_accepts_directory(tmp_path) -> None:
    builtin_dir = tmp_path / "builtin-skills"
    _write_skill(
        builtin_dir,
        "content-writer",
        description="Write human-sounding long-form content.",
        triggers="write article,blog post,写文章",
        body="The core enemy is statistical uniformity.",
    )
    _write_skill(
        builtin_dir,
        "weather",
        description="Weather forecasts and conditions.",
        triggers="weather,forecast",
        body="Use weather data and forecasts.",
    )

    benchmark_dir = tmp_path / "benchmarks"
    benchmark_dir.mkdir()
    (benchmark_dir / "content-writer.yaml").write_text(
        """skill: content-writer
cases:
  - message: Write a blog post about GPU agents.
""",
        encoding="utf-8",
    )
    (benchmark_dir / "weather.yaml").write_text(
        """skill: weather
cases:
  - message: What's the weather in Shanghai today?
""",
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        ["skill-eval", str(benchmark_dir), "--builtin-skills-dir", str(builtin_dir), "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["passed"] is True
    assert len(payload["benchmark_reports"]) == 2


def test_builtin_content_writer_benchmark_passes(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sync_workspace_templates(workspace, silent=True)

    benchmark_path = ROOT / "benchmarks" / "skills" / "content-writer.yaml"
    builtin_dir = ROOT / "lemonclaw" / "skills"

    bench = load_skill_benchmark(benchmark_path)
    report = evaluate_skill_benchmark(bench, workspace=workspace, builtin_skills_dir=builtin_dir)

    assert report.passed is True
    assert report.score == report.max_score


def test_evaluate_skill_benchmark_suite_from_directory(tmp_path) -> None:
    builtin_dir = tmp_path / "builtin-skills"
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    _write_skill(
        builtin_dir,
        "content-writer",
        description="Write human-sounding long-form content.",
        triggers="write article,blog post,写文章",
        body="The core enemy is statistical uniformity.",
    )
    _write_skill(
        builtin_dir,
        "weather",
        description="Weather forecasts and conditions.",
        triggers="weather,forecast",
        body="Use weather data and forecasts.",
    )

    benchmark_dir = tmp_path / "benchmarks"
    benchmark_dir.mkdir()
    (benchmark_dir / "content-writer.yaml").write_text(
        """skill: content-writer
cases:
  - message: Write a blog post about GPU agents.
""",
        encoding="utf-8",
    )
    (benchmark_dir / "weather.yaml").write_text(
        """skill: weather
cases:
  - message: What's the weather in Shanghai today?
""",
        encoding="utf-8",
    )

    report = evaluate_skill_benchmark_suite(
        benchmark_dir,
        workspace=workspace,
        builtin_skills_dir=builtin_dir,
    )

    assert report.passed is True
    assert len(report.benchmark_reports) == 2
    assert report.score == report.max_score


def test_repo_skill_benchmarks_all_pass(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sync_workspace_templates(workspace, silent=True)

    benchmark_dir = ROOT / "benchmarks" / "skills"
    builtin_dir = ROOT / "lemonclaw" / "skills"

    report = evaluate_skill_benchmark_suite(
        benchmark_dir,
        workspace=workspace,
        builtin_skills_dir=builtin_dir,
    )

    assert report.benchmark_reports
    assert report.passed is True
    assert report.score == report.max_score
