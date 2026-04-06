from __future__ import annotations

from pathlib import Path

from lemonclaw.agent.context import ContextBuilder
from lemonclaw.agent.lemondata_runtime import build_lemondata_runtime_block


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def test_build_lemondata_runtime_block_uses_live_model_contract(monkeypatch):
    monkeypatch.setattr(
        "lemonclaw.agent.lemondata_runtime._fetch_live_models",
        lambda category: {
            "data": [
                {
                    "id": "seedance-2.0",
                    "lemondata": {
                        "public_contract_summary": {
                            "request_endpoint": "/v1/videos/generations",
                            "supported_parameters": ["prompt", "operation", "image_url", "duration"],
                            "recommended_request_summary": {
                                "operation": "text-to-video",
                                "duration": 5,
                                "aspect_ratio": "16:9",
                            },
                        },
                        "supported_operations": ["image-to-video", "text-to-video"],
                    },
                },
            ],
        },
    )

    block = build_lemondata_runtime_block("用 seedance-2.0 把图片变成视频", media=["/tmp/input.png"])

    assert "seedance-2.0" in block
    assert "/v1/videos/generations" in block
    assert "image-to-video" in block
    assert "supported_parameters" in block


def test_context_builder_injects_lemondata_runtime_block(monkeypatch, tmp_path: Path):
    workspace = _workspace(tmp_path)
    builder = ContextBuilder(workspace)
    monkeypatch.setattr(
        "lemonclaw.agent.context.build_lemondata_runtime_block",
        lambda current_message, media=None: "[LemonData Live Capability — metadata only, discovered at runtime]\n- focus_model=seedance-2.0",
    )

    messages = builder.build_messages(
        history=[],
        current_message="请用 seedance-2.0 做图生视频",
        media=[],
        channel="webui",
        chat_id="webui",
    )

    assert len(messages) == 2
    user_content = messages[-1]["content"]
    assert isinstance(user_content, str)
    assert "focus_model=seedance-2.0" in user_content
