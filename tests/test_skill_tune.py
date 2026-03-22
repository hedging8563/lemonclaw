import asyncio
import json
from pathlib import Path

from typer.testing import CliRunner

from lemonclaw.agent.skill_tune import run_skill_tuning_loop
from lemonclaw.cli.commands import app
from lemonclaw.config.schema import Config
from lemonclaw.providers.base import LLMProvider, LLMResponse
from lemonclaw.utils.helpers import sync_workspace_templates

runner = CliRunner()


class StaticProvider(LLMProvider):
    def __init__(self, responses: list[str]):
        super().__init__(api_key="test-key", api_base="http://example.test")
        self._responses = list(responses)

    async def chat(
        self,
        messages,
        tools=None,
        model=None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        on_chunk=None,
    ) -> LLMResponse:
        if not self._responses:
            raise RuntimeError("no stub responses left")
        return LLMResponse(content=self._responses.pop(0))

    def get_default_model(self) -> str:
        return "stub-model"


def _write_skill(skill_path: Path, *, triggers: str) -> str:
    content = f"""---
name: content-writer
description: Write human-sounding long-form content.
triggers: "{triggers}"
---

# Content Writer

Keep prose crisp.
"""
    skill_path.parent.mkdir(parents=True, exist_ok=True)
    skill_path.write_text(content, encoding="utf-8")
    return content


def _write_benchmark(benchmark_path: Path) -> None:
    benchmark_path.write_text(
        """skill: content-writer
cases:
  - name: linkedin-post
    message: Draft a LinkedIn post announcing our v2 launch.
""",
        encoding="utf-8",
    )


def test_run_skill_tuning_loop_keeps_improvement(tmp_path) -> None:
    builtin_dir = tmp_path / "builtin-skills"
    skill_path = builtin_dir / "content-writer" / "SKILL.md"
    _write_skill(skill_path, triggers="write article,blog post")

    benchmark_path = tmp_path / "content-writer.yaml"
    _write_benchmark(benchmark_path)

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sync_workspace_templates(workspace, silent=True)

    improved_text = _write_skill(skill_path.with_name("candidate.SKILL.md"), triggers="write article,blog post,linkedin post")
    provider = StaticProvider([improved_text])

    report = asyncio.run(
        run_skill_tuning_loop(
            skill_path=skill_path,
            benchmark_path=benchmark_path,
            workspace=workspace,
            provider=provider,
            builtin_skills_dir=builtin_dir,
            iterations=1,
        )
    )

    assert report.improved is True
    assert report.best_score > report.baseline_score
    assert report.iterations[0].kept is True
    assert report.stopped_reason == "perfect_score"
    assert "linkedin post" in skill_path.read_text(encoding="utf-8")


def test_run_skill_tuning_loop_discards_non_improving_candidate(tmp_path) -> None:
    builtin_dir = tmp_path / "builtin-skills"
    skill_path = builtin_dir / "content-writer" / "SKILL.md"
    original = _write_skill(skill_path, triggers="write article,blog post")

    benchmark_path = tmp_path / "content-writer.yaml"
    _write_benchmark(benchmark_path)

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sync_workspace_templates(workspace, silent=True)

    worse_text = _write_skill(skill_path.with_name("candidate.SKILL.md"), triggers="write article")
    provider = StaticProvider([worse_text])

    report = asyncio.run(
        run_skill_tuning_loop(
            skill_path=skill_path,
            benchmark_path=benchmark_path,
            workspace=workspace,
            provider=provider,
            builtin_skills_dir=builtin_dir,
            iterations=1,
        )
    )

    assert report.improved is False
    assert report.iterations[0].kept is False
    assert report.stopped_reason == "iteration_limit"
    assert skill_path.read_text(encoding="utf-8") == original


def test_run_skill_tuning_loop_writes_report_and_honors_patience(tmp_path) -> None:
    builtin_dir = tmp_path / "builtin-skills"
    skill_path = builtin_dir / "content-writer" / "SKILL.md"
    original = _write_skill(skill_path, triggers="write article,blog post")

    benchmark_path = tmp_path / "content-writer.yaml"
    _write_benchmark(benchmark_path)

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sync_workspace_templates(workspace, silent=True)

    worse_text = _write_skill(skill_path.with_name("candidate.SKILL.md"), triggers="write article")
    report_path = tmp_path / "report.json"
    provider = StaticProvider([worse_text, worse_text])

    report = asyncio.run(
        run_skill_tuning_loop(
            skill_path=skill_path,
            benchmark_path=benchmark_path,
            workspace=workspace,
            provider=provider,
            builtin_skills_dir=builtin_dir,
            iterations=3,
            patience=1,
            report_out=report_path,
        )
    )

    assert report.stopped_reason == "patience_exhausted"
    assert report_path.exists()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["stopped_reason"] == "patience_exhausted"
    assert skill_path.read_text(encoding="utf-8") == original


def test_skill_tune_command_outputs_json_report(tmp_path, monkeypatch) -> None:
    builtin_dir = tmp_path / "builtin-skills"
    skill_path = builtin_dir / "content-writer" / "SKILL.md"
    _write_skill(skill_path, triggers="write article,blog post")

    benchmark_path = tmp_path / "content-writer.yaml"
    _write_benchmark(benchmark_path)

    improved_text = _write_skill(skill_path.with_name("candidate.SKILL.md"), triggers="write article,blog post,linkedin post")
    monkeypatch.setattr("lemonclaw.cli.commands._make_provider", lambda *args, **kwargs: StaticProvider([improved_text]))
    monkeypatch.setattr("lemonclaw.config.loader.load_config", lambda: Config())

    result = runner.invoke(
        app,
        [
            "skill-tune",
            str(benchmark_path),
            "--builtin-skills-dir",
            str(builtin_dir),
            "--iterations",
            "1",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["improved"] is True
    assert payload["best_score"] > payload["baseline_score"]
    assert payload["stopped_reason"] == "perfect_score"
