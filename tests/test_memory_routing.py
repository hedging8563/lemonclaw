from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from lemonclaw.config.defaults import DEFAULT_CONSOLIDATION_MODEL


@pytest.mark.asyncio
async def test_consolidation_uses_provider_resolved_for_consolidation_model(make_agent_loop) -> None:
    primary_provider = MagicMock()
    primary_provider.get_default_model.return_value = "gpt-5.4"
    primary_provider.default_model = "gpt-5.4"

    consolidation_provider = MagicMock()
    consolidation_provider.get_default_model.return_value = DEFAULT_CONSOLIDATION_MODEL
    consolidation_provider.default_model = DEFAULT_CONSOLIDATION_MODEL

    def _provider_factory(model: str | None):
        if model == DEFAULT_CONSOLIDATION_MODEL:
            return consolidation_provider
        return primary_provider

    loop, _bus = make_agent_loop(provider=primary_provider, provider_factory=_provider_factory)
    loop.context.memory.consolidate = AsyncMock(return_value=True)
    session = MagicMock()

    result = await loop._consolidate_memory(session)

    assert result is True
    loop.context.memory.consolidate.assert_awaited_once()
    args = loop.context.memory.consolidate.await_args.args
    assert args[0] is session
    assert args[1] is consolidation_provider
    assert args[2] == DEFAULT_CONSOLIDATION_MODEL
