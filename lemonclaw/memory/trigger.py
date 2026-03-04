"""Keyword trigger + hybrid search for memory context injection."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from lemonclaw.memory.entities import EntityCard, EntityStore

if TYPE_CHECKING:
    from lemonclaw.memory.search import MemorySearchIndex
    from lemonclaw.providers.base import LLMProvider


class MemoryTrigger:
    """Scan user messages for keyword matches against LTM entity cards.

    Fast path: pure string matching on card keywords (always available).
    Enhanced path: hybrid search via lancedb BM25 + vector (when available).
    """

    def __init__(self, entity_store: EntityStore, search_index: MemorySearchIndex | None = None):
        self._store = entity_store
        self._search = search_index

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

    async def hybrid_match(
        self,
        message: str,
        provider: LLMProvider,
        *,
        max_cards: int = 3,
        max_rules: int = 2,
    ) -> tuple[list[EntityCard], list[dict]]:
        """Enhanced match using hybrid search (BM25 + vector).

        Returns (matched_cards, matched_rules).
        Falls back to keyword match if search index is unavailable.
        """
        if not self._search or not self._search.available:
            return self.match(message, max_cards=max_cards), []

        try:
            entity_results = await self._search.search_entities(
                message, provider, limit=max_cards
            )
            rule_results = await self._search.search_rules(
                message, provider, limit=max_rules
            )
        except Exception as e:
            logger.debug("Hybrid search failed, falling back to keyword: {}", e)
            return self.match(message, max_cards=max_cards), []

        # Load actual EntityCard objects for matched entities
        cards: list[EntityCard] = []
        seen: set[str] = set()
        for result in entity_results:
            name = result.get("name", "")
            if name in seen:
                continue
            card = self._store.get_card(name)
            if card:
                card.record_access()
                card.save()
                cards.append(card)
                seen.add(name)

        # Supplement with keyword matches if hybrid returned few results
        if len(cards) < max_cards:
            kw_cards = self.match(message, max_cards=max_cards - len(cards))
            for card in kw_cards:
                if card.name not in seen:
                    cards.append(card)
                    seen.add(card.name)

        return cards[:max_cards], rule_results

    @staticmethod
    def format_for_context(cards: list[EntityCard]) -> str:
        """Format matched cards as context block for injection into messages."""
        if not cards:
            return ""
        parts = ["## Relevant Memory (auto-loaded)"]
        for card in cards:
            parts.append(f"\n### {card.name}\n{card.body.strip()}")
        return "\n".join(parts)
