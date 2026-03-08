"""Configuration synchronization for K8s managed instances.

Runs at gateway startup: read env vars → apply to Config → save if changed.
Each of the 7 operations is independent (one failure won't skip the rest).

K8s scenario:  Orchestrator injects env vars → config-sync applies them.
Self-hosted:   install.sh/lemonclaw init generates correct config; this module
               only runs as part of `lemonclaw gateway` startup.

Historical note: OpenClaw's config-sync.cjs was 465 lines because Zod .strict()
required manually injecting every missing field.  Pydantic defaults handle that
automatically, so this module focuses on env-override sync, migration, and
validation.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from loguru import logger

from lemonclaw.config.defaults import (
    DEFAULT_MODEL,
    DEFAULT_STT_MODEL,
    DEFAULT_STT_PROVIDER,
    DEFAULT_VISION_MODEL,
    LEMONDATA_API_BASE,
    LEMONDATA_API_BASE_V1,
    PROVIDER_LEMONDATA,
    PROVIDER_LEMONDATA_CLAUDE,
    PROVIDER_LEMONDATA_GEMINI,
    PROVIDER_LEMONDATA_MINIMAX,
)
from lemonclaw.config.schema import Config

# Type alias for sync operation functions
_SyncFn = Callable[[Config], bool]


# ============================================================================
# Result tracking
# ============================================================================


@dataclass
class SyncOp:
    name: str
    changed: bool = False
    error: str | None = None


@dataclass
class SyncReport:
    """Tracks what config-sync did."""

    ops: list[SyncOp] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return any(op.changed for op in self.ops)

    @property
    def failures(self) -> int:
        return sum(1 for op in self.ops if op.error)

    def record(self, name: str, changed: bool) -> None:
        self.ops.append(SyncOp(name=name, changed=changed))

    def record_failure(self, name: str, err: Exception) -> None:
        self.ops.append(SyncOp(name=name, error=str(err)))

    def summary(self) -> str:
        changed = [op.name for op in self.ops if op.changed]
        failed = [f"{op.name}({op.error})" for op in self.ops if op.error]
        parts = []
        if changed:
            parts.append(f"changed: {', '.join(changed)}")
        if failed:
            parts.append(f"FAILED: {', '.join(failed)}")
        if not parts:
            parts.append("no changes")
        return f"config-sync: {'; '.join(parts)}"


# ============================================================================
# Main entry point
# ============================================================================


def run_config_sync(config: Config) -> SyncReport:
    """Run all 8 sync operations. Called by gateway startup before serving.

    Note: load_config() already calls _apply_env_overrides() which handles
    the basic GATEWAY_TOKEN, API_KEY, API_BASE_URL, DEFAULT_MODEL, INSTANCE_ID
    mapping.  This module does additional sync that _apply_env_overrides()
    doesn't cover (trusted_proxies, migrations, validation).
    """
    report = SyncReport()

    ops: list[tuple[str, _SyncFn]] = [
        ("sync_api_key", _sync_api_key),
        ("inject_defaults", _inject_defaults),
        ("sync_gateway_token", _sync_gateway_token),
        ("sync_trusted_proxies", _sync_trusted_proxies),
        ("migrate_base_urls", _migrate_base_urls),
        ("validate_providers", _validate_providers),
        ("sync_model_config", _sync_model_config),
        ("clear_stale_credentials", _clear_stale_credentials),
    ]

    for name, fn in ops:
        try:
            changed = fn(config)
            report.record(name, changed)
        except Exception as e:
            logger.error(f"config-sync: {name} failed: {e}")
            report.record_failure(name, e)

    if report.changed:
        from lemonclaw.config.loader import save_config
        save_config(config)
        logger.info(f"config-sync: saved updated config")

    return report


# ============================================================================
# Shared helper: LemonData provider list
# ============================================================================


def _lemondata_providers(config: Config):
    """Return the 4 LemonData provider (name, config) tuples."""
    return [
        (PROVIDER_LEMONDATA, config.providers.lemondata),
        (PROVIDER_LEMONDATA_CLAUDE, config.providers.lemondata_claude),
        (PROVIDER_LEMONDATA_MINIMAX, config.providers.lemondata_minimax),
        (PROVIDER_LEMONDATA_GEMINI, config.providers.lemondata_gemini),
    ]


# ============================================================================
# Operation 1: Sync API key across all 4 LemonData providers
# ============================================================================


def _sync_api_key(config: Config) -> bool:
    """Ensure API_KEY env var is applied to all 3 LemonData providers.

    _apply_env_overrides() already does this, but we add change detection
    and handle the case where providers have stale keys.
    """
    api_key = os.environ.get("API_KEY", "")
    if not api_key:
        return False

    changed = False
    for name, prov in _lemondata_providers(config):
        if prov.api_key != api_key:
            prov.api_key = api_key
            changed = True
            logger.info(f"config-sync: updated {name} api_key")

    return changed


# ============================================================================
# Operation 2: Inject SSOT defaults
# ============================================================================


def _inject_defaults(config: Config) -> bool:
    """Ensure config uses SSOT defaults from config/defaults.py.

    Pydantic defaults handle most fields, but the schema default for model
    is 'anthropic/claude-opus-4-5' (upstream nanobot), while LemonClaw's
    SSOT is DEFAULT_MODEL from defaults.py.
    """
    changed = False

    # Fix upstream nanobot default model
    if config.agents.defaults.model == "anthropic/claude-opus-4-5":
        config.agents.defaults.model = DEFAULT_MODEL
        changed = True
        logger.info(f"config-sync: model default → {DEFAULT_MODEL}")

    return changed


# ============================================================================
# Operation 3: Sync gateway token
# ============================================================================


def _sync_gateway_token(config: Config) -> bool:
    """Apply GATEWAY_TOKEN env var. Already done by _apply_env_overrides(),
    this is a no-op validation + logging pass."""
    token = os.environ.get("GATEWAY_TOKEN", "")
    if not token:
        return False

    if config.gateway.auth_token != token:
        config.gateway.auth_token = token
        logger.info("config-sync: updated gateway auth_token")
        return True

    return False


# ============================================================================
# Operation 4: Sync trusted proxies
# ============================================================================

# Default for K8s internal network (K3s uses 10.42.0.0/16)
K8S_DEFAULT_CIDR = "10.42.0.0/16"


def _sync_trusted_proxies(config: Config) -> bool:
    """Apply TRUSTED_PROXIES env var to config.

    K8s scenario: Orchestrator sets TRUSTED_PROXIES=10.42.0.0/16 so the
    gateway trusts X-Forwarded-For from the K8s ingress.
    Self-hosted: Not set, remains empty (localhost-only access).
    """
    proxies_env = os.environ.get("TRUSTED_PROXIES", "")
    if not proxies_env:
        return False

    # Parse comma-separated CIDRs
    desired = [p.strip() for p in proxies_env.split(",") if p.strip()]
    if config.gateway.trusted_proxies == desired:
        return False

    config.gateway.trusted_proxies = desired
    logger.info(f"config-sync: trusted_proxies → {desired}")
    return True


# ============================================================================
# Operation 5: Migrate legacy base URLs
# ============================================================================

# Old internal K8s service URL (used before 2026-02)
_OLD_INTERNAL_URL = "http://lemondata-api.lemondata.svc.cluster.local"


def _migrate_base_urls(config: Config) -> bool:
    """Replace legacy internal HTTP URLs with current API_BASE_URL.

    Historical: Early K8s deployments used cluster-internal HTTP URLs.
    These must be migrated to the public HTTPS endpoint.
    """
    api_base = os.environ.get("API_BASE_URL", LEMONDATA_API_BASE)
    api_base_v1 = f"{api_base}/v1" if not api_base.endswith("/v1") else api_base
    api_base_no_v1 = api_base.removesuffix("/v1")

    changed = False

    # Check all 4 LemonData providers
    providers = [
        (PROVIDER_LEMONDATA, config.providers.lemondata, api_base_v1),
        (PROVIDER_LEMONDATA_CLAUDE, config.providers.lemondata_claude, api_base_no_v1),
        (PROVIDER_LEMONDATA_MINIMAX, config.providers.lemondata_minimax, api_base_no_v1),
        (PROVIDER_LEMONDATA_GEMINI, config.providers.lemondata_gemini, api_base_no_v1),
    ]

    for name, prov, expected_base in providers:
        if prov.api_base and _OLD_INTERNAL_URL in prov.api_base:
            prov.api_base = expected_base
            changed = True
            logger.info(f"config-sync: migrated {name} baseUrl → {expected_base}")

    # LemonData platform config
    if config.lemondata.api_base_url and _OLD_INTERNAL_URL in config.lemondata.api_base_url:
        config.lemondata.api_base_url = api_base
        changed = True
        logger.info(f"config-sync: migrated lemondata.api_base_url → {api_base}")

    return changed


# ============================================================================
# Operation 6: Validate provider API base patterns
# ============================================================================


def _validate_providers(config: Config) -> bool:
    """Validate and fix provider api_base URL patterns.

    Rules:
    - lemondata (OpenAI-compat): must end with /v1
    - lemondata_claude (Anthropic): must NOT end with /v1
    - lemondata_minimax (Anthropic format): must NOT end with /v1
    - lemondata_gemini (Gemini native): must NOT end with /v1
    """
    changed = False

    # (provider_name, provider_config, needs_v1)
    rules = [
        (PROVIDER_LEMONDATA, config.providers.lemondata, True),
        (PROVIDER_LEMONDATA_CLAUDE, config.providers.lemondata_claude, False),
        (PROVIDER_LEMONDATA_MINIMAX, config.providers.lemondata_minimax, False),
        (PROVIDER_LEMONDATA_GEMINI, config.providers.lemondata_gemini, False),
    ]

    for name, prov, needs_v1 in rules:
        if not prov.api_base:
            continue
        base = prov.api_base
        if needs_v1 and not base.endswith("/v1"):
            prov.api_base = f"{base}/v1"
            changed = True
            logger.info(f"config-sync: fixed {name} api_base (added /v1)")
        elif not needs_v1 and base.endswith("/v1"):
            prov.api_base = base.removesuffix("/v1")
            changed = True
            logger.info(f"config-sync: fixed {name} api_base (removed /v1)")

    return changed


# ============================================================================
# Operation 7: Sync versioned model configuration
# ============================================================================

# Bump this version when model defaults change. Config-sync only re-applies
# if the stored version is lower, preventing unnecessary config churn.
MODEL_CONFIG_VERSION = 7

_VERSION_FILE_NAME = ".managed-model-version"


def _sync_model_config(config: Config) -> bool:
    """Version-controlled model configuration sync.

    Unlike OpenClaw which maintains a full model registry (models[].id, cost,
    contextWindow...), LemonClaw delegates model routing to LiteLLM.
    This operation only syncs the default model selections and provider bases.
    """
    from lemonclaw.config.loader import get_config_path

    version_file = get_config_path().parent / _VERSION_FILE_NAME
    current_version = 0
    try:
        current_version = int(version_file.read_text().strip())
    except (FileNotFoundError, ValueError):
        pass

    if current_version >= MODEL_CONFIG_VERSION:
        return False

    # Force save on version upgrade to persist _apply_env_overrides values
    # that are correct in memory but missing on disk
    changed = True
    api_key = config.providers.lemondata.api_key or os.environ.get("API_KEY", "")

    # Ensure all 4 providers have correct api_base (always set, not conditional,
    # because _apply_env_overrides may have set in-memory values that mask
    # missing disk values — we need to persist them)
    if api_key:
        expected = [
            (config.providers.lemondata, LEMONDATA_API_BASE_V1),
            (config.providers.lemondata_claude, LEMONDATA_API_BASE),
            (config.providers.lemondata_minimax, LEMONDATA_API_BASE),
            (config.providers.lemondata_gemini, LEMONDATA_API_BASE),
        ]
        for prov, expected_base in expected:
            if prov.api_base != expected_base:
                prov.api_base = expected_base
                changed = True

    # v2: Ensure coding tool has api_key + api_base + enabled
    if api_key:
        coding = config.tools.coding
        if not coding.api_key:
            coding.api_key = api_key
            changed = True
        if not coding.api_base:
            coding.api_base = LEMONDATA_API_BASE
            changed = True
        if not coding.enabled:
            coding.enabled = True
            changed = True

    # v7: Ensure coding.model has a default value
    if not config.tools.coding.model:
        config.tools.coding.model = "claude-sonnet-4-6"
        changed = True
        logger.info("config-sync: set coding.model → claude-sonnet-4-6")

    # Ensure LemonData platform config
    if api_key and not config.lemondata.api_base_url:
        config.lemondata.api_base_url = LEMONDATA_API_BASE
        changed = True

    # Write version file (even if nothing else changed, to avoid re-running)
    try:
        version_file.write_text(str(MODEL_CONFIG_VERSION))
    except OSError as e:
        logger.warning(f"config-sync: failed to write version file: {e}")

    if changed:
        logger.info(f"config-sync: model config synced to v{MODEL_CONFIG_VERSION}")

    return changed


# ============================================================================
# Operation 8: Clear stale credentials on channel token change
# ============================================================================

# Maps channel name → (config attr path, token field name)
# When a channel's auth token changes, old pairing/allowFrom files must be
# cleared so auto-pairing can re-trigger with the new bot identity.
_CHANNEL_TOKEN_KEYS: dict[str, str] = {
    "telegram": "token",
    "discord": "token",
    "slack": "bot_token",
    "feishu": "app_id",
    "dingtalk": "app_key",
    "qq": "app_id",
}

_TOKEN_SNAPSHOT_FILE = ".channel-token-snapshot.json"


def _clear_stale_credentials(config: Config) -> bool:
    """Detect channel auth token changes and clear old pairing data.

    Mirrors the fix in Orchestrator's updateInstanceConfig() (k8s.ts):
    when a channel's botToken/appId changes, the old .{ch}-owner-paired
    sentinel and {ch}-allowFrom.json must be removed so auto-pairing
    re-triggers with the new bot identity.
    """
    from lemonclaw.config.loader import get_config_path

    cred_dir = get_config_path().parent / "credentials"
    snapshot_file = get_config_path().parent / _TOKEN_SNAPSHOT_FILE

    # Load previous token snapshot
    old_tokens: dict[str, str] = {}
    try:
        old_tokens = json.loads(snapshot_file.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    # Build current token snapshot
    channels_cfg = config.channels
    current_tokens: dict[str, str] = {}
    for ch, token_field in _CHANNEL_TOKEN_KEYS.items():
        ch_cfg = getattr(channels_cfg, ch, None)
        if ch_cfg is None:
            continue
        token_val = getattr(ch_cfg, token_field, "")
        if token_val:
            current_tokens[ch] = token_val

    # Detect changes
    channels_to_reset: list[str] = []
    for ch, new_token in current_tokens.items():
        old_token = old_tokens.get(ch, "")
        if old_token and new_token != old_token:
            channels_to_reset.append(ch)

    # Clear stale credential files
    changed = False
    if channels_to_reset and cred_dir.exists():
        for ch in channels_to_reset:
            for pattern in [
                f".{ch}-owner-paired",
                f"{ch}-allowFrom.json",
                f"{ch}-pairing.json",
            ]:
                path = cred_dir / pattern
                if path.exists():
                    path.unlink()
                    changed = True
        if changed:
            logger.info(
                f"config-sync: cleared stale pairing data for: "
                f"{', '.join(channels_to_reset)}"
            )

    # Always save current snapshot (even if no change, to bootstrap)
    if current_tokens != old_tokens:
        try:
            snapshot_file.parent.mkdir(parents=True, exist_ok=True)
            snapshot_file.write_text(json.dumps(current_tokens))
        except OSError as e:
            logger.warning(f"config-sync: failed to write token snapshot: {e}")

    return changed
