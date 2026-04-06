"""Guarded helper for LemonData non-chat model discovery and requests."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from lemonclaw.agent.tools.base import Tool

_SUPPORTED_CATEGORIES = ("image", "video", "music", "3d", "tts", "stt", "embedding", "rerank", "translation")
_DEFAULT_ENDPOINTS = {
    "image": "/v1/images/generations",
    "video": "/v1/videos/generations",
    "music": "/v1/music/generations",
    "3d": "/v1/3d/generations",
    "tts": "/v1/audio/speech",
    "stt": "/v1/audio/transcriptions",
    "embedding": "/v1/embeddings",
    "rerank": "/v1/rerank",
    "translation": "/v1/translations",
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
    "translation": {"/v1/translations"},
}
_RETRYABLE_ERROR_CODES = {"all_channels_failed", "upstream_error", "rate_limit_exceeded", "model_unavailable"}
_RETRYABLE_TRANSPORT_ERRORS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
    httpx.RemoteProtocolError,
)


class LemonDataNonChatTool(Tool):
    """Fresh-discovery wrapper for LemonData non-chat endpoints."""

    def __init__(self) -> None:
        super().__init__()

    @property
    def name(self) -> str:
        return "lemondata_nonchat"

    @property
    def description(self) -> str:
        return (
            "Discover currently available LemonData non-chat models and perform guarded non-chat requests. "
            "For image, video, music, 3d, tts, stt, embedding, rerank, and translation, discover reads the "
            "category catalog from /v1/models?category=... and can optionally overlay recommended_for snapshot metadata. "
            "When model is omitted for a request, it automatically picks from the top ready recommended models only. "
            "It only falls back to another model on transient retryable failures."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["discover", "request"],
                    "description": "discover = list the category catalog with optional recommendation metadata; request = execute a guarded API call",
                },
                "category": {
                    "type": "string",
                    "enum": list(_SUPPORTED_CATEGORIES),
                    "description": "Non-chat model category",
                },
                "model": {
                    "type": "string",
                    "description": "Requested model id. Optional for action=request; if omitted, the tool discovers and tries the top recommended ready models.",
                },
                "recommended_for": {
                    "type": "string",
                    "enum": list(_SUPPORTED_CATEGORIES),
                    "description": "Optional recommendation scene. Used for ranking metadata, not as the authoritative existence check.",
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
                    "description": "Optional display cap for discovered models. Omit to return the full category catalog.",
                    "minimum": 1,
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
        recommended_for: str | None = None,
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

        scene = str(recommended_for or category).strip().lower()
        if scene not in _SUPPORTED_CATEGORIES:
            return json.dumps({
                "ok": False,
                "error": f"Unsupported recommended_for '{scene}'.",
                "supported_recommended_for": list(_SUPPORTED_CATEGORIES),
            }, ensure_ascii=False)

        requested_model = str(model or "").strip()
        discovery = await self._discover(
            category,
            recommended_for=scene,
            limit=limit,
            include_recommendations=str(action or "") == "discover" or not requested_model,
        )
        if str(action or "") == "discover":
            return json.dumps(discovery, ensure_ascii=False)

        if not discovery["ok"]:
            return json.dumps({
                "ok": False,
                "error": "Fresh LemonData category discovery failed; refusing non-chat request.",
                "category": category,
                "discovery": discovery,
            }, ensure_ascii=False)

        resolved_endpoint = str(endpoint or _DEFAULT_ENDPOINTS[category]).strip()
        if resolved_endpoint not in _ALLOWED_ENDPOINTS[category]:
            return json.dumps({
                "ok": False,
                "error": f"Endpoint '{resolved_endpoint}' is not allowed for category '{category}'.",
                "category": category,
                "allowed_endpoints": sorted(_ALLOWED_ENDPOINTS[category]),
            }, ensure_ascii=False)

        available_models = {str(item) for item in discovery.get("all_model_ids") or []}
        if not available_models:
            available_models = {str(item["id"]) for item in discovery["models"]}
        if requested_model:
            if requested_model not in available_models:
                return json.dumps({
                    "ok": False,
                    "error": f"Requested model '{requested_model}' is not currently available in category '{category}'.",
                    "category": category,
                    "requested_model": requested_model,
                    "available_models": discovery["models"],
                }, ensure_ascii=False)
            attempt_chain = [requested_model]
        else:
            if discovery.get("recommendation_error"):
                return json.dumps({
                    "ok": False,
                    "error": "Fresh LemonData recommendation snapshot failed; refusing auto-selected non-chat request.",
                    "category": category,
                    "discovery": discovery,
                }, ensure_ascii=False)
            attempt_chain = [
                str(item["id"])
                for item in discovery["models"]
                if item.get("status") == "ready"
            ][:3]
            if not attempt_chain:
                return json.dumps({
                    "ok": False,
                    "error": f"No ready recommended models are currently available for category '{category}'.",
                    "category": category,
                    "discovery": discovery,
                }, ensure_ascii=False)

        auto_selected = not requested_model
        attempted_models: list[str] = []
        fallback_reason: str | None = None
        recommendation_context = {
            "scene": scene,
            "snapshot_at": discovery.get("snapshot_at"),
        }
        refreshed_after_failure = False

        while attempt_chain:
            selected_model = attempt_chain.pop(0)
            attempted_models.append(selected_model)
            request_payload = dict(payload or {})
            request_payload["model"] = selected_model
            validation_error = self._validate_payload(category, request_payload)
            if validation_error:
                return json.dumps({
                    "ok": False,
                    "error": validation_error,
                    "category": category,
                    "selected_model": selected_model,
                }, ensure_ascii=False)

            request_result = await self._request(resolved_endpoint, request_payload)
            request_result["discovery"] = {
                "category": category,
                "model_count": discovery["model_count"],
                "requested_model_verified": selected_model in available_models,
                "recommended_for": scene,
                "snapshot_at": discovery.get("snapshot_at"),
            }
            request_result["selected_model"] = selected_model
            request_result["attempted_models"] = attempted_models
            request_result["recommendation_context"] = {
                **recommendation_context,
                "selected_rank": next(
                    (item.get("preferred_rank") for item in discovery["models"] if item.get("id") == selected_model),
                    None,
                ),
                "success_rate_24h": next(
                    (item.get("success_rate_24h") for item in discovery["models"] if item.get("id") == selected_model),
                    None,
                ),
            }

            if request_result["ok"] or not auto_selected or not self._should_retry_with_next_model(request_result):
                if fallback_reason:
                    request_result["fallback_reason"] = fallback_reason
                return json.dumps(request_result, ensure_ascii=False)

            fallback_reason = request_result.get("error_code") or request_result.get("error") or "retryable_error"
            if not refreshed_after_failure:
                refreshed = await self._discover(
                    category,
                    recommended_for=scene,
                    limit=limit,
                    include_recommendations=True,
                    force_refresh=True,
                )
                if refreshed.get("ok"):
                    discovery = refreshed
                    available_models = {str(item) for item in discovery.get("all_model_ids") or []}
                    refreshed_candidates = [
                        str(item["id"])
                        for item in discovery["models"]
                        if item.get("status") == "ready" and str(item.get("id")) not in attempted_models
                    ][:3]
                    attempt_chain = refreshed_candidates
                    recommendation_context["snapshot_at"] = discovery.get("snapshot_at")
                refreshed_after_failure = True

        return json.dumps({
            "ok": False,
            "error": "All recommended models failed for this request.",
            "category": category,
            "attempted_models": attempted_models,
            "fallback_reason": fallback_reason,
            "recommendation_context": recommendation_context,
        }, ensure_ascii=False)

    async def _discover(
        self,
        category: str,
        *,
        recommended_for: str,
        limit: int | None,
        include_recommendations: bool,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        del force_refresh

        catalog_response = await self._fetch_json(f"/v1/models?category={category}")
        if not catalog_response["ok"]:
            return {
                "ok": False,
                "category": category,
                "error": catalog_response["error"],
            }

        recommendation_models: dict[str, dict[str, Any]] = {}
        recommendation_error: str | None = None
        snapshot_at: str | None = None

        if include_recommendations:
            recommendation_response = await self._fetch_json(
                f"/v1/models?category={category}&recommended_for={recommended_for}"
            )
            if recommendation_response["ok"]:
                recommendation_items = (
                    recommendation_response["body"].get("data")
                    if isinstance(recommendation_response["body"], dict)
                    else None
                )
                if isinstance(recommendation_items, list):
                    for item in recommendation_items:
                        if not isinstance(item, dict):
                            continue
                        model_id = str(item.get("id") or "").strip()
                        if not model_id:
                            continue
                        lemondata_meta = item.get("lemondata") if isinstance(item.get("lemondata"), dict) else {}
                        agent_preferences = (
                            lemondata_meta.get("agent_preferences")
                            if isinstance(lemondata_meta, dict)
                            else {}
                        )
                        preference = (
                            agent_preferences.get(recommended_for)
                            if isinstance(agent_preferences, dict) and isinstance(agent_preferences.get(recommended_for), dict)
                            else {}
                        )
                        recommendation_models[model_id] = {
                            "preferred_rank": preference.get("preferred_rank"),
                            "success_rate_24h": preference.get("success_rate_24h"),
                            "sample_count_24h": preference.get("sample_count_24h", 0),
                            "status": preference.get("status"),
                            "updated_at": preference.get("updated_at"),
                        }
                        if snapshot_at is None and preference.get("updated_at"):
                            snapshot_at = str(preference.get("updated_at"))
            else:
                recommendation_error = recommendation_response["error"]

        items = catalog_response["body"].get("data") if isinstance(catalog_response["body"], dict) else None
        models = []
        all_model_ids: list[str] = []
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                model_id = str(item.get("id") or "").strip()
                if not model_id:
                    continue
                all_model_ids.append(model_id)
            visible_items = items if limit is None else items[:limit]
            for item in visible_items:
                if not isinstance(item, dict):
                    continue
                model_id = str(item.get("id") or "").strip()
                if not model_id:
                    continue
                lemondata_meta = item.get("lemondata") if isinstance(item.get("lemondata"), dict) else {}
                preference = recommendation_models.get(model_id, {})
                models.append({
                    "id": model_id,
                    "category": str((lemondata_meta or {}).get("category") or category),
                    "tags": list((lemondata_meta or {}).get("capabilities") or []),
                    "pricing_unit": (lemondata_meta or {}).get("pricing_unit"),
                    "preferred_rank": preference.get("preferred_rank"),
                    "success_rate_24h": preference.get("success_rate_24h"),
                    "sample_count_24h": preference.get("sample_count_24h", 0),
                    "status": preference.get("status"),
                    "updated_at": preference.get("updated_at"),
                    "recommended": model_id in recommendation_models,
                })
        return {
            "ok": True,
            "category": category,
            "recommended_for": recommended_for,
            "model_count": len(all_model_ids),
            "catalog_total": len(all_model_ids),
            "returned_model_count": len(models),
            "truncated": len(all_model_ids) > len(models),
            "all_model_ids": all_model_ids,
            "models": models,
            "snapshot_at": snapshot_at,
            "recommendation_error": recommendation_error,
        }

    async def _request(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self._fetch_json(endpoint, method="POST", body=payload)
        if response["ok"]:
            return {
                "ok": True,
                "endpoint": endpoint,
                "response": response["body"],
            }
        error_body = response["body"] if isinstance(response["body"], dict) else {}
        error_payload = error_body.get("error") if isinstance(error_body.get("error"), dict) else {}
        return {
            "ok": False,
            "endpoint": endpoint,
            "error": response["error"],
            "response": response["body"],
            "error_code": error_payload.get("code") or ("transport_error" if response.get("transport_error") else None),
            "retryable": bool(error_payload.get("retryable")) or bool(response.get("transport_error")),
        }

    @staticmethod
    def _validate_payload(category: str, payload: dict[str, Any]) -> str | None:
        if category == "translation":
            if not str(payload.get("text") or "").strip():
                return "payload.text is required for translation requests"
            if not str(payload.get("target_language") or "").strip():
                return "payload.target_language is required for translation requests"
        return None

    @staticmethod
    def _should_retry_with_next_model(request_result: dict[str, Any]) -> bool:
        error_code = str(request_result.get("error_code") or "").strip().lower()
        if error_code in _RETRYABLE_ERROR_CODES:
            return True
        if error_code in {"invalid_request", "insufficient_balance"}:
            return False
        return bool(request_result.get("retryable"))

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
        except _RETRYABLE_TRANSPORT_ERRORS as exc:
            return {"ok": False, "error": str(exc), "body": None, "transport_error": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "body": None}
