"""Channel manager for coordinating chat channels."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from loguru import logger

from lemonclaw.bus.events import OutboundMessage
from lemonclaw.bus.queue import MessageBus
from lemonclaw.channels.base import BaseChannel
from lemonclaw.channels.capabilities import ALL_CHANNEL_NAMES, get_channel_capability
from lemonclaw.channels.delivery_context import apply_delivery_route, resolve_delivery_session_key
from lemonclaw.config.schema import Config
from lemonclaw.triggers import TriggerRuntime

if TYPE_CHECKING:
    from lemonclaw.bus.activity import ActivityBus


class ChannelManager:
    """
    Manages chat channels and coordinates message routing.

    Responsibilities:
    - Initialize enabled channels (Telegram, WhatsApp, etc.)
    - Start/stop channels
    - Route outbound messages
    """

    def __init__(
        self,
        config: Config,
        bus: MessageBus,
        activity_bus: ActivityBus | None = None,
        trigger_runtime: TriggerRuntime | None = None,
    ):
        self.config = config
        self.bus = bus
        self.activity_bus = activity_bus
        self.trigger_runtime = trigger_runtime
        self.channels: dict[str, BaseChannel] = {}
        self._channel_status: dict[str, dict[str, Any]] = {}
        self._channel_tasks: dict[str, asyncio.Task] = {}
        self._restart_locks: dict[str, asyncio.Lock] = {}
        self._restart_state: dict[str, dict[str, Any]] = {}
        self._dispatch_task: asyncio.Task | None = None

        self._init_channels()

        # Enable auto-pairing per channel (global legacy toggle or per-channel dm_policy)
        from lemonclaw.utils.helpers import get_data_path
        data_dir = get_data_path()
        for name, channel in self.channels.items():
            if self._channel_pairing_enabled(name):
                channel.enable_auto_pairing(data_dir)

    def _channel_pairing_enabled(self, channel_name: str) -> bool:
        if self.config.channels.auto_pairing:
            return True
        if channel_name == "slack":
            return self.config.channels.slack.dm.policy == "pairing"
        channel_cfg = getattr(self.config.channels, channel_name, None)
        return getattr(channel_cfg, "dm_policy", None) == "pairing"

    def _channel_config_error(self, channel_name: str) -> str:
        cfg = getattr(self.config.channels, channel_name, None)
        if cfg is None:
            return "missing channel config"

        def _missing(*fields: str) -> str:
            missing = [field for field in fields if not getattr(cfg, field, None)]
            return ", ".join(missing)

        if channel_name == "telegram":
            missing = _missing("token")
            return f"missing config: {missing}" if missing else ""
        if channel_name == "discord":
            missing = _missing("token")
            return f"missing config: {missing}" if missing else ""
        if channel_name == "feishu":
            missing = _missing("app_id", "app_secret")
            return f"missing config: {missing}" if missing else ""
        if channel_name == "dingtalk":
            missing = _missing("client_id", "client_secret")
            return f"missing config: {missing}" if missing else ""
        if channel_name == "slack":
            missing = _missing("bot_token", "app_token")
            return f"missing config: {missing}" if missing else ""
        if channel_name == "qq":
            missing = _missing("app_id", "secret")
            return f"missing config: {missing}" if missing else ""
        if channel_name == "matrix":
            missing = _missing("access_token", "user_id")
            return f"missing config: {missing}" if missing else ""
        if channel_name == "mochat":
            missing = _missing("claw_token")
            return f"missing config: {missing}" if missing else ""
        if channel_name == "wecom":
            missing = _missing("corp_id", "secret", "token", "encoding_aes_key")
            if not getattr(cfg, "agent_id", 0):
                missing = f"{missing}, agent_id" if missing else "agent_id"
            return f"missing config: {missing}" if missing else ""
        if channel_name == "weixin":
            missing = _missing("bridge_token")
            return f"missing config: {missing}" if missing else ""
        if channel_name == "email":
            missing = _missing("consent_granted", "imap_host", "imap_username", "imap_password")
            if getattr(cfg, "auto_reply_enabled", True):
                extra = _missing("smtp_host", "smtp_username", "smtp_password", "from_address")
                if extra:
                    missing = f"{missing}, {extra}" if missing else extra
            return f"missing config: {missing}" if missing else ""
        return ""

    def _init_channels(self) -> None:
        """Initialize channels based on config."""
        for name in ALL_CHANNEL_NAMES:
            enabled = bool(getattr(getattr(self.config.channels, name, None), "enabled", False))
            config_error = self._channel_config_error(name) if enabled else ""
            capability = get_channel_capability(name)
            self._channel_status[name] = {
                "configured_enabled": enabled,
                "configured_complete": not bool(config_error),
                "registered": False,
                "running": False,
                # `available` means a configured runtime is actually importable/usable.
                # Disabled channels stay unavailable instead of looking healthy-by-default.
                "available": False,
                "error": config_error,
                "transport": capability.transport,
                "attachment_only_ingress": capability.attachment_only_ingress,
                "media_delivery": capability.media_delivery,
                "media_notes": capability.notes,
            }

        # Telegram channel
        if self.config.channels.telegram.enabled:
            if self._channel_status["telegram"]["error"]:
                logger.warning("Telegram channel not available: {}", self._channel_status["telegram"]["error"])
            else:
                try:
                    from lemonclaw.channels.telegram import TelegramChannel
                    self.channels["telegram"] = TelegramChannel(
                        self.config.channels.telegram,
                        self.bus,
                        api_key=self.config.lemondata.api_key,
                        api_base=self.config.lemondata.api_base_url,
                        activity_bus=self.activity_bus,
                        trigger_runtime=self.trigger_runtime,
                    )
                    self._channel_status["telegram"].update({"registered": True, "available": True})
                    logger.info("Telegram channel enabled")
                except ImportError as e:
                    self._channel_status["telegram"].update({"available": False, "error": str(e)})
                    logger.warning("Telegram channel not available: {}", e)
        # WhatsApp channel
        if self.config.channels.whatsapp.enabled:
            try:
                from lemonclaw.channels.whatsapp import WhatsAppChannel
                self.channels["whatsapp"] = WhatsAppChannel(
                    self.config.channels.whatsapp, self.bus, trigger_runtime=self.trigger_runtime
                )
                self._channel_status["whatsapp"].update({"registered": True, "available": True})
                logger.info("WhatsApp channel enabled")
            except ImportError as e:
                self._channel_status["whatsapp"].update({"available": False, "error": str(e)})
                logger.warning("WhatsApp channel not available: {}", e)

        # Discord channel
        if self.config.channels.discord.enabled:
            if self._channel_status["discord"]["error"]:
                logger.warning("Discord channel not available: {}", self._channel_status["discord"]["error"])
            else:
                try:
                    from lemonclaw.channels.discord import DiscordChannel
                    self.channels["discord"] = DiscordChannel(
                        self.config.channels.discord, self.bus
                    )
                    self._channel_status["discord"].update({"registered": True, "available": True})
                    logger.info("Discord channel enabled")
                except ImportError as e:
                    self._channel_status["discord"].update({"available": False, "error": str(e)})
                    logger.warning("Discord channel not available: {}", e)

        # Feishu channel
        if self.config.channels.feishu.enabled:
            if self._channel_status["feishu"]["error"]:
                logger.warning("Feishu channel not available: {}", self._channel_status["feishu"]["error"])
            else:
                try:
                    from lemonclaw.channels.feishu import FeishuChannel
                    self.channels["feishu"] = FeishuChannel(
                        self.config.channels.feishu, self.bus, trigger_runtime=self.trigger_runtime
                    )
                    self._channel_status["feishu"].update({"registered": True, "available": True})
                    logger.info("Feishu channel enabled")
                except ImportError as e:
                    self._channel_status["feishu"].update({"available": False, "error": str(e)})
                    logger.warning("Feishu channel not available: {}", e)

        # Mochat channel
        if self.config.channels.mochat.enabled:
            if self._channel_status["mochat"]["error"]:
                logger.warning("Mochat channel not available: {}", self._channel_status["mochat"]["error"])
            else:
                try:
                    from lemonclaw.channels.mochat import MochatChannel

                    self.channels["mochat"] = MochatChannel(
                        self.config.channels.mochat, self.bus, trigger_runtime=self.trigger_runtime
                    )
                    self._channel_status["mochat"].update({"registered": True, "available": True})
                    logger.info("Mochat channel enabled")
                except ImportError as e:
                    self._channel_status["mochat"].update({"available": False, "error": str(e)})
                    logger.warning("Mochat channel not available: {}", e)

        # DingTalk channel
        if self.config.channels.dingtalk.enabled:
            if self._channel_status["dingtalk"]["error"]:
                logger.warning("DingTalk channel not available: {}", self._channel_status["dingtalk"]["error"])
            else:
                try:
                    from lemonclaw.channels.dingtalk import DingTalkChannel
                    self.channels["dingtalk"] = DingTalkChannel(
                        self.config.channels.dingtalk, self.bus, trigger_runtime=self.trigger_runtime
                    )
                    self._channel_status["dingtalk"].update({"registered": True, "available": True})
                    logger.info("DingTalk channel enabled")
                except ImportError as e:
                    self._channel_status["dingtalk"].update({"available": False, "error": str(e)})
                    logger.warning("DingTalk channel not available: {}", e)

        # Email channel
        if self.config.channels.email.enabled:
            if self._channel_status["email"]["error"]:
                logger.warning("Email channel not available: {}", self._channel_status["email"]["error"])
            else:
                try:
                    from lemonclaw.channels.email import EmailChannel
                    self.channels["email"] = EmailChannel(
                        self.config.channels.email, self.bus
                    )
                    self._channel_status["email"].update({"registered": True, "available": True})
                    logger.info("Email channel enabled")
                except ImportError as e:
                    self._channel_status["email"].update({"available": False, "error": str(e)})
                    logger.warning("Email channel not available: {}", e)

        # Slack channel
        if self.config.channels.slack.enabled:
            if self._channel_status["slack"]["error"]:
                logger.warning("Slack channel not available: {}", self._channel_status["slack"]["error"])
            else:
                try:
                    from lemonclaw.channels.slack import SlackChannel
                    self.channels["slack"] = SlackChannel(
                        self.config.channels.slack, self.bus, trigger_runtime=self.trigger_runtime
                    )
                    self._channel_status["slack"].update({"registered": True, "available": True})
                    logger.info("Slack channel enabled")
                except ImportError as e:
                    self._channel_status["slack"].update({"available": False, "error": str(e)})
                    logger.warning("Slack channel not available: {}", e)

        # QQ channel
        if self.config.channels.qq.enabled:
            if self._channel_status["qq"]["error"]:
                logger.warning("QQ channel not available: {}", self._channel_status["qq"]["error"])
            else:
                try:
                    from lemonclaw.channels.qq import QQChannel
                    self.channels["qq"] = QQChannel(
                        self.config.channels.qq,
                        self.bus,
                    )
                    self._channel_status["qq"].update({"registered": True, "available": True})
                    logger.info("QQ channel enabled")
                except ImportError as e:
                    self._channel_status["qq"].update({"available": False, "error": str(e)})
                    logger.warning("QQ channel not available: {}", e)

        # Matrix channel
        if self.config.channels.matrix.enabled:
            if self._channel_status["matrix"]["error"]:
                logger.warning("Matrix channel not available: {}", self._channel_status["matrix"]["error"])
            else:
                try:
                    from lemonclaw.channels.matrix import MatrixChannel
                    self.channels["matrix"] = MatrixChannel(
                        self.config.channels.matrix,
                        self.bus,
                        trigger_runtime=self.trigger_runtime,
                    )
                    self._channel_status["matrix"].update({"registered": True, "available": True})
                    logger.info("Matrix channel enabled")
                except ImportError as e:
                    self._channel_status["matrix"].update({"available": False, "error": str(e)})
                    logger.warning("Matrix channel not available: {}", e)

        # Weixin channel
        if self.config.channels.weixin.enabled:
            if self._channel_status["weixin"]["error"]:
                logger.warning("Weixin channel not available: {}", self._channel_status["weixin"]["error"])
            else:
                try:
                    from lemonclaw.channels.weixin import WeixinChannel

                    self.channels["weixin"] = WeixinChannel(
                        self.config.channels.weixin,
                        self.bus,
                        trigger_runtime=self.trigger_runtime,
                    )
                    self._channel_status["weixin"].update({"registered": True, "available": True})
                    logger.info("Weixin channel enabled")
                except ImportError as e:
                    self._channel_status["weixin"].update({"available": False, "error": str(e)})
                    logger.warning("Weixin channel not available: {}", e)

        # WeCom channel
        if self.config.channels.wecom.enabled:
            if self._channel_status["wecom"]["error"]:
                logger.warning("WeCom channel not available: {}", self._channel_status["wecom"]["error"])
            else:
                try:
                    from lemonclaw.channels.wecom import WeComChannel
                    self.channels["wecom"] = WeComChannel(
                        self.config.channels.wecom, self.bus, trigger_runtime=self.trigger_runtime
                    )
                    self._channel_status["wecom"].update({"registered": True, "available": True})
                    logger.info("WeCom channel enabled")
                except ImportError as e:
                    self._channel_status["wecom"].update({"available": False, "error": str(e)})
                    logger.warning("WeCom channel not available: {}", e)

    async def _start_channel(self, name: str, channel: BaseChannel) -> None:
        """Start a channel and log any exceptions."""
        try:
            self._channel_status.setdefault(name, {}).update({"running": True, "error": ""})
            await channel.start()
        except Exception as e:
            logger.error("Failed to start channel {}: {}", name, e)
            channel._running = False
            self._channel_status.setdefault(name, {}).update({"running": False, "available": False, "error": str(e)})
        else:
            self._channel_status.setdefault(name, {}).update({"running": False})

    def _spawn_channel_task(self, name: str, channel: BaseChannel) -> asyncio.Task:
        task = asyncio.create_task(self._start_channel(name, channel))
        self._channel_tasks[name] = task
        return task

    async def ensure_channel(self, name: str, channel: BaseChannel) -> BaseChannel:
        """Register and start a channel at runtime if it is not already active."""

        existing = self.channels.get(name)
        if existing is not None:
            task = self._channel_tasks.get(name)
            if task is None or task.done():
                self._spawn_channel_task(name, existing)
                await asyncio.sleep(0)
            return existing

        self.channels[name] = channel
        if self._channel_pairing_enabled(name):
            from lemonclaw.utils.helpers import get_data_path

            channel.enable_auto_pairing(get_data_path())
        self._channel_status.setdefault(name, {}).update(
            {
                "configured_enabled": True,
                "registered": True,
                "running": False,
                "available": True,
                "error": "",
            }
        )
        if self._dispatch_task is None or self._dispatch_task.done():
            self._dispatch_task = asyncio.create_task(self._dispatch_outbound())
        self._spawn_channel_task(name, channel)
        await asyncio.sleep(0)
        return channel

    async def start_all(self) -> None:
        """Start all channels and the outbound dispatcher."""
        if not self.channels:
            logger.warning("No channels enabled")
            return

        # Start outbound dispatcher
        self._dispatch_task = asyncio.create_task(self._dispatch_outbound())

        # Start channels
        tasks = []
        for name, channel in self.channels.items():
            logger.info("Starting {} channel...", name)
            tasks.append(self._spawn_channel_task(name, channel))

        # Wait for all to complete (they should run forever)
        await asyncio.gather(*tasks, return_exceptions=True)

    async def stop_all(self) -> None:
        """Stop all channels and the dispatcher."""
        logger.info("Stopping all channels...")

        # Stop dispatcher
        if self._dispatch_task:
            self._dispatch_task.cancel()
            try:
                await self._dispatch_task
            except asyncio.CancelledError:
                pass

        # Stop all channels
        for name, channel in self.channels.items():
            try:
                await channel.stop()
                self._channel_status.setdefault(name, {}).update({"running": False})
                logger.info("Stopped {} channel", name)
            except Exception as e:
                logger.error("Error stopping {}: {}", name, e)
                self._channel_status.setdefault(name, {}).update({"running": False, "error": str(e)})
        for name, task in list(self._channel_tasks.items()):
            if task.done():
                self._channel_tasks.pop(name, None)
                continue
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            self._channel_tasks.pop(name, None)

    def get_channel_status(self) -> dict[str, dict[str, Any]]:
        """Return a structured snapshot of configured channel availability."""
        return {name: dict(status) for name, status in self._channel_status.items()}

    async def restart_channel(self, name: str, *, reason: str = "", source: str = "system") -> dict[str, Any]:
        """Stop and restart a single channel without touching others."""
        channel = self.channels.get(name)
        if channel is None:
            raise KeyError(name)

        lock = self._restart_locks.setdefault(name, asyncio.Lock())
        async with lock:
            task = self._channel_tasks.get(name)
            await channel.stop()
            if task and not task.done():
                try:
                    await asyncio.wait_for(task, timeout=0.5)
                except asyncio.TimeoutError:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                finally:
                    self._channel_tasks.pop(name, None)

            logger.info("Restarting {} channel (reason={}, source={})...", name, reason or "unspecified", source)
            restart_task = self._spawn_channel_task(name, channel)
            await asyncio.sleep(0)
            result = {
                "channel": name,
                "running": channel.is_running,
                "task_done": restart_task.done(),
            }
            state = self._restart_state.setdefault(name, {"restart_count": 0, "restart_fail_count": 0})
            state["restart_count"] += 1
            now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
            state["last_restart_at_ms"] = now_ms
            state["last_restart_result"] = "running" if result["running"] else "not_running"
            state["last_restart_reason"] = reason[:500] if reason else ""
            state["last_restart_source"] = source
            if not result["running"]:
                state["restart_fail_count"] += 1
            # Append to audit history (capped at 20 entries)
            history = list(state.get("restart_history") or [])
            history.append({
                "at_ms": now_ms,
                "reason": reason[:500] if reason else "",
                "source": source,
                "result": state["last_restart_result"],
            })
            state["restart_history"] = history[-20:]
            result.update(state)
            return result

    @staticmethod
    def _activity_session_key(msg: OutboundMessage) -> str:
        thread_id = (msg.metadata or {}).get("message_thread_id")
        if thread_id:
            return f"{msg.channel}:{msg.chat_id}:{thread_id}"
        return f"{msg.channel}:{msg.chat_id}"

    @staticmethod
    def _is_internal_message(msg: OutboundMessage) -> bool:
        meta = msg.metadata or {}
        return bool(
            meta.get("_thinking")
            or meta.get("_chunk")
            or meta.get("_tool_start")
            or meta.get("_tool_result")
        )

    @staticmethod
    def _should_skip_activity_broadcast(msg: OutboundMessage) -> bool:
        meta = msg.metadata or {}
        return bool(meta.get("_thinking"))

    async def _dispatch_outbound(self) -> None:
        """Dispatch outbound messages to the appropriate channel."""
        logger.info("Outbound dispatcher started")

        while True:
            try:
                msg = await asyncio.wait_for(
                    self.bus.consume_outbound(),
                    timeout=1.0
                )
                delivery_session_key = resolve_delivery_session_key(
                    metadata=msg.metadata,
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                )
                apply_delivery_route(msg)

                # ActivityBus broadcast — before progress filter so all IM events are visible
                if msg.channel != "webui" and self.activity_bus and not self._should_skip_activity_broadcast(msg):
                    meta = msg.metadata or {}
                    if meta.get("_final"):
                        event_type = "done"
                    elif meta.get("_chunk"):
                        event_type = "chunk"
                    elif meta.get("_progress"):
                        event_type = "progress"
                    else:
                        event_type = "message"
                    event: dict[str, Any] = {
                        "type": event_type,
                        "session_key": delivery_session_key or self._activity_session_key(msg),
                        "channel": msg.channel,
                        "role": "assistant",
                        "content": msg.content,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                    if meta.get("_chunk_first"):
                        event["first"] = True
                    await self.activity_bus.broadcast(event)

                if msg.metadata.get("_progress"):
                    # Never leak internal reasoning or raw transport chunks to end-user channels.
                    if self._is_internal_message(msg):
                        continue
                    if msg.channel != "webui":
                        continue
                    if msg.metadata.get("_tool_hint") and not self.config.channels.send_tool_hints:
                        continue
                    if not msg.metadata.get("_tool_hint") and not self.config.channels.send_progress:
                        continue

                channel = self.channels.get(msg.channel)
                if channel:
                    try:
                        await channel.send(msg)
                    except Exception as e:
                        logger.error("Error sending to {}: {}", msg.channel, e)
                else:
                    logger.warning("Unknown channel: {}", msg.channel)

            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    def get_channel(self, name: str) -> BaseChannel | None:
        """Get a channel by name."""
        return self.channels.get(name)

    def get_status(self) -> dict[str, Any]:
        """Get status of all channels."""
        return {
            name: {
                **dict(self._channel_status.get(name, {})),
                "enabled": bool(self._channel_status.get(name, {}).get("configured_enabled", True)),
                "running": channel.is_running,
                **dict(self._restart_state.get(name, {})),
            }
            for name, channel in self.channels.items()
        }

    @property
    def enabled_channels(self) -> list[str]:
        """Get list of enabled channel names."""
        return list(self.channels.keys())
