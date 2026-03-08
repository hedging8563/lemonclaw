"""Telegram channel implementation using python-telegram-bot."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from loguru import logger
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update, ReplyParameters
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.request import HTTPXRequest

from lemonclaw.bus.events import OutboundMessage
from lemonclaw.bus.queue import MessageBus
from lemonclaw.channels.base import BaseChannel
from lemonclaw.config.schema import TelegramConfig

# Telegram Bot API file size limit (50MB)
_TG_MAX_FILE_BYTES = 50 * 1024 * 1024
# Target size per split segment (45MB, leave headroom)
_TG_SPLIT_TARGET_BYTES = 45 * 1024 * 1024


@dataclass
class _StreamState:
    """Per-chat streaming state for editMessageText approach."""
    message_id: int = 0       # 0 = no message sent yet
    text: str = ""
    last_sent_at: float = 0.0
    last_sent_text: str = ""


_STREAM_MIN_INTERVAL = 0.5   # seconds between edits (Telegram rate limit friendly)
_STREAM_MIN_CHARS = 20       # minimum new chars before editing


def _markdown_to_telegram_html(text: str) -> str:
    """
    Convert markdown to Telegram-safe HTML.
    """
    if not text:
        return ""
    
    # 1. Extract and protect code blocks (preserve content from other processing)
    code_blocks: list[str] = []
    def save_code_block(m: re.Match) -> str:
        code_blocks.append(m.group(1))
        return f"\x00CB{len(code_blocks) - 1}\x00"
    
    text = re.sub(r'```[\w]*\n?([\s\S]*?)```', save_code_block, text)
    
    # 2. Extract and protect inline code
    inline_codes: list[str] = []
    def save_inline_code(m: re.Match) -> str:
        inline_codes.append(m.group(1))
        return f"\x00IC{len(inline_codes) - 1}\x00"
    
    text = re.sub(r'`([^`]+)`', save_inline_code, text)

    # 3. Extract and protect markdown links (before HTML escaping)
    links: list[tuple[str, str]] = []
    def save_link(m: re.Match) -> str:
        links.append((m.group(1), m.group(2)))
        return f"\x00LK{len(links) - 1}\x00"

    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', save_link, text)

    # 4. Headers # Title -> just the title text
    text = re.sub(r'^#{1,6}\s+(.+)$', r'\1', text, flags=re.MULTILINE)

    # 5. Blockquotes > text -> just the text (before HTML escaping)
    text = re.sub(r'^>\s*(.*)$', r'\1', text, flags=re.MULTILINE)

    # 6. Escape HTML special characters
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # 7. Restore links with HTML tags (URL stays unescaped)
    for i, (link_text, url) in enumerate(links):
        escaped_text = link_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text = text.replace(f"\x00LK{i}\x00", f'<a href="{url}">{escaped_text}</a>')

    # 8. Bold **text** or __text__
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'__(.+?)__', r'<b>\1</b>', text)

    # 9. Italic _text_ (avoid matching inside words like some_var_name)
    text = re.sub(r'(?<![a-zA-Z0-9])_([^_]+)_(?![a-zA-Z0-9])', r'<i>\1</i>', text)

    # 10. Strikethrough ~~text~~
    text = re.sub(r'~~(.+?)~~', r'<s>\1</s>', text)

    # 11. Bullet lists - item -> • item
    text = re.sub(r'^[-*]\s+', '• ', text, flags=re.MULTILINE)

    # 12. Restore inline code with HTML tags
    for i, code in enumerate(inline_codes):
        # Escape HTML in code content
        escaped = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text = text.replace(f"\x00IC{i}\x00", f"<code>{escaped}</code>")

    # 13. Restore code blocks with HTML tags
    for i, code in enumerate(code_blocks):
        # Escape HTML in code content
        escaped = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text = text.replace(f"\x00CB{i}\x00", f"<pre><code>{escaped}</code></pre>")
    
    return text


from lemonclaw.channels.utils import split_message as _split_message_impl


def _split_message(content: str, max_len: int = 4000) -> list[str]:
    return _split_message_impl(content, max_len)


class TelegramChannel(BaseChannel):
    """
    Telegram channel using long polling.
    
    Simple and reliable - no webhook/public IP needed.
    """
    
    name = "telegram"
    
    # Commands registered with Telegram's command menu
    BOT_COMMANDS = [
        BotCommand("start", "Start the bot"),
        BotCommand("new", "Start a new conversation"),
        BotCommand("stop", "Stop the current task"),
        BotCommand("model", "List or switch AI models"),
        BotCommand("help", "Show available commands"),
    ]
    
    def __init__(
        self,
        config: TelegramConfig,
        bus: MessageBus,
        api_key: str = "",
        api_base: str = "",
    ):
        super().__init__(config, bus)
        self.config: TelegramConfig = config
        self.api_key = api_key
        self.api_base = api_base
        self._app: Application | None = None
        self._chat_ids: dict[str, int] = {}  # Map sender_id to chat_id for replies
        self._typing_tasks: dict[str, asyncio.Task] = {}  # chat_id -> typing loop task
        self._media_group_buffers: dict[str, dict] = {}
        self._media_group_tasks: dict[str, asyncio.Task] = {}
        self._seen_update_ids: set[int] = set()  # Dedup Telegram updates
        self._seen_update_ids_max = 500
        # Stream state: chat_id -> _StreamState
        self._stream_states: dict[str, _StreamState] = {}
    
    async def start(self) -> None:
        """Start the Telegram bot with long polling."""
        if not self.config.token:
            logger.error("Telegram bot token not configured")
            return

        self._running = True
        
        # Build the application with larger connection pool to avoid pool-timeout on long runs
        req = HTTPXRequest(connection_pool_size=16, pool_timeout=5.0, connect_timeout=30.0, read_timeout=30.0)
        builder = Application.builder().token(self.config.token).request(req).get_updates_request(req)
        if self.config.proxy:
            builder = builder.proxy(self.config.proxy).get_updates_proxy(self.config.proxy)
        self._app = builder.build()
        self._app.add_error_handler(self._on_error)
        
        # Add command handlers
        self._app.add_handler(CommandHandler("start", self._on_start))
        self._app.add_handler(CommandHandler("new", self._forward_command))
        self._app.add_handler(CommandHandler("model", self._forward_command))
        self._app.add_handler(CommandHandler("help", self._on_help))

        # Inline keyboard callback handler (for /model buttons)
        self._app.add_handler(CallbackQueryHandler(self._on_model_callback, pattern=r"^model:"))
        self._app.add_handler(CallbackQueryHandler(self._on_noop_callback, pattern=r"^noop$"))
        
        # Add message handler for text, photos, voice, documents
        self._app.add_handler(
            MessageHandler(
                (filters.TEXT | filters.PHOTO | filters.VOICE | filters.AUDIO | filters.Document.ALL) 
                & ~filters.COMMAND, 
                self._on_message
            )
        )
        
        logger.info("Starting Telegram bot (polling mode)...")
        
        # Initialize and start polling
        await self._app.initialize()
        await self._app.start()
        
        # Get bot info and register command menu
        bot_info = await self._app.bot.get_me()
        logger.info("Telegram bot @{} connected", bot_info.username)
        
        try:
            await self._app.bot.set_my_commands(self.BOT_COMMANDS)
            logger.debug("Telegram bot commands registered")
        except Exception as e:
            logger.warning("Failed to register bot commands: {}", e)
        
        # Start polling (this runs until stopped)
        await self._app.updater.start_polling(
            allowed_updates=["message", "callback_query"],
            drop_pending_updates=True  # Ignore old messages on startup
        )
        
        # Keep running until stopped
        while self._running:
            await asyncio.sleep(1)
    
    async def stop(self) -> None:
        """Stop the Telegram bot."""
        self._running = False

        # Cancel all typing indicators
        for chat_id in list(self._typing_tasks):
            self._stop_typing(chat_id)

        for task in self._media_group_tasks.values():
            task.cancel()
        self._media_group_tasks.clear()
        self._media_group_buffers.clear()
        self._stream_states.clear()

        if self._app:
            logger.info("Stopping Telegram bot...")
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
            self._app = None
    
    @staticmethod
    def _get_media_type(path: str) -> str:
        """Guess media type from file extension."""
        ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        if ext in ("jpg", "jpeg", "png", "gif", "webp"):
            return "photo"
        if ext in ("mp4", "webm", "mov", "avi", "mkv"):
            return "video"
        if ext == "ogg":
            return "voice"
        if ext in ("mp3", "m4a", "wav", "aac"):
            return "audio"
        return "document"

    @staticmethod
    def _get_video_duration(path: str) -> float | None:
        """Get video duration in seconds using ffprobe."""
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", path],
                capture_output=True, text=True, timeout=10,
            )
            return float(result.stdout.strip()) if result.returncode == 0 else None
        except Exception:
            return None

    @staticmethod
    def _split_video(path: str, target_bytes: int = _TG_SPLIT_TARGET_BYTES) -> list[str]:
        """Split a video into segments that fit within Telegram's file size limit.

        Returns a list of file paths for the segments, or an empty list on failure.
        """
        file_size = os.path.getsize(path)
        duration = TelegramChannel._get_video_duration(path)
        if not duration or duration <= 0:
            logger.warning("Cannot determine video duration for {}", path)
            return []

        # Calculate number of segments needed
        num_segments = max(2, int(file_size / target_bytes) + 1)
        segment_duration = duration / num_segments

        ext = path.rsplit(".", 1)[-1] if "." in path else "mp4"
        basename = os.path.basename(path).rsplit(".", 1)[0]
        tmp_dir = tempfile.mkdtemp(prefix="tg_split_")
        segments = []

        try:
            for i in range(num_segments):
                start = i * segment_duration
                out_path = os.path.join(tmp_dir, f"{basename}_part{i + 1}.{ext}")
                cmd = [
                    "ffmpeg", "-y", "-ss", str(start), "-i", path,
                    "-t", str(segment_duration), "-c", "copy",
                    "-avoid_negative_ts", "make_zero", out_path,
                ]
                result = subprocess.run(cmd, capture_output=True, timeout=120)
                if result.returncode != 0 or not os.path.exists(out_path):
                    logger.error("ffmpeg split failed for segment {}", i + 1)
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                    return []
                segments.append(out_path)
        except Exception as e:
            logger.error("Video split failed: {}", e)
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return []

        return segments

    # ── Streaming support (editMessageText approach) ────────────────────

    def _get_or_create_stream(self, chat_id: str) -> _StreamState:
        """Get or create a stream state for a chat."""
        if chat_id not in self._stream_states:
            self._stream_states[chat_id] = _StreamState()
        return self._stream_states[chat_id]

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through Telegram."""
        if not self._app:
            logger.warning("Telegram bot not running")
            return

        try:
            chat_id = int(msg.chat_id)
        except ValueError:
            logger.error("Invalid chat_id: {}", msg.chat_id)
            return

        is_progress = msg.metadata.get("_progress", False)
        thread_id = msg.metadata.get("message_thread_id")

        # ── Progress/chunk messages: stream via editMessageText ──
        if is_progress:
            if not msg.content or msg.content == "[empty message]":
                return
            stream = self._get_or_create_stream(msg.chat_id)

            is_chunk = msg.metadata.get("_chunk", False)

            # First chunk of a new LLM call resets the stream text
            if is_chunk and msg.metadata.get("_chunk_first"):
                stream.text = msg.content
            elif is_chunk:
                stream.text += msg.content
            else:
                # Status message (tool hints etc.) — append with newline
                if stream.text and not stream.text.endswith("\n"):
                    stream.text += "\n"
                stream.text += msg.content

            # Throttle: skip if too soon and too little new content
            now = time.monotonic()
            new_chars = len(stream.text) - len(stream.last_sent_text)
            if (now - stream.last_sent_at < _STREAM_MIN_INTERVAL
                    and new_chars < _STREAM_MIN_CHARS):
                return

            display = stream.text[:4096]
            if not display.strip():
                return

            try:
                if stream.message_id == 0:
                    # First update: send a new message
                    send_kwargs = {"chat_id": chat_id, "text": display + " ▍"}
                    if thread_id:
                        send_kwargs["message_thread_id"] = thread_id
                    sent = await self._app.bot.send_message(**send_kwargs)
                    stream.message_id = sent.message_id
                else:
                    # Subsequent updates: edit the existing message
                    await self._app.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=stream.message_id,
                        text=display + " ▍",
                    )
                stream.last_sent_at = now
                stream.last_sent_text = display
            except Exception as e:
                logger.debug("Stream edit failed: {}", e)
            return

        # ── Final message: edit stream message or send new ──────────────
        self._stop_typing(msg.chat_id)
        stream = self._stream_states.pop(msg.chat_id, None)

        reply_params = None
        if self.config.reply_to_message:
            reply_to_message_id = msg.metadata.get("message_id")
            if reply_to_message_id:
                reply_params = ReplyParameters(
                    message_id=reply_to_message_id,
                    allow_sending_without_reply=True
                )

        # Common kwargs for forum topic routing
        topic_kwargs = {"message_thread_id": thread_id} if thread_id else {}

        # Send media files (with automatic splitting for large videos)
        for media_path in (msg.media or []):
            try:
                # Remote URLs: send directly via Telegram Bot API (supports URL strings)
                if media_path.startswith(("http://", "https://")):
                    media_type = self._get_media_type(media_path)
                    sender = {
                        "photo": self._app.bot.send_photo,
                        "video": self._app.bot.send_video,
                        "voice": self._app.bot.send_voice,
                        "audio": self._app.bot.send_audio,
                    }.get(media_type, self._app.bot.send_document)
                    param = media_type if media_type in ("photo", "video", "voice", "audio") else "document"
                    await sender(
                        chat_id=chat_id,
                        **{param: media_path},
                        reply_parameters=reply_params,
                        **topic_kwargs,
                    )
                    continue

                file_size = os.path.getsize(media_path)
                media_type = self._get_media_type(media_path)

                # Large video/audio: split into segments
                if file_size > _TG_MAX_FILE_BYTES and media_type in ("video", "audio"):
                    filename = os.path.basename(media_path)
                    logger.info("File {} is {:.1f}MB, splitting for Telegram", filename, file_size / 1024 / 1024)
                    segments = self._split_video(media_path)
                    if segments:
                        tmp_dir = os.path.dirname(segments[0])
                        try:
                            total = len(segments)
                            for idx, seg_path in enumerate(segments, 1):
                                try:
                                    caption = f"{filename} [{idx}/{total}]"
                                    sender = self._app.bot.send_video if media_type == "video" else self._app.bot.send_audio
                                    param = media_type
                                    with open(seg_path, 'rb') as f:
                                        await sender(
                                            chat_id=chat_id,
                                            **{param: f},
                                            caption=caption,
                                            reply_parameters=reply_params,
                                            **topic_kwargs,
                                        )
                                except Exception as e:
                                    logger.error("Failed to send segment {}/{}: {}", idx, total, e)
                                    await self._app.bot.send_message(
                                        chat_id=chat_id,
                                        text=f"[Failed to send: {filename} part {idx}/{total}]",
                                        reply_parameters=reply_params,
                                        **topic_kwargs,
                                    )
                        finally:
                            shutil.rmtree(tmp_dir, ignore_errors=True)
                        continue
                    else:
                        # Split failed, notify user with file path
                        await self._app.bot.send_message(
                            chat_id=chat_id,
                            text=f"[File too large for Telegram ({file_size / 1024 / 1024:.0f}MB): {media_path}]",
                            reply_parameters=reply_params,
                            **topic_kwargs,
                        )
                        continue

                # Normal send
                sender = {
                    "photo": self._app.bot.send_photo,
                    "video": self._app.bot.send_video,
                    "voice": self._app.bot.send_voice,
                    "audio": self._app.bot.send_audio,
                }.get(media_type, self._app.bot.send_document)
                param = media_type if media_type in ("photo", "video", "voice", "audio") else "document"
                with open(media_path, 'rb') as f:
                    await sender(
                        chat_id=chat_id,
                        **{param: f},
                        reply_parameters=reply_params,
                        **topic_kwargs,
                    )
            except Exception as e:
                filename = media_path.rsplit("/", 1)[-1]
                logger.error("Failed to send media {}: {}", media_path, e)
                await self._app.bot.send_message(
                    chat_id=chat_id,
                    text=f"[Failed to send: {filename}]",
                    reply_parameters=reply_params,
                    **topic_kwargs,
                )

        # Send text content
        if msg.content and msg.content != "[empty message]":
            chunks = _split_message(msg.content)

            # Inline keyboard for /model list (Telegram-specific)
            reply_markup = None
            if msg.metadata.get("_command") == "model_list":
                reply_markup = self._build_model_keyboard(msg.metadata.get("_current_model"))
                # Replace verbose text list with compact header — keyboard is the UI
                current_id = msg.metadata.get("_current_model")
                from lemonclaw.providers.catalog import MODEL_MAP
                entry = MODEL_MAP.get(current_id) if current_id else None
                label = entry.label if entry else (current_id or "—")
                chunks = [f"🍋 *Select model*\nCurrent: `{label}`"]

            # If we have a stream message, edit the first chunk into it
            if stream and stream.message_id and len(chunks) >= 1:
                first_html = _markdown_to_telegram_html(chunks[0])
                try:
                    await self._app.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=stream.message_id,
                        text=first_html,
                        parse_mode="HTML",
                        reply_markup=reply_markup,
                    )
                except Exception as e:
                    logger.debug("Final edit failed, falling back to plain: {}", e)
                    try:
                        await self._app.bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=stream.message_id,
                            text=chunks[0],
                            reply_markup=reply_markup,
                        )
                    except Exception as e2:
                        logger.warning("Telegram message delivery failed completely: {}", e2)
                remaining = chunks[1:]
                reply_markup = None  # Only attach to first chunk
            else:
                remaining = chunks

            for chunk in remaining:
                html = _markdown_to_telegram_html(chunk)
                try:
                    await self._app.bot.send_message(
                        chat_id=chat_id,
                        text=html,
                        parse_mode="HTML",
                        reply_parameters=reply_params,
                        reply_markup=reply_markup,
                        **topic_kwargs,
                    )
                except Exception as e:
                    logger.warning("HTML parse failed, falling back to plain text: {}", e)
                    try:
                        await self._app.bot.send_message(
                            chat_id=chat_id,
                            text=chunk,
                            reply_parameters=reply_params,
                            reply_markup=reply_markup,
                            **topic_kwargs,
                        )
                    except Exception as e2:
                        logger.error("Error sending Telegram message: {}", e2)
                reply_markup = None  # Only attach to first chunk

            # After model switch, update the original keyboard to reflect new selection
            if msg.metadata.get("_command") == "model_switched":
                callback_msg_id = msg.metadata.get("_callback_message_id")
                new_model = msg.metadata.get("_current_model")
                if callback_msg_id and new_model:
                    try:
                        new_keyboard = self._build_model_keyboard(new_model)
                        await self._app.bot.edit_message_reply_markup(
                            chat_id=chat_id,
                            message_id=callback_msg_id,
                            reply_markup=new_keyboard,
                        )
                    except Exception as e:
                        logger.debug("Failed to update model keyboard: {}", e)
    
    def _dedup_update(self, update: Update) -> bool:
        """Return True if this update is new, False if duplicate."""
        uid = update.update_id
        if uid in self._seen_update_ids:
            logger.debug("Telegram duplicate update_id={}, skipping", uid)
            return False
        self._seen_update_ids.add(uid)
        if len(self._seen_update_ids) > self._seen_update_ids_max:
            # Trim oldest half
            sorted_ids = sorted(self._seen_update_ids)
            self._seen_update_ids = set(sorted_ids[len(sorted_ids) // 2:])
        return True

    async def _on_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command."""
        if not update.message or not update.effective_user:
            return

        user = update.effective_user
        await update.message.reply_text(
            f"👋 Hi {user.first_name}! I'm lemonclaw.\n\n"
            "Send me a message and I'll respond!\n"
            "Type /help to see available commands."
        )

    async def _on_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /help command, bypassing ACL so all users can access it."""
        if not update.message:
            return
        await update.message.reply_text(
            "🍋 LemonClaw commands:\n"
            "/new — Start a new conversation\n"
            "/stop — Stop the current task\n"
            "/help — Show available commands"
        )

    @staticmethod
    def _sender_id(user) -> str:
        """Build sender_id with username for allowlist matching."""
        sid = str(user.id)
        return f"{sid}|{user.username}" if user.username else sid

    async def _forward_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Forward slash commands to the bus for unified handling in AgentLoop."""
        if not update.message or not update.effective_user:
            return
        if not self._dedup_update(update):
            return
        message = update.message
        is_group = message.chat.type != "private"
        thread_id = getattr(message, "message_thread_id", None) if is_group else None
        str_chat_id = str(message.chat_id)
        session_key = f"telegram:{str_chat_id}:{thread_id}" if thread_id else None
        user = update.effective_user
        metadata = {
            "message_id": message.message_id,
            "user_id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "is_group": is_group,
        }
        if thread_id:
            metadata["message_thread_id"] = thread_id
        await self._handle_message(
            sender_id=self._sender_id(update.effective_user),
            chat_id=str_chat_id,
            content=message.text,
            metadata=metadata,
            session_key=session_key,
            pairing_policy=self.config.dm_policy if not is_group else None,
        )

    # ── Inline keyboard for /model ────────────────────────────────────────

    def _build_model_keyboard(self, current_model: str | None) -> InlineKeyboardMarkup:
        """Build a compact inline keyboard with model buttons grouped by tier."""
        from lemonclaw.providers.catalog import get_model_tiers

        TIER_EMOJI = {"Flagship": "👑", "Standard": "⚡", "Economy": "💡", "Specialist": "🔬"}

        buttons: list[list[InlineKeyboardButton]] = []
        for tier_label, models in get_model_tiers():
            emoji = TIER_EMOJI.get(tier_label, "▸")
            # Tier header (non-clickable, full width)
            buttons.append([InlineKeyboardButton(f"{emoji} {tier_label}", callback_data="noop")])
            # Model buttons — compact labels, 2 per row
            row: list[InlineKeyboardButton] = []
            for m in models:
                label = m.label.removeprefix("Claude ")
                check = " ✓" if current_model and m.id == current_model else ""
                row.append(InlineKeyboardButton(f"{label}{check}", callback_data=f"model:{m.id}"))
                if len(row) == 2:
                    buttons.append(row)
                    row = []
            if row:
                buttons.append(row)

        buttons.append([InlineKeyboardButton("✕ Close", callback_data="model:close")])
        return InlineKeyboardMarkup(buttons)

    async def _on_noop_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Acknowledge tier-header button taps (no action)."""
        if update.callback_query:
            await update.callback_query.answer()

    async def _on_model_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle inline keyboard button presses for model selection."""
        query = update.callback_query
        if not query or not query.data or not update.effective_user:
            return

        await query.answer()

        data = query.data

        # Close button: remove the keyboard
        if data == "model:close":
            try:
                await query.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass
            return

        # model:<id> — forward as /model <id> through the bus
        if data.startswith("model:"):
            model_id = data[6:]
            chat_id = str(query.message.chat_id)
            sender_id = self._sender_id(update.effective_user)

            is_group = query.message.chat.type != "private"
            thread_id = getattr(query.message, "message_thread_id", None) if is_group else None
            session_key = f"telegram:{chat_id}:{thread_id}" if thread_id else None

            metadata = {
                "user_id": update.effective_user.id,
                "username": update.effective_user.username,
                "first_name": update.effective_user.first_name,
                "is_group": is_group,
                "_callback_message_id": query.message.message_id,
            }
            if thread_id:
                metadata["message_thread_id"] = thread_id

            await self._handle_message(
                sender_id=sender_id,
                chat_id=chat_id,
                content=f"/model {model_id}",
                metadata=metadata,
                session_key=session_key,
            )

    async def _on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming messages (text, photos, voice, documents)."""
        if not update.message or not update.effective_user:
            return
        if not self._dedup_update(update):
            return

        message = update.message
        user = update.effective_user
        chat_id = message.chat_id
        sender_id = self._sender_id(user)
        is_group = message.chat.type != "private"

        # Forum topic support: use message_thread_id for topic-scoped sessions
        thread_id = getattr(message, "message_thread_id", None) if is_group else None

        # Store chat_id for replies
        self._chat_ids[sender_id] = chat_id

        # Build content from text and/or media
        content_parts = []
        media_paths = []

        # Text content
        if message.text:
            content_parts.append(message.text)
        if message.caption:
            content_parts.append(message.caption)
        
        # Handle media files
        media_file = None
        media_type = None
        
        if message.photo:
            media_file = message.photo[-1]  # Largest photo
            media_type = "image"
        elif message.voice:
            media_file = message.voice
            media_type = "voice"
        elif message.audio:
            media_file = message.audio
            media_type = "audio"
        elif message.document:
            media_file = message.document
            media_type = "file"
        
        # Download media if present
        if media_file and self._app:
            try:
                file = await self._app.bot.get_file(media_file.file_id)
                # Preserve original filename when available (e.g. document.file_name)
                original_name = getattr(media_file, 'file_name', None)
                ext = self._get_extension(media_type, getattr(media_file, 'mime_type', None))

                # Save to ~/.lemonclaw/media/
                from pathlib import Path
                media_dir = Path.home() / ".lemonclaw" / "media"
                media_dir.mkdir(parents=True, exist_ok=True)

                if original_name:
                    # Use original filename with file_id prefix to avoid collisions
                    safe_name = re.sub(r'[^\w\s.\-\u4e00-\u9fff]', '_', original_name)
                    file_path = media_dir / f"{media_file.file_id[:8]}_{safe_name}"
                else:
                    file_path = media_dir / f"{media_file.file_id[:16]}{ext}"
                await file.download_to_drive(str(file_path))

                media_paths.append(str(file_path))

                # Build descriptive label for the agent
                label = original_name or file_path.name

                # Handle voice transcription
                if media_type == "voice" or media_type == "audio":
                    from lemonclaw.providers.transcription import TranscriptionProvider
                    transcriber = TranscriptionProvider(api_key=self.api_key, api_base=self.api_base)
                    transcription = await transcriber.transcribe(file_path)
                    if transcription:
                        logger.info("Transcribed {}: {}...", media_type, transcription[:50])
                        content_parts.append(f"[transcription: {transcription}]")
                    else:
                        content_parts.append(f"[{media_type}: {file_path} ({label})]")
                else:
                    content_parts.append(f"[{media_type}: {file_path} ({label})]")
                    
                logger.debug("Downloaded {} to {}", media_type, file_path)
            except Exception as e:
                logger.error("Failed to download media: {}", e)
                content_parts.append(f"[{media_type}: download failed]")
        
        content = "\n".join(content_parts) if content_parts else "[empty message]"

        logger.debug("Telegram message from {}: {}...", sender_id, content[:50])

        str_chat_id = str(chat_id)

        # Forum topic support: build topic-scoped session key and metadata
        session_key = f"telegram:{str_chat_id}:{thread_id}" if thread_id else None
        base_metadata = {
            "message_id": message.message_id,
            "user_id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "is_group": is_group,
        }
        if thread_id:
            base_metadata["message_thread_id"] = thread_id

        # Telegram media groups: buffer briefly, forward as one aggregated turn.
        if media_group_id := getattr(message, "media_group_id", None):
            key = f"{str_chat_id}:{media_group_id}"
            if key not in self._media_group_buffers:
                self._media_group_buffers[key] = {
                    "sender_id": sender_id, "chat_id": str_chat_id,
                    "contents": [], "media": [],
                    "metadata": base_metadata,
                    "session_key": session_key,
                }
                self._start_typing(str_chat_id)
            buf = self._media_group_buffers[key]
            if content and content != "[empty message]":
                buf["contents"].append(content)
            buf["media"].extend(media_paths)
            if key not in self._media_group_tasks:
                self._media_group_tasks[key] = asyncio.create_task(self._flush_media_group(key))
            return

        # Start typing indicator before processing
        self._start_typing(str_chat_id)

        # Forward to the message bus
        await self._handle_message(
            sender_id=sender_id,
            chat_id=str_chat_id,
            content=content,
            media=media_paths,
            metadata=base_metadata,
            session_key=session_key,
        )
    
    async def _flush_media_group(self, key: str) -> None:
        """Wait briefly, then forward buffered media-group as one turn."""
        try:
            await asyncio.sleep(0.6)
            if not (buf := self._media_group_buffers.pop(key, None)):
                return
            content = "\n".join(buf["contents"]) or "[empty message]"
            await self._handle_message(
                sender_id=buf["sender_id"], chat_id=buf["chat_id"],
                content=content, media=list(dict.fromkeys(buf["media"])),
                metadata=buf["metadata"],
                session_key=buf.get("session_key"),
            )
        finally:
            self._media_group_tasks.pop(key, None)

    def _start_typing(self, chat_id: str) -> None:
        """Start sending 'typing...' indicator for a chat."""
        # Cancel any existing typing task for this chat
        self._stop_typing(chat_id)
        self._typing_tasks[chat_id] = asyncio.create_task(self._typing_loop(chat_id))
    
    def _stop_typing(self, chat_id: str) -> None:
        """Stop the typing indicator for a chat."""
        task = self._typing_tasks.pop(chat_id, None)
        if task and not task.done():
            task.cancel()
    
    async def _typing_loop(self, chat_id: str) -> None:
        """Repeatedly send 'typing' action until cancelled."""
        try:
            while self._app:
                await self._app.bot.send_chat_action(chat_id=int(chat_id), action="typing")
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug("Typing indicator stopped for {}: {}", chat_id, e)
    
    async def _on_error(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Log polling / handler errors instead of silently swallowing them."""
        logger.error("Telegram error: {}", context.error)

    def _get_extension(self, media_type: str, mime_type: str | None) -> str:
        """Get file extension based on media type."""
        if mime_type:
            ext_map = {
                "image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif",
                "audio/ogg": ".ogg", "audio/mpeg": ".mp3", "audio/mp4": ".m4a",
            }
            if mime_type in ext_map:
                return ext_map[mime_type]
        
        type_map = {"image": ".jpg", "voice": ".ogg", "audio": ".mp3", "file": ""}
        return type_map.get(media_type, "")
