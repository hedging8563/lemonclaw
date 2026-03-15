"""Structured HTTP request tool with SSRF protections."""

from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from lemonclaw.agent.tools.base import Tool
from lemonclaw.agent.tools.web import MAX_REDIRECTS, USER_AGENT, _validate_url


def _domain_allowed(host: str, patterns: list[str]) -> bool:
    if not patterns:
        return True
    host = host.lower()
    for pattern in patterns:
        p = pattern.strip().lower()
        if not p:
            continue
        if fnmatch.fnmatch(host, p):
            return True
        if p.startswith("*.") and (host == p[2:] or host.endswith("." + p[2:])):
            return True
        if host == p:
            return True
    return False


# -- Retryable status codes (used by both tool and delivery) --
RETRYABLE_STATUS_CODES = {408, 429, 502, 503, 504}


@dataclass
class HTTPRequestResult:
    """Structured result from _execute_http_request."""

    ok: bool
    status_code: int | None
    final_url: str
    method: str
    headers: dict[str, str]
    body: Any
    error: str | None = None
    dns_error: bool = False


async def _execute_http_request(
    *,
    method: str,
    url: str,
    headers: dict[str, str],
    query: dict[str, str],
    body: dict[str, Any],
    timeout: int,
    allow_domains: list[str],
    auth_profiles: dict[str, dict[str, str]],
    auth_profile: str = "",
    expect_json: bool = True,
) -> HTTPRequestResult:
    """Shared HTTP execution with SSRF protection and redirect tracking.

    Used by both HTTPRequestTool.execute() and outbox delivery.
    Raises nothing — all errors are captured in the result.
    """
    method = method.upper().strip()

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if not _domain_allowed(host, allow_domains):
        return HTTPRequestResult(
            ok=False, status_code=None, final_url=url, method=method,
            headers={}, body=None, error=f"Domain '{host}' is not in allow_domains",
        )

    if auth_profile:
        profile_headers = auth_profiles.get(auth_profile)
        if not profile_headers:
            return HTTPRequestResult(
                ok=False, status_code=None, final_url=url, method=method,
                headers={}, body=None, error=f"Unknown auth profile '{auth_profile}'",
            )
        for key, value in profile_headers.items():
            headers.setdefault(key, value)

    validated, error, resolved_ip = _validate_url(url)
    if not validated:
        is_dns = error in {"DNS resolution failed", "No addresses returned by DNS"}
        return HTTPRequestResult(
            ok=False, status_code=None, final_url=url, method=method,
            headers={}, body=None, error=f"URL validation failed: {error}", dns_error=is_dns,
        )

    response = None
    current_url = url
    current_ip = resolved_ip
    current_port = parsed.port or (443 if parsed.scheme == "https" else 80)
    transport = httpx.AsyncHTTPTransport()

    try:
        async with httpx.AsyncClient(
            follow_redirects=False,
            transport=transport,
            timeout=float(timeout),
            verify=True,
        ) as client:
            for _ in range(MAX_REDIRECTS):
                current_parsed = urlparse(current_url)
                request_url = current_url.replace(
                    f"{current_parsed.scheme}://{current_parsed.netloc}",
                    f"{current_parsed.scheme}://{current_ip}:{current_port}",
                    1,
                )
                req_headers = {"User-Agent": USER_AGENT, "Host": current_parsed.netloc, **headers}
                response = await client.request(
                    method,
                    request_url,
                    headers=req_headers,
                    params=query if method in {"GET", "HEAD", "DELETE"} else None,
                    json=body if method not in {"GET", "HEAD"} and body else None,
                )
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("location", "")
                    if not location:
                        break
                    if location.startswith("/"):
                        location = f"{current_parsed.scheme}://{current_parsed.netloc}{location}"
                    redir_ok, redir_err, redir_ip = _validate_url(location)
                    if not redir_ok:
                        is_dns = redir_err in {"DNS resolution failed", "No addresses returned by DNS"}
                        return HTTPRequestResult(
                            ok=False, status_code=None, final_url=current_url, method=method,
                            headers={}, body=None,
                            error=f"Redirect blocked: {redir_err}", dns_error=is_dns,
                        )
                    redir_parsed = urlparse(location)
                    redir_host = (redir_parsed.hostname or "").lower()
                    if not _domain_allowed(redir_host, allow_domains):
                        return HTTPRequestResult(
                            ok=False, status_code=None, final_url=current_url, method=method,
                            headers={}, body=None,
                            error=f"Redirect domain '{redir_host}' is not in allow_domains",
                        )
                    current_url = location
                    current_ip = redir_ip
                    current_port = redir_parsed.port or (443 if redir_parsed.scheme == "https" else 80)
                    continue
                break
    except Exception as e:
        return HTTPRequestResult(
            ok=False, status_code=None, final_url=url, method=method,
            headers={}, body=None, error=f"HTTP request failed: {e}",
        )

    if response is None:
        return HTTPRequestResult(
            ok=False, status_code=None, final_url=url, method=method,
            headers={}, body=None, error="No response received",
        )

    content_type = response.headers.get("content-type", "")
    raw_payload: Any
    if expect_json and "json" in content_type:
        try:
            raw_payload = response.json()
        except Exception:
            raw_payload = response.text[:10000]
    else:
        raw_payload = response.text[:10000]

    return HTTPRequestResult(
        ok=response.status_code < 400,
        status_code=response.status_code,
        final_url=current_url,
        method=method,
        headers=dict(response.headers),
        body=raw_payload,
    )


class HTTPRequestTool(Tool):
    """Perform structured HTTP requests with optional auth profiles."""

    def __init__(
        self,
        *,
        timeout: int = 30,
        allow_domains: list[str] | None = None,
        auth_profiles: dict[str, dict[str, str]] | None = None,
    ):
        self._timeout = timeout
        self._allow_domains = allow_domains or []
        self._auth_profiles = auth_profiles or {}

    @property
    def name(self) -> str:
        return "http_request"

    @property
    def description(self) -> str:
        return (
            "Perform a structured HTTP request to a public http/https endpoint. "
            "Supports method, headers, query params, JSON body, and optional auth profile. "
            "Use this for API automation instead of shell curl."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "method": {
                    "type": "string",
                    "enum": ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"],
                    "description": "HTTP method.",
                },
                "url": {
                    "type": "string",
                    "description": "Public http/https URL to request.",
                    "minLength": 1,
                },
                "headers": {
                    "type": "object",
                    "description": "Optional request headers.",
                    "additionalProperties": {"type": "string"},
                },
                "query": {
                    "type": "object",
                    "description": "Optional query string parameters.",
                    "additionalProperties": {"type": "string"},
                },
                "body": {
                    "type": "object",
                    "description": "Optional JSON body for write requests.",
                    "additionalProperties": True,
                },
                "auth_profile": {
                    "type": "string",
                    "description": "Optional auth profile name configured in tools.http.auth_profiles.",
                },
                "expect_json": {
                    "type": "boolean",
                    "description": "If true, parse response as JSON when possible.",
                },
                "timeout": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 120,
                    "description": "Optional per-request timeout seconds.",
                },
            },
            "required": ["method", "url"],
        }

    def resolve_capability(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> str:
        method = str(params.get("method", "GET")).upper()
        return "http.read" if method in {"GET", "HEAD"} else "http.write"

    async def execute(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        query: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
        auth_profile: str | None = None,
        expect_json: bool = True,
        timeout: int | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        method = method.upper().strip()
        headers = dict(headers or {})
        query = dict(query or {})
        body = body or {}
        request_timeout = timeout or self._timeout

        # Internal context injected by ToolRegistry — not exposed in tool schema
        _task_id: str | None = kwargs.get("_task_id")
        _task_ledger = kwargs.get("_task_ledger")
        _step_id: str | None = kwargs.get("_step_id")
        _outbox_enabled: bool = bool(kwargs.get("_outbox_enabled"))

        # Pre-validate domain and auth before enqueuing to fail fast
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if not _domain_allowed(host, self._allow_domains):
            return {"ok": False, "summary": f"Domain '{host}' is not in allow_domains", "raw": {"url": url, "host": host}}

        if auth_profile:
            profile_headers = self._auth_profiles.get(auth_profile)
            if not profile_headers:
                return {"ok": False, "summary": f"Unknown auth profile '{auth_profile}'", "raw": {"auth_profile": auth_profile}}

        if method not in {"GET", "HEAD"} and _outbox_enabled and _task_id and _task_ledger and _step_id:
            event = _task_ledger.enqueue_outbox(
                task_id=_task_id,
                step_id=_step_id,
                effect_type="http_json",
                target=url,
                payload={
                    "method": method,
                    "headers": headers,
                    "query": query,
                    "body": body,
                    "auth_profile": auth_profile or "",
                    "expect_json": expect_json,
                    "timeout": request_timeout,
                },
            )
            return {
                "ok": True,
                "summary": f"{method} {url} queued",
                "step_status": "waiting_outbox",
                "raw": {"event_id": event["event_id"], "queued": True, "method": method, "url": url},
                "artifacts": [],
            }

        result = await _execute_http_request(
            method=method,
            url=url,
            headers=headers,
            query=query,
            body=body,
            timeout=request_timeout,
            allow_domains=self._allow_domains,
            auth_profiles=self._auth_profiles,
            auth_profile=auth_profile or "",
            expect_json=expect_json,
        )

        if not result.ok and result.status_code is None:
            return {"ok": False, "summary": result.error or "Unknown error", "raw": {"url": url, "method": method}}

        return {
            "ok": result.ok,
            "summary": f"{result.method} {result.final_url} -> {result.status_code}",
            "raw": {
                "url": result.final_url,
                "method": result.method,
                "status_code": result.status_code,
                "headers": result.headers,
                "body": result.body,
            },
            "artifacts": [],
        }
