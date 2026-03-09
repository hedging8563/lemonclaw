"""Session management for conversation history."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from lemonclaw.utils.attachments import (
    append_attachment_inventory,
    persist_session_attachments,
    session_attachment_dir,
)
from lemonclaw.utils.helpers import ensure_dir, safe_filename


@dataclass
class Session:
    """
    A conversation session.

    Stores messages in JSONL format for easy reading and persistence.

    Important: Messages are append-only for LLM cache efficiency.
    The consolidation process writes summaries to MEMORY.md/HISTORY.md
    but does NOT modify the messages list or get_history() output.
    """

    key: str  # channel:chat_id
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)
    last_consolidated: int = 0  # Number of messages already consolidated to files
    version: int = 0  # Incremented on every save to support lightweight live sync

    def add_message(self, role: str, content: str, **kwargs: Any) -> None:
        """Add a message to the session."""
        msg = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            **kwargs,
        }
        self.messages.append(msg)
        self.updated_at = datetime.now()

    def get_history(self, max_messages: int = 500) -> list[dict[str, Any]]:
        """Return unconsolidated messages for LLM input, aligned to a user turn."""
        unconsolidated = self.messages[self.last_consolidated :]
        sliced = unconsolidated[-max_messages:]

        for index, message in enumerate(sliced):
            if message.get("role") == "user":
                sliced = sliced[index:]
                break
        else:
            sliced = []

        out: list[dict[str, Any]] = []
        for message in sliced:
            content = append_attachment_inventory(str(message.get("content", "") or ""), message.get("media"))
            entry: dict[str, Any] = {"role": message["role"], "content": content}
            for key in ("tool_calls", "tool_call_id", "name"):
                if key in message:
                    entry[key] = message[key]
            out.append(entry)
        return out

    def clear(self) -> None:
        """Clear all messages and reset session to initial state."""
        self.messages = []
        self.last_consolidated = 0
        self.updated_at = datetime.now()


class SessionManager:
    """Manages conversation sessions stored as JSONL files."""

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.sessions_dir = ensure_dir(self.workspace / "sessions")
        self.attachments_dir = ensure_dir(self.workspace / "attachments")
        self.legacy_sessions_dir = Path.home() / ".lemonclaw" / "sessions"
        self._cache: dict[str, Session] = {}
        self._cache_order: list[str] = []
        self._MAX_CACHED_SESSIONS = 200

    def _get_session_path(self, key: str) -> Path:
        safe_key = safe_filename(key.replace(":", "_"))
        return self.sessions_dir / f"{safe_key}.jsonl"

    def _get_legacy_session_path(self, key: str) -> Path:
        safe_key = safe_filename(key.replace(":", "_"))
        return self.legacy_sessions_dir / f"{safe_key}.jsonl"

    def get_attachment_dir(self, key: str, *, ensure: bool = True) -> Path:
        return session_attachment_dir(self.workspace, key, ensure=ensure)

    def persist_attachments(self, key: str, paths: list[str] | None) -> tuple[list[str], dict[str, str]]:
        return persist_session_attachments(self.workspace, key, paths)

    def _touch_cache(self, key: str) -> None:
        if key in self._cache_order:
            self._cache_order.remove(key)
        self._cache_order.append(key)

    def _evict_cache(self) -> None:
        while len(self._cache) > self._MAX_CACHED_SESSIONS and self._cache_order:
            oldest = self._cache_order.pop(0)
            self._cache.pop(oldest, None)

    def get_or_create(self, key: str) -> Session:
        if key in self._cache:
            self._touch_cache(key)
            return self._cache[key]

        session = self._load(key)
        if session is None:
            session = Session(key=key)

        self._cache[key] = session
        self._touch_cache(key)
        if len(self._cache) > self._MAX_CACHED_SESSIONS:
            self._evict_cache()
        return session

    def _load(self, key: str) -> Session | None:
        path = self._get_session_path(key)
        if not path.exists():
            legacy_path = self._get_legacy_session_path(key)
            if legacy_path.exists():
                try:
                    shutil.move(str(legacy_path), str(path))
                    logger.info("Migrated session {} from legacy path", key)
                except Exception:
                    logger.exception("Failed to migrate session {}", key)

        if not path.exists():
            return None

        try:
            messages: list[dict[str, Any]] = []
            metadata: dict[str, Any] = {}
            created_at = None
            last_consolidated = 0
            version = 0
            truncated = False

            with open(path, encoding="utf-8") as file_handle:
                for line_num, line in enumerate(file_handle, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning(
                            "Session {}: truncating corrupt line {} (partial write)",
                            key,
                            line_num,
                        )
                        truncated = True
                        break

                    if data.get("_type") == "metadata":
                        metadata = data.get("metadata", {})
                        created_at = datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None
                        last_consolidated = data.get("last_consolidated", 0)
                        version = data.get("version", 0)
                    else:
                        messages.append(data)

            session = Session(
                key=key,
                messages=messages,
                created_at=created_at or datetime.now(),
                metadata=metadata,
                last_consolidated=last_consolidated,
                version=version,
            )
            if truncated:
                self._atomic_save(path, session)
            return session
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            logger.warning("Failed to load session {}: {} ({})", key, type(exc).__name__, exc)
            return None

    def _atomic_save(self, path: Path, session: Session) -> None:
        tmp_path = path.with_suffix(f".jsonl.{os.getpid()}.tmp")
        with open(tmp_path, "w", encoding="utf-8") as file_handle:
            metadata_line = {
                "_type": "metadata",
                "key": session.key,
                "created_at": session.created_at.isoformat(),
                "updated_at": session.updated_at.isoformat(),
                "metadata": session.metadata,
                "last_consolidated": session.last_consolidated,
                "version": session.version,
            }
            file_handle.write(json.dumps(metadata_line, ensure_ascii=False) + "\n")
            for message in session.messages:
                file_handle.write(json.dumps(message, ensure_ascii=False) + "\n")
            file_handle.flush()
            os.fsync(file_handle.fileno())
        os.rename(str(tmp_path), str(path))

    def save(self, session: Session) -> None:
        session.version += 1
        path = self._get_session_path(session.key)
        self._atomic_save(path, session)
        self._cache[session.key] = session
        self._touch_cache(session.key)

    def invalidate(self, key: str) -> None:
        self._cache.pop(key, None)
        if key in self._cache_order:
            self._cache_order.remove(key)

    def list_sessions(self) -> list[dict[str, Any]]:
        sessions = []
        for path in self.sessions_dir.glob("*.jsonl"):
            try:
                with open(path, encoding="utf-8") as file_handle:
                    first_line = file_handle.readline().strip()
                    if not first_line:
                        continue
                    data = json.loads(first_line)
                    if data.get("_type") != "metadata":
                        continue
                    key = data.get("key") or path.stem.replace("_", ":", 1)
                    metadata = data.get("metadata", {})
                    msg_count = sum(1 for _ in file_handle)
                    sessions.append(
                        {
                            "key": key,
                            "title": metadata.get("title", ""),
                            "model": metadata.get("current_model", ""),
                            "created_at": data.get("created_at"),
                            "updated_at": data.get("updated_at"),
                            "message_count": msg_count,
                            "path": str(path),
                        }
                    )
            except Exception as exc:
                logger.debug("Failed to read session metadata from {}: {}", path, exc)
                continue
        return sorted(sessions, key=lambda item: item.get("updated_at") or "", reverse=True)

    def archive_session(self, key: str) -> bool:
        path = self._get_session_path(key)
        if not path.exists():
            return False

        ts = datetime.now().strftime("%Y%m%dT%H%M%S")
        archived_key = f"{key}:{ts}"
        session = self._load(key)
        if session:
            session.key = archived_key
            archived_path = self._get_session_path(archived_key)
            self._atomic_save(archived_path, session)

        attachments_src = self.get_attachment_dir(key, ensure=False)
        attachments_dst = self.get_attachment_dir(archived_key, ensure=False)
        if attachments_src.exists():
            attachments_dst.parent.mkdir(parents=True, exist_ok=True)
            if attachments_dst.exists():
                shutil.rmtree(attachments_dst)
            shutil.move(str(attachments_src), str(attachments_dst))

        try:
            path.unlink()
        except OSError:
            pass
        self._cache.pop(key, None)
        if key in self._cache_order:
            self._cache_order.remove(key)
        return True

    def delete_session(self, key: str) -> bool:
        path = self._get_session_path(key)
        attachments = self.get_attachment_dir(key, ensure=False)
        self._cache.pop(key, None)
        if key in self._cache_order:
            self._cache_order.remove(key)
        deleted = False
        if path.exists():
            path.unlink()
            deleted = True
        if attachments.exists():
            shutil.rmtree(attachments, ignore_errors=True)
            deleted = True
        return deleted
