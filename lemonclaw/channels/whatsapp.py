"""WhatsApp channel implementation using Node.js bridge."""

import asyncio
import json
from typing import Any

from loguru import logger

from lemonclaw.bus.events import OutboundMessage
from lemonclaw.bus.queue import MessageBus
from lemonclaw.channels.base import BaseChannel
from lemonclaw.config.schema import WhatsAppConfig


class WhatsAppChannel(BaseChannel):
    """
    WhatsApp channel that connects to a Node.js bridge.
    
    The bridge uses @whiskeysockets/baileys to handle the WhatsApp Web protocol.
    Communication between Python and Node.js is via WebSocket.
    """
    
    name = "whatsapp"
    
    def __init__(self, config: WhatsAppConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: WhatsAppConfig = config
        self._ws = None
        self._connected = False
        self._mention_warned = False  # Only warn once when mention mode lacks enough bridge identity
        self._bot_identity_tokens: set[str] = set()

    @staticmethod
    def _jid_tokens(value: str) -> set[str]:
        raw = str(value or "").strip().lower()
        if not raw:
            return set()
        tokens = {raw}
        if "@" in raw:
            local, domain = raw.split("@", 1)
            tokens.add(local)
            if ":" in local:
                base_local = local.split(":", 1)[0]
                tokens.add(base_local)
                tokens.add(f"{base_local}@{domain}")
        else:
            tokens.add(raw.split(":", 1)[0])
        return {token for token in tokens if token}

    def _remember_bot_account(self, account: dict[str, Any] | None) -> None:
        if not isinstance(account, dict):
            return
        for key in ("id", "phone"):
            value = account.get(key)
            if isinstance(value, str):
                self._bot_identity_tokens.update(self._jid_tokens(value))

    def _group_message_mentions_bot(self, data: dict[str, Any], content: str) -> bool:
        mention_tokens: set[str] = set()
        for item in data.get("mentions") or []:
            if isinstance(item, str):
                mention_tokens.update(self._jid_tokens(item))
        if mention_tokens and self._bot_identity_tokens.intersection(mention_tokens):
            return True

        quoted_participant = data.get("quotedParticipant")
        if isinstance(quoted_participant, str):
            if self._bot_identity_tokens.intersection(self._jid_tokens(quoted_participant)):
                return True

        phone_tokens = {
            token for token in self._bot_identity_tokens
            if token.isdigit() and len(token) >= 5
        }
        text_lower = (content or "").lower()
        return any(f"@{token}" in text_lower for token in phone_tokens)
    
    async def start(self) -> None:
        """Start the WhatsApp channel by connecting to the bridge."""
        import websockets
        
        bridge_url = self.config.bridge_url
        
        logger.info("Connecting to WhatsApp bridge at {}...", bridge_url)
        
        self._running = True
        
        while self._running:
            try:
                async with websockets.connect(bridge_url) as ws:
                    self._ws = ws
                    # Send auth token if configured
                    if self.config.bridge_token:
                        await ws.send(json.dumps({"type": "auth", "token": self.config.bridge_token}))
                    self._connected = True
                    logger.info("Connected to WhatsApp bridge")
                    
                    # Listen for messages
                    async for message in ws:
                        try:
                            await self._handle_bridge_message(message)
                        except Exception as e:
                            logger.error("Error handling bridge message: {}", e)
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._connected = False
                self._ws = None
                logger.warning("WhatsApp bridge connection error: {}", e)
                
                if self._running:
                    logger.info("Reconnecting in 5 seconds...")
                    await asyncio.sleep(5)
    
    async def stop(self) -> None:
        """Stop the WhatsApp channel."""
        self._running = False
        self._connected = False
        
        if self._ws:
            await self._ws.close()
            self._ws = None
    
    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through WhatsApp."""
        if not self._ws or not self._connected:
            logger.warning("WhatsApp bridge not connected")
            return
        
        try:
            payload = {
                "type": "send",
                "to": msg.chat_id,
                "text": msg.content or ""
            }
            if msg.media:
                logger.warning("WhatsApp channel does not support media sending yet, {} file(s) dropped", len(msg.media))
            await self._ws.send(json.dumps(payload, ensure_ascii=False))
        except Exception as e:
            logger.error("Error sending WhatsApp message: {}", e)
    
    async def _handle_bridge_message(self, raw: str) -> None:
        """Handle a message from the bridge."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON from bridge: {}", raw[:100])
            return
        
        msg_type = data.get("type")
        
        if msg_type == "message":
            # Incoming message from WhatsApp
            # Deprecated by whatsapp: old phone number style typically: <phone>@s.whatspp.net
            pn = data.get("pn", "")
            # New LID sytle typically: 
            sender = data.get("sender", "")
            content = data.get("content", "")
            
            # Extract just the phone number or lid as chat_id
            user_id = pn if pn else sender
            sender_id = user_id.split("@")[0] if "@" in user_id else user_id
            logger.info("Sender {}", sender)
            
            # Handle voice transcription if it's a voice message
            if content == "[Voice Message]":
                logger.info("Voice message received from {}, but direct download from bridge is not yet supported.", sender_id)
                content = "[Voice Message: Transcription not available for WhatsApp yet]"
            
            is_group = bool(data.get("isGroup", False))
            # In group messages, `sender` is the group JID (e.g. xxx@g.us)
            group_jid = sender if is_group else None

            # Group policy gate
            if is_group:
                policy, require_mention = self._resolve_group_gate()
                bot_mentioned = False
                if require_mention:
                    if self._bot_identity_tokens:
                        bot_mentioned = self._group_message_mentions_bot(data, content)
                    else:
                        if not self._mention_warned:
                            logger.warning(
                                "WhatsApp group mention requirement needs bot account identity from bridge status. "
                                "Group messages will be ignored until the bridge reports the connected account or mention requirement is disabled.",
                            )
                            self._mention_warned = True
                        return
                if not self._group_policy_allows(
                    policy,
                    in_allowlist=group_jid in (self.config.group_allow_from or []),
                    require_mention=require_mention,
                    was_mentioned=bot_mentioned,
                ):
                    return

            await self._handle_message(
                sender_id=sender_id,
                chat_id=sender,  # Use full LID for replies
                content=content,
                metadata={
                    "message_id": data.get("id"),
                    "timestamp": data.get("timestamp"),
                    "is_group": is_group
                },
                pairing_policy=self.config.dm_policy if not is_group else None,
            )
        
        elif msg_type == "status":
            # Connection status update
            status = data.get("status")
            logger.info("WhatsApp status: {}", status)
            self._remember_bot_account(data.get("account"))
            
            if status == "connected":
                self._connected = True
            elif status == "disconnected":
                self._connected = False
        
        elif msg_type == "qr":
            # QR code for authentication
            logger.info("Scan QR code in the bridge terminal to connect WhatsApp")
        
        elif msg_type == "error":
            logger.error("WhatsApp bridge error: {}", data.get('error'))
