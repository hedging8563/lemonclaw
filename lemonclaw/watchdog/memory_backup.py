"""Incremental memory backup.

Periodically copies workspace/memory/ and workspace/sessions/ to a
timestamped backup directory. Uses file mtime to skip unchanged files
(incremental). Runs as an asyncio background task alongside the gateway.
"""

from __future__ import annotations

import asyncio
import shutil
from datetime import datetime
from pathlib import Path

from loguru import logger

BACKUP_INTERVAL = 300  # 5 minutes
MAX_BACKUPS = 24       # keep last 24 backups (~2 hours at 5min interval)
BACKUP_DIRS = ("memory", "sessions")


class MemoryBackup:
    """Async background service for incremental memory backups."""

    def __init__(self, workspace: Path, backup_root: Path | None = None):
        self._workspace = workspace
        self._backup_root = backup_root or (workspace / "backups")
        self._task: asyncio.Task | None = None
        self._last_mtimes: dict[str, float] = {}

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())
        logger.info("Memory backup started (interval={}s)", BACKUP_INTERVAL)

    def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            logger.info("Memory backup stopped")

    async def _run(self) -> None:
        await asyncio.sleep(60)  # initial delay — let gateway settle
        while True:
            try:
                self._do_backup()
            except Exception:
                logger.exception("Memory backup failed")
            await asyncio.sleep(BACKUP_INTERVAL)

    def _do_backup(self) -> None:
        """Run one incremental backup cycle."""
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = self._backup_root / stamp
        copied = 0

        for dirname in BACKUP_DIRS:
            src_dir = self._workspace / dirname
            if not src_dir.is_dir():
                continue
            for src_file in src_dir.rglob("*"):
                if not src_file.is_file():
                    continue
                rel = src_file.relative_to(self._workspace)
                key = str(rel)
                mtime = src_file.stat().st_mtime

                # Skip unchanged files
                if key in self._last_mtimes and self._last_mtimes[key] >= mtime:
                    continue

                dst = dest / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_file, dst)
                self._last_mtimes[key] = mtime
                copied += 1

        if copied:
            logger.info("Memory backup: {} files → {}", copied, dest)
            self._prune()

    def _prune(self) -> None:
        """Remove old backups beyond MAX_BACKUPS."""
        if not self._backup_root.is_dir():
            return
        backups = sorted(
            [d for d in self._backup_root.iterdir() if d.is_dir()],
            key=lambda d: d.name,
        )
        while len(backups) > MAX_BACKUPS:
            old = backups.pop(0)
            shutil.rmtree(old, ignore_errors=True)
            logger.debug("Pruned old backup: {}", old.name)
