"""Channel manager for coordinating chat channels."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from loguru import logger

from lemonclaw.bus.events import OutboundMessage
from lemonclaw.bus.queue import MessageBus
from lemonclaw.channels.base import BaseChannel
from lemonclaw.config.schema import Config

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
    
    def __init__(self, config: Config, bus: MessageBus, activity_bus: ActivityBus | None = None):
        self.config = config
        self.bus = bus
        self.activity_bus = activity_bus
        self.channels: dict[str, BaseChannel] = {}
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

    def _init_channels(self) -> None:
        """Initialize channels based on config."""
        
        # Telegram channel
        if self.config.channels.telegram.enabled:
            try:
                from lemonclaw.channels.telegram import TelegramChannel
                self.channels["telegram"] = TelegramChannel(
                    self.config.channels.telegram,
                    self.bus,
                    api_key=self.config.lemondata.api_key,
                    api_base=self.config.lemondata.api_base_url,
                    activity_bus=self.activity_bus,
                )
                logger.info("Telegram channel enabled")
            except ImportError as e:
                logger.warning("Telegram channel not available: {}", e)
        
        # WhatsApp channel
        if self.config.channels.whatsapp.enabled:
            try:
                from lemonclaw.channels.whatsapp import WhatsAppChannel
                self.channels["whatsapp"] = WhatsAppChannel(
                    self.config.channels.whatsapp, self.bus
                )
                logger.info("WhatsApp channel enabled")
            except ImportError as e:
                logger.warning("WhatsApp channel not available: {}", e)

        # Discord channel
        if self.config.channels.discord.enabled:
            try:
                from lemonclaw.channels.discord import DiscordChannel
                self.channels["discord"] = DiscordChannel(
                    self.config.channels.discord, self.bus
                )
                logger.info("Discord channel enabled")
            except ImportError as e:
                logger.warning("Discord channel not available: {}", e)
        
        # Feishu channel
        if self.config.channels.feishu.enabled:
            try:
                from lemonclaw.channels.feishu import FeishuChannel
                self.channels["feishu"] = FeishuChannel(
                    self.config.channels.feishu, self.bus
                )
                logger.info("Feishu channel enabled")
            except ImportError as e:
                logger.warning("Feishu channel not available: {}", e)

        # Mochat channel
        if self.config.channels.mochat.enabled:
            try:
                from lemonclaw.channels.mochat import MochatChannel

                self.channels["mochat"] = MochatChannel(
                    self.config.channels.mochat, self.bus
                )
                logger.info("Mochat channel enabled")
            except ImportError as e:
                logger.warning("Mochat channel not available: {}", e)

        # DingTalk channel
        if self.config.channels.dingtalk.enabled:
            try:
                from lemonclaw.channels.dingtalk import DingTalkChannel
                self.channels["dingtalk"] = DingTalkChannel(
                    self.config.channels.dingtalk, self.bus
                )
                logger.info("DingTalk channel enabled")
            except ImportError as e:
                logger.warning("DingTalk channel not available: {}", e)

        # Email channel
        if self.config.channels.email.enabled:
            try:
                from lemonclaw.channels.email import EmailChannel
                self.channels["email"] = EmailChannel(
                    self.config.channels.email, self.bus
                )
                logger.info("Email channel enabled")
            except ImportError as e:
                logger.warning("Email channel not available: {}", e)

        # Slack channel
        if self.config.channels.slack.enabled:
            try:
                from lemonclaw.channels.slack import SlackChannel
                self.channels["slack"] = SlackChannel(
                    self.config.channels.slack, self.bus
                )
                logger.info("Slack channel enabled")
            except ImportError as e:
                logger.warning("Slack channel not available: {}", e)

        # QQ channel
        if self.config.channels.qq.enabled:
            try:
                from lemonclaw.channels.qq import QQChannel
                self.channels["qq"] = QQChannel(
                    self.config.channels.qq,
                    self.bus,
                )
                logger.info("QQ channel enabled")
            except ImportError as e:
                logger.warning("QQ channel not available: {}", e)
        
        # Matrix channel
        if self.config.channels.matrix.enabled:
            try:
                from lemonclaw.channels.matrix import MatrixChannel
                self.channels["matrix"] = MatrixChannel(
                    self.config.channels.matrix,
                    self.bus,
                )
                logger.info("Matrix channel enabled")
            except ImportError as e:
                logger.warning("Matrix channel not available: {}", e)

        # WeCom channel
        if self.config.channels.wecom.enabled:
            try:
                from lemonclaw.channels.wecom import WeComChannel
                self.channels["wecom"] = WeComChannel(
                    self.config.channels.wecom, self.bus
                )
                logger.info("WeCom channel enabled")
            except ImportError as e:
                logger.warning("WeCom channel not available: {}", e)
    
    async def _start_channel(self, name: str, channel: BaseChannel) -> None:
        """Start a channel and log any exceptions."""
        try:
            await channel.start()
        except Exception as e:
            logger.error("Failed to start channel {}: {}", name, e)
            channel._running = False

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
            tasks.append(asyncio.create_task(self._start_channel(name, channel)))
        
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
                logger.info("Stopped {} channel", name)
            except Exception as e:
                logger.error("Error stopping {}: {}", name, e)
    
    @staticmethod
    def _activity_session_key(msg: OutboundMessage) -> str:
        thread_id = (msg.metadata or {}).get("message_thread_id")
        if thread_id:
            return f"{msg.channel}:{msg.chat_id}:{thread_id}"
        return f"{msg.channel}:{msg.chat_id}"

    @staticmethod
    def _should_skip_activity_broadcast(msg: OutboundMessage) -> bool:
        meta = msg.metadata or {}
        return msg.channel == "telegram" and bool(meta.get("_progress") or meta.get("_final"))

    async def _dispatch_outbound(self) -> None:
        """Dispatch outbound messages to the appropriate channel."""
        logger.info("Outbound dispatcher started")

        while True:
            try:
                msg = await asyncio.wait_for(
                    self.bus.consume_outbound(),
                    timeout=1.0
                )

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
                        "session_key": self._activity_session_key(msg),
                        "channel": msg.channel,
                        "role": "assistant",
                        "content": msg.content,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                    if meta.get("_chunk_first"):
                        event["first"] = True
                    await self.activity_bus.broadcast(event)

                if msg.metadata.get("_progress"):
                    # Never leak thinking/reasoning content to users
                    if msg.metadata.get("_thinking"):
                        continue
                    # Never send raw LLM chunks to channels that can't edit messages
                    # (Telegram handles this via draft streaming; all others would spam)
                    if msg.metadata.get("_chunk"):
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
                "enabled": True,
                "running": channel.is_running
            }
            for name, channel in self.channels.items()
        }
    
    @property
    def enabled_channels(self) -> list[str]:
        """Get list of enabled channel names."""
        return list(self.channels.keys())
