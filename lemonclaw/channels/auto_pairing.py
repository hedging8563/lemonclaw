"""Auto-pairing: dynamic user approval for chat channels.

When allow_from is empty and auto_pairing is enabled, the first user to
message the bot becomes the "owner" and is automatically added to the
allow list. Subsequent unknown users trigger a pairing request that the
owner must approve via an inline reply.

This replaces the binary "open to all / locked to whitelist" model with
a practical middle ground for self-hosted instances.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loguru import logger


class AutoPairing:
    """Manages dynamic user pairing for a channel."""

    def __init__(self, channel_name: str, data_dir: Path):
        self._channel = channel_name
        self._path = data_dir / "pairing" / f"{channel_name}.json"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._state = self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def owner(self) -> str | None:
        return self._state.get("owner")

    @property
    def approved(self) -> list[str]:
        return self._state.get("approved", [])

    @property
    def pending(self) -> dict[str, str]:
        """Pending requests: {sender_id: display_name}."""
        return self._state.get("pending", {})

    def check_or_pair(self, sender_id: str, display_name: str = "") -> str:
        """Check a sender and return an action.

        Returns:
            "allowed"  — sender is owner or approved
            "paired"   — sender just became owner (first user)
            "pending"  — pairing request queued for owner approval
            "already_pending" — request already queued
        """
        sid = str(sender_id)

        # Already approved?
        if sid == self.owner or sid in self.approved:
            return "allowed"

        # Also check by splitting "id|username" format
        for part in sid.split("|"):
            if part and (part == self.owner or part in self.approved):
                return "allowed"

        # No owner yet → first user becomes owner
        if not self.owner:
            self._state["owner"] = sid
            self._state.setdefault("approved", []).append(sid)
            self._save()
            logger.info("auto-pairing: {} is now owner of {}", sid, self._channel)
            return "paired"

        # Already pending?
        if sid in self._state.get("pending", {}):
            return "already_pending"

        # Queue for approval
        self._state.setdefault("pending", {})[sid] = display_name or sid
        self._save()
        logger.info("auto-pairing: {} queued for approval on {}", sid, self._channel)
        return "pending"

    def approve(self, sender_id: str) -> bool:
        """Approve a pending user. Returns True if found and approved."""
        sid = str(sender_id)
        pending = self._state.get("pending", {})
        if sid not in pending:
            return False
        del pending[sid]
        self._state.setdefault("approved", []).append(sid)
        self._save()
        logger.info("auto-pairing: {} approved on {}", sid, self._channel)
        return True

    def deny(self, sender_id: str) -> bool:
        """Deny a pending user. Returns True if found and removed."""
        sid = str(sender_id)
        pending = self._state.get("pending", {})
        if sid not in pending:
            return False
        del pending[sid]
        self._save()
        return True

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> dict[str, Any]:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                logger.warning("auto-pairing: corrupt state for {}, resetting", self._channel)
        return {"owner": None, "approved": [], "pending": {}}

    def _save(self) -> None:
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._state, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.rename(self._path)
