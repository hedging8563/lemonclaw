from __future__ import annotations

from lemonclaw.channels.session_context import (
    SESSION_CONTEXT_KEY,
    attach_session_context,
    build_session_context,
    get_session_context,
)


def test_build_session_context_maps_identity_and_runtime_fields() -> None:
    context = build_session_context(
        channel="telegram",
        chat_id="12345",
        session_key="telegram:acct_01:12345:456",
        metadata={
            "account_id": "acct_01",
            "message_thread_id": 456,
            "timezone": "Asia/Shanghai",
            "run_mode": "detached",
        },
    )

    assert context["session_key"] == "telegram:acct_01:12345:456"
    assert context["identity"] == {
        "channel": "telegram",
        "account": "acct_01",
        "chat": "12345",
        "thread": "456",
        "topic": "456",
    }
    assert context["timezone"] == "Asia/Shanghai"
    assert context["run_mode"] == "detached"


def test_attach_session_context_is_idempotent() -> None:
    metadata = attach_session_context(
        channel="slack",
        chat_id="C123",
        session_key="slack:C123:ts_1",
        metadata={"slack": {"thread_ts": "ts_1"}},
    )
    attached = attach_session_context(
        channel="slack",
        chat_id="C123",
        session_key="slack:C123:ts_1",
        metadata=metadata,
    )

    assert attached == metadata
    assert get_session_context(attached)["identity"]["thread"] == "ts_1"


def test_attach_session_context_defaults_run_mode_to_interactive() -> None:
    metadata = attach_session_context(
        channel="email",
        chat_id="alice@example.com",
        session_key="email:alice@example.com",
        metadata={"run_mode": "unknown-mode"},
    )

    assert metadata[SESSION_CONTEXT_KEY]["run_mode"] == "interactive"
