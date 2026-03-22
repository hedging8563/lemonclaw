from __future__ import annotations

from lemonclaw.channels.capabilities import ALL_CHANNEL_NAMES, CHANNEL_CAPABILITIES, get_channel_capability


def test_channel_capability_registry_covers_all_builtin_channels() -> None:
    assert set(CHANNEL_CAPABILITIES) == set(ALL_CHANNEL_NAMES)


def test_builtin_channels_do_not_drop_attachment_only_messages() -> None:
    assert all(
        capability.attachment_only_ingress != "drop"
        for capability in CHANNEL_CAPABILITIES.values()
    )


def test_selected_channel_capabilities_match_current_runtime_contract() -> None:
    assert get_channel_capability("qq").attachment_only_ingress == "full"
    assert get_channel_capability("whatsapp").media_delivery == "local_paths"
    assert get_channel_capability("dingtalk").attachment_only_ingress == "full"
    assert get_channel_capability("mochat").attachment_only_ingress == "best_effort"
    assert get_channel_capability("weixin").media_delivery == "marker_only"
    assert get_channel_capability("wecom").media_delivery == "mixed"
