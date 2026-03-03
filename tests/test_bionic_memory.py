"""Tests for bionic memory system — P3-D Step 1."""

from datetime import date
from pathlib import Path

import pytest


# ── Entity Cards ─────────────────────────────────────────────────────────────


def test_parse_frontmatter():
    from lemonclaw.memory.entities import _parse_frontmatter

    text = """---
type: person
keywords: [用户, 偏好]
access_count: 5
last_accessed: 2026-03-04
---
# User Profile
- Language: Chinese
"""
    meta, body = _parse_frontmatter(text)
    assert meta["type"] == "person"
    assert meta["keywords"] == ["用户", "偏好"]
    assert meta["access_count"] == 5
    assert "# User Profile" in body


def test_parse_frontmatter_no_frontmatter():
    from lemonclaw.memory.entities import _parse_frontmatter

    text = "# Just markdown\nNo frontmatter here."
    meta, body = _parse_frontmatter(text)
    assert meta == {}
    assert body == text


def test_render_frontmatter():
    from lemonclaw.memory.entities import _render_frontmatter

    meta = {"type": "tech", "keywords": ["python", "rust"], "access_count": 3}
    result = _render_frontmatter(meta)
    assert result.startswith("---\n")
    assert result.endswith("---\n")
    assert "type: tech" in result
    assert "keywords: [python, rust]" in result
    assert "access_count: 3" in result


def test_entity_card_load_save(tmp_path):
    from lemonclaw.memory.entities import EntityCard, _render_frontmatter

    card_path = tmp_path / "test-card.md"
    meta = {"type": "test", "keywords": ["a", "b"], "access_count": 0}
    card_path.write_text(_render_frontmatter(meta) + "# Test\nBody content\n", encoding="utf-8")

    card = EntityCard.load(card_path)
    assert card.name == "test-card"
    assert card.keywords == ["a", "b"]
    assert card.access_count == 0
    assert "Body content" in card.body

    card.record_access()
    assert card.access_count == 1
    assert card.meta["last_accessed"] == str(date.today())

    card.save()
    reloaded = EntityCard.load(card_path)
    assert reloaded.access_count == 1


def test_entity_store_crud(tmp_path):
    from lemonclaw.memory.entities import EntityStore

    store = EntityStore(tmp_path / "memory")
    assert store.list_cards() == []

    card = store.create_card("my-card", "test", ["hello", "world"], body="# My Card\n")
    assert card.name == "my-card"
    assert (tmp_path / "memory" / "entities" / "my-card.md").exists()

    assert len(store.list_cards()) == 1
    assert store.get_card("my-card") is not None
    assert store.get_card("nonexistent") is None

    store.update_card("my-card", "# Updated\nNew body\n")
    reloaded = store.get_card("my-card")
    assert "New body" in reloaded.body


def test_entity_store_init_defaults(tmp_path):
    from lemonclaw.memory.entities import EntityStore, DEFAULT_CARDS

    store = EntityStore(tmp_path / "memory")
    created = store.init_defaults()
    assert created == len(DEFAULT_CARDS)
    assert len(store.list_cards()) == len(DEFAULT_CARDS)

    # Second call should be no-op
    created2 = store.init_defaults()
    assert created2 == 0


# ── Keyword Trigger ──────────────────────────────────────────────────────────


def test_trigger_match(tmp_path):
    from lemonclaw.memory.entities import EntityStore
    from lemonclaw.memory.trigger import MemoryTrigger

    store = EntityStore(tmp_path / "memory")
    store.create_card("tech", "tech", ["python", "rust", "版本"], body="# Tech\n")
    store.create_card("goals", "goal", ["目标", "计划"], body="# Goals\n")
    store.create_card("issues", "issue", ["bug", "问题"], body="# Issues\n")

    trigger = MemoryTrigger(store)

    # Match tech card
    results = trigger.match("What python version are we using?")
    assert len(results) == 1
    assert results[0].name == "tech"
    assert results[0].access_count == 1

    # Match multiple cards
    results = trigger.match("python有个bug需要修复")
    assert len(results) == 2
    names = {c.name for c in results}
    assert "tech" in names
    assert "issues" in names

    # No match
    results = trigger.match("hello world")
    assert len(results) == 0


def test_trigger_max_cards(tmp_path):
    from lemonclaw.memory.entities import EntityStore
    from lemonclaw.memory.trigger import MemoryTrigger

    store = EntityStore(tmp_path / "memory")
    for i in range(5):
        store.create_card(f"card-{i}", "test", ["共同关键词"], body=f"# Card {i}\n")

    trigger = MemoryTrigger(store)
    results = trigger.match("共同关键词测试", max_cards=2)
    assert len(results) == 2


def test_trigger_format_for_context(tmp_path):
    from lemonclaw.memory.entities import EntityStore
    from lemonclaw.memory.trigger import MemoryTrigger

    store = EntityStore(tmp_path / "memory")
    store.create_card("tech", "tech", ["python"], body="# Tech\nPython 3.13\n")

    trigger = MemoryTrigger(store)
    cards = trigger.match("python")
    text = MemoryTrigger.format_for_context(cards)
    assert "Relevant Memory" in text
    assert "Python 3.13" in text

    # Empty cards
    assert MemoryTrigger.format_for_context([]) == ""


# ── Today.md ─────────────────────────────────────────────────────────────────


def test_today_log_read_write(tmp_path):
    from lemonclaw.memory.today import TodayLog

    log = TodayLog(tmp_path / "memory")
    assert log.read() == ""

    log.append("Fixed billing bug", ["Used advisory lock", "Tests passed"])
    content = log.read()
    assert f"# {date.today()}" in content
    assert "Fixed billing bug" in content
    assert "Used advisory lock" in content


def test_today_log_stale_file(tmp_path):
    from lemonclaw.memory.today import TodayLog

    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    today_file = memory_dir / "today.md"
    today_file.write_text("# 2020-01-01\n\n## 10:00 — Old entry\n", encoding="utf-8")

    log = TodayLog(memory_dir)
    assert log.read() == ""  # Stale, returns empty


def test_today_log_archive(tmp_path):
    from lemonclaw.memory.today import TodayLog

    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    history_file = memory_dir / "HISTORY.md"

    log = TodayLog(memory_dir)
    log.append("Test entry", ["Detail 1"])

    assert log.archive_to_history(history_file)
    assert history_file.exists()
    assert "Test entry" in history_file.read_text(encoding="utf-8")

    # After archive, today.md should be fresh
    content = log.read()
    assert "Test entry" not in content


def test_today_log_archive_empty(tmp_path):
    from lemonclaw.memory.today import TodayLog

    log = TodayLog(tmp_path / "memory")
    assert not log.archive_to_history(tmp_path / "memory" / "HISTORY.md")


# ── MemoryStore integration ──────────────────────────────────────────────────


def test_memory_store_has_bionic_layers(tmp_path):
    from lemonclaw.agent.memory import MemoryStore

    store = MemoryStore(tmp_path)
    assert store.entities is not None
    assert store.today is not None
    assert store.trigger is not None


def test_memory_store_core(tmp_path):
    from lemonclaw.agent.memory import MemoryStore

    store = MemoryStore(tmp_path)
    assert store.read_core() == ""

    store.write_core("# Core Facts\n- User prefers Chinese\n")
    assert "User prefers Chinese" in store.read_core()


# ── ContextBuilder integration ───────────────────────────────────────────────


def test_context_builder_injects_core_and_today(tmp_path):
    from lemonclaw.agent.context import ContextBuilder

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "memory").mkdir()

    ctx = ContextBuilder(workspace)
    ctx.memory.write_core("# Core\n- Always use Chinese\n")
    ctx.memory.today.append("Fixed a bug", ["Detail"])

    prompt = ctx.build_system_prompt()
    assert "Core Memory" in prompt
    assert "Always use Chinese" in prompt
    assert "Today" in prompt
    assert "Fixed a bug" in prompt


def test_context_builder_injects_matched_cards(tmp_path):
    from lemonclaw.agent.context import ContextBuilder

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "memory").mkdir()

    ctx = ContextBuilder(workspace)
    ctx.memory.entities.create_card("tech", "tech", ["python"], body="# Tech\nPython 3.13\n")

    messages = ctx.build_messages(
        history=[],
        current_message="What python version?",
        channel="cli",
        chat_id="test",
    )
    # User message should contain matched card content
    user_msg = messages[-1]["content"]
    assert "Relevant Memory" in user_msg
    assert "Python 3.13" in user_msg


def test_context_builder_no_match_no_injection(tmp_path):
    from lemonclaw.agent.context import ContextBuilder

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "memory").mkdir()

    ctx = ContextBuilder(workspace)
    ctx.memory.entities.create_card("tech", "tech", ["python"], body="# Tech\n")

    messages = ctx.build_messages(
        history=[],
        current_message="Hello world",
        channel="cli",
        chat_id="test",
    )
    user_msg = messages[-1]["content"]
    assert "Relevant Memory" not in user_msg
