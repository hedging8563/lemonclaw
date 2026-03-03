"""Model semantic aliases + budget-aware tier downgrade."""

from __future__ import annotations

from lemonclaw.providers.catalog import MODEL_MAP, ModelEntry, TIER_ORDER

# Semantic aliases — map intent to ordered candidate list (best first)
MODEL_ALIASES: dict[str, list[str]] = {
    "fast-and-cheap": ["claude-haiku-4-5", "gpt-4.1-mini", "gemini-3-flash-preview", "minimax-m2.5"],
    "best-for-content": ["claude-sonnet-4-6", "gpt-5.2", "gemini-3.1-pro-preview", "deepseek-v3-2"],
    "best-for-plan": ["claude-opus-4-6", "gpt-5.2", "deepseek-v3-2"],
    "best-for-code": ["claude-opus-4-6", "gpt-5.3-codex", "deepseek-v3-2", "kimi-k2.5"],
    "best-for-reasoning": ["claude-opus-4-6", "deepseek-r1", "gpt-5.2"],
}

# Tier downgrade order: flagship → standard → economy
_TIER_DOWNGRADE: list[str] = ["flagship", "standard", "economy"]


def resolve_alias(alias: str) -> ModelEntry | None:
    """Resolve a semantic alias to the first available model entry."""
    candidates = MODEL_ALIASES.get(alias.lower().strip())
    if not candidates:
        return None
    for model_id in candidates:
        entry = MODEL_MAP.get(model_id)
        if entry:
            return entry
    return None


def list_aliases() -> dict[str, str]:
    """Return alias → first candidate model id mapping for display."""
    result: dict[str, str] = {}
    for alias, candidates in MODEL_ALIASES.items():
        for mid in candidates:
            if mid in MODEL_MAP:
                result[alias] = mid
                break
    return result


def downgrade_tier(current_model: str) -> ModelEntry | None:
    """Find a cheaper model in the next tier down. Returns None if already at economy."""
    entry = MODEL_MAP.get(current_model)
    if not entry:
        return None

    current_tier_idx = _TIER_DOWNGRADE.index(entry.tier) if entry.tier in _TIER_DOWNGRADE else -1
    if current_tier_idx < 0 or current_tier_idx >= len(_TIER_DOWNGRADE) - 1:
        return None  # Already economy or specialist

    target_tier = _TIER_DOWNGRADE[current_tier_idx + 1]
    # Pick first model in target tier from catalog order
    from lemonclaw.providers.catalog import MODEL_CATALOG
    for m in MODEL_CATALOG:
        if m.tier == target_tier and not m.hidden:
            return m
    return None


def budget_aware_select(current_model: str, balance_usd: float, threshold_usd: float = 1.0) -> str:
    """Select model considering budget. Downgrades tier if balance is low.

    Args:
        current_model: Currently configured model id
        balance_usd: User's remaining balance in USD
        threshold_usd: Balance threshold to trigger downgrade

    Returns:
        Model id to use (may be downgraded)
    """
    if balance_usd >= threshold_usd:
        return current_model

    downgraded = downgrade_tier(current_model)
    if downgraded:
        return downgraded.id
    return current_model
