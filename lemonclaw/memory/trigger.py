"""Keyword trigger + memory retrieval for context injection."""

from __future__ import annotations

from loguru import logger

from lemonclaw.memory.entities import EntityCard, EntityStore


class MemoryTrigger:
    """Scan user messages for keyword matches against LTM entity cards.

    Fast path: pure string matching on card keywords.
    Future: hybrid search (BM25 + vector) will be added in Step 3.
    """

    def __init__(self, entity_store: EntityStore):
        self._store = entity_store

    def match(self, message: str, *, max_cards: int = 3) -> list[EntityCard]:
        """Return entity cards whose keywords appear in the message.

        Cards are ranked by number of keyword hits, then by access_count.
        Each matched card gets its access_count incremented.
        """
        msg_lower = message.lower()
        scored: list[tuple[int, int, EntityCard]] = []

        for card in self._store.list_cards():
            hits = sum(1 for kw in card.keywords if kw.lower() in msg_lower)
            if hits > 0:
                scored.append((hits, card.access_count, card))

        # Sort: most keyword hits first, then highest access_count
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)

        results: list[EntityCard] = []
        for _, _, card in scored[:max_cards]:
            card.record_access()
            card.save()
            results.append(card)

        if results:
            logger.debug(
                "Memory trigger: {} cards matched for message ({})",
                len(results),
                ", ".join(c.name for c in results),
            )
        return results

    @staticmethod
    def format_for_context(cards: list[EntityCard]) -> str:
        """Format matched cards as context block for injection into messages."""
        if not cards:
            return ""
        parts = ["## Relevant Memory (auto-loaded)"]
        for card in cards:
            parts.append(f"\n### {card.name}\n{card.body.strip()}")
        return "\n".join(parts)
