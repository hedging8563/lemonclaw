"""Structured Kubernetes operator tool."""

from __future__ import annotations

import asyncio
import json
import re
import secrets
import time
from pathlib import Path
from typing import Any

from lemonclaw.agent.tools.base import Tool

_RESOURCE_TYPES = {
    "pod",
    "deployment",
    "service",
    "statefulset",
    "daemonset",
    "job",
    "cronjob",
    "configmap",
    "ingress",
}
_LOG_RESOURCE_TYPES = {"pod", "deployment", "statefulset", "daemonset", "job"}
_ROLLOUT_RESOURCE_TYPES = {"deployment", "statefulset", "daemonset"}
_SCALABLE_RESOURCE_TYPES = {"deployment", "statefulset"}
_SAFE_NAME_RE = re.compile(r"^[a-z0-9](?:[-a-z0-9_.]*[a-z0-9])?$")


def _valid_name(value: str) -> bool:
    return bool(value) and bool(_SAFE_NAME_RE.fullmatch(value))


class K8sTool(Tool):
    """Run a guarded subset of kubectl for cluster inspection and rollouts."""

    def __init__(
        self,
        *,
        timeout: int = 30,
        default_namespace: str = "",
        allowed_namespaces: list[str] | None = None,
        kubeconfig: str = "",
        context: str = "",
        max_items: int = 50,
        max_output: int = 50_000,
        confirmation_ttl: int = 120,
    ):
        self.timeout = timeout
        self.default_namespace = default_namespace.strip()
        self.allowed_namespaces = [ns.strip() for ns in (allowed_namespaces or []) if ns.strip()]
        self.kubeconfig = kubeconfig.strip()
        self.context = context.strip()
        self.max_items = max_items
        self.max_output = max_output
        self.confirmation_ttl = confirmation_ttl
        self._confirmations: dict[str, dict[str, Any]] = {}

    @property
    def name(self) -> str:
        return "k8s"

    @property
    def description(self) -> str:
        return (
            "Inspect Kubernetes resources and perform guarded rollout actions. "
            "Supports get, describe, logs, events, rollout_status, restart, and scale."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["get", "describe", "logs", "events", "rollout_status", "restart", "scale"],
                    "description": "Kubernetes action to perform.",
                },
                "resource_type": {
                    "type": "string",
                    "enum": sorted(_RESOURCE_TYPES),
                    "description": "Target Kubernetes resource type.",
                },
                "name": {
                    "type": "string",
                    "description": "Resource name for single-resource actions.",
                },
                "namespace": {
                    "type": "string",
                    "description": "Namespace override. Falls back to tools.k8s.default_namespace.",
                },
                "container": {
                    "type": "string",
                    "description": "Optional container name for logs.",
                },
                "tail_lines": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 2000,
                    "description": "Tail size for logs.",
                },
                "replicas": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 1000,
                    "description": "Replica count for action=scale.",
                },
                "confirm_token": {
                    "type": "string",
                    "description": "Required on the second call for destructive actions like restart or scale.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 500,
                    "description": "Maximum number of JSON list items to return.",
                },
                "timeout": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 300,
                    "description": "Optional command timeout override in seconds.",
                },
            },
            "required": ["action"],
        }

    def resolve_capability(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> str:
        action = params.get("action")
        if action == "restart":
            return "k8s.rollout.restart"
        if action == "scale":
            return "k8s.scale"
        return "k8s.read"

    async def execute(
        self,
        action: str,
        resource_type: str | None = None,
        name: str | None = None,
        namespace: str | None = None,
        container: str | None = None,
        tail_lines: int | None = None,
        replicas: int | None = None,
        confirm_token: str | None = None,
        limit: int | None = None,
        timeout: int | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        action = action.strip()
        namespace = (namespace or self.default_namespace).strip()
        task_id = str(kwargs.get("_task_id", "") or "")
        command_timeout = timeout or self.timeout
        if self.allowed_namespaces:
            if not namespace:
                return {
                    "ok": False,
                    "summary": "Namespace must be explicit when allowed_namespaces is configured",
                    "raw": {"allowed_namespaces": self.allowed_namespaces},
                }
            if namespace not in self.allowed_namespaces:
                return {
                    "ok": False,
                    "summary": f"Namespace '{namespace}' is not allowed",
                    "raw": {"namespace": namespace, "allowed_namespaces": self.allowed_namespaces},
                }
        if namespace and not _valid_name(namespace):
            return {"ok": False, "summary": f"Invalid namespace '{namespace}'", "raw": {"namespace": namespace}}

        if action == "events":
            command = self._base_command(namespace)
            command.extend(["get", "events", "--sort-by=.metadata.creationTimestamp", "-o", "json"])
            return await self._run_json_command(
                action=action,
                command=command,
                namespace=namespace,
                resource_type="event",
                limit=limit,
                summary_name="event",
                command_timeout=command_timeout,
            )

        if resource_type not in _RESOURCE_TYPES:
            return {
                "ok": False,
                "summary": "resource_type is required for this action",
                "raw": {"action": action, "resource_type": resource_type},
            }
        if name and not _valid_name(name):
            return {"ok": False, "summary": f"Invalid resource name '{name}'", "raw": {"name": name}}
        if container and not _valid_name(container):
            return {"ok": False, "summary": f"Invalid container name '{container}'", "raw": {"container": container}}

        if action == "get":
            command = self._base_command(namespace)
            command.extend(["get", resource_type])
            if name:
                command.append(name)
            command.extend(["-o", "json"])
            summary_name = f"{resource_type}/{name}" if name else resource_type
            return await self._run_json_command(
                action=action,
                command=command,
                namespace=namespace,
                resource_type=resource_type,
                limit=limit,
                summary_name=summary_name,
                command_timeout=command_timeout,
            )

        if action == "describe":
            if not name:
                return {"ok": False, "summary": "name is required for describe", "raw": {"resource_type": resource_type}}
            command = self._base_command(namespace)
            command.extend(["describe", resource_type, name])
            return await self._run_text_command(
                action=action,
                command=command,
                namespace=namespace,
                target=f"{resource_type}/{name}",
                command_timeout=command_timeout,
            )

        if action == "logs":
            if resource_type not in _LOG_RESOURCE_TYPES:
                return {
                    "ok": False,
                    "summary": f"logs does not support resource_type '{resource_type}'",
                    "raw": {"resource_type": resource_type},
                }
            if not name:
                return {"ok": False, "summary": "name is required for logs", "raw": {"resource_type": resource_type}}
            command = self._base_command(namespace)
            command.extend(["logs", f"{resource_type}/{name}", f"--tail={tail_lines or 200}"])
            if container:
                command.extend(["-c", container])
            return await self._run_text_command(
                action=action,
                command=command,
                namespace=namespace,
                target=f"{resource_type}/{name}",
                command_timeout=command_timeout,
            )

        if action == "rollout_status":
            if resource_type not in _ROLLOUT_RESOURCE_TYPES:
                return {
                    "ok": False,
                    "summary": f"rollout_status does not support resource_type '{resource_type}'",
                    "raw": {"resource_type": resource_type},
                }
            if not name:
                return {"ok": False, "summary": "name is required for rollout_status", "raw": {"resource_type": resource_type}}
            command = self._base_command(namespace)
            command.extend(["rollout", "status", f"{resource_type}/{name}", f"--timeout={command_timeout}s"])
            return await self._run_text_command(
                action=action,
                command=command,
                namespace=namespace,
                target=f"{resource_type}/{name}",
                command_timeout=command_timeout,
            )

        if action == "restart":
            if resource_type not in _ROLLOUT_RESOURCE_TYPES:
                return {
                    "ok": False,
                    "summary": f"restart does not support resource_type '{resource_type}'",
                    "raw": {"resource_type": resource_type},
                }
            if not name:
                return {"ok": False, "summary": "name is required for restart", "raw": {"resource_type": resource_type}}
            confirmation = self._require_confirmation(
                action=action,
                resource_type=resource_type,
                name=name,
                namespace=namespace,
                replicas=None,
                confirm_token=confirm_token,
                task_id=task_id,
            )
            if confirmation is not None:
                return confirmation
            command = self._base_command(namespace)
            command.extend(["rollout", "restart", f"{resource_type}/{name}"])
            return await self._run_text_command(
                action=action,
                command=command,
                namespace=namespace,
                target=f"{resource_type}/{name}",
                command_timeout=command_timeout,
            )

        if action == "scale":
            if resource_type not in _SCALABLE_RESOURCE_TYPES:
                return {
                    "ok": False,
                    "summary": f"scale does not support resource_type '{resource_type}'",
                    "raw": {"resource_type": resource_type},
                }
            if not name:
                return {"ok": False, "summary": "name is required for scale", "raw": {"resource_type": resource_type}}
            if replicas is None:
                return {"ok": False, "summary": "replicas is required for scale", "raw": {"resource_type": resource_type}}
            confirmation = self._require_confirmation(
                action=action,
                resource_type=resource_type,
                name=name,
                namespace=namespace,
                replicas=replicas,
                confirm_token=confirm_token,
                task_id=task_id,
            )
            if confirmation is not None:
                return confirmation
            command = self._base_command(namespace)
            command.extend(["scale", f"{resource_type}/{name}", f"--replicas={replicas}"])
            return await self._run_text_command(
                action=action,
                command=command,
                namespace=namespace,
                target=f"{resource_type}/{name}",
                command_timeout=command_timeout,
            )

        return {"ok": False, "summary": f"Unsupported action '{action}'", "raw": {"action": action}}

    def _base_command(self, namespace: str) -> list[str]:
        command = ["kubectl"]
        if self.kubeconfig:
            kubeconfig_path = str(Path(self.kubeconfig).expanduser())
            command.extend(["--kubeconfig", kubeconfig_path])
        if self.context:
            command.extend(["--context", self.context])
        if namespace:
            command.extend(["-n", namespace])
        return command

    async def _run_json_command(
        self,
        *,
        action: str,
        command: list[str],
        namespace: str,
        resource_type: str,
        limit: int | None,
        summary_name: str,
        command_timeout: int,
    ) -> dict[str, Any]:
        result = await self._run_process(command, command_timeout)
        stdout = result["stdout"]
        if result["ok"]:
            try:
                payload = json.loads(stdout or "{}")
                payload, item_count, truncated = self._trim_payload(payload, limit or self.max_items)
                result["summary"] = self._json_summary(action, summary_name, item_count, namespace, truncated)
                result["raw"].update({
                    "resource_type": resource_type,
                    "namespace": namespace,
                    "body": payload,
                    "item_count": item_count,
                    "truncated_count": truncated,
                })
                return result
            except json.JSONDecodeError:
                pass
        body = self._truncate_text(stdout if stdout.strip() else result["stderr"])
        result["summary"] = f"kubectl {action} {summary_name} -> exit {result['raw']['exit_code']}"
        result["raw"].update({"resource_type": resource_type, "namespace": namespace, "body": body})
        return result

    async def _run_text_command(
        self,
        *,
        action: str,
        command: list[str],
        namespace: str,
        target: str,
        command_timeout: int,
    ) -> dict[str, Any]:
        result = await self._run_process(command, command_timeout)
        body = self._truncate_text(result["stdout"] if result["stdout"].strip() else result["stderr"])
        if result["ok"]:
            result["summary"] = self._text_summary(action, target, namespace, body)
        result["raw"].update({"namespace": namespace, "target": target, "body": body})
        return result

    async def _run_process(self, command: list[str], command_timeout: int) -> dict[str, Any]:
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=command_timeout)
        except asyncio.TimeoutError:
            process.kill()
            try:
                await asyncio.wait_for(process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                pass
            return {
                "ok": False,
                "summary": f"kubectl timed out after {command_timeout}s",
                "raw": {"command": command, "exit_code": None},
                "stdout": "",
                "stderr": "",
            }
        except FileNotFoundError:
            return {
                "ok": False,
                "summary": "kubectl is not installed or not available in PATH",
                "raw": {"command": command, "exit_code": None},
                "stdout": "",
                "stderr": "",
            }
        except Exception as e:
            return {
                "ok": False,
                "summary": f"kubectl failed: {e}",
                "raw": {"command": command, "exit_code": None},
                "stdout": "",
                "stderr": str(e),
            }

        out = stdout.decode("utf-8", errors="replace")
        err = stderr.decode("utf-8", errors="replace")
        exit_code = process.returncode
        return {
            "ok": exit_code == 0,
            "summary": f"kubectl -> exit {exit_code}",
            "raw": {"command": command, "exit_code": exit_code, "stdout": out, "stderr": err},
            "stdout": out,
            "stderr": err,
        }

    def _trim_payload(self, payload: Any, limit: int) -> tuple[Any, int, int]:
        if isinstance(payload, dict) and isinstance(payload.get("items"), list):
            items = payload.get("items", [])
            item_count = len(items)
            truncated = max(item_count - limit, 0)
            if truncated:
                payload = dict(payload)
                payload["items"] = items[:limit]
            return payload, item_count, truncated
        return payload, 1 if payload else 0, 0

    def _truncate_text(self, value: str) -> str:
        if len(value) <= self.max_output:
            return value
        remaining = len(value) - self.max_output
        return value[:self.max_output] + f"\n... (truncated, {remaining} more chars)"

    def _require_confirmation(
        self,
        *,
        action: str,
        resource_type: str,
        name: str,
        namespace: str,
        replicas: int | None,
        confirm_token: str | None,
        task_id: str,
    ) -> dict[str, Any] | None:
        self._prune_confirmations()
        target = self._confirmation_target(
            action=action,
            resource_type=resource_type,
            name=name,
            namespace=namespace,
            replicas=replicas,
        )
        if confirm_token:
            record = self._confirmations.pop(confirm_token, None)
            if not record:
                return {
                    "ok": False,
                    "summary": "Invalid or expired confirm_token for destructive K8s action",
                    "raw": {"confirmation_required": True, "action": action, "target": target},
                }
            if record["target"] != target:
                return {
                    "ok": False,
                    "summary": "confirm_token does not match the current K8s target",
                    "raw": {"confirmation_required": True, "action": action, "target": target},
                }
            if record["task_id"] and task_id and record["task_id"] != task_id:
                return {
                    "ok": False,
                    "summary": "confirm_token was issued for a different task",
                    "raw": {"confirmation_required": True, "action": action, "target": target},
                }
            return None

        token = secrets.token_hex(6)
        expires_at = time.time() + self.confirmation_ttl
        self._confirmations[token] = {
            "target": target,
            "task_id": task_id,
            "expires_at": expires_at,
        }
        return {
            "ok": False,
            "summary": f"Confirmation required for k8s {action} on {target}. Repeat the same call with confirm_token.",
            "raw": {
                "confirmation_required": True,
                "confirm_token": token,
                "expires_at": expires_at,
                "action": action,
                "target": target,
            },
        }

    def _prune_confirmations(self) -> None:
        now = time.time()
        expired = [token for token, record in self._confirmations.items() if record.get("expires_at", 0) <= now]
        for token in expired:
            self._confirmations.pop(token, None)

    @staticmethod
    def _confirmation_target(
        *,
        action: str,
        resource_type: str,
        name: str,
        namespace: str,
        replicas: int | None,
    ) -> str:
        base = f"{action}:{resource_type}/{name}@{namespace or '-'}"
        if replicas is not None:
            return f"{base}:replicas={replicas}"
        return base

    @staticmethod
    def _json_summary(action: str, summary_name: str, item_count: int, namespace: str, truncated: int) -> str:
        location = f" in namespace {namespace}" if namespace else ""
        if truncated:
            return f"kubectl {action} {summary_name}{location}: {item_count} item(s), returning first {item_count - truncated}"
        return f"kubectl {action} {summary_name}{location}: {item_count} item(s)"

    @staticmethod
    def _text_summary(action: str, target: str, namespace: str, body: str) -> str:
        location = f" in namespace {namespace}" if namespace else ""
        first_line = body.strip().splitlines()[0] if body.strip() else ""
        if action == "restart":
            return first_line or f"Restart requested for {target}{location}"
        if action == "rollout_status":
            return first_line or f"Checked rollout status for {target}{location}"
        if action == "describe":
            return first_line or f"Described {target}{location}"
        if action == "logs":
            return f"Fetched logs for {target}{location}"
        if action == "scale":
            return first_line or f"Scaled {target}{location}"
        return first_line or f"kubectl {action} {target}{location}"
