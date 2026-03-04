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
        result = asyncio.get_event_loop().run_until_complete(
            idx.rebuild(AsyncMock())
        )
        assert result == 0

        results = asyncio.get_event_loop().run_until_complete(
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
    cards, rules = asyncio.get_event_loop().run_until_complete(
        trigger.hybrid_match("python version?", AsyncMock())
    )
    assert len(cards) == 1
    assert cards[0].name == "tech"
    assert rules == []


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
