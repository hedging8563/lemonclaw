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
from html import unescape
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

_SAFE_DOC_ID = re.compile(r"^kd_[A-Za-z0-9_-]{1,64}$")
_ALLOWED_TYPES = {"url", "file", "manual"}
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def _now_ms() -> int:
    return int(time.time() * 1000)


class KnowledgeStore:
    """Persistent registry for knowledge sources under workspace/knowledge/."""

    def __init__(self, workspace: Path):
        self._dir = workspace / "knowledge"
        self._manifest = self._dir / "documents.json"
        self._chunks = self._dir / "chunks.json"
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
        content: str = "",
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
            "content": str(content or "")[:20000],
            "status": "registered",
            "chunk_count": 0,
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
            self._delete_chunks_unlocked(doc_id)
            return True

    def ingest_document(self, doc_id: str) -> dict[str, Any]:
        if not self.is_valid_doc_id(doc_id):
            raise ValueError("invalid doc_id")
        with self._lock:
            data = self._read_manifest_unlocked()
            target = next((item for item in data["documents"] if item.get("doc_id") == doc_id), None)
            if not target:
                raise KeyError("document not found")

            try:
                raw = self._load_document_content(target)
                chunks = self._chunk_text(raw, title=str(target.get("title") or ""))
                target["status"] = "ingested"
                target["chunk_count"] = len(chunks)
                target["last_error"] = ""
                target["ingested_at_ms"] = _now_ms()
            except Exception as exc:
                target["status"] = "error"
                target["chunk_count"] = 0
                target["last_error"] = str(exc)[:500]
                target["updated_at_ms"] = _now_ms()
                self._write_manifest_unlocked(data)
                raise

            target["updated_at_ms"] = _now_ms()
            self._write_manifest_unlocked(data)
            self._replace_chunks_unlocked(doc_id, chunks)
            return dict(target)

    def search(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        query = str(query or "").strip()
        if not query:
          return []
        tokens = [tok for tok in re.split(r"[^\w\u4e00-\u9fff]+", query.lower()) if tok]
        if not tokens:
            return []
        with self._lock:
            chunks = self._read_chunks_unlocked()
            documents = {item["doc_id"]: item for item in self._read_manifest_unlocked()["documents"]}

        ranked: list[tuple[int, dict[str, Any]]] = []
        for chunk in chunks:
            text = str(chunk.get("text") or "")
            hay = text.lower()
            score = 0
            if query.lower() in hay:
                score += 50
            for token in tokens:
                score += hay.count(token)
            if score <= 0:
                continue
            ranked.append((score, chunk))

        ranked.sort(key=lambda item: item[0], reverse=True)
        results: list[dict[str, Any]] = []
        for score, chunk in ranked[:max(1, int(limit))]:
            doc = documents.get(str(chunk.get("doc_id") or ""), {})
            text = str(chunk.get("text") or "")
            results.append({
                "doc_id": chunk.get("doc_id"),
                "chunk_id": chunk.get("chunk_id"),
                "title": doc.get("title") or chunk.get("title") or "",
                "source": doc.get("source") or "",
                "source_type": doc.get("source_type") or "",
                "score": score,
                "snippet": text[:280],
            })
        return results

    def _load_document_content(self, document: dict[str, Any]) -> str:
        source_type = str(document.get("source_type") or "")
        if source_type == "manual":
            content = str(document.get("content") or document.get("note") or "")
            if not content.strip():
                raise ValueError("manual content is empty")
            return content
        if source_type == "file":
            source = str(document.get("source") or "")
            path = Path(source).expanduser()
            if not path.exists():
                raise FileNotFoundError("file not found")
            return path.read_text(encoding="utf-8", errors="ignore")
        if source_type == "url":
            source = str(document.get("source") or "")
            req = Request(source, headers={"User-Agent": "LemonClawKnowledge/1.0"})
            with urlopen(req, timeout=10) as response:
                raw = response.read().decode("utf-8", errors="ignore")
            raw = re.sub(r"<script[\s\S]*?</script>", " ", raw, flags=re.IGNORECASE)
            raw = re.sub(r"<style[\s\S]*?</style>", " ", raw, flags=re.IGNORECASE)
            text = unescape(_TAG_RE.sub(" ", raw))
            text = _WHITESPACE_RE.sub(" ", text).strip()
            if not text:
                raise ValueError("url content is empty")
            return text
        raise ValueError("invalid source_type")

    def _chunk_text(self, text: str, *, title: str = "", size: int = 1200) -> list[dict[str, Any]]:
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
        if not paragraphs:
            paragraphs = [text.strip()]
        chunks: list[str] = []
        current = ""
        for part in paragraphs:
            next_value = f"{current}\n\n{part}".strip() if current else part
            if current and len(next_value) > size:
                chunks.append(current)
                current = part
            else:
                current = next_value
        if current:
            chunks.append(current)
        output: list[dict[str, Any]] = []
        for idx, chunk in enumerate(chunks):
            output.append({
                "chunk_id": f"chunk_{idx}",
                "title": title,
                "text": chunk[:5000],
            })
        return output

    def _read_chunks_unlocked(self) -> list[dict[str, Any]]:
        if not self._chunks.exists():
            return []
        try:
            raw = json.loads(self._chunks.read_text(encoding="utf-8"))
        except Exception:
            return []
        return list(raw.get("chunks") or [])

    def _replace_chunks_unlocked(self, doc_id: str, chunks: list[dict[str, Any]]) -> None:
        data = self._read_chunks_unlocked()
        data = [item for item in data if item.get("doc_id") != doc_id]
        now = _now_ms()
        for item in chunks:
            data.append({
                "doc_id": doc_id,
                "chunk_id": item["chunk_id"],
                "title": item.get("title") or "",
                "text": item.get("text") or "",
                "updated_at_ms": now,
            })
        self._write_chunks_unlocked({"version": 1, "chunks": data})

    def _delete_chunks_unlocked(self, doc_id: str) -> None:
        data = self._read_chunks_unlocked()
        next_chunks = [item for item in data if item.get("doc_id") != doc_id]
        self._write_chunks_unlocked({"version": 1, "chunks": next_chunks})

    def _write_chunks_unlocked(self, payload: dict[str, Any]) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        self._chunks.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

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
