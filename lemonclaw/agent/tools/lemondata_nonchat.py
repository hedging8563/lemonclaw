"""Guarded helper for LemonData non-chat model discovery and requests."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from lemonclaw.agent.tools.base import Tool

_SUPPORTED_CATEGORIES = ("image", "video", "music", "3d", "tts", "stt", "embedding", "rerank")
_DEFAULT_ENDPOINTS = {
    "image": "/v1/images/generations",
    "video": "/v1/videos/generations",
    "music": "/v1/music/generations",
    "3d": "/v1/3d/generations",
    "tts": "/v1/audio/speech",
    "stt": "/v1/audio/transcriptions",
    "embedding": "/v1/embeddings",
    "rerank": "/v1/rerank",
}
_ALLOWED_ENDPOINTS = {
    "image": {"/v1/images/generations", "/v1/images/edits", "/v1/images/variations"},
    "video": {"/v1/videos/generations"},
    "music": {"/v1/music/generations"},
    "3d": {"/v1/3d/generations"},
    "tts": {"/v1/audio/speech"},
    "stt": {"/v1/audio/transcriptions"},
    "embedding": {"/v1/embeddings"},
    "rerank": {"/v1/rerank"},
}


class LemonDataNonChatTool(Tool):
    """Fresh-discovery wrapper for LemonData non-chat endpoints."""

    @property
    def name(self) -> str:
        return "lemondata_nonchat"

    @property
    def description(self) -> str:
        return (
            "Discover currently available LemonData non-chat models and perform guarded non-chat requests. "
            "For image, video, music, 3d, tts, stt, embedding, and rerank, this tool always fetches "
            "a fresh /v1/models?category=... list before making the request. If fresh discovery fails or "
            "the requested model is not currently available, it refuses the call."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["discover", "request"],
                    "description": "discover = list live models for a non-chat category; request = execute a guarded API call",
                },
                "category": {
                    "type": "string",
                    "enum": list(_SUPPORTED_CATEGORIES),
                    "description": "Non-chat model category",
                },
                "model": {
                    "type": "string",
                    "description": "Requested model id (required for action=request)",
                },
                "endpoint": {
                    "type": "string",
                    "description": "Optional endpoint override. Must match the category allowlist.",
                },
                "payload": {
                    "type": "object",
                    "description": "JSON request payload for action=request. The tool will enforce payload.model = model.",
                    "additionalProperties": True,
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of discovered models to return",
                    "minimum": 1,
                    "maximum": 50,
                },
            },
            "required": ["action", "category"],
            "additionalProperties": False,
        }

    def resolve_capability(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> str:
        del context
        if str(params.get("action") or "") == "request":
            return "tool.lemondata_nonchat.write"
        return "tool.lemondata_nonchat.read"

    async def execute(
        self,
        action: str,
        category: str,
        model: str | None = None,
        endpoint: str | None = None,
        payload: dict[str, Any] | None = None,
        limit: int | None = None,
        **kwargs: Any,
    ) -> str:
        del kwargs
        category = str(category or "").strip().lower()
        if category not in _SUPPORTED_CATEGORIES:
            return json.dumps({
                "ok": False,
                "error": f"Unsupported category '{category}'.",
                "supported_categories": list(_SUPPORTED_CATEGORIES),
            }, ensure_ascii=False)

        discovery = await self._discover(category, limit=limit or 12)
        if str(action or "") == "discover":
            return json.dumps(discovery, ensure_ascii=False)

        if not discovery["ok"]:
            return json.dumps({
                "ok": False,
                "error": "Fresh LemonData model discovery failed; refusing non-chat request.",
                "category": category,
                "discovery": discovery,
            }, ensure_ascii=False)

        requested_model = str(model or "").strip()
        if not requested_model:
            return json.dumps({
                "ok": False,
                "error": "model is required for action=request",
                "category": category,
                "available_models": discovery["models"],
            }, ensure_ascii=False)

        available_models = {str(item["id"]) for item in discovery["models"]}
        if requested_model not in available_models:
            return json.dumps({
                "ok": False,
                "error": f"Requested model '{requested_model}' is not currently available in category '{category}'.",
                "category": category,
                "requested_model": requested_model,
                "available_models": discovery["models"],
            }, ensure_ascii=False)

        resolved_endpoint = str(endpoint or _DEFAULT_ENDPOINTS[category]).strip()
        if resolved_endpoint not in _ALLOWED_ENDPOINTS[category]:
            return json.dumps({
                "ok": False,
                "error": f"Endpoint '{resolved_endpoint}' is not allowed for category '{category}'.",
                "category": category,
                "allowed_endpoints": sorted(_ALLOWED_ENDPOINTS[category]),
            }, ensure_ascii=False)

        request_payload = dict(payload or {})
        request_payload["model"] = requested_model

        request_result = await self._request(resolved_endpoint, request_payload)
        request_result["discovery"] = {
            "category": category,
            "model_count": discovery["model_count"],
            "requested_model_verified": True,
        }
        return json.dumps(request_result, ensure_ascii=False)

    async def _discover(self, category: str, *, limit: int) -> dict[str, Any]:
        response = await self._fetch_json(f"/v1/models?category={category}")
        if not response["ok"]:
            return {
                "ok": False,
                "category": category,
                "error": response["error"],
            }
        items = response["body"].get("data") if isinstance(response["body"], dict) else None
        models = []
        if isinstance(items, list):
            for item in items[:limit]:
                if not isinstance(item, dict):
                    continue
                model_id = str(item.get("id") or "").strip()
                if not model_id:
                    continue
                lemondata_meta = item.get("lemondata") if isinstance(item.get("lemondata"), dict) else {}
                models.append({
                    "id": model_id,
                    "category": str((lemondata_meta or {}).get("category") or category),
                    "tags": list((lemondata_meta or {}).get("tags") or []),
                    "pricing_unit": (lemondata_meta or {}).get("pricing_unit"),
                })
        return {
            "ok": True,
            "category": category,
            "model_count": len(models),
            "models": models,
        }

    async def _request(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self._fetch_json(endpoint, method="POST", body=payload)
        if response["ok"]:
            return {
                "ok": True,
                "endpoint": endpoint,
                "response": response["body"],
            }
        return {
            "ok": False,
            "endpoint": endpoint,
            "error": response["error"],
            "response": response["body"],
        }

    async def _fetch_json(
        self,
        path: str,
        *,
        method: str = "GET",
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        api_key = os.environ.get("API_KEY", "").strip()
        if not api_key:
            return {"ok": False, "error": "API_KEY is not set", "body": None}

        base = os.environ.get("API_BASE_URL", "https://api.lemondata.cc").rstrip("/")
        url = f"{base}{path}"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.request(method, url, headers=headers, json=body)
            try:
                payload = response.json()
            except Exception:
                payload = {"raw": response.text}
            if response.status_code >= 400:
                return {
                    "ok": False,
                    "error": f"HTTP {response.status_code}",
                    "body": payload,
                }
            return {"ok": True, "body": payload}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "body": None}
