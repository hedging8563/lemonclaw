"""MEMORY.md → Entity Cards migration — one-time upgrade from flat to structured LTM."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from lemonclaw.memory.entities import DEFAULT_CARDS, EntityStore

if TYPE_CHECKING:
    from lemonclaw.providers.base import LLMProvider

# LLM prompt for splitting MEMORY.md into entity cards
_MIGRATE_SYSTEM = """You are a memory migration assistant. Split the user's MEMORY.md content into structured entity cards.

Return a JSON object where keys are card names and values are the markdown body for each card.
Only use these card names: {card_names}

Rules:
- Each card body should start with a markdown heading (# Card Title)
- Put each fact into the most relevant card
- If a fact doesn't fit any card, put it in "preferences"
- Preserve all information — do not drop any facts
- Keep the original language (Chinese/English)
- Return ONLY valid JSON, no markdown fences"""

_MIGRATE_USER = """Split this MEMORY.md into entity cards:

{content}"""


async def migrate_memory_to_entities(
    memory_dir: Path,
    entity_store: EntityStore,
    provider: LLMProvider | None = None,
    model: str = "",
) -> bool:
    """Migrate MEMORY.md to entity cards. Returns True if migration happened.

    - If entities/ already has cards, skip (idempotent)
    - If MEMORY.md is empty/missing, just init defaults
    - If LLM available, use it to split content intelligently
    - If LLM unavailable, fallback: dump everything into a single card
    """
    # Already migrated with non-trivial content — skip
    existing_cards = entity_store.list_cards()
    if existing_cards and not _cards_look_like_default_shells(existing_cards):
        return False

    memory_file = memory_dir / "MEMORY.md"
    if not memory_file.exists():
        entity_store.init_defaults()
        return True

    content = memory_file.read_text(encoding="utf-8").strip()
    if not content:
        entity_store.init_defaults()
        return True

    logger.info("Migrating MEMORY.md ({} chars) to entity cards", len(content))

    # Try LLM-assisted migration
    if provider and model:
        try:
            result = await _llm_migrate(content, entity_store, provider, model)
            if result:
                logger.info("LLM migration complete — {} cards created", len(entity_store.list_cards()))
                return True
        except Exception:
            logger.warning("LLM migration failed, using fallback", exc_info=True)

    # Fallback: init defaults + dump content into preferences card
    _fallback_migrate(content, entity_store)
    logger.info("Fallback migration complete — content saved to preferences card")
    return True


def _cards_look_like_default_shells(cards: list) -> bool:
    """Return True when the existing cards are only untouched default shells.

    This lets migration proceed even if init_defaults() ran earlier, as long as
    those files do not contain meaningful body content yet.
    """
    if not cards:
        return False

    for card in cards:
        body = str(getattr(card, "body", "") or "").strip()
        name = str(getattr(card, "name", "") or "").strip()
        title = name.replace("-", " ").title()
        shell_variants = {
            f"# {title}",
            f"# {title}\n",
        }
        if body and body not in shell_variants:
            return False
    return True


async def _llm_migrate(
    content: str,
    entity_store: EntityStore,
    provider: LLMProvider,
    model: str,
) -> bool:
    """Use LLM to split MEMORY.md into entity cards. Returns True on success."""
    import json
    from lemonclaw.utils.helpers import strip_fences

    card_names = ", ".join(DEFAULT_CARDS.keys())
    messages = [
        {"role": "system", "content": _MIGRATE_SYSTEM.format(card_names=card_names)},
        {"role": "user", "content": _MIGRATE_USER.format(content=content)},
    ]

    response = await asyncio.wait_for(
        provider.chat(messages=messages, model=model),
        timeout=30,
    )

    text = strip_fences(response.content or "")
    if not text:
        return False

    cards_data = json.loads(text)
    if not isinstance(cards_data, dict):
        return False

    created = 0
    for name, body in cards_data.items():
        if name not in DEFAULT_CARDS:
            continue
        info = DEFAULT_CARDS[name]
        if body and isinstance(body, str) and body.strip():
            entity_store.create_card(name, info["type"], info["keywords"], body=body.strip() + "\n")
            created += 1

    # Create remaining default cards that LLM didn't populate
    for name, info in DEFAULT_CARDS.items():
        if entity_store.get_card(name) is None:
            title = name.replace("-", " ").title()
            entity_store.create_card(name, info["type"], info["keywords"], body=f"# {title}\n\n")

    return created > 0


def _fallback_migrate(content: str, entity_store: EntityStore) -> None:
    """Fallback: init defaults and bucket content into the default cards."""
    sections = _bucket_memory_content(content)
    for name, info in DEFAULT_CARDS.items():
        title = name.replace("-", " ").title()
        lines = sections.get(name) or []
        if lines:
            body = f"# {title}\n\n" + "\n".join(lines).strip() + "\n"
        elif name == "preferences" and not _is_noise(content):
            body = f"# Preferences\n\n## Migrated from MEMORY.md\n\n{content}\n"
        else:
            body = f"# {title}\n\n"
        entity_store.create_card(name, info["type"], info["keywords"], body=body)


def _bucket_memory_content(content: str) -> dict[str, list[str]]:
    """Heuristically split flat MEMORY.md content across default entity cards."""
    sections: dict[str, list[str]] = {}
    current = "preferences"
    for raw_line in content.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("###") or stripped.startswith("##"):
            header = stripped.lstrip("#").strip().lower()
            if any(token in header for token in ("需求", "preference", "偏好")):
                current = "preferences"
            elif any(token in header for token in ("进展", "tracker", "项目", "milestone")):
                current = "project-tracker"
            elif any(token in header for token in ("步骤", "流程", "method")):
                current = "methodology"
            elif any(token in header for token in ("目标", "goal", "todo", "下一步")):
                current = "goals"
            elif any(token in header for token in ("决定", "decision", "权衡")):
                current = "decisions"
            elif any(token in header for token in ("问题", "issue", "bug")):
                current = "issues"
            elif any(token in header for token in ("技术", "stack", "框架", "版本")):
                current = "tech-stack"
            else:
                current = "preferences"
            if not _is_noise(stripped):
                sections.setdefault(current, []).append(stripped)
            continue

        normalized = re.sub(r"^\d+\.\s*", "- ", stripped)
        candidate = normalized if normalized.startswith("- ") else f"- {normalized}"
        if not _is_noise(candidate[2:] if candidate.startswith("- ") else candidate):
            sections.setdefault(current, []).append(candidate)
    return sections


def _is_noise(text: str) -> bool:
    normalized = str(text or "").strip()
    lowered = normalized.casefold()
    if not normalized:
        return True
    if lowered.startswith("# ") and lowered in {
        "# seed",
        "# preferences",
        "# user profile",
        "# project tracker",
        "# methodology",
        "# goals",
        "# decisions",
        "# issues",
        "# tech stack",
    }:
        return True
    if len(normalized) <= 6:
        return True
    return False
