"""File system tools: read, inspect attachments, write, edit."""

import base64
import difflib
from pathlib import Path
from typing import Any

from lemonclaw.agent.tools.base import Tool
from lemonclaw.config.defaults import DEFAULT_VISION_MODEL
from lemonclaw.utils.attachments import attachment_metadata, inspect_attachment


def _resolve_path(path: str, workspace: Path | None = None) -> Path:
    """Resolve path against workspace (if relative)."""
    p = Path(path).expanduser()
    if not p.is_absolute() and workspace:
        p = workspace / p
    resolved = p.resolve()
    return resolved


def _is_image_attachment(path: Path) -> bool:
    meta = attachment_metadata(path)
    mime = str(meta.get("mime") or "")
    return mime.startswith("image/")


def _image_tool_hint(path: str) -> str:
    return (
        f"Error: {path} is an image attachment. "
        "Use analyze_image for screenshots/photos, or rely on the model's built-in vision input instead."
    )


class ReadFileTool(Tool):
    """Tool to read file contents."""

    def __init__(self, workspace: Path | None = None):
        self._workspace = workspace

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return (
            "Read the contents of a text file at the given path. "
            "Returns text content up to 512KB (truncated for larger files). "
            "Use this for code, configs, and logs. Do not use it for screenshots, photos, or image attachments; "
            "use analyze_image for images and read_attachment for PDFs/docs/spreadsheets."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The file path to read"
                }
            },
            "required": ["path"]
        }

    _MAX_READ_BYTES = 512 * 1024  # 512KB

    async def execute(self, path: str, **kwargs: Any) -> str:
        try:
            file_path = _resolve_path(path, self._workspace)
            if not file_path.exists():
                return f"Error: File not found: {path}"
            if not file_path.is_file():
                return f"Error: Not a file: {path}"
            if _is_image_attachment(file_path):
                return _image_tool_hint(path)

            size = file_path.stat().st_size
            if size > self._MAX_READ_BYTES:
                content = file_path.read_bytes()[:self._MAX_READ_BYTES].decode("utf-8", errors="replace")
                return content + f"\n... (file truncated at {self._MAX_READ_BYTES // 1024}KB, total {size // 1024}KB)"
            content = file_path.read_text(encoding="utf-8")
            return content
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error reading file: {str(e)}"


class ReadAttachmentTool(Tool):
    """Tool to inspect common attachment formats."""

    def __init__(self, workspace: Path | None = None):
        self._workspace = workspace

    @property
    def name(self) -> str:
        return "read_attachment"

    @property
    def description(self) -> str:
        return (
            "Inspect a non-image attachment by path. Supports text files, CSV/TSV, XLSX workbook previews, "
            "DOCX paragraph previews, PDF text extraction, and ZIP archive listings. "
            "Image files are not OCRed here; use analyze_image for screenshots/photos. "
            "For arbitrary binary files, returns metadata and guidance."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The attachment path to inspect"},
                "max_rows": {"type": "integer", "description": "Preview rows for CSV/XLSX", "minimum": 1, "maximum": 100},
                "max_chars": {"type": "integer", "description": "Maximum characters to return", "minimum": 200, "maximum": 50000},
            },
            "required": ["path"],
        }

    async def execute(self, path: str, max_rows: int = 20, max_chars: int = 12000, **kwargs: Any) -> str:
        try:
            file_path = _resolve_path(path, self._workspace)
            if _is_image_attachment(file_path):
                return _image_tool_hint(path)
            return inspect_attachment(str(file_path), max_rows=max_rows, max_chars=max_chars)
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error reading attachment: {str(e)}"


class AnalyzeImageTool(Tool):
    """Tool to analyze image attachments with a vision-capable model."""

    def __init__(self, provider: Any, workspace: Path | None = None, default_model: str = DEFAULT_VISION_MODEL):
        self._provider = provider
        self._workspace = workspace
        self._default_model = default_model

    @property
    def name(self) -> str:
        return "analyze_image"

    @property
    def description(self) -> str:
        return (
            "Analyze an image attachment by path using a vision-capable model. "
            "Use this for screenshots, scanned documents, photos, and extracting visible text from images. "
            "Prefer this over read_file/read_attachment for image files."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The image path to inspect"},
                "instruction": {"type": "string", "description": "Optional analysis instruction (e.g. extract all text, summarize the screenshot)"},
                "model": {"type": "string", "description": "Optional vision model override"},
                "max_tokens": {"type": "integer", "description": "Maximum tokens in the analysis result", "minimum": 100, "maximum": 8000},
            },
            "required": ["path"],
        }

    async def execute(
        self,
        path: str,
        instruction: str = "",
        model: str | None = None,
        max_tokens: int = 2000,
        **kwargs: Any,
    ) -> str:
        try:
            file_path = _resolve_path(path, self._workspace)
            if not file_path.exists():
                return f"Error: File not found: {path}"
            if not file_path.is_file():
                return f"Error: Not a file: {path}"
            if not _is_image_attachment(file_path):
                return f"Error: {path} is not an image attachment. Use read_attachment for non-image files."

            meta = attachment_metadata(file_path)
            mime = str(meta.get("mime") or "application/octet-stream")
            data_url = f"data:{mime};base64,{base64.b64encode(file_path.read_bytes()).decode()}"
            prompt = (instruction or "").strip() or (
                "Read the image carefully. First extract all clearly visible text verbatim in reading order. "
                "Then provide a short summary if helpful."
            )
            response = await self._provider.chat(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a precise vision assistant. Extract visible text faithfully before summarizing. "
                            "If part of the text is unreadable, say so instead of inventing it."
                        ),
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": data_url}},
                        ],
                    },
                ],
                model=model or self._default_model,
                max_tokens=max_tokens,
                temperature=0.1,
            )
            content = (response.content or "").strip()
            return content or "No readable text or image analysis result was produced."
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error analyzing image: {str(e)}"


class WriteFileTool(Tool):
    """Tool to write content to a file."""

    def __init__(self, workspace: Path | None = None):
        self._workspace = workspace

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return (
            "Write content to a file, creating parent directories if needed. "
            "Overwrites existing content entirely. For partial edits, use edit_file instead."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The file path to write to"
                },
                "content": {
                    "type": "string",
                    "description": "The content to write"
                }
            },
            "required": ["path", "content"]
        }

    async def execute(self, path: str, content: str, **kwargs: Any) -> str:
        try:
            file_path = _resolve_path(path, self._workspace)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            return f"Successfully wrote {len(content)} bytes to {file_path}"
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error writing file: {str(e)}"


class EditFileTool(Tool):
    """Tool to edit a file by replacing text."""

    def __init__(self, workspace: Path | None = None):
        self._workspace = workspace

    @property
    def name(self) -> str:
        return "edit_file"

    @property
    def description(self) -> str:
        return (
            "Edit a file by finding and replacing exact text. The old_text must match exactly "
            "(including whitespace and indentation). If old_text appears multiple times, "
            "provide more surrounding context to make it unique. Shows a diff on mismatch."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The file path to edit"
                },
                "old_text": {
                    "type": "string",
                    "description": "The exact text to find and replace"
                },
                "new_text": {
                    "type": "string",
                    "description": "The text to replace with"
                }
            },
            "required": ["path", "old_text", "new_text"]
        }

    async def execute(self, path: str, old_text: str, new_text: str, **kwargs: Any) -> str:
        try:
            file_path = _resolve_path(path, self._workspace)
            if not file_path.exists():
                return f"Error: File not found: {path}"

            content = file_path.read_text(encoding="utf-8")

            if old_text not in content:
                return self._not_found_message(old_text, content, path)

            # Count occurrences
            count = content.count(old_text)
            if count > 1:
                return f"Warning: old_text appears {count} times. Please provide more context to make it unique."

            new_content = content.replace(old_text, new_text, 1)
            file_path.write_text(new_content, encoding="utf-8")

            return f"Successfully edited {file_path}"
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error editing file: {str(e)}"

    @staticmethod
    def _not_found_message(old_text: str, content: str, path: str) -> str:
        """Build a helpful error when old_text is not found."""
        lines = content.splitlines(keepends=True)
        old_lines = old_text.splitlines(keepends=True)
        window = len(old_lines)

        best_ratio, best_start = 0.0, 0
        for i in range(max(1, len(lines) - window + 1)):
            ratio = difflib.SequenceMatcher(None, old_lines, lines[i : i + window]).ratio()
            if ratio > best_ratio:
                best_ratio, best_start = ratio, i

        if best_ratio > 0.5:
            diff = "\n".join(difflib.unified_diff(
                old_lines, lines[best_start : best_start + window],
                fromfile="old_text (provided)", tofile=f"{path} (actual, line {best_start + 1})",
                lineterm="",
            ))
            return f"Error: old_text not found in {path}.\nBest match ({best_ratio:.0%} similar) at line {best_start + 1}:\n{diff}"
        return f"Error: old_text not found in {path}. No similar text found. Verify the file content."


class ListDirTool(Tool):
    """Tool to list directory contents."""

    def __init__(self, workspace: Path | None = None):
        self._workspace = workspace

    @property
    def name(self) -> str:
        return "list_dir"

    @property
    def description(self) -> str:
        return (
            "List files and directories at the given path. "
            "For recursive file search by pattern, use the glob tool instead."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The directory path to list"
                }
            },
            "required": ["path"]
        }

    async def execute(self, path: str, **kwargs: Any) -> str:
        try:
            dir_path = _resolve_path(path, self._workspace)
            if not dir_path.exists():
                return f"Error: Directory not found: {path}"
            if not dir_path.is_dir():
                return f"Error: Not a directory: {path}"

            items = []
            for item in sorted(dir_path.iterdir()):
                prefix = "📁 " if item.is_dir() else "📄 "
                items.append(f"{prefix}{item.name}")

            if not items:
                return f"Directory {path} is empty"

            return "\n".join(items)
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error listing directory: {str(e)}"
