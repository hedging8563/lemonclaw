"""Settings API — read/write config.json with hot-reload support."""

from __future__ import annotations

import asyncio
import copy
import json
import re
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
    "agents.defaults.input_cost_per_1k_tokens",
    "agents.defaults.output_cost_per_1k_tokens",
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
    "tools.coding",  # Whole-object replacement (handleSave sends tools.coding as one object)
    "tools.browser.enabled",
    "tools.browser.timeout",
    "tools.browser.allowed_domains",
    "tools.browser.session_name",
    "tools.browser.headed",
    "tools.browser.content_boundaries",
    "tools.browser.max_output",
    "tools.browser",  # Whole-object replacement
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
    r"|tools\.(mcp_servers|coding|browser))"
)

# Sensitive field names — values masked in GET response
_SENSITIVE_KEYS = {"api_key", "token", "secret", "app_secret", "encoding_aes_key",
                   "bridge_token", "bot_token", "app_token", "access_token",
                   "client_secret", "imap_password", "smtp_password", "claw_token",
                   "encrypt_key", "verification_token"}

_SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$")


def _mask(value: str) -> str:
    if not value:
        return ""
    if value.startswith("(") and value.endswith(")"):
        return value  # Preserve markers like "(env)"
    if len(value) < 8:
        return "****"
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


def _get_nested(data: dict, path: str) -> Any:
    """Get a nested dict value by dot-separated path."""
    for key in path.split("."):
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def _is_masked(value: str) -> bool:
    """Check if a string looks like a masked or env-injected placeholder."""
    return isinstance(value, str) and ("****" in value or value.startswith("(injected"))


def _unmark_sensitive(new_obj: dict, path: str, original_data: dict) -> dict:
    """For provider/channel objects, replace masked sensitive values with originals."""
    original = _get_nested(original_data, path)
    if not isinstance(original, dict):
        return new_obj
    out = dict(new_obj)
    for key in _SENSITIVE_KEYS:
        if key in out and _is_masked(out[key]) and key in original:
            out[key] = original[key]  # Preserve original un-masked value
    return out


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

    # Serialize load→modify→save to prevent lost updates
    _config_lock = asyncio.Lock()

    def _require_auth(request: Request) -> tuple[bool, Response | None]:
        if not auth_token:
            return True, None
        cookie = request.cookies.get(COOKIE_NAME)
        if not cookie:
            return False, _json({"error": "Unauthorized"}, 401)
        valid, refreshed = verify_session_cookie(cookie, auth_token)
        if not valid:
            return False, _json({"error": "Unauthorized"}, 401)
        # Store refreshed cookie for _maybe_refresh to set on response
        request.state.refreshed_cookie = refreshed
        return True, None

    def _maybe_refresh(request: Request, response: Response) -> Response:
        """Set refreshed session cookie on response if available."""
        cookie = getattr(request.state, "refreshed_cookie", None)
        if cookie:
            secure = request.url.scheme == "https"
            response.set_cookie(
                COOKIE_NAME, cookie,
                httponly=True, samesite="strict", secure=secure, path="/",
            )
        return response

    # ── GET /api/settings ─────────────────────────────────────────────

    async def get_settings(request: Request) -> Response:
        ok, err = _require_auth(request)
        if not ok:
            return err  # type: ignore[return-value]

        # Read config.json without env overlay so users see their saved values,
        # not env-injected overrides (e.g. DEFAULT_MODEL).
        import json as _json_mod
        from lemonclaw.config.schema import Config
        try:
            if config_path.exists():
                with open(config_path, encoding="utf-8") as f:
                    raw = _json_mod.load(f)
                config = Config.model_validate(raw)
            else:
                config = Config()
        except Exception as exc:
            logger.error("Failed to load config: {}", exc)
            return _json({"error": "Failed to load config"}, 500)

        data = config.model_dump(by_alias=False)
        # Remove platform-level fields that users shouldn't see/edit
        data.pop("lemondata", None)
        data.pop("gateway", None)

        # For env-injected LemonData providers: if config.json has no api_key
        # but env var API_KEY is set, show a placeholder so users know keys are active.
        import os as _os
        if _os.environ.get("API_KEY"):
            _ENV_PROVIDERS = ("lemondata", "lemondata_claude", "lemondata_minimax", "lemondata_gemini")
            providers = data.get("providers", {})
            for pname in _ENV_PROVIDERS:
                prov = providers.get(pname, {})
                if isinstance(prov, dict) and not prov.get("api_key"):
                    prov["api_key"] = "(injected from environment variable)"

        # Include the effective (runtime) model so frontend can show both
        effective_model = agent_loop.model if agent_loop and hasattr(agent_loop, "model") else None
        result = {"settings": _mask_dict(data)}
        if effective_model:
            result["effective_model"] = effective_model

        return _maybe_refresh(request, _json(result))

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

        # Field-specific validation
        sys_prompt = body.get("agents.defaults.system_prompt")
        if sys_prompt is not None and isinstance(sys_prompt, str) and len(sys_prompt) > 4000:
            return _json({"error": "system_prompt exceeds 4000 character limit"}, 400)

        # Load current config, apply changes, save (serialized to prevent lost updates)
        async with _config_lock:
            from lemonclaw.config.loader import load_config, save_config
            try:
                config = load_config(config_path)
            except Exception as exc:
                logger.error("Failed to load config for patch: {}", exc)
                return _json({"error": "Failed to load config"}, 500)

            data = config.model_dump(by_alias=False)
            # Preserve original sensitive values when masked placeholder is sent back
            original_data = copy.deepcopy(data)  # deep copy before mutation
            for path, value in body.items():
                if isinstance(value, dict):
                    # For provider/channel objects: preserve original sensitive fields if masked
                    value = _unmark_sensitive(value, path, original_data)
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

        return _maybe_refresh(request, _json({"saved": True}))

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

        # Hot-reload provider credentials (API keys, api_base) + agent defaults
        if config_watcher:
            config_watcher.reload_now()

        # After watcher reload, re-apply agent defaults from config.json directly
        # (without env overlay) so WebUI-saved values aren't overridden by
        # DEFAULT_MODEL / other env vars that load_config() always overlays.
        if agent_loop and changed_paths:
            import json as _json_mod
            try:
                with open(config_path, encoding="utf-8") as f:
                    raw = _json_mod.load(f)
                file_defaults = raw.get("agents", {}).get("defaults", {})
                update_kwargs = {}
                _FIELD_MAP = {
                    "agents.defaults.model": ("model", ["model"]),
                    "agents.defaults.temperature": ("temperature", ["temperature"]),
                    "agents.defaults.max_tokens": ("max_tokens", ["maxTokens", "max_tokens"]),
                    "agents.defaults.memory_window": ("memory_window", ["memoryWindow", "memory_window"]),
                    "agents.defaults.max_tool_iterations": ("max_tool_iterations", ["maxToolIterations", "max_tool_iterations"]),
                    "agents.defaults.system_prompt": ("system_prompt", ["systemPrompt", "system_prompt"]),
                    "agents.defaults.disabled_skills": ("disabled_skills", ["disabledSkills", "disabled_skills"]),
                }
                for path in changed_paths:
                    mapping = _FIELD_MAP.get(path)
                    if not mapping:
                        continue
                    kwarg_name, json_keys = mapping
                    for jk in json_keys:
                        if jk in file_defaults:
                            update_kwargs[kwarg_name] = file_defaults[jk]
                            break
                if update_kwargs:
                    agent_loop.update_defaults(**update_kwargs)
            except Exception:
                logger.warning("Settings apply: failed to read config.json for direct update")

        if restart_required:
            logger.info("Settings apply: restart required for {}", restart_fields)
            # Return response first, then exit — K8s/systemd will restart
            resp = _json({
                "reloaded": True,
                "restart_required": True,
                "restart_fields": restart_fields,
            })
            # Schedule graceful shutdown after response is sent (SIGTERM triggers drain sequence)
            import os
            import signal
            asyncio.get_event_loop().call_later(0.5, lambda: os.kill(os.getpid(), signal.SIGTERM))
            return resp

        return _maybe_refresh(request, _json({"reloaded": True, "restart_required": False}))

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

        return _maybe_refresh(request, _json({"skills": skills}))

    # ── PATCH /api/settings/skills/{name} — enable/disable ───────────

    async def toggle_skill(request: Request) -> Response:
        ok, err = _require_auth(request)
        if not ok:
            return err  # type: ignore[return-value]

        name = request.path_params["name"]
        if not _SAFE_NAME_RE.match(name):
            return _json({"error": "Invalid skill name"}, 400)

        try:
            body = await request.json()
        except Exception:
            return _json({"error": "Invalid JSON"}, 400)

        enabled = body.get("enabled")
        if not isinstance(enabled, bool):
            return _json({"error": "Expected {\"enabled\": true|false}"}, 400)

        # Update disabled_skills in config (serialized)
        async with _config_lock:
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

        return _maybe_refresh(request, _json({"name": name, "enabled": enabled}))

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

        if not agent_loop:
            return _json({"error": "Agent not available"}, 503)

        workspace_skills = agent_loop.context.skills.workspace_skills
        workspace_skills.mkdir(parents=True, exist_ok=True)

        import subprocess, shutil, tempfile, re as _re

        # Parse various input formats:
        # 1. "npx skills add https://github.com/owner/repo --skill skill-name"
        # 2. "npx skills add owner/repo --skill skill-name"
        # 3. "https://skills.sh/owner/repo/skill-name"
        # 4. "owner/repo/skill-name"
        # 5. "https://github.com/owner/repo" (existing git clone)

        # Strip "npx skills add " prefix if pasted from CLI
        cleaned = url
        if cleaned.startswith("npx "):
            cleaned = _re.sub(r'^npx\s+skills?\s+add\s+', '', cleaned).strip()

        # Extract --skill flag
        explicit_skill = None
        skill_flag_match = _re.search(r'--skill\s+(\S+)', cleaned)
        if skill_flag_match:
            explicit_skill = skill_flag_match.group(1)
            cleaned = _re.sub(r'\s*--skill\s+\S+', '', cleaned).strip()

        # Detect skills.sh format: "owner/repo/skill" or "https://skills.sh/owner/repo/skill"
        skills_sh_match = None

        if explicit_skill and _SAFE_NAME_RE.match(explicit_skill):
            # --skill flag provided: extract owner/repo from URL or shorthand
            repo_url = cleaned.replace("https://skills.sh/", "").replace("http://skills.sh/", "")
            repo_url = repo_url.replace("https://github.com/", "").replace("http://github.com/", "")
            repo_url = repo_url.rstrip("/").removesuffix(".git")
            repo_parts = [p for p in repo_url.split("/") if p]
            if len(repo_parts) >= 2:
                skills_sh_match = (repo_parts[0], repo_parts[1], explicit_skill)
        else:
            stripped = cleaned.replace("https://skills.sh/", "").replace("http://skills.sh/", "")
            # Match owner/repo/skill-name (3 segments, no protocol)
            parts = [p for p in stripped.strip("/").split("/") if p]
            if len(parts) == 3 and not cleaned.startswith(("https://github", "http://github")):
                owner, repo, skill_name = parts
                if _SAFE_NAME_RE.match(skill_name):
                    skills_sh_match = (owner, repo, skill_name)

        if skills_sh_match:
            owner, repo, skill_name = skills_sh_match
            target = workspace_skills / skill_name
            if not target.resolve().parent == workspace_skills.resolve():
                return _json({"error": "Invalid skill path"}, 400)
            if target.exists():
                return _json({"error": f"Skill '{skill_name}' already exists"}, 409)

            # Clone to temp dir, extract skill subdirectory
            tmp_dir = tempfile.mkdtemp(prefix="lc_skill_")
            try:
                git_url = f"https://github.com/{owner}/{repo}.git"
                result = subprocess.run(
                    ["git", "clone", "--depth=1", git_url, tmp_dir],
                    capture_output=True, text=True, timeout=30,
                )
                if result.returncode != 0:
                    return _json({"error": f"git clone failed: {result.stderr.strip()}"}, 422)

                # Look for skill in skills/<name>/ or <name>/
                skill_src = Path(tmp_dir) / "skills" / skill_name
                if not skill_src.is_dir():
                    skill_src = Path(tmp_dir) / skill_name
                if not skill_src.is_dir() or not (skill_src / "SKILL.md").exists():
                    return _json({"error": f"Skill '{skill_name}' not found in {owner}/{repo}"}, 422)

                shutil.copytree(str(skill_src), str(target))
                return _maybe_refresh(request, _json({"installed": skill_name, "source": f"skills.sh:{owner}/{repo}"}, 201))
            except subprocess.TimeoutExpired:
                return _json({"error": "git clone timed out"}, 422)
            except FileNotFoundError:
                return _json({"error": "git not found on system"}, 500)
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)

        # Standard GitHub URL install (existing logic)
        if not url.startswith(("https://", "http://")):
            return _json({"error": "URL must start with https:// or http://, or use owner/repo/skill format"}, 400)

        # Extract skill name from URL (last path segment) with strict validation
        skill_name = url.rstrip("/").split("/")[-1]
        if skill_name.endswith(".git"):
            skill_name = skill_name[:-4]
        if not _SAFE_NAME_RE.match(skill_name):
            return _json({"error": f"Invalid skill name: '{skill_name}' (only alphanumeric, hyphens, dots, underscores)"}, 400)
        target = workspace_skills / skill_name
        # Defense-in-depth: ensure resolved path stays within workspace_skills
        if not target.resolve().parent == workspace_skills.resolve():
            return _json({"error": "Invalid skill path"}, 400)

        if target.exists():
            return _json({"error": f"Skill '{skill_name}' already exists"}, 409)

        # Git clone
        try:
            result = subprocess.run(
                ["git", "clone", "--depth=1", url, str(target)],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                return _json({"error": f"git clone failed: {result.stderr.strip()}"}, 422)
        except subprocess.TimeoutExpired:
            # Clean up partial clone
            if target.exists():
                shutil.rmtree(target)
            return _json({"error": "git clone timed out"}, 422)
        except FileNotFoundError:
            return _json({"error": "git not found on system"}, 500)

        # Verify SKILL.md exists
        if not (target / "SKILL.md").exists():
            shutil.rmtree(target)
            return _json({"error": "No SKILL.md found in repository"}, 422)

        return _maybe_refresh(request, _json({"installed": skill_name}, 201))

    # ── DELETE /api/settings/skills/{name} ────────────────────────────

    async def delete_skill(request: Request) -> Response:
        ok, err = _require_auth(request)
        if not ok:
            return err  # type: ignore[return-value]

        name = request.path_params["name"]
        if not _SAFE_NAME_RE.match(name):
            return _json({"error": "Invalid skill name"}, 400)

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

        # Also remove from disabled list if present (serialized)
        async with _config_lock:
            from lemonclaw.config.loader import load_config, save_config
            try:
                config = load_config(config_path)
                if name in config.agents.defaults.disabled_skills:
                    config.agents.defaults.disabled_skills.remove(name)
                    save_config(config, config_path)
            except Exception:
                pass  # Non-critical cleanup

        return _maybe_refresh(request, _json({"deleted": name}))

    # ── Assemble routes ───────────────────────────────────────────────

    return [
        Route("/api/settings", get_settings, methods=["GET"]),
        Route("/api/settings", patch_settings, methods=["PATCH"]),
        Route("/api/settings/apply", apply_settings, methods=["POST"]),
        Route("/api/settings/skills", list_skills, methods=["GET"]),
        Route("/api/settings/skills", install_skill, methods=["POST"]),
        Route("/api/settings/skills/{name}", toggle_skill, methods=["PATCH"]),
        Route("/api/settings/skills/{name}", delete_skill, methods=["DELETE"]),
    ]
