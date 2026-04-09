"""Base channel interface for chat platforms."""

from collections import deque
from abc import ABC, abstractmethod
from pathlib import Path
import time
from typing import Any

from loguru import logger

from lemonclaw.bus.events import InboundMessage, OutboundMessage
from lemonclaw.channels.delivery_context import attach_delivery_context
from lemonclaw.channels.session_context import attach_session_context
from lemonclaw.channels.session_keys import build_channel_session_key
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
        self._rate_limit_window_s = 30.0
        self._rate_limit_max_messages = 12
        self._rate_limit_hits: dict[str, deque[float]] = {}
        self._rate_limit_notice_at: dict[str, float] = {}
    
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
    
    def is_allowed(self, sender_id: str, *, warn_on_empty: bool = True) -> bool:
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
            if not warn_on_empty:
                return False
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
    
    def _is_rate_limited(self, sender_id: str) -> bool:
        now = time.monotonic()
        window_start = now - self._rate_limit_window_s
        dq = self._rate_limit_hits.setdefault(str(sender_id), deque())
        while dq and dq[0] < window_start:
            dq.popleft()
        if len(dq) >= self._rate_limit_max_messages:
            logger.warning("Rate limit exceeded for sender {} on channel {}", sender_id, self.name)
            return True
        dq.append(now)
        return False

    async def _publish_feedback(self, chat_id: str, content: str) -> None:
        await self.bus.publish_outbound(
            OutboundMessage(
                channel=self.name,
                chat_id=str(chat_id),
                content=content,
            )
        )

    def _should_send_rate_limit_notice(self, sender_id: str) -> bool:
        now = time.monotonic()
        last_notice = self._rate_limit_notice_at.get(str(sender_id), 0.0)
        if now - last_notice < self._rate_limit_window_s:
            return False
        self._rate_limit_notice_at[str(sender_id)] = now
        return True

    def enable_auto_pairing(self, data_dir: Path) -> None:
        """Enable auto-pairing for this channel."""
        from lemonclaw.channels.auto_pairing import AutoPairing
        self._pairing = AutoPairing(self.name, data_dir)


    def _resolve_group_gate(self) -> tuple[str, bool]:
        """Resolve normalized group policy + mention requirement.

        Legacy configs may still store group_policy="mention". Treat that as
        group_policy="open" + group_require_mention=true for backward compatibility.
        """
        raw_policy = str(getattr(self.config, "group_policy", "disabled") or "disabled").strip().lower()
        require_mention = bool(getattr(self.config, "group_require_mention", True))
        if raw_policy == "mention":
            return "open", True
        if raw_policy == "disabled":
            return "disabled", False
        return raw_policy, require_mention

    @staticmethod
    def _group_policy_allows(policy: str, *, in_allowlist: bool = True, require_mention: bool = False, was_mentioned: bool = False) -> bool:
        """Evaluate normalized group access semantics.

        policy controls scope (all groups vs allowlist), while require_mention controls
        trigger behavior within the allowed scope.
        """
        if policy == "disabled":
            return False
        if policy == "allowlist" and not in_allowlist:
            return False
        if policy not in {"open", "allowlist"}:
            return False
        if require_mention and not was_mentioned:
            return False
        return True

    async def _run_pairing_flow(
        self,
        *,
        sender_id: str,
        notify_target: str,
        content: str,
        display_name: str | None = None,
        policy: str | None = None,
    ) -> bool:
        """Run the standard auto-pairing gate.

        Returns True when the message should continue into normal handling.
        Returns False when the message was blocked, queued for approval,
        or consumed as an approval command.
        """
        stripped = content.strip()
        effective_policy = (policy or "").strip().lower() or None

        if effective_policy == "open":
            return True
        if effective_policy == "disabled":
            await self._publish_feedback(
                notify_target,
                "Direct messages are disabled for this bot on this channel.",
            )
            return False
        if effective_policy == "allowlist":
            if self.is_allowed(sender_id):
                return True
            await self._publish_feedback(
                notify_target,
                "Access denied. This bot only accepts messages from approved senders on this channel.",
            )
            return False

        if self._pairing and (
            stripped.startswith(("/approve ", "/deny ", "/pairing "))
            or stripped in {"/pairing", "/pairing status", "/pairing pending"}
        ):
            reply = await self._handle_pairing_command(sender_id, stripped, notify_target=str(notify_target))
            if reply:
                await self.bus.publish_outbound(OutboundMessage(
                    channel=self.name, chat_id=str(notify_target), content=reply,
                ))
            return False

        warn_on_empty_allowlist = effective_policy == "allowlist" or not self._pairing
        if self.is_allowed(sender_id, warn_on_empty=warn_on_empty_allowlist):
            return True

        if not self._pairing:
            logger.warning(
                "Access denied for sender {} on channel {}. "
                "Add them to allowFrom list in config to grant access.",
                sender_id, self.name,
            )
            await self._publish_feedback(
                notify_target,
                "Access denied. Ask the current owner to add you to the allow list or enable pairing for this channel.",
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
            await self.bus.publish_outbound(OutboundMessage(
                channel=self.name,
                chat_id=str(notify_target),
                content=(
                    "Your access request is pending owner approval.\n"
                    f"Ask the current owner to reply /approve {sender_id} or /deny {sender_id} from their linked chat."
                ),
            ))
        if result == "already_pending":
            await self.bus.publish_outbound(OutboundMessage(
                channel=self.name,
                chat_id=str(notify_target),
                content=(
                    "Your access request is still pending owner approval.\n"
                    f"Ask the current owner to reply /approve {sender_id} or /deny {sender_id} from their linked chat."
                ),
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
        pairing_policy: str | None = None,
    ) -> None:
        """
        Handle an incoming message from the chat platform.

        This method checks permissions (static allow_from + auto-pairing)
        and forwards to the bus.
        """
        stripped = content.strip()
        is_group_message = bool((metadata or {}).get("is_group"))
        if not stripped.startswith(("/approve ", "/deny ")) and self._is_rate_limited(str(sender_id)):
            if self._should_send_rate_limit_notice(str(sender_id)):
                await self._publish_feedback(
                    chat_id,
                    "Too many messages too quickly. Please wait a moment and try again.",
                )
            return

        # Group ingress is governed by group_policy / group_allow_from upstream in the
        # channel implementation. Do not re-apply DM allow_from / pairing here.
        if not is_group_message:
            if not await self._run_pairing_flow(
                sender_id=str(sender_id),
                notify_target=str(chat_id),
                content=content,
                display_name=str(sender_id),
                policy=pairing_policy,
            ):
                return

        msg = InboundMessage(
            channel=self.name,
            sender_id=str(sender_id),
            chat_id=str(chat_id),
            content=content,
            media=media or [],
            metadata=attach_session_context(
                channel=self.name,
                chat_id=str(chat_id),
                session_key=session_key or build_channel_session_key(self.name, str(chat_id)),
                metadata=attach_delivery_context(
                    channel=self.name,
                    chat_id=str(chat_id),
                    session_key=session_key or build_channel_session_key(self.name, str(chat_id)),
                    metadata=metadata,
                ),
            ),
            session_key_override=session_key,
        )

        await self.bus.publish_inbound(msg)

    async def _handle_pairing_command(self, sender_id: str, content: str, *, notify_target: str | None = None) -> str | None:
        """Handle pairing commands. Only the owner can execute mutating actions."""
        if not self._pairing:
            return None

        sid = str(sender_id)
        owner = self._pairing.owner
        # Check if sender is the owner
        is_owner = sid == owner
        if not is_owner and "|" in sid:
            is_owner = any(p == owner for p in sid.split("|") if p)
        if content == "/pairing" or content == "/pairing status":
            summary = self._pairing.describe_sender(sid)
            state = str(summary.get("state") or "unknown")
            if state == "owner":
                pending_ids = list(summary.get("pending_ids") or [])
                break_glass = self._pairing.get_break_glass_metadata()
                suffix = f"\nPending requests: {', '.join(pending_ids)}" if pending_ids else "\nPending requests: none"
                recovery_line = "\nRecovery code: none active"
                if break_glass.get("active"):
                    ttl_remaining = int(break_glass.get("ttl_remaining_s") or 0)
                    recovery_line = f"\nRecovery code: active ({ttl_remaining}s remaining)"
                return (
                    f"You are the current owner on this channel.\n"
                    f"Approved users: {summary.get('approved_count', 0)}\n"
                    f"Pending requests: {summary.get('pending_count', 0)}"
                    f"{suffix}"
                    f"{recovery_line}"
                )
            if state == "approved":
                return "You are approved to use this bot on this channel."
            if state == "pending":
                return "Your access request is still pending owner approval."
            return "You are not approved on this channel yet. Send a normal message to request access."

        if content == "/pairing pending":
            if not is_owner:
                return "Only the current owner can view the full pending request list."
            pending_ids = self._pairing.list_pending_ids()
            if not pending_ids:
                return "There are no pending pairing requests."
            return "Pending pairing requests:\n- " + "\n- ".join(pending_ids)

        if content.startswith("/pairing break-glass "):
            code = content.split(maxsplit=2)[2].strip()
            new_notify_target = self._pairing.claim_owner_with_break_glass_code(
                code,
                sender_id=sid,
                notify_target=notify_target,
            )
            if new_notify_target:
                await self.bus.publish_outbound(OutboundMessage(
                    channel=self.name,
                    chat_id=str(new_notify_target),
                    content="✅ Break-glass recovery succeeded. You are now the current owner for this channel.",
                ))
                return "Break-glass recovery succeeded."
            return "Invalid or expired break-glass recovery code."

        if content.startswith("/pairing recovery-code"):
            if not is_owner:
                return "Only the current owner can issue a break-glass recovery code."
            parts = content.split(maxsplit=2)
            ttl_s = 600
            if len(parts) == 3:
                try:
                    ttl_s = int(parts[2].strip())
                except ValueError:
                    return "Usage: /pairing recovery-code [ttl_seconds]"
            issued = self._pairing.issue_break_glass_code(ttl_s=ttl_s)
            return (
                "Break-glass recovery code issued.\n"
                f"Code: {issued['code']}\n"
                f"TTL: {issued['ttl_s']}s\n"
                "Store it safely. Anyone with this code can claim channel ownership once."
            )

        if not is_owner:
            return "Only the current owner can approve, deny, transfer, or inspect pending pairing requests."

        parts = content.split(maxsplit=1)
        if len(parts) < 2:
            return "Usage: /approve <user_id>, /deny <user_id>, /pairing pending, /pairing transfer <user_id>, /pairing recovery-code [ttl_seconds], or /pairing break-glass <code>"

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
                await self.bus.publish_outbound(OutboundMessage(
                    channel=self.name,
                    chat_id=str(notify_target),
                    content="❌ Access denied. Ask the current owner to re-approve if this was a mistake.",
                ))
                return f"Denied: {target}"
            return f"No pending request from: {target}"
        elif cmd == "/pairing":
            action_parts = target.split(maxsplit=1)
            action = action_parts[0].lower() if action_parts else ""
            payload = action_parts[1].strip() if len(action_parts) > 1 else ""
            if action == "transfer":
                if not payload:
                    return "Usage: /pairing transfer <user_id>"
                notify_target = self._pairing.transfer_owner(payload)
                if notify_target:
                    await self.bus.publish_outbound(OutboundMessage(
                        channel=self.name,
                        chat_id=str(notify_target),
                        content="✅ You are now the current owner for this channel.",
                    ))
                    return f"Ownership transferred to: {payload}"
                return f"Cannot transfer ownership to `{payload}`. Approve that user first."
            if action == "status":
                return await self._handle_pairing_command(sender_id, "/pairing status")
            if action == "pending":
                return await self._handle_pairing_command(sender_id, "/pairing pending")
            if action == "break-glass":
                if not payload:
                    return "Usage: /pairing break-glass <code>"
                return await self._handle_pairing_command(sender_id, f"/pairing break-glass {payload}", notify_target=notify_target)
            if action == "recovery-code":
                suffix = f" {payload}" if payload else ""
                return await self._handle_pairing_command(sender_id, f"/pairing recovery-code{suffix}", notify_target=notify_target)
            return "Usage: /pairing status, /pairing pending, /pairing transfer <user_id>, /pairing recovery-code [ttl_seconds], or /pairing break-glass <code>"
        return None
    
    @property
    def is_running(self) -> bool:
        """Check if the channel is running."""
        return self._running
