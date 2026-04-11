from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from lemonclaw.config.watcher import ConfigWatcher


class _FakeProvider:
    def __init__(self, api_key: str, api_base: str | None):
        self.api_key = api_key
        self.api_base = api_base
        self.calls: list[tuple[str, str | None]] = []

    def update_credentials(self, api_key: str, api_base: str | None = None) -> None:
        self.calls.append((api_key, api_base))
        self.api_key = api_key
        self.api_base = api_base


class _FakeConfig:
    def __init__(self, *, api_key: str, api_base: str | None):
        self.agents = SimpleNamespace(defaults=SimpleNamespace(model="test-model"))
        self._provider = SimpleNamespace(api_key=api_key)
        self._api_base = api_base

    def get_provider(self, _model: str):
        return self._provider

    def get_api_base(self, _model: str):
        return self._api_base


def test_reload_provider_clears_stale_api_key_when_removed() -> None:
    provider = _FakeProvider(api_key="old-key", api_base="https://old.example")
    watcher = ConfigWatcher(Path("config.json"), provider)

    watcher._reload_provider(_FakeConfig(api_key="", api_base="https://new.example"))

    assert provider.calls == [("", "https://new.example")]
    assert provider.api_key == ""
    assert provider.api_base == "https://new.example"


def test_reload_provider_skips_when_credentials_unchanged() -> None:
    provider = _FakeProvider(api_key="same-key", api_base="https://same.example")
    watcher = ConfigWatcher(Path("config.json"), provider)

    watcher._reload_provider(_FakeConfig(api_key="same-key", api_base="https://same.example"))

    assert provider.calls == []
