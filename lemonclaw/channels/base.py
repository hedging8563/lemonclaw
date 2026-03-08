"""Base channel interface for chat platforms."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from loguru import logger

from lemonclaw.bus.events import InboundMessage, OutboundMessage
from lemonclaw.bus.queue import MessageBus


class BaseChannel(ABC):
    """
    Abstract base class for chat channel implementations.

    Each channel (Telegram, Discord, etc.) should implement this interface
    to integrate with the lemonclaw message bus.
    """

    name: str = "base"

    def __init__(self, config: Any, bus: MessageBus):
        """
        Initialize the channel.

        Args:
            config: Channel-specific configuration.
            bus: The message bus for communication.
        """
        self.config = config
        self.bus = bus
        self._running = False
        self._pairing: "AutoPairing | None" = None
    
    @abstractmethod
    async def start(self) -> None:
        """
        Start the channel and begin listening for messages.
        
        This should be a long-running async task that:
        1. Connects to the chat platform
        2. Listens for incoming messages
        3. Forwards messages to the bus via _handle_message()
        """
        pass
    
    @abstractmethod
    async def stop(self) -> None:
        """Stop the channel and clean up resources."""
        pass
    
    @abstractmethod
    async def send(self, msg: OutboundMessage) -> None:
        """
        Send a message through this channel.
        
        Args:
            msg: The message to send.
        """
        pass
    
    def is_allowed(self, sender_id: str) -> bool:
        """
        Check if a sender is allowed to use this bot.

        Deny-by-default: if allow_from is empty, reject all messages.
        This prevents accidental exposure when the whitelist is not configured.

        Args:
            sender_id: The sender's identifier.

        Returns:
            True if allowed, False otherwise.
        """
        allow_list = getattr(self.config, "allow_from", [])

        # Deny-by-default: empty allow_from means no one is allowed
        if not allow_list:
            logger.warning(
                "Channel {} has empty allow_from — all messages denied. "
                "Configure allow_from in config to grant access.",
                self.name,
            )
            return False

        sender_str = str(sender_id)
        if '*' in allow_list:
            return True
        if sender_str in allow_list:
            return True
        if "|" in sender_str:
            for part in sender_str.split("|"):
                if part and part in allow_list:
                    return True
        return False
    
    def enable_auto_pairing(self, data_dir: Path) -> None:
        """Enable auto-pairing for this channel."""
        from lemonclaw.channels.auto_pairing import AutoPairing
        self._pairing = AutoPairing(self.name, data_dir)

    async def _run_pairing_flow(
        self,
        *,
        sender_id: str,
        notify_target: str,
        content: str,
        display_name: str | None = None,
    ) -> bool:
        """Run the standard auto-pairing gate.

        Returns True when the message should continue into normal handling.
        Returns False when the message was blocked, queued for approval,
        or consumed as an approval command.
        """
        stripped = content.strip()
        if self._pairing and stripped.startswith(("/approve ", "/deny ")):
            reply = await self._handle_pairing_command(sender_id, stripped)
            if reply:
                await self.bus.publish_outbound(OutboundMessage(
                    channel=self.name, chat_id=str(notify_target), content=reply,
                ))
            return False

        if self.is_allowed(sender_id):
            return True

        if not self._pairing:
            logger.warning(
                "Access denied for sender {} on channel {}. "
                "Add them to allowFrom list in config to grant access.",
                sender_id, self.name,
            )
            return False

        result = self._pairing.check_or_pair(
            sender_id,
            display_name=display_name or str(sender_id),
            notify_target=str(notify_target),
        )
        if result == "paired":
            logger.info("Auto-paired {} as owner on {}", sender_id, self.name)
            return True
        if result == "allowed":
            return True
        if result == "pending":
            owner_target = self._pairing.owner_notify_target
            if owner_target:
                await self.bus.publish_outbound(OutboundMessage(
                    channel=self.name,
                    chat_id=str(owner_target),
                    content=f"New user wants access: {sender_id}\nReply /approve {sender_id} or /deny {sender_id}",
                ))
        return False

    async def _handle_message(
        self,
        sender_id: str,
        chat_id: str,
        content: str,
        media: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        session_key: str | None = None,
    ) -> None:
        """
        Handle an incoming message from the chat platform.

        This method checks permissions (static allow_from + auto-pairing)
        and forwards to the bus.
        """
        if not await self._run_pairing_flow(
            sender_id=str(sender_id),
            notify_target=str(chat_id),
            content=content,
            display_name=str(sender_id),
        ):
            return

        msg = InboundMessage(
            channel=self.name,
            sender_id=str(sender_id),
            chat_id=str(chat_id),
            content=content,
            media=media or [],
            metadata=metadata or {},
            session_key_override=session_key,
        )

        await self.bus.publish_inbound(msg)

    async def _handle_pairing_command(self, sender_id: str, content: str) -> str | None:
        """Handle /approve or /deny commands. Only the owner can execute these."""
        if not self._pairing:
            return None

        sid = str(sender_id)
        owner = self._pairing.owner
        # Check if sender is the owner
        is_owner = sid == owner
        if not is_owner and "|" in sid:
            is_owner = any(p == owner for p in sid.split("|") if p)
        if not is_owner:
            return None  # silently ignore non-owner pairing commands

        parts = content.split(maxsplit=1)
        if len(parts) < 2:
            return "Usage: /approve <user_id> or /deny <user_id>"

        cmd, target = parts[0].lower(), parts[1].strip()

        if cmd == "/approve":
            notify_target = self._pairing.approve(target)
            if notify_target:
                await self.bus.publish_outbound(OutboundMessage(
                    channel=self.name,
                    chat_id=str(notify_target),
                    content="✅ Access approved. Send a message to start chatting.",
                ))
                return f"Approved: {target}"
            return f"No pending request from: {target}"
        elif cmd == "/deny":
            notify_target = self._pairing.deny(target)
            if notify_target:
                return f"Denied: {target}"
            return f"No pending request from: {target}"
        return None
    
    @property
    def is_running(self) -> bool:
        """Check if the channel is running."""
        return self._running
