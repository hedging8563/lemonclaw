"""Governance runtime for capability-aware authorization and audit."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from lemonclaw.governance.audit import append_audit_record, read_audit_records
from lemonclaw.governance.kill_switch import (
    is_kill_switched,
    load_kill_switch_state,
    patch_kill_switch_state,
)
from lemonclaw.governance.redaction import redact_sensitive_value
from lemonclaw.governance.token import issue_capability_token, validate_capability_token
from lemonclaw.governance.types import (
    ApprovalPolicy,
    AuditRecord,
    AuthorizationDecision,
    AutonomyCap,
    CapabilityDefinition,
    CapabilityToken,
    IdentityMode,
    RiskLevel,
)

_HIGH_RISK_LEVELS = {
    RiskLevel.LOCAL_MUTATION,
    RiskLevel.EXTERNAL_WRITE,
    RiskLevel.DESTRUCTIVE,
}
_SANDBOX_GUARDED_CAPABILITIES = {
    "http.write",
    "git.write.local",
    "git.write.remote",
    "k8s.rollout.restart",
    "k8s.scale",
    "exec.read",
    "exec.write",
    "exec.network",
    "exec.package",
    "exec.system",
    "browser.read",
    "browser.interact",
    "spawn.agent",
    "cron.read",
    "cron.write",
    "message.send",
}
_CAPABILITY_SPECS: dict[str, dict[str, Any]] = {
    "http.read": {
        "tool_name": "http_request",
        "category": "http",
        "risk_level": RiskLevel.READ_ONLY,
        "side_effect_level": "none",
        "identity_mode": IdentityMode.SERVICE_ACCOUNT,
    },
    "http.write": {
        "tool_name": "http_request",
        "category": "http",
        "risk_level": RiskLevel.EXTERNAL_WRITE,
        "side_effect_level": "external_write",
        "identity_mode": IdentityMode.SERVICE_ACCOUNT,
        "requires_secrets": True,
        "network_scope": "egress",
    },
    "notify.channel.send": {
        "tool_name": "notify",
        "category": "messaging",
        "risk_level": RiskLevel.EXTERNAL_WRITE,
        "side_effect_level": "external_write",
        "identity_mode": IdentityMode.SERVICE_ACCOUNT,
    },
    "notify.webhook.send": {
        "tool_name": "notify",
        "category": "messaging",
        "risk_level": RiskLevel.EXTERNAL_WRITE,
        "side_effect_level": "external_write",
        "identity_mode": IdentityMode.SERVICE_ACCOUNT,
        "network_scope": "egress",
    },
    "git.read": {
        "tool_name": "git",
        "category": "repository",
        "risk_level": RiskLevel.READ_ONLY,
        "side_effect_level": "none",
        "identity_mode": IdentityMode.SERVICE_ACCOUNT,
    },
    "git.write.local": {
        "tool_name": "git",
        "category": "repository",
        "risk_level": RiskLevel.LOCAL_MUTATION,
        "side_effect_level": "local",
        "identity_mode": IdentityMode.SERVICE_ACCOUNT,
        "filesystem_scope": "workspace",
    },
    "git.write.remote": {
        "tool_name": "git",
        "category": "repository",
        "risk_level": RiskLevel.EXTERNAL_WRITE,
        "approval_policy": ApprovalPolicy.REQUIRE_CONFIRM,
        "side_effect_level": "external_write",
        "identity_mode": IdentityMode.SERVICE_ACCOUNT,
        "requires_secrets": True,
        "network_scope": "egress",
    },
    "db.read": {
        "tool_name": "db",
        "category": "database",
        "risk_level": RiskLevel.READ_ONLY,
        "side_effect_level": "none",
        "identity_mode": IdentityMode.SERVICE_ACCOUNT,
        "requires_secrets": True,
    },
    "k8s.read": {
        "tool_name": "k8s",
        "category": "infrastructure",
        "risk_level": RiskLevel.READ_ONLY,
        "side_effect_level": "none",
        "identity_mode": IdentityMode.INSTANCE_IDENTITY,
    },
    "k8s.rollout.restart": {
        "tool_name": "k8s",
        "category": "infrastructure",
        "risk_level": RiskLevel.DESTRUCTIVE,
        "approval_policy": ApprovalPolicy.REQUIRE_CONFIRM,
        "side_effect_level": "external_write",
        "identity_mode": IdentityMode.INSTANCE_IDENTITY,
    },
    "k8s.scale": {
        "tool_name": "k8s",
        "category": "infrastructure",
        "risk_level": RiskLevel.DESTRUCTIVE,
        "approval_policy": ApprovalPolicy.REQUIRE_CONFIRM,
        "side_effect_level": "external_write",
        "identity_mode": IdentityMode.INSTANCE_IDENTITY,
    },
    "task.checkpoint.write": {
        "tool_name": "task_checkpoint",
        "category": "ledger",
        "risk_level": RiskLevel.LOCAL_MUTATION,
        "side_effect_level": "local",
        "identity_mode": IdentityMode.SERVICE_ACCOUNT,
    },
    "spawn.agent": {
        "tool_name": "spawn",
        "category": "agent",
        "risk_level": RiskLevel.LOCAL_MUTATION,
        "side_effect_level": "local",
        "identity_mode": IdentityMode.SERVICE_ACCOUNT,
        "supports_cancel": True,
    },
    "cron.read": {
        "tool_name": "cron",
        "category": "scheduler",
        "risk_level": RiskLevel.READ_ONLY,
        "side_effect_level": "none",
        "identity_mode": IdentityMode.SERVICE_ACCOUNT,
    },
    "cron.write": {
        "tool_name": "cron",
        "category": "scheduler",
        "risk_level": RiskLevel.EXTERNAL_WRITE,
        "side_effect_level": "external_write",
        "identity_mode": IdentityMode.SERVICE_ACCOUNT,
    },
    "message.send": {
        "tool_name": "message",
        "category": "messaging",
        "risk_level": RiskLevel.EXTERNAL_WRITE,
        "side_effect_level": "external_write",
        "identity_mode": IdentityMode.SERVICE_ACCOUNT,
    },
    "browser.read": {
        "tool_name": "browser",
        "category": "browser",
        "risk_level": RiskLevel.READ_ONLY,
        "side_effect_level": "none",
        "identity_mode": IdentityMode.SERVICE_ACCOUNT,
        "supports_cancel": True,
    },
    "browser.interact": {
        "tool_name": "browser",
        "category": "browser",
        "risk_level": RiskLevel.EXTERNAL_WRITE,
        "side_effect_level": "external_write",
        "identity_mode": IdentityMode.SERVICE_ACCOUNT,
        "supports_cancel": True,
    },
    "exec.read": {
        "tool_name": "exec",
        "category": "shell",
        "risk_level": RiskLevel.READ_ONLY,
        "side_effect_level": "none",
        "identity_mode": IdentityMode.INSTANCE_IDENTITY,
        "supports_cancel": True,
    },
    "exec.write": {
        "tool_name": "exec",
        "category": "shell",
        "risk_level": RiskLevel.LOCAL_MUTATION,
        "side_effect_level": "local",
        "identity_mode": IdentityMode.INSTANCE_IDENTITY,
        "supports_cancel": True,
        "filesystem_scope": "workspace",
    },
    "exec.network": {
        "tool_name": "exec",
        "category": "shell",
        "risk_level": RiskLevel.EXTERNAL_WRITE,
        "side_effect_level": "external_write",
        "identity_mode": IdentityMode.INSTANCE_IDENTITY,
        "supports_cancel": True,
        "network_scope": "egress",
    },
    "exec.package": {
        "tool_name": "exec",
        "category": "shell",
        "risk_level": RiskLevel.EXTERNAL_WRITE,
        "side_effect_level": "external_write",
        "identity_mode": IdentityMode.INSTANCE_IDENTITY,
        "supports_cancel": True,
        "network_scope": "egress",
        "filesystem_scope": "runtime",
    },
    "exec.system": {
        "tool_name": "exec",
        "category": "shell",
        "risk_level": RiskLevel.DESTRUCTIVE,
        "approval_policy": ApprovalPolicy.REQUIRE_CONFIRM,
        "side_effect_level": "external_write",
        "identity_mode": IdentityMode.INSTANCE_IDENTITY,
        "supports_cancel": True,
        "network_scope": "egress",
        "filesystem_scope": "runtime",
    },
}


def _obj_get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


class GovernanceRuntime:
    """Minimal local governance engine for tool execution."""

    def __init__(
        self,
        *,
        workspace: Path,
        config: Any | None = None,
        agent_id: str = "default",
    ):
        self.workspace = workspace
        self.config = config
        self.agent_id = agent_id

        self.enabled = bool(getattr(config, "enabled", True)) if config is not None else False
        self.default_autonomy_cap = AutonomyCap(
            getattr(config, "default_autonomy_cap", AutonomyCap.L1.value)
        ) if config is not None else AutonomyCap.L1
        self.token_ttl_seconds = int(getattr(config, "token_ttl_seconds", 900)) if config is not None else 900
        self.capability_overrides = dict(getattr(config, "capability_overrides", {}) or {}) if config is not None else {}
        self.secret_profiles = dict(getattr(config, "secret_profiles", {}) or {}) if config is not None else {}
        self.sandbox_profiles = dict(getattr(config, "sandbox_profiles", {}) or {}) if config is not None else {}
        self.identity_defaults = getattr(config, "identity_defaults", None) if config is not None else None
        default_state_dir = workspace / ".lemonclaw-state"
        self._kill_switch_path = Path(
            getattr(config, "kill_switch_file", str(default_state_dir / "governance.json"))
        ).expanduser()
        self._audit_log_path = Path(
            getattr(config, "audit_log_path", str(default_state_dir / "capability-audit.jsonl"))
        ).expanduser()
        budgets = getattr(config, "budgets", None)
        self._budget_snapshot = {
            "platform_daily_usd": getattr(budgets, "platform_daily_usd", None) if budgets is not None else None,
            "tenant_daily_usd": getattr(budgets, "tenant_daily_usd", None) if budgets is not None else None,
            "default_task_usd": getattr(budgets, "default_task_usd", None) if budgets is not None else None,
        }
        self._task_budget = self._budget_snapshot.get("default_task_usd")
        self._configured_secret_values = tuple(self._iter_configured_secret_values())

    def issue_token(
        self,
        *,
        task_id: str,
        tenant_id: str = "",
        mode: str = "chat",
        allowed_capabilities: list[str] | None = None,
    ) -> CapabilityToken:
        state = load_kill_switch_state(self._kill_switch_path)
        return issue_capability_token(
            task_id=task_id,
            tenant_id=tenant_id,
            mode=mode,
            ttl_seconds=self.token_ttl_seconds,
            allowed_capabilities=allowed_capabilities,
            autonomy_cap=self.default_autonomy_cap,
            cost_ceiling_usd=self._task_budget,
            kill_switch_epoch=int(state.get("epoch", 0)),
        )

    def validate_tool_call(
        self,
        *,
        capability: CapabilityDefinition,
        params: dict[str, Any],
        tool: Any | None = None,
    ) -> tuple[bool, str]:
        if not capability.sandbox_profile:
            return True, ""
        profile = self.sandbox_profiles.get(capability.sandbox_profile)
        if profile is None:
            return True, ""
        allowed_domains = [str(item).strip().lower() for item in (_obj_get(profile, "allowed_domains", []) or []) if str(item).strip()]
        allowed_paths = [str(item).strip() for item in (_obj_get(profile, "allowed_paths", []) or []) if str(item).strip()]
        blocked_commands = [str(item) for item in (_obj_get(profile, "blocked_commands", []) or []) if str(item)]
        max_timeout_seconds = _obj_get(profile, "max_timeout_seconds", None)
        allow_headed_browser = _obj_get(profile, "allow_headed_browser", None)
        require_content_boundaries = _obj_get(profile, "require_content_boundaries", None)

        if capability.tool_name == "exec":
            command = str(params.get("command") or "")
            for pattern in blocked_commands:
                if pattern and pattern.lower() in command.lower():
                    return False, f"command blocked by sandbox profile '{capability.sandbox_profile}'"
            working_dir = str(params.get("working_dir") or getattr(tool, "working_dir", "") or "")
            if allowed_paths and working_dir:
                target = Path(working_dir).expanduser().resolve()
                allowed = any(target.is_relative_to(Path(prefix).expanduser().resolve()) for prefix in allowed_paths)
                if not allowed:
                    return False, f"working_dir is outside sandbox profile '{capability.sandbox_profile}'"
            timeout = getattr(tool, "timeout", None)
            if max_timeout_seconds is not None and timeout is not None and timeout > int(max_timeout_seconds):
                return False, f"tool timeout exceeds sandbox profile '{capability.sandbox_profile}'"
        elif capability.tool_name == "browser":
            command = str(params.get("command") or "")
            if allowed_domains:
                for url in self._extract_urls(command):
                    host = (urlparse(url).hostname or "").lower()
                    if host and not self._host_matches(host, allowed_domains):
                        return False, f"browser target '{host}' is outside sandbox profile '{capability.sandbox_profile}'"
            headed = getattr(tool, "_headed", False)
            if allow_headed_browser is False and headed:
                return False, f"headed browser is disabled by sandbox profile '{capability.sandbox_profile}'"
            boundaries = getattr(tool, "_content_boundaries", True)
            if require_content_boundaries and not boundaries:
                return False, f"content boundaries are required by sandbox profile '{capability.sandbox_profile}'"
        elif capability.capability_id == "http.write":
            url = str(params.get("url") or "")
            host = (urlparse(url).hostname or "").lower()
            if allowed_domains and host and not self._host_matches(host, allowed_domains):
                return False, f"http target '{host}' is outside sandbox profile '{capability.sandbox_profile}'"
        return True, ""

    def authorize(
        self,
        *,
        capability_id: str,
        tool_name: str,
        token: CapabilityToken | None,
        tenant_id: str = "",
        mode: str = "chat",
    ) -> AuthorizationDecision:
        capability = self._resolve_definition(capability_id, tool_name)
        if not self.enabled:
            return AuthorizationDecision(allowed=True, capability=capability, warnings=self._definition_warnings(capability))
        if not capability.enabled:
            return AuthorizationDecision(False, capability, "capability disabled")
        if token is None:
            return AuthorizationDecision(False, capability, "missing capability token")

        allowed, reason = validate_capability_token(token, capability_id)
        if not allowed:
            return AuthorizationDecision(False, capability, reason)

        state = load_kill_switch_state(self._kill_switch_path)
        if int(state.get("epoch", 0)) > token.kill_switch_epoch:
            return AuthorizationDecision(False, capability, "kill switch epoch changed")
        if is_kill_switched(
            state,
            capability_id=capability_id,
            category=capability.category,
            tenant_id=tenant_id or token.tenant_id,
            agent_id=self.agent_id,
        ):
            return AuthorizationDecision(False, capability, "capability blocked by kill switch")

        if capability.approval_policy == ApprovalPolicy.DENY:
            return AuthorizationDecision(False, capability, "capability denied by policy")
        if capability.approval_policy == ApprovalPolicy.REQUIRE_CONFIRM and token.approval_state != "approved":
            return AuthorizationDecision(False, capability, "approval required")
        return AuthorizationDecision(True, capability, warnings=self._definition_warnings(capability))

    def record_audit(
        self,
        *,
        capability: CapabilityDefinition,
        token: CapabilityToken | None,
        task_id: str,
        mode: str,
        actor_identity: str,
        started_at: float,
        ended_at: float,
        params: dict[str, Any],
        result_status: str,
        warnings: list[str] | None = None,
    ) -> None:
        try:
            payload = repr(sorted(params.items())).encode("utf-8", errors="replace")
            input_hash = hashlib.sha256(payload).hexdigest()
            state = load_kill_switch_state(self._kill_switch_path)
            record = AuditRecord(
                task_id=task_id,
                capability_id=capability.capability_id,
                tool_name=capability.tool_name,
                mode=mode,
                risk_level=capability.risk_level.value,
                actor_identity=actor_identity,
                result_status=result_status,
                started_at=started_at,
                ended_at=ended_at,
                input_hash=input_hash,
                budget_snapshot={
                    **self._budget_snapshot,
                    "task_usd": token.cost_ceiling_usd if token and token.cost_ceiling_usd is not None else self._task_budget,
                    "policy": capability.budget_policy,
                },
                capability_token_id=token.token_id if token else "",
                kill_switch_state={
                    "epoch": state.get("epoch", 0),
                    "global": bool(state.get("global")),
                },
                tenant_id=token.tenant_id if token else "",
                secret_profile=capability.secret_profile,
                sandbox_profile=capability.sandbox_profile,
                approval_policy=capability.approval_policy.value,
                identity_mode=capability.identity_mode.value,
                warnings=list(warnings or ()),
            )
            append_audit_record(self._audit_log_path, record)
        except Exception:
            # Audit must never block tool execution.
            return

    def _resolve_definition(self, capability_id: str, tool_name: str) -> CapabilityDefinition:
        override = self.capability_overrides.get(capability_id, {})
        defaults = self._default_definition(capability_id, tool_name)
        for key, value in override.items():
            if key == "risk_level":
                defaults.risk_level = RiskLevel(value)
            elif key == "approval_policy":
                defaults.approval_policy = ApprovalPolicy(value)
            elif key == "identity_mode":
                defaults.identity_mode = IdentityMode(value)
            elif key == "autonomy_cap":
                defaults.autonomy_cap = AutonomyCap(value)
            elif hasattr(defaults, key):
                setattr(defaults, key, value)
        return defaults

    def get_governance_overview(self) -> dict[str, Any]:
        capabilities = self.list_capabilities_view()
        by_risk = {risk.value: 0 for risk in RiskLevel}
        by_category: dict[str, int] = {}
        disabled = []
        unbound_secret = []
        unbound_sandbox = []
        for item in capabilities:
            by_risk[str(item.get("risk_level") or RiskLevel.READ_ONLY.value)] = (
                by_risk.get(str(item.get("risk_level") or RiskLevel.READ_ONLY.value), 0) + 1
            )
            category = str(item.get("category") or "tool")
            by_category[category] = by_category.get(category, 0) + 1
            if not item.get("enabled", True):
                disabled.append(str(item.get("capability_id") or ""))
            if str(((item.get("secret_profile_status") or {}).get("state") or "")) in {"unbound", "missing"}:
                unbound_secret.append(str(item.get("capability_id") or ""))
            if str(((item.get("sandbox_profile_status") or {}).get("state") or "")) in {"unbound", "missing"}:
                unbound_sandbox.append(str(item.get("capability_id") or ""))
        return {
            "enabled": self.enabled,
            "default_autonomy_cap": self.default_autonomy_cap.value,
            "token_ttl_seconds": self.token_ttl_seconds,
            "identity_defaults": self._identity_defaults_view(),
            "budgets": dict(self._budget_snapshot),
            "capabilities": {
                "total": len(capabilities),
                "enabled_count": sum(1 for item in capabilities if item.get("enabled", True)),
                "disabled_count": len(disabled),
                "by_risk": by_risk,
                "by_category": by_category,
                "disabled_capabilities": disabled[:12],
                "unbound_secret_count": len(unbound_secret),
                "unbound_sandbox_count": len(unbound_sandbox),
                "unbound_secret_capabilities": unbound_secret[:12],
                "unbound_sandbox_capabilities": unbound_sandbox[:12],
            },
            "secret_profiles": {
                "count": len(self.secret_profiles),
                "configured_count": sum(1 for item in self.list_secret_profiles_view() if item.get("configured")),
            },
            "sandbox_profiles": {
                "count": len(self.sandbox_profiles),
            },
            "kill_switch": self.get_kill_switch_view(),
            "audit": {
                "path": str(self._audit_log_path),
                "recent_count": len(self.list_audit_view(limit=10)),
            },
        }

    def list_capabilities_view(self) -> list[dict[str, Any]]:
        capability_ids = sorted(set(_CAPABILITY_SPECS) | set(self.capability_overrides))
        items: list[dict[str, Any]] = []
        for capability_id in capability_ids:
            defaults = _CAPABILITY_SPECS.get(capability_id, {})
            tool_name = str(defaults.get("tool_name") or capability_id.split(".", 1)[0])
            definition = self._resolve_definition(capability_id, tool_name)
            warnings = self._definition_warnings(definition)
            items.append({
                **definition.to_dict(),
                "secret_profile_status": self._binding_status(
                    definition.secret_profile,
                    self.secret_profiles,
                    required=bool(definition.requires_secrets),
                ),
                "sandbox_profile_status": self._binding_status(
                    definition.sandbox_profile,
                    self.sandbox_profiles,
                    required=self._requires_sandbox_binding(definition),
                ),
                "warnings": warnings,
            })
        return items

    def list_secret_profiles_view(self) -> list[dict[str, Any]]:
        bindings = self._profile_bindings("secret_profile")
        items: list[dict[str, Any]] = []
        for name, profile in sorted(self.secret_profiles.items()):
            values = dict(_obj_get(profile, "values", {}) or {})
            items.append({
                "name": name,
                "kind": str(_obj_get(profile, "kind", "generic") or "generic"),
                "description": str(_obj_get(profile, "description", "") or ""),
                "fields": sorted(values.keys()),
                "configured": bool(values),
                "field_count": len(values),
                "bound_capabilities": bindings.get(name, []),
            })
        return items

    def list_sandbox_profiles_view(self) -> list[dict[str, Any]]:
        bindings = self._profile_bindings("sandbox_profile")
        items: list[dict[str, Any]] = []
        for name, profile in sorted(self.sandbox_profiles.items()):
            allowed_domains = list(_obj_get(profile, "allowed_domains", []) or [])
            allowed_paths = list(_obj_get(profile, "allowed_paths", []) or [])
            blocked_commands = list(_obj_get(profile, "blocked_commands", []) or [])
            items.append({
                "name": name,
                "allowed_domains": allowed_domains,
                "allowed_paths": allowed_paths,
                "blocked_commands": blocked_commands,
                "max_timeout_seconds": _obj_get(profile, "max_timeout_seconds", None),
                "allow_headed_browser": _obj_get(profile, "allow_headed_browser", None),
                "require_content_boundaries": _obj_get(profile, "require_content_boundaries", None),
                "bound_capabilities": bindings.get(name, []),
            })
        return items

    def get_kill_switch_view(self) -> dict[str, Any]:
        state = load_kill_switch_state(self._kill_switch_path)
        categories = {str(name): bool(value) for name, value in (state.get("categories") or {}).items() if value}
        capabilities = {str(name): bool(value) for name, value in (state.get("capabilities") or {}).items() if value}
        agents = {str(name): bool(value) for name, value in (state.get("agents") or {}).items() if value}
        tenants = {str(name): bool(value) for name, value in (state.get("tenants") or {}).items() if value}
        return {
            "path": str(self._kill_switch_path),
            "epoch": int(state.get("epoch", 0)),
            "global": bool(state.get("global")),
            "categories": categories,
            "capabilities": capabilities,
            "agents": agents,
            "tenants": tenants,
            "counts": {
                "categories": len(categories),
                "capabilities": len(capabilities),
                "agents": len(agents),
                "tenants": len(tenants),
            },
        }

    def list_audit_view(self, *, limit: int = 50) -> list[dict[str, Any]]:
        records = read_audit_records(self._audit_log_path, limit=limit)
        return [redact_sensitive_value(item, configured_secret_values=self._configured_secret_values) for item in records]

    def redact_payload(self, value: Any) -> Any:
        return redact_sensitive_value(value, configured_secret_values=self._configured_secret_values)

    def patch_kill_switch(self, patch: dict[str, Any]) -> dict[str, Any]:
        state = patch_kill_switch_state(self._kill_switch_path, patch)
        return {
            "state": self.get_kill_switch_view(),
            "epoch": int(state.get("epoch", 0)),
        }

    @staticmethod
    def _default_definition(capability_id: str, tool_name: str) -> CapabilityDefinition:
        spec = _CAPABILITY_SPECS.get(capability_id)
        if spec:
            payload = dict(spec)
            payload.setdefault("tool_name", tool_name)
            return CapabilityDefinition(capability_id=capability_id, **payload)
        mapping: dict[str, tuple[str, RiskLevel, ApprovalPolicy]] = {
            "read_file": ("filesystem", RiskLevel.READ_ONLY, ApprovalPolicy.AUTO),
            "read_attachment": ("filesystem", RiskLevel.READ_ONLY, ApprovalPolicy.AUTO),
            "list_dir": ("filesystem", RiskLevel.READ_ONLY, ApprovalPolicy.AUTO),
            "grep": ("search", RiskLevel.READ_ONLY, ApprovalPolicy.AUTO),
            "glob": ("search", RiskLevel.READ_ONLY, ApprovalPolicy.AUTO),
            "web_search": ("web", RiskLevel.READ_ONLY, ApprovalPolicy.AUTO),
            "web_fetch": ("web", RiskLevel.READ_ONLY, ApprovalPolicy.AUTO),
            "git": ("repository", RiskLevel.READ_ONLY, ApprovalPolicy.AUTO),
            "db": ("database", RiskLevel.READ_ONLY, ApprovalPolicy.AUTO),
            "k8s": ("infrastructure", RiskLevel.READ_ONLY, ApprovalPolicy.AUTO),
            "analyze_image": ("filesystem", RiskLevel.READ_ONLY, ApprovalPolicy.AUTO),
            "write_file": ("filesystem", RiskLevel.LOCAL_MUTATION, ApprovalPolicy.AUTO),
            "edit_file": ("filesystem", RiskLevel.LOCAL_MUTATION, ApprovalPolicy.AUTO),
            "coding": ("coding", RiskLevel.LOCAL_MUTATION, ApprovalPolicy.AUTO),
            "browser": ("browser", RiskLevel.LOCAL_MUTATION, ApprovalPolicy.AUTO),
            "exec": ("shell", RiskLevel.LOCAL_MUTATION, ApprovalPolicy.AUTO),
            "spawn": ("agent", RiskLevel.LOCAL_MUTATION, ApprovalPolicy.AUTO),
            "cron": ("scheduler", RiskLevel.EXTERNAL_WRITE, ApprovalPolicy.AUTO),
            "message": ("messaging", RiskLevel.EXTERNAL_WRITE, ApprovalPolicy.AUTO),
            "notify": ("messaging", RiskLevel.EXTERNAL_WRITE, ApprovalPolicy.AUTO),
            "task_checkpoint": ("ledger", RiskLevel.LOCAL_MUTATION, ApprovalPolicy.AUTO),
        }
        category, risk, approval = mapping.get(tool_name, ("tool", RiskLevel.READ_ONLY, ApprovalPolicy.AUTO))
        return CapabilityDefinition(
            capability_id=capability_id,
            tool_name=tool_name,
            category=category,
            risk_level=risk,
            approval_policy=approval,
            side_effect_level="external_write" if risk in (RiskLevel.EXTERNAL_WRITE, RiskLevel.DESTRUCTIVE) else "local",
            identity_mode=IdentityMode.SERVICE_ACCOUNT,
            supports_cancel=tool_name in {"browser", "coding", "exec"},
            supports_resume=False,
        )

    def _iter_configured_secret_values(self) -> list[str]:
        values: list[str] = []
        for profile in self.secret_profiles.values():
            for value in dict(_obj_get(profile, "values", {}) or {}).values():
                if isinstance(value, str) and value:
                    values.append(value)
        return values

    def _identity_defaults_view(self) -> dict[str, str]:
        defaults = self.identity_defaults
        return {
            "interactive": str(_obj_get(defaults, "interactive", IdentityMode.SERVICE_ACCOUNT.value) or IdentityMode.SERVICE_ACCOUNT.value),
            "automation": str(_obj_get(defaults, "automation", IdentityMode.SERVICE_ACCOUNT.value) or IdentityMode.SERVICE_ACCOUNT.value),
        }

    def _profile_bindings(self, attr_name: str) -> dict[str, list[str]]:
        bindings: dict[str, list[str]] = {}
        for item in self.list_capabilities_view():
            profile_name = str(item.get(attr_name) or "")
            if not profile_name:
                continue
            bindings.setdefault(profile_name, []).append(str(item.get("capability_id") or ""))
        for values in bindings.values():
            values.sort()
        return bindings

    @staticmethod
    def _binding_status(profile_name: str, profile_map: dict[str, Any], *, required: bool) -> dict[str, str]:
        if not required and not profile_name:
            return {"state": "not_required", "label": "Not required"}
        if not profile_name:
            return {"state": "unbound", "label": "Unbound"}
        if profile_name not in profile_map:
            return {"state": "missing", "label": "Missing"}
        return {"state": "configured", "label": "Configured"}

    def _requires_sandbox_binding(self, capability: CapabilityDefinition) -> bool:
        if capability.capability_id in _SANDBOX_GUARDED_CAPABILITIES:
            return True
        return capability.risk_level in _HIGH_RISK_LEVELS

    @staticmethod
    def _extract_urls(command: str) -> list[str]:
        return [part for part in command.split() if part.startswith("http://") or part.startswith("https://")]

    @staticmethod
    def _host_matches(host: str, patterns: list[str]) -> bool:
        for pattern in patterns:
            value = pattern.lower()
            if value.startswith("*.") and (host == value[2:] or host.endswith("." + value[2:])):
                return True
            if host == value:
                return True
        return False

    def _definition_warnings(self, capability: CapabilityDefinition) -> list[str]:
        warnings: list[str] = []
        secret_status = self._binding_status(
            capability.secret_profile,
            self.secret_profiles,
            required=bool(capability.requires_secrets),
        )
        if secret_status["state"] in {"unbound", "missing"}:
            warnings.append(f"{secret_status['state']}_secret_profile")
        sandbox_status = self._binding_status(
            capability.sandbox_profile,
            self.sandbox_profiles,
            required=self._requires_sandbox_binding(capability),
        )
        if sandbox_status["state"] in {"unbound", "missing"}:
            warnings.append(f"{sandbox_status['state']}_sandbox_profile")
        return warnings
