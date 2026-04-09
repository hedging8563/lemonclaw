"""Weixin channel implementation using the local Node.js bridge."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from loguru import logger

from lemonclaw.bus.events import OutboundMessage
from lemonclaw.bus.queue import MessageBus
from lemonclaw.channels.base import BaseChannel
from lemonclaw.channels.inbound_dedupe import InboundDedupeCache
from lemonclaw.channels.session_keys import build_channel_session_key
from lemonclaw.channels.weixin_bridge_runtime import (
    WeixinBridgeError,
    ensure_weixin_bridge_running,
    poll_weixin_updates,
    send_weixin_text,
)
from lemonclaw.config.loader import get_data_dir
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
        self._cursor = self._load_cursor()
        self._ingress_dedupe = InboundDedupeCache(ttl_seconds=300, max_entries=2000)

    @staticmethod
    def _cursor_state_path() -> Path:
        return get_data_dir() / "weixin-consumer-cursor.json"

    def _load_cursor(self) -> int:
        path = self._cursor_state_path()
        try:
            data = json.loads(path.read_text())
        except Exception:
            return 0
        return max(0, int(data.get("cursor") or 0))

    def _save_cursor(self, cursor: int) -> None:
        path = self._cursor_state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"cursor": max(0, int(cursor))}))
        tmp.replace(path)

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
                    ack_cursor=self._cursor,
                    limit=50,
                    wait_timeout=25.0,
                )
                next_cursor = payload.get("nextCursor")
                candidate_cursor = self._cursor
                if isinstance(next_cursor, int) and next_cursor >= self._cursor:
                    candidate_cursor = next_cursor

                for event in payload.get("events") or []:
                    if isinstance(event, dict):
                        await self._handle_bridge_event(event)
                if candidate_cursor != self._cursor:
                    self._cursor = candidate_cursor
                    self._save_cursor(self._cursor)
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
            logger.info("Weixin media send via bridge: {} file(s)", len(msg.media))

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
            raise

    async def _handle_bridge_event(self, event: dict[str, Any]) -> None:
        if event.get("type") != "message":
            return

        account_id = str(event.get("accountId") or "").strip()
        peer_id = str(event.get("peerId") or event.get("senderId") or "").strip()
        chat_id = str(event.get("chatId") or "").strip() or f"{account_id}|{peer_id}"
        content = str(event.get("content") or "")
        event_id = str(event.get("id") or "").strip()
        if event_id and not self._ingress_dedupe.remember(f"event:{event_id}"):
            logger.debug("Weixin duplicate event id={}, skipping", event_id)
            return
        trigger_metadata: dict[str, Any] = {}

        if self._trigger_runtime:
            trigger = self._trigger_runtime.record_trigger(
                source="bridge.weixin",
                kind="message.dm",
                payload_summary=content[:200],
                session_key=build_channel_session_key(
                    self.name,
                    peer_id,
                    account_id=account_id,
                    preserve_empty_account_slot=True,
                ),
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
            session_key=build_channel_session_key(
                self.name,
                peer_id,
                account_id=account_id,
                preserve_empty_account_slot=True,
            ),
        )
