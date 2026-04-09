import pytest

from lemonclaw.agent.tools.cron import CronTool, _IN_CRON_CONTEXT
from lemonclaw.cli.commands import _normalize_runtime_delivery_metadata
from lemonclaw.cron.service import CronService
from lemonclaw.cron.types import CronSchedule
from lemonclaw.ledger.runtime import TaskLedger


def test_add_job_rejects_unknown_timezone(tmp_path) -> None:
    service = CronService(tmp_path / "cron" / "jobs.json")

    with pytest.raises(ValueError, match="unknown timezone 'America/Vancovuer'"):
        service.add_job(
            name="tz typo",
            schedule=CronSchedule(kind="cron", expr="0 9 * * *", tz="America/Vancovuer"),
            message="hello",
        )

    assert service.list_jobs(include_disabled=True) == []


def test_normalize_runtime_delivery_metadata_promotes_delivery_contract() -> None:
    metadata = {
        "session_context": {
            "session_key": "telegram:123:456",
            "identity": {
                "channel": "telegram",
                "account": "",
                "chat": "123",
                "thread": "456",
                "topic": "",
            },
            "timezone": "Asia/Shanghai",
            "run_mode": "interactive",
        },
        "delivery_context": {
            "source_channel": "telegram",
            "source_chat_id": "123",
            "session_key": "telegram:123:456",
            "route": {"reply_to_message_id": 321, "message_thread_id": 456},
        },
        "delivery_policy": {
            "mode": "replace",
            "preserve_message_identity": True,
        },
    }

    normalized = _normalize_runtime_delivery_metadata(metadata)

    assert normalized["_session_context"]["identity"]["thread"] == "456"
    assert normalized["_delivery_context"]["route"]["message_thread_id"] == 456
    assert normalized["delivery_context"]["session_key"] == "telegram:123:456"
    assert normalized["_delivery_policy"]["mode"] == "replace"
    assert normalized["delivery_policy"]["preserve_message_identity"] is True


async def test_cron_tool_blocks_add_in_cron_context(tmp_path) -> None:
    """CronTool.execute(action='add') should be rejected inside cron context."""
    service = CronService(tmp_path / "cron" / "jobs.json")
    tool = CronTool(service)
    tool.set_context("test", "chat1")

    # Normal add should work
    result = await tool.execute(action="add", message="hello", every_seconds=60, _default_channel="test", _default_chat_id="chat1", _session_key="test:chat1")
    assert "Created job" in result

    # Inside cron context, add should be blocked
    token = _IN_CRON_CONTEXT.set(True)
    try:
        result = await tool.execute(action="add", message="recursive", every_seconds=60, _default_channel="test", _default_chat_id="chat1", _session_key="test:chat1")
        assert "cannot schedule" in result
    finally:
        _IN_CRON_CONTEXT.reset(token)

    # After reset, add should work again
    result = await tool.execute(action="add", message="after reset", every_seconds=120, _default_channel="test", _default_chat_id="chat1", _session_key="test:chat1")
    assert "Created job" in result


@pytest.mark.asyncio
async def test_cron_tool_prefers_per_call_default_context_over_instance_context(tmp_path) -> None:
    service = CronService(tmp_path / "cron" / "jobs.json")
    tool = CronTool(service)
    tool.set_context("old", "stale")

    result = await tool.execute(
        action="add",
        message="hello",
        every_seconds=60,
        _default_channel="fresh",
        _default_chat_id="target",
        _session_key="fresh:target:thread",
    )

    assert "Created job" in result
    jobs = service.list_jobs()
    assert len(jobs) == 1
    assert jobs[0].payload.channel == "fresh"
    assert jobs[0].payload.to == "target"
    assert jobs[0].payload.session_key == "fresh:target:thread"


@pytest.mark.asyncio
async def test_cron_tool_fails_closed_without_full_context(tmp_path) -> None:
    service = CronService(tmp_path / "cron" / "jobs.json")
    tool = CronTool(service)
    tool.set_context("old", "stale")

    result = await tool.execute(
        action="add",
        message="hello",
        every_seconds=60,
        _default_channel="fresh",
        _default_chat_id="target",
    )

    assert "cron add needs an active conversation target" in result
    assert service.list_jobs() == []


@pytest.mark.asyncio
async def test_cron_tool_persists_session_and_delivery_context(tmp_path) -> None:
    service = CronService(tmp_path / "cron" / "jobs.json")
    tool = CronTool(service)
    tool.set_context("telegram", "123")

    result = await tool.execute(
        action="add",
        message="hello",
        every_seconds=60,
        _default_channel="telegram",
        _default_chat_id="123",
        _session_key="telegram:123:456",
        _default_session_context={
            "session_key": "telegram:123:456",
            "identity": {
                "channel": "telegram",
                "account": "",
                "chat": "123",
                "thread": "456",
                "topic": "",
            },
            "timezone": "Asia/Shanghai",
            "run_mode": "interactive",
        },
        _default_delivery_context={
            "source_channel": "telegram",
            "source_chat_id": "123",
            "session_key": "telegram:123:456",
            "route": {"reply_to_message_id": 321, "message_thread_id": 456},
        },
        _default_delivery_policy={
            "mode": "replace",
            "preserve_message_identity": True,
        },
    )

    assert "Created job" in result
    jobs = service.list_jobs()
    assert len(jobs) == 1
    assert jobs[0].payload.session_key == "telegram:123:456"
    assert jobs[0].payload.metadata["session_context"]["identity"]["thread"] == "456"
    assert jobs[0].payload.metadata["session_context"]["run_mode"] == "interactive"
    assert jobs[0].payload.metadata["delivery_context"]["route"]["message_thread_id"] == 456
    assert jobs[0].payload.metadata["delivery_policy"]["mode"] == "replace"
    assert jobs[0].payload.metadata["delivery_policy"]["preserve_message_identity"] is True


def test_cron_service_round_trips_session_key_from_json(tmp_path) -> None:
    service = CronService(tmp_path / "cron" / "jobs.json")
    service.add_job(
        name="persist session",
        schedule=CronSchedule(kind="every", every_ms=1000),
        message="hello",
        channel="telegram",
        to="123",
        session_key="telegram:123:456",
        metadata={"delivery_context": {"session_key": "telegram:123:456"}},
    )

    reloaded = CronService(tmp_path / "cron" / "jobs.json")
    jobs = reloaded.list_jobs()

    assert len(jobs) == 1
    assert jobs[0].payload.session_key == "telegram:123:456"
    assert jobs[0].payload.metadata["delivery_context"]["session_key"] == "telegram:123:456"


@pytest.mark.asyncio
async def test_cron_service_recovers_prefix_jobs_from_corrupt_tail(tmp_path) -> None:
    path = tmp_path / "cron" / "jobs.json"
    service = CronService(path)
    first = service.add_job(
        name="first job",
        schedule=CronSchedule(kind="every", every_ms=1000),
        message="hello first",
    )
    second = service.add_job(
        name="second job",
        schedule=CronSchedule(kind="every", every_ms=2000),
        message="hello second",
    )

    text = path.read_text(encoding="utf-8")
    cut_at = text.index(f'"id": "{second.id}"')
    path.write_text(text[:cut_at] + "\n{\"broken\": ", encoding="utf-8")

    reloaded = CronService(path)
    jobs = reloaded.list_jobs(include_disabled=True)

    assert [job.id for job in jobs] == [first.id]
    assert jobs[0].name == "first job"

    await reloaded.start()
    reloaded.stop()

    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert [job["id"] for job in persisted["jobs"]] == [first.id]


@pytest.mark.asyncio
async def test_cron_service_does_not_overwrite_unrecoverable_corrupt_store(tmp_path) -> None:
    path = tmp_path / "cron" / "jobs.json"
    original_text = '{"version": 1, "jobs": [\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(original_text, encoding="utf-8")

    service = CronService(path)
    assert service.list_jobs(include_disabled=True) == []

    await service.start()
    service.stop()

    assert path.read_text(encoding="utf-8") == original_text


def test_add_job_accepts_valid_timezone(tmp_path) -> None:
    service = CronService(tmp_path / "cron" / "jobs.json")

    job = service.add_job(
        name="tz ok",
        schedule=CronSchedule(kind="cron", expr="0 9 * * *", tz="America/Vancouver"),
        message="hello",
    )

    assert job.schedule.tz == "America/Vancouver"
    assert job.state.next_run_at_ms is not None


@pytest.mark.asyncio
async def test_cron_service_writes_task_ledger(tmp_path) -> None:
    ledger = TaskLedger(tmp_path)
    service = CronService(tmp_path / "cron" / "jobs.json", task_ledger=ledger)
    job = service.add_job(
        name="ledger job",
        schedule=CronSchedule(kind="every", every_ms=1000),
        message="hello ledger",
    )

    async def _on_job(_job):
        return "ok"

    service.on_job = _on_job
    await service._execute_job(job)

    task_id_prefix = f"task_cron_{job.id}_"
    tasks = [task for task in ledger.list_tasks(limit=10) if str(task.get("task_id") or "").startswith(task_id_prefix)]
    assert len(tasks) == 1
    task = tasks[0]
    assert task["status"] == "completed"
    assert task["resume_context"]["channel"] == "cli"
    assert task["resume_context"]["chat_id"] == "direct"
    assert task["resume_context"]["session_key"] == f"cron:{job.id}"
    assert task["resume_context"]["session_context"]["identity"]["channel"] == "cli"
    assert task["resume_context"]["session_context"]["run_mode"] == "system"
    assert task["resume_context"]["auto_resume_allowed"] is False
    assert "explicit delivery target" in task["resume_context"]["resume_disabled_reason"]
    assert task["completion_gate"]["passed"] is True


@pytest.mark.asyncio
async def test_cron_service_persists_resume_context_from_job_payload(tmp_path) -> None:
    ledger = TaskLedger(tmp_path)
    service = CronService(tmp_path / "cron" / "jobs.json", task_ledger=ledger)
    job = service.add_job(
        name="threaded job",
        schedule=CronSchedule(kind="every", every_ms=1000),
        message="hello thread",
        channel="telegram",
        to="123",
        session_key="telegram:123:456",
        metadata={
            "delivery_context": {
                "source_channel": "telegram",
                "source_chat_id": "123",
                "session_key": "telegram:123:456",
                "route": {"reply_to_message_id": 321, "message_thread_id": 456},
            },
            "delivery_policy": {
                "mode": "replace",
                "preserve_message_identity": True,
                "throttle_ms": "250",
            },
        },
    )

    async def _on_job(_job):
        return "ok"

    service.on_job = _on_job
    await service._execute_job(job)

    task_id_prefix = f"task_cron_{job.id}_"
    tasks = [task for task in ledger.list_tasks(limit=10) if str(task.get("task_id") or "").startswith(task_id_prefix)]
    assert len(tasks) == 1
    task = tasks[0]
    assert task["resume_context"]["channel"] == "telegram"
    assert task["resume_context"]["chat_id"] == "123"
    assert task["resume_context"]["session_key"] == "telegram:123:456"
    assert task["resume_context"]["session_context"]["identity"]["chat"] == "123"
    assert task["resume_context"]["session_context"]["run_mode"] == "system"
    assert task["resume_context"]["auto_resume_allowed"] is True
    assert task["resume_context"]["delivery_context"]["route"]["message_thread_id"] == 456
    assert task["resume_context"]["delivery_policy"]["mode"] == "replace"
    assert task["resume_context"]["delivery_policy"]["preserve_message_identity"] is True
    assert task["resume_context"]["delivery_policy"]["throttle_ms"] == 250
