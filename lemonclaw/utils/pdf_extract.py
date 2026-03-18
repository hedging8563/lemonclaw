"""Shared PDF extraction helpers for previews and knowledge ingestion."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


def _normalize_spaces(text: str) -> str:
    return " ".join((text or "").split()).strip()


def _sha1_hexdigest(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()[:12]


def _pypdf_available() -> bool:
    try:
        import pypdf  # noqa: F401
        return True
    except Exception:
        return False


def _pdfplumber_available() -> bool:
    try:
        import pdfplumber  # noqa: F401
        return True
    except Exception:
        return False


def infer_pdf_title(text: str, *, fallback: str = "") -> str:
    for line in text.splitlines():
        candidate = _normalize_spaces(line)
        if len(candidate) >= 4:
            return candidate[:200]
    return fallback[:200]


def extract_pdf_content(path: Path) -> dict[str, Any]:
    errors: list[str] = []
    if _pypdf_available():
        try:
            return _extract_pdf_with_pypdf(path)
        except Exception as exc:
            errors.append(f"pypdf:{exc}")
    if _pdfplumber_available():
        try:
            return _extract_pdf_with_pdfplumber(path)
        except Exception as exc:
            errors.append(f"pdfplumber:{exc}")
    if errors:
        raise RuntimeError("; ".join(errors)[:500])
    raise RuntimeError("pypdf or pdfplumber is required for pdf extraction")


def preview_pdf(path: Path, *, max_pages: int, max_chars: int) -> str:
    content = extract_pdf_content(path)
    pages = list(content.get("pages") or [])
    parts: list[str] = []
    for index, raw in enumerate(pages[:max_pages], 1):
        normalized = "\n".join(line.strip() for line in str(raw or "").splitlines() if line.strip())
        normalized = normalized or "(no extractable text on this page)"
        parts.append(f"[Page {index}]\n{normalized}")
        if len("\n\n".join(parts)) >= max_chars:
            break
    if len(pages) > max_pages:
        parts.append(f"... and {len(pages) - max_pages} more pages")
    return "\n\n".join(parts)[:max_chars]


def _extract_pdf_with_pypdf(path: Path) -> dict[str, Any]:
    from pypdf import PdfReader

    raw_bytes = path.read_bytes()
    reader = PdfReader(str(path))
    pages_obj = list(getattr(reader, "pages", []) or [])
    pages = [(page.extract_text() or "") for page in pages_obj]
    text = "\n\n".join(part.strip() for part in pages if part.strip())
    if not text:
        raise ValueError("pdf content is empty")
    metadata = getattr(reader, "metadata", {}) or {}
    title = str(metadata.get("/Title") or "").strip()
    return {
        "text": text,
        "pages": pages,
        "metadata": {
            "extractor": "pdf-pypdf",
            "path": str(path),
            "suffix": ".pdf",
            "page_count": len(pages_obj),
            "title": title or infer_pdf_title(text, fallback=path.stem),
            "content_bytes": path.stat().st_size,
            "content_hash": _sha1_hexdigest(raw_bytes),
        },
    }


def _extract_pdf_with_pdfplumber(path: Path) -> dict[str, Any]:
    import pdfplumber

    raw_bytes = path.read_bytes()
    with pdfplumber.open(str(path)) as pdf:
        pages = [(page.extract_text() or "") for page in pdf.pages]
        metadata = dict(getattr(pdf, "metadata", {}) or {})
        page_count = len(pdf.pages)
    text = "\n\n".join(part.strip() for part in pages if part.strip())
    if not text:
        raise ValueError("pdf content is empty")
    title = str(metadata.get("Title") or metadata.get("/Title") or "").strip()
    return {
        "text": text,
        "pages": pages,
        "metadata": {
            "extractor": "pdf-pdfplumber",
            "path": str(path),
            "suffix": ".pdf",
            "page_count": page_count,
            "title": title or infer_pdf_title(text, fallback=path.stem),
            "content_bytes": path.stat().st_size,
            "content_hash": _sha1_hexdigest(raw_bytes),
        },
    }
