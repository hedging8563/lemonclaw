"""Benchmark-driven keep/discard tuning loop for SKILL.md files."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lemonclaw.agent.skill_eval import (
    SkillBenchmarkReport,
    evaluate_skill_benchmark,
    load_skill_benchmark,
)
from lemonclaw.agent.skills import _parse_frontmatter
from lemonclaw.providers.base import LLMProvider
from lemonclaw.utils.helpers import strip_fences


class SkillTuneError(ValueError):
    """Raised when skill tuning cannot proceed."""


@dataclass(slots=True)
class SkillTuneIteration:
    """One candidate-tuning iteration."""

    iteration: int
    candidate_score: int
    candidate_max_score: int
    kept: bool
    reason: str
    report: SkillBenchmarkReport

    def to_dict(self) -> dict[str, Any]:
        return {
            "iteration": self.iteration,
            "candidate_score": self.candidate_score,
            "candidate_max_score": self.candidate_max_score,
            "kept": self.kept,
            "reason": self.reason,
            "report": self.report.to_dict(),
        }


@dataclass(slots=True)
class SkillTuneReport:
    """Overall tuning result."""

    skill: str
    skill_path: str
    benchmark_path: str
    baseline_score: int
    baseline_max_score: int
    best_score: int
    best_max_score: int
    improved: bool
    iterations: list[SkillTuneIteration] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill": self.skill,
            "skill_path": self.skill_path,
            "benchmark_path": self.benchmark_path,
            "baseline_score": self.baseline_score,
            "baseline_max_score": self.baseline_max_score,
            "best_score": self.best_score,
            "best_max_score": self.best_max_score,
            "improved": self.improved,
            "iterations": [item.to_dict() for item in self.iterations],
        }


def _summarize_failures(report: SkillBenchmarkReport) -> str:
    lines: list[str] = []
    for case in report.case_reports:
        if case.passed:
            continue
        lines.append(f"- {case.name}: matched={case.triggered_skills or []}")
        for failure in case.failures:
            lines.append(f"  - {failure}")
    return "\n".join(lines) if lines else "- none"


def _build_messages(
    *,
    skill_name: str,
    current_text: str,
    benchmark_text: str,
    report: SkillBenchmarkReport,
) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You improve a LemonClaw SKILL.md file to maximize a deterministic benchmark score.\n"
                "Return ONLY the full updated SKILL.md content.\n"
                "Preserve valid YAML frontmatter.\n"
                "Prefer the smallest useful change.\n"
                "Fix description/triggers first; only change the body when benchmark prompt checks require it.\n"
                "Do not add README files, comments about the benchmark, or any extra files."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Target skill: {skill_name}\n"
                f"Current score: {report.score}/{report.max_score}\n\n"
                "Current failed cases:\n"
                f"{_summarize_failures(report)}\n\n"
                "Benchmark file:\n"
                f"{benchmark_text}\n\n"
                "Current SKILL.md:\n"
                f"{current_text}"
            ),
        },
    ]


def _validate_candidate(skill_name: str, candidate_text: str) -> None:
    meta = _parse_frontmatter(candidate_text)
    if not meta:
        raise SkillTuneError("candidate is missing valid YAML frontmatter")
    candidate_name = str(meta.get("name") or "").strip()
    if candidate_name != skill_name:
        raise SkillTuneError(
            f"candidate frontmatter name mismatch: expected {skill_name!r}, got {candidate_name!r}"
        )


async def run_skill_tuning_loop(
    *,
    skill_path: Path,
    benchmark_path: Path,
    workspace: Path,
    provider: LLMProvider,
    builtin_skills_dir: Path,
    iterations: int = 3,
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 8192,
) -> SkillTuneReport:
    """Iteratively edit a skill file and keep only score-improving candidates."""

    if iterations < 1:
        raise SkillTuneError("iterations must be >= 1")
    if not skill_path.exists():
        raise SkillTuneError(f"skill file not found: {skill_path}")
    if not benchmark_path.exists():
        raise SkillTuneError(f"benchmark file not found: {benchmark_path}")

    benchmark = load_skill_benchmark(benchmark_path)
    original_text = skill_path.read_text(encoding="utf-8")
    _validate_candidate(benchmark.skill, original_text)

    baseline = evaluate_skill_benchmark(
        benchmark,
        workspace=workspace,
        builtin_skills_dir=builtin_skills_dir,
    )
    best_text = original_text
    best_report = baseline
    history: list[SkillTuneIteration] = []

    if baseline.score >= baseline.max_score:
        return SkillTuneReport(
            skill=benchmark.skill,
            skill_path=str(skill_path),
            benchmark_path=str(benchmark_path),
            baseline_score=baseline.score,
            baseline_max_score=baseline.max_score,
            best_score=baseline.score,
            best_max_score=baseline.max_score,
            improved=False,
            iterations=history,
        )

    benchmark_text = benchmark_path.read_text(encoding="utf-8")

    try:
        for idx in range(1, iterations + 1):
            messages = _build_messages(
                skill_name=benchmark.skill,
                current_text=best_text,
                benchmark_text=benchmark_text,
                report=best_report,
            )
            response = await provider.chat(
                messages,
                tools=None,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            candidate_text = strip_fences(response.content or "")
            if not candidate_text:
                raise SkillTuneError("model returned empty candidate content")
            _validate_candidate(benchmark.skill, candidate_text)

            skill_path.write_text(candidate_text, encoding="utf-8")
            candidate_report = evaluate_skill_benchmark(
                benchmark,
                workspace=workspace,
                builtin_skills_dir=builtin_skills_dir,
            )

            if candidate_report.score > best_report.score:
                best_text = candidate_text
                best_report = candidate_report
                history.append(
                    SkillTuneIteration(
                        iteration=idx,
                        candidate_score=candidate_report.score,
                        candidate_max_score=candidate_report.max_score,
                        kept=True,
                        reason="score improved",
                        report=candidate_report,
                    )
                )
                if best_report.score >= best_report.max_score:
                    break
            else:
                skill_path.write_text(best_text, encoding="utf-8")
                history.append(
                    SkillTuneIteration(
                        iteration=idx,
                        candidate_score=candidate_report.score,
                        candidate_max_score=candidate_report.max_score,
                        kept=False,
                        reason="score did not improve",
                        report=candidate_report,
                    )
                )

        skill_path.write_text(best_text, encoding="utf-8")
    except Exception:
        skill_path.write_text(best_text, encoding="utf-8")
        raise

    return SkillTuneReport(
        skill=benchmark.skill,
        skill_path=str(skill_path),
        benchmark_path=str(benchmark_path),
        baseline_score=baseline.score,
        baseline_max_score=baseline.max_score,
        best_score=best_report.score,
        best_max_score=best_report.max_score,
        improved=best_report.score > baseline.score,
        iterations=history,
    )
