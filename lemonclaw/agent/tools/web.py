"""Web tools: web_search and web_fetch."""

import html
import json
import os
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from lemonclaw.agent.tools.base import Tool
from lemonclaw.agent.tools.search_providers import (
    BraveSearchProvider,
    DuckDuckGoSearchProvider,
    SearchProvider,
    SearchProviderAttempt,
    SearchResponse,
)

# Shared constants
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_2) AppleWebKit/537.36"
MAX_REDIRECTS = 5  # Limit redirects to prevent DoS attacks


def _format_search_diagnostics(provider_names: list[str], attempts: list[SearchProviderAttempt]) -> str:
    """Format search fallback diagnostics in a compact, agent-readable way."""
    lines = ["Diagnostics:", "Provider chain:"]
    lines.extend(f"- provider={name}" for name in provider_names or ["none"])
    lines.append("Provider matrix:")
    lines.extend(attempt.to_line() for attempt in attempts)
    return "\n".join(lines)


def _strip_tags(text: str) -> str:
    """Remove HTML tags and decode entities."""
    text = re.sub(r'<script[\s\S]*?</script>', '', text, flags=re.I)
    text = re.sub(r'<style[\s\S]*?</style>', '', text, flags=re.I)
    text = re.sub(r'<[^>]+>', '', text)
    return html.unescape(text).strip()


def _normalize(text: str) -> str:
    """Normalize whitespace."""
    text = re.sub(r'[ \t]+', ' ', text)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def _infer_search_status(result: SearchResponse) -> str:
    if result.error:
        return "error"
    if result.results:
        return "success"
    if result.warning:
        return "warning"
    return "empty"


def _validate_url(url: str) -> tuple[bool, str, str]:
    """Validate URL shape.

    Returns (is_valid, error_msg, resolved_ip).
    resolved_ip is unused in full-power mode and kept for compatibility.
    """
    try:
        p = urlparse(url)
        if p.scheme not in ('http', 'https'):
            return False, f"Only http/https allowed, got '{p.scheme or 'none'}'", ""
        if not p.netloc:
            return False, "Missing domain", ""
        hostname = p.hostname or ""
        if not hostname:
            return False, "Missing hostname", ""
        return True, "", ""
    except Exception as e:
        return False, str(e), ""


class WebSearchTool(Tool):
    """Search the web through pluggable search providers."""
    
    name = "web_search"
    description = "Search the web. Returns titles, URLs, and snippets."
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "count": {"type": "integer", "description": "Results (1-10)", "minimum": 1, "maximum": 10}
        },
        "required": ["query"]
    }
    
    def __init__(
        self,
        api_key: str | None = None,
        max_results: int = 5,
        providers: list[SearchProvider] | None = None,
    ):
        self._init_api_key = api_key
        self.max_results = max_results
        self._providers = providers

    @property
    def api_key(self) -> str:
        """Resolve API key at call time so env/config changes are picked up."""
        return self._init_api_key or os.environ.get("BRAVE_API_KEY", "")

    async def execute(self, query: str, count: int | None = None, **kwargs: Any) -> str:
        n = min(max(count or self.max_results, 1), 10)
        providers = self._providers or self._default_providers()
        provider_names = [provider.name for provider in providers]
        attempts: list[SearchProviderAttempt] = []

        for provider in providers:
            result = await provider.search(query, n)
            attempts.append(
                SearchProviderAttempt(
                    provider=result.provider,
                    status=_infer_search_status(result),
                    compatibility=result.compatibility,
                    result_count=len(result.results),
                    error=result.error,
                    warning=result.warning,
                )
            )
            if result.results:
                return self._format_results(query, result, attempts[-1])

        headline = f"Search error: {query}" if any(item.error for item in attempts) else f"No results for: {query}"
        return "\n".join([headline, _format_search_diagnostics(provider_names, attempts)])

    def _default_providers(self) -> list[SearchProvider]:
        providers: list[SearchProvider] = []
        if self.api_key:
            providers.append(BraveSearchProvider(self.api_key))
        providers.append(DuckDuckGoSearchProvider())
        return providers

    @staticmethod
    def _format_results(query: str, response: SearchResponse, attempt: SearchProviderAttempt) -> str:
        lines = [
            f"Results for: {query}",
            f"Provider: {response.provider}",
            f"Provider status: {attempt.status}",
            f"Provider compatibility: {attempt.compatibility}",
            "Provider matrix:",
            attempt.to_line(),
            "",
        ]
        for i, item in enumerate(response.results, 1):
            lines.append(f"{i}. {item.title}\n   {item.url}")
            if item.description:
                lines.append(f"   {item.description}")
        return "\n".join(lines)


class WebFetchTool(Tool):
    """Fetch and extract content from a URL using Readability."""
    
    name = "web_fetch"
    description = "Fetch URL and extract readable content (HTML → markdown/text)."
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to fetch"},
            "extractMode": {"type": "string", "enum": ["markdown", "text"], "default": "markdown"},
            "maxChars": {"type": "integer", "minimum": 100}
        },
        "required": ["url"]
    }
    
    def __init__(self, max_chars: int = 50000):
        self.max_chars = max_chars
    
    async def execute(self, url: str, extractMode: str = "markdown", maxChars: int | None = None, **kwargs: Any) -> str:
        from readability import Document

        max_chars = maxChars or self.max_chars

        is_valid, error_msg, _resolved_ip = _validate_url(url)
        if not is_valid:
            return json.dumps({"error": f"URL validation failed: {error_msg}", "url": url}, ensure_ascii=False)

        try:
            async with httpx.AsyncClient(
                follow_redirects=False,
                timeout=30.0,
                verify=True,
            ) as client:
                current_url = url
                for _ in range(MAX_REDIRECTS):
                    r = await client.get(
                        current_url,
                        headers={"User-Agent": USER_AGENT},
                    )
                    if r.status_code in (301, 302, 303, 307, 308):
                        location = r.headers.get("location", "")
                        if not location:
                            break
                        # Make absolute if relative
                        if location.startswith("/"):
                            p = urlparse(current_url)
                            location = f"{p.scheme}://{p.netloc}{location}"
                        redir_valid, redir_err, _redir_ip = _validate_url(location)
                        if not redir_valid:
                            return json.dumps({"error": f"Redirect blocked: {redir_err}", "url": url}, ensure_ascii=False)
                        current_url = location
                        continue
                    break
                r.raise_for_status()
            
            ctype = r.headers.get("content-type", "")
            
            # JSON
            if "application/json" in ctype:
                text, extractor = json.dumps(r.json(), indent=2, ensure_ascii=False), "json"
            # HTML
            elif "text/html" in ctype or r.text[:256].lower().startswith(("<!doctype", "<html")):
                doc = Document(r.text)
                content = self._to_markdown(doc.summary()) if extractMode == "markdown" else _strip_tags(doc.summary())
                text = f"# {doc.title()}\n\n{content}" if doc.title() else content
                extractor = "readability"
            else:
                text, extractor = r.text, "raw"
            
            truncated = len(text) > max_chars
            if truncated:
                text = text[:max_chars]
            
            return json.dumps({"url": url, "finalUrl": str(r.url), "status": r.status_code,
                              "extractor": extractor, "truncated": truncated, "length": len(text), "text": text}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e), "url": url}, ensure_ascii=False)
    
    def _to_markdown(self, html: str) -> str:
        """Convert HTML to markdown."""
        # Convert links, headings, lists before stripping tags
        text = re.sub(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>([\s\S]*?)</a>',
                      lambda m: f'[{_strip_tags(m[2])}]({m[1]})', html, flags=re.I)
        text = re.sub(r'<h([1-6])[^>]*>([\s\S]*?)</h\1>',
                      lambda m: f'\n{"#" * int(m[1])} {_strip_tags(m[2])}\n', text, flags=re.I)
        text = re.sub(r'<li[^>]*>([\s\S]*?)</li>', lambda m: f'\n- {_strip_tags(m[1])}', text, flags=re.I)
        text = re.sub(r'</(p|div|section|article)>', '\n\n', text, flags=re.I)
        text = re.sub(r'<(br|hr)\s*/?>', '\n', text, flags=re.I)
        return _normalize(_strip_tags(text))
