"""Lightweight knowledge source registry.

This is the first productized layer for knowledge management:
- register external sources (URL/file/manual)
- inspect them in WebUI
- prepare a stable contract for later ingestion/retrieval jobs
"""

from __future__ import annotations

import json
import hashlib
import re
import threading
import time
import tempfile
import uuid
from html import unescape
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from lemonclaw.utils.pdf_extract import extract_pdf_content

_SAFE_DOC_ID = re.compile(r"^kd_[A-Za-z0-9_-]{1,64}$")
_ALLOWED_TYPES = {"url", "file", "manual"}
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?\.])\s+")
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _next_refresh_at_ms(interval_hours: int, *, now_ms: int | None = None) -> int | None:
    if interval_hours <= 0:
        return None
    base = now_ms if now_ms is not None else _now_ms()
    return base + int(interval_hours * 60 * 60 * 1000)


def _sha1_hexdigest(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()[:12]


class _RemoteNotModified(RuntimeError):
    def __init__(self, metadata: dict[str, Any]):
        super().__init__("remote content not modified")
        self.metadata = metadata


class KnowledgeStore:
    """Persistent registry for knowledge sources under workspace/knowledge/."""

    def __init__(self, workspace: Path):
        self._dir = workspace / "knowledge"
        self._manifest = self._dir / "documents.json"
        self._chunks = self._dir / "chunks.json"
        self._facts = self._dir / "facts.json"
        self._lock = threading.RLock()

    @staticmethod
    def is_valid_doc_id(doc_id: str) -> bool:
        return bool(_SAFE_DOC_ID.match(doc_id))

    def list_documents(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._read_manifest_unlocked()["documents"])

    def read_document(self, doc_id: str) -> dict[str, Any] | None:
        if not self.is_valid_doc_id(doc_id):
            raise ValueError("invalid doc_id")
        with self._lock:
            data = self._read_manifest_unlocked()
            return next((dict(item) for item in data["documents"] if item.get("doc_id") == doc_id), None)

    def summarize(self) -> dict[str, Any]:
        docs = self.list_documents()
        by_type: dict[str, int] = {}
        by_status: dict[str, int] = {}
        due_count = 0
        for doc in docs:
            by_type[doc["source_type"]] = by_type.get(doc["source_type"], 0) + 1
            by_status[doc["status"]] = by_status.get(doc["status"], 0) + 1
            if self._is_due_document(doc):
                due_count += 1
        return {
            "total": len(docs),
            "by_type": by_type,
            "by_status": by_status,
            "due_count": due_count,
        }

    def create_document(
        self,
        *,
        source_type: str,
        source: str,
        title: str = "",
        note: str = "",
        content: str = "",
        refresh_interval_hours: int = 0,
    ) -> dict[str, Any]:
        source_type = str(source_type or "").strip().lower()
        if source_type not in _ALLOWED_TYPES:
            raise ValueError("invalid source_type")
        source = str(source or "").strip()
        if not source:
            raise ValueError("source is required")
        refresh_interval_hours = max(0, int(refresh_interval_hours or 0))
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
            "fact_count": 0,
            "metadata": {},
            "refresh_interval_hours": refresh_interval_hours,
            "next_refresh_at_ms": None,
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
            self._delete_facts_unlocked(doc_id)
            return True

    def update_document(
        self,
        doc_id: str,
        *,
        title: str | None = None,
        note: str | None = None,
        source: str | None = None,
        source_type: str | None = None,
        content: str | None = None,
        refresh_interval_hours: int | None = None,
    ) -> dict[str, Any]:
        if not self.is_valid_doc_id(doc_id):
            raise ValueError("invalid doc_id")
        with self._lock:
            data = self._read_manifest_unlocked()
            target = next((item for item in data["documents"] if item.get("doc_id") == doc_id), None)
            if not target:
                raise KeyError("document not found")

            needs_reingest = False
            if title is not None:
                target["title"] = str(title).strip()[:200]
            if note is not None:
                target["note"] = str(note or "")[:2000]
            if source is not None:
                next_source = str(source or "").strip()
                if not next_source:
                    raise ValueError("source is required")
                if next_source != str(target.get("source") or ""):
                    target["source"] = next_source[:2000]
                    needs_reingest = True
            if source_type is not None:
                next_type = str(source_type or "").strip().lower()
                if next_type not in _ALLOWED_TYPES:
                    raise ValueError("invalid source_type")
                if next_type != str(target.get("source_type") or ""):
                    target["source_type"] = next_type
                    needs_reingest = True
            if content is not None:
                next_content = str(content or "")[:20000]
                if next_content != str(target.get("content") or ""):
                    target["content"] = next_content
                    needs_reingest = True
            if refresh_interval_hours is not None:
                interval = max(0, int(refresh_interval_hours or 0))
                if interval != int(target.get("refresh_interval_hours") or 0):
                    target["refresh_interval_hours"] = interval
                    if target.get("status") == "ingested":
                        target["next_refresh_at_ms"] = _next_refresh_at_ms(interval)

            if needs_reingest:
                target["status"] = "registered"
                target["chunk_count"] = 0
                target["fact_count"] = 0
                target["last_error"] = ""
                target["metadata"] = {}
                target.pop("ingested_at_ms", None)
                target["next_refresh_at_ms"] = None
                self._delete_chunks_unlocked(doc_id)
                self._delete_facts_unlocked(doc_id)

            target["updated_at_ms"] = _now_ms()
            self._write_manifest_unlocked(data)
            return dict(target)

    def ingest_document(self, doc_id: str) -> dict[str, Any]:
        if not self.is_valid_doc_id(doc_id):
            raise ValueError("invalid doc_id")
        with self._lock:
            data = self._read_manifest_unlocked()
            target = next((item for item in data["documents"] if item.get("doc_id") == doc_id), None)
            if not target:
                raise KeyError("document not found")

            now = _now_ms()
            existing_meta = dict(target.get("metadata") or {})
            try:
                raw = self._load_document_content(target)
            except _RemoteNotModified as exc:
                target["status"] = "ingested"
                target["last_error"] = ""
                target["checked_at_ms"] = now
                target["metadata"] = {**existing_meta, **exc.metadata, "refresh_state": "not_modified"}
                target["next_refresh_at_ms"] = _next_refresh_at_ms(int(target.get("refresh_interval_hours") or 0), now_ms=now)
                target["updated_at_ms"] = now
                self._write_manifest_unlocked(data)
                return dict(target)
            try:
                text = str(raw.get("text") or "")
                detected_title = str(raw.get("title") or "")
                detected_meta = dict(raw.get("metadata") or {})
                if not str(target.get("title") or "").strip() or str(target.get("title") or "") == str(target.get("source") or ""):
                    target["title"] = (detected_title or str(target.get("title") or "")).strip()[:200]
                existing_hash = str(existing_meta.get("content_hash") or "")
                next_hash = str(detected_meta.get("content_hash") or "")
                if (
                    target.get("status") == "ingested"
                    and int(target.get("chunk_count") or 0) > 0
                    and existing_hash
                    and next_hash
                    and existing_hash == next_hash
                ):
                    target["last_error"] = ""
                    target["checked_at_ms"] = now
                    target["metadata"] = {**existing_meta, **detected_meta, "refresh_state": "unchanged"}
                    target["next_refresh_at_ms"] = _next_refresh_at_ms(int(target.get("refresh_interval_hours") or 0), now_ms=now)
                    target["updated_at_ms"] = now
                    self._write_manifest_unlocked(data)
                    return dict(target)
                pages = list(raw.get("pages") or [])
                chunks = self._chunk_pdf_pages(pages, title=str(target.get("title") or "")) if pages else self._chunk_text(text, title=str(target.get("title") or ""))
                facts = self._extract_pdf_page_facts(pages, title=str(target.get("title") or "")) if pages else self._extract_facts(text, title=str(target.get("title") or ""))
                target["status"] = "ingested"
                target["chunk_count"] = len(chunks)
                target["fact_count"] = len(facts)
                target["last_error"] = ""
                target["metadata"] = {**detected_meta, "refresh_state": "updated"}
                target["ingested_at_ms"] = now
                target["checked_at_ms"] = now
                target["next_refresh_at_ms"] = _next_refresh_at_ms(int(target.get("refresh_interval_hours") or 0), now_ms=target["ingested_at_ms"])
            except Exception as exc:
                target["status"] = "error"
                target["chunk_count"] = 0
                target["fact_count"] = 0
                target["last_error"] = str(exc)[:500]
                target["metadata"] = {}
                target["updated_at_ms"] = _now_ms()
                self._write_manifest_unlocked(data)
                raise

            target["updated_at_ms"] = _now_ms()
            self._write_manifest_unlocked(data)
            self._replace_chunks_unlocked(doc_id, chunks)
            self._replace_facts_unlocked(doc_id, facts)
            return dict(target)

    def reingest_all(self) -> dict[str, Any]:
        docs = self.list_documents()
        updated = 0
        failed = 0
        errors: list[dict[str, str]] = []
        for doc in docs:
            try:
                self.ingest_document(str(doc.get("doc_id") or ""))
                updated += 1
            except Exception as exc:
                failed += 1
                errors.append({
                    "doc_id": str(doc.get("doc_id") or ""),
                    "error": str(exc)[:200],
                })
        return {
            "updated": updated,
            "failed": failed,
            "errors": errors,
        }

    def refresh_due(self, *, limit: int = 20) -> dict[str, Any]:
        docs = [doc for doc in self.list_documents() if self._is_due_document(doc)][:max(1, int(limit))]
        updated = 0
        failed = 0
        errors: list[dict[str, str]] = []
        for doc in docs:
            try:
                self.ingest_document(str(doc.get("doc_id") or ""))
                updated += 1
            except Exception as exc:
                failed += 1
                errors.append({
                    "doc_id": str(doc.get("doc_id") or ""),
                    "error": str(exc)[:200],
                })
        return {
            "updated": updated,
            "failed": failed,
            "errors": errors,
        }

    def search(
        self,
        query: str,
        *,
        limit: int = 5,
        source_type: str | None = None,
        result_type: str | None = None,
    ) -> list[dict[str, Any]]:
        query = str(query or "").strip()
        if not query:
            return []
        tokens = [tok for tok in re.split(r"[^\w\u4e00-\u9fff]+", query.lower()) if tok]
        if not tokens:
            return []
        with self._lock:
            chunks = self._read_chunks_unlocked()
            facts = self._read_facts_unlocked()
            documents = {item["doc_id"]: item for item in self._read_manifest_unlocked()["documents"]}

        ranked: list[tuple[int, dict[str, Any]]] = []
        for chunk in chunks:
            text = str(chunk.get("text") or "")
            doc = documents.get(str(chunk.get("doc_id") or ""), {})
            score = self._score_search_candidate(
                query=query,
                tokens=tokens,
                body=text,
                title=str(doc.get("title") or ""),
                source=str(doc.get("source") or ""),
                result_type="chunk",
                updated_at_ms=int(doc.get("updated_at_ms") or 0),
            )
            if score <= 0:
                continue
            if source_type and str(doc.get("source_type") or "") != source_type:
                continue
            if result_type and result_type != "chunk":
                continue
            ranked.append((score, {**chunk, "result_type": "chunk"}))
        for fact in facts:
            claim = str(fact.get("claim") or "")
            doc = documents.get(str(fact.get("doc_id") or ""), {})
            score = self._score_search_candidate(
                query=query,
                tokens=tokens,
                body=claim,
                title=str(doc.get("title") or ""),
                source=str(doc.get("source") or ""),
                result_type="fact",
                updated_at_ms=int(doc.get("updated_at_ms") or 0),
            )
            if score <= 0:
                continue
            if source_type and str(doc.get("source_type") or "") != source_type:
                continue
            if result_type and result_type != "fact":
                continue
            ranked.append((score, {**fact, "result_type": "fact"}))

        ranked.sort(
            key=lambda item: (
                item[0],
                int(documents.get(str(item[1].get("doc_id") or ""), {}).get("updated_at_ms") or 0),
            ),
            reverse=True,
        )
        results: list[dict[str, Any]] = []
        seen_per_doc: dict[str, int] = {}
        for score, chunk in ranked:
            doc_id = str(chunk.get("doc_id") or "")
            if doc_id:
                seen = seen_per_doc.get(doc_id, 0)
                if seen >= 2:
                    continue
                seen_per_doc[doc_id] = seen + 1
            doc = documents.get(str(chunk.get("doc_id") or ""), {})
            result_type = str(chunk.get("result_type") or "chunk")
            text = str(chunk.get("text") or chunk.get("claim") or "")
            page_label = str(chunk.get("page_label") or "").strip()
            doc_meta = dict(doc.get("metadata") or {})
            if not page_label and str(doc_meta.get("extractor") or "").startswith("pdf-") and int(doc_meta.get("page_count") or 0) == 1:
                page_label = "p.1"
            results.append({
                "doc_id": chunk.get("doc_id"),
                "chunk_id": chunk.get("chunk_id"),
                "fact_id": chunk.get("fact_id"),
                "result_type": result_type,
                "title": doc.get("title") or chunk.get("title") or "",
                "source": doc.get("source") or "",
                "source_type": doc.get("source_type") or "",
                "score": score,
                "snippet": text[:280],
                "page_start": chunk.get("page_start"),
                "page_end": chunk.get("page_end"),
                "page_label": page_label,
            })
            if len(results) >= max(1, int(limit)):
                break
        return results

    @staticmethod
    def _score_search_candidate(
        *,
        query: str,
        tokens: list[str],
        body: str,
        title: str,
        source: str,
        result_type: str,
        updated_at_ms: int,
    ) -> int:
        query_lower = query.lower()
        body_lower = body.lower()
        title_lower = title.lower()
        source_lower = source.lower()
        score = 0

        if query_lower in body_lower:
            score += 55 if result_type == "chunk" else 80
        if query_lower == title_lower and query_lower:
            score += 260
        if query_lower in title_lower:
            score += 120
        if query_lower in source_lower:
            score += 15

        if tokens and all(token in title_lower for token in tokens):
            score += 50
        if tokens and all(token in body_lower for token in tokens):
            score += 20

        for token in tokens:
            body_hits = min(body_lower.count(token), 3)
            title_hits = min(title_lower.count(token), 2)
            source_hits = min(source_lower.count(token), 1)
            score += body_hits * (2 if result_type == "fact" else 1)
            score += title_hits * 3
            score += source_hits

        # Prefer concise facts/chunks once relevance is established.
        body_len = max(len(body.strip()), 1)
        if body_len <= 240:
            score += 6
        elif body_len <= 800:
            score += 3

        # Light recency boost without overwhelming lexical relevance.
        if updated_at_ms > 0:
            age_ms = max(_now_ms() - updated_at_ms, 0)
            if age_ms <= 24 * 60 * 60 * 1000:
                score += 4
            elif age_ms <= 7 * 24 * 60 * 60 * 1000:
                score += 2
        return score

    def list_chunks(self, doc_id: str) -> list[dict[str, Any]]:
        if not self.is_valid_doc_id(doc_id):
            raise ValueError("invalid doc_id")
        with self._lock:
            chunks = [dict(item) for item in self._read_chunks_unlocked() if item.get("doc_id") == doc_id]
        chunks.sort(key=lambda item: str(item.get("chunk_id") or ""))
        return chunks

    def list_facts(self, doc_id: str) -> list[dict[str, Any]]:
        if not self.is_valid_doc_id(doc_id):
            raise ValueError("invalid doc_id")
        with self._lock:
            facts = [dict(item) for item in self._read_facts_unlocked() if item.get("doc_id") == doc_id]
        facts.sort(key=lambda item: str(item.get("fact_id") or ""))
        return facts

    @staticmethod
    def _is_due_document(document: dict[str, Any], *, now_ms: int | None = None) -> bool:
        next_refresh = int(document.get("next_refresh_at_ms") or 0)
        interval = int(document.get("refresh_interval_hours") or 0)
        if interval <= 0 or next_refresh <= 0:
            return False
        return next_refresh <= (now_ms if now_ms is not None else _now_ms())

    @staticmethod
    def format_for_context(results: list[dict[str, Any]]) -> str:
        if not results:
            return ""
        parts = ["## Relevant Knowledge (auto-loaded)"]
        for item in results:
            title = str(item.get("title") or item.get("doc_id") or "knowledge")
            source = str(item.get("source") or "—")
            snippet = str(item.get("snippet") or "").strip()
            result_type = str(item.get("result_type") or "chunk")
            page_label = str(item.get("page_label") or "").strip()
            page_line = f"\n- Page: {page_label}" if page_label else ""
            parts.append(f"\n### {title}\n- Source: {source}\n- Type: {result_type}{page_line}\n- Snippet: {snippet}")
        return "\n".join(parts)

    def _load_document_content(self, document: dict[str, Any]) -> dict[str, Any]:
        source_type = str(document.get("source_type") or "")
        if source_type == "manual":
            content = str(document.get("content") or document.get("note") or "")
            if not content.strip():
                raise ValueError("manual content is empty")
            return {
                "text": content,
                "title": str(document.get("title") or ""),
                "metadata": {
                    "extractor": "manual",
                    "content_bytes": len(content.encode("utf-8")),
                    "content_hash": hashlib.sha1(content.encode("utf-8")).hexdigest()[:12],
                },
            }
        if source_type == "file":
            source = str(document.get("source") or "")
            path = Path(source).expanduser()
            if not path.exists():
                raise FileNotFoundError("file not found")
            suffix = path.suffix.lower()
            if suffix == ".pdf":
                content = extract_pdf_content(path)
                meta = dict(content.get("metadata") or {})
                return {
                    "text": str(content.get("text") or ""),
                    "title": str(meta.get("title") or path.stem),
                    "metadata": meta,
                    "pages": list(content.get("pages") or []),
                }
            raw_bytes = path.read_bytes()
            content = raw_bytes.decode("utf-8", errors="ignore")
            if suffix in {".html", ".htm"}:
                title = self._extract_html_title(content) or path.stem
                return {
                    "text": self._html_to_text(content),
                    "title": title,
                    "metadata": {
                        "extractor": "html-file",
                        "path": str(path),
                        "suffix": suffix,
                        "content_bytes": len(raw_bytes),
                        "content_hash": _sha1_hexdigest(raw_bytes),
                    },
                }
            return {
                "text": content,
                "title": path.stem,
                "metadata": {
                    "extractor": "text-file",
                    "path": str(path),
                    "suffix": suffix or "(none)",
                    "content_bytes": len(raw_bytes),
                    "content_hash": _sha1_hexdigest(raw_bytes),
                },
            }
        if source_type == "url":
            source = str(document.get("source") or "")
            existing_meta = dict(document.get("metadata") or {})
            headers = {"User-Agent": "LemonClawKnowledge/1.0"}
            etag = str(existing_meta.get("etag") or "").strip()
            last_modified = str(existing_meta.get("last_modified") or "").strip()
            if etag:
                headers["If-None-Match"] = etag
            if last_modified:
                headers["If-Modified-Since"] = last_modified
            req = Request(source, headers=headers)
            try:
                with urlopen(req, timeout=10) as response:
                    raw_bytes = response.read()
                    content_type = str(response.headers.get("Content-Type") or "").lower()
                    etag = str(response.headers.get("ETag") or etag).strip()
                    last_modified = str(response.headers.get("Last-Modified") or last_modified).strip()
            except HTTPError as exc:
                if exc.code == 304:
                    raise _RemoteNotModified({
                        "extractor": str(existing_meta.get("extractor") or "url-html"),
                        "source_url": source,
                        "content_bytes": int(existing_meta.get("content_bytes") or 0),
                        "content_hash": str(existing_meta.get("content_hash") or ""),
                        "etag": etag,
                        "last_modified": last_modified,
                    }) from exc
                raise
            if self._is_pdf_url_source(source, content_type):
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                    tmp.write(raw_bytes)
                    tmp_path = Path(tmp.name)
                try:
                    content = extract_pdf_content(tmp_path)
                finally:
                    tmp_path.unlink(missing_ok=True)
                meta = dict(content.get("metadata") or {})
                meta.update({
                    "extractor": str(meta.get("extractor") or "pdf-url"),
                    "source_url": source,
                    "content_bytes": len(raw_bytes),
                    "content_hash": _sha1_hexdigest(raw_bytes),
                    "etag": etag,
                    "last_modified": last_modified,
                    "content_type": content_type or "application/pdf",
                })
                return {
                    "text": str(content.get("text") or ""),
                    "title": str(meta.get("title") or document.get("title") or source),
                    "metadata": meta,
                    "pages": list(content.get("pages") or []),
                }
            raw = raw_bytes.decode("utf-8", errors="ignore")
            title = self._extract_html_title(raw) or str(document.get("title") or source)
            text = self._html_to_text(raw)
            if not text:
                raise ValueError("url content is empty")
            return {
                "text": text,
                "title": title,
                "metadata": {
                    "extractor": "url-html",
                    "source_url": source,
                    "content_bytes": len(raw_bytes),
                    "content_hash": _sha1_hexdigest(raw_bytes),
                    "etag": etag,
                    "last_modified": last_modified,
                    "content_type": content_type,
                },
            }
        raise ValueError("invalid source_type")

    @staticmethod
    def _is_pdf_url_source(source: str, content_type: str) -> bool:
        lowered = str(source or "").split("?", 1)[0].lower()
        if lowered.endswith(".pdf"):
            return True
        return "application/pdf" in str(content_type or "").lower()

    @staticmethod
    def _extract_html_title(raw: str) -> str:
        match = _TITLE_RE.search(raw or "")
        if not match:
            return ""
        return _WHITESPACE_RE.sub(" ", unescape(match.group(1))).strip()[:200]

    @staticmethod
    def _html_to_text(raw: str) -> str:
        raw = re.sub(r"<script[\s\S]*?</script>", " ", raw, flags=re.IGNORECASE)
        raw = re.sub(r"<style[\s\S]*?</style>", " ", raw, flags=re.IGNORECASE)
        text = unescape(_TAG_RE.sub(" ", raw))
        return _WHITESPACE_RE.sub(" ", text).strip()

    @staticmethod
    def _extract_pdf_text(path: Path) -> tuple[str, dict[str, Any]]:
        content = extract_pdf_content(path)
        return str(content.get("text") or ""), dict(content.get("metadata") or {})

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

    def _chunk_pdf_pages(self, pages: list[str], *, title: str = "", size: int = 1200) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for page_index, raw_page in enumerate(pages, 1):
            page_text = str(raw_page or "").strip()
            if not page_text:
                continue
            page_chunks = self._chunk_text(page_text, title=title, size=size)
            for idx, chunk in enumerate(page_chunks):
                output.append({
                    **chunk,
                    "chunk_id": f"page_{page_index:03d}_chunk_{idx}",
                    "page_start": page_index,
                    "page_end": page_index,
                    "page_label": f"p.{page_index}",
                })
        if output:
            return output
        merged = "\n\n".join(str(page or "").strip() for page in pages if str(page or "").strip())
        return self._chunk_text(merged, title=title, size=size)

    def _extract_facts(self, text: str, *, title: str = "", limit: int = 12) -> list[dict[str, Any]]:
        normalized = _WHITESPACE_RE.sub(" ", text).strip()
        if not normalized:
            return []
        candidates = _SENTENCE_SPLIT_RE.split(normalized)
        if len(candidates) == 1:
            candidates = re.split(r"[;\n]+", normalized)
        output: list[dict[str, Any]] = []
        seen: set[str] = set()
        for idx, candidate in enumerate(candidates):
            claim = candidate.strip(" -\t\r\n")
            if len(claim) < 24 or len(claim) > 280:
                continue
            lowered = claim.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            output.append({
                "fact_id": f"fact_{idx}",
                "title": title,
                "claim": claim,
            })
            if len(output) >= limit:
                break
        return output

    def _extract_pdf_page_facts(self, pages: list[str], *, title: str = "", limit: int = 12) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        seen: set[str] = set()
        for page_index, raw_page in enumerate(pages, 1):
            if len(output) >= limit:
                break
            page_facts = self._extract_facts(str(raw_page or ""), title=title, limit=limit)
            for item in page_facts:
                claim = str(item.get("claim") or "").strip()
                lowered = claim.lower()
                if not claim or lowered in seen:
                    continue
                seen.add(lowered)
                output.append({
                    **item,
                    "fact_id": f"page_{page_index:03d}_{item.get('fact_id')}",
                    "page_start": page_index,
                    "page_end": page_index,
                    "page_label": f"p.{page_index}",
                })
                if len(output) >= limit:
                    break
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
                "page_start": item.get("page_start"),
                "page_end": item.get("page_end"),
                "page_label": item.get("page_label") or "",
                "updated_at_ms": now,
            })
        self._write_chunks_unlocked({"version": 1, "chunks": data})

    def _delete_chunks_unlocked(self, doc_id: str) -> None:
        data = self._read_chunks_unlocked()
        next_chunks = [item for item in data if item.get("doc_id") != doc_id]
        self._write_chunks_unlocked({"version": 1, "chunks": next_chunks})

    def _read_facts_unlocked(self) -> list[dict[str, Any]]:
        if not self._facts.exists():
            return []
        try:
            raw = json.loads(self._facts.read_text(encoding="utf-8"))
        except Exception:
            return []
        return list(raw.get("facts") or [])

    def _replace_facts_unlocked(self, doc_id: str, facts: list[dict[str, Any]]) -> None:
        data = self._read_facts_unlocked()
        data = [item for item in data if item.get("doc_id") != doc_id]
        now = _now_ms()
        for item in facts:
            data.append({
                "doc_id": doc_id,
                "fact_id": item["fact_id"],
                "title": item.get("title") or "",
                "claim": item.get("claim") or "",
                "page_start": item.get("page_start"),
                "page_end": item.get("page_end"),
                "page_label": item.get("page_label") or "",
                "updated_at_ms": now,
            })
        self._write_facts_unlocked({"version": 1, "facts": data})

    def _delete_facts_unlocked(self, doc_id: str) -> None:
        data = self._read_facts_unlocked()
        next_facts = [item for item in data if item.get("doc_id") != doc_id]
        self._write_facts_unlocked({"version": 1, "facts": next_facts})

    def _write_facts_unlocked(self, payload: dict[str, Any]) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        self._facts.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

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
