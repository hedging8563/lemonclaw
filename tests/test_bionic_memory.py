"""Tests for bionic memory system — P3-D Step 1."""

from datetime import date

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
    from lemonclaw.memory.entities import DEFAULT_CARDS, EntityStore

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


# ── Procedural Memory ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_procedural_add_and_list(tmp_path):
    from lemonclaw.memory.reflect import ProceduralMemory

    pm = ProceduralMemory(tmp_path / "memory")
    assert pm.list_rules() == []

    rid = await pm.add_rule("MiniMax 路由", "原生格式是 Anthropic", "用 anthropic provider", "P2-D 踩坑")
    assert rid == 1
    rules = pm.list_rules()
    assert len(rules) == 1
    assert rules[0]["trigger"] == "MiniMax 路由"
    assert rules[0]["lesson"] == "原生格式是 Anthropic"

    rid2 = await pm.add_rule("Fastify body", "空 body 禁令", "检查一致性", "API 502")
    assert rid2 == 2
    assert len(pm.list_rules()) == 2


@pytest.mark.asyncio
async def test_procedural_match_rules(tmp_path):
    from lemonclaw.memory.reflect import ProceduralMemory

    pm = ProceduralMemory(tmp_path / "memory")
    await pm.add_rule("MiniMax 模型路由", "原生格式是 Anthropic", "用 anthropic provider", "P2-D")
    await pm.add_rule("Fastify 空 body", "禁止空 body", "检查一致性", "API")
    await pm.add_rule("K8s 部署", "Recreate 策略", "不用 RollingUpdate", "Claw")

    # Match MiniMax
    matched = pm.match_rules("MiniMax 模型怎么路由")
    assert len(matched) == 1
    assert matched[0]["trigger"] == "MiniMax 模型路由"

    # No match
    assert pm.match_rules("hello world") == []


@pytest.mark.asyncio
async def test_procedural_format_for_context(tmp_path):
    from lemonclaw.memory.reflect import ProceduralMemory

    pm = ProceduralMemory(tmp_path / "memory")
    await pm.add_rule("test trigger", "test lesson", "test action", "test source")

    rules = pm.match_rules("test trigger")
    text = ProceduralMemory.format_for_context(rules)
    assert "Experience Rules" in text
    assert "test lesson" in text

    assert ProceduralMemory.format_for_context([]) == ""


def test_procedural_reflect_fallback(tmp_path):
    """Test reflect fallback when LLM is unavailable — returns None, no low-quality rule."""
    import asyncio
    from unittest.mock import AsyncMock

    from lemonclaw.memory.reflect import ProceduralMemory

    pm = ProceduralMemory(tmp_path / "memory")
    mock_provider = AsyncMock()
    mock_provider.chat.side_effect = Exception("LLM unavailable")

    rid = asyncio.get_event_loop().run_until_complete(
        pm.reflect(mock_provider, "deploy to K8s", "pod crash loop", model="test")
    )
    assert rid is None
    assert pm.list_rules() == []


def test_memory_store_has_procedural(tmp_path):
    from lemonclaw.agent.memory import MemoryStore

    store = MemoryStore(tmp_path)
    assert store.procedural is not None


@pytest.mark.asyncio
async def test_context_builder_injects_matched_rules(tmp_path):
    from lemonclaw.agent.context import ContextBuilder

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "memory").mkdir()

    ctx = ContextBuilder(workspace)
    await ctx.memory.procedural.add_rule("python 部署", "需要 venv", "先创建 venv", "部署踩坑")

    messages = ctx.build_messages(
        history=[],
        current_message="python 部署到服务器",
        channel="cli",
        chat_id="test",
    )
    user_msg = messages[-1]["content"]
    assert "Experience Rules" in user_msg
    assert "需要 venv" in user_msg


# ── Core Promotion / Demotion ────────────────────────────────────────────────


def test_core_promoter_add_and_remove(tmp_path):
    from lemonclaw.memory.entities import EntityStore
    from lemonclaw.memory.promote import CorePromoter

    store = EntityStore(tmp_path / "memory")
    promoter = CorePromoter(tmp_path / "memory", store)

    assert promoter.read_core() == ""
    assert promoter.add_to_core("- User prefers Chinese")
    assert "User prefers Chinese" in promoter.read_core()

    assert promoter.remove_from_core("Chinese")
    assert "Chinese" not in promoter.read_core()

    assert not promoter.remove_from_core("nonexistent")


def test_core_promoter_size_limit(tmp_path):
    from lemonclaw.memory.entities import EntityStore
    from lemonclaw.memory.promote import CORE_MAX_CHARS, CorePromoter

    store = EntityStore(tmp_path / "memory")
    promoter = CorePromoter(tmp_path / "memory", store)

    # Fill core to near limit
    promoter.write_core("x" * (CORE_MAX_CHARS - 10))
    assert not promoter.add_to_core("This is way too long to fit")


def test_core_promoter_run_promotion(tmp_path):
    from lemonclaw.memory.entities import EntityStore
    from lemonclaw.memory.promote import PROMOTE_ACCESS_THRESHOLD, CorePromoter

    store = EntityStore(tmp_path / "memory")
    card = store.create_card("tech", "tech", ["python"], body="# Tech\nPython 3.13\n")
    # Simulate high access
    card.meta["access_count"] = PROMOTE_ACCESS_THRESHOLD
    card.save()

    promoter = CorePromoter(tmp_path / "memory", store)
    promoted = promoter.run_promotion()
    assert "tech" in promoted
    assert "Python 3.13" in promoter.read_core()

    # Access count should be reset
    store.invalidate_cache()
    assert store.get_card("tech").access_count == 0


def test_core_promoter_run_promotion_below_threshold(tmp_path):
    from lemonclaw.memory.entities import EntityStore
    from lemonclaw.memory.promote import CorePromoter

    store = EntityStore(tmp_path / "memory")
    store.create_card("tech", "tech", ["python"], body="# Tech\nPython 3.13\n")

    promoter = CorePromoter(tmp_path / "memory", store)
    promoted = promoter.run_promotion()
    assert promoted == []


def test_core_promoter_run_demotion(tmp_path):
    from lemonclaw.memory.entities import EntityStore
    from lemonclaw.memory.promote import CorePromoter

    store = EntityStore(tmp_path / "memory")
    card = store.create_card("old-card", "test", ["old"], body="# Old\nStale info\n")
    # Set last_accessed to 60 days ago
    card.meta["last_accessed"] = "2026-01-01"
    card.save()

    promoter = CorePromoter(tmp_path / "memory", store)
    promoter.write_core("- [old-card] Stale info\n- Some other fact\n")

    demoted = promoter.run_demotion()
    assert len(demoted) == 1
    assert "old-card" in demoted[0]
    # Non-card lines should remain
    assert "Some other fact" in promoter.read_core()


def test_core_promoter_no_demotion_recent(tmp_path):
    from datetime import date

    from lemonclaw.memory.entities import EntityStore
    from lemonclaw.memory.promote import CorePromoter

    store = EntityStore(tmp_path / "memory")
    card = store.create_card("active", "test", ["active"], body="# Active\n")
    card.meta["last_accessed"] = str(date.today())
    card.save()

    promoter = CorePromoter(tmp_path / "memory", store)
    promoter.write_core("- [active] Recent info\n")

    demoted = promoter.run_demotion()
    assert demoted == []


# ── MEMORY.md Migration ──────────────────────────────────────────────────────


def test_migrate_no_memory_file(tmp_path):
    """No MEMORY.md → just init defaults."""
    import asyncio

    from lemonclaw.memory.entities import DEFAULT_CARDS, EntityStore
    from lemonclaw.memory.migrate import migrate_memory_to_entities

    store = EntityStore(tmp_path / "memory")
    result = asyncio.get_event_loop().run_until_complete(
        migrate_memory_to_entities(tmp_path / "memory", store)
    )
    assert result is True
    assert len(store.list_cards()) == len(DEFAULT_CARDS)


def test_migrate_empty_memory_file(tmp_path):
    """Empty MEMORY.md → init defaults."""
    import asyncio

    from lemonclaw.memory.entities import DEFAULT_CARDS, EntityStore
    from lemonclaw.memory.migrate import migrate_memory_to_entities

    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "MEMORY.md").write_text("", encoding="utf-8")

    store = EntityStore(memory_dir)
    result = asyncio.get_event_loop().run_until_complete(
        migrate_memory_to_entities(memory_dir, store)
    )
    assert result is True
    assert len(store.list_cards()) == len(DEFAULT_CARDS)


def test_migrate_fallback_no_llm(tmp_path):
    """MEMORY.md with content but no LLM → fallback to preferences card."""
    import asyncio

    from lemonclaw.memory.entities import DEFAULT_CARDS, EntityStore
    from lemonclaw.memory.migrate import migrate_memory_to_entities

    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "MEMORY.md").write_text(
        "# User Facts\n- Prefers Chinese\n- Uses Python 3.13\n", encoding="utf-8"
    )

    store = EntityStore(memory_dir)
    result = asyncio.get_event_loop().run_until_complete(
        migrate_memory_to_entities(memory_dir, store)
    )
    assert result is True
    assert len(store.list_cards()) == len(DEFAULT_CARDS)
    prefs = store.get_card("preferences")
    assert prefs is not None
    assert "Prefers Chinese" in prefs.body
    assert "Python 3.13" in prefs.body


def test_migrate_fallback_llm_fails(tmp_path):
    """LLM available but fails → fallback to preferences card."""
    import asyncio
    from unittest.mock import AsyncMock

    from lemonclaw.memory.entities import EntityStore
    from lemonclaw.memory.migrate import migrate_memory_to_entities

    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "MEMORY.md").write_text("# Facts\n- Test data\n", encoding="utf-8")

    mock_provider = AsyncMock()
    mock_provider.chat.side_effect = Exception("LLM down")

    store = EntityStore(memory_dir)
    result = asyncio.get_event_loop().run_until_complete(
        migrate_memory_to_entities(memory_dir, store, provider=mock_provider, model="test")
    )
    assert result is True
    prefs = store.get_card("preferences")
    assert "Test data" in prefs.body


def test_migrate_idempotent(tmp_path):
    """Already migrated → skip."""
    import asyncio

    from lemonclaw.memory.entities import EntityStore
    from lemonclaw.memory.migrate import migrate_memory_to_entities

    memory_dir = tmp_path / "memory"
    store = EntityStore(memory_dir)
    store.create_card("existing", "test", ["test"], body="# Existing\n")

    result = asyncio.get_event_loop().run_until_complete(
        migrate_memory_to_entities(memory_dir, store)
    )
    assert result is False  # No migration needed
    assert len(store.list_cards()) == 1  # Only the existing card


# ── ContextBuilder integration ───────────────────────────────────────────────


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


# ── Memory Cron ──────────────────────────────────────────────────────────────


def test_memory_cron_daily_archive(tmp_path):
    import asyncio

    from lemonclaw.memory.cron import EVENT_DAILY_ARCHIVE, run_memory_event

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    memory_dir = workspace / "memory"
    memory_dir.mkdir()

    # Write some today.md content
    (memory_dir / "today.md").write_text("# 2020-01-01\n\n## 10:00 — Test\n- Detail\n", encoding="utf-8")

    result = asyncio.get_event_loop().run_until_complete(
        run_memory_event(EVENT_DAILY_ARCHIVE, workspace)
    )
    assert "Archived" in result
    assert (memory_dir / "HISTORY.md").exists()
    assert "Test" in (memory_dir / "HISTORY.md").read_text(encoding="utf-8")


def test_memory_cron_daily_archive_empty(tmp_path):
    import asyncio

    from lemonclaw.memory.cron import EVENT_DAILY_ARCHIVE, run_memory_event

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = asyncio.get_event_loop().run_until_complete(
        run_memory_event(EVENT_DAILY_ARCHIVE, workspace)
    )
    assert "Nothing" in result


def test_memory_cron_weekly_promote(tmp_path):
    import asyncio

    from lemonclaw.memory.cron import EVENT_WEEKLY_PROMOTE, run_memory_event
    from lemonclaw.memory.promote import PROMOTE_ACCESS_THRESHOLD

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    memory_dir = workspace / "memory"
    memory_dir.mkdir()

    # Create a high-access card
    from lemonclaw.memory.entities import EntityStore
    store = EntityStore(memory_dir)
    card = store.create_card("tech", "tech", ["python"], body="# Tech\nPython 3.13\n")
    card.meta["access_count"] = PROMOTE_ACCESS_THRESHOLD
    card.save()

    result = asyncio.get_event_loop().run_until_complete(
        run_memory_event(EVENT_WEEKLY_PROMOTE, workspace)
    )
    assert "Promoted 1" in result


def test_memory_cron_monthly_cleanup(tmp_path):
    import asyncio

    from lemonclaw.memory.cron import EVENT_MONTHLY_CLEANUP, run_memory_event

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = asyncio.get_event_loop().run_until_complete(
        run_memory_event(EVENT_MONTHLY_CLEANUP, workspace)
    )
    assert "truncated" in result.lower() or "cleared" in result.lower()


def test_memory_cron_register_jobs(tmp_path):
    from lemonclaw.cron.service import CronService
    from lemonclaw.memory.cron import register_memory_jobs

    cron = CronService(tmp_path / "cron" / "jobs.json")
    added = register_memory_jobs(cron)
    assert added == 3

    jobs = cron.list_jobs(include_disabled=True)
    names = {j.name for j in jobs}
    assert "memory:daily_archive" in names
    assert "memory:weekly_promote" in names
    assert "memory:monthly_cleanup" in names

    # Idempotent — second call adds nothing
    added2 = register_memory_jobs(cron)
    assert added2 == 0


def test_memory_cron_is_memory_event():
    from lemonclaw.memory.cron import is_memory_event

    assert is_memory_event("memory:daily_archive")
    assert is_memory_event("memory:weekly_promote")
    assert is_memory_event("memory:monthly_cleanup")
    assert not is_memory_event("some:other:event")
    assert not is_memory_event("")


def test_memory_store_auto_initializes_default_entities(tmp_path):
    from lemonclaw.agent.memory import MemoryStore
    from lemonclaw.memory.entities import DEFAULT_CARDS

    store = MemoryStore(tmp_path)
    assert len(store.entities.list_cards()) == len(DEFAULT_CARDS)


def test_entity_store_init_defaults_backfills_missing_defaults(tmp_path):
    from lemonclaw.memory.entities import DEFAULT_CARDS, EntityStore

    store = EntityStore(tmp_path / "memory")
    store.create_card("user-profile", "person", ["用户"], body="# Existing\n")

    created = store.init_defaults()

    assert created == len(DEFAULT_CARDS) - 1
    names = {card.name for card in store.list_cards()}
    assert set(DEFAULT_CARDS) <= names

