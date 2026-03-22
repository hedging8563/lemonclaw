from __future__ import annotations

import pytest

from lemonclaw.channels.weixin_bridge_runtime import (
    estimate_weixin_send_timeout,
    send_weixin_text,
)
from lemonclaw.config.schema import WeixinConfig


def test_estimate_weixin_send_timeout_scales_with_media_size(tmp_path) -> None:
    media = tmp_path / "voice.mp3"
    media.write_bytes(b"x" * (1024 * 1024))

    timeout = estimate_weixin_send_timeout([str(media)])

    assert timeout == pytest.approx(81.2)


def test_estimate_weixin_send_timeout_ignores_missing_media() -> None:
    assert estimate_weixin_send_timeout(["/tmp/does-not-exist"]) == 20.0


def test_send_weixin_text_uses_estimated_timeout_for_media(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    media = tmp_path / "voice.mp3"
    media.write_bytes(b"x" * (1024 * 1024))
    captured: dict[str, object] = {}

    def fake_bridge_request(
        config: WeixinConfig,
        path: str,
        *,
        method: str = "GET",
        body: dict[str, object] | None = None,
        timeout: float = 15.0,
    ) -> dict[str, object]:
        captured["config"] = config
        captured["path"] = path
        captured["method"] = method
        captured["body"] = body
        captured["timeout"] = timeout
        return {"ok": True}

    monkeypatch.setattr(
        "lemonclaw.channels.weixin_bridge_runtime._bridge_request",
        fake_bridge_request,
    )

    send_weixin_text(
        WeixinConfig(enabled=True, allow_from=["*"]),
        account_id="bot-1",
        to="wx-user-9",
        text="hello",
        context_token="ctx-123",
        media_paths=[str(media)],
    )

    assert captured["path"] == "/send"
    assert captured["method"] == "POST"
    assert captured["timeout"] == pytest.approx(81.2)
    assert captured["body"] == {
        "accountId": "bot-1",
        "to": "wx-user-9",
        "text": "hello",
        "contextToken": "ctx-123",
        "mediaPaths": [str(media)],
    }
