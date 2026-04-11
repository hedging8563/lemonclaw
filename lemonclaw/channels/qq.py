"""QQ channel implementation using botpy SDK."""

import asyncio
import mimetypes
import re
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from loguru import logger

from lemonclaw.bus.events import OutboundMessage
from lemonclaw.bus.queue import MessageBus
from lemonclaw.channels.base import BaseChannel
from lemonclaw.channels.inbound_dedupe import InboundDedupeCache
from lemonclaw.config.schema import QQConfig

try:
    import botpy
    from botpy.message import C2CMessage, GroupMessage

    QQ_AVAILABLE = True
except ImportError:
    QQ_AVAILABLE = False
    botpy = None
    C2CMessage = None
    GroupMessage = None

if TYPE_CHECKING:
    from botpy.message import C2CMessage, GroupMessage

_QQ_MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024


def _make_bot_class(channel: "QQChannel") -> "type[botpy.Client]":
    """Create a botpy Client subclass bound to the given channel."""
    intents = botpy.Intents(public_messages=True, direct_message=True)

    class _Bot(botpy.Client):
        def __init__(self):
            super().__init__(intents=intents)

        async def on_ready(self):
            logger.info("QQ bot ready: {}", self.robot.name)

        async def on_c2c_message_create(self, message: "C2CMessage"):
            await channel._on_message(message)

        async def on_direct_message_create(self, message):
            await channel._on_message(message)

        async def on_group_at_message_create(self, message: "GroupMessage"):
            await channel._on_message(message)

    return _Bot


class QQChannel(BaseChannel):
    """QQ channel using botpy SDK with WebSocket connection."""

    name = "qq"

    def __init__(self, config: QQConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: QQConfig = config
        self._client: "botpy.Client | None" = None
        self._http: httpx.AsyncClient | None = None
        self._ingress_dedupe = InboundDedupeCache(ttl_seconds=300, max_entries=2000)

    async def start(self) -> None:
        """Start the QQ bot."""
        if not QQ_AVAILABLE:
            logger.error("QQ SDK not installed. Run: pip install qq-botpy")
            return

        if not self.config.app_id or not self.config.secret:
            logger.error("QQ app_id and secret not configured")
            return

        self._running = True
        BotClass = _make_bot_class(self)
        self._client = BotClass()
        self._http = httpx.AsyncClient(timeout=30.0, follow_redirects=True)

        logger.info("QQ bot started (C2C + group @ message)")
        if self.config.group_policy == "open" and not self.config.group_require_mention:
            logger.warning(
                "QQ SDK only delivers group @bot messages. "
                "group_policy=open with require_mention=false will still only receive explicit @ mentions."
            )
        await self._run_bot()

    async def _run_bot(self) -> None:
        """Run the bot connection with auto-reconnect."""
        while self._running:
            try:
                await self._client.start(appid=self.config.app_id, secret=self.config.secret)
            except Exception as e:
                logger.warning("QQ bot error: {}", e)
            if self._running:
                logger.info("Reconnecting QQ bot in 5 seconds...")
                await asyncio.sleep(5)

    async def stop(self) -> None:
        """Stop the QQ bot."""
        self._running = False
        if self._http:
            await self._http.aclose()
            self._http = None
        if self._client:
            try:
                await self._client.close()
            except Exception as e:
                logger.warning("QQ bot close error: {}", e)
        logger.info("QQ bot stopped")

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through QQ."""
        if not self._client:
            logger.warning("QQ client not initialized")
            return
        try:
            qq_meta = (msg.metadata or {}).get("qq") if isinstance(msg.metadata, dict) else {}
            is_group = bool((qq_meta or {}).get("is_group"))
            reply_to = str(msg.reply_to or (qq_meta or {}).get("reply_to") or "")
            if is_group:
                await self._client.api.post_group_message(
                    group_openid=msg.chat_id,
                    msg_type=0,
                    content=msg.content,
                    msg_id=reply_to or None,
                )
            else:
                await self._client.api.post_c2c_message(
                    openid=msg.chat_id,
                    msg_type=0,
                    content=msg.content,
                    msg_id=reply_to or None,
                )
        except Exception as e:
            logger.error("Error sending QQ message: {}", e)

    async def _on_message(self, data: "C2CMessage | GroupMessage") -> None:
        """Handle incoming message from QQ."""
        try:
            # Dedup by message ID
            if not self._ingress_dedupe.remember(f"message:{data.id}"):
                return

            author = data.author
            is_group = hasattr(data, "group_openid") and bool(getattr(data, "group_openid", None))
            user_id = str(
                getattr(author, 'id', None)
                or getattr(author, 'user_openid', None)
                or getattr(author, 'member_openid', 'unknown')
            )
            content = (data.content or "").strip()
            content_parts = [content] if content else []
            reply_to = str(getattr(getattr(data, "message_reference", None), "message_id", "") or "")

            chat_id = str(getattr(data, "group_openid", "") or user_id)
            if is_group:
                policy, require_mention = self._resolve_group_gate()
                if not self._group_policy_allows(
                    policy,
                    in_allowlist=chat_id in (self.config.group_allow_from or []),
                    require_mention=require_mention,
                    was_mentioned=True,  # QQ group event is already an explicit @bot event
                ):
                    return

            base_metadata = {
                "message_id": data.id,
                "attachments": [
                    {
                        "id": str(getattr(item, "id", "") or ""),
                        "filename": str(getattr(item, "filename", "") or ""),
                        "content_type": str(getattr(item, "content_type", "") or ""),
                        "size": int(getattr(item, "size", 0) or 0),
                        "url": str(getattr(item, "url", "") or ""),
                    }
                    for item in list(getattr(data, "attachments", []) or [])
                ],
                "reply_to": reply_to or None,
                "qq": {
                    "is_group": is_group,
                    "group_openid": chat_id if is_group else "",
                    "reply_to": reply_to or None,
                },
            }
            pairing_policy = self.config.dm_policy if hasattr(self.config, "dm_policy") and not is_group else None
            if not await self._preflight_direct_inbound_access(
                sender_id=user_id,
                chat_id=chat_id,
                content=content,
                pairing_policy=pairing_policy,
                is_group_message=is_group,
            ):
                return

            media_paths: list[str] = []
            for attachment in list(getattr(data, "attachments", []) or []):
                marker, file_path = await self._download_attachment(attachment)
                if marker:
                    content_parts.append(marker)
                if file_path:
                    media_paths.append(file_path)
            if not content_parts and not media_paths:
                return
            content = "\n".join(part for part in content_parts if part).strip()

            await self._handle_message(
                sender_id=user_id,
                chat_id=chat_id,
                content=content,
                media=media_paths or None,
                metadata=base_metadata,
                pairing_policy=pairing_policy,
                pairing_checked=not is_group,
            )
        except Exception:
            logger.exception("Error handling QQ message")

    async def _download_attachment(self, attachment: object) -> tuple[str | None, str | None]:
        filename = str(getattr(attachment, "filename", "") or "attachment")
        url = str(getattr(attachment, "url", "") or "")
        size = int(getattr(attachment, "size", 0) or 0)
        content_type = str(getattr(attachment, "content_type", "") or "")
        attachment_id = str(getattr(attachment, "id", "") or "file")

        if size and size > _QQ_MAX_ATTACHMENT_BYTES:
            return f"[attachment: {filename} - too large]", None
        if not url or not self._http:
            return f"[attachment: {filename} - download failed]", None

        media_dir = Path.home() / ".lemonclaw" / "media" / "qq"
        media_dir.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r"[^\w\s.\-\u4e00-\u9fff]", "_", filename).strip() or "attachment"
        suffix = Path(safe_name).suffix
        if not suffix and content_type:
            suffix = mimetypes.guess_extension(content_type.split(";", 1)[0].strip()) or ""
            safe_name = f"{safe_name}{suffix}"
        file_path = media_dir / f"{attachment_id}_{safe_name}"

        try:
            response = await self._http.get(url)
            response.raise_for_status()
            file_path.write_bytes(response.content)
            return f"[attachment: {file_path}]", str(file_path)
        except Exception as exc:
            logger.warning("Failed to download QQ attachment {}: {}", filename, exc)
            return f"[attachment: {filename} - download failed]", None
