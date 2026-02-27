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

import os
from dataclasses import dataclass, field

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
    PROVIDER_LEMONDATA_MINIMAX,
)
from lemonclaw.config.schema import Config


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
    """Run all 7 sync operations. Called by gateway startup before serving.

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
# Operation 1: Sync API key across all 3 LemonData providers
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
    providers = [
        (PROVIDER_LEMONDATA, config.providers.lemondata),
        (PROVIDER_LEMONDATA_CLAUDE, config.providers.lemondata_claude),
        (PROVIDER_LEMONDATA_MINIMAX, config.providers.lemondata_minimax),
    ]

    for name, prov in providers:
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

    # Check all 3 LemonData providers
    providers = [
        (PROVIDER_LEMONDATA, config.providers.lemondata, api_base_v1),
        (PROVIDER_LEMONDATA_CLAUDE, config.providers.lemondata_claude, api_base_no_v1),
        (PROVIDER_LEMONDATA_MINIMAX, config.providers.lemondata_minimax, api_base_v1),
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
    - lemondata_minimax (OpenAI-compat): must end with /v1
    """
    changed = False

    # lemondata: needs /v1
    if config.providers.lemondata.api_base:
        base = config.providers.lemondata.api_base
        if not base.endswith("/v1"):
            config.providers.lemondata.api_base = f"{base}/v1"
            changed = True
            logger.info(f"config-sync: fixed lemondata api_base (added /v1)")

    # lemondata_claude: must NOT have /v1
    if config.providers.lemondata_claude.api_base:
        base = config.providers.lemondata_claude.api_base
        if base.endswith("/v1"):
            config.providers.lemondata_claude.api_base = base.removesuffix("/v1")
            changed = True
            logger.info(f"config-sync: fixed lemondata_claude api_base (removed /v1)")

    # lemondata_minimax: needs /v1
    if config.providers.lemondata_minimax.api_base:
        base = config.providers.lemondata_minimax.api_base
        if not base.endswith("/v1"):
            config.providers.lemondata_minimax.api_base = f"{base}/v1"
            changed = True
            logger.info(f"config-sync: fixed lemondata_minimax api_base (added /v1)")

    return changed


# ============================================================================
# Operation 7: Sync versioned model configuration
# ============================================================================

# Bump this version when model defaults change. Config-sync only re-applies
# if the stored version is lower, preventing unnecessary config churn.
MODEL_CONFIG_VERSION = 1

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

    changed = False
    api_key = config.providers.lemondata.api_key or os.environ.get("API_KEY", "")

    # Ensure all 3 providers have correct api_base
    if api_key:
        if not config.providers.lemondata.api_base:
            config.providers.lemondata.api_base = LEMONDATA_API_BASE_V1
            changed = True
        if not config.providers.lemondata_claude.api_base:
            config.providers.lemondata_claude.api_base = LEMONDATA_API_BASE
            changed = True
        if not config.providers.lemondata_minimax.api_base:
            config.providers.lemondata_minimax.api_base = LEMONDATA_API_BASE_V1
            changed = True

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
