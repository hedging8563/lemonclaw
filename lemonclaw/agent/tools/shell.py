"""Shell execution tool."""

from __future__ import annotations

import asyncio
import os
import re
import shlex
from pathlib import Path
from typing import Any

from lemonclaw.agent.tools.base import Tool

_SHELL_OPERATORS = {"&&", "||", ";", "|", "&", "<", ">", "<<", ">>", "<<<"}
_SHELL_BUILTINS = {".", "alias", "cd", "exec", "exit", "export", "source", "umask", "unset"}


class ExecTool(Tool):
    """Tool to execute local commands."""

    def __init__(
        self,
        timeout: int = 60,
        working_dir: str | None = None,
        deny_patterns: list[str] | None = None,
        allow_patterns: list[str] | None = None,
        restrict_to_workspace: bool = False,
        path_append: str = "",
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
        self._deny_arg_combos = {
            "rm": {"-r", "-rf", "-fr", "-f", "--recursive", "--force"},
        }
        self.allow_patterns = allow_patterns or []
        self.restrict_to_workspace = restrict_to_workspace
        self.path_append = path_append

    @property
    def name(self) -> str:
        return "exec"

    @property
    def description(self) -> str:
        return (
            "Execute a local command and return its output. "
            "Shell operators and builtins are blocked; use `working_dir` instead of `cd`."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The command to execute",
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

        guard_error, tokens = self._guard_command(command, cwd)
        if guard_error:
            return guard_error

        env = os.environ.copy()
        if self.path_append:
            env["PATH"] = env.get("PATH", "") + os.pathsep + self.path_append

        try:
            process = await asyncio.create_subprocess_exec(
                *tokens,
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
            max_len = 10000
            if len(result) > max_len:
                result = result[:max_len] + f"\n... (truncated, {len(result) - max_len} more chars)"
            return result
        except FileNotFoundError:
            return f"Error executing command: command not found: {tokens[0]}"
        except Exception as exc:
            return f"Error executing command: {exc}"

    def _resolve_cwd(self, working_dir: str | None) -> tuple[Path, str | None]:
        base_dir = Path(self.working_dir or os.getcwd()).resolve()
        if not working_dir:
            return base_dir, None

        raw_target = Path(working_dir).expanduser()
        target = raw_target.resolve() if raw_target.is_absolute() else (base_dir / raw_target).resolve()
        if self.restrict_to_workspace and target != base_dir and base_dir not in target.parents:
            return base_dir, "Error: working_dir is outside the workspace"
        return target, None

    def _guard_command(self, command: str, cwd: Path) -> tuple[str | None, list[str]]:
        """Best-effort safety guard for potentially destructive commands."""
        cmd = command.strip()
        lower = cmd.lower()

        for pattern in self.deny_patterns:
            if re.search(pattern, lower):
                return "Error: Command blocked by safety guard (dangerous pattern detected)", []

        if self.allow_patterns and not any(re.search(p, lower) for p in self.allow_patterns):
            return "Error: Command blocked by safety guard (not in allowlist)", []

        try:
            lexer = shlex.shlex(cmd, posix=True, punctuation_chars=";&|<>")
            lexer.whitespace_split = True
            lexer.commenters = ""
            tokens = list(lexer)
        except ValueError:
            return "Error: Command blocked by safety guard (malformed shell syntax)", []

        if not tokens:
            return "Error: empty command", []

        if any(token in _SHELL_OPERATORS for token in tokens):
            return (
                "Error: Command blocked by safety guard (shell operators are not supported; run commands separately)",
                [],
            )

        base_cmd = os.path.basename(tokens[0]).lower()
        if base_cmd in _SHELL_BUILTINS:
            if base_cmd == "cd":
                return "Error: `cd` is not supported; use the working_dir parameter instead", []
            return "Error: Command blocked by safety guard (shell builtins are not supported)", []

        if base_cmd in self._deny_arg_combos:
            dangerous_args = self._deny_arg_combos[base_cmd]
            cmd_args = {token.lower() for token in tokens[1:] if token.startswith("-")}
            if cmd_args & dangerous_args:
                return "Error: Command blocked by safety guard (dangerous pattern detected)", []
        elif base_cmd in {"dd", "mkfs", "diskpart", "shutdown", "reboot", "poweroff", "format", "rm", "rmdir"}:
            return "Error: Command blocked by safety guard (dangerous pattern detected)", []

        if self.restrict_to_workspace:
            for token in tokens:
                normalized = os.path.normpath(token)
                if ".." in normalized.split(os.sep):
                    return "Error: Command blocked by safety guard (path traversal detected)", []

            win_paths = re.findall(r"[A-Za-z]:\\[^\\\"']+", cmd)
            posix_paths = re.findall(r"(?:^|[\s|>])(/[^\s\"'>]+)", cmd)
            for raw in win_paths + posix_paths:
                try:
                    path = Path(raw.strip()).resolve()
                except Exception:
                    continue
                if path.is_absolute() and cwd not in path.parents and path != cwd:
                    return "Error: Command blocked by safety guard (path outside working dir)", []

        return None, tokens
