"""Browser automation via agent-browser CLI."""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import shlex
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from loguru import logger

from lemonclaw.agent.tools.base import Tool

_CHAIN_OPERATORS = {"&&", "||", ";"}
_BLOCKED_SHELL_TOKENS = {"|", "&", "<", ">", "<<", ">>", "<<<"}


class BrowserTool(Tool):
    """Browser automation via agent-browser CLI.

    Wraps the agent-browser CLI to provide web interaction capabilities:
    navigation, snapshots, clicking, form filling, screenshots, PDFs, etc.
    """

    def __init__(
        self,
        timeout: int = 60,
        allowed_domains: list[str] | None = None,
        session_name: str = "",
        headed: bool = False,
        content_boundaries: bool = True,
        max_output: int = 50000,
        workspace: Path | str | None = None,
    ):
        self._timeout = timeout
        self._allowed_domains = [d.strip().lower() for d in (allowed_domains or []) if d.strip()]
        self._session_prefix = self._sanitize_session_component(session_name or "lc")
        self._headed = headed
        self._content_boundaries = content_boundaries
        self._max_output = max_output
        self._workspace = Path(workspace).expanduser().resolve() if workspace else None
        self._cli_path = shutil.which("agent-browser")
        self._active_sessions: set[str] = set()


    @property
    def available(self) -> bool:
        return bool(self._cli_path)

    @property
    def name(self) -> str:
        return "browser"

    @property
    def description(self) -> str:
        available = "AVAILABLE" if self._cli_path else "NOT INSTALLED"
        domains = f" Allowed domains: {', '.join(self._allowed_domains)}." if self._allowed_domains else ""
        workspace = f" Default working directory: {self._workspace}." if self._workspace else ""
        return (
            f"Browser automation via agent-browser CLI ({available}). "
            "Use for interacting with websites: navigating pages, filling forms, "
            "clicking buttons, taking screenshots, extracting data, or any browser task. "
            "Pass the full agent-browser command string (without the 'agent-browser' prefix). "
            "Examples: 'open https://example.com', 'snapshot -i', 'click @e1', "
            "'fill @e2 \"text\"', 'screenshot', 'close'. "
            "Always snapshot after navigation to get fresh element refs (@e1, @e2...)."
            f"{domains}{workspace}"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": (
                        "agent-browser command (without the 'agent-browser' prefix). "
                        "Examples: 'open https://example.com', 'snapshot -i', "
                        "'click @e1', 'fill @e2 \"text\"', 'screenshot', 'close'"
                    ),
                },
            },
            "required": ["command"],
        }

    async def execute(self, command: str, _session_key: str | None = None, **kwargs: Any) -> str:
        del kwargs
        if not self._cli_path:
            return "Error: agent-browser CLI is not installed. Install with: npm install -g agent-browser"

        if not command.strip():
            return "Error: empty command"

        parsed = self._parse_command_chain(command)
        if isinstance(parsed, str):
            return parsed
        commands, operators = parsed

        violation = self._check_commands(commands)
        if violation:
            return violation

        session_name = self._resolve_session_name(_session_key)
        self._active_sessions.add(session_name)
        env = self._build_env()
        cwd = str(self._workspace) if self._workspace else None

        logger.info("browser [{}]: {}", session_name, command)
        outputs: list[str] = []
        last_success = True
        last_error: str | None = None
        deadline = asyncio.get_running_loop().time() + self._timeout

        for index, step in enumerate(commands):
            if index > 0:
                op = operators[index - 1]
                if op == "&&" and not last_success:
                    break
                if op == "||" and last_success:
                    continue

            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return f"Error: browser command timed out after {self._timeout}s"

            output, error = await self._run_step(
                step_args=step,
                session_name=session_name,
                env=env,
                cwd=cwd,
                timeout=remaining,
            )
            if output:
                outputs.append(output)
            if error:
                last_success = False
                last_error = error
            else:
                last_success = True
                last_error = None

        if last_error:
            return last_error

        combined = "\n".join(part for part in outputs if part).strip()
        return self._truncate(combined) if combined else "(no output)"

    async def _run_step(
        self,
        *,
        step_args: list[str],
        session_name: str,
        env: dict[str, str],
        cwd: str | None,
        timeout: float,
    ) -> tuple[str, str | None]:
        process = await asyncio.create_subprocess_exec(
            *self._build_argv(step_args, session_name),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=cwd,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            process.kill()
            try:
                await asyncio.wait_for(process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                pass
            return "", f"Error: browser command timed out after {self._timeout}s"
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
            error_text = err or output or "unknown error"
            return "", f"Error (exit {process.returncode}): {error_text}"
        return output, None

    def _build_argv(self, step_args: list[str], session_name: str) -> list[str]:
        """Build the full argv list for agent-browser."""
        argv = [self._cli_path or "agent-browser"]
        if session_name:
            argv.extend(["--session", session_name])
        if self._headed:
            argv.append("--headed")
        argv.extend(step_args)
        return argv

    def _build_env(self) -> dict[str, str]:
        """Build environment variables for agent-browser."""
        env = os.environ.copy()
        if self._content_boundaries:
            env["AGENT_BROWSER_CONTENT_BOUNDARIES"] = "1"
        if self._allowed_domains:
            env["AGENT_BROWSER_ALLOWED_DOMAINS"] = ",".join(self._allowed_domains)
        if self._max_output:
            env["AGENT_BROWSER_MAX_OUTPUT"] = str(self._max_output)
        return env

    def _parse_command_chain(self, command: str) -> tuple[list[list[str]], list[str]] | str:
        """Parse browser commands without invoking a shell."""
        try:
            lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>")
            lexer.whitespace_split = True
            lexer.commenters = ""
            tokens = list(lexer)
        except ValueError:
            return "Error: malformed browser command"

        if not tokens:
            return "Error: empty command"

        commands: list[list[str]] = []
        operators: list[str] = []
        current: list[str] = []
        for token in tokens:
            if token in _CHAIN_OPERATORS:
                if not current:
                    return "Error: malformed browser command"
                commands.append(current)
                operators.append(token)
                current = []
                continue
            if token in _BLOCKED_SHELL_TOKENS:
                return (
                    "Error: shell redirection and pipes are not supported in browser commands. "
                    "Use multiple browser calls or filesystem tools instead."
                )
            current.append(token)

        if not current:
            return "Error: malformed browser command"
        commands.append(current)
        return commands, operators

    def _check_commands(self, commands: list[list[str]]) -> str | None:
        for step_args in commands:
            violation = self._check_navigation(step_args)
            if violation:
                return violation
            violation = self._check_workspace_paths(step_args)
            if violation:
                return violation
        return None

    def _check_navigation(self, step_args: list[str]) -> str | None:
        if not step_args or step_args[0] not in {"open", "goto", "navigate"}:
            return None

        url = next((token for token in step_args[1:] if not token.startswith("-")), "")
        if not url:
            return None

        try:
            if ":" in url.split("/")[0] and "://" not in url:
                parsed = urlparse(url)
            else:
                parsed = urlparse(url if "://" in url else f"https://{url}")
        except Exception:
            return None

        scheme = (parsed.scheme or "").lower()
        domain = (parsed.hostname or "").lower()
        if scheme and scheme not in {"http", "https"}:
            return f"Error: scheme '{scheme}' is not allowed (only http/https)"
        if domain and self._allowed_domains and not self._is_domain_allowed(domain):
            return (
                f"Error: domain '{domain}' is not in the allowed domains list: "
                f"{', '.join(self._allowed_domains)}"
            )
        return None

    def _check_workspace_paths(self, step_args: list[str]) -> str | None:
        return None

    def _resolve_session_name(self, session_key: str | None) -> str:
        if not session_key:
            return self._session_prefix
        safe_key = self._sanitize_session_component(session_key, default="session")[:32]
        digest = hashlib.sha256(session_key.encode("utf-8")).hexdigest()[:10]
        return f"{self._session_prefix}-{safe_key}-{digest}"[:80]

    @staticmethod
    def _sanitize_session_component(value: str, default: str = "lc") -> str:
        cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-._")
        return cleaned[:48] or default

    def _is_domain_allowed(self, domain: str) -> bool:
        """Check if a domain matches the allowlist."""
        for allowed in self._allowed_domains:
            if allowed.startswith("*."):
                base = allowed[2:]
                if domain == base or domain.endswith(f".{base}"):
                    return True
            elif domain == allowed:
                return True
        return False

    def _truncate(self, text: str) -> str:
        """Truncate output to max_output chars."""
        if len(text) <= self._max_output:
            return text
        return text[:self._max_output] + f"\n... (truncated, {len(text) - self._max_output} more chars)"

    async def cleanup(self) -> None:
        """Close all browser sessions. Called on agent shutdown."""
        if not self._cli_path:
            return
        env = self._build_env()
        cwd = str(self._workspace) if self._workspace else None
        for session_name in sorted(self._active_sessions):
            try:
                process = await asyncio.create_subprocess_exec(
                    self._cli_path,
                    "--session",
                    session_name,
                    "close",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                    cwd=cwd,
                )
                await asyncio.wait_for(process.communicate(), timeout=10.0)
                logger.info("browser [{}]: session closed", session_name)
            except asyncio.TimeoutError:
                process.kill()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5.0)
                except Exception:
                    pass
                logger.debug("browser [{}]: cleanup timed out; process killed", session_name)
            except Exception as e:
                logger.debug("browser [{}]: cleanup error (non-fatal): {}", session_name, e)
        self._active_sessions.clear()
