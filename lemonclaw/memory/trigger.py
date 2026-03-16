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

    def _keyword_match(
        self,
        message: str,
        *,
        max_cards: int = 3,
        record_access: bool = True,
    ) -> list[EntityCard]:
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
            if record_access:
                card.record_access()
                card.save()
            results.append(card)
        return results

    def match(self, message: str, *, max_cards: int = 3) -> list[EntityCard]:
        """Return keyword-matched cards using the legacy sync fast path."""
        results = self._keyword_match(message, max_cards=max_cards, record_access=True)

        if results:
            logger.debug(
                "Memory trigger: {} cards matched for message ({})",
                len(results),
                ", ".join(c.name for c in results),
            )
        return results

    @staticmethod
    def _rule_key(rule: dict) -> str:
        return str(rule.get("header") or rule.get("trigger") or "")

    @staticmethod
    def _merge_source_label(existing: str, incoming: str) -> str:
        parts = [part for part in str(existing or "").split("+") if part]
        if incoming and incoming not in parts:
            parts.append(incoming)
        return "+".join(parts)

    @classmethod
    def merge_rule_matches(
        cls,
        *,
        preferred_rules: list[dict],
        preferred_source: str,
        secondary_rules: list[dict] | None = None,
        secondary_source: str = "",
        existing_sources: dict[str, str] | None = None,
        max_rules: int = 2,
    ) -> tuple[list[dict], dict[str, str]]:
        merged: list[dict] = []
        seen: set[str] = set()
        sources = dict(existing_sources or {})

        def _append(rule: dict, source: str) -> None:
            if len(merged) >= max_rules:
                return
            key = cls._rule_key(rule)
            if not key:
                return
            existing = str(sources.get(key) or "")
            sources[key] = cls._merge_source_label(existing, source) if existing else source
            if key in seen:
                return
            seen.add(key)
            merged.append(rule)

        for rule in preferred_rules:
            _append(rule, preferred_source)
        for rule in secondary_rules or []:
            _append(rule, secondary_source)

        return merged, sources

    async def hybrid_match(
        self,
        message: str,
        provider: LLMProvider,
        *,
        max_cards: int = 3,
        max_rules: int = 2,
    ) -> tuple[list[EntityCard], list[dict]]:
        cards, rules, _trace = await self.hybrid_match_with_trace(
            message,
            provider,
            max_cards=max_cards,
            max_rules=max_rules,
        )
        return cards, rules

    async def hybrid_match_with_trace(
        self,
        message: str,
        provider: LLMProvider,
        *,
        max_cards: int = 3,
        max_rules: int = 2,
        keyword_rules: list[dict] | None = None,
    ) -> tuple[list[EntityCard], list[dict], dict]:
        """Enhanced match using hybrid search (BM25 + vector).

        Returns (matched_cards, matched_rules, trace).
        Falls back to keyword match if search index is unavailable.
        """
        keyword_cards = self._keyword_match(message, max_cards=max_cards, record_access=False)
        trace = {
            "strategy": "keyword",
            "fallbacks": [],
            "card_sources": {card.name: "keyword" for card in keyword_cards},
            "rule_sources": {},
            "keyword_card_count": len(keyword_cards),
            "hybrid_card_count": 0,
            "hybrid_rule_count": 0,
        }

        if not self._search or not self._search.available:
            trace["fallbacks"].append("lancedb_unavailable")
            for card in keyword_cards:
                card.record_access()
                card.save()
            merged_rules, rule_sources = self.merge_rule_matches(
                preferred_rules=keyword_rules or [],
                preferred_source="keyword",
                max_rules=max_rules,
            )
            trace["rule_sources"] = rule_sources
            return keyword_cards, merged_rules, trace

        try:
            entity_results = await self._search.search_entities(
                message, provider, limit=max_cards
            )
            rule_results = await self._search.search_rules(
                message, provider, limit=max_rules
            )
        except Exception as e:
            logger.debug("Hybrid search failed, falling back to keyword: {}", e)
            trace["fallbacks"].append(f"search_error:{type(e).__name__}")
            for card in keyword_cards:
                card.record_access()
                card.save()
            merged_rules, rule_sources = self.merge_rule_matches(
                preferred_rules=keyword_rules or [],
                preferred_source="keyword",
                max_rules=max_rules,
            )
            trace["rule_sources"] = rule_sources
            return keyword_cards, merged_rules, trace

        trace["strategy"] = "hybrid"
        trace["hybrid_card_count"] = len(entity_results)
        trace["hybrid_rule_count"] = len(rule_results)

        # Preserve exact keyword hits first, then fill with hybrid semantic hits.
        cards: list[EntityCard] = []
        seen: set[str] = set()
        for card in keyword_cards:
            cards.append(card)
            seen.add(card.name)

        for result in entity_results:
            name = result.get("name", "")
            if name in seen:
                trace["card_sources"][name] = "hybrid+keyword"
                continue
            card = self._store.get_card(name)
            if not card:
                continue
            cards.append(card)
            seen.add(name)
            trace["card_sources"][name] = "hybrid"
            if len(cards) >= max_cards:
                break

        for card in cards:
            card.record_access()
            card.save()

        merged_rules, rule_sources = self.merge_rule_matches(
            preferred_rules=keyword_rules or [],
            preferred_source="keyword",
            secondary_rules=rule_results,
            secondary_source="hybrid",
            max_rules=max_rules,
        )
        trace["rule_sources"] = rule_sources

        return cards[:max_cards], merged_rules, trace

    @staticmethod
    def format_for_context(cards: list[EntityCard]) -> str:
        """Format matched cards as context block for injection into messages."""
        if not cards:
            return ""
        parts = ["## Relevant Memory (auto-loaded)"]
        for card in cards:
            parts.append(f"\n### {card.name}\n{card.body.strip()}")
        return "\n".join(parts)
