"""Structured HTTP request tool with SSRF protections."""

from __future__ import annotations

import fnmatch
import json
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

        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if not _domain_allowed(host, self._allow_domains):
            return {"ok": False, "summary": f"Domain '{host}' is not in allow_domains", "raw": {"url": url, "host": host}}

        if auth_profile:
            profile_headers = self._auth_profiles.get(auth_profile)
            if not profile_headers:
                return {"ok": False, "summary": f"Unknown auth profile '{auth_profile}'", "raw": {"auth_profile": auth_profile}}
            for key, value in profile_headers.items():
                headers.setdefault(key, value)

        validated, error, resolved_ip = _validate_url(url)
        if not validated:
            return {"ok": False, "summary": f"URL validation failed: {error}", "raw": {"url": url}}

        response = None
        current_url = url
        current_ip = resolved_ip
        current_port = parsed.port or (443 if parsed.scheme == "https" else 80)
        transport = httpx.AsyncHTTPTransport()

        try:
            async with httpx.AsyncClient(
                follow_redirects=False,
                transport=transport,
                timeout=float(request_timeout),
                verify=True,
            ) as client:
                for _ in range(MAX_REDIRECTS):
                    request_url = current_url.replace(
                        f"{urlparse(current_url).scheme}://{urlparse(current_url).netloc}",
                        f"{urlparse(current_url).scheme}://{current_ip}:{current_port}",
                        1,
                    )
                    req_headers = {"User-Agent": USER_AGENT, "Host": urlparse(current_url).netloc, **headers}
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
                            p = urlparse(current_url)
                            location = f"{p.scheme}://{p.netloc}{location}"
                        redir_ok, redir_err, redir_ip = _validate_url(location)
                        if not redir_ok:
                            return {"ok": False, "summary": f"Redirect blocked: {redir_err}", "raw": {"url": current_url, "redirect": location}}
                        redir_parsed = urlparse(location)
                        redir_host = (redir_parsed.hostname or "").lower()
                        if not _domain_allowed(redir_host, self._allow_domains):
                            return {"ok": False, "summary": f"Redirect domain '{redir_host}' is not in allow_domains", "raw": {"redirect": location}}
                        current_url = location
                        current_ip = redir_ip
                        current_port = redir_parsed.port or (443 if redir_parsed.scheme == "https" else 80)
                        continue
                    break
        except Exception as e:
            return {"ok": False, "summary": f"HTTP request failed: {e}", "raw": {"url": url, "method": method}}

        if response is None:
            return {"ok": False, "summary": "No response received", "raw": {"url": url, "method": method}}

        content_type = response.headers.get("content-type", "")
        raw_payload: Any
        if expect_json and "json" in content_type:
            try:
                raw_payload = response.json()
            except Exception:
                raw_payload = response.text[:10000]
        else:
            raw_payload = response.text[:10000]

        ok = response.status_code < 400
        return {
            "ok": ok,
            "summary": f"{method} {current_url} -> {response.status_code}",
            "raw": {
                "url": current_url,
                "method": method,
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "body": raw_payload,
            },
            "artifacts": [],
        }
