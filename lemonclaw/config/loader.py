"""Configuration loading utilities."""

import json
import os
from pathlib import Path

from loguru import logger

from lemonclaw.config.schema import Config


def get_config_path() -> Path:
    """Get the default configuration file path."""
    return Path.home() / ".lemonclaw" / "config.json"


def get_data_dir() -> Path:
    """Get the lemonclaw data directory."""
    from lemonclaw.utils.helpers import get_data_path
    return get_data_path()


def load_config(config_path: Path | None = None) -> Config:
    """Load configuration from file, then overlay environment variables.

    Priority (highest wins):
    1. Environment variables (Orchestrator-injected)
    2. Config file (~/.lemonclaw/config.json)
    3. Pydantic defaults

    Env vars recognized:
    - GATEWAY_TOKEN  → gateway.auth_token
    - GATEWAY_BIND   → gateway.host
    - GATEWAY_PORT   → gateway.port
    - API_BASE_URL   → lemondata.api_base_url + auto-populate providers
    - API_KEY        → lemondata.api_key + auto-populate providers
    - DEFAULT_MODEL  → agents.defaults.model
    - INSTANCE_ID    → lemondata.instance_id
    """
    path = config_path or get_config_path()

    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            data = _migrate_config(data)
            config = Config.model_validate(data)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Failed to load config from {path}: {e}, backing up and using defaults")
            try:
                bak = path.with_suffix(".json.bak")
                path.rename(bak)
                logger.info(f"Corrupt config backed up to {bak}")
            except OSError:
                pass
            config = Config()
    else:
        config = Config()

    _apply_env_overrides(config)
    return config


def save_config(config: Config, config_path: Path | None = None) -> None:
    """Save configuration to file (atomic: write tmp → fsync → rename).

    Strips env-injected values to prevent leaking API keys to disk.
    """
    path = config_path or get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    data = config.model_dump(by_alias=True)

    # Load original file data to detect env-injected values
    original: dict = {}
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                original = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    # Strip env-injected provider keys: if original file had empty/missing key,
    # don't persist the env-injected value
    _strip_env_injected(data, original)

    tmp_path = path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    tmp_path.rename(path)


# Provider fields that _apply_env_overrides auto-populates from API_KEY env var
_ENV_INJECTED_PROVIDERS = ("lemondata", "lemondataClaude", "lemondataMinimax", "lemondataGemini")


def _strip_env_injected(data: dict, original: dict) -> None:
    """Remove env-injected provider credentials that weren't in the original file.

    Only strips apiKey (sensitive credential). apiBase is NOT stripped because
    config-sync needs to persist it (e.g. filling in missing provider base URLs).
    """
    if not os.environ.get("API_KEY"):
        return  # No env injection active
    providers = data.get("providers", {})
    orig_providers = original.get("providers", {})
    for name in _ENV_INJECTED_PROVIDERS:
        if name not in providers:
            continue
        orig_prov = orig_providers.get(name, {})
        # If original file had no api_key for this provider, clear the injected one
        if not orig_prov.get("apiKey", orig_prov.get("api_key", "")):
            providers[name]["apiKey"] = ""
            providers[name].pop("api_key", None)


def _apply_env_overrides(config: Config) -> None:
    """Overlay environment variables onto loaded config.

    K8s scenario: Orchestrator sets these env vars on the Deployment.
    Self-hosted: Users can also set them in launchd/systemd env.

    NOTE: These env vars are UNPREFIXED (e.g. GATEWAY_TOKEN, API_KEY).
    Pydantic BaseSettings only reads LEMONCLAW_* prefixed vars (see schema.py),
    so there is no conflict between the two env parsing paths.
    Priority: _apply_env_overrides > Pydantic env > config file > defaults.
    """
    if token := os.environ.get("GATEWAY_TOKEN"):
        config.gateway.auth_token = token

    if bind := os.environ.get("GATEWAY_BIND"):
        config.gateway.host = bind

    if port := os.environ.get("GATEWAY_PORT"):
        try:
            config.gateway.port = int(port)
        except ValueError:
            logger.warning(f"Invalid GATEWAY_PORT={port}, ignoring")

    # DEFAULT_MODEL is a fallback: only apply if config.json didn't set a model
    # (i.e. still has the Pydantic default). This allows users to override via Settings.
    if model := os.environ.get("DEFAULT_MODEL"):
        _DEFAULT_MODEL = "claude-sonnet-4-6"  # must match AgentDefaults.model default
        if config.agents.defaults.model == _DEFAULT_MODEL:
            config.agents.defaults.model = model

    if instance_id := os.environ.get("INSTANCE_ID"):
        config.lemondata.instance_id = instance_id

    # Trusted proxies (K8s internal network CIDRs)
    if proxies := os.environ.get("TRUSTED_PROXIES"):
        config.gateway.trusted_proxies = [p.strip() for p in proxies.split(",") if p.strip()]

    # API_BASE_URL + API_KEY: populate LemonData config and provider entries
    api_base = os.environ.get("API_BASE_URL")
    api_key = os.environ.get("API_KEY")

    if api_base:
        config.lemondata.api_base_url = api_base

    if api_key:
        config.lemondata.api_key = api_key

    if api_key:
        base = api_base or "https://api.lemondata.cc"
        base_v1 = f"{base}/v1" if not base.endswith("/v1") else base
        base_no_v1 = base.removesuffix("/v1")

        # Auto-populate the 4 LemonData providers
        config.providers.lemondata.api_key = api_key
        config.providers.lemondata.api_base = base_v1

        config.providers.lemondata_claude.api_key = api_key
        config.providers.lemondata_claude.api_base = base_no_v1

        config.providers.lemondata_minimax.api_key = api_key
        config.providers.lemondata_minimax.api_base = base_no_v1

        config.providers.lemondata_gemini.api_key = api_key
        config.providers.lemondata_gemini.api_base = base_no_v1


def _migrate_config(data: dict) -> dict:
    """Migrate old config formats to current."""
    # Move tools.exec.restrictToWorkspace → tools.restrictToWorkspace
    tools = data.get("tools", {})
    exec_cfg = tools.get("exec", {})
    if "restrictToWorkspace" in exec_cfg and "restrictToWorkspace" not in tools:
        tools["restrictToWorkspace"] = exec_cfg.pop("restrictToWorkspace")
    return data
