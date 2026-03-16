"""Tests for memory search index (lancedb hybrid search)."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest


def test_search_index_available_check(tmp_path):
    """MemorySearchIndex.available reflects lancedb import status."""
    from lemonclaw.memory.search import MemorySearchIndex

    idx = MemorySearchIndex(tmp_path / "memory")
    # available depends on whether lancedb is installed
    assert isinstance(idx.available, bool)


def test_search_index_graceful_when_unavailable(tmp_path):
    """Search returns empty when lancedb is not installed."""
    from lemonclaw.memory.search import MemorySearchIndex

    idx = MemorySearchIndex(tmp_path / "memory")

    with patch("lemonclaw.memory.search._lancedb_available", return_value=False):
        result = asyncio.run(
            idx.rebuild(AsyncMock())
        )
        assert result == 0

        results = asyncio.run(
            idx.search("test", AsyncMock())
        )
        assert results == []


def test_trigger_hybrid_fallback_to_keyword(tmp_path):
    """hybrid_match falls back to keyword match when search index unavailable."""
    from lemonclaw.memory.entities import EntityStore
    from lemonclaw.memory.trigger import MemoryTrigger

    store = EntityStore(tmp_path / "memory")
    store.create_card("tech", "tech", ["python"], body="# Tech\nPython 3.13\n")

    # No search index
    trigger = MemoryTrigger(store, search_index=None)
    cards, rules = asyncio.run(
        trigger.hybrid_match("python version?", AsyncMock())
    )
    assert len(cards) == 1
    assert cards[0].name == "tech"
    assert rules == []


def test_trigger_hybrid_trace_preserves_keyword_hits(tmp_path):
    """Exact keyword hits should survive even when hybrid results return other cards."""
    from lemonclaw.memory.entities import EntityStore
    from lemonclaw.memory.trigger import MemoryTrigger

    class _FakeSearch:
        available = True

        async def search_entities(self, query, provider, limit=3):
            return [{"name": "semantic"}]

        async def search_rules(self, query, provider, limit=2):
            return []

    store = EntityStore(tmp_path / "memory")
    store.create_card("tech", "tech", ["python"], body="# Tech\nPython 3.13\n")
    store.create_card("semantic", "semantic", ["llm"], body="# Semantic\nPy runtime\n")

    trigger = MemoryTrigger(store, search_index=_FakeSearch())
    cards, rules, trace = asyncio.run(
        trigger.hybrid_match_with_trace("python version?", AsyncMock())
    )

    assert rules == []
    assert [card.name for card in cards] == ["tech", "semantic"]
    assert trace["strategy"] == "hybrid"
    assert trace["card_sources"]["tech"] == "keyword"
    assert trace["card_sources"]["semantic"] == "hybrid"


def test_merge_rule_matches_dedupes_and_preserves_existing_sources():
    from lemonclaw.memory.trigger import MemoryTrigger

    keyword_rule = {"header": "## Rule #1", "trigger": "python 部署", "lesson": "需要 venv"}
    hybrid_rule = {"header": "## Rule #2", "trigger": "部署回滚", "lesson": "先确认版本"}

    merged, sources = MemoryTrigger.merge_rule_matches(
        preferred_rules=[keyword_rule],
        preferred_source="keyword",
        secondary_rules=[keyword_rule, hybrid_rule],
        secondary_source="hybrid",
        existing_sources={"## Rule #1": "hybrid"},
        max_rules=2,
    )

    assert merged == [keyword_rule, hybrid_rule]
    assert sources["## Rule #1"] == "hybrid+keyword"
    assert sources["## Rule #2"] == "hybrid"


def test_trigger_keyword_match_still_works(tmp_path):
    """Existing keyword match API unchanged after trigger.py update."""
    from lemonclaw.memory.entities import EntityStore
    from lemonclaw.memory.trigger import MemoryTrigger

    store = EntityStore(tmp_path / "memory")
    store.create_card("tech", "tech", ["python", "rust"], body="# Tech\n")
    store.create_card("goals", "goal", ["目标"], body="# Goals\n")

    trigger = MemoryTrigger(store)
    results = trigger.match("python version")
    assert len(results) == 1
    assert results[0].name == "tech"

    results = trigger.match("hello world")
    assert len(results) == 0


def test_memory_store_has_search_index(tmp_path):
    """MemoryStore exposes search_index attribute."""
    from lemonclaw.agent.memory import MemoryStore

    store = MemoryStore(tmp_path)
    assert store.search_index is not None
    assert store.trigger._search is store.search_index


def test_search_index_status_tracks_unavailable_state(tmp_path):
    from lemonclaw.memory.search import MemorySearchIndex

    idx = MemorySearchIndex(tmp_path / "memory")
    with patch("lemonclaw.memory.search._lancedb_available", return_value=False):
        result = asyncio.run(idx.search("test", AsyncMock()))
        status = idx.status()

    assert result == []
    assert status["available"] is False
    assert status["last_operation"] == "search"
    assert status["last_error"] == "lancedb_unavailable"


def test_memory_store_entity_write_records_provider_unbound_status(tmp_path):
    from lemonclaw.agent.memory import MemoryStore

    store = MemoryStore(tmp_path)
    with patch("lemonclaw.memory.search._lancedb_available", return_value=True):
        store._on_entity_write("tech", "# Tech")
        status = store.search_index.status()

    assert status["last_operation"] == "upsert_entity"
    assert status["last_error"] == "provider_unbound"
