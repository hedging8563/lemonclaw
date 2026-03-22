"""Weixin channel implementation using the local Node.js bridge."""

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger

from lemonclaw.bus.events import OutboundMessage
from lemonclaw.bus.queue import MessageBus
from lemonclaw.channels.base import BaseChannel
from lemonclaw.channels.weixin_bridge_runtime import (
    WeixinBridgeError,
    ensure_weixin_bridge_running,
    poll_weixin_updates,
    send_weixin_text,
)
from lemonclaw.config.schema import WeixinConfig
from lemonclaw.triggers import TriggerRuntime, build_trigger_metadata


def _split_chat_id(chat_id: str) -> tuple[str, str]:
    raw = str(chat_id or "")
    if "|" not in raw:
        return "", raw
    account_id, peer_id = raw.split("|", 1)
    return account_id.strip(), peer_id.strip()


class WeixinChannel(BaseChannel):
    """Weixin direct-message channel backed by a local bridge process."""

    name = "weixin"

    def __init__(self, config: WeixinConfig, bus: MessageBus, trigger_runtime: TriggerRuntime | None = None):
        super().__init__(config, bus)
        self.config: WeixinConfig = config
        self._trigger_runtime = trigger_runtime
        self._cursor = 0

    async def start(self) -> None:
        self._running = True
        while self._running:
            try:
                state = await asyncio.to_thread(ensure_weixin_bridge_running, self.config, wait_timeout=10.0)
                accounts = state.get("accounts") if isinstance(state, dict) else []
                if not isinstance(accounts, list) or len(accounts) == 0:
                    await asyncio.sleep(3)
                    continue

                payload = await asyncio.to_thread(
                    poll_weixin_updates,
                    self.config,
                    cursor=self._cursor,
                    limit=50,
                    wait_timeout=25.0,
                )
                next_cursor = payload.get("nextCursor")
                if isinstance(next_cursor, int) and next_cursor >= self._cursor:
                    self._cursor = next_cursor

                for event in payload.get("events") or []:
                    if isinstance(event, dict):
                        await self._handle_bridge_event(event)
            except asyncio.CancelledError:
                break
            except WeixinBridgeError as exc:
                logger.warning("Weixin bridge error: {}", exc)
                await asyncio.sleep(5)
            except Exception as exc:  # pragma: no cover - runtime safety
                logger.exception("Weixin channel loop failed: {}", exc)
                await asyncio.sleep(5)

    async def stop(self) -> None:
        self._running = False

    async def send(self, msg: OutboundMessage) -> None:
        account_id = str((msg.metadata or {}).get("account_id") or "").strip()
        peer_id = str((msg.metadata or {}).get("peer_id") or "").strip()
        context_token = str((msg.metadata or {}).get("context_token") or "").strip() or None
        if not account_id or not peer_id:
            parsed_account_id, parsed_peer_id = _split_chat_id(msg.chat_id)
            account_id = account_id or parsed_account_id
            peer_id = peer_id or parsed_peer_id

        if not account_id or not peer_id:
            logger.warning("Weixin send skipped: missing account_id/peer_id for chat_id={}", msg.chat_id)
            return

        if msg.media:
            logger.warning("Weixin media sending is not wired yet; {} file(s) dropped", len(msg.media))

        try:
            await asyncio.to_thread(
                send_weixin_text,
                self.config,
                account_id=account_id,
                to=peer_id,
                text=msg.content or "",
                context_token=context_token,
                media_paths=list(msg.media or []),
            )
        except Exception as exc:
            logger.error("Error sending Weixin message: {}", exc)

    async def _handle_bridge_event(self, event: dict[str, Any]) -> None:
        if event.get("type") != "message":
            return

        account_id = str(event.get("accountId") or "").strip()
        peer_id = str(event.get("peerId") or event.get("senderId") or "").strip()
        chat_id = str(event.get("chatId") or "").strip() or f"{account_id}|{peer_id}"
        content = str(event.get("content") or "")
        trigger_metadata: dict[str, Any] = {}

        if self._trigger_runtime:
            trigger = self._trigger_runtime.record_trigger(
                source="bridge.weixin",
                kind="message.dm",
                payload_summary=content[:200],
                session_key=f"{self.name}:{account_id}:{peer_id}",
                channel=self.name,
                chat_id=chat_id,
                metadata={
                    "account_id": account_id,
                    "peer_id": peer_id,
                    "message_id": str(event.get("messageId") or ""),
                },
            )
            trigger_metadata = build_trigger_metadata(trigger)

        await self._handle_message(
            sender_id=peer_id,
            chat_id=chat_id,
            content=content,
            media=list(((event.get("metadata") or {}) if isinstance(event.get("metadata"), dict) else {}).get("mediaPaths") or []),
            metadata={
                **trigger_metadata,
                "account_id": account_id,
                "peer_id": peer_id,
                "context_token": event.get("contextToken"),
                "message_id": event.get("messageId"),
                "timestamp": event.get("timestamp"),
                "item_types": ((event.get("metadata") or {}) if isinstance(event.get("metadata"), dict) else {}).get("itemTypes") or [],
            },
            session_key=f"{self.name}:{account_id}:{peer_id}",
        )
