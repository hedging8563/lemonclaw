"""Claude Code CLI integration tool."""

import asyncio
import json
import os
import shutil
from typing import Any

from loguru import logger

from lemonclaw.agent.tools.base import Tool


class CodingTool(Tool):
    """Tool to delegate coding tasks to Claude Code CLI."""

    def __init__(
        self,
        working_dir: str,
        timeout: int = 300,
        api_key: str = "",
        api_base: str = "",
        model: str = "",
        restrict_to_workspace: bool = False,
        home_dir: str | None = None,
    ):
        self._working_dir = working_dir
        self._timeout = timeout
        self._api_key = api_key
        self._api_base = api_base
        self._model = model
        self._restrict_to_workspace = restrict_to_workspace
        self._home_dir = home_dir
        self._cli_path = shutil.which("claude")

    @property
    def name(self) -> str:
        return "coding"

    @property
    def description(self) -> str:
        available = "AVAILABLE" if self._cli_path else "NOT INSTALLED"
        return (
            f"Delegate a coding task to Claude Code CLI ({available}). "
            "Use for complex code generation, refactoring, or multi-file changes "
            "that benefit from a dedicated coding agent. The CLI runs in "
            "non-interactive mode with its own context."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The coding task to perform, described in natural language",
                },
                "working_dir": {
                    "type": "string",
                    "description": "Working directory for the task (default: workspace root)",
                },
            },
            "required": ["task"],
        }

    async def execute(self, task: str, working_dir: str | None = None, **kwargs: Any) -> str:
        if not self._cli_path:
            return "Error: claude CLI is not installed. Install with: npm install -g @anthropic-ai/claude-code"

        cwd = working_dir or self._working_dir
        if self._restrict_to_workspace:
            from pathlib import Path
            # Use home_dir as security boundary (e.g. ~/.lemonclaw/)
            boundary = Path(self._home_dir).resolve() if self._home_dir else Path(self._working_dir).resolve()
            # Resolve relative paths against workspace, not process cwd
            ws = Path(self._working_dir).resolve()
            target = (ws / cwd).resolve() if not Path(cwd).is_absolute() else Path(cwd).resolve()
            if boundary not in target.parents and target != boundary:
                return "Error: working_dir is outside the allowed boundary"

        env = os.environ.copy()
        if self._api_key:
            env["ANTHROPIC_API_KEY"] = self._api_key
        if self._api_base:
            env["ANTHROPIC_BASE_URL"] = self._api_base
        # Prevent nested session detection
        env.pop("CLAUDECODE", None)

        cmd = [
            self._cli_path,
            "--print",
            "--output-format", "json",
            "--max-turns", "10",
            "--dangerously-skip-permissions",
        ]
        if self._model:
            # Basic validation: model names are alphanumeric with hyphens/dots/slashes
            import re
            if re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_./:@-]{0,127}', self._model):
                cmd.extend(["--model", self._model])
            else:
                logger.warning("coding: invalid model name '{}', using CLI default", self._model[:40])
        cmd.append(task)

        logger.info("coding: running claude CLI in {}", cwd)
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=self._timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    pass
                return f"Error: Claude CLI timed out after {self._timeout}s"
            except asyncio.CancelledError:
                process.kill()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5.0)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    pass
                raise

            output = stdout.decode("utf-8", errors="replace").strip()
            err = stderr.decode("utf-8", errors="replace").strip()

            if process.returncode != 0:
                return f"Error (exit {process.returncode}): {err or output or 'unknown error'}"

            return self._parse_output(output)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            return f"Error running claude CLI: {e}"

    def _parse_output(self, raw: str) -> str:
        """Extract meaningful content from CLI JSON output."""
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            if len(raw) > 8000:
                return raw[:8000] + f"\n... (truncated, {len(raw) - 8000} more chars)"
            return raw or "(no output)"

        # --output-format json returns a list of content blocks
        if isinstance(data, list):
            parts = []
            for block in data:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
            result = "\n".join(parts) if parts else json.dumps(data, ensure_ascii=False)
        elif isinstance(data, dict):
            result = data.get("result", data.get("text", json.dumps(data, ensure_ascii=False)))
        else:
            result = str(data)

        if len(result) > 8000:
            result = result[:8000] + f"\n... (truncated, {len(result) - 8000} more chars)"
        return result or "(no output)"
