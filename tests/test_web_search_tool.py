from lemonclaw.agent.tools.search_providers import SearchProvider, SearchResponse, SearchResult
from lemonclaw.agent.tools.web import WebSearchTool


class _FakeProvider:
    def __init__(
        self,
        name: str,
        results: list[SearchResult] | None = None,
        error: str | None = None,
        warning: str | None = None,
    ) -> None:
        self.name = name
        self._results = results or []
        self._error = error
        self._warning = warning

    async def search(self, query: str, count: int) -> SearchResponse:
        return SearchResponse(
            provider=self.name,
            results=self._results[:count],
            error=self._error,
            warning=self._warning,
        )


async def test_web_search_tool_includes_source_attribution() -> None:
    tool = WebSearchTool(providers=[
        _FakeProvider("brave", [SearchResult(title="Example", url="https://example.com", description="Snippet")]),
    ])

    result = await tool.execute("example")

    assert "Provider: brave" in result
    assert "https://example.com" in result


async def test_web_search_tool_falls_back_when_primary_errors() -> None:
    tool = WebSearchTool(providers=[
        _FakeProvider("brave", error="quota exceeded"),
        _FakeProvider("duckduckgo", [SearchResult(title="Fallback", url="https://ddg.example", description="Backup")]),
    ])

    result = await tool.execute("fallback query")

    assert "Provider: duckduckgo" in result
    assert "https://ddg.example" in result


async def test_web_search_tool_reports_provider_chain_errors() -> None:
    tool = WebSearchTool(providers=[
        _FakeProvider("brave", error="quota exceeded"),
        _FakeProvider("duckduckgo", error="network down"),
    ])

    result = await tool.execute("broken query")

    assert "Search error:" in result
    assert "brave: quota exceeded" in result
    assert "duckduckgo: network down" in result


async def test_web_search_tool_surfaces_provider_warnings_when_no_results() -> None:
    tool = WebSearchTool(providers=[
        _FakeProvider("duckduckgo", warning="parser found no result markup"),
    ])

    result = await tool.execute("broken html")

    assert "No results for: broken html" in result
    assert "Warnings:" in result
    assert "duckduckgo: parser found no result markup" in result
