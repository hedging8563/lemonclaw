"""Cron service for scheduling agent tasks."""

import asyncio
import contextvars
import json
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Coroutine

from loguru import logger

from lemonclaw.channels.delivery_context import get_delivery_policy
from lemonclaw.cron.types import CronJob, CronJobState, CronPayload, CronSchedule, CronStore
from lemonclaw.ledger.completion_gate import finalize_task
from lemonclaw.ledger.runtime import TaskLedger, build_task_resume_context


def _now_ms() -> int:
    return int(time.time() * 1000)


def _compute_next_run(schedule: CronSchedule, now_ms: int) -> int | None:
    """Compute next run time in ms."""
    if schedule.kind == "at":
        return schedule.at_ms if schedule.at_ms and schedule.at_ms > now_ms else None
    
    if schedule.kind == "every":
        if not schedule.every_ms or schedule.every_ms <= 0:
            return None
        # Next interval from now
        return now_ms + schedule.every_ms
    
    if schedule.kind == "cron" and schedule.expr:
        try:
            from croniter import croniter
            from zoneinfo import ZoneInfo
            # Use caller-provided reference time for deterministic scheduling
            base_time = now_ms / 1000
            tz = ZoneInfo(schedule.tz) if schedule.tz else datetime.now().astimezone().tzinfo
            base_dt = datetime.fromtimestamp(base_time, tz=tz)
            cron = croniter(schedule.expr, base_dt)
            next_dt = cron.get_next(datetime)
            return int(next_dt.timestamp() * 1000)
        except Exception:
            return None
    
    return None


def _validate_schedule_for_add(schedule: CronSchedule) -> None:
    """Validate schedule fields that would otherwise create non-runnable jobs."""
    if schedule.tz and schedule.kind != "cron":
        raise ValueError("tz can only be used with cron schedules")

    if schedule.kind == "cron" and schedule.tz:
        try:
            from zoneinfo import ZoneInfo

            ZoneInfo(schedule.tz)
        except Exception:
            raise ValueError(f"unknown timezone '{schedule.tz}'") from None


def _extract_complete_json_value(text: str, start: int) -> tuple[str, int] | None:
    """Extract one complete JSON object/array from text starting at *start*.

    This is intentionally small and local to the cron store loader so we can
    recover valid prefix data from partially-written files without changing the
    on-disk schema.
    """
    if start >= len(text) or text[start] not in "{[":
        return None

    closing_stack = ["}" if text[start] == "{" else "]"]
    in_string = False
    escaped = False

    for index in range(start + 1, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
            continue
        if char == "{":
            closing_stack.append("}")
            continue
        if char == "[":
            closing_stack.append("]")
            continue
        if char in "}]":
            if not closing_stack or char != closing_stack[-1]:
                return None
            closing_stack.pop()
            if not closing_stack:
                return text[start : index + 1], index + 1

    return None


class CronService:
    """Service for managing and executing scheduled jobs."""
    
    def __init__(
        self,
        store_path: Path,
        on_job: Callable[[CronJob], Coroutine[Any, Any, str | None]] | None = None,
        task_ledger: TaskLedger | None = None,
    ):
        self.store_path = store_path
        self.on_job = on_job  # Callback to execute job, returns response text
        self._store: CronStore | None = None
        self._store_load_failed = False
        self._timer_task: asyncio.Task | None = None
        self._running = False
        self._task_ledger = task_ledger
    
    def _load_store(self) -> CronStore:
        """Load jobs from disk."""
        if self._store:
            return self._store

        self._store_load_failed = False
        if self.store_path.exists():
            try:
                text = self.store_path.read_text(encoding="utf-8")
                store, recovered = self._parse_store_text(text)
                if store is None:
                    raise ValueError("unable to recover cron store prefix")
                self._store = store
                if recovered:
                    logger.warning("Recovered cron store {} from a truncated tail", self.store_path)
                    self._store_load_failed = False
            except Exception as e:
                logger.warning("Failed to load cron store: {}", e)
                self._store = CronStore()
                self._store_load_failed = True
        else:
            self._store = CronStore()
        
        return self._store

    def _parse_store_text(self, text: str) -> tuple[CronStore | None, bool]:
        """Parse a cron store, salvaging valid prefix data when possible."""
        decoder = json.JSONDecoder()
        stripped = text.lstrip()
        if not stripped:
            return None, False

        try:
            data, end = decoder.raw_decode(stripped)
        except json.JSONDecodeError:
            data = None
        else:
            if isinstance(data, dict):
                recovered = bool(stripped[end:].strip())
                store = self._store_from_data(data)
                if store is not None:
                    return store, recovered

        return self._recover_store_prefix(text)

    def _recover_store_prefix(self, text: str) -> tuple[CronStore | None, bool]:
        version_match = re.search(r'"version"\s*:\s*(\d+)', text)
        version = int(version_match.group(1)) if version_match else 1
        jobs_match = re.search(r'"jobs"\s*:\s*\[', text)
        if not jobs_match:
            return None, False

        jobs: list[CronJob] = []
        index = jobs_match.end()
        while index < len(text):
            while index < len(text) and text[index] in " \t\r\n,":
                index += 1
            if index >= len(text):
                break
            if text[index] == "]":
                return CronStore(version=version, jobs=jobs), bool(text[index + 1 :].strip())
            extracted = _extract_complete_json_value(text, index)
            if extracted is None:
                break
            raw_job, next_index = extracted
            job = self._job_from_data(json.loads(raw_job))
            if job is None:
                break
            jobs.append(job)
            index = next_index

        if not jobs:
            return None, False
        return CronStore(version=version, jobs=jobs), True

    def _store_from_data(self, data: dict[str, Any]) -> CronStore | None:
        jobs_data = data.get("jobs", [])
        if not isinstance(jobs_data, list):
            return None
        jobs: list[CronJob] = []
        for item in jobs_data:
            job = self._job_from_data(item)
            if job is None:
                return None
            jobs.append(job)
        version = data.get("version", 1)
        return CronStore(version=int(version) if isinstance(version, int) else 1, jobs=jobs)

    @staticmethod
    def _job_from_data(item: Any) -> CronJob | None:
        if not isinstance(item, dict):
            return None
        schedule_data = item.get("schedule")
        payload_data = item.get("payload")
        if not isinstance(schedule_data, dict) or not isinstance(payload_data, dict):
            return None
        return CronJob(
            id=str(item["id"]),
            name=str(item["name"]),
            enabled=bool(item.get("enabled", True)),
            schedule=CronSchedule(
                kind=str(schedule_data["kind"]),
                at_ms=schedule_data.get("atMs"),
                every_ms=schedule_data.get("everyMs"),
                expr=schedule_data.get("expr"),
                tz=schedule_data.get("tz"),
            ),
            payload=CronPayload(
                kind=str(payload_data.get("kind", "agent_turn")),
                message=str(payload_data.get("message", "")),
                deliver=bool(payload_data.get("deliver", False)),
                channel=payload_data.get("channel"),
                to=payload_data.get("to"),
                session_key=payload_data.get("sessionKey"),
                metadata=dict(payload_data.get("metadata", {}) or {}),
            ),
            state=CronJobState(
                next_run_at_ms=(item.get("state") or {}).get("nextRunAtMs"),
                last_run_at_ms=(item.get("state") or {}).get("lastRunAtMs"),
                last_status=(item.get("state") or {}).get("lastStatus"),
                last_error=(item.get("state") or {}).get("lastError"),
            ),
            created_at_ms=int(item.get("createdAtMs", 0) or 0),
            updated_at_ms=int(item.get("updatedAtMs", 0) or 0),
            delete_after_run=bool(item.get("deleteAfterRun", False)),
        )
    
    def _save_store(self) -> None:
        """Save jobs to disk."""
        if not self._store:
            return
        
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        
        data = {
            "version": self._store.version,
            "jobs": [
                {
                    "id": j.id,
                    "name": j.name,
                    "enabled": j.enabled,
                    "schedule": {
                        "kind": j.schedule.kind,
                        "atMs": j.schedule.at_ms,
                        "everyMs": j.schedule.every_ms,
                        "expr": j.schedule.expr,
                        "tz": j.schedule.tz,
                    },
                    "payload": {
                        "kind": j.payload.kind,
                        "message": j.payload.message,
                        "deliver": j.payload.deliver,
                        "channel": j.payload.channel,
                        "to": j.payload.to,
                        # Keep camelCase in JSON while the Python model stays
                        # snake_case to match the rest of the codebase.
                        "sessionKey": j.payload.session_key,
                        "metadata": dict(j.payload.metadata or {}),
                    },
                    "state": {
                        "nextRunAtMs": j.state.next_run_at_ms,
                        "lastRunAtMs": j.state.last_run_at_ms,
                        "lastStatus": j.state.last_status,
                        "lastError": j.state.last_error,
                    },
                    "createdAtMs": j.created_at_ms,
                    "updatedAtMs": j.updated_at_ms,
                    "deleteAfterRun": j.delete_after_run,
                }
                for j in self._store.jobs
            ]
        }
        
        tmp = self.store_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.store_path)
    
    async def start(self) -> None:
        """Start the cron service."""
        self._running = True
        self._load_store()
        self._recompute_next_runs()
        if not self._store_load_failed:
            self._save_store()
        self._arm_timer()
        logger.info("Cron service started with {} jobs", len(self._store.jobs if self._store else []))
    
    def stop(self) -> None:
        """Stop the cron service."""
        self._running = False
        if self._timer_task:
            self._timer_task.cancel()
            self._timer_task = None
    
    def _recompute_next_runs(self) -> None:
        """Recompute next run times for all enabled jobs."""
        if not self._store:
            return
        now = _now_ms()
        for job in self._store.jobs:
            if job.enabled:
                job.state.next_run_at_ms = _compute_next_run(job.schedule, now)
    
    def _get_next_wake_ms(self) -> int | None:
        """Get the earliest next run time across all jobs."""
        if not self._store:
            return None
        times = [j.state.next_run_at_ms for j in self._store.jobs 
                 if j.enabled and j.state.next_run_at_ms]
        return min(times) if times else None
    
    def _arm_timer(self) -> None:
        """Schedule the next timer tick."""
        if self._timer_task:
            self._timer_task.cancel()
        
        next_wake = self._get_next_wake_ms()
        if not next_wake or not self._running:
            return
        
        delay_ms = max(0, next_wake - _now_ms())
        delay_s = delay_ms / 1000
        
        async def tick():
            await asyncio.sleep(delay_s)
            if self._running:
                await self._on_timer()
        
        self._timer_task = asyncio.create_task(tick())
    
    async def _on_timer(self) -> None:
        """Handle timer tick - run due jobs."""
        if not self._store:
            return
        
        now = _now_ms()
        due_jobs = [
            j for j in self._store.jobs
            if j.enabled and j.state.next_run_at_ms and now >= j.state.next_run_at_ms
        ]
        
        for job in due_jobs:
            await self._execute_job(job)
        
        self._save_store()
        self._arm_timer()
    
    async def _execute_job(self, job: CronJob) -> None:
        """Execute a single job."""
        from lemonclaw.agent.tools.cron import _IN_CRON_CONTEXT

        start_ms = _now_ms()
        task_id = f"task_cron_{job.id}_{start_ms}"
        has_explicit_resume_target = bool(job.payload.channel and job.payload.to)
        effective_session_key = job.payload.session_key or f"cron:{job.id}"
        effective_channel = job.payload.channel or "cli"
        effective_chat_id = job.payload.to or "direct"
        payload_metadata = dict(job.payload.metadata or {})
        delivery_context = dict(payload_metadata.get("delivery_context") or {})
        delivery_policy = get_delivery_policy(payload_metadata)
        logger.info("Cron: executing job '{}' ({})", job.name, job.id)
        if self._task_ledger:
            self._task_ledger.ensure_task(
                task_id=task_id,
                session_key=effective_session_key,
                agent_id="cron",
                mode="cron",
                channel=effective_channel,
                goal=job.payload.message[:500],
                current_stage="cron_execute",
                resume_context=build_task_resume_context(
                    channel=effective_channel,
                    chat_id=effective_chat_id,
                    sender_id="cron",
                    session_key=effective_session_key,
                    timezone=str(payload_metadata.get("timezone") or ""),
                    run_mode="system",
                    session_context=dict(payload_metadata.get("_session_context") or {}) if isinstance(payload_metadata.get("_session_context"), dict) else None,
                    message_id="",
                    delivery_context=delivery_context,
                    delivery_policy=dict(delivery_policy) if isinstance(delivery_policy, dict) else None,
                    auto_resume_allowed=has_explicit_resume_target,
                    resume_disabled_reason=(
                        "" if has_explicit_resume_target
                        else "cron job has no explicit delivery target; resume requires operator review"
                    ),
                ),
                metadata={"job_id": job.id},
            )
            step = self._task_ledger.start_step(task_id, step_type="cron_job", name=job.name, input_summary=job.payload.message[:500])
        else:
            step = None

        token = _IN_CRON_CONTEXT.set(True)
        try:
            response = None
            if self.on_job:
                response = await self.on_job(job)

            job.state.last_status = "ok"
            job.state.last_error = None
            if step:
                self._task_ledger.finish_step(step, status="completed")
            if self._task_ledger:
                finalize_task(self._task_ledger, task_id)
            logger.info("Cron: job '{}' completed", job.name)

        except Exception as e:
            job.state.last_status = "error"
            job.state.last_error = str(e)
            if step:
                self._task_ledger.finish_step(step, status="failed", error=str(e)[:500])
            if self._task_ledger:
                self._task_ledger.update_task(task_id, status="failed", current_stage="error", error=str(e)[:500])
            logger.error("Cron: job '{}' failed: {}", job.name, e)
        finally:
            _IN_CRON_CONTEXT.reset(token)

        job.state.last_run_at_ms = start_ms
        job.updated_at_ms = _now_ms()
        
        # Handle one-shot jobs
        if job.schedule.kind == "at":
            if job.delete_after_run:
                self._store.jobs = [j for j in self._store.jobs if j.id != job.id]
            else:
                job.enabled = False
                job.state.next_run_at_ms = None
        else:
            # Compute next run
            job.state.next_run_at_ms = _compute_next_run(job.schedule, _now_ms())
    
    # ========== Public API ==========
    
    def list_jobs(self, include_disabled: bool = False) -> list[CronJob]:
        """List all jobs."""
        store = self._load_store()
        jobs = store.jobs if include_disabled else [j for j in store.jobs if j.enabled]
        return sorted(jobs, key=lambda j: j.state.next_run_at_ms or float('inf'))
    
    def add_job(
        self,
        name: str,
        schedule: CronSchedule,
        message: str,
        deliver: bool = False,
        channel: str | None = None,
        to: str | None = None,
        session_key: str | None = None,
        metadata: dict[str, Any] | None = None,
        delete_after_run: bool = False,
        payload_kind: str = "agent_turn",
    ) -> CronJob:
        """Add a new job."""
        store = self._load_store()
        _validate_schedule_for_add(schedule)
        now = _now_ms()

        job = CronJob(
            id=str(uuid.uuid4())[:8],
            name=name,
            enabled=True,
            schedule=schedule,
            payload=CronPayload(
                kind=payload_kind,
                message=message,
                deliver=deliver,
                channel=channel,
                to=to,
                session_key=session_key,
                metadata=metadata or {},
            ),
            state=CronJobState(next_run_at_ms=_compute_next_run(schedule, now)),
            created_at_ms=now,
            updated_at_ms=now,
            delete_after_run=delete_after_run,
        )
        
        store.jobs.append(job)
        self._save_store()
        self._arm_timer()
        
        logger.info("Cron: added job '{}' ({})", name, job.id)
        return job
    
    def remove_job(self, job_id: str) -> bool:
        """Remove a job by ID."""
        store = self._load_store()
        before = len(store.jobs)
        store.jobs = [j for j in store.jobs if j.id != job_id]
        removed = len(store.jobs) < before
        
        if removed:
            self._save_store()
            self._arm_timer()
            logger.info("Cron: removed job {}", job_id)
        
        return removed
    
    def enable_job(self, job_id: str, enabled: bool = True) -> CronJob | None:
        """Enable or disable a job."""
        store = self._load_store()
        for job in store.jobs:
            if job.id == job_id:
                job.enabled = enabled
                job.updated_at_ms = _now_ms()
                if enabled:
                    job.state.next_run_at_ms = _compute_next_run(job.schedule, _now_ms())
                else:
                    job.state.next_run_at_ms = None
                self._save_store()
                self._arm_timer()
                return job
        return None
    
    async def run_job(self, job_id: str, force: bool = False) -> bool:
        """Manually run a job."""
        store = self._load_store()
        for job in store.jobs:
            if job.id == job_id:
                if not force and not job.enabled:
                    return False
                await self._execute_job(job)
                self._save_store()
                self._arm_timer()
                return True
        return False
    
    def status(self) -> dict:
        """Get service status."""
        store = self._load_store()
        return {
            "enabled": self._running,
            "jobs": len(store.jobs),
            "next_wake_at_ms": self._get_next_wake_ms(),
        }
