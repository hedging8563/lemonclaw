from lemonclaw.providers.registry import find_by_name


def test_managed_lemondata_provider_registry_keeps_expected_api_shapes() -> None:
    lemondata = find_by_name("lemondata")
    responses = find_by_name("lemondata_response")
    claude = find_by_name("lemondata_claude")
    minimax = find_by_name("lemondata_minimax")
    gemini = find_by_name("lemondata_gemini")

    assert lemondata is not None
    assert responses is not None
    assert claude is not None
    assert minimax is not None
    assert gemini is not None

    assert lemondata.default_api_base.endswith("/v1")
    assert responses.default_api_base.endswith("/v1")
    assert not claude.default_api_base.endswith("/v1")
    assert not minimax.default_api_base.endswith("/v1")
    assert not gemini.default_api_base.endswith("/v1")

    assert lemondata.is_gateway is True
    assert responses.is_gateway is True
    assert claude.is_gateway is True
    assert minimax.is_gateway is True
    assert gemini.is_gateway is True

    assert responses.keywords == ("gpt-5.4", "gpt-5.4-pro")
    assert claude.keywords == ("claude",)
    assert minimax.keywords == ("minimax",)
    assert gemini.keywords == ("gemini",)
