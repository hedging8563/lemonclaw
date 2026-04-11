from email.message import EmailMessage
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from lemonclaw.bus.events import OutboundMessage
from lemonclaw.bus.queue import MessageBus
from lemonclaw.channels.email import EmailChannel
from lemonclaw.config.schema import EmailConfig


def _make_config() -> EmailConfig:
    return EmailConfig(
        enabled=True,
        consent_granted=True,
        imap_host="imap.example.com",
        imap_port=993,
        imap_username="bot@example.com",
        imap_password="secret",
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_username="bot@example.com",
        smtp_password="secret",
        mark_seen=True,
    )


def _make_raw_email(
    from_addr: str = "alice@example.com",
    subject: str = "Hello",
    body: str = "This is the body.",
) -> bytes:
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = "bot@example.com"
    msg["Subject"] = subject
    msg["Message-ID"] = "<m1@example.com>"
    msg.set_content(body)
    return msg.as_bytes()


def _make_raw_email_with_attachment(
    from_addr: str = "alice@example.com",
    subject: str = "Attachment only",
    filename: str = "notes.pdf",
) -> bytes:
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = "bot@example.com"
    msg["Subject"] = subject
    msg["Message-ID"] = "<m2@example.com>"
    msg.set_content("")
    msg.add_attachment(
        b"%PDF-1.4 fake",
        maintype="application",
        subtype="pdf",
        filename=filename,
    )
    return msg.as_bytes()


def test_fetch_new_messages_parses_unseen_and_marks_seen(monkeypatch) -> None:
    raw = _make_raw_email(subject="Invoice", body="Please pay")

    class FakeIMAP:
        def __init__(self) -> None:
            self.store_calls: list[tuple[bytes, str, str]] = []

        def login(self, _user: str, _pw: str):
            return "OK", [b"logged in"]

        def select(self, _mailbox: str):
            return "OK", [b"1"]

        def search(self, *_args):
            return "OK", [b"1"]

        def fetch(self, _imap_id: bytes, _parts: str):
            return "OK", [(b"1 (UID 123 BODY[] {200})", raw), b")"]

        def store(self, imap_id: bytes, op: str, flags: str):
            self.store_calls.append((imap_id, op, flags))
            return "OK", [b""]

        def logout(self):
            return "BYE", [b""]

    fake = FakeIMAP()
    monkeypatch.setattr("lemonclaw.channels.email.imaplib.IMAP4_SSL", lambda _h, _p: fake)

    channel = EmailChannel(_make_config(), MessageBus())
    items = channel._fetch_new_messages()

    assert len(items) == 1
    assert items[0]["sender"] == "alice@example.com"
    assert items[0]["subject"] == "Invoice"
    assert "Please pay" in items[0]["content"]
    assert fake.store_calls == [(b"1", "+FLAGS", "\\Seen")]

    # Same UID should be deduped in-process.
    items_again = channel._fetch_new_messages()
    assert items_again == []


def test_extract_text_body_falls_back_to_html() -> None:
    msg = EmailMessage()
    msg["From"] = "alice@example.com"
    msg["To"] = "bot@example.com"
    msg["Subject"] = "HTML only"
    msg.add_alternative("<p>Hello<br>world</p>", subtype="html")

    text = EmailChannel._extract_text_body(msg)
    assert "Hello" in text
    assert "world" in text


def test_fetch_new_messages_keeps_attachment_only_email(monkeypatch, tmp_path) -> None:
    raw = _make_raw_email_with_attachment()

    class FakeIMAP:
        def login(self, _user: str, _pw: str):
            return "OK", [b"logged in"]

        def select(self, _mailbox: str):
            return "OK", [b"1"]

        def search(self, *_args):
            return "OK", [b"1"]

        def fetch(self, _imap_id: bytes, _parts: str):
            return "OK", [(b"1 (UID 456 BODY[] {200})", raw), b")"]

        def store(self, _imap_id: bytes, _op: str, _flags: str):
            return "OK", [b""]

        def logout(self):
            return "BYE", [b""]

    monkeypatch.setattr("lemonclaw.channels.email.imaplib.IMAP4_SSL", lambda _h, _p: FakeIMAP())
    monkeypatch.setattr("lemonclaw.channels.email.Path.home", lambda: tmp_path)

    channel = EmailChannel(_make_config(), MessageBus())
    items = channel._fetch_new_messages()

    assert len(items) == 1
    assert "[attachment:" in items[0]["content"]
    assert items[0]["media"] and items[0]["media"][0].endswith("notes.pdf")
    assert items[0]["metadata"]["attachments"][0]["filename"] == "notes.pdf"


def test_fetch_new_messages_sanitizes_attachment_path_when_uid_parse_fails(monkeypatch, tmp_path) -> None:
    msg = EmailMessage()
    msg["From"] = "alice@example.com"
    msg["To"] = "bot@example.com"
    msg["Subject"] = "Traversal attempt"
    msg["Message-ID"] = "../../escape/<attacker@example.com>"
    msg.set_content("")
    msg.add_attachment(
        b"malicious-bytes",
        maintype="application",
        subtype="octet-stream",
        filename="../../payload.bin",
    )
    raw = msg.as_bytes()

    class FakeIMAP:
        def login(self, _user: str, _pw: str):
            return "OK", [b"logged in"]

        def select(self, _mailbox: str):
            return "OK", [b"1"]

        def search(self, *_args):
            return "OK", [b"1"]

        def fetch(self, _imap_id: bytes, _parts: str):
            return "OK", [(b'1 (BODY[] {200})', raw), b")"]

        def store(self, _imap_id: bytes, _op: str, _flags: str):
            return "OK", [b""]

        def logout(self):
            return "BYE", [b""]

    monkeypatch.setattr("lemonclaw.channels.email.imaplib.IMAP4_SSL", lambda _h, _p: FakeIMAP())
    monkeypatch.setattr("lemonclaw.channels.email.Path.home", lambda: tmp_path)

    channel = EmailChannel(_make_config(), MessageBus())
    items = channel._fetch_new_messages()

    assert len(items) == 1
    media_dir = tmp_path / ".lemonclaw" / "media" / "email"
    attachment_path = Path(items[0]["media"][0])
    assert attachment_path.exists()
    assert attachment_path.parent == media_dir
    assert attachment_path.name.endswith("payload.bin")
    assert items[0]["metadata"]["attachments"][0]["path"] == str(attachment_path)


def test_fetch_new_messages_can_defer_attachment_materialization(monkeypatch, tmp_path) -> None:
    raw = _make_raw_email_with_attachment()

    class FakeIMAP:
        def login(self, _user: str, _pw: str):
            return "OK", [b"logged in"]

        def select(self, _mailbox: str):
            return "OK", [b"1"]

        def search(self, *_args):
            return "OK", [b"1"]

        def fetch(self, _imap_id: bytes, _parts: str):
            return "OK", [(b"1 (UID 456 BODY[] {200})", raw), b")"]

        def store(self, _imap_id: bytes, _op: str, _flags: str):
            return "OK", [b""]

        def logout(self):
            return "BYE", [b""]

    monkeypatch.setattr("lemonclaw.channels.email.imaplib.IMAP4_SSL", lambda _h, _p: FakeIMAP())
    monkeypatch.setattr("lemonclaw.channels.email.Path.home", lambda: tmp_path)

    channel = EmailChannel(_make_config(), MessageBus())
    items = channel._fetch_new_messages(materialize_attachments=False)

    assert len(items) == 1
    assert "[attachment: notes.pdf]" in items[0]["content"]
    assert items[0]["media"] == []
    assert items[0]["metadata"]["attachments"][0]["filename"] == "notes.pdf"
    assert "path" not in items[0]["metadata"]["attachments"][0]
    assert items[0]["_attachment_specs"]
    media_dir = tmp_path / ".lemonclaw" / "media" / "email"
    assert not media_dir.exists()


@pytest.mark.asyncio
async def test_start_returns_immediately_without_consent(monkeypatch) -> None:
    cfg = _make_config()
    cfg.consent_granted = False
    channel = EmailChannel(cfg, MessageBus())

    called = {"fetch": False}

    def _fake_fetch(*, materialize_attachments: bool = True):
        called["fetch"] = True
        return []

    monkeypatch.setattr(channel, "_fetch_new_messages", _fake_fetch)
    await channel.start()
    assert channel.is_running is False
    assert called["fetch"] is False


@pytest.mark.asyncio
async def test_start_allows_imap_only_mode_when_auto_reply_disabled(monkeypatch) -> None:
    cfg = _make_config()
    cfg.auto_reply_enabled = False
    cfg.smtp_host = ""
    cfg.smtp_username = ""
    cfg.smtp_password = ""
    channel = EmailChannel(cfg, MessageBus())

    called = {"fetch": False}

    def _fake_fetch(*, materialize_attachments: bool = True):
        assert materialize_attachments is False
        called["fetch"] = True
        channel._running = False
        return []

    monkeypatch.setattr(channel, "_fetch_new_messages", _fake_fetch)
    monkeypatch.setattr("lemonclaw.channels.email.asyncio.sleep", AsyncMock())
    await channel.start()

    assert called["fetch"] is True
    assert channel.is_running is False


@pytest.mark.asyncio
async def test_start_does_not_materialize_blocked_sender_attachments(monkeypatch, tmp_path) -> None:
    cfg = _make_config()
    cfg.allow_from = ["owner@example.com"]
    channel = EmailChannel(cfg, MessageBus())

    blocked_item = {
        "sender": "blocked@example.com",
        "subject": "Attachment only",
        "message_id": "<m2@example.com>",
        "content_base": "Email received.\nFrom: blocked@example.com\nSubject: Attachment only\nDate: now\n\n(empty email body)",
        "content": "Email received.\nFrom: blocked@example.com\nSubject: Attachment only\nDate: now\n\n(empty email body)\n\n[attachment: notes.pdf]",
        "media": [],
        "_attachment_specs": [
            {
                "message_key": "456",
                "index": 1,
                "filename": "notes.pdf",
                "content_type": "application/pdf",
                "payload": b"%PDF-1.4 fake",
                "size_bytes": 13,
            }
        ],
        "metadata": {
            "message_id": "<m2@example.com>",
            "subject": "Attachment only",
            "date": "now",
            "sender_email": "blocked@example.com",
            "uid": "456",
            "attachments": [
                {
                    "filename": "notes.pdf",
                    "content_type": "application/pdf",
                    "size_bytes": 13,
                }
            ],
        },
    }

    async def _fake_publish_feedback(*_args, **_kwargs):
        channel._running = False

    def _fake_fetch(*, materialize_attachments: bool = True):
        assert materialize_attachments is False
        return [blocked_item]

    channel._handle_message = AsyncMock(side_effect=AssertionError("should remain blocked"))
    monkeypatch.setattr(channel, "_fetch_new_messages", _fake_fetch)
    monkeypatch.setattr(channel, "_publish_feedback", _fake_publish_feedback)
    monkeypatch.setattr("lemonclaw.channels.email.Path.home", lambda: tmp_path)
    monkeypatch.setattr("lemonclaw.channels.email.asyncio.sleep", AsyncMock())

    await channel.start()

    media_dir = tmp_path / ".lemonclaw" / "media" / "email"
    assert not media_dir.exists()
    assert "blocked@example.com" not in channel._last_subject_by_chat
    assert "blocked@example.com" not in channel._last_message_id_by_chat


@pytest.mark.asyncio
async def test_start_materializes_allowed_sender_attachments_after_gate(monkeypatch, tmp_path) -> None:
    cfg = _make_config()
    cfg.allow_from = ["alice@example.com"]
    channel = EmailChannel(cfg, MessageBus())

    allowed_item = {
        "sender": "alice@example.com",
        "subject": "Attachment only",
        "message_id": "<m2@example.com>",
        "content_base": "Email received.\nFrom: alice@example.com\nSubject: Attachment only\nDate: now\n\n(empty email body)",
        "content": "Email received.\nFrom: alice@example.com\nSubject: Attachment only\nDate: now\n\n(empty email body)\n\n[attachment: notes.pdf]",
        "media": [],
        "_attachment_specs": [
            {
                "message_key": "456",
                "index": 1,
                "filename": "notes.pdf",
                "content_type": "application/pdf",
                "payload": b"%PDF-1.4 fake",
                "size_bytes": 13,
            }
        ],
        "metadata": {
            "message_id": "<m2@example.com>",
            "subject": "Attachment only",
            "date": "now",
            "sender_email": "alice@example.com",
            "uid": "456",
            "attachments": [
                {
                    "filename": "notes.pdf",
                    "content_type": "application/pdf",
                    "size_bytes": 13,
                }
            ],
        },
    }

    def _fake_fetch(*, materialize_attachments: bool = True):
        assert materialize_attachments is False
        channel._running = False
        return [allowed_item]

    channel._handle_message = AsyncMock()
    monkeypatch.setattr(channel, "_fetch_new_messages", _fake_fetch)
    monkeypatch.setattr("lemonclaw.channels.email.Path.home", lambda: tmp_path)
    monkeypatch.setattr("lemonclaw.channels.email.asyncio.sleep", AsyncMock())

    await channel.start()

    channel._handle_message.assert_awaited_once()
    kwargs = channel._handle_message.await_args.kwargs
    assert kwargs["pairing_checked"] is True
    assert kwargs["media"] and kwargs["media"][0].endswith("notes.pdf")
    assert "[attachment: " in kwargs["content"]
    attachment_meta = kwargs["metadata"]["attachments"][0]
    assert attachment_meta["path"].endswith("notes.pdf")
    assert Path(attachment_meta["path"]).exists()
    assert channel._last_subject_by_chat["alice@example.com"] == "Attachment only"
    assert channel._last_message_id_by_chat["alice@example.com"] == "<m2@example.com>"


@pytest.mark.asyncio
async def test_send_uses_smtp_and_reply_subject(monkeypatch) -> None:
    class FakeSMTP:
        def __init__(self, _host: str, _port: int, timeout: int = 30) -> None:
            self.timeout = timeout
            self.started_tls = False
            self.logged_in = False
            self.sent_messages: list[EmailMessage] = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def starttls(self, context=None):
            self.started_tls = True

        def login(self, _user: str, _pw: str):
            self.logged_in = True

        def send_message(self, msg: EmailMessage):
            self.sent_messages.append(msg)

    fake_instances: list[FakeSMTP] = []

    def _smtp_factory(host: str, port: int, timeout: int = 30):
        instance = FakeSMTP(host, port, timeout=timeout)
        fake_instances.append(instance)
        return instance

    monkeypatch.setattr("lemonclaw.channels.email.smtplib.SMTP", _smtp_factory)

    channel = EmailChannel(_make_config(), MessageBus())
    channel._last_subject_by_chat["alice@example.com"] = "Invoice #42"
    channel._last_message_id_by_chat["alice@example.com"] = "<m1@example.com>"

    await channel.send(
        OutboundMessage(
            channel="email",
            chat_id="alice@example.com",
            content="Acknowledged.",
        )
    )

    assert len(fake_instances) == 1
    smtp = fake_instances[0]
    assert smtp.started_tls is True
    assert smtp.logged_in is True
    assert len(smtp.sent_messages) == 1
    sent = smtp.sent_messages[0]
    assert sent["Subject"] == "Re: Invoice #42"
    assert sent["To"] == "alice@example.com"
    assert sent["In-Reply-To"] == "<m1@example.com>"


@pytest.mark.asyncio
async def test_send_skips_reply_when_auto_reply_disabled(monkeypatch) -> None:
    """When auto_reply_enabled=False, replies should be skipped but proactive sends allowed."""
    class FakeSMTP:
        def __init__(self, _host: str, _port: int, timeout: int = 30) -> None:
            self.sent_messages: list[EmailMessage] = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def starttls(self, context=None):
            return None

        def login(self, _user: str, _pw: str):
            return None

        def send_message(self, msg: EmailMessage):
            self.sent_messages.append(msg)

    fake_instances: list[FakeSMTP] = []

    def _smtp_factory(host: str, port: int, timeout: int = 30):
        instance = FakeSMTP(host, port, timeout=timeout)
        fake_instances.append(instance)
        return instance

    monkeypatch.setattr("lemonclaw.channels.email.smtplib.SMTP", _smtp_factory)

    cfg = _make_config()
    cfg.auto_reply_enabled = False
    channel = EmailChannel(cfg, MessageBus())

    # Mark alice as someone who sent us an email (making this a "reply")
    channel._last_subject_by_chat["alice@example.com"] = "Previous email"

    # Reply should be skipped (auto_reply_enabled=False)
    await channel.send(
        OutboundMessage(
            channel="email",
            chat_id="alice@example.com",
            content="Should not send.",
        )
    )
    assert fake_instances == []

    # Reply with force_send=True should be sent
    await channel.send(
        OutboundMessage(
            channel="email",
            chat_id="alice@example.com",
            content="Force send.",
            metadata={"force_send": True},
        )
    )
    assert len(fake_instances) == 1
    assert len(fake_instances[0].sent_messages) == 1


@pytest.mark.asyncio
async def test_send_proactive_email_when_auto_reply_disabled(monkeypatch) -> None:
    """Proactive emails (not replies) should be sent even when auto_reply_enabled=False."""
    class FakeSMTP:
        def __init__(self, _host: str, _port: int, timeout: int = 30) -> None:
            self.sent_messages: list[EmailMessage] = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def starttls(self, context=None):
            return None

        def login(self, _user: str, _pw: str):
            return None

        def send_message(self, msg: EmailMessage):
            self.sent_messages.append(msg)

    fake_instances: list[FakeSMTP] = []

    def _smtp_factory(host: str, port: int, timeout: int = 30):
        instance = FakeSMTP(host, port, timeout=timeout)
        fake_instances.append(instance)
        return instance

    monkeypatch.setattr("lemonclaw.channels.email.smtplib.SMTP", _smtp_factory)

    cfg = _make_config()
    cfg.auto_reply_enabled = False
    channel = EmailChannel(cfg, MessageBus())

    # bob@example.com has never sent us an email (proactive send)
    # This should be sent even with auto_reply_enabled=False
    await channel.send(
        OutboundMessage(
            channel="email",
            chat_id="bob@example.com",
            content="Hello, this is a proactive email.",
        )
    )
    assert len(fake_instances) == 1
    assert len(fake_instances[0].sent_messages) == 1
    sent = fake_instances[0].sent_messages[0]
    assert sent["To"] == "bob@example.com"


@pytest.mark.asyncio
async def test_send_skips_when_consent_not_granted(monkeypatch) -> None:
    class FakeSMTP:
        def __init__(self, _host: str, _port: int, timeout: int = 30) -> None:
            self.sent_messages: list[EmailMessage] = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def starttls(self, context=None):
            return None

        def login(self, _user: str, _pw: str):
            return None

        def send_message(self, msg: EmailMessage):
            self.sent_messages.append(msg)

    called = {"smtp": False}

    def _smtp_factory(host: str, port: int, timeout: int = 30):
        called["smtp"] = True
        return FakeSMTP(host, port, timeout=timeout)

    monkeypatch.setattr("lemonclaw.channels.email.smtplib.SMTP", _smtp_factory)

    cfg = _make_config()
    cfg.consent_granted = False
    channel = EmailChannel(cfg, MessageBus())
    await channel.send(
        OutboundMessage(
            channel="email",
            chat_id="alice@example.com",
            content="Should not send.",
            metadata={"force_send": True},
        )
    )
    assert called["smtp"] is False


def test_fetch_messages_between_dates_uses_imap_since_before_without_mark_seen(monkeypatch) -> None:
    raw = _make_raw_email(subject="Status", body="Yesterday update")

    class FakeIMAP:
        def __init__(self) -> None:
            self.search_args = None
            self.store_calls: list[tuple[bytes, str, str]] = []

        def login(self, _user: str, _pw: str):
            return "OK", [b"logged in"]

        def select(self, _mailbox: str):
            return "OK", [b"1"]

        def search(self, *_args):
            self.search_args = _args
            return "OK", [b"5"]

        def fetch(self, _imap_id: bytes, _parts: str):
            return "OK", [(b"5 (UID 999 BODY[] {200})", raw), b")"]

        def store(self, imap_id: bytes, op: str, flags: str):
            self.store_calls.append((imap_id, op, flags))
            return "OK", [b""]

        def logout(self):
            return "BYE", [b""]

    fake = FakeIMAP()
    monkeypatch.setattr("lemonclaw.channels.email.imaplib.IMAP4_SSL", lambda _h, _p: fake)

    channel = EmailChannel(_make_config(), MessageBus())
    items = channel.fetch_messages_between_dates(
        start_date=date(2026, 2, 6),
        end_date=date(2026, 2, 7),
        limit=10,
    )

    assert len(items) == 1
    assert items[0]["subject"] == "Status"
    # search(None, "SINCE", "06-Feb-2026", "BEFORE", "07-Feb-2026")
    assert fake.search_args is not None
    assert fake.search_args[1:] == ("SINCE", "06-Feb-2026", "BEFORE", "07-Feb-2026")
    assert fake.store_calls == []
