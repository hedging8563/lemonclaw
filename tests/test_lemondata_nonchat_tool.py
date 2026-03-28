from __future__ import annotations

import json

import pytest

from lemonclaw.agent.tools.lemondata_nonchat import LemonDataNonChatTool


@pytest.mark.asyncio
async def test_lemondata_nonchat_discover_returns_live_models(monkeypatch: pytest.MonkeyPatch) -> None:
    tool = LemonDataNonChatTool()

    async def _fake_fetch(path: str, *, method: str = "GET", body=None):
        assert path == "/v1/models?category=video&recommended_for=video"
        return {
            "ok": True,
            "body": {
                "data": [
                    {
                        "id": "sora-2",
                        "lemondata": {
                            "category": "video",
                            "capabilities": ["video"],
                            "agent_preferences": {
                                "video": {
                                    "preferred_rank": 1,
                                    "success_rate_24h": 0.95,
                                    "sample_count_24h": 12,
                                    "status": "ready",
                                    "updated_at": "2026-03-28T00:00:00.000Z",
                                }
                            },
                        },
                    },
                    {"id": "veo3.1", "lemondata": {"category": "video", "capabilities": ["video", "premium"]}},
                ]
            },
        }

    monkeypatch.setattr(tool, "_fetch_json", _fake_fetch)
    result = json.loads(await tool.execute(action="discover", category="video"))

    assert result["ok"] is True
    assert result["model_count"] == 2
    assert result["models"][0]["id"] == "sora-2"
    assert result["models"][0]["preferred_rank"] == 1
    assert result["snapshot_at"] == "2026-03-28T00:00:00.000Z"


@pytest.mark.asyncio
async def test_lemondata_nonchat_request_rejects_model_not_in_live_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    tool = LemonDataNonChatTool()

    async def _fake_fetch(path: str, *, method: str = "GET", body=None):
        assert path == "/v1/models?category=video&recommended_for=video"
        return {
            "ok": True,
            "body": {"data": [{"id": "sora-2", "lemondata": {"category": "video", "agent_preferences": {"video": {"status": "ready"}}}}]},
        }

    monkeypatch.setattr(tool, "_fetch_json", _fake_fetch)
    result = json.loads(
        await tool.execute(
            action="request",
            category="video",
            model="hailuo-2.3",
            payload={"prompt": "test"},
        )
    )

    assert result["ok"] is False
    assert "not currently available" in result["error"]
    assert result["requested_model"] == "hailuo-2.3"


@pytest.mark.asyncio
async def test_lemondata_nonchat_request_executes_only_after_fresh_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    tool = LemonDataNonChatTool()
    calls: list[tuple[str, str]] = []

    async def _fake_fetch(path: str, *, method: str = "GET", body=None):
        calls.append((method, path))
        if path == "/v1/models?category=video&recommended_for=video":
            return {
                "ok": True,
                "body": {"data": [{"id": "sora-2", "lemondata": {"category": "video", "agent_preferences": {"video": {"status": "ready"}}}}]},
            }
        if path == "/v1/videos/generations":
            return {
                "ok": True,
                "body": {"id": "task_123", "status": "pending", "model": body["model"]},
            }
        raise AssertionError(path)

    monkeypatch.setattr(tool, "_fetch_json", _fake_fetch)
    result = json.loads(
        await tool.execute(
            action="request",
            category="video",
            model="sora-2",
            payload={"prompt": "test"},
        )
    )

    assert result["ok"] is True
    assert result["response"]["model"] == "sora-2"
    assert calls == [
        ("GET", "/v1/models?category=video&recommended_for=video"),
        ("POST", "/v1/videos/generations"),
    ]


@pytest.mark.asyncio
async def test_lemondata_nonchat_request_refuses_without_fresh_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    tool = LemonDataNonChatTool()

    async def _fake_fetch(path: str, *, method: str = "GET", body=None):
        return {"ok": False, "error": "HTTP 503", "body": None}

    monkeypatch.setattr(tool, "_fetch_json", _fake_fetch)
    result = json.loads(
        await tool.execute(
            action="request",
            category="video",
            model="sora-2",
            payload={"prompt": "test"},
        )
    )

    assert result["ok"] is False
    assert "Fresh LemonData model discovery failed" in result["error"]


@pytest.mark.asyncio
async def test_lemondata_nonchat_request_auto_selects_and_falls_back_on_retryable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    tool = LemonDataNonChatTool()
    calls: list[tuple[str, str, dict | None]] = []

    async def _fake_fetch(path: str, *, method: str = "GET", body=None):
        calls.append((method, path, body))
        if path == "/v1/models?category=image&recommended_for=image":
            return {
                "ok": True,
                "body": {
                    "data": [
                        {
                            "id": "gemini-2.5-flash-image",
                            "lemondata": {
                                "category": "image",
                                "agent_preferences": {
                                    "image": {
                                        "preferred_rank": 1,
                                        "success_rate_24h": 0.98,
                                        "sample_count_24h": 50,
                                        "status": "ready",
                                        "updated_at": "2026-03-28T00:00:00.000Z",
                                    }
                                },
                            },
                        },
                        {
                            "id": "imagen-4",
                            "lemondata": {
                                "category": "image",
                                "agent_preferences": {
                                    "image": {
                                        "preferred_rank": 2,
                                        "success_rate_24h": 0.95,
                                        "sample_count_24h": 40,
                                        "status": "ready",
                                        "updated_at": "2026-03-28T00:00:00.000Z",
                                    }
                                },
                            },
                        },
                    ]
                },
            }
        if path == "/v1/images/generations" and body and body["model"] == "gemini-2.5-flash-image":
            return {
                "ok": False,
                "error": "HTTP 503",
                "body": {"error": {"code": "all_channels_failed", "retryable": True}},
            }
        if path == "/v1/images/generations" and body and body["model"] == "imagen-4":
            return {
                "ok": True,
                "body": {"id": "img_123", "model": "imagen-4"},
            }
        raise AssertionError((method, path, body))

    monkeypatch.setattr(tool, "_fetch_json", _fake_fetch)
    result = json.loads(
        await tool.execute(
            action="request",
            category="image",
            payload={"prompt": "draw a skyline"},
        )
    )

    assert result["ok"] is True
    assert result["selected_model"] == "imagen-4"
    assert result["attempted_models"] == ["gemini-2.5-flash-image", "imagen-4"]
    assert result["fallback_reason"] == "all_channels_failed"


@pytest.mark.asyncio
async def test_lemondata_nonchat_translation_requires_text_and_target_language(monkeypatch: pytest.MonkeyPatch) -> None:
    tool = LemonDataNonChatTool()

    async def _fake_fetch(path: str, *, method: str = "GET", body=None):
        if path == "/v1/models?category=translation&recommended_for=translation":
            return {
                "ok": True,
                "body": {
                    "data": [
                        {
                            "id": "gemini-translation-pro",
                            "lemondata": {
                                "category": "translation",
                                "agent_preferences": {"translation": {"status": "ready"}},
                            },
                        }
                    ]
                },
            }
        raise AssertionError(path)

    monkeypatch.setattr(tool, "_fetch_json", _fake_fetch)
    result = json.loads(
        await tool.execute(
            action="request",
            category="translation",
            payload={"text": "hello"},
        )
    )

    assert result["ok"] is False
    assert "target_language" in result["error"]
