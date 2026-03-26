"""Search provider abstraction for the web_search tool."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Protocol

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


@dataclass
class SearchResponse:
    provider: str
    results: list[SearchResult]
    error: str | None = None


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
            return SearchResponse(provider=self.name, results=results)
        except Exception as exc:
            return SearchResponse(provider=self.name, results=[], error=str(exc))


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

            return SearchResponse(provider=self.name, results=results)
        except Exception as exc:
            return SearchResponse(provider=self.name, results=[], error=str(exc))
