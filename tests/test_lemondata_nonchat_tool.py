from __future__ import annotations

import json
from pathlib import Path

import pytest

from lemonclaw.agent.tools.lemondata_nonchat import LemonDataNonChatTool


@pytest.mark.asyncio
async def test_lemondata_nonchat_discover_returns_live_models(monkeypatch: pytest.MonkeyPatch) -> None:
    tool = LemonDataNonChatTool()
    calls: list[str] = []

    async def _fake_fetch(path: str, *, method: str = "GET", body=None):
        calls.append(path)
        if path == "/v1/models?category=video":
            return {
                "ok": True,
                "body": {
                    "data": [
                        {"id": "seedance-2.0", "lemondata": {"category": "video", "capabilities": ["video", "text-to-video"]}},
                        {"id": "sora-2", "lemondata": {"category": "video", "capabilities": ["video"]}},
                    ]
                },
            }
        if path == "/v1/models?category=video&recommended_for=video":
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
                    ]
                },
            }
        raise AssertionError(path)

    monkeypatch.setattr(tool, "_fetch_json", _fake_fetch)
    result = json.loads(await tool.execute(action="discover", category="video"))

    assert result["ok"] is True
    assert result["model_count"] == 2
    assert result["models"][0]["id"] == "seedance-2.0"
    assert result["models"][0]["recommended"] is False
    assert result["models"][1]["id"] == "sora-2"
    assert result["models"][1]["preferred_rank"] == 1
    assert result["models"][1]["recommended"] is True
    assert result["snapshot_at"] == "2026-03-28T00:00:00.000Z"
    assert calls == [
        "/v1/models?category=video",
        "/v1/models?category=video&recommended_for=video",
    ]
    assert result["catalog_total"] == 2
    assert result["returned_model_count"] == 2
    assert result["truncated"] is False
    assert result["request_guidance"]["default_endpoint"] == "/v1/videos/generations"


@pytest.mark.asyncio
async def test_lemondata_nonchat_request_rejects_model_not_in_live_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    tool = LemonDataNonChatTool()

    async def _fake_fetch(path: str, *, method: str = "GET", body=None):
        assert path == "/v1/models?category=video"
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
        if path == "/v1/models?category=video":
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
    assert "Fresh LemonData category discovery failed" in result["error"]


@pytest.mark.asyncio
async def test_lemondata_nonchat_request_allows_explicit_catalog_model_absent_from_recommendation_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = LemonDataNonChatTool()
    calls: list[tuple[str, str]] = []

    async def _fake_fetch(path: str, *, method: str = "GET", body=None):
        calls.append((method, path))
        if path == "/v1/models?category=video":
            return {
                "ok": True,
                "body": {"data": [{"id": "seedance-2.0", "lemondata": {"category": "video"}}]},
            }
        if path == "/v1/videos/generations":
            return {
                "ok": True,
                "body": {"id": "task_456", "status": "pending", "model": body["model"]},
            }
        raise AssertionError(path)

    monkeypatch.setattr(tool, "_fetch_json", _fake_fetch)
    result = json.loads(
        await tool.execute(
            action="request",
            category="video",
            model="seedance-2.0",
            payload={"prompt": "test"},
        )
    )

    assert result["ok"] is True
    assert result["selected_model"] == "seedance-2.0"
    assert result["response"]["model"] == "seedance-2.0"
    assert calls == [
        ("GET", "/v1/models?category=video"),
        ("POST", "/v1/videos/generations"),
    ]


@pytest.mark.asyncio
async def test_lemondata_nonchat_request_allows_explicit_catalog_model_beyond_display_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = LemonDataNonChatTool()

    async def _fake_fetch(path: str, *, method: str = "GET", body=None):
        if path == "/v1/models?category=video":
            return {
                "ok": True,
                "body": {
                    "data": [
                        {"id": "sora-2", "lemondata": {"category": "video"}},
                        {"id": "seedance-2.0-fast", "lemondata": {"category": "video"}},
                    ]
                },
            }
        if path == "/v1/videos/generations":
            return {
                "ok": True,
                "body": {"id": "task_789", "status": "pending", "model": body["model"]},
            }
        raise AssertionError(path)

    monkeypatch.setattr(tool, "_fetch_json", _fake_fetch)
    result = json.loads(
        await tool.execute(
            action="request",
            category="video",
            model="seedance-2.0-fast",
            limit=1,
            payload={"prompt": "test"},
        )
    )

    assert result["ok"] is True
    assert result["selected_model"] == "seedance-2.0-fast"
    assert result["response"]["model"] == "seedance-2.0-fast"


@pytest.mark.asyncio
async def test_lemondata_nonchat_request_auto_selects_and_falls_back_on_retryable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    tool = LemonDataNonChatTool()
    calls: list[tuple[str, str, dict | None]] = []

    async def _fake_fetch(path: str, *, method: str = "GET", body=None):
        calls.append((method, path, body))
        if path == "/v1/models?category=image":
            return {
                "ok": True,
                "body": {
                    "data": [
                        {"id": "gemini-2.5-flash-image", "lemondata": {"category": "image"}},
                        {"id": "imagen-4", "lemondata": {"category": "image"}},
                    ]
                },
            }
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
async def test_lemondata_nonchat_request_auto_selects_catalog_fallback_when_recommendation_snapshot_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = LemonDataNonChatTool()
    calls: list[tuple[str, str, dict | None]] = []

    async def _fake_fetch(path: str, *, method: str = "GET", body=None):
        calls.append((method, path, body))
        if path == "/v1/models?category=image":
            return {
                "ok": True,
                "body": {
                    "data": [
                        {"id": "catalog-a", "lemondata": {"category": "image"}},
                        {"id": "catalog-b", "lemondata": {"category": "image"}},
                    ]
                },
            }
        if path == "/v1/models?category=image&recommended_for=image":
            return {"ok": False, "error": "HTTP 503", "body": None}
        if path == "/v1/images/generations" and body and body["model"] == "catalog-a":
            return {"ok": True, "body": {"id": "img_ok", "model": "catalog-a"}}
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
    assert result["selected_model"] == "catalog-a"
    assert result["attempted_models"] == ["catalog-a"]
    assert result["selection_reason"] == "recommendation_snapshot_failed"
    assert result["response"]["model"] == "catalog-a"
    assert calls == [
        ("GET", "/v1/models?category=image", None),
        ("GET", "/v1/models?category=image&recommended_for=image", None),
        ("POST", "/v1/images/generations", {"prompt": "draw a skyline", "model": "catalog-a"}),
    ]


@pytest.mark.asyncio
async def test_lemondata_nonchat_request_auto_selects_catalog_fallback_when_recommendations_are_not_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = LemonDataNonChatTool()

    async def _fake_fetch(path: str, *, method: str = "GET", body=None):
        if path == "/v1/models?category=image":
            return {
                "ok": True,
                "body": {
                    "data": [
                        {"id": "catalog-a", "lemondata": {"category": "image"}},
                        {"id": "catalog-b", "lemondata": {"category": "image"}},
                    ]
                },
            }
        if path == "/v1/models?category=image&recommended_for=image":
            return {
                "ok": True,
                "body": {
                    "data": [
                        {
                            "id": "catalog-a",
                            "lemondata": {
                                "category": "image",
                                "agent_preferences": {
                                    "image": {
                                        "preferred_rank": 1,
                                        "status": "pending",
                                        "updated_at": "2026-03-28T00:00:00.000Z",
                                    }
                                },
                            },
                        },
                        {
                            "id": "catalog-b",
                            "lemondata": {
                                "category": "image",
                                "agent_preferences": {
                                    "image": {
                                        "preferred_rank": 2,
                                        "status": "pending",
                                        "updated_at": "2026-03-28T00:00:00.000Z",
                                    }
                                },
                            },
                        },
                    ]
                },
            }
        if path == "/v1/images/generations" and body and body["model"] == "catalog-a":
            return {"ok": True, "body": {"id": "img_ready", "model": "catalog-a"}}
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
    assert result["selected_model"] == "catalog-a"
    assert result["attempted_models"] == ["catalog-a"]
    assert result["selection_reason"] == "no_ready_recommendations"
    assert result["response"]["model"] == "catalog-a"


@pytest.mark.asyncio
async def test_lemondata_nonchat_translation_requires_text_and_target_language(monkeypatch: pytest.MonkeyPatch) -> None:
    tool = LemonDataNonChatTool()

    async def _fake_fetch(path: str, *, method: str = "GET", body=None):
        if path == "/v1/models?category=translation":
            return {
                "ok": True,
                "body": {
                    "data": [
                        {
                            "id": "gemini-translation-pro",
                            "lemondata": {"category": "translation"},
                        }
                    ]
                },
            }
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


@pytest.mark.asyncio
async def test_lemondata_nonchat_request_retries_on_transport_error(monkeypatch: pytest.MonkeyPatch) -> None:
    tool = LemonDataNonChatTool()

    async def _fake_fetch(path: str, *, method: str = "GET", body=None):
        if path == "/v1/models?category=image":
            return {
                "ok": True,
                "body": {
                    "data": [
                        {"id": "model-a", "lemondata": {"category": "image"}},
                        {"id": "model-b", "lemondata": {"category": "image"}},
                    ]
                },
            }
        if path == "/v1/models?category=image&recommended_for=image":
            return {
                "ok": True,
                "body": {
                    "data": [
                        {
                            "id": "model-a",
                            "lemondata": {"category": "image", "agent_preferences": {"image": {"status": "ready", "preferred_rank": 1}}},
                        },
                        {
                            "id": "model-b",
                            "lemondata": {"category": "image", "agent_preferences": {"image": {"status": "ready", "preferred_rank": 2}}},
                        },
                    ]
                },
            }
        if path == "/v1/images/generations" and body and body["model"] == "model-a":
            return {"ok": False, "error": "connect timeout", "body": None, "transport_error": True}
        if path == "/v1/images/generations" and body and body["model"] == "model-b":
            return {"ok": True, "body": {"id": "img_ok", "model": "model-b"}}
        raise AssertionError((path, method, body))

    monkeypatch.setattr(tool, "_fetch_json", _fake_fetch)
    result = json.loads(
        await tool.execute(
            action="request",
            category="image",
            payload={"prompt": "fallback on transport"},
        )
    )

    assert result["ok"] is True
    assert result["selected_model"] == "model-b"
    assert result["attempted_models"] == ["model-a", "model-b"]
    assert result["fallback_reason"] == "transport_error"


@pytest.mark.asyncio
async def test_lemondata_nonchat_image_generation_converts_local_file_to_data_url(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    tool = LemonDataNonChatTool(workspace=tmp_path)
    source = tmp_path / "source.png"
    source.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    seen_request: dict[str, object] = {}

    async def _fake_fetch(path: str, *, method: str = "GET", body=None):
        if path == "/v1/models?category=image":
            return {
                "ok": True,
                "body": {"data": [{"id": "gpt-image-1", "lemondata": {"category": "image"}}]},
            }
        if path == "/v1/images/generations":
            seen_request["body"] = body
            return {
                "ok": True,
                "body": {"id": "img_local", "model": body["model"], "image_url": body.get("image_url")},
            }
        raise AssertionError((path, method, body))

    monkeypatch.setattr(tool, "_fetch_json", _fake_fetch)
    result = json.loads(
        await tool.execute(
            action="request",
            category="image",
            model="gpt-image-1",
            payload={"prompt": "edit this", "operation": "image-to-image"},
            files={"image_path": "source.png"},
        )
    )

    assert result["ok"] is True
    body = seen_request["body"]
    assert isinstance(body, dict)
    assert str(body["image_url"]).startswith("data:image/png;base64,")
    assert result["request_mode"] == "json"


@pytest.mark.asyncio
async def test_lemondata_nonchat_image_edit_supports_multipart_local_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    tool = LemonDataNonChatTool(workspace=tmp_path)
    image = tmp_path / "edit-source.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nsource")
    mask = tmp_path / "edit-mask.png"
    mask.write_bytes(b"\x89PNG\r\n\x1a\nmask")
    seen_request: dict[str, object] = {}

    async def _fake_fetch(path: str, *, method: str = "GET", body=None):
        if path == "/v1/models?category=image":
            return {
                "ok": True,
                "body": {"data": [{"id": "flux-kontext-pro", "lemondata": {"category": "image"}}]},
            }
        raise AssertionError((path, method, body))

    async def _fake_fetch_response(path: str, *, method: str = "GET", body=None, files=None, save_to=None):
        seen_request["path"] = path
        seen_request["body"] = body
        seen_request["files"] = files
        seen_request["save_to"] = save_to
        return {
            "ok": True,
            "body": {"id": "edit_123", "model": body["model"]},
            "content_type": "application/json",
        }

    monkeypatch.setattr(tool, "_fetch_json", _fake_fetch)
    monkeypatch.setattr(tool, "_fetch_response", _fake_fetch_response)
    result = json.loads(
        await tool.execute(
            action="request",
            category="image",
            endpoint="/v1/images/edits",
            model="flux-kontext-pro",
            payload={"prompt": "replace the background"},
            files={"image_path": "edit-source.png", "mask_path": "edit-mask.png"},
        )
    )

    assert result["ok"] is True
    assert result["request_mode"] == "multipart"
    assert seen_request["path"] == "/v1/images/edits"
    assert seen_request["body"] == {"prompt": "replace the background", "model": "flux-kontext-pro"}
    assert seen_request["files"] == {"image_path": "edit-source.png", "mask_path": "edit-mask.png"}


@pytest.mark.asyncio
async def test_lemondata_nonchat_stt_supports_local_audio_upload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    tool = LemonDataNonChatTool(workspace=tmp_path)
    audio = tmp_path / "voice.mp3"
    audio.write_bytes(b"fake-mp3")
    seen_request: dict[str, object] = {}

    async def _fake_fetch(path: str, *, method: str = "GET", body=None):
        if path == "/v1/models?category=stt":
            return {
                "ok": True,
                "body": {"data": [{"id": "gpt-4o-mini-transcribe", "lemondata": {"category": "stt"}}]},
            }
        raise AssertionError((path, method, body))

    async def _fake_fetch_response(path: str, *, method: str = "GET", body=None, files=None, save_to=None):
        seen_request["path"] = path
        seen_request["body"] = body
        seen_request["files"] = files
        return {
            "ok": True,
            "body": {"text": "hello world"},
            "content_type": "application/json",
        }

    monkeypatch.setattr(tool, "_fetch_json", _fake_fetch)
    monkeypatch.setattr(tool, "_fetch_response", _fake_fetch_response)
    result = json.loads(
        await tool.execute(
            action="request",
            category="stt",
            model="gpt-4o-mini-transcribe",
            payload={"language": "en"},
            files={"audio_path": "voice.mp3"},
        )
    )

    assert result["ok"] is True
    assert result["request_mode"] == "multipart"
    assert seen_request["path"] == "/v1/audio/transcriptions"
    assert seen_request["files"] == {"audio_path": "voice.mp3"}


@pytest.mark.asyncio
async def test_lemondata_nonchat_tts_binary_request_passes_save_to(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = LemonDataNonChatTool()
    seen_request: dict[str, object] = {}

    async def _fake_fetch(path: str, *, method: str = "GET", body=None):
        if path == "/v1/models?category=tts":
            return {
                "ok": True,
                "body": {"data": [{"id": "gpt-4o-mini-tts", "lemondata": {"category": "tts"}}]},
            }
        raise AssertionError((path, method, body))

    async def _fake_fetch_response(path: str, *, method: str = "GET", body=None, files=None, save_to=None):
        seen_request["path"] = path
        seen_request["body"] = body
        seen_request["save_to"] = save_to
        return {
            "ok": True,
            "body": {"saved_to": save_to, "content_type": "audio/mpeg", "size_bytes": 123},
            "content_type": "audio/mpeg",
        }

    monkeypatch.setattr(tool, "_fetch_json", _fake_fetch)
    monkeypatch.setattr(tool, "_fetch_response", _fake_fetch_response)
    result = json.loads(
        await tool.execute(
            action="request",
            category="tts",
            model="gpt-4o-mini-tts",
            payload={"input": "hello", "voice": "nova"},
            save_to="outputs/voice.mp3",
        )
    )

    assert result["ok"] is True
    assert result["request_mode"] == "json"
    assert result["content_type"] == "audio/mpeg"
    assert seen_request["path"] == "/v1/audio/speech"
    assert seen_request["save_to"] == "outputs/voice.mp3"
