from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
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
        "managed_skill_prefix": "lc-auto--",
        "min_tool_steps_for_extraction": 2,
    }
    config.update(overrides)
    return config


@pytest.mark.asyncio
async def test_process_direct_promotes_managed_skill_and_exports_learning(make_agent_loop, echo_provider, tmp_workspace):
    (tmp_workspace / "notes.txt").write_text("release notes", encoding="utf-8")
    loop, _bus = make_agent_loop(learning_config=_learning_config())
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
    loop, _bus = make_agent_loop(learning_config=_learning_config())

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
