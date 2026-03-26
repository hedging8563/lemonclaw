"""LemonData Responses API provider."""

from __future__ import annotations

from typing import Any

import json_repair
from openai import AsyncOpenAI

from lemonclaw.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from lemonclaw.providers.litellm_provider import _is_balance_error, _sanitize_error
from lemonclaw.providers.openai_codex_provider import _convert_messages, _convert_tools


class LemonDataResponsesProvider(LLMProvider):
    """Direct OpenAI Responses API provider against LemonData gateway."""

    def __init__(
        self,
        api_key: str = "no-key",
        api_base: str = "https://api.lemondata.cc/v1",
        default_model: str = "gpt-5.4",
        extra_headers: dict[str, str] | None = None,
    ):
        super().__init__(api_key, api_base)
        self.default_model = default_model
        self.extra_headers = extra_headers or {}
        client_kwargs: dict[str, Any] = {
            "api_key": api_key,
            "base_url": api_base,
        }
        if self.extra_headers:
            client_kwargs["default_headers"] = self.extra_headers
        self._client = AsyncOpenAI(**client_kwargs)

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        on_chunk: "OnChunkCallback | None" = None,
    ) -> LLMResponse:
        selected_model = self._strip_model_prefix(model or self.default_model)
        system_prompt, input_items = _convert_messages(self._sanitize_empty_content(messages))
        kwargs: dict[str, Any] = {
            "model": selected_model,
            "input": input_items,
            "instructions": system_prompt,
            "max_output_tokens": max(1, max_tokens),
            "temperature": temperature,
            "store": False,
            "parallel_tool_calls": True,
            "tool_choice": "auto",
        }
        if tools:
            kwargs["tools"] = _convert_tools(tools)

        try:
            response = await self._client.responses.create(**kwargs)
            parsed = self._parse_response(response)
            # This provider is request/response, not token-streaming. When the model
            # also returns tool calls, the agent loop will surface response.content via
            # on_progress before executing tools. Emitting the same full text through
            # on_chunk here makes WebUI append it twice.
            if on_chunk and parsed.content and not parsed.tool_calls:
                await on_chunk(parsed.content, first=True)
            return parsed
        except Exception as exc:
            if _is_balance_error(exc):
                return LLMResponse(
                    content="API balance insufficient. Please top up at https://lemondata.cc/dashboard/billing or switch to a cheaper model.",
                    finish_reason="error",
                )
            return LLMResponse(content=f"Error: {_sanitize_error(exc)}", finish_reason="error")

    def get_default_model(self) -> str:
        return self.default_model

    @staticmethod
    def _strip_model_prefix(model: str) -> str:
        if model.startswith("lemondata_response/"):
            return model.split("/", 1)[1]
        return model

    def _parse_response(self, response: Any) -> LLMResponse:
        content_parts: list[str] = []
        tool_calls: list[ToolCallRequest] = []

        for item in list(getattr(response, "output", []) or []):
            item_type = getattr(item, "type", None)
            if item_type == "message":
                for part in list(getattr(item, "content", []) or []):
                    part_type = getattr(part, "type", None)
                    if part_type in {"output_text", "text"}:
                        text = getattr(part, "text", None)
                        if text:
                            content_parts.append(str(text))
            elif item_type == "function_call":
                raw_arguments = getattr(item, "arguments", None) or "{}"
                try:
                    arguments = json_repair.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
                except Exception:
                    arguments = {"raw": raw_arguments}
                call_id = getattr(item, "call_id", None) or "call_0"
                item_id = getattr(item, "id", None) or "fc_0"
                tool_calls.append(
                    ToolCallRequest(
                        id=f"{call_id}|{item_id}",
                        name=str(getattr(item, "name", None) or ""),
                        arguments=arguments if isinstance(arguments, dict) else {"value": arguments},
                    )
                )

        usage = getattr(response, "usage", None)
        usage_payload: dict[str, int] = {}
        if usage is not None:
            input_tokens = getattr(usage, "input_tokens", None)
            output_tokens = getattr(usage, "output_tokens", None)
            total_tokens = getattr(usage, "total_tokens", None)
            if isinstance(input_tokens, int):
                usage_payload["prompt_tokens"] = input_tokens
            if isinstance(output_tokens, int):
                usage_payload["completion_tokens"] = output_tokens
            if isinstance(total_tokens, int):
                usage_payload["total_tokens"] = total_tokens
            elif usage_payload:
                usage_payload["total_tokens"] = usage_payload.get("prompt_tokens", 0) + usage_payload.get("completion_tokens", 0)

        status = getattr(response, "status", None) or "completed"
        finish_reason = "stop" if status == "completed" else ("length" if status == "incomplete" else "error")
        return LLMResponse(
            content="\n".join(part for part in content_parts if part).strip() or None,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage_payload,
        )
