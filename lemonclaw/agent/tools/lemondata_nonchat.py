"""Guarded helper for LemonData non-chat model discovery and requests."""

from __future__ import annotations

import json
import mimetypes
import os
import tempfile
import uuid
from pathlib import Path
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
_BINARY_RESPONSE_ENDPOINTS = {"/v1/audio/speech"}
_MULTIPART_ONLY_ENDPOINTS = {"/v1/images/variations", "/v1/audio/transcriptions"}
_BINARY_CONTENT_PREFIXES = ("audio/", "image/", "video/")


def _compact_dict(value: dict[str, Any] | None) -> dict[str, Any]:
    if not value:
        return {}
    return {
        key: item
        for key, item in value.items()
        if item is not None and item != "" and item != []
    }


def _stringify_form_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


class LemonDataNonChatTool(Tool):
    """Fresh-discovery wrapper for LemonData non-chat endpoints."""

    def __init__(self, workspace: Path | str | None = None) -> None:
        super().__init__()
        self._workspace = Path(workspace).expanduser().resolve() if workspace else None

    @property
    def name(self) -> str:
        return "lemondata_nonchat"

    @property
    def description(self) -> str:
        return (
            "Discover currently available LemonData non-chat models and perform guarded non-chat requests. "
            "For image, video, music, 3d, tts, stt, embedding, rerank, and translation, discover reads the "
            "category catalog from /v1/models?category=... and can optionally overlay recommended_for snapshot metadata. "
            "When model is omitted for a request, it automatically picks from the top ready recommended models when available, "
            "then falls back to catalog-backed candidates if the recommendation snapshot is missing or not ready. "
            "Request supports JSON payloads plus local file uploads for multipart endpoints: "
            "image edits and variations can use files.image_path / files.mask_path, "
            "speech-to-text can use files.audio_path or files.file_path, and text-to-speech binary output can be saved via save_to. "
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
                    "description": (
                        "Request payload for action=request. Common fields include prompt, input, text, target_language, "
                        "operation, size, quality, style, n, image_url, image_urls, reference_image_urls, mask_url, voice, "
                        "query, and documents. The tool enforces payload.model = selected model."
                    ),
                    "properties": {
                        "prompt": {"type": "string"},
                        "input": {"type": "string"},
                        "text": {"type": "string"},
                        "target_language": {"type": "string"},
                        "operation": {
                            "type": "string",
                            "enum": ["text-to-image", "image-to-image", "image-edit"],
                        },
                        "size": {"type": "string"},
                        "quality": {"type": "string"},
                        "style": {"type": "string"},
                        "n": {"type": "integer", "minimum": 1},
                        "image_url": {"type": "string"},
                        "image_urls": {"type": "array", "items": {"type": "string"}},
                        "reference_image_urls": {"type": "array", "items": {"type": "string"}},
                        "mask_url": {"type": "string"},
                        "response_format": {"type": "string"},
                        "user": {"type": "string"},
                        "voice": {"type": "string"},
                        "language_code": {"type": "string"},
                        "query": {"type": "string"},
                        "documents": {"type": "array", "items": {}},
                    },
                    "additionalProperties": True,
                },
                "files": {
                    "type": "object",
                    "description": (
                        "Optional local file paths for multipart or inline media requests. "
                        "For /v1/images/edits use files.image_path and optional files.mask_path. "
                        "For /v1/images/variations use files.image_path. "
                        "For /v1/audio/transcriptions use files.audio_path or files.file_path. "
                        "For /v1/images/generations, local image paths are converted to data URLs when possible."
                    ),
                    "properties": {
                        "image_path": {"type": "string"},
                        "image_paths": {"type": "array", "items": {"type": "string"}},
                        "reference_image_paths": {"type": "array", "items": {"type": "string"}},
                        "mask_path": {"type": "string"},
                        "audio_path": {"type": "string"},
                        "file_path": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                "save_to": {
                    "type": "string",
                    "description": (
                        "Optional local output path for binary responses such as /v1/audio/speech. "
                        "If omitted, the tool saves under the workspace or temp directory and returns the saved path."
                    ),
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
        files: dict[str, Any] | None = None,
        save_to: str | None = None,
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
        selection_reason: str | None = None
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
            attempt_chain, selection_reason = self._build_auto_attempt_chain(discovery)
            if not attempt_chain:
                return json.dumps({
                    "ok": False,
                    "error": f"No catalog models are currently available for category '{category}'.",
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
            try:
                normalized_payload, normalized_files = self._normalize_request_inputs(
                    resolved_endpoint,
                    request_payload,
                    files,
                )
            except Exception as exc:
                return json.dumps({
                    "ok": False,
                    "error": str(exc),
                    "category": category,
                    "selected_model": selected_model,
                }, ensure_ascii=False)

            validation_error = self._validate_request(category, resolved_endpoint, normalized_payload, normalized_files)
            if validation_error:
                return json.dumps({
                    "ok": False,
                    "error": validation_error,
                    "category": category,
                    "selected_model": selected_model,
                }, ensure_ascii=False)

            request_result = await self._request(
                resolved_endpoint,
                normalized_payload,
                files=normalized_files,
                save_to=save_to,
            )
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
            request_result["request_guidance"] = self._request_guidance(category)
            if selection_reason:
                request_result["selection_reason"] = selection_reason

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
            "error": "All selected models failed for this request.",
            "category": category,
            "attempted_models": attempted_models,
            "fallback_reason": fallback_reason,
            "selection_reason": selection_reason,
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
            "request_guidance": self._request_guidance(category),
        }

    @staticmethod
    def _build_auto_attempt_chain(discovery: dict[str, Any]) -> tuple[list[str], str | None]:
        models = discovery.get("models") if isinstance(discovery, dict) else None
        ready_models: list[str] = []
        if isinstance(models, list):
            for item in models:
                if not isinstance(item, dict):
                    continue
                model_id = str(item.get("id") or "").strip()
                if model_id and item.get("status") == "ready":
                    ready_models.append(model_id)
        if ready_models:
            return ready_models[:3], None

        catalog_ids = [
            str(item).strip()
            for item in (discovery.get("all_model_ids") if isinstance(discovery, dict) else [])
            if str(item).strip()
        ]
        if not catalog_ids and isinstance(models, list):
            catalog_ids = [
                str(item.get("id") or "").strip()
                for item in models
                if isinstance(item, dict) and str(item.get("id") or "").strip()
            ]
        if not catalog_ids:
            return [], None

        selection_reason = "recommendation_snapshot_failed" if discovery.get("recommendation_error") else "no_ready_recommendations"
        return catalog_ids[:3], selection_reason

    async def _request(
        self,
        endpoint: str,
        payload: dict[str, Any],
        *,
        files: dict[str, Any] | None = None,
        save_to: str | None = None,
    ) -> dict[str, Any]:
        normalized_files = _compact_dict(files)
        request_mode = self._resolve_request_mode(endpoint, normalized_files)
        expects_binary = endpoint in _BINARY_RESPONSE_ENDPOINTS

        if request_mode == "json" and not expects_binary:
            response = await self._fetch_json(endpoint, method="POST", body=payload)
        else:
            response = await self._fetch_response(
                endpoint,
                method="POST",
                body=payload,
                files=normalized_files,
                save_to=save_to,
            )

        if response["ok"]:
            result = {
                "ok": True,
                "endpoint": endpoint,
                "response": response["body"],
                "request_mode": request_mode,
            }
            if response.get("content_type"):
                result["content_type"] = response["content_type"]
            return result
        error_body = response["body"] if isinstance(response["body"], dict) else {}
        error_payload = error_body.get("error") if isinstance(error_body.get("error"), dict) else {}
        return {
            "ok": False,
            "endpoint": endpoint,
            "error": response["error"],
            "response": response["body"],
            "error_code": error_payload.get("code") or ("transport_error" if response.get("transport_error") else None),
            "retryable": bool(error_payload.get("retryable")) or bool(response.get("transport_error")),
            "request_mode": request_mode,
        }

    @staticmethod
    def _validate_request(
        category: str,
        endpoint: str,
        payload: dict[str, Any],
        files: dict[str, Any],
    ) -> str | None:
        if category == "translation":
            if not str(payload.get("text") or "").strip():
                return "payload.text is required for translation requests"
            if not str(payload.get("target_language") or "").strip():
                return "payload.target_language is required for translation requests"
        if category == "tts" and not str(payload.get("input") or "").strip():
            return "payload.input is required for text-to-speech requests"
        if category == "embedding" and payload.get("input") in (None, "", []):
            return "payload.input is required for embedding requests"
        if category == "rerank":
            if not str(payload.get("query") or "").strip():
                return "payload.query is required for rerank requests"
            if not isinstance(payload.get("documents"), list) or not payload.get("documents"):
                return "payload.documents must be a non-empty array for rerank requests"
        if category == "stt":
            if not str(files.get("audio_path") or files.get("file_path") or "").strip():
                return "files.audio_path or files.file_path is required for speech-to-text requests"
        if category == "image":
            prompt = str(payload.get("prompt") or "").strip()
            if endpoint in {"/v1/images/generations", "/v1/images/edits"} and not prompt:
                return "payload.prompt is required for image generation or edit requests"
            if endpoint == "/v1/images/generations":
                operation = str(payload.get("operation") or "").strip().lower()
                if operation in {"image-to-image", "image-edit"}:
                    has_source = bool(
                        payload.get("image_url")
                        or payload.get("image_urls")
                        or payload.get("reference_image_urls")
                    )
                    if not has_source:
                        return (
                            "image-to-image requests need payload.image_url, payload.image_urls, or "
                            "payload.reference_image_urls (local files are converted automatically when possible)"
                        )
                if files:
                    return "files are only supported for /v1/images/edits, /v1/images/variations, or inline image-to-image conversion"
            if endpoint == "/v1/images/edits":
                has_json_image = bool(payload.get("image_url"))
                has_file_image = bool(files.get("image_path") or files.get("file_path"))
                if not (has_json_image or has_file_image):
                    return "image edits need payload.image_url or files.image_path"
            if endpoint == "/v1/images/variations":
                if not str(files.get("image_path") or files.get("file_path") or "").strip():
                    return "image variations require files.image_path or files.file_path"
        return None

    @staticmethod
    def _should_retry_with_next_model(request_result: dict[str, Any]) -> bool:
        error_code = str(request_result.get("error_code") or "").strip().lower()
        if error_code in _RETRYABLE_ERROR_CODES:
            return True
        if error_code in {"invalid_request", "insufficient_balance"}:
            return False
        return bool(request_result.get("retryable"))

    def _normalize_request_inputs(
        self,
        endpoint: str,
        payload: dict[str, Any] | None,
        files: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        normalized_payload = _compact_dict(dict(payload or {}))
        normalized_files = _compact_dict(dict(files or {}))

        if endpoint != "/v1/images/generations":
            return normalized_payload, normalized_files

        if "image_url" not in normalized_payload:
            source_path = normalized_files.pop("image_path", None) or normalized_files.pop("file_path", None)
            if source_path:
                normalized_payload["image_url"] = self._file_to_data_url(str(source_path))

        if "image_urls" not in normalized_payload and normalized_files.get("image_paths"):
            normalized_payload["image_urls"] = [
                self._file_to_data_url(str(item))
                for item in list(normalized_files.pop("image_paths") or [])
            ]

        if "reference_image_urls" not in normalized_payload and normalized_files.get("reference_image_paths"):
            normalized_payload["reference_image_urls"] = [
                self._file_to_data_url(str(item))
                for item in list(normalized_files.pop("reference_image_paths") or [])
            ]

        if "mask_url" not in normalized_payload and normalized_files.get("mask_path"):
            normalized_payload["mask_url"] = self._file_to_data_url(str(normalized_files.pop("mask_path")))

        return normalized_payload, normalized_files

    @staticmethod
    def _resolve_request_mode(endpoint: str, files: dict[str, Any]) -> str:
        if endpoint in _MULTIPART_ONLY_ENDPOINTS:
            return "multipart"
        if endpoint == "/v1/images/edits" and files:
            return "multipart"
        return "json"

    def _resolve_local_path(self, path: str) -> Path:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute() and self._workspace:
            candidate = self._workspace / candidate
        resolved = candidate.resolve()
        if not resolved.exists():
            raise FileNotFoundError(f"Local file not found: {path}")
        if not resolved.is_file():
            raise ValueError(f"Local path is not a file: {path}")
        return resolved

    def _file_to_data_url(self, path: str) -> str:
        file_path = self._resolve_local_path(path)
        mime = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        import base64

        encoded = base64.b64encode(file_path.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{encoded}"

    async def _fetch_response(
        self,
        path: str,
        *,
        method: str = "GET",
        body: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        save_to: str | None = None,
    ) -> dict[str, Any]:
        api_key = os.environ.get("API_KEY", "").strip()
        if not api_key:
            return {"ok": False, "error": "API_KEY is not set", "body": None}

        base = os.environ.get("API_BASE_URL", "https://api.lemondata.cc").rstrip("/")
        url = f"{base}{path}"
        headers = {"Authorization": f"Bearer {api_key}"}
        request_kwargs: dict[str, Any] = {}
        file_handles: list[Any] = []
        compact_body = _compact_dict(body)
        compact_files = _compact_dict(files)

        if compact_files:
            multipart_files: dict[str, tuple[str, Any, str]] = {}

            def _attach(field_name: str, value: str | None) -> None:
                if not value:
                    return
                file_path = self._resolve_local_path(value)
                handle = file_path.open("rb")
                file_handles.append(handle)
                mime = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
                multipart_files[field_name] = (file_path.name, handle, mime)

            if path == "/v1/images/edits":
                _attach("image", str(compact_files.get("image_path") or compact_files.get("file_path") or ""))
                _attach("mask", str(compact_files.get("mask_path") or ""))
            elif path == "/v1/images/variations":
                _attach("image", str(compact_files.get("image_path") or compact_files.get("file_path") or ""))
            elif path == "/v1/audio/transcriptions":
                _attach("file", str(compact_files.get("audio_path") or compact_files.get("file_path") or ""))
            else:
                return {
                    "ok": False,
                    "error": f"Multipart upload is not supported for endpoint '{path}'.",
                    "body": None,
                }

            request_kwargs["data"] = {
                key: _stringify_form_value(value)
                for key, value in compact_body.items()
            }
            request_kwargs["files"] = multipart_files
        else:
            headers["Content-Type"] = "application/json"
            if body is not None:
                request_kwargs["json"] = compact_body

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.request(method, url, headers=headers, **request_kwargs)

            content_type = (response.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
            if response.status_code >= 400:
                payload: Any
                if content_type.startswith("application/json"):
                    try:
                        payload = response.json()
                    except Exception:
                        payload = {"raw": response.text}
                else:
                    payload = {"raw": response.text}
                return {
                    "ok": False,
                    "error": f"HTTP {response.status_code}",
                    "body": payload,
                    "content_type": content_type,
                }

            if content_type.startswith("application/json"):
                try:
                    payload = response.json()
                except Exception:
                    payload = {"raw": response.text}
                return {"ok": True, "body": payload, "content_type": content_type}

            if content_type.startswith("text/"):
                return {"ok": True, "body": response.text, "content_type": content_type}

            if content_type.startswith(_BINARY_CONTENT_PREFIXES) or path in _BINARY_RESPONSE_ENDPOINTS:
                saved_to = self._save_binary_response(response.content, content_type, save_to)
                return {
                    "ok": True,
                    "body": {
                        "saved_to": str(saved_to),
                        "content_type": content_type or "application/octet-stream",
                        "size_bytes": len(response.content),
                    },
                    "content_type": content_type,
                }

            return {
                "ok": True,
                "body": {"raw": response.text},
                "content_type": content_type,
            }
        except _RETRYABLE_TRANSPORT_ERRORS as exc:
            return {"ok": False, "error": str(exc), "body": None, "transport_error": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "body": None}
        finally:
            for handle in file_handles:
                try:
                    handle.close()
                except Exception:
                    continue

    async def _fetch_json(
        self,
        path: str,
        *,
        method: str = "GET",
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = await self._fetch_response(path, method=method, body=body)
        if not response["ok"]:
            return response
        if isinstance(response["body"], (dict, list)):
            return {"ok": True, "body": response["body"]}
        return {
            "ok": False,
            "error": f"Expected JSON response from '{path}' but received {response.get('content_type') or 'non-JSON content'}",
            "body": response["body"],
        }

    def _save_binary_response(self, content: bytes, content_type: str, save_to: str | None) -> Path:
        output_path = self._resolve_output_path(save_to, content_type)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(content)
        return output_path

    def _resolve_output_path(self, save_to: str | None, content_type: str) -> Path:
        if save_to:
            target = Path(save_to).expanduser()
            if not target.is_absolute() and self._workspace:
                target = self._workspace / target
            return target.resolve()

        extension = self._extension_for_content_type(content_type)
        base_dir = self._workspace / "attachments" / "_lemondata_nonchat" if self._workspace else Path(tempfile.gettempdir()) / "lemonclaw-lemondata-nonchat"
        return (base_dir / f"{uuid.uuid4().hex}{extension}").resolve()

    @staticmethod
    def _extension_for_content_type(content_type: str) -> str:
        normalized = (content_type or "").split(";", 1)[0].strip().lower()
        explicit = {
            "audio/mpeg": ".mp3",
            "audio/mp3": ".mp3",
            "audio/wav": ".wav",
            "audio/x-wav": ".wav",
            "audio/ogg": ".ogg",
            "audio/flac": ".flac",
            "image/png": ".png",
            "image/jpeg": ".jpg",
        }
        if normalized in explicit:
            return explicit[normalized]
        guessed = mimetypes.guess_extension(normalized or "application/octet-stream")
        return guessed or ".bin"

    @staticmethod
    def _request_guidance(category: str) -> dict[str, Any]:
        guidance: dict[str, dict[str, Any]] = {
            "image": {
                "default_endpoint": "/v1/images/generations",
                "allowed_endpoints": sorted(_ALLOWED_ENDPOINTS["image"]),
                "recipes": {
                    "/v1/images/generations": {
                        "request_mode": "json",
                        "common_payload_fields": [
                            "prompt",
                            "operation",
                            "size",
                            "quality",
                            "style",
                            "n",
                            "image_url",
                            "image_urls",
                            "reference_image_urls",
                            "mask_url",
                        ],
                        "tool_file_shortcuts": [
                            "files.image_path -> payload.image_url as data URL",
                            "files.image_paths -> payload.image_urls as data URLs",
                            "files.reference_image_paths -> payload.reference_image_urls as data URLs",
                            "files.mask_path -> payload.mask_url as data URL",
                        ],
                    },
                    "/v1/images/edits": {
                        "request_modes": ["json", "multipart"],
                        "json_payload_fields": ["prompt", "image_url", "n", "quality", "size", "response_format", "user"],
                        "multipart_file_fields": ["files.image_path", "files.mask_path"],
                    },
                    "/v1/images/variations": {
                        "request_mode": "multipart",
                        "multipart_file_fields": ["files.image_path"],
                        "payload_fields": ["model", "n", "size", "response_format", "user"],
                    },
                },
            },
            "video": {
                "default_endpoint": "/v1/videos/generations",
                "allowed_endpoints": sorted(_ALLOWED_ENDPOINTS["video"]),
                "recipes": {
                    "/v1/videos/generations": {
                        "request_mode": "json",
                        "common_payload_fields": ["prompt", "image_url", "image_urls", "duration", "aspect_ratio"],
                    },
                },
            },
            "music": {
                "default_endpoint": "/v1/music/generations",
                "allowed_endpoints": sorted(_ALLOWED_ENDPOINTS["music"]),
                "recipes": {
                    "/v1/music/generations": {
                        "request_mode": "json",
                        "common_payload_fields": ["prompt", "duration", "style", "lyrics"],
                    },
                },
            },
            "3d": {
                "default_endpoint": "/v1/3d/generations",
                "allowed_endpoints": sorted(_ALLOWED_ENDPOINTS["3d"]),
                "recipes": {
                    "/v1/3d/generations": {
                        "request_mode": "json",
                        "common_payload_fields": ["prompt", "image_url", "texture", "quality"],
                    },
                },
            },
            "tts": {
                "default_endpoint": "/v1/audio/speech",
                "allowed_endpoints": sorted(_ALLOWED_ENDPOINTS["tts"]),
                "recipes": {
                    "/v1/audio/speech": {
                        "request_mode": "json",
                        "common_payload_fields": ["input", "voice", "model", "response_format", "language_code", "speed"],
                        "binary_output": "Returns audio bytes. Use save_to to control the output path.",
                    },
                },
            },
            "stt": {
                "default_endpoint": "/v1/audio/transcriptions",
                "allowed_endpoints": sorted(_ALLOWED_ENDPOINTS["stt"]),
                "recipes": {
                    "/v1/audio/transcriptions": {
                        "request_mode": "multipart",
                        "multipart_file_fields": ["files.audio_path", "files.file_path"],
                        "payload_fields": ["model", "language", "prompt", "response_format", "temperature"],
                    },
                },
            },
            "embedding": {
                "default_endpoint": "/v1/embeddings",
                "allowed_endpoints": sorted(_ALLOWED_ENDPOINTS["embedding"]),
                "recipes": {
                    "/v1/embeddings": {
                        "request_mode": "json",
                        "common_payload_fields": ["input", "dimensions", "encoding_format"],
                    },
                },
            },
            "rerank": {
                "default_endpoint": "/v1/rerank",
                "allowed_endpoints": sorted(_ALLOWED_ENDPOINTS["rerank"]),
                "recipes": {
                    "/v1/rerank": {
                        "request_mode": "json",
                        "common_payload_fields": ["query", "documents", "top_n", "return_documents"],
                    },
                },
            },
            "translation": {
                "default_endpoint": "/v1/translations",
                "allowed_endpoints": sorted(_ALLOWED_ENDPOINTS["translation"]),
                "recipes": {
                    "/v1/translations": {
                        "request_mode": "json",
                        "common_payload_fields": ["text", "target_language", "source_language", "tone"],
                    },
                },
            },
        }
        return guidance.get(category, {
            "default_endpoint": _DEFAULT_ENDPOINTS.get(category),
            "allowed_endpoints": sorted(_ALLOWED_ENDPOINTS.get(category, [])),
        })
