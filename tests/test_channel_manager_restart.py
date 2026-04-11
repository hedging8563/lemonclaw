import asyncio
from types import SimpleNamespace

import pytest

from lemonclaw.bus.events import OutboundMessage
from lemonclaw.bus.queue import MessageBus
from lemonclaw.channels.delivery_context import DELIVERY_CONTEXT_KEY
from lemonclaw.channels.manager import ChannelManager, _DISPATCH_RETRY_MAX_AGE_MS
from lemonclaw.config.schema import Config


class _FakeChannel:
    def __init__(self) -> None:
        self._running = False
        self.start_calls = 0
        self.stop_calls = 0
        self.auto_pairing_enabled = False
        self._stop_event = asyncio.Event()
        self.sent_messages = []

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
        self.sent_messages.append(msg)
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


@pytest.mark.asyncio
async def test_channel_manager_refresh_channels_from_config_restarts_only_changed_channel(monkeypatch) -> None:
    config = Config()
    config.channels.telegram.enabled = True
    config.channels.telegram.token = "token-1"
    config.channels.discord.enabled = True
    config.channels.discord.token = "discord-1"

    manager = ChannelManager(config, MessageBus())
    telegram_old = _FakeChannel()
    discord_old = _FakeChannel()
    manager.channels = {"telegram": telegram_old, "discord": discord_old}
    manager._channel_status["telegram"].update({"configured_enabled": True, "registered": True, "available": True})
    manager._channel_status["discord"].update({"configured_enabled": True, "registered": True, "available": True})
    manager._spawn_channel_task("telegram", telegram_old)
    manager._spawn_channel_task("discord", discord_old)
    await asyncio.sleep(0.05)

    built: dict[str, _FakeChannel] = {}

    def _fake_build(name: str):
        channel = _FakeChannel()
        built[name] = channel
        return channel

    monkeypatch.setattr(manager, "_build_channel", _fake_build)
    monkeypatch.setattr(manager, "_enable_pairing_if_needed", lambda name, channel: None)

    next_config = Config()
    next_config.channels.telegram.enabled = True
    next_config.channels.telegram.token = "token-2"
    next_config.channels.discord.enabled = True
    next_config.channels.discord.token = "discord-1"

    result = await manager.refresh_channels_from_config(next_config, changed_paths=["channels.telegram.token"])
    await asyncio.sleep(0.05)

    assert list(result.keys()) == ["telegram"]
    assert result["telegram"]["refreshed"] is True
    assert telegram_old.stop_calls == 1
    assert discord_old.stop_calls == 0
    assert manager.channels["telegram"] is built["telegram"]
    assert manager.channels["discord"] is discord_old

    await built["telegram"].stop()
    await discord_old.stop()


@pytest.mark.asyncio
async def test_channel_manager_requeues_outbound_while_channel_missing_during_refresh():
    manager = ChannelManager(Config(), MessageBus())
    manager._channel_status["telegram"] = {
        "configured_enabled": True,
        "configured_complete": True,
        "registered": False,
        "running": False,
        "available": False,
        "error": "",
    }
    manager._dispatch_task = asyncio.create_task(manager._dispatch_outbound())

    await manager.bus.publish_outbound(
        OutboundMessage(
            channel="telegram",
            chat_id="chat-1",
            content="hello",
        )
    )
    await asyncio.sleep(0.05)

    fake = _FakeChannel()
    fake._running = True
    manager.channels["telegram"] = fake
    manager._channel_status["telegram"].update({"registered": True, "running": True, "available": True})

    await asyncio.sleep(0.2)

    assert len(fake.sent_messages) == 1
    assert fake.sent_messages[0].content == "hello"

    await manager.stop_all()


@pytest.mark.asyncio
async def test_channel_manager_requeues_outbound_while_channel_restart_lock_is_held():
    manager = ChannelManager(Config(), MessageBus())
    fake = _FakeChannel()
    fake._running = False
    manager.channels["telegram"] = fake
    manager._channel_status["telegram"] = {
        "configured_enabled": True,
        "configured_complete": True,
        "registered": True,
        "running": False,
        "available": True,
        "error": "",
    }
    lock = asyncio.Lock()
    await lock.acquire()
    manager._restart_locks["telegram"] = lock
    manager._dispatch_task = asyncio.create_task(manager._dispatch_outbound())

    await manager.bus.publish_outbound(
        OutboundMessage(
            channel="telegram",
            chat_id="chat-1",
            content="hello again",
        )
    )
    await asyncio.sleep(0.05)

    fake._running = True
    lock.release()
    await asyncio.sleep(0.2)

    assert len(fake.sent_messages) == 1
    assert fake.sent_messages[0].content == "hello again"

    await manager.stop_all()


@pytest.mark.asyncio
async def test_channel_manager_keeps_requeueing_outbound_past_previous_retry_cap():
    manager = ChannelManager(Config(), MessageBus())
    manager._channel_status["telegram"] = {
        "configured_enabled": True,
        "configured_complete": True,
        "registered": False,
        "running": False,
        "available": False,
        "error": "",
    }
    manager._dispatch_task = asyncio.create_task(manager._dispatch_outbound())

    await manager.bus.publish_outbound(
        OutboundMessage(
            channel="telegram",
            chat_id="chat-1",
            content="hello after many retries",
            metadata={"_dispatch_retry_count": 20},
        )
    )
    await asyncio.sleep(0.05)

    fake = _FakeChannel()
    fake._running = True
    manager.channels["telegram"] = fake
    manager._channel_status["telegram"].update({"registered": True, "running": True, "available": True})

    await asyncio.sleep(1.15)

    assert len(fake.sent_messages) == 1
    assert fake.sent_messages[0].content == "hello after many retries"
    assert fake.sent_messages[0].metadata.get("_dispatch_retry_count", 0) >= 21

    await manager.stop_all()


@pytest.mark.asyncio
async def test_channel_manager_requeues_outbound_while_channel_marked_unavailable_after_failed_start():
    manager = ChannelManager(Config(), MessageBus())
    failed = _FakeChannel()
    failed._running = False
    manager.channels["telegram"] = failed
    manager._channel_status["telegram"] = {
        "configured_enabled": True,
        "configured_complete": True,
        "registered": True,
        "running": False,
        "available": False,
        "error": "startup failed",
    }
    done = asyncio.get_running_loop().create_future()
    done.set_result(None)
    manager._channel_tasks["telegram"] = done
    manager._dispatch_task = asyncio.create_task(manager._dispatch_outbound())

    await manager.bus.publish_outbound(
        OutboundMessage(
            channel="telegram",
            chat_id="chat-1",
            content="hello after failed start",
        )
    )
    await asyncio.sleep(0.05)
    assert failed.sent_messages == []

    failed._running = True
    manager._channel_status["telegram"].update({"available": True, "running": True, "error": ""})
    await asyncio.sleep(0.2)

    assert len(failed.sent_messages) == 1
    assert failed.sent_messages[0].content == "hello after failed start"

    await manager.stop_all()


@pytest.mark.asyncio
async def test_channel_manager_preserves_delivery_route_across_temporary_requeue():
    manager = ChannelManager(Config(), MessageBus())
    manager._channel_status["telegram"] = {
        "configured_enabled": True,
        "configured_complete": True,
        "registered": False,
        "running": False,
        "available": False,
        "error": "",
    }
    manager._dispatch_task = asyncio.create_task(manager._dispatch_outbound())

    await manager.bus.publish_outbound(
        OutboundMessage(
            channel="telegram",
            chat_id="chat-1",
            content="threaded hello",
            metadata={
                DELIVERY_CONTEXT_KEY: {
                    "source_channel": "telegram",
                    "source_chat_id": "chat-1",
                    "session_key": "telegram:chat-1",
                    "route": {
                        "reply_to_message_id": 321,
                        "message_thread_id": 456,
                    },
                },
            },
        )
    )
    await asyncio.sleep(0.05)

    fake = _FakeChannel()
    fake._running = True
    manager.channels["telegram"] = fake
    manager._channel_status["telegram"].update({"registered": True, "running": True, "available": True})
    await asyncio.sleep(0.2)

    assert len(fake.sent_messages) == 1
    assert fake.sent_messages[0].metadata["message_id"] == 321
    assert fake.sent_messages[0].metadata["message_thread_id"] == 456
    assert DELIVERY_CONTEXT_KEY not in fake.sent_messages[0].metadata

    await manager.stop_all()


@pytest.mark.asyncio
async def test_channel_manager_terminalizes_stale_temporary_retries():
    manager = ChannelManager(Config(), MessageBus())
    manager._channel_status["telegram"] = {
        "configured_enabled": True,
        "configured_complete": True,
        "registered": False,
        "running": False,
        "available": False,
        "error": "",
    }
    manager._dispatch_task = asyncio.create_task(manager._dispatch_outbound())

    await manager.bus.publish_outbound(
        OutboundMessage(
            channel="telegram",
            chat_id="chat-1",
            content="stale retry",
            metadata={
                "_dispatch_retry_count": 12,
                "_dispatch_retry_first_at_ms": manager._now_ms() - (_DISPATCH_RETRY_MAX_AGE_MS + 1_000),
            },
        )
    )
    await asyncio.sleep(0.05)

    status = manager.get_channel_status()["telegram"]
    assert "dispatch retry window exhausted" in status["last_dispatch_dead_letter_reason"]
    assert status["last_dispatch_dead_letter_retry_count"] == 13
    assert manager.bus.outbound_size == 0

    await manager.stop_all()
