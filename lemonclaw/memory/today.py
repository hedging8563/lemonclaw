"""Today.md — daily hot data layer for STM."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from loguru import logger


class TodayLog:
    """Manages today.md — a focused daily summary that's more useful than HISTORY.md.

    Format:
        # YYYY-MM-DD
        ## HH:MM — Brief title
        - Detail line 1
        - Detail line 2
    """

    def __init__(self, memory_dir: Path):
        self._dir = memory_dir
        self._file = memory_dir / "today.md"

    def _read_raw(self) -> str:
        """Read today.md raw content regardless of staleness."""
        if not self._file.exists():
            return ""
        return self._file.read_text(encoding="utf-8")

    def read(self) -> str:
        """Read today.md content. Returns empty string if file doesn't exist or is stale."""
        text = self._read_raw()
        if not text:
            return ""
        # Check if the file is from today
        first_line = text.split("\n", 1)[0].strip()
        today_header = f"# {date.today()}"
        if not first_line.startswith(today_header):
            return ""  # Stale file from a previous day
        return text

    def append(self, title: str, details: list[str] | None = None) -> None:
        """Append an entry to today.md."""
        self._dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now().strftime("%H:%M")
        today_header = f"# {date.today()}\n"

        existing = self.read()
        if not existing:
            # Start fresh for today
            existing = today_header + "\n"

        entry = f"## {now} — {title}\n"
        if details:
            entry += "\n".join(f"- {d}" for d in details) + "\n"
        entry += "\n"

        self._file.write_text(existing + entry, encoding="utf-8")

    def archive_to_history(self, history_file: Path) -> bool:
        """Move today's content to HISTORY.md and clear today.md.

        Called by Daily Reflection cron job.
        Returns True if there was content to archive.
        Uses _read_raw() to avoid staleness check — stale files ARE what we want to archive.
        """
        content = self._read_raw()
        if not content.strip():
            return False

        # Append to HISTORY.md
        with open(history_file, "a", encoding="utf-8") as f:
            f.write(content.rstrip() + "\n\n")

        # Clear today.md
        self._file.write_text(f"# {date.today()}\n\n", encoding="utf-8")
        logger.info("Archived today.md to HISTORY.md")
        return True
