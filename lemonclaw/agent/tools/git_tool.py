"""Structured git inspection tool."""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from typing import Any

from lemonclaw.agent.tools.base import Tool

_READ_ACTIONS = {"status", "diff", "show", "log", "branch"}
_WRITE_ACTIONS = {"commit", "apply_patch", "push"}


class GitTool(Tool):
    """Structured git operations with guarded local write support."""

    def __init__(
        self,
        *,
        working_dir: str | None = None,
        timeout: int = 20,
        max_output: int = 50_000,
        max_patch_bytes: int = 200_000,
        auth_profiles: dict[str, dict[str, str]] | None = None,
    ):
        self.working_dir = working_dir
        self.timeout = timeout
        self.max_output = max_output
        self.max_patch_bytes = max_patch_bytes
        self.auth_profiles = auth_profiles or {}

    @property
    def name(self) -> str:
        return "git"

    @property
    def description(self) -> str:
        return (
            "Inspect or safely mutate local git state using structured subcommands. "
            "Supports status, diff, show, log, branch, commit, apply_patch, and push. "
            "Use auth_profile for remote push instead of embedding tokens in shell commands. "
            "Use this instead of shell git for common repository work."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": sorted(_READ_ACTIONS | _WRITE_ACTIONS),
                    "description": "Git action to perform.",
                },
                "target": {
                    "type": "string",
                    "description": "Optional ref, commit, branch, or push refspec target.",
                },
                "remote": {
                    "type": "string",
                    "description": "Optional remote name for action=push. Defaults to origin.",
                },
                "pathspec": {
                    "type": "string",
                    "description": "Optional file or path scope.",
                },
                "paths": {
                    "type": "array",
                    "description": "Optional list of file paths to stage for commit.",
                    "items": {"type": "string"},
                },
                "message": {
                    "type": "string",
                    "description": "Commit message for action=commit.",
                    "minLength": 1,
                },
                "patch": {
                    "type": "string",
                    "description": "Unified diff patch for action=apply_patch.",
                    "minLength": 1,
                },
                "auth_profile": {
                    "type": "string",
                    "description": "Optional named git auth profile configured in tools.git.auth_profiles for action=push.",
                },
                "set_upstream": {
                    "type": "boolean",
                    "description": "If true, pass --set-upstream when pushing.",
                },
                "check": {
                    "type": "boolean",
                    "description": "If true, validate patch applicability without applying it.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Optional limit for log output.",
                },
                "working_dir": {
                    "type": "string",
                    "description": "Optional working directory override.",
                },
            },
            "required": ["action"],
        }

    def resolve_capability(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> str:
        action = str(params.get("action", "")).strip()
        if action in _READ_ACTIONS:
            return "git.read"
        if action == "push":
            return "git.write.remote"
        return "git.write.local"

    async def execute(
        self,
        action: str,
        target: str | None = None,
        pathspec: str | None = None,
        paths: list[str] | None = None,
        message: str | None = None,
        patch: str | None = None,
        remote: str | None = None,
        auth_profile: str | None = None,
        set_upstream: bool = False,
        check: bool = False,
        limit: int | None = None,
        working_dir: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        cwd = self._resolve_cwd(working_dir)
        if action in _READ_ACTIONS:
            return await self._run_action(
                cwd=cwd,
                action=action,
                args=self._build_read_args(action, target, pathspec, limit),
            )
        if action == "commit":
            return await self._commit(cwd=cwd, message=message, paths=paths)
        if action == "apply_patch":
            return await self._apply_patch(cwd=cwd, patch=patch, check=check)
        if action == "push":
            return await self._push(
                cwd=cwd,
                remote=remote,
                target=target,
                auth_profile=auth_profile,
                set_upstream=set_upstream,
            )
        return {"ok": False, "summary": f"Unsupported git action '{action}'", "raw": {"action": action}}

    async def _commit(self, *, cwd: Path, message: str | None, paths: list[str] | None) -> dict[str, Any]:
        if not message or not message.strip():
            return {"ok": False, "summary": "commit requires a non-empty message", "raw": {"action": "commit"}}
        normalized_paths, error = self._normalize_paths(cwd, paths or [])
        if error:
            return {"ok": False, "summary": error, "raw": {"action": "commit", "paths": paths or []}}
        if normalized_paths:
            add_result = await self._run_action(
                cwd=cwd,
                action="add",
                args=["add", "--", *normalized_paths],
            )
            if not add_result["ok"]:
                add_result["summary"] = f"git add failed before commit: {add_result['summary']}"
                return add_result

        commit_result = await self._run_action(
            cwd=cwd,
            action="commit",
            args=["commit", "-m", message.strip(), "--no-verify"],
        )
        if commit_result["ok"]:
            commit_result["summary"] = f"Committed local changes: {message.strip()}"
        return commit_result

    async def _apply_patch(self, *, cwd: Path, patch: str | None, check: bool) -> dict[str, Any]:
        if not patch:
            return {"ok": False, "summary": "apply_patch requires a unified diff patch", "raw": {"action": "apply_patch"}}
        patch_bytes = patch.encode("utf-8")
        if len(patch_bytes) > self.max_patch_bytes:
            return {
                "ok": False,
                "summary": f"Patch exceeds max_patch_bytes ({self.max_patch_bytes})",
                "raw": {"action": "apply_patch", "size": len(patch_bytes)},
            }

        check_result = await self._run_action(
            cwd=cwd,
            action="apply_patch_check",
            args=["apply", "--check", "--verbose", "-"],
            stdin=patch_bytes,
        )
        if not check_result["ok"]:
            check_result["summary"] = f"Patch validation failed: {check_result['summary']}"
            return check_result
        if check:
            check_result["summary"] = "Patch validated successfully"
            return check_result

        apply_result = await self._run_action(
            cwd=cwd,
            action="apply_patch",
            args=["apply", "--whitespace=nowarn", "-"],
            stdin=patch_bytes,
        )
        if apply_result["ok"]:
            apply_result["summary"] = "Patch applied successfully"
        return apply_result

    async def _push(
        self,
        *,
        cwd: Path,
        remote: str | None,
        target: str | None,
        auth_profile: str | None,
        set_upstream: bool,
    ) -> dict[str, Any]:
        remote_name = str(remote or "origin").strip() or "origin"
        refspec = str(target or "").strip()
        if not refspec:
            branch_result = await self._run_action(
                cwd=cwd,
                action="branch_current",
                args=["branch", "--show-current"],
            )
            if not branch_result["ok"]:
                branch_result["summary"] = f"Unable to determine current branch: {branch_result['summary']}"
                return branch_result
            refspec = str(branch_result["raw"].get("stdout") or "").strip()
            if not refspec:
                return {"ok": False, "summary": "Unable to determine current branch for push", "raw": {"remote": remote_name}}

        env = None
        askpass_path: str | None = None
        try:
            if auth_profile:
                profile = dict(self.auth_profiles.get(auth_profile) or {})
                if not profile:
                    return {"ok": False, "summary": f"Unknown git auth profile '{auth_profile}'", "raw": {"auth_profile": auth_profile}}

                username = str(profile.get("username") or "x-access-token").strip() or "x-access-token"
                password = str(profile.get("password") or "").strip()
                if not password:
                    return {"ok": False, "summary": f"Git auth profile '{auth_profile}' is missing a password/token", "raw": {"auth_profile": auth_profile}}

                remote_url_result = await self._run_action(
                    cwd=cwd,
                    action="remote_get_url",
                    args=["remote", "get-url", remote_name],
                )
                if not remote_url_result["ok"]:
                    remote_url_result["summary"] = f"Unable to inspect remote '{remote_name}': {remote_url_result['summary']}"
                    return remote_url_result
                remote_url = str(remote_url_result["raw"].get("stdout") or "").strip()
                if not remote_url.startswith(("https://", "http://")):
                    return {
                        "ok": False,
                        "summary": f"Git auth profile '{auth_profile}' requires an http/https remote; got '{remote_url or remote_name}'",
                        "raw": {"remote": remote_name, "auth_profile": auth_profile},
                    }

                askpass_path = self._write_askpass_script()
                env = os.environ.copy()
                env.update({
                    "GIT_TERMINAL_PROMPT": "0",
                    "GIT_ASKPASS": askpass_path,
                    "LC_GIT_USERNAME": username,
                    "LC_GIT_PASSWORD": password,
                })

            args = ["push"]
            if set_upstream:
                args.append("--set-upstream")
            args.extend([remote_name, refspec])
            push_result = await self._run_action(
                cwd=cwd,
                action="push",
                args=args,
                env=env,
            )
            if push_result["ok"]:
                push_result["summary"] = f"Pushed {refspec} to {remote_name}"
            return push_result
        finally:
            if askpass_path:
                try:
                    os.remove(askpass_path)
                except OSError:
                    pass

    async def _run_action(
        self,
        *,
        cwd: Path,
        action: str,
        args: list[str],
        stdin: bytes | None = None,
        env: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        git_args = ["git", *args]
        try:
            stdout, stderr, exit_code = await self._spawn_git(cwd=cwd, git_args=git_args, stdin=stdin, env=env)
        except asyncio.TimeoutError:
            return {"ok": False, "summary": f"git {action} timed out after {self.timeout}s", "raw": {"action": action}}
        except Exception as e:
            return {"ok": False, "summary": f"git {action} failed: {e}", "raw": {"action": action}}

        out = stdout.decode("utf-8", errors="replace")
        err = stderr.decode("utf-8", errors="replace")
        body = out if out.strip() else err
        if len(body) > self.max_output:
            body = body[:self.max_output] + f"\n... (truncated, {len(body) - self.max_output} more chars)"
        return {
            "ok": exit_code == 0,
            "summary": f"git {action} -> exit {exit_code}",
            "raw": {
                "action": action,
                "args": args,
                "cwd": str(cwd),
                "stdout": out,
                "stderr": err,
                "exit_code": exit_code,
                "body": body,
            },
        }

    def _resolve_cwd(self, working_dir: str | None) -> Path:
        base_dir = Path(self.working_dir or ".").resolve()
        if not working_dir:
            return base_dir
        raw = Path(working_dir).expanduser()
        return raw.resolve() if raw.is_absolute() else (base_dir / raw).resolve()

    async def _spawn_git(
        self,
        *,
        cwd: Path,
        git_args: list[str],
        stdin: bytes | None = None,
        env: dict[str, str] | None = None,
    ) -> tuple[bytes, bytes, int]:
        try:
            process = await asyncio.create_subprocess_exec(
                *git_args,
                stdin=asyncio.subprocess.PIPE if stdin is not None else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd),
                env=env,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(stdin), timeout=self.timeout)
            return stdout, stderr, process.returncode
        except asyncio.TimeoutError:
            process.kill()
            try:
                await asyncio.wait_for(process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                pass
            raise

    @staticmethod
    def _write_askpass_script() -> str:
        fd, path = tempfile.mkstemp(prefix="lc-git-askpass-", suffix=".sh")
        script = (
            "#!/bin/sh\n"
            "case \"$1\" in\n"
            "  *Username*) printf '%s\\n' \"$LC_GIT_USERNAME\" ;;\n"
            "  *Password*) printf '%s\\n' \"$LC_GIT_PASSWORD\" ;;\n"
            "  *) exit 1 ;;\n"
            "esac\n"
        )
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(script)
        os.chmod(path, 0o700)
        return path

    @staticmethod
    def _build_read_args(action: str, target: str | None, pathspec: str | None, limit: int | None) -> list[str]:
        if action == "status":
            args = ["status", "--short", "--branch"]
            if pathspec:
                args.extend(["--", pathspec])
            return args
        if action == "diff":
            args = ["diff", "--no-ext-diff"]
            if target:
                args.append(target)
            if pathspec:
                args.extend(["--", pathspec])
            return args
        if action == "show":
            args = ["show", "--stat", target or "HEAD"]
            if pathspec:
                args.extend(["--", pathspec])
            return args
        if action == "log":
            args = ["log", "--oneline", f"-n{limit or 10}"]
            if target:
                args.append(target)
            return args
        if action == "branch":
            if target == "current":
                return ["branch", "--show-current"]
            return ["branch", "--list", target or "*"]
        raise ValueError(f"Unsupported git action '{action}'")

    @staticmethod
    def _normalize_paths(cwd: Path, paths: list[str]) -> tuple[list[str], str | None]:
        normalized: list[str] = []
        for raw in paths:
            path = str(raw or "").strip()
            if not path:
                return [], "paths entries must be non-empty strings"
            if path.startswith("-"):
                return [], f"Invalid path '{path}'"
            resolved = (cwd / path).resolve()
            try:
                resolved.relative_to(cwd)
            except ValueError:
                return [], f"Path '{path}' escapes working_dir"
            normalized.append(path)
        return normalized, None
