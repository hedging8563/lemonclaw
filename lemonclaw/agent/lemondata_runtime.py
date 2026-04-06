"""Runtime LemonData capability discovery for agent prompts.

This module intentionally prefers live `/v1/models` discovery over static
prompt guidance so bots do not depend on repo-side contract snapshots.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import httpx

from lemonclaw.utils.attachments import attachment_metadata

_CACHE_TTL_SECONDS = 45
_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "video": (
        "video", "视频", "seedance", "kling", "hailuo", "vidu", "runway",
        "image-to-video", "reference-to-video", "start-end-to-video", "video-to-video",
    ),
    "image": (
        "image", "图片", "画图", "图生图", "edit image", "image-edit", "flux",
        "gpt-image", "gemini-image", "nano banana", "remove background", "upscale",
    ),
    "tts": ("tts", "配音", "语音合成", "text-to-speech", "speech"),
    "stt": ("stt", "转录", "语音识别", "transcription", "speech-to-text"),
    "embedding": ("embedding", "嵌入", "向量"),
    "rerank": ("rerank", "重排"),
    "translation": ("translation", "翻译"),
    "music": ("music", "音乐", "歌曲"),
    "3d": ("3d", "三维", "模型生成"),
}
_LIVE_DISCOVERY_CACHE: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}


def _normalize_api_base(value: str | None) -> str:
    base = str(value or "https://api.lemondata.cc").strip().rstrip("/")
    return base[:-3] if base.endswith("/v1") else base


def _guess_category(current_message: str, media: list[str] | None) -> str | None:
    lowered = str(current_message or "").lower()
    attachment_types = {
        str((attachment_metadata(path).get("mime") or "")).split("/", 1)[0]
        for path in (media or [])
    }
    for category, keywords in _CATEGORY_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return category
    if "video" in attachment_types:
        return "video"
    if "image" in attachment_types:
        return "image"
    if "audio" in attachment_types:
        return "stt"
    return None


def _guess_video_operation(current_message: str, media: list[str] | None) -> str | None:
    lowered = str(current_message or "").lower()
    media_items = [attachment_metadata(path) for path in (media or [])]
    image_items = [item for item in media_items if str(item.get("mime") or "").startswith("image/")]
    video_items = [item for item in media_items if str(item.get("mime") or "").startswith("video/")]

    if "start-end-to-video" in lowered or ("首帧" in current_message and "尾帧" in current_message):
        return "start-end-to-video"
    if "reference-to-video" in lowered or "参考图" in current_message:
        return "reference-to-video"
    if "video-to-video" in lowered or video_items:
        return "video-to-video"
    if "image-to-video" in lowered or image_items:
        return "image-to-video"
    if "text-to-video" in lowered:
        return "text-to-video"
    return None


def _build_attachment_hints(category: str, operation: str | None, media: list[str] | None) -> list[str]:
    hints: list[str] = []
    media = media or []
    if not media:
        return hints

    image_paths = [path for path in media if str(attachment_metadata(path).get("mime") or "").startswith("image/")]
    video_paths = [path for path in media if str(attachment_metadata(path).get("mime") or "").startswith("video/")]
    audio_paths = [path for path in media if str(attachment_metadata(path).get("mime") or "").startswith("audio/")]

    if category == "video":
        if operation == "start-end-to-video" and len(image_paths) >= 2:
            hints.append(f"Use start_image={image_paths[0]} and end_image={image_paths[1]}")
        elif operation == "reference-to-video" and image_paths:
            hints.append(f"Use reference_images={json.dumps(image_paths[: min(3, len(image_paths))], ensure_ascii=False)}")
        elif operation == "image-to-video" and image_paths:
            hints.append(f"Use image_url or image_urls from the latest image attachment: {image_paths[-1]}")
        elif operation == "video-to-video" and video_paths:
            hints.append(f"Use video_url from the latest video attachment: {video_paths[-1]}")
    elif category == "image":
        if image_paths:
            hints.append(f"Use image_url/image_urls from available image attachments: {json.dumps(image_paths[: min(3, len(image_paths))], ensure_ascii=False)}")
    elif category == "stt" and audio_paths:
        hints.append(f"Use files.audio_path={audio_paths[-1]}")

    return hints


def _format_models(models: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for item in models[:5]:
        lemondata = dict(item.get("lemondata") or {})
        contract = dict(lemondata.get("public_contract_summary") or {})
        operations = list(lemondata.get("supported_operations") or contract.get("public_operations") or [])
        lines.append(
            f"- {item.get('id')} | ops={', '.join(str(op) for op in operations[:6]) or '—'}"
            f" | endpoint={contract.get('request_endpoint') or '—'}"
            f" | status={((lemondata.get('agent_preferences') or {}).get(lemondata.get('category') or '', {}) or {}).get('status') or '—'}"
        )
    return lines


def _select_focus_model(models: list[dict[str, Any]], current_message: str) -> dict[str, Any] | None:
    lowered = str(current_message or "").lower()
    for item in models:
        model_id = str(item.get("id") or "")
        if model_id and model_id.lower() in lowered:
            return item
    return models[0] if models else None


def _request_fields_from_model(model_entry: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    lemondata = dict(model_entry.get("lemondata") or {})
    contract = dict(lemondata.get("public_contract_summary") or {})
    supported_parameters = [str(item) for item in list(contract.get("supported_parameters") or []) if item]
    recommended_request = dict(contract.get("recommended_request_summary") or {})
    return supported_parameters, recommended_request


def _fetch_live_models(category: str) -> dict[str, Any]:
    base = _normalize_api_base(os.environ.get("API_BASE_URL"))
    api_key = str(os.environ.get("API_KEY") or "").strip()
    cache_key = (base, category)
    now = time.time()
    cached = _LIVE_DISCOVERY_CACHE.get(cache_key)
    if cached and now - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]

    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    url = f"{base}/v1/models?category={category}&recommended_for={category}"
    with httpx.Client(timeout=4.0, follow_redirects=True) as client:
        response = client.get(url, headers=headers)
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Unexpected LemonData /v1/models payload")
    _LIVE_DISCOVERY_CACHE[cache_key] = (now, payload)
    return payload


def build_lemondata_runtime_block(current_message: str, media: list[str] | None = None) -> str:
    category = _guess_category(current_message, media)
    if not category:
        return ""

    try:
        payload = _fetch_live_models(category)
    except Exception as exc:
        return (
            "[LemonData Live Capability — best-effort runtime discovery]\n"
            f"- category={category}\n"
            f"- discovery_error={type(exc).__name__}: {exc}"
        )

    models = list(payload.get("data") or [])
    if not models:
        return (
            "[LemonData Live Capability — best-effort runtime discovery]\n"
            f"- category={category}\n"
            "- live_models=none"
        )

    focus_model = _select_focus_model(models, current_message)
    operation = _guess_video_operation(current_message, media) if category == "video" else None
    lines = [
        "[LemonData Live Capability — metadata only, discovered at runtime]",
        f"- category={category}",
        f"- discovery_endpoint=/v1/models?category={category}&recommended_for={category}",
    ]
    if focus_model:
        lemondata = dict(focus_model.get("lemondata") or {})
        contract = dict(lemondata.get("public_contract_summary") or {})
        operations = list(lemondata.get("supported_operations") or contract.get("public_operations") or [])
        fields, recommended_request = _request_fields_from_model(focus_model)
        lines.extend([
            f"- focus_model={focus_model.get('id')}",
            f"- focus_endpoint={contract.get('request_endpoint') or '—'}",
            f"- supported_operations={json.dumps(operations, ensure_ascii=False)}",
            f"- supported_parameters={json.dumps(fields, ensure_ascii=False)}",
        ])
        if recommended_request:
            lines.append(f"- recommended_request={json.dumps(recommended_request, ensure_ascii=False)}")
        if operation:
            lines.append(f"- inferred_operation={operation}")
    hints = _build_attachment_hints(category, operation, media)
    if hints:
        lines.extend(f"- attachment_hint={hint}" for hint in hints)
    lines.append("- top_live_models:")
    lines.extend(_format_models(models))
    return "\n".join(lines)
