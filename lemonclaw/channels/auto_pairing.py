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
    def owner_notify_target(self) -> str | None:
        target = self._state.get("owner_notify_target")
        if isinstance(target, str) and target:
            return target
        owner = self.owner
        if isinstance(owner, str) and owner:
            return owner.split("|")[0]
        return None

    @property
    def approved(self) -> list[str]:
        return self._state.get("approved", [])

    @property
    def pending(self) -> dict[str, dict[str, str]]:
        return self._state.get("pending", {})

    def get_pending_notify_target(self, sender_id: str) -> str | None:
        entry = self.pending.get(str(sender_id), {})
        target = entry.get("notify_target")
        if isinstance(target, str) and target:
            return target
        sid = str(sender_id)
        return sid.split("|")[0] if sid else None

    def check_or_pair(
        self,
        sender_id: str,
        display_name: str = "",
        notify_target: str | None = None,
    ) -> str:
        """Check a sender and return an action.

        Returns:
            "allowed"  — sender is owner or approved
            "paired"   — sender just became owner (first user)
            "pending"  — pairing request queued for owner approval
            "already_pending" — request already queued
        """
        sid = str(sender_id)
        target = str(notify_target or sid).strip() or sid

        if sid == self.owner or sid in self.approved:
            if sid == self.owner and not self._state.get("owner_notify_target"):
                self._state["owner_notify_target"] = target
                self._save()
            return "allowed"

        for part in sid.split("|"):
            if part and (part == self.owner or part in self.approved):
                return "allowed"

        if not self.owner:
            self._state["owner"] = sid
            self._state["owner_notify_target"] = target
            self._state.setdefault("approved", []).append(sid)
            self._save()
            logger.info("auto-pairing: {} is now owner of {}", sid, self._channel)
            return "paired"

        if sid in self.pending:
            return "already_pending"

        self._state.setdefault("pending", {})[sid] = {
            "display_name": display_name or sid,
            "notify_target": target,
        }
        self._save()
        logger.info("auto-pairing: {} queued for approval on {}", sid, self._channel)
        return "pending"

    def approve(self, sender_id: str) -> str | None:
        """Approve a pending user. Returns the requester notify target if found."""
        sid = str(sender_id)
        pending = self.pending
        if sid not in pending:
            return None
        target = pending.get(sid, {}).get("notify_target") or sid.split("|")[0]
        del pending[sid]
        approved = self._state.setdefault("approved", [])
        if sid not in approved:
            approved.append(sid)
        self._save()
        logger.info("auto-pairing: {} approved on {}", sid, self._channel)
        return target

    def deny(self, sender_id: str) -> str | None:
        """Deny a pending user. Returns the requester notify target if found."""
        sid = str(sender_id)
        pending = self.pending
        if sid not in pending:
            return None
        target = pending.get(sid, {}).get("notify_target") or sid.split("|")[0]
        del pending[sid]
        self._save()
        return target

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> dict[str, Any]:
        if self._path.exists():
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    pending_raw = raw.get("pending", {})
                    pending: dict[str, dict[str, str]] = {}
                    if isinstance(pending_raw, dict):
                        for sid, value in pending_raw.items():
                            if isinstance(value, str):
                                pending[str(sid)] = {
                                    "display_name": value,
                                    "notify_target": str(sid),
                                }
                            elif isinstance(value, dict):
                                pending[str(sid)] = {
                                    "display_name": str(value.get("display_name") or sid),
                                    "notify_target": str(value.get("notify_target") or sid),
                                }
                    return {
                        "owner": raw.get("owner"),
                        "owner_notify_target": raw.get("owner_notify_target") or raw.get("owner"),
                        "approved": list(raw.get("approved", [])),
                        "pending": pending,
                    }
            except (json.JSONDecodeError, OSError, TypeError, ValueError):
                logger.warning("auto-pairing: corrupt state for {}, resetting", self._channel)
        return {"owner": None, "owner_notify_target": None, "approved": [], "pending": {}}

    def _save(self) -> None:
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._state, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.rename(self._path)
