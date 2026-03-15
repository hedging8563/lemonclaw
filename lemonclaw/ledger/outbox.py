"""Outbox dispatcher for durable side-effect delivery.

This is a best-effort durable outbox:
- delivery intents are durably recorded before send
- retries, manual intervention and recovery remain auditable
- but it is not a fully transactional outbox with atomic commit guarantees
  across every external side effect
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from loguru import logger

from lemonclaw.ledger.completion_gate import finalize_task
from lemonclaw.ledger.runtime import TaskLedger


class PermanentOutboxError(RuntimeError):
    """Non-retriable outbox delivery error."""


class OutboxDispatcher:
    """Background dispatcher for best-effort durable outbox flows."""

    def __init__(
        self,
        ledger: TaskLedger,
        on_deliver: Callable[[dict[str, Any]], Awaitable[None]],
        *,
        poll_interval_s: float = 1.0,
        max_idle_poll_s: float = 15.0,
        batch_size: int = 20,
        retry_delay_ms: int = 5_000,
        max_attempts: int = 3,
        claim_owner: str = "outbox_dispatcher",
    ) -> None:
        self._ledger = ledger
        self._on_deliver = on_deliver
        self._poll_interval_s = poll_interval_s
        self._max_idle_poll_s = max(max_idle_poll_s, poll_interval_s)
        self._batch_size = batch_size
        self._retry_delay_ms = retry_delay_ms
        self._max_attempts = max_attempts
        self._claim_owner = claim_owner
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "outbox: dispatcher started (poll={}s batch={} retry={}ms max_attempts={})",
            self._poll_interval_s,
            self._batch_size,
            self._retry_delay_ms,
            self._max_attempts,
        )

    def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

    async def _run_loop(self) -> None:
        idle_sleep_s = self._poll_interval_s
        while self._running:
            try:
                delivered = await self.dispatch_once()
                if delivered == 0:
                    await asyncio.sleep(idle_sleep_s)
                    idle_sleep_s = min(self._max_idle_poll_s, idle_sleep_s * 2)
                else:
                    idle_sleep_s = self._poll_interval_s
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("outbox: dispatcher tick failed")
                await asyncio.sleep(idle_sleep_s)
                idle_sleep_s = min(self._max_idle_poll_s, idle_sleep_s * 2)

    async def dispatch_once(self) -> int:
        claimed = await asyncio.to_thread(
            self._ledger.claim_due_outbox_events,
            limit=self._batch_size,
            claim_owner=self._claim_owner,
        )
        delivered = 0
        for event in claimed:
            event_id = str(event.get("event_id") or "")
            task_id = str(event.get("task_id") or "")
            try:
                await self._on_deliver(event)
            except PermanentOutboxError as exc:
                updated = await asyncio.to_thread(
                    self._ledger.mark_outbox_failed,
                    event_id,
                    error=str(exc),
                )
                logger.warning("outbox: permanent delivery failure for {}: {}", event_id, exc)
                if updated and task_id and event.get("step_id"):
                    await asyncio.to_thread(
                        self._ledger.update_step_state,
                        task_id,
                        str(event.get("step_id")),
                        status="waiting_outbox",
                        error=str(exc),
                    )
                if updated and task_id:
                    await asyncio.to_thread(finalize_task, self._ledger, task_id)
            except Exception as exc:
                updated = await asyncio.to_thread(
                    self._ledger.mark_outbox_retry,
                    event_id,
                    error=str(exc),
                    retry_at_ms=self._ledger.now_ms() + self._retry_delay_ms,
                    max_attempts=self._max_attempts,
                )
                status = str((updated or {}).get("status") or "")
                logger.warning("outbox: delivery failed for {} (status={}): {}", event_id, status or "missing", exc)
                if updated and task_id and event.get("step_id"):
                    await asyncio.to_thread(
                        self._ledger.update_step_state,
                        task_id,
                        str(event.get("step_id")),
                        status="waiting_outbox",
                        error=str(exc),
                    )
                if updated and status == "failed" and task_id:
                    await asyncio.to_thread(finalize_task, self._ledger, task_id)
            else:
                updated = await asyncio.to_thread(self._ledger.mark_outbox_sent, event_id)
                if updated:
                    delivered += 1
                    logger.info("outbox: delivered {}", event_id)
                if updated and task_id and event.get("step_id"):
                    await asyncio.to_thread(
                        self._ledger.update_step_state,
                        task_id,
                        str(event.get("step_id")),
                        status="completed",
                        error=None,
                    )
                if updated and task_id:
                    await asyncio.to_thread(finalize_task, self._ledger, task_id)
        return delivered
