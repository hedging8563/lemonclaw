from lemonclaw.channels.session_keys import build_channel_session_key, build_system_session_key


def test_build_channel_session_key_without_optional_dimensions() -> None:
    assert build_channel_session_key("telegram", "12345") == "telegram:12345"


def test_build_channel_session_key_with_thread_dimension() -> None:
    assert build_channel_session_key("telegram", "12345", thread_id=456) == "telegram:12345:456"


def test_build_channel_session_key_prefers_account_before_chat() -> None:
    assert build_channel_session_key("weixin", "peer-9", account_id="bot-1") == "weixin:bot-1:peer-9"


def test_build_channel_session_key_preserves_empty_account_slot_when_requested() -> None:
    assert build_channel_session_key(
        "weixin",
        "peer-9",
        account_id="",
        preserve_empty_account_slot=True,
    ) == "weixin::peer-9"


def test_build_channel_session_key_uses_topic_when_thread_missing() -> None:
    assert build_channel_session_key("slack", "C123", topic_id="ts-1") == "slack:C123:ts-1"


def test_build_channel_session_key_keeps_zero_thread_dimension() -> None:
    assert build_channel_session_key("telegram", "12345", thread_id=0) == "telegram:12345:0"


def test_build_system_session_key_is_explicit() -> None:
    assert build_system_session_key("heartbeat") == "system:heartbeat"
