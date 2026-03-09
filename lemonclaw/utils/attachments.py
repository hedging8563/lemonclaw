"""Attachment metadata, persistence, and preview helpers."""

from __future__ import annotations

import csv
import mimetypes
import shutil
import zipfile
from io import StringIO
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from lemonclaw.utils.helpers import ensure_dir, safe_filename


def _human_size(size: int | None) -> str:
    if size is None or size < 0:
        return "unknown"
    units = ["B", "KB", "MB", "GB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{int(value)} B"


def media_paths(media: list[Any] | None) -> list[str]:
    out: list[str] = []
    for item in media or []:
        if isinstance(item, str) and item:
            out.append(item)
        elif isinstance(item, dict) and isinstance(item.get("path"), str) and item.get("path"):
            out.append(str(item["path"]))
    seen: set[str] = set()
    deduped: list[str] = []
    for path in out:
        if path not in seen:
            seen.add(path)
            deduped.append(path)
    return deduped


def attachment_metadata(path: str | Path) -> dict[str, Any]:
    raw = str(path)
    p = Path(raw).expanduser()
    resolved = None
    exists = False
    size = None
    mime = None
    if raw.startswith(("http://", "https://")):
        filename = Path(raw.split("?", 1)[0]).name or raw
        return {
            "path": raw,
            "filename": filename,
            "suffix": Path(filename).suffix.lower(),
            "mime": None,
            "size": None,
            "exists": False,
        }
    try:
        resolved = p.resolve(strict=True)
        exists = resolved.is_file()
        if exists:
            size = resolved.stat().st_size
            mime = mimetypes.guess_type(str(resolved), strict=False)[0]
    except OSError:
        resolved = p.resolve(strict=False)
        mime = mimetypes.guess_type(str(p), strict=False)[0]
    filename = (resolved or p).name or raw
    return {
        "path": str(resolved or p),
        "filename": filename,
        "suffix": Path(filename).suffix.lower(),
        "mime": mime,
        "size": size,
        "exists": exists,
    }


def attachment_trigger_text(paths: list[str] | None) -> str:
    parts: list[str] = []
    for path in media_paths(paths):
        meta = attachment_metadata(path)
        filename = str(meta.get("filename") or "")
        suffix = str(meta.get("suffix") or "")
        mime = str(meta.get("mime") or "")
        if filename:
            parts.append(filename.lower())
        if suffix:
            parts.append(suffix.lower())
        if mime:
            parts.append(mime.lower())
    return " ".join(parts)


def format_attachment_inventory(paths: list[str] | None, *, heading: str = "Attached files") -> str:
    items = media_paths(paths)
    if not items:
        return ""
    lines = [f"[{heading}]"]
    for path in items:
        meta = attachment_metadata(path)
        filename = meta["filename"]
        mime = meta.get("mime") or "unknown"
        size = _human_size(meta.get("size"))
        lines.append(f"- {filename} | mime={mime} | size={size} | path={meta['path']}")
    return "\n".join(lines)


def append_attachment_inventory(content: str, media: list[Any] | None) -> str:
    inventory = format_attachment_inventory(media)
    if not inventory:
        return content
    if not content:
        return inventory
    return f"{content}\n\n{inventory}"


def rewrite_text_paths(text: str, mapping: dict[str, str]) -> str:
    if not text or not mapping:
        return text
    updated = text
    for old in sorted(mapping, key=len, reverse=True):
        updated = updated.replace(old, mapping[old])
    return updated


def rewrite_payload_paths(payload: Any, mapping: dict[str, str]) -> Any:
    if not mapping:
        return payload
    if isinstance(payload, str):
        return rewrite_text_paths(payload, mapping)
    if isinstance(payload, list):
        return [rewrite_payload_paths(item, mapping) for item in payload]
    if isinstance(payload, dict):
        return {key: rewrite_payload_paths(value, mapping) for key, value in payload.items()}
    return payload


def session_attachment_dir(workspace: Path, session_key: str, *, ensure: bool = True) -> Path:
    safe_key = safe_filename(session_key.replace(":", "_")) or "session"
    path = workspace / "attachments" / safe_key
    return ensure_dir(path) if ensure else path


def _unique_destination(directory: Path, filename: str, index: int) -> Path:
    safe_name = safe_filename(Path(filename).name) or f"attachment_{index}"
    stem = Path(safe_name).stem[:80] or f"attachment_{index}"
    suffix = Path(safe_name).suffix[:24]
    candidate = directory / f"{index:02d}_{stem}{suffix}"
    if not candidate.exists():
        return candidate
    n = 2
    while True:
        candidate = directory / f"{index:02d}_{stem}_{n}{suffix}"
        if not candidate.exists():
            return candidate
        n += 1


def persist_session_attachments(workspace: Path, session_key: str, paths: list[str] | None) -> tuple[list[str], dict[str, str]]:
    items = media_paths(paths)
    if not items:
        return [], {}
    target_dir = session_attachment_dir(workspace, session_key)
    persisted: list[str] = []
    mapping: dict[str, str] = {}
    copied: dict[str, str] = {}
    for index, raw in enumerate(items, 1):
        if raw.startswith(("http://", "https://")):
            persisted.append(raw)
            continue
        try:
            source = Path(raw).expanduser().resolve(strict=True)
        except OSError:
            continue
        source_str = str(source)
        if target_dir == source or target_dir in source.parents:
            persisted.append(source_str)
            mapping[raw] = source_str
            mapping[source_str] = source_str
            continue
        if source_str in copied:
            dest_str = copied[source_str]
            persisted.append(dest_str)
            mapping[raw] = dest_str
            mapping[source_str] = dest_str
            continue
        dest = _unique_destination(target_dir, source.name, index)
        shutil.copy2(source, dest)
        dest_str = str(dest)
        copied[source_str] = dest_str
        persisted.append(dest_str)
        mapping[raw] = dest_str
        mapping[source_str] = dest_str
    return persisted, mapping


_TEXT_EXTS = {".txt", ".md", ".json", ".yaml", ".yml", ".csv", ".tsv", ".log", ".py", ".js", ".ts", ".html", ".xml"}


def _preview_delimited(text: str, *, delimiter: str, max_rows: int) -> str:
    reader = csv.reader(StringIO(text), delimiter=delimiter)
    rows: list[str] = []
    for idx, row in enumerate(reader, 1):
        rows.append(" | ".join(cell.strip() for cell in row))
        if idx >= max_rows:
            break
    return "\n".join(rows)


_XLSX_NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pkgrel": "http://schemas.openxmlformats.org/package/2006/relationships",
}


def _xlsx_col_index(cell_ref: str) -> int:
    letters = "".join(ch for ch in cell_ref if ch.isalpha()).upper()
    value = 0
    for ch in letters:
        value = value * 26 + (ord(ch) - 64)
    return max(value - 1, 0)


def _xlsx_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    values: list[str] = []
    for si in root.findall("main:si", _XLSX_NS):
        text = "".join(node.text or "" for node in si.findall(".//main:t", _XLSX_NS))
        values.append(text)
    return values


def _xlsx_sheet_targets(zf: zipfile.ZipFile) -> list[tuple[str, str]]:
    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rel_map = {
        rel.attrib.get("Id"): rel.attrib.get("Target", "")
        for rel in rels.findall("pkgrel:Relationship", _XLSX_NS)
    }
    targets: list[tuple[str, str]] = []
    for sheet in workbook.findall("main:sheets/main:sheet", _XLSX_NS):
        name = sheet.attrib.get("name") or "Sheet"
        rel_id = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        target = rel_map.get(rel_id, "")
        if target:
            targets.append((name, f"xl/{target.lstrip('/')}"))
    return targets


def _xlsx_preview(path: Path, *, max_rows: int, max_sheets: int = 3) -> str:
    with zipfile.ZipFile(path) as zf:
        shared = _xlsx_shared_strings(zf)
        sheet_targets = _xlsx_sheet_targets(zf)
        if not sheet_targets:
            return "Workbook has no readable sheets."
        parts: list[str] = []
        for sheet_name, target in sheet_targets[:max_sheets]:
            rows: list[str] = []
            root = ET.fromstring(zf.read(target))
            for row in root.findall("main:sheetData/main:row", _XLSX_NS):
                values: list[str] = []
                last_index = -1
                for cell in row.findall("main:c", _XLSX_NS):
                    col_index = _xlsx_col_index(cell.attrib.get("r", "A1"))
                    while last_index + 1 < col_index:
                        values.append("")
                        last_index += 1
                    cell_type = cell.attrib.get("t")
                    value = ""
                    if cell_type == "inlineStr":
                        value = "".join(t.text or "" for t in cell.findall(".//main:t", _XLSX_NS))
                    else:
                        raw_value = cell.findtext("main:v", default="", namespaces=_XLSX_NS)
                        if cell_type == "s":
                            try:
                                value = shared[int(raw_value)]
                            except Exception:
                                value = raw_value
                        else:
                            value = raw_value
                    values.append(value.strip())
                    last_index = col_index
                rows.append(" | ".join(values).rstrip())
                if len(rows) >= max_rows:
                    break
            preview = "\n".join(rows) if rows else "(empty sheet)"
            parts.append(f"[Sheet] {sheet_name}\n{preview}")
        return "\n\n".join(parts)


_DOCX_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def _docx_preview(path: Path, *, max_paragraphs: int, max_chars: int) -> str:
    with zipfile.ZipFile(path) as zf:
        root = ET.fromstring(zf.read("word/document.xml"))
    paragraphs: list[str] = []
    for para in root.findall(".//w:p", _DOCX_NS):
        text = "".join(node.text or "" for node in para.findall(".//w:t", _DOCX_NS)).strip()
        if text:
            paragraphs.append(text)
        if len(paragraphs) >= max_paragraphs:
            break
    if not paragraphs:
        return "Document has no extractable paragraphs."
    preview = "\n".join(paragraphs)
    if len(preview) > max_chars:
        preview = preview[:max_chars] + "..."
    return preview


def _load_pypdf_reader():
    try:
        from pypdf import PdfReader
        return PdfReader
    except Exception:
        return None


def _pdf_preview(path: Path, *, max_pages: int, max_chars: int) -> str:
    pdf_reader_cls = _load_pypdf_reader()
    if pdf_reader_cls is None:
        return "PDF preview unavailable because pypdf is not installed."
    reader = pdf_reader_cls(str(path))
    parts: list[str] = []
    for index, page in enumerate(reader.pages[:max_pages], 1):
        try:
            raw = page.extract_text() or ""
        except Exception:
            raw = ""
        normalized = "\n".join(line.strip() for line in raw.splitlines() if line.strip()) or "(no extractable text on this page)"
        parts.append(f"[Page {index}]\n{normalized}")
        if len("\n\n".join(parts)) >= max_chars:
            break
    if len(reader.pages) > max_pages:
        parts.append(f"... and {len(reader.pages) - max_pages} more pages")
    return "\n\n".join(parts)[:max_chars]


def inspect_attachment(path: str, *, max_chars: int = 12000, max_rows: int = 20, max_entries: int = 100) -> str:
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        return f"Error: File not found: {path}"
    if not resolved.is_file():
        return f"Error: Not a file: {path}"

    meta = attachment_metadata(resolved)
    header = f"File: {meta['filename']}\nPath: {resolved}\nMIME: {meta.get('mime') or 'unknown'}\nSize: {_human_size(meta.get('size'))}"
    suffix = str(meta.get("suffix") or "").lower()

    try:
        if suffix in {".csv", ".tsv"}:
            raw = resolved.read_text(encoding="utf-8", errors="replace")
            preview = _preview_delimited(raw, delimiter="," if suffix == ".csv" else "\t", max_rows=max_rows)
            return f"{header}\n\nPreview:\n{preview[:max_chars]}"
        if suffix in {".xlsx", ".xlsm"}:
            preview = _xlsx_preview(resolved, max_rows=max_rows)
            return f"{header}\n\nWorkbook preview:\n{preview[:max_chars]}"
        if suffix == ".docx":
            preview = _docx_preview(resolved, max_paragraphs=max_rows, max_chars=max_chars)
            return f"{header}\n\nDocument preview:\n{preview}"
        if suffix == ".pdf":
            preview = _pdf_preview(resolved, max_pages=max_rows, max_chars=max_chars)
            return f"{header}\n\nPDF preview:\n{preview}"
        if suffix == ".zip":
            with zipfile.ZipFile(resolved) as zf:
                infos = zf.infolist()
                lines = [f"- {info.filename} ({_human_size(info.file_size)})" for info in infos[:max_entries]]
                if len(infos) > max_entries:
                    lines.append(f"... and {len(infos) - max_entries} more entries")
            return f"{header}\n\nArchive entries:\n" + "\n".join(lines)
        mime = str(meta.get("mime") or "")
        if suffix in _TEXT_EXTS or mime.startswith("text/") or mime.endswith("json") or mime.endswith("xml"):
            content = resolved.read_text(encoding="utf-8", errors="replace")
            return f"{header}\n\nContent:\n{content[:max_chars]}"
        return f"{header}\n\nBinary attachment detected. Use dedicated tools or shell commands for deeper inspection."
    except zipfile.BadZipFile:
        return f"Error: Invalid ZIP/XLSX archive: {path}"
    except Exception as exc:
        return f"Error reading attachment: {exc}"
