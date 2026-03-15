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
    assert fake.start_calls == 2
    assert fake.stop_calls == 1
    assert manager._channel_tasks["telegram"] is not first_task

    await fake.stop()
    await asyncio.sleep(0.05)
