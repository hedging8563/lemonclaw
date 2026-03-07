"""Browser automation via agent-browser CLI."""

import asyncio
import os
import re
import shlex
import shutil
from typing import Any
from urllib.parse import urlparse

from loguru import logger

from lemonclaw.agent.tools.base import Tool


class BrowserTool(Tool):
    """Browser automation via agent-browser CLI.

    Wraps the agent-browser CLI to provide web interaction capabilities:
    navigation, snapshots, clicking, form filling, screenshots, etc.
    """

    def __init__(
        self,
        timeout: int = 60,
        allowed_domains: list[str] | None = None,
        session_name: str = "",
        headed: bool = False,
        content_boundaries: bool = True,
        max_output: int = 50000,
    ):
        self._timeout = timeout
        self._allowed_domains = allowed_domains or []
        self._session_name = session_name
        self._headed = headed
        self._content_boundaries = content_boundaries
        self._max_output = max_output
        self._cli_path = shutil.which("agent-browser")

    @property
    def name(self) -> str:
        return "browser"

    @property
    def description(self) -> str:
        available = "AVAILABLE" if self._cli_path else "NOT INSTALLED"
        domains = f" Allowed domains: {', '.join(self._allowed_domains)}." if self._allowed_domains else ""
        return (
            f"Browser automation via agent-browser CLI ({available}). "
            "Use for interacting with websites: navigating pages, filling forms, "
            "clicking buttons, taking screenshots, extracting data, or any browser task. "
            "Pass the full agent-browser command string (without the 'agent-browser' prefix). "
            "Examples: 'open https://example.com', 'snapshot -i', 'click @e1', "
            "'fill @e2 \"text\"', 'screenshot', 'close'. "
            "Always snapshot after navigation to get fresh element refs (@e1, @e2...)."
            f"{domains}"
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

    async def execute(self, command: str, **kwargs: Any) -> str:
        if not self._cli_path:
            return "Error: agent-browser CLI is not installed. Install with: npm install -g agent-browser"

        if not command.strip():
            return "Error: empty command"

        # Domain allowlist check on 'open' / 'goto' / 'navigate' commands
        violation = self._check_domain(command)
        if violation:
            return violation

        shell_cmd = self._build_command(command)

        logger.info("browser: {}", command)
        try:
            process = await asyncio.create_subprocess_shell(
                shell_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._build_env(),
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
                return f"Error: browser command timed out after {self._timeout}s"
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
                # Combine stderr + stdout for error context
                error_text = err or output or "unknown error"
                return f"Error (exit {process.returncode}): {error_text}"

            return self._truncate(output) if output else "(no output)"

        except asyncio.CancelledError:
            raise
        except Exception as e:
            return f"Error running agent-browser: {e}"

    def _build_command(self, command: str) -> str:
        """Build the full shell command with global flags."""
        parts = [shlex.quote(self._cli_path or "agent-browser")]

        if self._session_name:
            parts.append(f"--session {shlex.quote(self._session_name)}")
        if self._headed:
            parts.append("--headed")

        parts.append(command)
        return " ".join(parts)

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

    def _check_domain(self, command: str) -> str | None:
        """Check domain allowlist for navigation commands. Returns error string or None.

        Handles chained commands (&&, ||, ;) by checking each sub-command.
        """
        if not self._allowed_domains:
            return None

        # Split on shell operators to handle chained commands
        sub_commands = [s.strip() for s in re.split(r"&&|\|\||;", command)]
        for sub in sub_commands:
            parts = sub.split(None, 1)
            if not parts or parts[0] not in ("open", "goto", "navigate"):
                continue
            if len(parts) < 2:
                continue

            url = parts[1].strip().strip("\"'")
            try:
                # Detect scheme: urlparse needs :// for proper parsing;
                # "javascript:x" has : but not ://, still has a scheme
                if ":" in url.split("/")[0] and "://" not in url:
                    # Looks like scheme:something (javascript:, data:, file:)
                    parsed = urlparse(url)
                else:
                    parsed = urlparse(url if "://" in url else f"https://{url}")
                scheme = parsed.scheme or ""
                domain = parsed.hostname or ""
            except Exception:
                continue  # Let agent-browser handle invalid URLs

            # Block non-http(s) schemes (file://, javascript:, data:, etc.)
            if scheme and scheme not in ("http", "https"):
                return f"Error: scheme '{scheme}' is not allowed (only http/https)"

            if not domain:
                continue

            if not self._is_domain_allowed(domain):
                return f"Error: domain '{domain}' is not in the allowed domains list: {', '.join(self._allowed_domains)}"

        return None

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
        """Close the browser session. Called on agent shutdown."""
        if not self._cli_path:
            return
        try:
            cmd = self._build_command("close")
            process = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._build_env(),
            )
            await asyncio.wait_for(process.communicate(), timeout=10.0)
            logger.info("browser: session closed")
        except Exception as e:
            logger.debug("browser: cleanup error (non-fatal): {}", e)
