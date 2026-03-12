"""Core governance types for capability-aware execution."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from time import time
from typing import Any


class RiskLevel(str, Enum):
    READ_ONLY = "read_only"
    LOCAL_MUTATION = "local_mutation"
    EXTERNAL_WRITE = "external_write"
    DESTRUCTIVE = "destructive"


class ApprovalPolicy(str, Enum):
    AUTO = "auto"
    REQUIRE_CONFIRM = "require_confirm"
    DENY = "deny"


class AutonomyCap(str, Enum):
    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


class IdentityMode(str, Enum):
    SERVICE_ACCOUNT = "service_account"
    DELEGATED_USER = "delegated_user"
    INSTANCE_IDENTITY = "instance_identity"
    ANONYMOUS_READONLY = "anonymous_readonly"


@dataclass(slots=True)
class CapabilityDefinition:
    capability_id: str
    tool_name: str
    category: str
    risk_level: RiskLevel = RiskLevel.READ_ONLY
    side_effect_level: str = "none"
    requires_secrets: bool = False
    auth_profile: str = ""
    identity_mode: IdentityMode = IdentityMode.SERVICE_ACCOUNT
    approval_policy: ApprovalPolicy = ApprovalPolicy.AUTO
    timeout_policy: str = "default"
    retry_policy: str = "default"
    budget_policy: str = "default"
    network_scope: str = "default"
    filesystem_scope: str = "default"
    artifact_types: list[str] = field(default_factory=list)
    audit_fields: list[str] = field(default_factory=list)
    supports_cancel: bool = False
    supports_resume: bool = False
    autonomy_cap: AutonomyCap = AutonomyCap.L1
    kill_switch_scope: str = "capability"
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["risk_level"] = self.risk_level.value
        data["approval_policy"] = self.approval_policy.value
        data["identity_mode"] = self.identity_mode.value
        data["autonomy_cap"] = self.autonomy_cap.value
        return data


@dataclass(slots=True)
class CapabilityToken:
    token_id: str
    task_id: str
    tenant_id: str = ""
    mode: str = "chat"
    expires_at: float = 0.0
    allowed_capabilities: list[str] = field(default_factory=lambda: ["*"])
    autonomy_cap: AutonomyCap = AutonomyCap.L1
    cost_ceiling_usd: float | None = None
    approval_state: str = "approved"
    kill_switch_epoch: int = 0

    def is_expired(self, now: float | None = None) -> bool:
        return (now or time()) >= self.expires_at

    def allows(self, capability_id: str) -> bool:
        return "*" in self.allowed_capabilities or capability_id in self.allowed_capabilities

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["autonomy_cap"] = self.autonomy_cap.value
        return data


@dataclass(slots=True)
class AuthorizationDecision:
    allowed: bool
    capability: CapabilityDefinition
    reason: str = ""


@dataclass(slots=True)
class AuditRecord:
    task_id: str
    capability_id: str
    tool_name: str
    mode: str
    risk_level: str
    actor_identity: str
    result_status: str
    started_at: float
    ended_at: float
    input_hash: str = ""
    budget_snapshot: dict[str, Any] = field(default_factory=dict)
    capability_token_id: str = ""
    kill_switch_state: dict[str, Any] = field(default_factory=dict)
    tenant_id: str = ""
    artifact_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
