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

    @staticmethod
    def _default_notify_target(sender_id: str) -> str:
        sid = str(sender_id).strip()
        return sid.split("|")[0] if sid else sid

    def resolve_sender(self, sender_id: str, *, include_pending: bool = True) -> str | None:
        sid = str(sender_id).strip()
        if not sid:
            return None
        candidates = []
        if self.owner:
            candidates.append(str(self.owner))
        candidates.extend(str(item) for item in self.approved if str(item))
        if include_pending:
            candidates.extend(str(item) for item in self.pending.keys() if str(item))
        if sid in candidates:
            return sid
        for candidate in candidates:
            if sid and any(part == sid for part in candidate.split("|") if part):
                return candidate
        return None

    def describe_sender(self, sender_id: str) -> dict[str, Any]:
        sid = str(sender_id).strip()
        resolved = self.resolve_sender(sid)
        if self.owner and resolved == self.owner:
            return {
                "state": "owner",
                "resolved_sender_id": resolved,
                "approved_count": len(self.approved),
                "pending_count": len(self.pending),
                "pending_ids": list(self.pending.keys()),
            }
        if resolved in self.approved:
            return {
                "state": "approved",
                "resolved_sender_id": resolved,
                "approved_count": len(self.approved),
                "pending_count": len(self.pending),
                "pending_ids": [],
            }
        if resolved in self.pending:
            return {
                "state": "pending",
                "resolved_sender_id": resolved,
                "approved_count": len(self.approved),
                "pending_count": len(self.pending),
                "pending_ids": [],
            }
        return {
            "state": "unknown",
            "resolved_sender_id": None,
            "approved_count": len(self.approved),
            "pending_count": len(self.pending),
            "pending_ids": [],
        }

    def list_pending_ids(self) -> list[str]:
        return sorted(str(item) for item in self.pending.keys())

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

    def transfer_owner(self, sender_id: str) -> str | None:
        """Transfer ownership to an already approved user.

        Returns the new owner notify target when successful.
        """
        resolved = self.resolve_sender(sender_id, include_pending=False)
        if not resolved:
            return None
        if resolved not in self.approved and resolved != self.owner:
            return None
        self._state["owner"] = resolved
        self._state["owner_notify_target"] = self._default_notify_target(resolved)
        approved = self._state.setdefault("approved", [])
        if resolved not in approved:
            approved.append(resolved)
        self._save()
        logger.info("auto-pairing: {} became owner of {}", resolved, self._channel)
        return self.owner_notify_target

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
