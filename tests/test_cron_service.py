import pytest

from lemonclaw.agent.tools.cron import CronTool, _IN_CRON_CONTEXT
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


async def test_cron_tool_blocks_add_in_cron_context(tmp_path) -> None:
    """CronTool.execute(action='add') should be rejected inside cron context."""
    service = CronService(tmp_path / "cron" / "jobs.json")
    tool = CronTool(service)
    tool.set_context("test", "chat1")

    # Normal add should work
    result = await tool.execute(action="add", message="hello", every_seconds=60)
    assert "Created job" in result

    # Inside cron context, add should be blocked
    token = _IN_CRON_CONTEXT.set(True)
    try:
        result = await tool.execute(action="add", message="recursive", every_seconds=60)
        assert "cannot schedule" in result
    finally:
        _IN_CRON_CONTEXT.reset(token)

    # After reset, add should work again
    result = await tool.execute(action="add", message="after reset", every_seconds=120)
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
    )

    assert "Created job" in result
    jobs = service.list_jobs()
    assert len(jobs) == 1
    assert jobs[0].payload.channel == "fresh"
    assert jobs[0].payload.to == "target"


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
        _default_delivery_context={
            "source_channel": "telegram",
            "source_chat_id": "123",
            "session_key": "telegram:123:456",
            "route": {"reply_to_message_id": 321, "message_thread_id": 456},
        },
    )

    assert "Created job" in result
    jobs = service.list_jobs()
    assert len(jobs) == 1
    assert jobs[0].payload.session_key == "telegram:123:456"
    assert jobs[0].payload.metadata["delivery_context"]["route"]["message_thread_id"] == 456


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
    task_files = list((tmp_path / ".lemonclaw-state" / "tasks").glob(f"{task_id_prefix}*.json"))
    assert len(task_files) == 1
    task = __import__("json").loads(task_files[0].read_text(encoding="utf-8"))
    assert task["status"] == "completed"
    assert task["resume_context"]["channel"] == "cli"
    assert task["resume_context"]["chat_id"] == "direct"
    assert task["resume_context"]["session_key"] == f"cron:{job.id}"
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
            }
        },
    )

    async def _on_job(_job):
        return "ok"

    service.on_job = _on_job
    await service._execute_job(job)

    task_id_prefix = f"task_cron_{job.id}_"
    task_files = list((tmp_path / ".lemonclaw-state" / "tasks").glob(f"{task_id_prefix}*.json"))
    assert len(task_files) == 1
    task = __import__("json").loads(task_files[0].read_text(encoding="utf-8"))
    assert task["resume_context"]["channel"] == "telegram"
    assert task["resume_context"]["chat_id"] == "123"
    assert task["resume_context"]["session_key"] == "telegram:123:456"
    assert task["resume_context"]["auto_resume_allowed"] is True
    assert task["resume_context"]["delivery_context"]["route"]["message_thread_id"] == 456
