from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import yaml
from starlette.testclient import TestClient

from lemonclaw.config.schema import Config
from lemonclaw.config.loader import save_config
from lemonclaw.cron.types import CronJob, CronJobState, CronPayload, CronSchedule
from lemonclaw.gateway.server import create_app
from lemonclaw.ledger.runtime import TaskLedger
from lemonclaw.ledger.task_exports import build_task_bundle
from lemonclaw.providers.base import LLMResponse, ToolCallRequest


def _learning_config(**overrides):
    config = {
        "enabled": True,
        "surfaces": ["chat", "conductor", "cron", "heartbeat"],
        "record_react_trace": True,
        "auto_promote": True,
        "require_replay": True,
        "promotion_scope": "repo",
        "evaluator_model": "gpt-5.4-pro",
        "renderer_model": "",
        "allow_llm_render": True,
        "managed_skill_prefix": "lc-auto--",
        "min_tool_steps_for_extraction": 2,
    }
    config.update(overrides)
    return config


def _rendered_frontmatter(candidate: dict) -> str:
    frontmatter = {
        "name": candidate["skill_name"],
        "description": candidate["description"],
        "triggers": candidate["trigger_examples"],
        "metadata": {
            "lemonclaw": {
                "pattern": "pipeline",
                "managed": True,
                "scope": candidate["scope"],
            }
        },
    }
    return "---\n" + yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).strip() + "\n---\n\n"


async def _wait_for_learning(loop) -> None:
    await asyncio.sleep(0)
    if loop._learning_tasks:
        await asyncio.gather(*list(loop._learning_tasks))


@pytest.mark.asyncio
async def test_process_direct_promotes_managed_skill_and_exports_learning(make_agent_loop, echo_provider, tmp_workspace):
    (tmp_workspace / "notes.txt").write_text("release notes", encoding="utf-8")
    loop, _bus = make_agent_loop(learning_config=_learning_config(allow_llm_render=False))
    echo_provider.responses = [
        LLMResponse(
            content="",
            reasoning_content="private thoughts that must not enter learning trace",
            tool_calls=[
                ToolCallRequest(id="call-1", name="list_dir", arguments={"path": "."}),
                ToolCallRequest(id="call-2", name="read_file", arguments={"path": "notes.txt"}),
            ],
        ),
        LLMResponse(content="Done"),
        LLMResponse(content=json.dumps({
            "accepted": True,
            "score": 0.93,
            "risks": [],
            "reason": "solid managed skill",
            "scope_override": "repo",
        })),
    ]

    result = await loop.process_direct(
        "Review notes and summarize next steps",
        session_key="cli:skill-learning",
        metadata={"_task_id": "task_skill_learning_1"},
    )
    await _wait_for_learning(loop)

    assert result == "Done"
    task = loop.ledger.read_task("task_skill_learning_1")
    learning = dict((task.get("metadata") or {}).get("learning") or {})
    assert learning["status"] == "promoted"
    assert learning["surface"] == "chat"
    assert learning["replay"]["passed"] is True
    assert learning["evaluator"]["accepted"] is True
    assert "private thoughts" not in json.dumps(learning["react_trace"], ensure_ascii=False)
    assert all("thought" not in item for item in learning["react_trace"])
    assert learning["eligibility"]["eligible"] is True
    assert learning["candidate"]["workflow_fingerprint"]

    promoted_skill = dict(learning["promoted_skill"])
    skill_path = Path(promoted_skill["path"])
    sidecar_path = Path(promoted_skill["sidecar_path"])
    assert skill_path.exists()
    assert sidecar_path.exists()
    skill_text = skill_path.read_text(encoding="utf-8")
    assert "pattern: pipeline" in skill_text
    assert "Managed Auto Skill" in skill_text

    skill_names = [item["name"] for item in loop.context.skills.list_skills(filter_unavailable=False)]
    assert skill_path.parent.name in skill_names

    export_view = loop.ledger.build_task_export_view("task_skill_learning_1")
    assert export_view["learning"]["status"] == "promoted"
    bundle = build_task_bundle(loop.ledger, "task_skill_learning_1")
    assert bundle["learning"]["status"] == "promoted"
    postmortem = loop.ledger.build_task_postmortem_view("task_skill_learning_1")
    assert postmortem["learning"]["status"] == "promoted"


@pytest.mark.asyncio
async def test_learning_replaces_managed_skill_only_when_score_improves(make_agent_loop, echo_provider, tmp_workspace):
    (tmp_workspace / "notes.txt").write_text("release notes", encoding="utf-8")
    loop, _bus = make_agent_loop(learning_config=_learning_config(allow_llm_render=False))

    async def _run(task_id: str, evaluator_score: float) -> None:
        echo_provider._call_count = 0
        echo_provider.responses = [
            LLMResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(id="call-1", name="list_dir", arguments={"path": "."}),
                    ToolCallRequest(id="call-2", name="read_file", arguments={"path": "notes.txt"}),
                ],
            ),
            LLMResponse(content="Done"),
            LLMResponse(content=json.dumps({
                "accepted": True,
                "score": evaluator_score,
                "risks": [],
                "reason": "scored",
                "scope_override": "repo",
            })),
        ]
        await loop.process_direct(
            "Review notes and summarize next steps",
            session_key=f"cli:{task_id}",
            metadata={"_task_id": task_id},
        )
        await _wait_for_learning(loop)

    await _run("task_skill_learning_replace_1", 0.40)
    await _run("task_skill_learning_replace_2", 0.95)

    first = loop.ledger.read_task("task_skill_learning_replace_1")
    second = loop.ledger.read_task("task_skill_learning_replace_2")
    first_learning = dict((first.get("metadata") or {}).get("learning") or {})
    second_learning = dict((second.get("metadata") or {}).get("learning") or {})
    skill_dir = Path(second_learning["promoted_skill"]["path"]).parent
    sidecar = json.loads((skill_dir / "skill.asset.json").read_text(encoding="utf-8"))
    assert first_learning["status"] == "promoted"
    assert second_learning["status"] == "promoted"
    assert sidecar["evaluator"]["score"] == 0.95
    assert sidecar["replacement_history"]
    archive_path = Path(sidecar["replacement_history"][-1]["path"])
    assert (archive_path / "SKILL.md").exists()
    assert (archive_path / "skill.asset.json").exists()


@pytest.mark.asyncio
async def test_learning_does_not_replace_existing_skill_when_same_title_maps_to_different_workflow(
    make_agent_loop,
    echo_provider,
    tmp_workspace,
):
    (tmp_workspace / "notes.txt").write_text("release notes", encoding="utf-8")
    loop, _bus = make_agent_loop(learning_config=_learning_config(allow_llm_render=False))

    async def _run(task_id: str, tool_calls: list[ToolCallRequest]) -> dict:
        echo_provider._call_count = 0
        echo_provider.responses = [
            LLMResponse(content="", tool_calls=tool_calls),
            LLMResponse(content="Done"),
            LLMResponse(content=json.dumps({
                "accepted": True,
                "score": 0.91,
                "risks": [],
                "reason": "scored",
                "scope_override": "repo",
            })),
        ]
        await loop.process_direct(
            "Review notes and summarize next steps",
            session_key=f"cli:{task_id}",
            metadata={"_task_id": task_id},
        )
        await _wait_for_learning(loop)
        task = loop.ledger.read_task(task_id)
        return dict((task.get("metadata") or {}).get("learning") or {})

    first_learning = await _run(
        "task_skill_learning_collision_1",
        [
            ToolCallRequest(id="call-1", name="list_dir", arguments={"path": "."}),
            ToolCallRequest(id="call-2", name="read_file", arguments={"path": "notes.txt"}),
        ],
    )
    second_learning = await _run(
        "task_skill_learning_collision_2",
        [
            ToolCallRequest(id="call-1", name="list_dir", arguments={"path": "."}),
            ToolCallRequest(id="call-2", name="glob", arguments={"pattern": "*.txt"}),
        ],
    )

    assert first_learning["status"] == "promoted"
    assert second_learning["status"] == "discarded"
    assert first_learning["candidate"]["workflow_fingerprint"] != second_learning["candidate"]["workflow_fingerprint"]
    assert second_learning["reason"] == "replay_failed"
    assert Path(first_learning["promoted_skill"]["path"]).exists()
    assert "promoted_skill" not in second_learning


@pytest.mark.asyncio
async def test_learning_replay_rejects_existing_skill_trigger_conflict(make_agent_loop, echo_provider, tmp_workspace):
    (tmp_workspace / "notes.txt").write_text("release notes", encoding="utf-8")
    existing_skill = tmp_workspace / "skills" / "manual-review"
    existing_skill.mkdir(parents=True, exist_ok=True)
    (existing_skill / "SKILL.md").write_text(
        """---
name: manual-review
description: Existing skill with overlapping trigger
triggers:
  - Review notes and summarize next steps
metadata:
  lemonclaw:
    pattern: pipeline
---

# Manual Review
""",
        encoding="utf-8",
    )
    loop, _bus = make_agent_loop(learning_config=_learning_config(allow_llm_render=False))
    echo_provider.responses = [
        LLMResponse(
            content="",
            tool_calls=[
                ToolCallRequest(id="call-1", name="list_dir", arguments={"path": "."}),
                ToolCallRequest(id="call-2", name="read_file", arguments={"path": "notes.txt"}),
            ],
        ),
        LLMResponse(content="Done"),
    ]

    result = await loop.process_direct(
        "Review notes and summarize next steps",
        session_key="cli:skill-learning-conflict",
        metadata={"_task_id": "task_skill_learning_conflict"},
    )
    await _wait_for_learning(loop)

    assert result == "Done"
    task = loop.ledger.read_task("task_skill_learning_conflict")
    learning = dict((task.get("metadata") or {}).get("learning") or {})
    assert learning["status"] == "discarded"
    assert learning["reason"] == "replay_failed"
    assert learning["replay"]["passed"] is False
    assert "promoted_skill" not in learning


@pytest.mark.asyncio
async def test_process_direct_returns_before_background_learning_finishes(make_agent_loop, echo_provider):
    loop, _bus = make_agent_loop(learning_config=_learning_config())
    started = asyncio.Event()
    release = asyncio.Event()

    async def _slow_learning(*args, **kwargs):
        started.set()
        await release.wait()
        return {"status": "promoted"}

    loop.learning.maybe_promote_for_task = _slow_learning
    echo_provider.responses = [LLMResponse(content="Done")]

    result = await asyncio.wait_for(
        loop.process_direct(
            "Say hello",
            session_key="cli:skill-learning-background",
            metadata={"_task_id": "task_skill_learning_background"},
        ),
        timeout=0.5,
    )

    assert result == "Done"
    await asyncio.wait_for(started.wait(), timeout=0.5)
    assert loop._learning_tasks
    release.set()
    await _wait_for_learning(loop)


@pytest.mark.asyncio
async def test_learning_uses_llm_renderer_when_validation_passes(make_agent_loop, echo_provider, tmp_workspace):
    (tmp_workspace / "notes.txt").write_text("release notes", encoding="utf-8")
    loop, _bus = make_agent_loop(learning_config=_learning_config())

    async def _render(candidate, *, bundle):
        return (
            _rendered_frontmatter(candidate)
            + f"# Refined Managed Skill: {candidate['title']}\n\n"
            + "Use this polished managed skill when the request matches the intent below.\n\n"
            + "## Trigger Examples\n"
            + "".join(f"- {item}\n" for item in candidate["trigger_examples"])
            + "\n## Required Inputs\n"
            + "".join(f"- {item}\n" for item in candidate["required_inputs"])
            + "\n## Pipeline\n"
            + f"- `{candidate['tool_names'][0]}`: inspect the workspace before acting.\n"
            + f"- `{candidate['tool_names'][1]}`: read the source material and summarize the findings.\n"
            + "\n## Verification\n"
            + "".join(f"- {item}\n" for item in candidate["verification_steps"])
            + "\n## Failure Signals\n"
            + "".join(f"- {item}\n" for item in candidate["failure_signals"])
        )

    loop.learning._render_skill_markdown_llm = _render
    echo_provider.responses = [
        LLMResponse(
            content="",
            tool_calls=[
                ToolCallRequest(id="call-1", name="list_dir", arguments={"path": "."}),
                ToolCallRequest(id="call-2", name="read_file", arguments={"path": "notes.txt"}),
            ],
        ),
        LLMResponse(content="Done"),
        LLMResponse(content=json.dumps({
            "accepted": True,
            "score": 0.91,
            "risks": [],
            "reason": "renderer output is acceptable",
            "scope_override": "repo",
        })),
    ]

    await loop.process_direct(
        "Review notes and summarize next steps",
        session_key="cli:renderer-pass",
        metadata={"_task_id": "task_skill_learning_renderer_pass"},
    )
    await _wait_for_learning(loop)

    task = loop.ledger.read_task("task_skill_learning_renderer_pass")
    learning = dict((task.get("metadata") or {}).get("learning") or {})
    assert learning["renderer"]["strategy"] == "llm"
    assert learning["render_validation"]["passed"] is True
    assert "Refined Managed Skill" in learning["rendered_skill_markdown"]
    promoted_path = Path(learning["promoted_skill"]["path"])
    assert "Refined Managed Skill" in promoted_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_learning_falls_back_to_template_when_renderer_introduces_new_tool(make_agent_loop, echo_provider, tmp_workspace):
    (tmp_workspace / "notes.txt").write_text("release notes", encoding="utf-8")
    loop, _bus = make_agent_loop(learning_config=_learning_config())

    async def _bad_render(candidate, *, bundle):
        return (
            _rendered_frontmatter(candidate)
            + f"# Refined Managed Skill: {candidate['title']}\n\n"
            + "## Trigger Examples\n"
            + "".join(f"- {item}\n" for item in candidate["trigger_examples"])
            + "\n## Required Inputs\n"
            + "".join(f"- {item}\n" for item in candidate["required_inputs"])
            + "\n## Pipeline\n"
            + f"- `{candidate['tool_names'][0]}`: inspect the workspace before acting.\n"
            + "- `write_file`: create a new report automatically.\n"
            + "\n## Verification\n"
            + "".join(f"- {item}\n" for item in candidate["verification_steps"])
            + "\n## Failure Signals\n"
            + "".join(f"- {item}\n" for item in candidate["failure_signals"])
        )

    loop.learning._render_skill_markdown_llm = _bad_render
    echo_provider.responses = [
        LLMResponse(
            content="",
            tool_calls=[
                ToolCallRequest(id="call-1", name="list_dir", arguments={"path": "."}),
                ToolCallRequest(id="call-2", name="read_file", arguments={"path": "notes.txt"}),
            ],
        ),
        LLMResponse(content="Done"),
        LLMResponse(content=json.dumps({
            "accepted": True,
            "score": 0.89,
            "risks": [],
            "reason": "template fallback is acceptable",
            "scope_override": "repo",
        })),
    ]

    await loop.process_direct(
        "Review notes and summarize next steps",
        session_key="cli:renderer-fallback",
        metadata={"_task_id": "task_skill_learning_renderer_fallback"},
    )
    await _wait_for_learning(loop)

    task = loop.ledger.read_task("task_skill_learning_renderer_fallback")
    learning = dict((task.get("metadata") or {}).get("learning") or {})
    assert learning["renderer"]["strategy"] == "template_fallback"
    assert learning["render_validation"]["passed"] is False
    assert any("unexpected_tools" in failure for failure in learning["render_validation"]["failures"])
    promoted_path = Path(learning["promoted_skill"]["path"])
    promoted_text = promoted_path.read_text(encoding="utf-8")
    assert "Managed Auto Skill" in promoted_text
    assert "`write_file`" not in promoted_text


@pytest.mark.asyncio
async def test_learning_uses_template_when_renderer_unavailable(make_agent_loop, echo_provider, tmp_workspace):
    (tmp_workspace / "notes.txt").write_text("release notes", encoding="utf-8")
    loop, _bus = make_agent_loop(learning_config=_learning_config())
    loop.learning.renderer_model = "renderer-model"
    original_resolver = loop.learning._provider_resolver
    loop.learning._provider_resolver = lambda model=None: None if model == "renderer-model" else original_resolver(model)
    echo_provider.responses = [
        LLMResponse(
            content="",
            tool_calls=[
                ToolCallRequest(id="call-1", name="list_dir", arguments={"path": "."}),
                ToolCallRequest(id="call-2", name="read_file", arguments={"path": "notes.txt"}),
            ],
        ),
        LLMResponse(content="Done"),
        LLMResponse(content=json.dumps({
            "accepted": True,
            "score": 0.84,
            "risks": [],
            "reason": "template fallback is acceptable",
            "scope_override": "repo",
        })),
    ]

    await loop.process_direct(
        "Review notes and summarize next steps",
        session_key="cli:renderer-unavailable",
        metadata={"_task_id": "task_skill_learning_renderer_unavailable"},
    )
    await _wait_for_learning(loop)

    task = loop.ledger.read_task("task_skill_learning_renderer_unavailable")
    learning = dict((task.get("metadata") or {}).get("learning") or {})
    assert learning["renderer"]["strategy"] == "template_fallback"
    assert learning["renderer"]["reason"] == "renderer_unavailable"
    assert learning["status"] == "promoted"
    assert learning["evaluator"]["accepted"] is True


@pytest.mark.asyncio
async def test_cron_service_runs_learning_after_finalize(tmp_path):
    from lemonclaw.cron.service import CronService

    ledger = TaskLedger(tmp_path)
    learning = SimpleNamespace(maybe_promote_for_task=AsyncMock())
    service = CronService(
        tmp_path / "cron-jobs.json",
        on_job=AsyncMock(return_value="done"),
        task_ledger=ledger,
        learning_service=learning,
    )
    job = CronJob(
        id="job-1",
        name="Daily skill learning",
        schedule=CronSchedule(kind="every", every_ms=60_000),
        payload=CronPayload(message="Run the daily workspace audit", kind="agent_turn"),
        state=CronJobState(next_run_at_ms=1),
    )

    await service._execute_job(job)

    learning.maybe_promote_for_task.assert_awaited_once()
    task = next(item for item in ledger.list_tasks(limit=10) if str(item.get("task_id") or "").startswith("task_cron_"))
    assert task["status"] == "completed"


def test_apply_settings_propagates_learning_config(tmp_path):
    config_path = tmp_path / "config.json"
    cfg = Config()
    cfg.agents.learning.enabled = True
    cfg.agents.learning.evaluator_model = "gpt-5.4-pro"
    save_config(cfg, config_path)

    class FakeAgentLoop:
        def __init__(self) -> None:
            self.refresh_calls = []
            self.defaults_calls = []

        async def refresh_runtime_config(self, config, *, changed_paths):
            self.refresh_calls.append(list(changed_paths))
            return {}

        def update_defaults(self, **kwargs):
            self.defaults_calls.append(kwargs)

    fake_loop = FakeAgentLoop()
    app = create_app(config_path=config_path, auth_token=None, agent_loop=fake_loop)
    client = TestClient(app)

    resp = client.post("/api/settings/apply", json={"changed_paths": ["agents.learning.enabled"]})

    assert resp.status_code == 200
    assert fake_loop.defaults_calls
    assert fake_loop.defaults_calls[-1]["learning_config"]["enabled"] is True
    assert fake_loop.defaults_calls[-1]["learning_config"]["evaluatorModel"] == "gpt-5.4-pro"


def test_apply_settings_propagates_learning_renderer_fields(tmp_path):
    config_path = tmp_path / "config.json"
    cfg = Config()
    cfg.agents.learning.renderer_model = "gpt-5.4-mini"
    cfg.agents.learning.allow_llm_render = False
    save_config(cfg, config_path)

    class FakeAgentLoop:
        def __init__(self) -> None:
            self.defaults_calls = []

        async def refresh_runtime_config(self, config, *, changed_paths):
            return {}

        def update_defaults(self, **kwargs):
            self.defaults_calls.append(kwargs)

    fake_loop = FakeAgentLoop()
    app = create_app(config_path=config_path, auth_token=None, agent_loop=fake_loop)
    client = TestClient(app)

    resp = client.post("/api/settings/apply", json={"changed_paths": ["agents.learning.renderer_model"]})

    assert resp.status_code == 200
    assert fake_loop.defaults_calls[-1]["learning_config"]["rendererModel"] == "gpt-5.4-mini"
    assert fake_loop.defaults_calls[-1]["learning_config"]["allowLlmRender"] is False
