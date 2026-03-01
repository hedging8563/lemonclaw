"""WeCom (企业微信) channel implementation using webhook callback + HTTP API.

Architecture:
- Inbound: Gateway registers GET+POST /webhook/wecom routes.
  GET handles URL verification (echostr). POST receives encrypted XML messages.
- Outbound: HTTP POST to qyapi.weixin.qq.com API with auto-refreshing access_token.

Requires: pycryptodome for AES message encryption/decryption.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac as hmac_mod
import os
import struct
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx
from loguru import logger

from lemonclaw.bus.events import OutboundMessage
from lemonclaw.bus.queue import MessageBus
from lemonclaw.channels.base import BaseChannel
from lemonclaw.config.schema import WeComConfig

try:
    from Crypto.Cipher import AES

    CRYPTO_AVAILABLE = True
except ImportError:
    AES = None  # type: ignore[assignment]
    CRYPTO_AVAILABLE = False

WECOM_API_BASE = "https://qyapi.weixin.qq.com/cgi-bin"


# ---------------------------------------------------------------------------
# WeCom message crypto (AES-256-CBC with PKCS#7 padding)
# ---------------------------------------------------------------------------


class WeComCrypto:
    """AES encryption/decryption for WeCom callback messages.

    EncodingAESKey is a 43-char base64 string that decodes to a 32-byte AES key.
    Messages use AES-256-CBC with the first 16 bytes of the key as IV.
    Note: The fixed IV is mandated by the WeCom protocol specification.
    """

    def __init__(self, encoding_aes_key: str, corp_id: str):
        self.corp_id = corp_id
        # EncodingAESKey is base64 (no padding) → 32 bytes
        self.aes_key = base64.b64decode(encoding_aes_key + "=")
        self.iv = self.aes_key[:16]

    def decrypt(self, encrypted: str) -> str:
        """Decrypt a base64-encoded encrypted message and verify corp_id."""
        if not CRYPTO_AVAILABLE:
            raise RuntimeError("pycryptodome is required for WeCom message decryption")

        cipher = AES.new(self.aes_key, AES.MODE_CBC, self.iv)
        decrypted = cipher.decrypt(base64.b64decode(encrypted))

        # Validate and remove PKCS#7 padding
        if len(decrypted) == 0:
            raise ValueError("Decrypted message is empty")
        pad_len = decrypted[-1]
        if pad_len < 1 or pad_len > 32:
            raise ValueError(f"Invalid PKCS#7 padding length: {pad_len}")
        # Verify all padding bytes are consistent
        if decrypted[-pad_len:] != bytes([pad_len]) * pad_len:
            raise ValueError("Invalid PKCS#7 padding bytes")
        content = decrypted[:-pad_len]

        # Format: 16 bytes random + 4 bytes msg_len (network order) + msg + corp_id
        if len(content) < 20:
            raise ValueError("Decrypted content too short")
        msg_len = struct.unpack("!I", content[16:20])[0]
        if 20 + msg_len > len(content):
            raise ValueError(f"Message length {msg_len} exceeds content size {len(content) - 20}")
        msg = content[20 : 20 + msg_len].decode("utf-8")
        from_corp_id = content[20 + msg_len :].decode("utf-8")

        if from_corp_id != self.corp_id:
            raise ValueError(f"corp_id mismatch: expected {self.corp_id}, got {from_corp_id}")

        return msg

    def encrypt(self, plaintext: str) -> str:
        """Encrypt a plaintext message for WeCom."""
        if not CRYPTO_AVAILABLE:
            raise RuntimeError("pycryptodome is required for WeCom message encryption")

        text_bytes = plaintext.encode("utf-8")
        corp_id_bytes = self.corp_id.encode("utf-8")

        # 16 bytes random + 4 bytes msg_len + msg + corp_id
        random_bytes = os.urandom(16)
        msg_len = struct.pack("!I", len(text_bytes))
        content = random_bytes + msg_len + text_bytes + corp_id_bytes

        # PKCS#7 padding to AES block size (32 bytes for WeCom)
        block_size = 32
        pad_len = block_size - (len(content) % block_size)
        content += bytes([pad_len]) * pad_len

        cipher = AES.new(self.aes_key, AES.MODE_CBC, self.iv)
        encrypted = cipher.encrypt(content)
        return base64.b64encode(encrypted).decode("utf-8")


def verify_signature(token: str, timestamp: str, nonce: str, encrypt: str = "") -> str:
    """Calculate WeCom callback signature for verification."""
    parts = sorted([token, timestamp, nonce, encrypt])
    return hashlib.sha1("".join(parts).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# XML helpers
# ---------------------------------------------------------------------------


def parse_xml(xml_text: str) -> dict[str, str]:
    """Parse WeCom callback XML into a flat dict."""
    root = ET.fromstring(xml_text)
    return {child.tag: (child.text or "") for child in root}


def build_reply_xml(encrypt: str, signature: str, timestamp: str, nonce: str) -> str:
    """Build encrypted reply XML for passive response."""
    return (
        "<xml>"
        f"<Encrypt><![CDATA[{encrypt}]]></Encrypt>"
        f"<MsgSignature><![CDATA[{signature}]]></MsgSignature>"
        f"<TimeStamp>{timestamp}</TimeStamp>"
        f"<Nonce><![CDATA[{nonce}]]></Nonce>"
        "</xml>"
    )


# ---------------------------------------------------------------------------
# Channel
# ---------------------------------------------------------------------------


class WeComChannel(BaseChannel):
    """WeCom channel using webhook callback for receiving + HTTP API for sending.

    Inbound flow:
    1. Gateway receives POST /webhook/wecom with encrypted XML
    2. Verify signature → decrypt → parse XML → extract MsgType/Content
    3. Forward to MessageBus via _handle_message()

    Outbound flow:
    1. Get/refresh access_token (cached, 2h TTL)
    2. POST message to WeCom API (text or markdown)
    """

    name = "wecom"

    def __init__(self, config: WeComConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: WeComConfig = config
        self._http: httpx.AsyncClient | None = None
        self._crypto: WeComCrypto | None = None

        # Access token management
        self._access_token: str | None = None
        self._token_expiry: float = 0
        self._token_lock = asyncio.Lock()

    async def start(self) -> None:
        """Start the WeCom channel.

        Unlike Telegram/Feishu which poll or use WebSocket, WeCom relies on
        webhook callbacks. The gateway server handles HTTP routing.
        This method just initializes the HTTP client and crypto, then waits.
        """
        if not CRYPTO_AVAILABLE:
            logger.error("pycryptodome not installed. Run: pip install pycryptodome")
            return

        if not self.config.corp_id or not self.config.secret:
            logger.error("WeCom corp_id and secret not configured")
            return

        if not self.config.encoding_aes_key:
            logger.error("WeCom encoding_aes_key not configured (required for message decryption)")
            return

        self._running = True
        self._http = httpx.AsyncClient(timeout=30.0)
        self._crypto = WeComCrypto(self.config.encoding_aes_key, self.config.corp_id)

        logger.info("WeCom channel started (webhook mode, waiting for callbacks)")
        logger.info(
            "Configure webhook URL in WeCom admin: https://<your-domain>/webhook/wecom"
        )

        # Pre-fetch access_token to validate credentials early
        token = await self._get_access_token()
        if token:
            logger.info("WeCom access_token acquired successfully")
        else:
            logger.warning("Failed to acquire WeCom access_token — sending will fail")

        # Keep running until stopped (webhook callbacks are handled by gateway)
        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        """Stop the WeCom channel."""
        self._running = False
        if self._http:
            await self._http.aclose()
            self._http = None
        logger.info("WeCom channel stopped")

    # ---- Webhook handlers (called by gateway) --------------------------------

    async def handle_verify(self, params: dict[str, str]) -> str | None:
        """Handle GET /webhook/wecom — WeCom URL verification.

        WeCom sends: msg_signature, timestamp, nonce, echostr
        We verify signature, decrypt echostr, and return plaintext.
        """
        msg_signature = params.get("msg_signature", "")
        timestamp = params.get("timestamp", "")
        nonce = params.get("nonce", "")
        echostr = params.get("echostr", "")

        if not all([msg_signature, timestamp, nonce, echostr]):
            logger.warning("WeCom verify: missing parameters")
            return None

        # Verify signature
        expected = verify_signature(self.config.token, timestamp, nonce, echostr)
        if not hmac_mod.compare_digest(expected, msg_signature):
            logger.warning("WeCom verify: signature mismatch")
            return None

        # Decrypt echostr
        if not self._crypto:
            logger.error("WeCom crypto not initialized")
            return None

        try:
            return self._crypto.decrypt(echostr)
        except Exception as e:
            logger.error("WeCom verify: decrypt failed: {}", e)
            return None

    async def handle_callback(self, params: dict[str, str], body: str) -> str | None:
        """Handle POST /webhook/wecom — incoming message callback.

        Returns encrypted XML reply (passive reply) or None.
        """
        msg_signature = params.get("msg_signature", "")
        timestamp = params.get("timestamp", "")
        nonce = params.get("nonce", "")

        # Parse outer XML to get Encrypt field
        try:
            xml_data = parse_xml(body)
        except ET.ParseError as e:
            logger.error("WeCom callback: XML parse error: {}", e)
            return None

        encrypt = xml_data.get("Encrypt", "")
        if not encrypt:
            logger.warning("WeCom callback: missing Encrypt field")
            return None

        # Verify signature
        expected = verify_signature(self.config.token, timestamp, nonce, encrypt)
        if not hmac_mod.compare_digest(expected, msg_signature):
            logger.warning("WeCom callback: signature mismatch")
            return None

        # Decrypt message
        if not self._crypto:
            logger.error("WeCom crypto not initialized")
            return None

        try:
            decrypted_xml = self._crypto.decrypt(encrypt)
        except Exception as e:
            logger.error("WeCom callback: decrypt failed: {}", e)
            return None

        # Parse decrypted XML
        try:
            msg = parse_xml(decrypted_xml)
        except ET.ParseError as e:
            logger.error("WeCom callback: inner XML parse error: {}", e)
            return None

        # Process message
        await self._process_message(msg)

        # Return "success" response (WeCom expects a response within 5 seconds)
        return "success"

    async def _process_message(self, msg: dict[str, str]) -> None:
        """Process a decrypted WeCom message."""
        msg_type = msg.get("MsgType", "")
        from_user = msg.get("FromUserName", "")

        if not from_user:
            return

        content = ""
        media: list[str] = []

        if msg_type == "text":
            content = msg.get("Content", "").strip()
        elif msg_type == "image":
            pic_url = msg.get("PicUrl", "")
            if pic_url:
                # Download image to local disk
                file_path = await self._download_media(pic_url, "image")
                if file_path:
                    media.append(file_path)
                content = "[image]"
            else:
                content = "[image: no URL]"
        elif msg_type == "voice":
            content = msg.get("Recognition", "[voice]")  # Speech recognition result if enabled
        elif msg_type == "video":
            content = "[video]"
        elif msg_type == "location":
            label = msg.get("Label", "")
            lat = msg.get("Location_X", "")
            lng = msg.get("Location_Y", "")
            content = f"[location: {label} ({lat}, {lng})]" if label else f"[location: ({lat}, {lng})]"
        elif msg_type == "link":
            title = msg.get("Title", "")
            desc = msg.get("Description", "")
            url = msg.get("Url", "")
            content = f"[link: {title}]\n{desc}\n{url}".strip()
        elif msg_type == "event":
            # Events like subscribe, click, etc. — ignore for now
            event_type = msg.get("Event", "")
            logger.debug("WeCom event: {} from {}", event_type, from_user)
            return
        else:
            content = f"[{msg_type}]"

        if not content and not media:
            return

        await self._handle_message(
            sender_id=from_user,
            chat_id=from_user,  # WeCom uses UserId for both
            content=content,
            media=media if media else None,
            metadata={
                "msg_type": msg_type,
                "msg_id": msg.get("MsgId", ""),
                "platform": "wecom",
            },
        )

    # ---- Outbound: send messages via HTTP API --------------------------------

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through WeCom API."""
        token = await self._get_access_token()
        if not token:
            logger.error("WeCom: cannot send, no access_token")
            return

        content = (msg.content or "").strip()
        if not content and not msg.media:
            return

        # Send media files first (as image messages if applicable)
        for file_path in msg.media:
            await self._send_media(token, msg.chat_id, file_path)

        # Send text content
        if content:
            await self._send_text(token, msg.chat_id, content)

    # WeCom text message limit: 2048 bytes
    TEXT_MAX_BYTES = 2048

    async def _send_text(self, token: str, user_id: str, content: str) -> None:
        """Send a text message to a WeCom user.

        WeCom markdown support is limited (no code blocks, tables, etc.),
        so we send as plain text for reliability.
        Messages exceeding 2048 bytes are split into multiple sends.
        """
        chunks = self._split_text(content)
        for chunk in chunks:
            await self._send_text_chunk(token, user_id, chunk)

    def _split_text(self, content: str) -> list[str]:
        """Split text into chunks that fit within WeCom's 2048-byte limit."""
        encoded = content.encode("utf-8")
        if len(encoded) <= self.TEXT_MAX_BYTES:
            return [content]

        chunks: list[str] = []
        remaining = content
        while remaining:
            encoded = remaining.encode("utf-8")
            if len(encoded) <= self.TEXT_MAX_BYTES:
                chunks.append(remaining)
                break
            # Estimate cut point proportionally (safe for multi-byte chars)
            cut = len(remaining)
            while len(remaining[:cut].encode("utf-8")) > self.TEXT_MAX_BYTES:
                cut = max(1, cut * self.TEXT_MAX_BYTES // len(remaining[:cut].encode("utf-8")))
            # Prefer breaking at newline
            nl = remaining.rfind("\n", 0, cut)
            if nl > cut // 2:
                cut = nl + 1
            chunks.append(remaining[:cut])
            remaining = remaining[cut:]
        return chunks

    async def _send_text_chunk(self, token: str, user_id: str, content: str) -> None:
        """Send a single text chunk to a WeCom user."""
        url = f"{WECOM_API_BASE}/message/send?access_token={token}"
        data = {
            "touser": user_id,
            "msgtype": "text",
            "agentid": self.config.agent_id,
            "text": {"content": content},
        }

        if not self._http:
            return

        try:
            resp = await self._http.post(url, json=data)
            result = resp.json()
            if result.get("errcode", 0) != 0:
                logger.error("WeCom send failed: {}", result.get("errmsg", "unknown"))
            else:
                logger.debug("WeCom message sent to {}", user_id)
        except Exception as e:
            logger.error("WeCom send error: {}", e)

    async def _send_media(self, token: str, user_id: str, file_path: str) -> None:
        """Upload and send a media file (image) to a WeCom user."""
        if not os.path.isfile(file_path):
            logger.warning("WeCom: media file not found: {}", file_path)
            return

        media_id = await self._upload_media(token, file_path)
        if not media_id:
            return

        url = f"{WECOM_API_BASE}/message/send?access_token={token}"
        data = {
            "touser": user_id,
            "msgtype": "image",
            "agentid": self.config.agent_id,
            "image": {"media_id": media_id},
        }

        if not self._http:
            return

        try:
            resp = await self._http.post(url, json=data)
            result = resp.json()
            if result.get("errcode", 0) != 0:
                logger.error("WeCom send media failed: {}", result.get("errmsg", "unknown"))
        except Exception as e:
            logger.error("WeCom send media error: {}", e)

    async def _upload_media(self, token: str, file_path: str) -> str | None:
        """Upload a temporary media file to WeCom and return media_id."""
        url = f"{WECOM_API_BASE}/media/upload?access_token={token}&type=image"

        if not self._http:
            return None

        try:
            filename = os.path.basename(file_path)
            with open(file_path, "rb") as f:
                files = {"media": (filename, f, "application/octet-stream")}
                resp = await self._http.post(url, files=files)
            result = resp.json()
            if result.get("errcode", 0) != 0:
                logger.error("WeCom upload failed: {}", result.get("errmsg", "unknown"))
                return None
            return result.get("media_id")
        except Exception as e:
            logger.error("WeCom upload error: {}", e)
            return None

    # ---- Access token management ---------------------------------------------

    async def _get_access_token(self) -> str | None:
        """Get or refresh the WeCom access_token (2h TTL, cached, concurrency-safe)."""
        # Fast path: token still valid
        if self._access_token and time.time() < self._token_expiry:
            return self._access_token

        async with self._token_lock:
            # Double-check after acquiring lock (another coroutine may have refreshed)
            if self._access_token and time.time() < self._token_expiry:
                return self._access_token

            url = f"{WECOM_API_BASE}/gettoken"
            params = {"corpid": self.config.corp_id, "corpsecret": self.config.secret}

            if not self._http:
                return None

            try:
                resp = await self._http.get(url, params=params)
                result = resp.json()
                if result.get("errcode", 0) != 0:
                    logger.error("WeCom gettoken failed: {}", result.get("errmsg", "unknown"))
                    return None

                self._access_token = result["access_token"]
                # Expire 60s early for safety margin
                self._token_expiry = time.time() + result.get("expires_in", 7200) - 60
                return self._access_token
            except Exception as e:
                logger.error("WeCom gettoken error: {}", e)
                return None

    # ---- Media download helper -----------------------------------------------

    async def _download_media(self, url: str, media_type: str) -> str | None:
        """Download media from URL to local disk."""
        if not self._http:
            return None

        try:
            media_dir = Path.home() / ".lemonclaw" / "media"
            media_dir.mkdir(parents=True, exist_ok=True)

            resp = await self._http.get(url)
            if resp.status_code != 200:
                logger.warning("WeCom media download failed: HTTP {}", resp.status_code)
                return None

            # Determine extension from content-type
            ct = resp.headers.get("content-type", "")
            ext = ".jpg"
            if "png" in ct:
                ext = ".png"
            elif "gif" in ct:
                ext = ".gif"
            elif "webp" in ct:
                ext = ".webp"

            filename = f"wecom_{int(time.time())}_{os.urandom(4).hex()}{ext}"
            file_path = media_dir / filename
            file_path.write_bytes(resp.content)
            logger.debug("Downloaded WeCom {} to {}", media_type, file_path)
            return str(file_path)
        except Exception as e:
            logger.error("WeCom media download error: {}", e)
            return None
