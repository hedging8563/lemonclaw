"""Persistent runtime view for event-driven triggers."""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from loguru import logger

from lemonclaw.governance.redaction import redact_sensitive_value

_SAFE_TRIGGER_ID = re.compile(r"^tr_[A-Za-z0-9_-]{1,64}$")


def _now_ms() -> int:
    return int(time.time() * 1000)


def build_trigger_metadata(trigger: dict[str, Any], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build normalized runtime metadata to propagate a trigger through execution."""
    payload = {
        "_trigger_id": str(trigger.get("trigger_id") or ""),
        "_trigger_source": str(trigger.get("source") or ""),
        "_trigger_kind": str(trigger.get("kind") or ""),
    }
    if extra:
        payload.update(dict(extra))
    return payload


def _derive_trigger_family(source: str, kind: str) -> str:
    source_value = str(source or "").strip().lower()
    kind_value = str(kind or "").strip().lower()
    if source_value in {"cron", "heartbeat"}:
        return "scheduled"
    if source_value.startswith("alert.") or source_value.startswith("watchdog") or kind_value.startswith("watchdog."):
        return "alert"
    for prefix, family in (
        ("webhook.", "webhook"),
        ("stream.", "stream"),
        ("socket.", "socket"),
        ("poll.", "poll"),
        ("queue.", "queue"),
        ("bridge.", "bridge"),
        ("sync.", "sync"),
    ):
        if source_value.startswith(prefix):
            return family
    return "runtime"


class TriggerRuntime:
    """Append-only local trigger ledger for cron, webhook, and internal events."""

    def __init__(self, workspace: Path):
        self._state_dir = workspace / ".lemonclaw-state"
        self._path = self._state_dir / "triggers.jsonl"
        self._lock = threading.RLock()

    @staticmethod
    def is_valid_trigger_id(trigger_id: str) -> bool:
        return bool(_SAFE_TRIGGER_ID.match(trigger_id))

    def record_trigger(
        self,
        *,
        source: str,
        kind: str,
        payload_summary: str = "",
        session_key: str = "",
        channel: str = "",
        chat_id: str = "",
        status: str = "received",
        metadata: dict[str, Any] | None = None,
        task_id: str = "",
    ) -> dict[str, Any]:
        now = _now_ms()
        record = {
            "trigger_id": f"tr_{uuid.uuid4().hex[:12]}",
            "source": str(source or ""),
            "family": _derive_trigger_family(source, kind),
            "kind": str(kind or ""),
            "status": str(status or "received"),
            "payload_summary": str(payload_summary or "")[:500],
            "session_key": str(session_key or ""),
            "channel": str(channel or ""),
            "chat_id": str(chat_id or ""),
            "task_id": str(task_id or ""),
            "result_summary": "",
            "error": "",
            "created_at_ms": now,
            "updated_at_ms": now,
            "metadata": dict(metadata or {}),
        }
        with self._lock:
            self._append_jsonl(record)
        return self._sanitize(record)

    def link_task(
        self,
        trigger_id: str,
        *,
        task_id: str,
        session_key: str = "",
        status: str = "dispatching",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        return self.update_trigger(
            trigger_id,
            task_id=task_id,
            session_key=session_key,
            status=status,
            metadata=metadata or {},
        )

    def finish_trigger(
        self,
        trigger_id: str,
        *,
        status: str,
        result_summary: str = "",
        error: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        return self.update_trigger(
            trigger_id,
            status=status,
            result_summary=result_summary[:500],
            error=error[:500],
            metadata=metadata or {},
        )

    def update_trigger(self, trigger_id: str, **updates: Any) -> dict[str, Any] | None:
        self._require_valid_trigger_id(trigger_id)
        with self._lock:
            current = self._read_trigger_unlocked(trigger_id)
            if not current:
                return None
            current.update({k: v for k, v in updates.items() if v is not None and k != "metadata"})
            if "metadata" in updates:
                merged = dict(current.get("metadata") or {})
                merged.update(dict(updates.get("metadata") or {}))
                current["metadata"] = merged
            next_updated = _now_ms()
            previous_updated = int(current.get("updated_at_ms") or 0)
            current["updated_at_ms"] = max(next_updated, previous_updated + 1)
            self._append_jsonl(current)
            return self._sanitize(current)

    def read_trigger(self, trigger_id: str) -> dict[str, Any] | None:
        self._require_valid_trigger_id(trigger_id)
        with self._lock:
            record = self._read_trigger_unlocked(trigger_id)
        return self._sanitize(record) if record else None

    def list_triggers(
        self,
        *,
        limit: int = 50,
        source: str | None = None,
        family: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            records = self._materialize_unlocked()
        if source:
            records = [item for item in records if str(item.get("source") or "") == source]
        if family:
            records = [item for item in records if str(item.get("family") or "") == family]
        if status:
            records = [item for item in records if str(item.get("status") or "") == status]
        return [self._sanitize(item) for item in records[:max(1, int(limit))]]

    def summarize_triggers(self, *, limit: int = 500) -> dict[str, Any]:
        records = self.list_triggers(limit=limit)
        by_source: dict[str, int] = {}
        by_family: dict[str, int] = {}
        by_status: dict[str, int] = {}
        by_kind: dict[str, int] = {}
        for item in records:
            source = str(item.get("source") or "unknown")
            family = str(item.get("family") or "unknown")
            status = str(item.get("status") or "unknown")
            kind = str(item.get("kind") or "unknown")
            by_source[source] = by_source.get(source, 0) + 1
            by_family[family] = by_family.get(family, 0) + 1
            by_status[status] = by_status.get(status, 0) + 1
            by_kind[kind] = by_kind.get(kind, 0) + 1
        return {
            "total": len(records),
            "by_source": by_source,
            "by_family": by_family,
            "by_status": by_status,
            "by_kind": by_kind,
        }

    def _require_valid_trigger_id(self, trigger_id: str) -> None:
        if not self.is_valid_trigger_id(trigger_id):
            raise ValueError("invalid trigger_id")

    def _read_trigger_unlocked(self, trigger_id: str) -> dict[str, Any] | None:
        latest: dict[str, Any] | None = None
        for item in self._read_events_unlocked():
            if str(item.get("trigger_id") or "") == trigger_id:
                latest = item
        return latest

    def _materialize_unlocked(self) -> list[dict[str, Any]]:
        latest_by_id: dict[str, dict[str, Any]] = {}
        for item in self._read_events_unlocked():
            trigger_id = str(item.get("trigger_id") or "")
            if not trigger_id:
                continue
            latest_by_id[trigger_id] = item
        return sorted(
            latest_by_id.values(),
            key=lambda item: int(item.get("updated_at_ms") or 0),
            reverse=True,
        )

    def _read_events_unlocked(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line_number, line in enumerate(self._path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                logger.warning(
                    "Trigger ledger {}: truncating corrupt line {} (partial write)",
                    self._path,
                    line_number,
                )
                break
        return records

    def _append_jsonl(self, payload: dict[str, Any]) -> None:
        self._state_dir.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    @staticmethod
    def _sanitize(record: dict[str, Any]) -> dict[str, Any]:
        return redact_sensitive_value(record)
