"""Grep tool — search file contents using regex patterns."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from lemonclaw.agent.tools.base import Tool

_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache", ".pytest_cache"}

_TYPE_MAP = {
    "py": ["*.py"],
    "js": ["*.js", "*.jsx", "*.mjs", "*.cjs"],
    "ts": ["*.ts", "*.tsx", "*.mts", "*.cts"],
    "go": ["*.go"],
    "rs": ["*.rs"],
    "java": ["*.java"],
    "rb": ["*.rb"],
    "php": ["*.php"],
    "c": ["*.c", "*.h"],
    "cpp": ["*.cpp", "*.hpp", "*.cc", "*.cxx"],
    "md": ["*.md", "*.mdx"],
    "json": ["*.json"],
    "yaml": ["*.yaml", "*.yml"],
    "toml": ["*.toml"],
    "sh": ["*.sh", "*.bash", "*.zsh"],
    "sql": ["*.sql"],
    "html": ["*.html", "*.htm"],
    "css": ["*.css", "*.scss", "*.less"],
}


def _is_binary(path: Path, sample_size: int = 8192) -> bool:
    """Heuristic: file is binary if it contains null bytes in the first N bytes."""
    try:
        with open(path, "rb") as f:
            chunk = f.read(sample_size)
        return b"\x00" in chunk
    except (OSError, PermissionError):
        return True


def _should_skip(path: Path) -> bool:
    """Check if any path component is in the skip set."""
    return bool(_SKIP_DIRS.intersection(path.parts))


class GrepTool(Tool):
    """Search file contents using regex patterns."""

    def __init__(self, workspace: Path | None = None, allowed_dir: Path | None = None):
        self._workspace = workspace
        self._allowed_dir = allowed_dir

    @property
    def name(self) -> str:
        return "grep"

    @property
    def description(self) -> str:
        return (
            "Search file contents using regex patterns. Returns matching lines with "
            "file paths and line numbers. Supports context lines, file type filtering "
            "(e.g. type='py'), and glob filtering (e.g. glob='*.ts'). "
            "Use this for code search instead of shell grep."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Regex pattern to search for",
                },
                "path": {
                    "type": "string",
                    "description": "Directory or file to search in (default: workspace root)",
                },
                "glob": {
                    "type": "string",
                    "description": "Glob pattern to filter files (e.g. '*.py', '*.ts')",
                },
                "type": {
                    "type": "string",
                    "description": "File type shorthand: py, js, ts, go, rs, java, rb, php, c, cpp, md, json, yaml, sh, sql, html, css",
                },
                "context_lines": {
                    "type": "integer",
                    "description": "Number of context lines before and after each match (default: 0)",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of matching lines to return (default: 50)",
                },
                "case_insensitive": {
                    "type": "boolean",
                    "description": "Case-insensitive search (default: false)",
                },
            },
            "required": ["pattern"],
        }

    async def execute(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
        type: str | None = None,
        context_lines: int = 0,
        max_results: int = 50,
        case_insensitive: bool = False,
        **kwargs: Any,
    ) -> str:
        # Resolve search root
        search_root = self._resolve_path(path)
        if isinstance(search_root, str):
            return search_root  # error message

        # Compile regex
        flags = re.IGNORECASE if case_insensitive else 0
        try:
            regex = re.compile(pattern, flags)
        except re.error as e:
            return f"Error: Invalid regex pattern: {e}"

        # Determine file globs to match
        file_globs: list[str] | None = None
        if type:
            file_globs = _TYPE_MAP.get(type)
            if not file_globs:
                return f"Error: Unknown file type '{type}'. Available: {', '.join(sorted(_TYPE_MAP))}"
        if glob:
            file_globs = [glob]

        # Collect matching files
        if search_root.is_file():
            files = [search_root]
        else:
            files = self._collect_files(search_root, file_globs)

        # Search
        matches: list[str] = []
        context_lines = max(0, min(context_lines, 10))  # clamp
        max_results = max(1, min(max_results, 500))
        files_with_matches = 0

        for fpath in files:
            if len(matches) >= max_results:
                break
            file_matches = self._search_file(fpath, regex, context_lines, max_results - len(matches), search_root)
            if file_matches:
                files_with_matches += 1
                matches.extend(file_matches)

        if not matches:
            return f"No matches found for pattern '{pattern}'"

        header = f"Found {len(matches)} match{'es' if len(matches) > 1 else ''} in {files_with_matches} file{'s' if files_with_matches > 1 else ''}"
        if len(matches) >= max_results:
            header += f" (limited to {max_results})"
        return header + "\n\n" + "\n".join(matches)

    def _resolve_path(self, path: str | None) -> Path | str:
        """Resolve and validate the search path."""
        if path:
            p = Path(path).expanduser()
            if not p.is_absolute() and self._workspace:
                p = self._workspace / p
            p = p.resolve()
        else:
            p = (self._workspace or Path.cwd()).resolve()

        if self._allowed_dir:
            allowed = self._allowed_dir.resolve()
            try:
                p.relative_to(allowed)
            except ValueError:
                return f"Error: Path '{path}' is outside allowed directory"

        if not p.exists():
            return f"Error: Path not found: {path}"
        return p

    def _collect_files(self, root: Path, file_globs: list[str] | None) -> list[Path]:
        """Collect files to search, respecting skip dirs and glob filters."""
        files: list[Path] = []
        max_files = 5000

        if file_globs:
            for g in file_globs:
                for f in root.rglob(g):
                    try:
                        rel = f.relative_to(root)
                    except ValueError:
                        continue
                    if f.is_file() and not _should_skip(rel):
                        files.append(f)
                        if len(files) >= max_files:
                            return files
        else:
            for f in root.rglob("*"):
                try:
                    rel = f.relative_to(root)
                except ValueError:
                    continue
                if f.is_file() and not _should_skip(rel):
                    files.append(f)
                    if len(files) >= max_files:
                        return files

        return files

    def _search_file(
        self, fpath: Path, regex: re.Pattern, context: int, remaining: int, root: Path
    ) -> list[str]:
        """Search a single file and return formatted match lines."""
        if _is_binary(fpath):
            return []

        try:
            lines = fpath.read_text(encoding="utf-8", errors="replace").splitlines()
        except (OSError, PermissionError):
            return []

        try:
            rel = fpath.relative_to(root)
        except ValueError:
            rel = fpath

        results: list[str] = []
        for i, line in enumerate(lines):
            if len(results) >= remaining:
                break
            if regex.search(line):
                if context > 0:
                    start = max(0, i - context)
                    end = min(len(lines), i + context + 1)
                    block = []
                    for j in range(start, end):
                        marker = ">" if j == i else " "
                        block.append(f"{rel}:{j + 1}:{marker} {lines[j]}")
                    results.append("\n".join(block))
                else:
                    results.append(f"{rel}:{i + 1}: {line}")

        return results
