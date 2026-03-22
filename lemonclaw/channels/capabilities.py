"""Static channel message/media capability contracts.

These contracts are the single source of truth for built-in channel ingress
expectations. They make attachment-only handling explicit so new channel work
does not silently regress back to text-only assumptions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

AttachmentIngress = Literal["full", "best_effort", "marker", "drop"]
MediaDelivery = Literal["local_paths", "mixed", "marker_only", "none"]
ChannelTransport = Literal["native", "bridge"]


@dataclass(frozen=True)
class ChannelCapability:
    """Explicit contract for built-in channel ingress semantics."""

    name: str
    transport: ChannelTransport
    attachment_only_ingress: AttachmentIngress
    media_delivery: MediaDelivery
    notes: str = ""


ALL_CHANNEL_NAMES: tuple[str, ...] = (
    "telegram",
    "whatsapp",
    "discord",
    "feishu",
    "mochat",
    "dingtalk",
    "email",
    "slack",
    "qq",
    "matrix",
    "weixin",
    "wecom",
)


CHANNEL_CAPABILITIES: dict[str, ChannelCapability] = {
    "telegram": ChannelCapability(
        name="telegram",
        transport="native",
        attachment_only_ingress="full",
        media_delivery="local_paths",
        notes="Downloads photo/audio/document media and forwards local paths.",
    ),
    "whatsapp": ChannelCapability(
        name="whatsapp",
        transport="bridge",
        attachment_only_ingress="full",
        media_delivery="local_paths",
        notes="Bridge downloads inbound image/video/document/audio before forwarding.",
    ),
    "discord": ChannelCapability(
        name="discord",
        transport="native",
        attachment_only_ingress="full",
        media_delivery="local_paths",
        notes="Downloads inbound attachments from Discord CDN and forwards local paths.",
    ),
    "feishu": ChannelCapability(
        name="feishu",
        transport="native",
        attachment_only_ingress="full",
        media_delivery="local_paths",
        notes="Downloads image/audio/file/media attachments and keeps attachment-only messages.",
    ),
    "mochat": ChannelCapability(
        name="mochat",
        transport="bridge",
        attachment_only_ingress="best_effort",
        media_delivery="local_paths",
        notes="Downloads attachment URLs when present in content/meta payloads; payload shape is bridge-dependent.",
    ),
    "dingtalk": ChannelCapability(
        name="dingtalk",
        transport="native",
        attachment_only_ingress="full",
        media_delivery="local_paths",
        notes="Uses robot messageFiles download flow to fetch inbound file/image payloads.",
    ),
    "email": ChannelCapability(
        name="email",
        transport="native",
        attachment_only_ingress="full",
        media_delivery="local_paths",
        notes="Extracts MIME attachments from inbound email and forwards local paths.",
    ),
    "slack": ChannelCapability(
        name="slack",
        transport="native",
        attachment_only_ingress="full",
        media_delivery="local_paths",
        notes="Preserves file_share events and downloads Slack attachments with bot auth.",
    ),
    "qq": ChannelCapability(
        name="qq",
        transport="native",
        attachment_only_ingress="full",
        media_delivery="local_paths",
        notes="Downloads botpy attachments and keeps attachment-only QQ messages on the main runtime path.",
    ),
    "matrix": ChannelCapability(
        name="matrix",
        transport="native",
        attachment_only_ingress="full",
        media_delivery="local_paths",
        notes="Handles media events directly and decrypts/downloads supported attachments.",
    ),
    "weixin": ChannelCapability(
        name="weixin",
        transport="bridge",
        attachment_only_ingress="marker",
        media_delivery="marker_only",
        notes="Bridge handles QR login and text replies; inbound media currently lands as markers until media download/send is added.",
    ),
    "wecom": ChannelCapability(
        name="wecom",
        transport="native",
        attachment_only_ingress="best_effort",
        media_delivery="mixed",
        notes="Downloads image media; voice/video/link/location remain marker/text-first.",
    ),
}


def get_channel_capability(name: str) -> ChannelCapability:
    """Return the declared ingress contract for a built-in channel."""

    try:
        return CHANNEL_CAPABILITIES[name]
    except KeyError as exc:  # pragma: no cover - guarded by tests
        raise KeyError(f"Unknown channel capability: {name}") from exc
