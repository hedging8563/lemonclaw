from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from lemonclaw.providers.base import LLMResponse
from lemonclaw.providers.openai_codex_provider import OpenAICodexProvider


@pytest.mark.asyncio
async def test_openai_codex_provider_does_not_disable_tls_on_cert_failure() -> None:
    provider = OpenAICodexProvider()

    with patch("lemonclaw.providers.openai_codex_provider.get_codex_token", return_value=SimpleNamespace(account_id="acct", access="token")), \
         patch("lemonclaw.providers.openai_codex_provider._request_codex", new=AsyncMock(side_effect=RuntimeError("CERTIFICATE_VERIFY_FAILED")) ) as request_mock:
        response = await provider.chat(messages=[{"role": "user", "content": "hello"}])

    assert isinstance(response, LLMResponse)
    assert response.finish_reason == "error"
    assert "CERTIFICATE_VERIFY_FAILED" in (response.content or "")
    request_mock.assert_awaited_once()
    assert request_mock.await_args.kwargs["verify"] is True
