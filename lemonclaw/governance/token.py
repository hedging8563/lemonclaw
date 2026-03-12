"""Capability token issuance and validation."""

from __future__ import annotations

import secrets
import time

from lemonclaw.governance.types import AutonomyCap, CapabilityToken


def issue_capability_token(
    *,
    task_id: str,
    tenant_id: str = "",
    mode: str = "chat",
    ttl_seconds: int = 900,
    allowed_capabilities: list[str] | None = None,
    autonomy_cap: AutonomyCap = AutonomyCap.L1,
    cost_ceiling_usd: float | None = None,
    approval_state: str = "approved",
    kill_switch_epoch: int = 0,
) -> CapabilityToken:
    return CapabilityToken(
        token_id=f"ct_{secrets.token_hex(6)}",
        task_id=task_id,
        tenant_id=tenant_id,
        mode=mode,
        expires_at=time.time() + max(ttl_seconds, 1),
        allowed_capabilities=allowed_capabilities or ["*"],
        autonomy_cap=autonomy_cap,
        cost_ceiling_usd=cost_ceiling_usd,
        approval_state=approval_state,
        kill_switch_epoch=kill_switch_epoch,
    )


def validate_capability_token(token: CapabilityToken, capability_id: str) -> tuple[bool, str]:
    if token.is_expired():
        return False, "capability token expired"
    if not token.allows(capability_id):
        return False, f"capability '{capability_id}' not granted"
    return True, ""
