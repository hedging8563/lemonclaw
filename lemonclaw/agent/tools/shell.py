"""Shell execution tool — runs commands via /bin/sh."""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from typing import Any

from lemonclaw.agent.tools.base import Tool


class ExecTool(Tool):
    """Tool to execute shell commands via /bin/sh -c."""

    def __init__(
        self,
        timeout: int = 60,
        working_dir: str | None = None,
        deny_patterns: list[str] | None = None,
        allow_patterns: list[str] | None = None,
        restrict_to_workspace: bool = False,
        home_dir: str | None = None,
        path_append: str = "",
        max_output: int = 50_000,
    ):
        self.timeout = timeout
        self.working_dir = working_dir
        self.deny_patterns = deny_patterns or [
            r"\brm\s+-[rf]{1,2}\b",
            r"\bdel\s+/[fq]\b",
            r"\brmdir\s+/s\b",
            r"(?:^|[;&|]\s*)format\b",
            r"\b(mkfs|diskpart)\b",
            r"\bdd\s+if=",
            r">\s*/dev/sd",
            r"\b(shutdown|reboot|poweroff)\b",
            r":\(\)\s*\{.*\};\s*:",
        ]
        self.allow_patterns = allow_patterns or []
        self.restrict_to_workspace = restrict_to_workspace
        self.home_dir = home_dir
        self.path_append = path_append
        self.max_output = max_output

    @property
    def name(self) -> str:
        return "exec"

    @property
    def description(self) -> str:
        return (
            "Execute a shell command via /bin/sh and return stdout+stderr. "
            "Supports pipes (|), chaining (&&, ||), redirects (>, >>), "
            "environment variables ($VAR), subshells, and all standard shell features. "
            "Use for: running scripts, curl, git, package managers, build tools. "
            "Commands are subject to safety guards (rm -rf, mkfs, etc. are blocked)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute (passed to /bin/sh -c)",
                },
                "working_dir": {
                    "type": "string",
                    "description": "Optional working directory for the command",
                },
            },
            "required": ["command"],
        }

    async def execute(self, command: str, working_dir: str | None = None, **kwargs: Any) -> str:
        del kwargs
        cwd, cwd_error = self._resolve_cwd(working_dir)
        if cwd_error:
            return cwd_error

        guard_error = self._guard_command(command, cwd)
        if guard_error:
            return guard_error

        env = os.environ.copy()
        if self.path_append:
            env["PATH"] = env.get("PATH", "") + os.pathsep + self.path_append

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd),
                env=env,
            )
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self.timeout)
            except asyncio.TimeoutError:
                process.kill()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    pass
                return f"Error: Command timed out after {self.timeout} seconds"
            except asyncio.CancelledError:
                process.kill()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5.0)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    pass
                raise

            output_parts = []
            if stdout:
                output_parts.append(stdout.decode("utf-8", errors="replace"))
            if stderr:
                stderr_text = stderr.decode("utf-8", errors="replace")
                if stderr_text.strip():
                    output_parts.append(f"STDERR:\n{stderr_text}")
            if process.returncode != 0:
                output_parts.append(f"\nExit code: {process.returncode}")

            result = "\n".join(output_parts) if output_parts else "(no output)"
            if len(result) > self.max_output:
                result = result[:self.max_output] + f"\n... (truncated, {len(result) - self.max_output} more chars)"
            return result
        except Exception as exc:
            return f"Error executing command: {exc}"

    def _resolve_cwd(self, working_dir: str | None) -> tuple[Path, str | None]:
        base_dir = Path(self.working_dir or os.getcwd()).resolve()
        if not working_dir:
            return base_dir, None

        raw_target = Path(working_dir).expanduser()
        target = raw_target.resolve() if raw_target.is_absolute() else (base_dir / raw_target).resolve()
        if self.restrict_to_workspace:
            boundary = Path(self.home_dir).resolve() if self.home_dir else base_dir
            if target != boundary and boundary not in target.parents:
                return base_dir, "Error: working_dir is outside the allowed boundary"
        return target, None

    def _guard_command(self, command: str, cwd: Path) -> str | None:
        """Safety guard: deny_patterns + optional workspace boundary check."""
        lower = command.strip().lower()

        for pattern in self.deny_patterns:
            if re.search(pattern, lower):
                return "Error: Command blocked by safety guard (dangerous pattern detected)"

        if self.allow_patterns and not any(re.search(p, lower) for p in self.allow_patterns):
            return "Error: Command blocked by safety guard (not in allowlist)"

        if self.restrict_to_workspace:
            boundary = Path(self.home_dir).resolve() if self.home_dir else cwd
            # Check for path traversal via ..
            posix_paths = re.findall(r"(?:^|[\s|>])(/[^\s\"'>]+)", command)
            win_paths = re.findall(r"[A-Za-z]:\\[^\\\"']+", command)
            for raw in posix_paths + win_paths:
                normalized = os.path.normpath(raw.strip())
                if ".." in normalized.split(os.sep):
                    return "Error: Command blocked by safety guard (path traversal detected)"
                try:
                    path = Path(normalized).resolve()
                except Exception:
                    continue
                if path.is_absolute() and boundary not in path.parents and path != boundary:
                    return "Error: Command blocked by safety guard (path outside allowed boundary)"

        return None
