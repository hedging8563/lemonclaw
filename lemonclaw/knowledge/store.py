"""Lightweight knowledge source registry.

This is the first productized layer for knowledge management:
- register external sources (URL/file/manual)
- inspect them in WebUI
- prepare a stable contract for later ingestion/retrieval jobs
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

_SAFE_DOC_ID = re.compile(r"^kd_[A-Za-z0-9_-]{1,64}$")
_ALLOWED_TYPES = {"url", "file", "manual"}


def _now_ms() -> int:
    return int(time.time() * 1000)


class KnowledgeStore:
    """Persistent registry for knowledge sources under workspace/knowledge/."""

    def __init__(self, workspace: Path):
        self._dir = workspace / "knowledge"
        self._manifest = self._dir / "documents.json"
        self._lock = threading.RLock()

    @staticmethod
    def is_valid_doc_id(doc_id: str) -> bool:
        return bool(_SAFE_DOC_ID.match(doc_id))

    def list_documents(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._read_manifest_unlocked()["documents"])

    def summarize(self) -> dict[str, Any]:
        docs = self.list_documents()
        by_type: dict[str, int] = {}
        by_status: dict[str, int] = {}
        for doc in docs:
            by_type[doc["source_type"]] = by_type.get(doc["source_type"], 0) + 1
            by_status[doc["status"]] = by_status.get(doc["status"], 0) + 1
        return {
            "total": len(docs),
            "by_type": by_type,
            "by_status": by_status,
        }

    def create_document(
        self,
        *,
        source_type: str,
        source: str,
        title: str = "",
        note: str = "",
    ) -> dict[str, Any]:
        source_type = str(source_type or "").strip().lower()
        if source_type not in _ALLOWED_TYPES:
            raise ValueError("invalid source_type")
        source = str(source or "").strip()
        if not source:
            raise ValueError("source is required")
        now = _now_ms()
        record = {
            "doc_id": f"kd_{uuid.uuid4().hex[:12]}",
            "source_type": source_type,
            "source": source[:2000],
            "title": (title or source).strip()[:200],
            "note": str(note or "")[:2000],
            "status": "registered",
            "created_at_ms": now,
            "updated_at_ms": now,
        }
        with self._lock:
            data = self._read_manifest_unlocked()
            data["documents"].insert(0, record)
            self._write_manifest_unlocked(data)
        return record

    def delete_document(self, doc_id: str) -> bool:
        if not self.is_valid_doc_id(doc_id):
            raise ValueError("invalid doc_id")
        with self._lock:
            data = self._read_manifest_unlocked()
            before = len(data["documents"])
            data["documents"] = [item for item in data["documents"] if item.get("doc_id") != doc_id]
            if len(data["documents"]) == before:
                return False
            self._write_manifest_unlocked(data)
            return True

    def _read_manifest_unlocked(self) -> dict[str, Any]:
        if not self._manifest.exists():
            return {"version": 1, "documents": []}
        try:
            raw = json.loads(self._manifest.read_text(encoding="utf-8"))
        except Exception:
            return {"version": 1, "documents": []}
        docs = list(raw.get("documents") or [])
        docs.sort(key=lambda item: int(item.get("updated_at_ms") or 0), reverse=True)
        return {"version": 1, "documents": docs}

    def _write_manifest_unlocked(self, payload: dict[str, Any]) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        self._manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
