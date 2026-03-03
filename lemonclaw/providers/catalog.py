"""Centralized model catalog — the single source of truth for available models.

Add or remove models here. Everything else (slash commands, fallback chains,
display labels) derives from this file.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelEntry:
    id: str                      # LiteLLM model identifier
    label: str                   # Human-readable display name
    tier: str                    # "flagship" | "standard" | "economy" | "specialist"
    description: str             # Short note (shown in /model list)
    fallback: str | None = None  # Model ID to try when this one fails
    hidden: bool = False         # If True, excluded from /model list (internal use only)


# ── Catalog ──────────────────────────────────────────────────────────────────
# Ordered by tier, then by preference within tier.

MODEL_CATALOG: list[ModelEntry] = [
    # Flagship
    ModelEntry("claude-opus-4-6",         "Claude Opus 4.6",          "flagship",   "Most capable",              fallback="claude-opus-4-5"),
    ModelEntry("claude-opus-4-5",         "Claude Opus 4.5",          "flagship",   "Strong all-rounder",        fallback="claude-sonnet-4-6"),
    ModelEntry("gpt-5.2",                 "GPT-5.2",                  "flagship",   "Strong reasoning",          fallback="gpt-4.1-mini"),

    # Standard
    ModelEntry("claude-sonnet-4-6",       "Claude Sonnet 4.6",        "standard",   "Recommended, best value",   fallback="claude-sonnet-4-5"),
    ModelEntry("claude-sonnet-4-5",       "Claude Sonnet 4.5",        "standard",   "Reliable backup",           fallback="gpt-4.1-mini"),
    ModelEntry("gemini-3.1-pro-preview",  "Gemini 3.1 Pro",           "standard",   "1M context, strong vision", fallback="claude-sonnet-4-6"),
    ModelEntry("deepseek-v3-2",           "DeepSeek V3.2",            "standard",   "Great value, strong Chinese", fallback="claude-sonnet-4-6"),
    ModelEntry("kimi-k2.5",              "Kimi K2.5",                "standard",   "Long-context Chinese",      fallback="deepseek-v3-2"),
    ModelEntry("grok-4.1",               "Grok 4.1",                 "standard",   "Real-time knowledge",       fallback="gpt-5.2"),

    # Economy
    ModelEntry("claude-haiku-4-5",        "Claude Haiku 4.5",         "economy",    "Fast and lightweight",      fallback="gpt-4.1-mini"),
    ModelEntry("gpt-4.1-mini",            "GPT-4.1 Mini",             "economy",    "Stable tool calling",       fallback="claude-haiku-4-5"),
    ModelEntry("gemini-3-flash-preview",  "Gemini 3 Flash",           "economy",    "Ultra fast, low cost",      fallback="gpt-4.1-mini"),
    ModelEntry("minimax-m2.5",            "MiniMax M2.5",             "economy",    "Cheapest option",           fallback="gpt-4.1-mini"),
    ModelEntry("glm-5",                   "GLM-5",                    "economy",    "128K output",               fallback="deepseek-v3-2"),

    # Groq (ultra-fast inference, used for consolidation — hidden from /model)
    ModelEntry("llama-3.3-70b-versatile",          "Llama 3.3 70B (Groq)",   "economy", "394 TPS, strong tool calling", fallback="qwen3-32b", hidden=True),
    ModelEntry("qwen3-32b",                        "Qwen3 32B (Groq)",       "economy", "662 TPS, fast and cheap",      fallback="llama-4-scout-17b-16e-instruct", hidden=True),
    ModelEntry("llama-4-scout-17b-16e-instruct",   "Llama 4 Scout (Groq)",   "economy", "594 TPS, cheapest Groq",       fallback="gpt-4.1-mini", hidden=True),

    # Specialist
    ModelEntry("gpt-5.3-codex",           "GPT-5.3 Codex",            "specialist", "Code generation",           fallback="claude-sonnet-4-6"),
    ModelEntry("deepseek-r1",             "DeepSeek R1",               "specialist", "Deep reasoning (CoT)",      fallback="claude-opus-4-6"),
]

# ── Derived lookups ──────────────────────────────────────────────────────────

MODEL_MAP: dict[str, ModelEntry] = {m.id: m for m in MODEL_CATALOG}

DEFAULT_MODEL: str = "claude-sonnet-4-6"

# Tier display order
TIER_ORDER: dict[str, int] = {"flagship": 0, "standard": 1, "economy": 2, "specialist": 3}
TIER_LABELS: dict[str, str] = {
    "flagship": "Flagship",
    "standard": "Standard",
    "economy": "Economy",
    "specialist": "Specialist",
}


def fuzzy_match(query: str) -> ModelEntry | None:
    """Find a model by exact ID, partial ID, label substring, or semantic alias.

    Only searches visible (non-hidden) models.
    Priority: exact id > semantic alias > id prefix > id substring > label substring.
    """
    q = query.lower().strip()
    if not q:
        return None

    visible = [m for m in MODEL_CATALOG if not m.hidden]

    # Exact match (visible only)
    for m in visible:
        if m.id == q:
            return m

    # Semantic alias (e.g. "best-for-code" → claude-opus-4-6)
    from lemonclaw.providers.aliases import resolve_alias
    alias_hit = resolve_alias(q)
    if alias_hit:
        return alias_hit

    # Prefix match (e.g. "claude-sonnet" → "claude-sonnet-4-6")
    prefix_hits = [m for m in visible if m.id.startswith(q)]
    if len(prefix_hits) == 1:
        return prefix_hits[0]

    # Substring match on id
    sub_hits = [m for m in visible if q in m.id]
    if len(sub_hits) == 1:
        return sub_hits[0]

    # Label substring
    label_hits = [m for m in visible if q in m.label.lower()]
    if len(label_hits) == 1:
        return label_hits[0]

    # Multiple matches — prefer shortest id (most specific)
    all_hits = prefix_hits or sub_hits or label_hits
    if all_hits:
        return min(all_hits, key=lambda m: len(m.id))

    return None


def format_model_list(current_model: str | None = None) -> str:
    """Format the model catalog as a grouped display string for /model command."""
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
            marker = " ← current" if current_model and m.id == current_model else ""
            lines.append(f"  `{m.id}` — {m.description}{marker}")

    header = "Available models (use `/model <name>` to switch):\n"
    footer = "\n\n**Aliases** (use `/model <alias>` to switch):"
    from lemonclaw.providers.aliases import list_aliases
    for alias, model_id in list_aliases().items():
        footer += f"\n  `{alias}` → {model_id}"
    return header + "\n".join(lines) + footer
