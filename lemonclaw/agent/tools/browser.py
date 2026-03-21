"""Browser automation via agent-browser CLI."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shlex
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
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
        self._dicloak_enabled = os.environ.get("DICLOAK_ENABLED", "").lower() == "true"
        self._dicloak_api_base_url = (os.environ.get("DICLOAK_API_BASE_URL") or "").rstrip("/")
        self._dicloak_api_key = os.environ.get("DICLOAK_API_KEY", "")
        self._dicloak_leases: dict[str, dict[str, Any]] = {}
        self._dicloak_last_open: dict[str, Any] | None = None
        self._dicloak_last_close: dict[str, Any] | None = None


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
            " When DICloak is enabled, explicit profile lifecycle commands are available: "
            "'dicloak list_profiles', 'dicloak open_profile <profile_id>', 'dicloak close_profile [profile_id]'."
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
                        "'click @e1', 'fill @e2 \"text\"', 'screenshot', 'close'. "
                        "DICloak commands: 'dicloak list_profiles', 'dicloak open_profile <profile_id>', "
                        "'dicloak close_profile [profile_id]'."
                    ),
                },
            },
            "required": ["command"],
        }

    def resolve_capability(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> str:
        del context
        command = str(params.get("command") or "").strip().lower()
        if not command:
            return "browser.read"
        if re.search(r"\b(click|fill|type|press|select|submit|check|uncheck|drag|upload|file-upload|accept-dialog|dismiss-dialog)\b", command):
            return "browser.interact"
        return "browser.read"

    async def execute(self, command: str, _session_key: str | None = None, **kwargs: Any) -> str:
        del kwargs
        dicloak_result = await self._maybe_execute_dicloak(command, _session_key)
        if dicloak_result is not None:
            return dicloak_result
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

    async def _maybe_execute_dicloak(self, command: str, session_key: str | None) -> str | None:
        stripped = command.strip()
        if not stripped.lower().startswith("dicloak"):
            return None
        if not self._dicloak_enabled or not self._dicloak_api_base_url or not self._dicloak_api_key:
            return "Error: DICloak backend is not enabled for this instance."

        parts = stripped.split()
        if len(parts) < 2:
            return "Error: missing DICloak command."
        action = parts[1].lower()
        session_name = self._resolve_session_name(session_key)

        async with httpx.AsyncClient(timeout=min(self._timeout, 15.0)) as client:
            headers = {"X-API-KEY": self._dicloak_api_key}
            if action == "list_profiles":
                response = await client.get(f"{self._dicloak_api_base_url}/v1/env/list", params={"page_no": 1, "page_size": 20}, headers=headers)
                payload = response.json()
                if response.status_code != 200 or payload.get("code") != 0:
                    return f"Error: DICloak list_profiles failed: {payload.get('msg') or response.text}"
                rows = []
                for item in list(((payload.get("data") or {}).get("list") or []))[:20]:
                    if not isinstance(item, dict):
                        continue
                    rows.append(f"- {item.get('id') or '—'} · {item.get('name') or 'Unnamed'} · {item.get('operate_status') or item.get('status') or 'unknown'}")
                return "DICloak profiles:\n" + ("\n".join(rows) if rows else "(no profiles)")

            if action == "open_profile":
                if len(parts) < 3:
                    return "Error: missing profile_id for DICloak open_profile."
                if not self._cli_path:
                    return "Error: agent-browser CLI is required for DICloak profile sessions."
                profile_id = parts[2]
                existing_profile_id = str((self._dicloak_leases.get(session_name) or {}).get("profile_id") or "")
                if existing_profile_id and existing_profile_id != profile_id:
                    await self._maybe_execute_dicloak(f"dicloak close_profile {existing_profile_id}", session_key)
                response = await client.patch(f"{self._dicloak_api_base_url}/v1/env/{profile_id}/open", headers=headers)
                payload = response.json()
                if response.status_code != 200 or payload.get("code") != 0:
                    details = payload.get("data") if isinstance(payload.get("data"), dict) else {}
                    detail_message = str((details or {}).get("message") or "")
                    self._dicloak_last_open = {
                        "ok": False,
                        "profile_id": profile_id,
                        "session_name": session_name,
                        "error": detail_message or payload.get("msg") or response.text,
                    }
                    if detail_message == "BROWSER_NOT_INSTALL_2":
                        return (
                            "Error: DICloak open_profile failed because the selected profile kernel is not installed "
                            "for this runtime yet (BROWSER_NOT_INSTALL_2). Known supported kernel candidates are "
                            "120, 134, 142, 143."
                        )
                    return f"Error: DICloak open_profile failed: {detail_message or payload.get('msg') or response.text}"
                data = payload.get("data") or {}
                debug_port = data.get("debug_port")
                if not debug_port:
                    return "Error: DICloak open_profile returned no debug_port."
                env = self._build_env()
                cwd = str(self._workspace) if self._workspace else None
                connect_output, connect_error = await self._run_step(
                    step_args=["connect", str(debug_port)],
                    session_name=session_name,
                    env=env,
                    cwd=cwd,
                    timeout=min(self._timeout, 15.0),
                )
                if connect_error:
                    return connect_error
                self._active_sessions.add(session_name)
                self._dicloak_leases[session_name] = {
                    "profile_id": profile_id,
                    "debug_port": debug_port,
                    "opened_at": data.get("serial_number"),
                }
                self._dicloak_last_open = {
                    "ok": True,
                    "profile_id": profile_id,
                    "session_name": session_name,
                    "debug_port": debug_port,
                }
                return self._truncate(json.dumps({
                    "profile_id": profile_id,
                    "debug_port": debug_port,
                    "agent_browser": connect_output or "connected",
                    "status": "opened",
                }, ensure_ascii=False))

            if action == "close_profile":
                profile_id = parts[2] if len(parts) >= 3 else str((self._dicloak_leases.get(session_name) or {}).get("profile_id") or "")
                if not profile_id:
                    return "Error: no DICloak profile is currently leased for this session."
                if self._cli_path:
                    env = self._build_env()
                    cwd = str(self._workspace) if self._workspace else None
                    await self._run_step(
                        step_args=["close"],
                        session_name=session_name,
                        env=env,
                        cwd=cwd,
                        timeout=min(self._timeout, 10.0),
                    )
                response = await client.patch(f"{self._dicloak_api_base_url}/v1/env/{profile_id}/close", headers=headers)
                payload = response.json()
                if response.status_code != 200 or payload.get("code") != 0:
                    self._dicloak_last_close = {
                        "ok": False,
                        "profile_id": profile_id,
                        "session_name": session_name,
                        "error": payload.get("msg") or response.text,
                    }
                    return f"Error: DICloak close_profile failed: {payload.get('msg') or response.text}"
                self._dicloak_leases.pop(session_name, None)
                self._dicloak_last_close = {
                    "ok": True,
                    "profile_id": profile_id,
                    "session_name": session_name,
                }
                return f"DICloak profile closed: {profile_id}"

        return "Error: unsupported DICloak command. Supported: list_profiles, open_profile, close_profile."

    def get_dicloak_runtime_status(self) -> dict[str, Any]:
        leases = [
            {
                "session_name": session_name,
                "profile_id": str(data.get("profile_id") or ""),
                "debug_port": data.get("debug_port"),
            }
            for session_name, data in sorted(self._dicloak_leases.items())
        ]
        return {
            "enabled": self._dicloak_enabled and bool(self._dicloak_api_base_url and self._dicloak_api_key),
            "lease_count": len(leases),
            "leases": leases,
            "last_open": dict(self._dicloak_last_open or {}),
            "last_close": dict(self._dicloak_last_close or {}),
        }

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
        """Reserved for future browser-side path policy hooks.

        LemonClaw currently runs in full-power mode, so browser save/export
        commands are not sandboxed to the workspace here. Container/runtime
        isolation remains the intended boundary.
        """
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
