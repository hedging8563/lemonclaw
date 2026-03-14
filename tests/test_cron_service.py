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
    assert task["completion_gate"]["passed"] is True
