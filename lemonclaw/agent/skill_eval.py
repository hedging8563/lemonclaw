"""Benchmark helpers for deterministic skill trigger and prompt evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any

import yaml

from lemonclaw.agent.context import ContextBuilder
from lemonclaw.agent.skills import BUILTIN_SKILLS_DIR, SkillsLoader


class SkillBenchmarkError(ValueError):
    """Raised when a benchmark file is invalid."""


@dataclass(slots=True)
class SkillBenchmarkCase:
    """One benchmark case for a skill."""

    name: str
    message: str
    mode: str | None = None
    weight: int = 1
    expect_triggered: bool = True
    expected_always_loaded: bool | None = None
    required_skills: list[str] = field(default_factory=list)
    forbidden_skills: list[str] = field(default_factory=list)
    conflict_skills: list[str] = field(default_factory=list)
    prompt_must_contain: list[str] = field(default_factory=list)
    prompt_must_not_contain: list[str] = field(default_factory=list)
    prompt_must_match_regex: list[str] = field(default_factory=list)
    prompt_must_not_match_regex: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SkillBenchmark:
    """A benchmark suite targeting one skill."""

    skill: str
    cases: list[SkillBenchmarkCase]
    mode: str = "chat"
    ignore_requirements: bool = True
    expected_always_loaded: bool | None = None
    conflict_skills: list[str] = field(default_factory=list)
    disabled_skills: list[str] = field(default_factory=list)
    session_prompt_override: str = ""
    path: Path | None = None


@dataclass(slots=True)
class SkillBenchmarkCaseReport:
    """Result for one benchmark case."""

    name: str
    message: str
    passed: bool
    score: int
    max_score: int
    triggered_skills: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "message": self.message,
            "passed": self.passed,
            "score": self.score,
            "max_score": self.max_score,
            "triggered_skills": self.triggered_skills,
            "failures": self.failures,
        }


@dataclass(slots=True)
class SkillBenchmarkReport:
    """Aggregate benchmark report."""

    skill: str
    benchmark_path: str | None
    workspace: str
    builtin_skills_dir: str
    passed: bool
    score: int
    max_score: int
    case_reports: list[SkillBenchmarkCaseReport] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill": self.skill,
            "benchmark_path": self.benchmark_path,
            "workspace": self.workspace,
            "builtin_skills_dir": self.builtin_skills_dir,
            "passed": self.passed,
            "score": self.score,
            "max_score": self.max_score,
            "case_reports": [case.to_dict() for case in self.case_reports],
        }


@dataclass(slots=True)
class SkillBenchmarkSuiteReport:
    """Aggregate report for multiple benchmark files."""

    root: str
    passed: bool
    score: int
    max_score: int
    benchmark_reports: list[SkillBenchmarkReport] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "passed": self.passed,
            "score": self.score,
            "max_score": self.max_score,
            "benchmark_reports": [report.to_dict() for report in self.benchmark_reports],
        }


def _ensure_mapping(data: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise SkillBenchmarkError(f"{label} must be a mapping")
    return data


def _coerce_string(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SkillBenchmarkError(f"{label} must be a non-empty string")
    return value.strip()


def _coerce_string_list(value: Any, *, label: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if not isinstance(value, list):
        raise SkillBenchmarkError(f"{label} must be a string or list of strings")
    items: list[str] = []
    for idx, item in enumerate(value, start=1):
        if not isinstance(item, str) or not item.strip():
            raise SkillBenchmarkError(f"{label}[{idx}] must be a non-empty string")
        items.append(item.strip())
    return items


def _coerce_bool(value: Any, *, label: str, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise SkillBenchmarkError(f"{label} must be a boolean")
    return value


def _coerce_optional_bool(value: Any, *, label: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise SkillBenchmarkError(f"{label} must be a boolean")
    return value


def _coerce_positive_int(value: Any, *, label: str, default: int = 1) -> int:
    if value is None:
        return default
    if not isinstance(value, int) or value < 1:
        raise SkillBenchmarkError(f"{label} must be an integer >= 1")
    return value


def load_skill_benchmark(path: Path) -> SkillBenchmark:
    """Load a skill benchmark from YAML or JSON."""

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    data = _ensure_mapping(raw, label=str(path))

    skill = _coerce_string(data.get("skill"), label="skill")
    mode = str(data.get("mode") or "chat").strip() or "chat"
    ignore_requirements = _coerce_bool(
        data.get("ignore_requirements"),
        label="ignore_requirements",
        default=True,
    )
    expected_always_loaded = _coerce_optional_bool(
        data.get("expected_always_loaded"),
        label="expected_always_loaded",
    )
    conflict_skills = _coerce_string_list(data.get("conflict_skills"), label="conflict_skills")
    disabled_skills = _coerce_string_list(data.get("disabled_skills"), label="disabled_skills")
    session_prompt_override = str(data.get("session_prompt_override") or "")

    raw_cases = data.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise SkillBenchmarkError("cases must be a non-empty list")

    cases: list[SkillBenchmarkCase] = []
    for idx, raw_case in enumerate(raw_cases, start=1):
        case_data = _ensure_mapping(raw_case, label=f"cases[{idx}]")
        case_name = (
            str(case_data.get("name") or case_data.get("id") or f"case-{idx}").strip()
            or f"case-{idx}"
        )
        cases.append(
            SkillBenchmarkCase(
                name=case_name,
                message=_coerce_string(case_data.get("message"), label=f"cases[{idx}].message"),
                mode=(str(case_data.get("mode")).strip() if case_data.get("mode") else None),
                weight=_coerce_positive_int(case_data.get("weight"), label=f"cases[{idx}].weight"),
                expect_triggered=_coerce_bool(
                    case_data.get("expect_triggered"),
                    label=f"cases[{idx}].expect_triggered",
                    default=True,
                ),
                expected_always_loaded=_coerce_optional_bool(
                    case_data.get("expected_always_loaded"),
                    label=f"cases[{idx}].expected_always_loaded",
                ),
                required_skills=_coerce_string_list(
                    case_data.get("required_skills"),
                    label=f"cases[{idx}].required_skills",
                ),
                forbidden_skills=_coerce_string_list(
                    case_data.get("forbidden_skills"),
                    label=f"cases[{idx}].forbidden_skills",
                ),
                conflict_skills=_coerce_string_list(
                    case_data.get("conflict_skills"),
                    label=f"cases[{idx}].conflict_skills",
                ),
                prompt_must_contain=_coerce_string_list(
                    case_data.get("prompt_must_contain"),
                    label=f"cases[{idx}].prompt_must_contain",
                ),
                prompt_must_not_contain=_coerce_string_list(
                    case_data.get("prompt_must_not_contain"),
                    label=f"cases[{idx}].prompt_must_not_contain",
                ),
                prompt_must_match_regex=_coerce_string_list(
                    case_data.get("prompt_must_match_regex"),
                    label=f"cases[{idx}].prompt_must_match_regex",
                ),
                prompt_must_not_match_regex=_coerce_string_list(
                    case_data.get("prompt_must_not_match_regex"),
                    label=f"cases[{idx}].prompt_must_not_match_regex",
                ),
            )
        )

    return SkillBenchmark(
        skill=skill,
        cases=cases,
        mode=mode,
        ignore_requirements=ignore_requirements,
        expected_always_loaded=expected_always_loaded,
        conflict_skills=conflict_skills,
        disabled_skills=disabled_skills,
        session_prompt_override=session_prompt_override,
        path=path,
    )


def collect_skill_benchmark_files(path: Path) -> list[Path]:
    """Collect benchmark files from a file path or directory."""

    if path.is_file():
        return [path]
    if not path.exists():
        raise SkillBenchmarkError(f"{path} does not exist")
    if not path.is_dir():
        raise SkillBenchmarkError(f"{path} must be a file or directory")
    files = sorted(
        child for child in path.iterdir()
        if child.is_file() and child.suffix.lower() in {".yaml", ".yml", ".json"}
    )
    if not files:
        raise SkillBenchmarkError(f"no benchmark files found in {path}")
    return files


def evaluate_skill_benchmark(
    benchmark: SkillBenchmark,
    *,
    workspace: Path,
    builtin_skills_dir: Path | None = None,
) -> SkillBenchmarkReport:
    """Evaluate trigger and prompt assertions for a skill benchmark."""

    resolved_builtin_dir = (builtin_skills_dir or BUILTIN_SKILLS_DIR).resolve()
    builder = ContextBuilder(workspace, disabled_skills=benchmark.disabled_skills)
    builder.skills = SkillsLoader(
        workspace,
        builtin_skills_dir=resolved_builtin_dir,
        disabled_skills=benchmark.disabled_skills,
    )
    original_requirement_checker = builder.skills._check_requirements
    if benchmark.ignore_requirements:
        builder.skills._check_requirements = lambda skill_meta: True

    try:
        available_names = {skill["name"] for skill in builder.skills.list_skills(filter_unavailable=False)}
        if benchmark.skill not in available_names:
            raise SkillBenchmarkError(
                f"skill '{benchmark.skill}' was not found in {resolved_builtin_dir}"
            )
        always_skill_names = set(builder.skills.get_always_skills())

        reports: list[SkillBenchmarkCaseReport] = []
        total_score = 0
        total_max_score = 0
        target_marker = f"### Skill: {benchmark.skill}"

        for case in benchmark.cases:
            trigger_text = case.message
            messages = builder.build_messages(
                [],
                case.message,
                mode=case.mode or benchmark.mode,
                session_prompt_override=benchmark.session_prompt_override,
                memory_context_override="",
                rules_context_override="",
                skip_local_retrieval=True,
            )
            system_prompt = str(messages[0]["content"])
            triggered_skills = list(builder.skills.match_skills(trigger_text))
            synthetic_loaded_skills: list[str] = []
            case_score = 0
            case_max_score = 0
            failures: list[str] = []

            def check(condition: bool, failure: str, *, weight: int = case.weight) -> None:
                nonlocal case_score, case_max_score
                case_max_score += weight
                if condition:
                    case_score += weight
                else:
                    failures.append(failure)

            target_triggered = benchmark.skill in triggered_skills
            expected_loaded = (
                case.expected_always_loaded
                if case.expected_always_loaded is not None
                else (
                    benchmark.expected_always_loaded
                    if benchmark.expected_always_loaded is not None
                    else benchmark.skill in always_skill_names
                )
            )
            synthetic_loaded_skills.extend(skill for skill in always_skill_names if skill in available_names)
            synthetic_loaded_skills.extend(triggered_skills)
            benchmark_prompt = system_prompt
            if synthetic_loaded_skills:
                synthetic_prompt = builder.skills.load_skills_for_context(
                    list(dict.fromkeys(synthetic_loaded_skills))
                )
                if synthetic_prompt:
                    benchmark_prompt = benchmark_prompt + "\n\n# Synthetic Skill Load (benchmark only)\n\n" + synthetic_prompt

            target_loaded = target_marker in benchmark_prompt
            check(
                target_triggered == case.expect_triggered,
                (
                    f"expected target skill '{benchmark.skill}' "
                    f"{'to trigger' if case.expect_triggered else 'not to trigger'}; "
                    f"matched={triggered_skills}"
                ),
            )
            check(
                target_loaded == (case.expect_triggered or expected_loaded),
                (
                    f"expected prompt "
                    f"{'to include' if (case.expect_triggered or expected_loaded) else 'not to include'} "
                    f"the injected section for '{benchmark.skill}'"
                ),
            )

            for skill_name in case.required_skills:
                check(
                    skill_name in triggered_skills,
                    f"expected skill '{skill_name}' to trigger; matched={triggered_skills}",
                )
            for skill_name in case.forbidden_skills:
                check(
                    skill_name not in triggered_skills,
                    f"expected skill '{skill_name}' not to trigger; matched={triggered_skills}",
                )
            combined_conflicts = [*benchmark.conflict_skills, *case.conflict_skills]
            if target_triggered:
                for skill_name in combined_conflicts:
                    check(
                        skill_name not in triggered_skills,
                        f"expected conflict skill '{skill_name}' not to co-trigger; matched={triggered_skills}",
                    )
            for snippet in case.prompt_must_contain:
                check(
                    snippet in benchmark_prompt,
                    f"expected prompt to contain snippet: {snippet!r}",
                )
            for snippet in case.prompt_must_not_contain:
                check(
                    snippet not in benchmark_prompt,
                    f"expected prompt not to contain snippet: {snippet!r}",
                )
            for pattern in case.prompt_must_match_regex:
                try:
                    matched = re.search(pattern, benchmark_prompt, re.MULTILINE) is not None
                except re.error as exc:
                    raise SkillBenchmarkError(f"invalid regex {pattern!r}: {exc}") from exc
                check(
                    matched,
                    f"expected prompt to match regex: {pattern!r}",
                )
            for pattern in case.prompt_must_not_match_regex:
                try:
                    matched = re.search(pattern, benchmark_prompt, re.MULTILINE) is not None
                except re.error as exc:
                    raise SkillBenchmarkError(f"invalid regex {pattern!r}: {exc}") from exc
                check(
                    not matched,
                    f"expected prompt not to match regex: {pattern!r}",
                )

            total_score += case_score
            total_max_score += case_max_score
            reports.append(
                SkillBenchmarkCaseReport(
                    name=case.name,
                    message=case.message,
                    passed=not failures,
                    score=case_score,
                    max_score=case_max_score,
                    triggered_skills=triggered_skills,
                    failures=failures,
                )
            )

        return SkillBenchmarkReport(
            skill=benchmark.skill,
            benchmark_path=str(benchmark.path) if benchmark.path else None,
            workspace=str(workspace.resolve()),
            builtin_skills_dir=str(resolved_builtin_dir),
            passed=all(case.passed for case in reports),
            score=total_score,
            max_score=total_max_score,
            case_reports=reports,
        )
    finally:
        builder.skills._check_requirements = original_requirement_checker


def evaluate_skill_benchmark_suite(
    benchmark_root: Path,
    *,
    workspace: Path,
    builtin_skills_dir: Path | None = None,
) -> SkillBenchmarkSuiteReport:
    """Evaluate all benchmark files under a file or directory path."""

    reports = [
        evaluate_skill_benchmark(
            load_skill_benchmark(benchmark_file),
            workspace=workspace,
            builtin_skills_dir=builtin_skills_dir,
        )
        for benchmark_file in collect_skill_benchmark_files(benchmark_root)
    ]
    return SkillBenchmarkSuiteReport(
        root=str(benchmark_root.resolve()),
        passed=all(report.passed for report in reports),
        score=sum(report.score for report in reports),
        max_score=sum(report.max_score for report in reports),
        benchmark_reports=reports,
    )
