import shutil
import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from lemonclaw.cli.commands import app
from lemonclaw.config.schema import Config
from lemonclaw.providers.base import LLMResponse
from lemonclaw.providers.lemondata_response_provider import LemonDataResponsesProvider
from lemonclaw.providers.litellm_provider import LiteLLMProvider
from lemonclaw.providers.openai_codex_provider import _strip_model_prefix
from lemonclaw.providers.registry import find_by_model

runner = CliRunner()


@pytest.fixture
def mock_paths():
    """Mock config/workspace paths for test isolation."""
    with patch("lemonclaw.config.loader.get_config_path") as mock_cp, \
         patch("lemonclaw.config.loader.save_config") as mock_sc, \
         patch("lemonclaw.config.loader.load_config") as mock_lc, \
         patch("lemonclaw.utils.helpers.get_workspace_path") as mock_ws:

        base_dir = Path("./test_onboard_data")
        if base_dir.exists():
            shutil.rmtree(base_dir)
        base_dir.mkdir()

        config_file = base_dir / "config.json"
        workspace_dir = base_dir / "workspace"

        mock_cp.return_value = config_file
        mock_ws.return_value = workspace_dir
        mock_sc.side_effect = lambda config: config_file.write_text("{}")

        yield config_file, workspace_dir

        if base_dir.exists():
            shutil.rmtree(base_dir)


def test_onboard_fresh_install(mock_paths):
    """No existing config — should create from scratch."""
    config_file, workspace_dir = mock_paths

    result = runner.invoke(app, ["onboard"])

    assert result.exit_code == 0
    assert "Created config" in result.stdout
    assert "Created workspace" in result.stdout
    assert "lemonclaw is ready" in result.stdout
    assert config_file.exists()
    assert (workspace_dir / "AGENTS.md").exists()
    assert (workspace_dir / "memory" / "MEMORY.md").exists()


def test_onboard_existing_config_refresh(mock_paths):
    """Config exists, user declines overwrite — should refresh (load-merge-save)."""
    config_file, workspace_dir = mock_paths
    config_file.write_text('{"existing": true}')

    result = runner.invoke(app, ["onboard"], input="n\n")

    assert result.exit_code == 0
    assert "Config already exists" in result.stdout
    assert "existing values preserved" in result.stdout
    assert workspace_dir.exists()
    assert (workspace_dir / "AGENTS.md").exists()


def test_onboard_existing_config_overwrite(mock_paths):
    """Config exists, user confirms overwrite — should reset to defaults."""
    config_file, workspace_dir = mock_paths
    config_file.write_text('{"existing": true}')

    result = runner.invoke(app, ["onboard"], input="y\n")

    assert result.exit_code == 0
    assert "Config already exists" in result.stdout
    assert "Config reset to defaults" in result.stdout
    assert workspace_dir.exists()


def test_onboard_existing_workspace_safe_create(mock_paths):
    """Workspace exists — should not recreate, but still add missing templates."""
    config_file, workspace_dir = mock_paths
    workspace_dir.mkdir(parents=True)
    config_file.write_text("{}")

    result = runner.invoke(app, ["onboard"], input="n\n")

    assert result.exit_code == 0
    assert "Created workspace" not in result.stdout
    assert "Created AGENTS.md" in result.stdout
    assert (workspace_dir / "AGENTS.md").exists()


def test_config_matches_github_copilot_codex_with_hyphen_prefix():
    config = Config()
    config.agents.defaults.model = "github-copilot/gpt-5.3-codex"

    assert config.get_provider_name() == "github_copilot"


def test_config_matches_openai_codex_with_hyphen_prefix():
    config = Config()
    config.agents.defaults.model = "openai-codex/gpt-5.1-codex"

    assert config.get_provider_name() == "openai_codex"


def test_config_matches_lemondata_response_for_gpt54():
    config = Config()
    config.agents.defaults.model = "gpt-5.4"
    config.providers.lemondata_response.api_key = "sk-test"

    assert config.get_provider_name() == "lemondata_response"


def test_find_by_model_prefers_explicit_prefix_over_generic_codex_keyword():
    spec = find_by_model("github-copilot/gpt-5.3-codex")

    assert spec is not None
    assert spec.name == "github_copilot"


def test_litellm_provider_canonicalizes_github_copilot_hyphen_prefix():
    provider = LiteLLMProvider(default_model="github-copilot/gpt-5.3-codex")

    resolved = provider._resolve_model("github-copilot/gpt-5.3-codex")

    assert resolved == "github_copilot/gpt-5.3-codex"


def test_litellm_provider_uses_platform_env_for_embedding_gateway(monkeypatch):
    monkeypatch.setenv("API_KEY", "sk-platform")
    monkeypatch.setenv("API_BASE_URL", "https://api.lemondata.cc/v1")

    provider = LiteLLMProvider()

    gateway = provider._embedding_gateway_for_model("text-embedding-005")
    kwargs = provider._build_embedding_kwargs("text-embedding-005", gateway=gateway)

    assert gateway is not None
    assert gateway.name == "lemondata"
    assert kwargs["api_key"] == "sk-platform"
    assert kwargs["api_base"] == "https://api.lemondata.cc/v1"
    assert kwargs["model"] == "openai/text-embedding-005"


def test_litellm_provider_uses_platform_env_for_gemini_embedding_gateway(monkeypatch):
    monkeypatch.setenv("API_KEY", "sk-platform")
    monkeypatch.setenv("API_BASE_URL", "https://api.lemondata.cc/v1")

    provider = LiteLLMProvider()

    gateway = provider._embedding_gateway_for_model("gemini-embedding-001")
    kwargs = provider._build_embedding_kwargs("gemini-embedding-001", gateway=gateway)

    assert gateway is not None
    assert gateway.name == "lemondata_gemini"
    assert kwargs["api_key"] == "sk-platform"
    assert kwargs["api_base"] == "https://api.lemondata.cc"
    assert kwargs["model"] == "gemini/gemini-embedding-001"


def test_litellm_provider_uses_platform_env_for_chat_requests(monkeypatch):
    monkeypatch.setenv("API_KEY", "sk-platform")
    monkeypatch.setenv("API_BASE_URL", "https://api.lemondata.cc/v1")

    provider = LiteLLMProvider()

    async def _exercise():
        with patch.object(provider, "_chat_with_retry", return_value=LLMResponse(content="ok")) as chat_with_retry:
            await provider.chat([{"role": "user", "content": "hi"}], model="gpt-5.4")
            forwarded_kwargs = chat_with_retry.call_args.args[0]
            assert forwarded_kwargs["api_key"] == "sk-platform"
            assert forwarded_kwargs["api_base"] == "https://api.lemondata.cc/v1"
            assert forwarded_kwargs["model"] == "gpt-5.4"

    asyncio.run(_exercise())


def test_openai_codex_strip_prefix_supports_hyphen_and_underscore():
    assert _strip_model_prefix("openai-codex/gpt-5.1-codex") == "gpt-5.1-codex"
    assert _strip_model_prefix("openai_codex/gpt-5.1-codex") == "gpt-5.1-codex"


def test_make_provider_returns_lemondata_response_provider():
    from lemonclaw.cli.commands import _make_provider

    config = Config()
    config.agents.defaults.model = "gpt-5.4"
    config.providers.lemondata_response.api_key = "sk-test"
    config.providers.lemondata_response.api_base = "https://api.lemondata.cc/v1"

    provider = _make_provider(config)

    assert isinstance(provider, LemonDataResponsesProvider)


def test_make_provider_returns_litellm_provider_for_llama_consolidation_model():
    from lemonclaw.cli.commands import _make_provider

    config = Config()
    config.providers.lemondata.api_key = "sk-test"
    config.providers.lemondata.api_base = "https://api.lemondata.cc/v1"

    provider = _make_provider(config, "llama-3.3-70b-versatile")

    assert isinstance(provider, LiteLLMProvider)


def test_channels_status_lists_matrix_and_wecom():
    config = Config()
    config.channels.matrix.enabled = True
    config.channels.matrix.user_id = "@bot:matrix.org"
    config.channels.wecom.enabled = True
    config.channels.wecom.corp_id = "wx-demo-corp"

    with patch("lemonclaw.config.loader.load_config", return_value=config):
        result = runner.invoke(app, ["channels", "status"])

    assert result.exit_code == 0
    assert "Matrix" in result.stdout
    assert "@bot:matrix.org" in result.stdout
    assert "WeCom" in result.stdout
    assert "wx-demo-corp" in result.stdout


def test_runtime_version_prefers_env_override(monkeypatch):
    from lemonclaw.cli.commands import _runtime_version

    monkeypatch.setenv("LEMONCLAW_RUNTIME_VERSION", "latest")
    assert _runtime_version() == "latest"


def test_runtime_version_falls_back_to_package_version(monkeypatch):
    from lemonclaw.cli.commands import _runtime_version

    monkeypatch.delenv("LEMONCLAW_RUNTIME_VERSION", raising=False)
    assert _runtime_version() == "2026.3.28.1"


def test_llm_response_normalizes_stringified_text_blocks():
    response = LLMResponse(content='[{"type":"text","text":"hello world"}]')

    assert response.content == "hello world"
