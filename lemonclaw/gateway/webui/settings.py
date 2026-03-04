"""Settings API — read/write config.json with hot-reload support."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from lemonclaw.gateway.webui.auth import verify_session_cookie, COOKIE_NAME

if TYPE_CHECKING:
    from lemonclaw.config.watcher import ConfigWatcher


_NO_CACHE = {"Cache-Control": "no-store, private", "Pragma": "no-cache"}

# Fields that can be written via PATCH /api/settings (whitelist)
_WRITABLE_PATHS: set[str] = {
    # Agent defaults
    "agents.defaults.model",
    "agents.defaults.provider",
    "agents.defaults.temperature",
    "agents.defaults.max_tokens",
    "agents.defaults.timezone",
    "agents.defaults.memory_window",
    "agents.defaults.max_tool_iterations",
    "agents.defaults.token_budget_per_session",
    "agents.defaults.cost_budget_per_day",
    "agents.defaults.system_prompt",
    "agents.defaults.disabled_skills",
    # Channels (top-level flags)
    "channels.send_progress",
    "channels.send_tool_hints",
    "channels.auto_pairing",
    # Tools
    "tools.web.search.api_key",
    "tools.web.search.max_results",
    "tools.coding.enabled",
    "tools.coding.timeout",
    "tools.coding.api_key",
    "tools.coding.api_base",
    "tools.exec.timeout",
    "tools.exec.path_append",
    "tools.restrict_to_workspace",
    "tools.mcp_servers",
}

# Channel names that accept full object replacement
_CHANNEL_NAMES = {
    "telegram", "discord", "whatsapp", "slack", "feishu",
    "dingtalk", "email", "wecom", "qq", "mochat", "matrix",
}
# Add channels.{name} to writable paths
for _ch in _CHANNEL_NAMES:
    _WRITABLE_PATHS.add(f"channels.{_ch}")

# Provider names that accept full object replacement
_PROVIDER_NAMES = {
    "lemondata", "lemondata_claude", "lemondata_minimax", "lemondata_gemini",
    "custom", "anthropic", "openai", "openrouter", "deepseek", "groq",
    "zhipu", "dashscope", "vllm", "gemini", "moonshot", "minimax",
    "aihubmix", "siliconflow", "volcengine", "openai_codex", "github_copilot",
}
for _p in _PROVIDER_NAMES:
    _WRITABLE_PATHS.add(f"providers.{_p}")

# Fields that require restart (not hot-reloadable)
_RESTART_FIELDS = re.compile(
    r"^(channels\.(telegram|discord|whatsapp|slack|feishu|dingtalk|email|wecom|qq|mochat|matrix)"
    r"|tools\.(mcp_servers|coding))"
)

# Sensitive field names — values masked in GET response
_SENSITIVE_KEYS = {"api_key", "token", "secret", "app_secret", "encoding_aes_key",
                   "bridge_token", "bot_token", "app_token", "access_token"}


def _mask(value: str) -> str:
    if not value or len(value) < 8:
        return "****" if value else ""
    return value[:4] + "****" + value[-4:]


def _mask_dict(d: dict, depth: int = 0) -> dict:
    """Recursively mask sensitive string values in a dict."""
    if depth > 5:
        return d
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out[k] = _mask_dict(v, depth + 1)
        elif isinstance(v, str) and k in _SENSITIVE_KEYS and v:
            out[k] = _mask(v)
        else:
            out[k] = v
    return out


def _set_nested(data: dict, path: str, value: Any) -> None:
    """Set a nested dict value by dot-separated path."""
    keys = path.split(".")
    obj = data
    for key in keys[:-1]:
        obj = obj.setdefault(key, {})
    obj[keys[-1]] = value


def _json(data: dict, status_code: int = 200) -> JSONResponse:
    return JSONResponse(data, status_code=status_code, headers=_NO_CACHE)


def get_settings_routes(
    *,
    auth_token: str | None,
    config_path: Path,
    config_watcher: ConfigWatcher | None = None,
    agent_loop: Any | None = None,
) -> list[Route]:
    """Build Settings API routes."""

    def _require_auth(request: Request) -> tuple[bool, Response | None]:
        if not auth_token:
            return True, None
        cookie = request.cookies.get(COOKIE_NAME)
        if not cookie:
            return False, _json({"error": "Unauthorized"}, 401)
        valid, _ = verify_session_cookie(cookie, auth_token)
        if not valid:
            return False, _json({"error": "Unauthorized"}, 401)
        return True, None

    # ── GET /api/settings ─────────────────────────────────────────────

    async def get_settings(request: Request) -> Response:
        ok, err = _require_auth(request)
        if not ok:
            return err  # type: ignore[return-value]

        from lemonclaw.config.loader import load_config
        try:
            config = load_config(config_path)
        except Exception as exc:
            logger.error("Failed to load config: {}", exc)
            return _json({"error": "Failed to load config"}, 500)

        data = config.model_dump(by_alias=True)
        # Remove platform-level fields that users shouldn't see/edit
        data.pop("lemondata", None)
        data.pop("gateway", None)

        return _json({"settings": _mask_dict(data)})

    # ── PATCH /api/settings ───────────────────────────────────────────

    async def patch_settings(request: Request) -> Response:
        ok, err = _require_auth(request)
        if not ok:
            return err  # type: ignore[return-value]

        try:
            body = await request.json()
        except Exception:
            return _json({"error": "Invalid JSON"}, 400)

        if not isinstance(body, dict) or not body:
            return _json({"error": "Expected non-empty object"}, 400)

        # Validate all paths are writable
        rejected = [k for k in body if k not in _WRITABLE_PATHS]
        if rejected:
            return _json({"error": f"Forbidden paths: {', '.join(rejected)}"}, 403)

        # Load current config, apply changes, save
        from lemonclaw.config.loader import load_config, save_config
        try:
            config = load_config(config_path)
        except Exception as exc:
            logger.error("Failed to load config for patch: {}", exc)
            return _json({"error": "Failed to load config"}, 500)

        data = config.model_dump(by_alias=True)
        for path, value in body.items():
            _set_nested(data, path, value)

        # Re-validate through Pydantic
        from lemonclaw.config.schema import Config
        try:
            updated = Config.model_validate(data)
        except Exception as exc:
            return _json({"error": f"Validation failed: {exc}"}, 422)

        try:
            save_config(updated, config_path)
        except Exception as exc:
            logger.error("Failed to save config: {}", exc)
            return _json({"error": "Failed to save config"}, 500)

        return _json({"saved": True})

    # ── POST /api/settings/apply ──────────────────────────────────────

    async def apply_settings(request: Request) -> Response:
        ok, err = _require_auth(request)
        if not ok:
            return err  # type: ignore[return-value]

        # Determine which fields changed since last apply
        restart_required = False
        restart_fields: list[str] = []

        try:
            body = await request.json()
        except Exception:
            body = {}

        changed_paths = body.get("changed_paths", [])
        for path in changed_paths:
            if _RESTART_FIELDS.match(path):
                restart_required = True
                restart_fields.append(path)

        # Always do hot-reload first (provider + agent defaults)
        if config_watcher:
            config_watcher.reload_now()

        if restart_required:
            logger.info("Settings apply: restart required for {}", restart_fields)
            # Return response first, then exit — K8s/systemd will restart
            resp = _json({
                "reloaded": True,
                "restart_required": True,
                "restart_fields": restart_fields,
            })
            # Schedule exit after response is sent
            import asyncio
            asyncio.get_event_loop().call_later(0.5, lambda: sys.exit(0))
            return resp

        return _json({"reloaded": True, "restart_required": False})

    # ── GET /api/settings/skills ──────────────────────────────────────

    async def list_skills(request: Request) -> Response:
        ok, err = _require_auth(request)
        if not ok:
            return err  # type: ignore[return-value]

        if not agent_loop:
            return _json({"error": "Agent not available"}, 503)

        skills_loader = agent_loop.context.skills
        raw = skills_loader.list_skills(filter_unavailable=False)
        disabled = skills_loader._disabled

        skills = []
        for s in raw:
            meta = skills_loader.get_skill_metadata(s["name"])
            desc = (meta or {}).get("description", s["name"])
            skills.append({
                "name": s["name"],
                "source": s["source"],
                "description": desc,
                "enabled": s["name"] not in disabled,
                "available": skills_loader._check_requirements(
                    skills_loader._get_skill_meta(s["name"])
                ),
            })

        return _json({"skills": skills})

    # ── PATCH /api/settings/skills/{name} — enable/disable ───────────

    async def toggle_skill(request: Request) -> Response:
        ok, err = _require_auth(request)
        if not ok:
            return err  # type: ignore[return-value]

        name = request.path_params["name"]

        try:
            body = await request.json()
        except Exception:
            return _json({"error": "Invalid JSON"}, 400)

        enabled = body.get("enabled")
        if not isinstance(enabled, bool):
            return _json({"error": "Expected {\"enabled\": true|false}"}, 400)

        # Update disabled_skills in config
        from lemonclaw.config.loader import load_config, save_config
        try:
            config = load_config(config_path)
        except Exception:
            return _json({"error": "Failed to load config"}, 500)

        disabled = set(config.agents.defaults.disabled_skills)
        if enabled:
            disabled.discard(name)
        else:
            disabled.add(name)
        config.agents.defaults.disabled_skills = sorted(disabled)

        try:
            save_config(config, config_path)
        except Exception:
            return _json({"error": "Failed to save config"}, 500)

        # Update in-memory disabled set
        if agent_loop:
            agent_loop.context.skills._disabled = disabled

        return _json({"name": name, "enabled": enabled})

    # ── POST /api/settings/skills — install from URL ─────────────────

    async def install_skill(request: Request) -> Response:
        ok, err = _require_auth(request)
        if not ok:
            return err  # type: ignore[return-value]

        try:
            body = await request.json()
        except Exception:
            return _json({"error": "Invalid JSON"}, 400)

        url = body.get("url", "").strip()
        if not url:
            return _json({"error": "Missing 'url' field"}, 400)

        # Basic URL validation
        if not url.startswith(("https://", "http://")):
            return _json({"error": "URL must start with https:// or http://"}, 400)

        if not agent_loop:
            return _json({"error": "Agent not available"}, 503)

        workspace_skills = agent_loop.context.skills.workspace_skills
        workspace_skills.mkdir(parents=True, exist_ok=True)

        # Extract skill name from URL (last path segment)
        skill_name = url.rstrip("/").split("/")[-1]
        if skill_name.endswith(".git"):
            skill_name = skill_name[:-4]
        target = workspace_skills / skill_name

        if target.exists():
            return _json({"error": f"Skill '{skill_name}' already exists"}, 409)

        # Git clone
        import subprocess
        try:
            result = subprocess.run(
                ["git", "clone", "--depth=1", url, str(target)],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                return _json({"error": f"git clone failed: {result.stderr.strip()}"}, 422)
        except subprocess.TimeoutExpired:
            # Clean up partial clone
            import shutil
            if target.exists():
                shutil.rmtree(target)
            return _json({"error": "git clone timed out"}, 422)
        except FileNotFoundError:
            return _json({"error": "git not found on system"}, 500)

        # Verify SKILL.md exists
        if not (target / "SKILL.md").exists():
            import shutil
            shutil.rmtree(target)
            return _json({"error": "No SKILL.md found in repository"}, 422)

        return _json({"installed": skill_name}, 201)

    # ── DELETE /api/settings/skills/{name} ────────────────────────────

    async def delete_skill(request: Request) -> Response:
        ok, err = _require_auth(request)
        if not ok:
            return err  # type: ignore[return-value]

        name = request.path_params["name"]

        if not agent_loop:
            return _json({"error": "Agent not available"}, 503)

        # Only workspace skills can be deleted (not builtin)
        skills_loader = agent_loop.context.skills
        skill_info = next(
            (s for s in skills_loader.list_skills(filter_unavailable=False) if s["name"] == name),
            None,
        )
        if not skill_info:
            return _json({"error": f"Skill '{name}' not found"}, 404)
        if skill_info["source"] != "workspace":
            return _json({"error": "Cannot delete built-in skills"}, 403)

        target = skills_loader.workspace_skills / name
        if target.exists():
            import shutil
            shutil.rmtree(target)

        # Also remove from disabled list if present
        from lemonclaw.config.loader import load_config, save_config
        try:
            config = load_config(config_path)
            if name in config.agents.defaults.disabled_skills:
                config.agents.defaults.disabled_skills.remove(name)
                save_config(config, config_path)
        except Exception:
            pass  # Non-critical cleanup

        return _json({"deleted": name})

    # ── Assemble routes ───────────────────────────────────────────────

    return [
        Route("/api/settings", get_settings, methods=["GET"]),
        Route("/api/settings", patch_settings, methods=["PATCH"]),
        Route("/api/settings/apply", apply_settings, methods=["POST"]),
        Route("/api/settings/skills", list_skills, methods=["GET"]),
        Route("/api/settings/skills", install_skill, methods=["POST"]),
        Route("/api/settings/skills/{name:path}", toggle_skill, methods=["PATCH"]),
        Route("/api/settings/skills/{name:path}", delete_skill, methods=["DELETE"]),
    ]
