"""Centralized model catalog — baseline defaults + hosted runtime override support."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ModelEntry:
    id: str
    label: str
    tier: str
    description: str
    fallback: str | None = None  # compatibility field derived from active fallback profile
    hidden: bool = False
    source: str = "builtin"
    profile: str | None = None


_BUILTIN_MODEL_CATALOG: list[ModelEntry] = [
    ModelEntry("claude-opus-4-6", "Claude Opus 4.6", "flagship", "Most capable", fallback="claude-opus-4-5"),
    ModelEntry("claude-opus-4-5", "Claude Opus 4.5", "flagship", "Strong all-rounder", fallback="claude-sonnet-4-6"),
    ModelEntry("gpt-5.2", "GPT-5.2", "flagship", "Strong reasoning", fallback="gpt-4.1-mini"),
    ModelEntry("claude-sonnet-4-6", "Claude Sonnet 4.6", "standard", "Recommended, best value", fallback="claude-sonnet-4-5"),
    ModelEntry("claude-sonnet-4-5", "Claude Sonnet 4.5", "standard", "Reliable backup", fallback="gpt-4.1-mini"),
    ModelEntry("gemini-3.1-pro-preview", "Gemini 3.1 Pro", "standard", "1M context, strong vision", fallback="claude-sonnet-4-6"),
    ModelEntry("deepseek-v3-2", "DeepSeek V3.2", "standard", "Great value, strong Chinese", fallback="claude-sonnet-4-6"),
    ModelEntry("kimi-k2.5", "Kimi K2.5", "standard", "Long-context Chinese", fallback="deepseek-v3-2"),
    ModelEntry("grok-4.1", "Grok 4.1", "standard", "Real-time knowledge", fallback="gpt-5.2"),
    ModelEntry("claude-haiku-4-5", "Claude Haiku 4.5", "economy", "Fast and lightweight", fallback="gpt-4.1-mini"),
    ModelEntry("gpt-4.1-mini", "GPT-4.1 Mini", "economy", "Stable tool calling", fallback="claude-haiku-4-5"),
    ModelEntry("gemini-3-flash-preview", "Gemini 3 Flash", "economy", "Ultra fast, low cost", fallback="gpt-4.1-mini"),
    ModelEntry("minimax-m2.5", "MiniMax M2.5", "economy", "Cheapest option", fallback="gpt-4.1-mini"),
    ModelEntry("glm-5", "GLM-5", "economy", "128K output", fallback="deepseek-v3-2"),
    ModelEntry("llama-3.3-70b-versatile", "Llama 3.3 70B (Groq)", "economy", "394 TPS, strong tool calling", fallback="qwen3-32b", hidden=True),
    ModelEntry("qwen3-32b", "Qwen3 32B (Groq)", "economy", "662 TPS, fast and cheap", fallback="llama-4-scout-17b-16e-instruct", hidden=True),
    ModelEntry("llama-4-scout-17b-16e-instruct", "Llama 4 Scout (Groq)", "economy", "594 TPS, cheapest Groq", fallback="gpt-4.1-mini", hidden=True),
    ModelEntry("gpt-5.3-codex", "GPT-5.3 Codex", "specialist", "Code generation", fallback="claude-sonnet-4-6"),
    ModelEntry("deepseek-r1", "DeepSeek R1", "specialist", "Deep reasoning (CoT)", fallback="claude-opus-4-6"),
]

MODEL_CATALOG: list[ModelEntry] = list(_BUILTIN_MODEL_CATALOG)
MODEL_MAP: dict[str, ModelEntry] = {m.id: m for m in MODEL_CATALOG}
DEFAULT_MODEL: str = "claude-sonnet-4-6"
_RUNTIME_DEFAULTS: dict[str, str] = {
    "chat": DEFAULT_MODEL,
    "vision": "gpt-4.1-mini",
    "fast": "gpt-4.1-mini",
    "reasoning": "claude-opus-4-6",
    "coding": "claude-sonnet-4-6",
    "consolidation": "llama-3.3-70b-versatile",
}
_RUNTIME_SCENE_PROFILES: dict[str, str] = {}
_RUNTIME_PROFILES: dict[str, list[str]] = {}
_RUNTIME_MODEL_PROFILE_OVERRIDES: dict[str, str] = {}
_RUNTIME_POLICY_ACTIVE = False
_RUNTIME_POLICY_PATH = Path(os.environ.get('LEMONCLAW_RUNTIME_MODEL_POLICY_PATH', str(Path.home() / '.lemonclaw' / 'runtime-model-policy.json')))

TIER_ORDER: dict[str, int] = {"flagship": 0, "standard": 1, "economy": 2, "specialist": 3}
TIER_LABELS: dict[str, str] = {"flagship": "Flagship", "standard": "Standard", "economy": "Economy", "specialist": "Specialist"}


def _builtin_defaults() -> dict[str, str]:
    return {
        "chat": "claude-sonnet-4-6",
        "vision": "gpt-4.1-mini",
        "fast": "gpt-4.1-mini",
        "reasoning": "claude-opus-4-6",
        "coding": "claude-sonnet-4-6",
        "consolidation": "llama-3.3-70b-versatile",
    }


def _reset_to_builtin() -> None:
    MODEL_CATALOG[:] = list(_BUILTIN_MODEL_CATALOG)
    MODEL_MAP.clear()
    MODEL_MAP.update({m.id: m for m in MODEL_CATALOG})
    _RUNTIME_DEFAULTS.clear()
    _RUNTIME_DEFAULTS.update(_builtin_defaults())
    _RUNTIME_SCENE_PROFILES.clear()
    _RUNTIME_PROFILES.clear()
    _RUNTIME_MODEL_PROFILE_OVERRIDES.clear()
    globals()['DEFAULT_MODEL'] = _RUNTIME_DEFAULTS['chat']
    globals()['_RUNTIME_POLICY_ACTIVE'] = False


def _dedupe(seq: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in seq:
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def get_runtime_default_model(scene: str = 'chat') -> str:
    return _RUNTIME_DEFAULTS.get(scene, _RUNTIME_DEFAULTS['chat'])


def get_fallback_chain(model_id: str, scene: str = 'chat') -> list[str]:
    profile_name = _RUNTIME_MODEL_PROFILE_OVERRIDES.get(model_id) or _RUNTIME_SCENE_PROFILES.get(scene)
    if profile_name and profile_name in _RUNTIME_PROFILES:
        return _dedupe([model_id, *_RUNTIME_PROFILES[profile_name]])
    chain: list[str] = []
    visited: set[str] = set()
    current = model_id
    while current and current not in visited:
        visited.add(current)
        chain.append(current)
        entry = MODEL_MAP.get(current)
        current = entry.fallback if entry else None
    return chain


def apply_runtime_model_policy(policy: dict[str, Any] | None) -> None:
    if not policy:
        _reset_to_builtin()
        return

    raw_catalog = policy.get('catalog') or []
    defaults = policy.get('defaults') or {}
    raw_profiles = policy.get('profiles') or {}
    raw_scene_profiles = policy.get('sceneProfiles') or {}
    raw_model_overrides = policy.get('modelProfileOverrides') or {}

    runtime_rows: list[dict[str, Any]] = []
    active_model_ids: set[str] = set()
    for raw in raw_catalog:
        if not isinstance(raw, dict):
            continue
        model_id = str(raw.get('id') or '').strip()
        if not model_id or not bool(raw.get('enabled', True)):
            continue
        runtime_rows.append(raw)
        active_model_ids.add(model_id)

    if not active_model_ids:
        _reset_to_builtin()
        return

    profiles: dict[str, list[str]] = {}
    for key, value in raw_profiles.items():
        if not isinstance(value, list):
            continue
        profile_name = str(key)
        profiles[profile_name] = [
            candidate
            for candidate in _dedupe([str(item) for item in value if item])
            if candidate in active_model_ids
        ]

    scene_profiles = {
        str(key): str(value)
        for key, value in raw_scene_profiles.items()
        if isinstance(value, str) and value and str(value) in profiles
    }
    model_overrides = {
        str(key): str(value)
        for key, value in raw_model_overrides.items()
        if isinstance(value, str) and value and str(key) in active_model_ids and str(value) in profiles
    }

    built_entries: list[ModelEntry] = []
    for raw in runtime_rows:
        model_id = str(raw.get('id') or '').strip()
        profile_name = model_overrides.get(model_id) or scene_profiles.get('chat')
        chain = _dedupe([model_id, *(profiles.get(profile_name) or [])]) if profile_name else [model_id]
        fallback = None
        if model_id in chain:
            idx = chain.index(model_id)
            fallback = chain[idx + 1] if idx + 1 < len(chain) else None
        built_entries.append(ModelEntry(
            id=model_id,
            label=str(raw.get('label') or model_id),
            tier=str(raw.get('tier') or 'standard'),
            description=str(raw.get('description') or model_id),
            fallback=fallback,
            hidden=not bool(raw.get('visible', True)),
            source='runtime-policy',
            profile=profile_name,
        ))

    MODEL_CATALOG[:] = built_entries
    MODEL_MAP.clear()
    MODEL_MAP.update({m.id: m for m in MODEL_CATALOG})
    _RUNTIME_DEFAULTS.clear()
    _RUNTIME_DEFAULTS.update({
        **_builtin_defaults(),
        **{
            k: str(v)
            for k, v in defaults.items()
            if isinstance(v, str) and v and str(v) in active_model_ids
        },
    })
    _RUNTIME_SCENE_PROFILES.clear()
    _RUNTIME_SCENE_PROFILES.update(scene_profiles)
    _RUNTIME_PROFILES.clear()
    _RUNTIME_PROFILES.update(profiles)
    _RUNTIME_MODEL_PROFILE_OVERRIDES.clear()
    _RUNTIME_MODEL_PROFILE_OVERRIDES.update(model_overrides)
    globals()['DEFAULT_MODEL'] = _RUNTIME_DEFAULTS['chat']
    globals()['_RUNTIME_POLICY_ACTIVE'] = True


def load_runtime_model_policy_from_disk() -> None:
    try:
        if not _RUNTIME_POLICY_PATH.exists():
            _reset_to_builtin()
            return
        data = json.loads(_RUNTIME_POLICY_PATH.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            _reset_to_builtin()
            return
        apply_runtime_model_policy(data)
    except Exception:
        _reset_to_builtin()


load_runtime_model_policy_from_disk()


def runtime_policy_active() -> bool:
    return bool(_RUNTIME_POLICY_ACTIVE)


def get_model_source(model_id: str) -> str:
    entry = MODEL_MAP.get(model_id)
    return entry.source if entry else ('runtime-policy' if runtime_policy_active() else 'builtin')


def get_model_profile(model_id: str, scene: str = 'chat') -> str | None:
    entry = MODEL_MAP.get(model_id)
    if entry and entry.profile:
        return entry.profile
    return _RUNTIME_MODEL_PROFILE_OVERRIDES.get(model_id) or _RUNTIME_SCENE_PROFILES.get(scene)


def get_model_runtime_meta(model_id: str, scene: str = 'chat') -> dict[str, str | bool | None]:
    return {
        'source': get_model_source(model_id),
        'profile': get_model_profile(model_id, scene),
        'runtimePolicyActive': runtime_policy_active(),
    }


def format_model_runtime_badge(model_id: str, scene: str = 'chat') -> str:
    meta = get_model_runtime_meta(model_id, scene)
    bits = ['runtime-policy' if meta['source'] == 'runtime-policy' else 'builtin']
    if isinstance(meta['profile'], str) and meta['profile']:
        bits.append(f"profile={meta['profile']}")
    return ' · '.join(bits)


def get_model_tiers() -> list[tuple[str, list[ModelEntry]]]:
    grouped: dict[str, list[ModelEntry]] = {}
    for m in MODEL_CATALOG:
        if m.hidden:
            continue
        grouped.setdefault(m.tier, []).append(m)
    return [(TIER_LABELS.get(tier, tier.title()), grouped[tier]) for tier in sorted(grouped, key=lambda t: TIER_ORDER.get(t, 99))]


def fuzzy_match(query: str) -> ModelEntry | None:
    q = query.lower().strip()
    if not q:
        return None
    visible = [m for m in MODEL_CATALOG if not m.hidden]
    for m in visible:
        if m.id == q:
            return m
    from lemonclaw.providers.aliases import resolve_alias
    alias_hit = resolve_alias(q)
    if alias_hit:
        return alias_hit
    prefix_hits = [m for m in visible if m.id.startswith(q)]
    if len(prefix_hits) == 1:
        return prefix_hits[0]
    sub_hits = [m for m in visible if q in m.id]
    if len(sub_hits) == 1:
        return sub_hits[0]
    label_hits = [m for m in visible if q in m.label.lower()]
    if len(label_hits) == 1:
        return label_hits[0]
    all_hits = prefix_hits or sub_hits or label_hits
    if all_hits:
        return min(all_hits, key=lambda m: len(m.id))
    return None


def format_model_list(current_model: str | None = None) -> str:
    lines: list[str] = []
    grouped: dict[str, list[ModelEntry]] = {}
    for m in MODEL_CATALOG:
        if m.hidden:
            continue
        grouped.setdefault(m.tier, []).append(m)
    for tier in sorted(grouped, key=lambda t: TIER_ORDER.get(t, 99)):
        label = TIER_LABELS.get(tier, tier.title())
        lines.append(f"\n**{label}**")
        for m in grouped[tier]:
            marker = ' ← current' if current_model and m.id == current_model else ''
            lines.append(f"  `{m.id}` — {m.description}{marker}")
    header = 'Available models (use `/model <name>` to switch):\n'
    footer = '\n\n**Aliases** (use `/model <alias>` to switch):'
    from lemonclaw.providers.aliases import list_aliases
    for alias, model_id in list_aliases().items():
        footer += f"\n  `{alias}` → {model_id}"
    return header + '\n'.join(lines) + footer
