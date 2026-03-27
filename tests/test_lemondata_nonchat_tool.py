from __future__ import annotations

import json

import pytest

from lemonclaw.agent.tools.lemondata_nonchat import LemonDataNonChatTool


@pytest.mark.asyncio
async def test_lemondata_nonchat_discover_returns_live_models(monkeypatch: pytest.MonkeyPatch) -> None:
    tool = LemonDataNonChatTool()

    async def _fake_fetch(path: str, *, method: str = "GET", body=None):
        assert path == "/v1/models?category=video"
        return {
            "ok": True,
            "body": {
                "data": [
                    {"id": "sora-2", "lemondata": {"category": "video", "tags": ["video"]}},
                    {"id": "veo3.1", "lemondata": {"category": "video", "tags": ["video", "premium"]}},
                ]
            },
        }

    monkeypatch.setattr(tool, "_fetch_json", _fake_fetch)
    result = json.loads(await tool.execute(action="discover", category="video"))

    assert result["ok"] is True
    assert result["model_count"] == 2
    assert result["models"][0]["id"] == "sora-2"


@pytest.mark.asyncio
async def test_lemondata_nonchat_request_rejects_model_not_in_live_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    tool = LemonDataNonChatTool()

    async def _fake_fetch(path: str, *, method: str = "GET", body=None):
        assert path == "/v1/models?category=video"
        return {
            "ok": True,
            "body": {"data": [{"id": "sora-2", "lemondata": {"category": "video"}}]},
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
        if path == "/v1/models?category=video":
            return {
                "ok": True,
                "body": {"data": [{"id": "sora-2", "lemondata": {"category": "video"}}]},
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
        ("GET", "/v1/models?category=video"),
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
