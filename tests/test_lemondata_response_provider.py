from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from lemonclaw.providers.lemondata_response_provider import LemonDataResponsesProvider


@pytest.mark.asyncio
async def test_lemondata_response_provider_parses_text_and_tool_calls() -> None:
    provider = LemonDataResponsesProvider(api_key="sk-test", api_base="https://api.lemondata.cc/v1", default_model="gpt-5.4")
    provider._client.responses.create = AsyncMock(return_value=SimpleNamespace(
        output=[
            SimpleNamespace(
                type="message",
                content=[SimpleNamespace(type="output_text", text="Hello from responses")],
            ),
            SimpleNamespace(
                type="function_call",
                id="fc_123",
                call_id="call_123",
                name="search_knowledge",
                arguments='{"query":"retry outbox"}',
            ),
        ],
        usage=SimpleNamespace(input_tokens=11, output_tokens=7, total_tokens=18),
        status="completed",
    ))

    response = await provider.chat(
        messages=[{"role": "user", "content": "find retry docs"}],
        tools=[{"type": "function", "function": {"name": "search_knowledge", "parameters": {"type": "object"}}}],
        model="gpt-5.4",
    )

    assert response.content == "Hello from responses"
    assert response.tool_calls[0].id == "call_123|fc_123"
    assert response.tool_calls[0].name == "search_knowledge"
    assert response.tool_calls[0].arguments == {"query": "retry outbox"}
    assert response.usage["prompt_tokens"] == 11
    assert response.finish_reason == "stop"


@pytest.mark.asyncio
async def test_lemondata_response_provider_calls_on_chunk_once() -> None:
    provider = LemonDataResponsesProvider(api_key="sk-test", api_base="https://api.lemondata.cc/v1", default_model="gpt-5.4")
    provider._client.responses.create = AsyncMock(return_value=SimpleNamespace(
        output=[SimpleNamespace(type="message", content=[SimpleNamespace(type="output_text", text="Chunked once")])],
        usage=None,
        status="completed",
    ))
    on_chunk = AsyncMock()

    response = await provider.chat(
        messages=[{"role": "user", "content": "hello"}],
        on_chunk=on_chunk,
    )

    assert response.content == "Chunked once"
    on_chunk.assert_awaited_once_with("Chunked once", first=True)
