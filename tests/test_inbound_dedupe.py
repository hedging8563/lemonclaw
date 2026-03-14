from __future__ import annotations

import importlib


def test_remember_returns_false_for_duplicate_within_ttl() -> None:
    mod = importlib.import_module("lemonclaw.channels.inbound_dedupe")
    cache = mod.InboundDedupeCache(ttl_seconds=300, max_entries=10)

    assert cache.remember("telegram:update:1") is True
    assert cache.remember("telegram:update:1") is False


def test_remember_allows_key_again_after_ttl(monkeypatch) -> None:
    mod = importlib.import_module("lemonclaw.channels.inbound_dedupe")
    now = 1000.0
    monkeypatch.setattr(mod.time, "monotonic", lambda: now)
    cache = mod.InboundDedupeCache(ttl_seconds=10, max_entries=10)

    assert cache.remember("feishu:message:1") is True
    monkeypatch.setattr(mod.time, "monotonic", lambda: now + 11)
    assert cache.remember("feishu:message:1") is True


def test_remember_evicts_oldest_when_max_entries_exceeded() -> None:
    cache = importlib.import_module("lemonclaw.channels.inbound_dedupe").InboundDedupeCache(
        ttl_seconds=300,
        max_entries=2,
    )

    assert cache.remember("a") is True
    assert cache.remember("b") is True
    assert cache.remember("c") is True
    assert cache.remember("a") is True


def test_remember_allows_empty_key() -> None:
    cache = importlib.import_module("lemonclaw.channels.inbound_dedupe").InboundDedupeCache()

    assert cache.remember("") is True
    assert cache.remember("") is True
