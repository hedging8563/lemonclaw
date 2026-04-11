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
from lemonclaw.channels.delivery_context import apply_delivery_policy, apply_delivery_route, get_delivery_policy, resolve_delivery_session_key
from lemonclaw.channels.session_keys import build_channel_session_key
from lemonclaw.config.schema import Config
from lemonclaw.triggers import TriggerRuntime

if TYPE_CHECKING:
    from lemonclaw.bus.activity import ActivityBus


_CHANNEL_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "telegram": ("token",),
    "discord": ("token",),
    "whatsapp": ("bridge_url",),
    "feishu": ("app_id", "app_secret"),
    "dingtalk": ("client_id", "client_secret"),
    "slack": ("bot_token", "app_token"),
    "qq": ("app_id", "secret"),
    "matrix": ("access_token", "user_id"),
    "mochat": ("claw_token",),
}


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
        self._dispatch_retry_tasks: set[asyncio.Task] = set()

        self._init_channels()

    def _channel_pairing_enabled(self, channel_name: str) -> bool:
        if self.config.channels.auto_pairing:
            return True
        if channel_name == "slack":
            return self.config.channels.slack.dm.policy == "pairing"
        channel_cfg = getattr(self.config.channels, channel_name, None)
        return getattr(channel_cfg, "dm_policy", None) == "pairing"

    def _channel_status_base(self, name: str) -> dict[str, Any]:
        enabled = bool(getattr(getattr(self.config.channels, name, None), "enabled", False))
        config_error = self._channel_config_error(name) if enabled else ""
        capability = get_channel_capability(name)
        previous = dict(self._channel_status.get(name, {}))
        preserved = {
            key: value
            for key, value in previous.items()
            if key.startswith("last_") or key.startswith("restart_")
        }
        return {
            **preserved,
            "configured_enabled": enabled,
            "configured_complete": not bool(config_error),
            "registered": False,
            "running": False,
            "available": False,
            "error": config_error,
            "transport": capability.transport,
            "attachment_only_ingress": capability.attachment_only_ingress,
            "media_delivery": capability.media_delivery,
            "delivery_mode": capability.delivery_mode,
            "media_notes": capability.notes,
        }

    def _set_channel_status_base(self, name: str) -> None:
        self._channel_status[name] = self._channel_status_base(name)

    def _enable_pairing_if_needed(self, name: str, channel: BaseChannel) -> None:
        if not self._channel_pairing_enabled(name):
            return
        from lemonclaw.utils.helpers import get_data_path

        channel.enable_auto_pairing(get_data_path())

    def _build_channel(self, name: str) -> BaseChannel | None:
        status = self._channel_status.setdefault(name, self._channel_status_base(name))
        if not status.get("configured_enabled"):
            return None
        if status.get("error"):
            logger.warning("{} channel not available: {}", name.capitalize(), status["error"])
            return None

        try:
            if name == "telegram":
                from lemonclaw.channels.telegram import TelegramChannel

                return TelegramChannel(
                    self.config.channels.telegram,
                    self.bus,
                    api_key=self.config.lemondata.api_key,
                    api_base=self.config.lemondata.api_base_url,
                    activity_bus=self.activity_bus,
                    trigger_runtime=self.trigger_runtime,
                )
            if name == "whatsapp":
                from lemonclaw.channels.whatsapp import WhatsAppChannel

                return WhatsAppChannel(self.config.channels.whatsapp, self.bus, trigger_runtime=self.trigger_runtime)
            if name == "discord":
                from lemonclaw.channels.discord import DiscordChannel

                return DiscordChannel(self.config.channels.discord, self.bus)
            if name == "feishu":
                from lemonclaw.channels.feishu import FeishuChannel

                return FeishuChannel(self.config.channels.feishu, self.bus, trigger_runtime=self.trigger_runtime)
            if name == "mochat":
                from lemonclaw.channels.mochat import MochatChannel

                return MochatChannel(self.config.channels.mochat, self.bus, trigger_runtime=self.trigger_runtime)
            if name == "dingtalk":
                from lemonclaw.channels.dingtalk import DingTalkChannel

                return DingTalkChannel(self.config.channels.dingtalk, self.bus, trigger_runtime=self.trigger_runtime)
            if name == "email":
                from lemonclaw.channels.email import EmailChannel

                return EmailChannel(self.config.channels.email, self.bus)
            if name == "slack":
                from lemonclaw.channels.slack import SlackChannel

                return SlackChannel(self.config.channels.slack, self.bus, trigger_runtime=self.trigger_runtime)
            if name == "qq":
                from lemonclaw.channels.qq import QQChannel

                return QQChannel(self.config.channels.qq, self.bus)
            if name == "matrix":
                from lemonclaw.channels.matrix import MatrixChannel

                return MatrixChannel(self.config.channels.matrix, self.bus, trigger_runtime=self.trigger_runtime)
            if name == "weixin":
                from lemonclaw.channels.weixin import WeixinChannel

                return WeixinChannel(self.config.channels.weixin, self.bus, trigger_runtime=self.trigger_runtime)
            if name == "wecom":
                from lemonclaw.channels.wecom import WeComChannel

                return WeComChannel(self.config.channels.wecom, self.bus, trigger_runtime=self.trigger_runtime)
        except ImportError as e:
            status.update({"available": False, "error": str(e)})
            logger.warning("{} channel not available: {}", name.capitalize(), e)
            return None

        return None

    def _channel_config_error(self, channel_name: str) -> str:
        cfg = getattr(self.config.channels, channel_name, None)
        if cfg is None:
            return "missing channel config"

        def _missing(*fields: str) -> str:
            missing = [field for field in fields if not getattr(cfg, field, None)]
            return ", ".join(missing)

        if channel_name in _CHANNEL_REQUIRED_FIELDS:
            missing = _missing(*_CHANNEL_REQUIRED_FIELDS[channel_name])
            return f"missing config: {missing}" if missing else ""
        if channel_name == "wecom":
            missing = _missing("corp_id", "secret", "token", "encoding_aes_key")
            if not getattr(cfg, "agent_id", 0):
                missing = f"{missing}, agent_id" if missing else "agent_id"
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
            self._set_channel_status_base(name)
            channel = self._build_channel(name)
            if channel is None:
                self.channels.pop(name, None)
                continue
            self.channels[name] = channel
            self._channel_status[name].update({"registered": True, "available": True})
            self._enable_pairing_if_needed(name, channel)
            logger.info("{} channel enabled", name.capitalize())

    async def _stop_channel_instance(self, name: str) -> None:
        channel = self.channels.pop(name, None)
        if channel is None:
            return
        try:
            await channel.stop()
        except Exception as e:
            logger.error("Error stopping {}: {}", name, e)
            self._channel_status.setdefault(name, {}).update({"error": str(e)})
        task = self._channel_tasks.pop(name, None)
        if task and not task.done():
            try:
                await asyncio.wait_for(task, timeout=0.5)
            except asyncio.TimeoutError:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    async def refresh_channels_from_config(
        self,
        config: Config,
        *,
        changed_paths: list[str],
        source: str = "settings_apply",
    ) -> dict[str, dict[str, Any]]:
        self.config = config
        changed = set()
        if "channels.auto_pairing" in changed_paths:
            changed.update(ALL_CHANNEL_NAMES)
        for path in changed_paths:
            if path.startswith("channels."):
                parts = path.split(".")
                if len(parts) >= 2 and parts[1] in ALL_CHANNEL_NAMES:
                    changed.add(parts[1])
        if not changed:
            return {}

        results: dict[str, dict[str, Any]] = {}
        for name in sorted(changed):
            await self._stop_channel_instance(name)
            self._set_channel_status_base(name)
            channel = self._build_channel(name)
            if channel is None:
                self._channel_status[name].update({"registered": False, "running": False})
                results[name] = {
                    "channel": name,
                    "refreshed": True,
                    "running": False,
                    "registered": False,
                    "available": bool(self._channel_status[name].get("available")),
                    "error": self._channel_status[name].get("error", ""),
                    "source": source,
                }
                continue
            self.channels[name] = channel
            self._channel_status[name].update({"registered": True, "available": True, "error": ""})
            self._enable_pairing_if_needed(name, channel)
            if self._dispatch_task is None or self._dispatch_task.done():
                self._dispatch_task = asyncio.create_task(self._dispatch_outbound())
            task = self._spawn_channel_task(name, channel)
            await asyncio.sleep(0)
            results[name] = {
                "channel": name,
                "refreshed": True,
                "running": channel.is_running,
                "registered": True,
                "available": True,
                "task_done": task.done(),
                "error": "",
                "source": source,
            }
        return results

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
        for task in list(self._dispatch_retry_tasks):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._dispatch_retry_tasks.clear()

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
        metadata = dict(msg.metadata or {})
        return build_channel_session_key(
            msg.channel,
            str(msg.chat_id),
            thread_id=metadata.get("message_thread_id"),
            topic_id=metadata.get("topic_id") or metadata.get("root_id") or metadata.get("parent_id"),
        )

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

    def _channel_allows_progress_delivery(
        self,
        channel_name: str,
        *,
        tool_hint: bool = False,
        delivery_policy: dict[str, Any] | None = None,
    ) -> bool:
        if str((delivery_policy or {}).get("mode") or "").strip().lower() == "final_only":
            return False
        if channel_name == "webui":
            if tool_hint:
                return bool(self.config.channels.send_tool_hints)
            return bool(self.config.channels.send_progress)

        try:
            capability = get_channel_capability(channel_name)
        except KeyError:
            return False

        if capability.delivery_mode == "final_only":
            return False
        if capability.delivery_mode == "kickoff_progress_final":
            return not tool_hint
        if capability.delivery_mode in ("streaming", "pseudo_streaming"):
            return True
        return False

    @staticmethod
    def _dispatch_retry_count(msg: OutboundMessage) -> int:
        try:
            return max(0, int((msg.metadata or {}).get("_dispatch_retry_count") or 0))
        except (TypeError, ValueError):
            return 0

    def _channel_temporarily_unavailable_for_dispatch(
        self,
        channel_name: str,
        channel: BaseChannel | None,
    ) -> bool:
        lock = self._restart_locks.get(channel_name)
        if lock and lock.locked():
            return True
        if channel is None:
            status = self._channel_status.get(channel_name, {})
            return bool(status.get("configured_enabled")) and not bool(status.get("error"))
        task = self._channel_tasks.get(channel_name)
        running = getattr(channel, "is_running", True)
        return not bool(running) and bool(task and not task.done())

    def _schedule_outbound_retry(self, msg: OutboundMessage, *, reason: str) -> None:
        metadata = dict(msg.metadata or {})
        retry_count = self._dispatch_retry_count(msg) + 1
        metadata["_dispatch_retry_count"] = retry_count
        metadata["_dispatch_retry_reason"] = reason
        requeued = OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=msg.content,
            reply_to=msg.reply_to,
            media=list(msg.media or []),
            metadata=metadata,
        )
        delay = min(0.1 * retry_count, 1.0)

        async def _requeue_later() -> None:
            try:
                await asyncio.sleep(delay)
                await self.bus.publish_outbound(requeued)
            finally:
                self._dispatch_retry_tasks.discard(task)

        task = asyncio.create_task(_requeue_later())
        self._dispatch_retry_tasks.add(task)

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
                delivery_policy = get_delivery_policy(msg.metadata)
                apply_delivery_policy(msg)
                channel = self.channels.get(msg.channel)
                if self._channel_temporarily_unavailable_for_dispatch(msg.channel, channel):
                    retry_count = self._dispatch_retry_count(msg)
                    if retry_count < 20:
                        self._schedule_outbound_retry(msg, reason="channel_temporarily_unavailable")
                        continue
                    logger.error("Dropping outbound for {} after {} dispatch retries", msg.channel, retry_count)

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
                    if meta.get("_progress_kind"):
                        event["progress_kind"] = str(meta.get("_progress_kind"))
                    if meta.get("_chunk_first"):
                        event["first"] = True
                    if delivery_policy:
                        event["delivery_policy"] = dict(delivery_policy)
                    await self.activity_bus.broadcast(event)

                if msg.metadata.get("_progress"):
                    # Never leak internal reasoning or raw transport chunks to end-user channels.
                    if self._is_internal_message(msg):
                        continue
                    if not self._channel_allows_progress_delivery(
                        msg.channel,
                        tool_hint=bool(msg.metadata.get("_tool_hint")),
                        delivery_policy=delivery_policy,
                    ):
                        continue

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
