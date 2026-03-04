"""MEMORY.md → Entity Cards migration — one-time upgrade from flat to structured LTM."""

from __future__ import annotations

import asyncio
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
    # Already migrated — skip
    if entity_store.list_cards():
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
    """Fallback: init defaults and dump all content into preferences card."""
    for name, info in DEFAULT_CARDS.items():
        if name == "preferences":
            body = f"# Preferences\n\n## Migrated from MEMORY.md\n\n{content}\n"
            entity_store.create_card(name, info["type"], info["keywords"], body=body)
        else:
            title = name.replace("-", " ").title()
            entity_store.create_card(name, info["type"], info["keywords"], body=f"# {title}\n\n")
