import asyncio
from types import SimpleNamespace

import pytest

from lemonclaw.bus.queue import MessageBus
from lemonclaw.channels.manager import ChannelManager
from lemonclaw.config.schema import Config


class _FakeChannel:
    def __init__(self) -> None:
        self._running = False
        self.start_calls = 0
        self.stop_calls = 0
        self.auto_pairing_enabled = False
        self._stop_event = asyncio.Event()

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        self.start_calls += 1
        self._running = True
        self._stop_event = asyncio.Event()
        await self._stop_event.wait()
        self._running = False

    async def stop(self) -> None:
        self.stop_calls += 1
        self._running = False
        self._stop_event.set()

    async def send(self, msg) -> None:
        return None

    def enable_auto_pairing(self, data_dir) -> None:
        self.auto_pairing_enabled = True


@pytest.mark.asyncio
async def test_channel_manager_restart_channel_restarts_task():
    manager = ChannelManager(Config(), MessageBus())
    fake = _FakeChannel()
    manager.channels["telegram"] = fake
    first_task = manager._spawn_channel_task("telegram", fake)
    await asyncio.sleep(0.05)

    result = await manager.restart_channel("telegram")
    await asyncio.sleep(0.05)

    assert result["channel"] == "telegram"
    assert result["running"] is True
    assert result["restart_count"] == 1
    assert result["restart_fail_count"] == 0
    assert fake.start_calls == 2
    assert fake.stop_calls == 1
    assert manager._channel_tasks["telegram"] is not first_task
    assert manager.get_status()["telegram"]["restart_count"] == 1

    await fake.stop()
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_channel_manager_restart_channel_is_serialized():
    manager = ChannelManager(Config(), MessageBus())
    fake = _FakeChannel()
    manager.channels["telegram"] = fake
    manager._spawn_channel_task("telegram", fake)
    await asyncio.sleep(0.05)

    first = asyncio.create_task(manager.restart_channel("telegram"))
    second = asyncio.create_task(manager.restart_channel("telegram"))
    first_result, second_result = await asyncio.gather(first, second)

    assert first_result["channel"] == "telegram"
    assert second_result["channel"] == "telegram"
    assert fake.start_calls == 3
    await fake.stop()
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_channel_manager_restart_records_reason_and_history():
    manager = ChannelManager(Config(), MessageBus())
    fake = _FakeChannel()
    manager.channels["telegram"] = fake
    manager._spawn_channel_task("telegram", fake)
    await asyncio.sleep(0.05)

    result = await manager.restart_channel("telegram", reason="config changed", source="webui")
    await asyncio.sleep(0.05)

    assert result["last_restart_reason"] == "config changed"
    assert result["last_restart_source"] == "webui"
    assert len(result["restart_history"]) == 1
    assert result["restart_history"][0]["reason"] == "config changed"
    assert result["restart_history"][0]["source"] == "webui"
    assert result["restart_history"][0]["result"] == "running"

    status = manager.get_status()
    assert status["telegram"]["last_restart_reason"] == "config changed"

    await fake.stop()
    await asyncio.sleep(0.05)


def test_channel_manager_disabled_channels_start_unavailable():
    manager = ChannelManager(Config(), MessageBus())

    status = manager.get_channel_status()

    assert status["telegram"]["configured_enabled"] is False
    assert status["telegram"]["configured_complete"] is True
    assert status["telegram"]["available"] is False
    assert status["telegram"]["attachment_only_ingress"] == "full"
    assert status["telegram"]["media_delivery"] == "local_paths"
    assert status["telegram"]["delivery_mode"] == "final_only"


def test_channel_manager_enabled_but_incomplete_channel_is_blocked():
    config = Config()
    config.channels.telegram.enabled = True

    manager = ChannelManager(config, MessageBus())
    status = manager.get_channel_status()

    assert "telegram" not in manager.channels
    assert status["telegram"]["configured_enabled"] is True
    assert status["telegram"]["configured_complete"] is False
    assert status["telegram"]["available"] is False
    assert "missing config: token" in status["telegram"]["error"]


def test_channel_manager_enabled_but_incomplete_whatsapp_is_blocked():
    config = Config()
    config.channels.whatsapp.enabled = True
    config.channels.whatsapp.bridge_url = ""

    manager = ChannelManager(config, MessageBus())
    status = manager.get_channel_status()

    assert "whatsapp" not in manager.channels
    assert status["whatsapp"]["configured_enabled"] is True
    assert status["whatsapp"]["configured_complete"] is False
    assert status["whatsapp"]["available"] is False
    assert "missing config: bridge_url" in status["whatsapp"]["error"]


def test_channel_manager_enabled_weixin_without_bridge_token_is_allowed():
    config = Config()
    config.channels.weixin.enabled = True

    manager = ChannelManager(config, MessageBus())
    status = manager.get_channel_status()

    assert "weixin" in manager.channels
    assert status["weixin"]["configured_enabled"] is True
    assert status["weixin"]["configured_complete"] is True
    assert status["weixin"]["available"] is True
    assert status["weixin"]["error"] == ""


@pytest.mark.asyncio
async def test_channel_manager_ensure_channel_enables_auto_pairing() -> None:
    config = Config()
    config.channels.auto_pairing = True
    manager = ChannelManager(config, MessageBus())
    fake = _FakeChannel()

    await manager.ensure_channel("weixin", fake)

    assert fake.auto_pairing_enabled is True
    await fake.stop()
