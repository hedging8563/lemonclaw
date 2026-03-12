"""Governance runtime for capability-aware authorization and audit."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

from lemonclaw.governance.audit import append_audit_record
from lemonclaw.governance.kill_switch import is_kill_switched, load_kill_switch_state
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
        default_state_dir = workspace / ".lemonclaw-state"
        self._kill_switch_path = Path(
            getattr(config, "kill_switch_file", str(default_state_dir / "governance.json"))
        ).expanduser()
        self._audit_log_path = Path(
            getattr(config, "audit_log_path", str(default_state_dir / "capability-audit.jsonl"))
        ).expanduser()
        budgets = getattr(config, "budgets", None)
        self._task_budget = getattr(budgets, "default_task_usd", None) if budgets is not None else None

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
            return AuthorizationDecision(allowed=True, capability=capability)
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
        return AuthorizationDecision(True, capability)

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
                budget_snapshot={"task_usd": self._task_budget},
                capability_token_id=token.token_id if token else "",
                kill_switch_state={"epoch": state.get("epoch", 0)},
                tenant_id=token.tenant_id if token else "",
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

    @staticmethod
    def _default_definition(capability_id: str, tool_name: str) -> CapabilityDefinition:
        if capability_id == "http.write":
            return CapabilityDefinition(
                capability_id=capability_id,
                tool_name=tool_name,
                category="http",
                risk_level=RiskLevel.EXTERNAL_WRITE,
                approval_policy=ApprovalPolicy.AUTO,
                side_effect_level="external_write",
                identity_mode=IdentityMode.SERVICE_ACCOUNT,
            )
        if capability_id == "http.read":
            return CapabilityDefinition(
                capability_id=capability_id,
                tool_name=tool_name,
                category="http",
                risk_level=RiskLevel.READ_ONLY,
                approval_policy=ApprovalPolicy.AUTO,
                side_effect_level="local",
                identity_mode=IdentityMode.SERVICE_ACCOUNT,
            )
        if capability_id == "git.write.local":
            return CapabilityDefinition(
                capability_id=capability_id,
                tool_name=tool_name,
                category="repository",
                risk_level=RiskLevel.LOCAL_MUTATION,
                approval_policy=ApprovalPolicy.AUTO,
                side_effect_level="local",
                identity_mode=IdentityMode.SERVICE_ACCOUNT,
            )
        if capability_id == "git.write.remote":
            return CapabilityDefinition(
                capability_id=capability_id,
                tool_name=tool_name,
                category="repository",
                risk_level=RiskLevel.EXTERNAL_WRITE,
                approval_policy=ApprovalPolicy.REQUIRE_CONFIRM,
                side_effect_level="external_write",
                identity_mode=IdentityMode.SERVICE_ACCOUNT,
            )
        if capability_id == "k8s.read":
            return CapabilityDefinition(
                capability_id=capability_id,
                tool_name=tool_name,
                category="infrastructure",
                risk_level=RiskLevel.READ_ONLY,
                approval_policy=ApprovalPolicy.AUTO,
                side_effect_level="local",
                identity_mode=IdentityMode.SERVICE_ACCOUNT,
            )
        if capability_id == "k8s.rollout.restart":
            return CapabilityDefinition(
                capability_id=capability_id,
                tool_name=tool_name,
                category="infrastructure",
                risk_level=RiskLevel.DESTRUCTIVE,
                approval_policy=ApprovalPolicy.REQUIRE_CONFIRM,
                side_effect_level="external_write",
                identity_mode=IdentityMode.SERVICE_ACCOUNT,
            )
        if capability_id == "k8s.scale":
            return CapabilityDefinition(
                capability_id=capability_id,
                tool_name=tool_name,
                category="infrastructure",
                risk_level=RiskLevel.DESTRUCTIVE,
                approval_policy=ApprovalPolicy.REQUIRE_CONFIRM,
                side_effect_level="external_write",
                identity_mode=IdentityMode.SERVICE_ACCOUNT,
            )
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
