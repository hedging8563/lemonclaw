"""Glob tool — find files matching glob patterns."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lemonclaw.agent.tools.base import Tool

_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache", ".pytest_cache"}


def _should_skip(path: Path) -> bool:
    """Check if any path component is in the skip set."""
    return bool(_SKIP_DIRS.intersection(path.parts))


class GlobTool(Tool):
    """Find files matching glob patterns."""

    def __init__(self, workspace: Path | None = None, allowed_dir: Path | None = None):
        self._workspace = workspace
        self._allowed_dir = allowed_dir

    @property
    def name(self) -> str:
        return "glob"

    @property
    def description(self) -> str:
        return (
            "Find files matching a glob pattern (e.g. '**/*.py', 'src/**/*.ts'). "
            "Returns file paths sorted by modification time (newest first). "
            "Use this to discover files by name or extension. "
            "Skips .git, node_modules, __pycache__ directories."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern (e.g. '**/*.py', 'src/**/*.ts', '*.json')",
                },
                "path": {
                    "type": "string",
                    "description": "Base directory to search from (default: workspace root)",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of files to return (default: 100)",
                },
            },
            "required": ["pattern"],
        }

    async def execute(
        self,
        pattern: str,
        path: str | None = None,
        max_results: int = 100,
        **kwargs: Any,
    ) -> str:
        # Resolve base path
        base = self._resolve_path(path)
        if isinstance(base, str):
            return base  # error message

        max_results = max(1, min(max_results, 1000))

        # Collect matches
        try:
            matches: list[Path] = []
            for f in base.glob(pattern):
                try:
                    rel = f.relative_to(base)
                except ValueError:
                    continue
                if f.is_file() and not _should_skip(rel):
                    matches.append(f)
                    if len(matches) >= max_results * 2:  # over-collect for sorting
                        break
        except (OSError, ValueError) as e:
            return f"Error: Invalid glob pattern: {e}"

        if not matches:
            return f"No files found matching '{pattern}'"

        # Sort by modification time (newest first)
        matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        matches = matches[:max_results]

        # Format output
        lines: list[str] = []
        for m in matches:
            try:
                rel = m.relative_to(base)
            except ValueError:
                rel = m
            lines.append(str(rel))

        header = f"Found {len(lines)} file{'s' if len(lines) > 1 else ''}"
        if len(lines) >= max_results:
            header += f" (limited to {max_results})"
        return header + "\n\n" + "\n".join(lines)

    def _resolve_path(self, path: str | None) -> Path | str:
        """Resolve and validate the base path."""
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
        if not p.is_dir():
            return f"Error: Not a directory: {path}"
        return p
