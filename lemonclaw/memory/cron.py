"""Memory cron jobs — daily archive, weekly promotion, monthly cleanup."""

from __future__ import annotations

from pathlib import Path

from loguru import logger


# System event names used in CronPayload.message
EVENT_DAILY_ARCHIVE = "memory:daily_archive"
EVENT_WEEKLY_PROMOTE = "memory:weekly_promote"
EVENT_MONTHLY_CLEANUP = "memory:monthly_cleanup"

_ALL_EVENTS = {EVENT_DAILY_ARCHIVE, EVENT_WEEKLY_PROMOTE, EVENT_MONTHLY_CLEANUP}


async def run_memory_event(event: str, workspace: Path) -> str:
    """Execute a memory system event. Returns a status message."""
    from lemonclaw.agent.memory import MemoryStore

    store = MemoryStore(workspace)

    if event == EVENT_DAILY_ARCHIVE:
        archived = store.today.archive_to_history(store.history_file)
        msg = "Archived today.md to HISTORY.md" if archived else "Nothing to archive"
        logger.info("Memory cron [daily_archive]: {}", msg)
        return msg

    if event == EVENT_WEEKLY_PROMOTE:
        promoted = store.promoter.run_promotion()
        demoted = store.promoter.run_demotion()
        msg = f"Promoted {len(promoted)}, demoted {len(demoted)}"
        logger.info("Memory cron [weekly_promote]: {}", msg)
        return msg

    if event == EVENT_MONTHLY_CLEANUP:
        store._truncate_history_if_needed()
        # Invalidate entity cache so stale cards don't linger
        store.entities.invalidate_cache()
        msg = "History truncated, entity cache cleared"
        logger.info("Memory cron [monthly_cleanup]: {}", msg)
        return msg

    logger.warning("Unknown memory event: {}", event)
    return f"Unknown event: {event}"


def is_memory_event(message: str) -> bool:
    """Check if a cron payload message is a memory system event."""
    return message in _ALL_EVENTS


def register_memory_jobs(cron_service) -> int:
    """Register default memory cron jobs if not already present.

    Returns the number of jobs added.
    """
    from lemonclaw.cron.types import CronSchedule

    existing_names = {j.name for j in cron_service.list_jobs(include_disabled=True)}
    added = 0

    jobs = [
        ("memory:daily_archive", "0 0 * * *", EVENT_DAILY_ARCHIVE),      # midnight
        ("memory:weekly_promote", "0 3 * * 0", EVENT_WEEKLY_PROMOTE),    # Sunday 3am
        ("memory:monthly_cleanup", "0 4 1 * *", EVENT_MONTHLY_CLEANUP),  # 1st of month 4am
    ]

    for name, expr, event in jobs:
        if name in existing_names:
            continue
        cron_service.add_job(
            name=name,
            schedule=CronSchedule(kind="cron", expr=expr),
            message=event,
            payload_kind="system_event",
        )
        added += 1

    if added:
        logger.info("Registered {} memory cron jobs", added)
    return added
