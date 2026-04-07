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


@pytest.mark.asyncio
async def test_lemondata_response_provider_skips_on_chunk_when_tool_calls_present() -> None:
    provider = LemonDataResponsesProvider(api_key="sk-test", api_base="https://api.lemondata.cc/v1", default_model="gpt-5.4")
    provider._client.responses.create = AsyncMock(return_value=SimpleNamespace(
        output=[
            SimpleNamespace(
                type="message",
                content=[SimpleNamespace(type="output_text", text="I will first check the file.")],
            ),
            SimpleNamespace(
                type="function_call",
                id="fc_456",
                call_id="call_456",
                name="read_file",
                arguments='{"path":"notes.md"}',
            ),
        ],
        usage=None,
        status="completed",
    ))
    on_chunk = AsyncMock()

    response = await provider.chat(
        messages=[{"role": "user", "content": "check notes"}],
        on_chunk=on_chunk,
    )

    assert response.content == "I will first check the file."
    assert response.tool_calls[0].name == "read_file"
    on_chunk.assert_not_called()


@pytest.mark.asyncio
async def test_lemondata_response_provider_surfaces_balance_topup_guidance() -> None:
    provider = LemonDataResponsesProvider(api_key="sk-test", api_base="https://api.lemondata.cc/v1", default_model="gpt-5.4")
    provider._client.responses.create = AsyncMock(side_effect=Exception("Insufficient organization balance"))

    response = await provider.chat(
        messages=[{"role": "user", "content": "hello"}],
    )

    assert response.finish_reason == "error"
    assert response.content == "API balance insufficient. Please top up at https://lemondata.cc/dashboard/billing or switch to a cheaper model."


@pytest.mark.asyncio
async def test_lemondata_response_provider_uses_conservative_kwargs_for_gpt_54() -> None:
    provider = LemonDataResponsesProvider(api_key="sk-test", api_base="https://api.lemondata.cc/v1", default_model="gpt-5.4")
    provider._client.responses.create = AsyncMock(return_value=SimpleNamespace(
        output=[SimpleNamespace(type="message", content=[SimpleNamespace(type="output_text", text="ok")])],
        usage=None,
        status="completed",
    ))

    await provider.chat(
        messages=[{"role": "system", "content": "You are helpful."}, {"role": "user", "content": "hello"}],
        tools=[{"type": "function", "function": {"name": "search_knowledge", "parameters": {"type": "object"}}}],
        model="gpt-5.4",
        temperature=0.1,
    )

    kwargs = provider._client.responses.create.await_args.kwargs
    assert kwargs["model"] == "gpt-5.4"
    assert kwargs["instructions"] == "You are helpful."
    assert "temperature" not in kwargs
    assert "parallel_tool_calls" not in kwargs
    assert "tool_choice" not in kwargs
    assert "tools" not in kwargs


@pytest.mark.asyncio
async def test_lemondata_response_provider_keeps_full_kwargs_for_non_conservative_models() -> None:
    provider = LemonDataResponsesProvider(api_key="sk-test", api_base="https://api.lemondata.cc/v1", default_model="gpt-5.4")
    provider._client.responses.create = AsyncMock(return_value=SimpleNamespace(
        output=[SimpleNamespace(type="message", content=[SimpleNamespace(type="output_text", text="ok")])],
        usage=None,
        status="completed",
    ))

    await provider.chat(
        messages=[{"role": "system", "content": "You are helpful."}, {"role": "user", "content": "hello"}],
        tools=[{"type": "function", "function": {"name": "search_knowledge", "parameters": {"type": "object"}}}],
        model="claude-opus-4-6",
        temperature=0.1,
    )

    kwargs = provider._client.responses.create.await_args.kwargs
    assert kwargs["model"] == "claude-opus-4-6"
    assert kwargs["instructions"] == "You are helpful."
    assert kwargs["temperature"] == 0.1
    assert kwargs["parallel_tool_calls"] is True
    assert kwargs["tool_choice"] == "auto"
    assert "tools" in kwargs
