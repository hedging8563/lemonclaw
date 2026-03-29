"""Search provider abstraction for the web_search tool."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Literal, Protocol

import httpx

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_2) AppleWebKit/537.36"


def _strip_tags(text: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>", "", text, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", "", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


@dataclass
class SearchResult:
    title: str
    url: str
    description: str = ""


SearchProviderStatus = Literal["success", "empty", "warning", "error"]
SearchProviderCompatibility = Literal["native"]


@dataclass
class SearchResponse:
    provider: str
    results: list[SearchResult]
    error: str | None = None
    warning: str | None = None
    status: SearchProviderStatus = "success"
    compatibility: SearchProviderCompatibility = "native"


@dataclass(frozen=True)
class SearchProviderAttempt:
    provider: str
    status: SearchProviderStatus
    compatibility: SearchProviderCompatibility
    result_count: int
    error: str | None = None
    warning: str | None = None

    def to_line(self) -> str:
        parts = [
            f"provider={self.provider}",
            f"status={self.status}",
            f"compatibility={self.compatibility}",
            f"results={self.result_count}",
        ]
        if self.error:
            parts.append(f"error={self.error}")
        if self.warning:
            parts.append(f"warning={self.warning}")
        return "- " + "; ".join(parts)


def _looks_like_ddg_no_results(body: str) -> bool:
    lower = body.lower()
    return (
        "no results found" in lower
        or "no results." in lower
        or "did not match any documents" in lower
    )


class SearchProvider(Protocol):
    name: str

    async def search(self, query: str, count: int) -> SearchResponse:
        ...


class BraveSearchProvider:
    name = "brave"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    async def search(self, query: str, count: int) -> SearchResponse:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    params={"q": query, "count": count},
                    headers={"Accept": "application/json", "X-Subscription-Token": self.api_key},
                    timeout=10.0,
                )
                response.raise_for_status()

            raw_results = response.json().get("web", {}).get("results", [])
            results = [
                SearchResult(
                    title=str(item.get("title", "")),
                    url=str(item.get("url", "")),
                    description=str(item.get("description", "")),
                )
                for item in raw_results[:count]
                if item.get("title") and item.get("url")
            ]
            return SearchResponse(
                provider=self.name,
                results=results,
                status="success" if results else "empty",
            )
        except Exception as exc:
            return SearchResponse(provider=self.name, results=[], error=str(exc), status="error")


class DuckDuckGoSearchProvider:
    name = "duckduckgo"

    async def search(self, query: str, count: int) -> SearchResponse:
        try:
            async with httpx.AsyncClient(follow_redirects=True, max_redirects=3) as client:
                response = await client.get(
                    "https://html.duckduckgo.com/html/",
                    params={"q": query},
                    headers={"User-Agent": USER_AGENT},
                    timeout=10.0,
                )
                response.raise_for_status()

            results: list[SearchResult] = []
            for match in re.finditer(
                r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>([\s\S]*?)</a>'
                r'[\s\S]*?<a[^>]+class="result__snippet"[^>]*>([\s\S]*?)</a>',
                response.text,
            ):
                url = match.group(1)
                title = _strip_tags(match.group(2))
                snippet = _strip_tags(match.group(3))
                if title and url:
                    results.append(SearchResult(title=title, url=url, description=snippet))
                if len(results) >= count:
                    break

            warning = None
            if not results and not _looks_like_ddg_no_results(response.text):
                warning = "DuckDuckGo HTML returned 200 but parser found no results; result markup may have changed."

            return SearchResponse(
                provider=self.name,
                results=results,
                warning=warning,
                status="success" if results else ("warning" if warning else "empty"),
            )
        except Exception as exc:
            return SearchResponse(provider=self.name, results=[], error=str(exc), status="error")
