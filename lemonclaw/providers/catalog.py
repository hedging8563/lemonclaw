"""Centralized model catalog — builtin metadata plus hosted runtime direct-config overrides."""

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
    fallback: str | None = None
    hidden: bool = False
    source: str = "builtin"
    profile: str | None = None
    aliases: tuple[str, ...] = ()


_BUILTIN_MODEL_CATALOG: list[ModelEntry] = [
    ModelEntry("gpt-5.4", "GPT-5.4", "flagship", "Latest frontier model", fallback="gpt-5.2"),
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

_BUILTIN_MODEL_MAP: dict[str, ModelEntry] = {m.id: m for m in _BUILTIN_MODEL_CATALOG}
_DEFAULT_CHAT_MODELS = [m.id for m in _BUILTIN_MODEL_CATALOG if not m.hidden]
_DEFAULT_VISION_CHAIN = ["gpt-4.1-mini", "claude-haiku-4-5", "gemini-3.1-pro-preview"]
_DEFAULT_MEMORY_ORDER = [
    "text-embedding-005",
    "gemini-embedding-001",
    "text-multilingual-embedding-002",
]
_DEFAULTS = {
    "chat": "gpt-5.4",
    "vision": "gpt-4.1-mini",
    "coding": "claude-sonnet-4-6",
    "consolidation": "llama-3.3-70b-versatile",
}

MODEL_CATALOG: list[ModelEntry] = list(_BUILTIN_MODEL_CATALOG)
MODEL_MAP: dict[str, ModelEntry] = {m.id: m for m in MODEL_CATALOG}
DEFAULT_MODEL: str = _DEFAULTS["chat"]
_RUNTIME_CHAT_MODELS: list[str] = list(_DEFAULT_CHAT_MODELS)
_RUNTIME_VISION_CHAIN: list[str] = list(_DEFAULT_VISION_CHAIN)
_RUNTIME_ALIAS_MAP: dict[str, str] = {}
_RUNTIME_MEMORY_POLICY: dict[str, Any] = {
    "indexMode": "auto",
    "embeddingOrder": list(_DEFAULT_MEMORY_ORDER),
}
_RUNTIME_POLICY_ACTIVE = False
_RUNTIME_POLICY_PATH = Path(os.environ.get('LEMONCLAW_RUNTIME_MODEL_POLICY_PATH', str(Path.home() / '.lemonclaw' / 'runtime-model-policy.json')))

TIER_ORDER: dict[str, int] = {"flagship": 0, "standard": 1, "economy": 2, "specialist": 3}
TIER_LABELS: dict[str, str] = {"flagship": "Flagship", "standard": "Standard", "economy": "Economy", "specialist": "Specialist"}


def _dedupe(seq: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in seq:
        normalized = str(item or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out


def _normalize_model_key(model_id: str | None) -> str:
    return str(model_id or '').strip().lower()


def _is_builtin_model(model_id: str) -> bool:
    return model_id in _BUILTIN_MODEL_MAP


def _is_vision_capable(model_id: str) -> bool:
    entry = _BUILTIN_MODEL_MAP.get(model_id)
    if not entry:
        return False
    return model_id in {"gpt-4.1-mini", "claude-haiku-4-5", "gemini-3.1-pro-preview", "claude-sonnet-4-6"}


def _reset_to_builtin() -> None:
    MODEL_CATALOG[:] = list(_BUILTIN_MODEL_CATALOG)
    MODEL_MAP.clear()
    MODEL_MAP.update({m.id: m for m in MODEL_CATALOG})
    _RUNTIME_CHAT_MODELS.clear()
    _RUNTIME_CHAT_MODELS.extend(_DEFAULT_CHAT_MODELS)
    _RUNTIME_VISION_CHAIN.clear()
    _RUNTIME_VISION_CHAIN.extend(_DEFAULT_VISION_CHAIN)
    _RUNTIME_ALIAS_MAP.clear()
    _RUNTIME_MEMORY_POLICY.clear()
    _RUNTIME_MEMORY_POLICY.update({
        "indexMode": "auto",
        "embeddingOrder": list(_DEFAULT_MEMORY_ORDER),
    })
    globals()['DEFAULT_MODEL'] = _DEFAULTS["chat"]
    globals()['_RUNTIME_POLICY_ACTIVE'] = False


def _coerce_direct_config(policy: dict[str, Any]) -> dict[str, Any]:
    if isinstance(policy.get("chat"), dict) and isinstance(policy.get("vision"), dict) and isinstance(policy.get("memory"), dict):
        chat = policy["chat"]
        vision = policy["vision"]
        memory = policy["memory"]
        available_models = [
            model_id
            for model_id in _dedupe([str(item) for item in list(chat.get("availableModels") or [])])
            if _is_builtin_model(model_id)
        ]
        default_model = str(chat.get("defaultModel") or "").strip()
        if not _is_builtin_model(default_model):
            default_model = _DEFAULTS["chat"]
        if default_model not in available_models:
            available_models.insert(0, default_model)

        vision_chain = [
            model_id
            for model_id in _dedupe([str(item) for item in list(vision.get("chain") or [])])
            if _is_builtin_model(model_id) and _is_vision_capable(model_id)
        ] or list(_DEFAULT_VISION_CHAIN)

        embedding_order = _dedupe([str(item) for item in list(memory.get("embeddingOrder") or [])]) or list(_DEFAULT_MEMORY_ORDER)

        return {
            "chat": {
                "defaultModel": default_model,
                "availableModels": available_models or list(_DEFAULT_CHAT_MODELS),
            },
            "vision": {
                "chain": vision_chain,
            },
            "memory": {
                "indexMode": str(memory.get("indexMode") or "auto").strip().lower() or "auto",
                "embeddingOrder": embedding_order,
            },
        }

    defaults = policy.get("defaults") if isinstance(policy.get("defaults"), dict) else {}
    catalog = [entry for entry in list(policy.get("catalog") or []) if isinstance(entry, dict)]
    profiles = policy.get("profiles") if isinstance(policy.get("profiles"), dict) else {}
    scene_profiles = policy.get("sceneProfiles") if isinstance(policy.get("sceneProfiles"), dict) else {}
    internal = policy.get("internal") if isinstance(policy.get("internal"), dict) else {}
    internal_memory = internal.get("memory") if isinstance(internal.get("memory"), dict) else {}

    available_models = [
        model_id
        for model_id in _dedupe([
            str(entry.get("id") or "")
            for entry in catalog
            if bool(entry.get("visible", False)) and bool(entry.get("enabled", True))
        ])
        if _is_builtin_model(model_id)
    ]
    default_model = str(defaults.get("chat") or "").strip()
    if not _is_builtin_model(default_model):
        default_model = _DEFAULTS["chat"]
    if default_model not in available_models:
        available_models.insert(0, default_model)

    vision_profile_name = str(scene_profiles.get("vision") or "").strip()
    vision_models = profiles.get(vision_profile_name) if isinstance(profiles.get(vision_profile_name), list) else []
    vision_chain = [
        model_id
        for model_id in _dedupe([str(defaults.get("vision") or ""), *[str(item) for item in vision_models]])
        if _is_builtin_model(model_id) and _is_vision_capable(model_id)
    ] or list(_DEFAULT_VISION_CHAIN)

    preferred_embedding_model = str(internal_memory.get("preferredEmbeddingModel") or _DEFAULT_MEMORY_ORDER[0]).strip()
    fallback_embedding_models = [str(item) for item in list(internal_memory.get("fallbackEmbeddingModels") or _DEFAULT_MEMORY_ORDER[1:])]
    embedding_order = _dedupe([preferred_embedding_model, *fallback_embedding_models]) or list(_DEFAULT_MEMORY_ORDER)

    return {
        "chat": {
            "defaultModel": default_model,
            "availableModels": available_models or list(_DEFAULT_CHAT_MODELS),
        },
        "vision": {
            "chain": vision_chain,
        },
        "memory": {
            "indexMode": str(internal_memory.get("indexMode") or "auto").strip().lower() or "auto",
            "embeddingOrder": embedding_order,
        },
    }


def resolve_model_id(model_id: str | None) -> str | None:
    normalized = str(model_id or '').strip()
    if not normalized:
        return None

    if normalized in MODEL_MAP:
        return normalized

    normalized_key = _normalize_model_key(normalized)
    alias_hit = _RUNTIME_ALIAS_MAP.get(normalized_key)
    if alias_hit:
        return alias_hit

    for canonical_id in MODEL_MAP:
        if _normalize_model_key(canonical_id) == normalized_key:
            return canonical_id

    return normalized


def get_runtime_default_model(scene: str = 'chat') -> str:
    if scene == "chat":
        return DEFAULT_MODEL
    if scene == "vision":
        return _RUNTIME_VISION_CHAIN[0] if _RUNTIME_VISION_CHAIN else _DEFAULTS["vision"]
    if scene == "coding":
        return _DEFAULTS["coding"]
    if scene == "consolidation":
        return _DEFAULTS["consolidation"]
    return DEFAULT_MODEL


def get_runtime_memory_policy() -> dict[str, Any]:
    order = _dedupe([str(item) for item in list(_RUNTIME_MEMORY_POLICY.get("embeddingOrder") or [])]) or list(_DEFAULT_MEMORY_ORDER)
    return {
        "indexMode": str(_RUNTIME_MEMORY_POLICY.get("indexMode") or "auto"),
        "embeddingOrder": order,
        "preferredEmbeddingModel": order[0],
        "fallbackEmbeddingModels": order[1:],
    }


def get_fallback_chain(model_id: str, scene: str = 'chat') -> list[str]:
    resolved_model = resolve_model_id(model_id) or model_id
    if _RUNTIME_POLICY_ACTIVE:
        if scene == "vision":
            if resolved_model in _RUNTIME_VISION_CHAIN:
                return list(_RUNTIME_VISION_CHAIN[_RUNTIME_VISION_CHAIN.index(resolved_model):])
            return [resolved_model]
        return [resolved_model]

    chain: list[str] = []
    visited: set[str] = set()
    current = resolved_model
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

    config = _coerce_direct_config(policy)
    chat_ids = config["chat"]["availableModels"]
    vision_chain = config["vision"]["chain"]
    memory_policy = config["memory"]

    visible_entries = []
    for model_id in chat_ids:
        builtin = _BUILTIN_MODEL_MAP.get(model_id)
        if not builtin:
            continue
        visible_entries.append(ModelEntry(
            id=builtin.id,
            label=builtin.label,
            tier=builtin.tier,
            description=builtin.description,
            fallback=None,
            hidden=False,
            source="runtime-policy",
            profile="chat",
            aliases=(),
        ))

    hidden_entries = []
    for builtin in _BUILTIN_MODEL_CATALOG:
        if builtin.id in chat_ids:
            continue
        profile = "vision" if builtin.id in vision_chain else None
        hidden_entries.append(ModelEntry(
            id=builtin.id,
            label=builtin.label,
            tier=builtin.tier,
            description=builtin.description,
            fallback=None,
            hidden=True,
            source="runtime-policy",
            profile=profile,
            aliases=(),
        ))

    MODEL_CATALOG[:] = [*visible_entries, *hidden_entries]
    MODEL_MAP.clear()
    MODEL_MAP.update({m.id: m for m in MODEL_CATALOG})
    _RUNTIME_CHAT_MODELS.clear()
    _RUNTIME_CHAT_MODELS.extend(chat_ids)
    _RUNTIME_VISION_CHAIN.clear()
    _RUNTIME_VISION_CHAIN.extend(vision_chain)
    _RUNTIME_ALIAS_MAP.clear()
    _RUNTIME_MEMORY_POLICY.clear()
    _RUNTIME_MEMORY_POLICY.update({
        "indexMode": memory_policy["indexMode"],
        "embeddingOrder": list(memory_policy["embeddingOrder"]),
    })
    globals()['DEFAULT_MODEL'] = config["chat"]["defaultModel"]
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
    entry = MODEL_MAP.get(resolve_model_id(model_id) or model_id)
    return entry.source if entry else ('runtime-policy' if runtime_policy_active() else 'builtin')


def get_model_profile(model_id: str, scene: str = 'chat') -> str | None:
    resolved_model_id = resolve_model_id(model_id) or model_id
    if scene == "chat" and resolved_model_id in _RUNTIME_CHAT_MODELS:
        return "chat"
    if scene == "vision" and resolved_model_id in _RUNTIME_VISION_CHAIN:
        return "vision"
    entry = MODEL_MAP.get(resolved_model_id)
    return entry.profile if entry else None


def get_model_runtime_meta(model_id: str, scene: str = 'chat') -> dict[str, str | bool | None]:
    resolved_model_id = resolve_model_id(model_id) or model_id
    return {
        'source': get_model_source(resolved_model_id),
        'profile': get_model_profile(resolved_model_id, scene),
        'runtimePolicyActive': runtime_policy_active(),
    }


def format_model_runtime_badge(model_id: str, scene: str = 'chat') -> str:
    meta = get_model_runtime_meta(model_id, scene)
    bits = ['runtime-policy' if meta['source'] == 'runtime-policy' else 'builtin']
    if isinstance(meta['profile'], str) and meta['profile']:
        bits.append(f"group={meta['profile']}")
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
        if _normalize_model_key(m.id) == q:
            return m
    for canonical_id in MODEL_MAP:
        if _normalize_model_key(canonical_id) == q:
            entry = MODEL_MAP.get(canonical_id)
            if entry and not entry.hidden:
                return entry
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
    resolved_current = resolve_model_id(current_model) if current_model else None
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
            marker = ' ← current' if resolved_current and m.id == resolved_current else ''
            lines.append(f"  `{m.id}` — {m.description}{marker}")
    header = 'Available models (use `/model <name>` to switch):\n'
    return header + '\n'.join(lines)
