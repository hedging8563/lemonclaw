from pathlib import Path
from types import SimpleNamespace

from lemonclaw.config.schema import Config
from lemonclaw.providers.catalog import apply_runtime_model_policy, get_runtime_default_model


def teardown_function():
    apply_runtime_model_policy(None)


def test_sync_runtime_model_policy_updates_local_files_and_defaults(monkeypatch, tmp_path: Path):
    from lemonclaw.config.sync import _sync_runtime_model_policy

    config = Config()
    config.providers.lemondata.api_key = 'sk-test'
    config.lemondata.api_base_url = 'https://api.lemondata.cc'
    config.agents.defaults.model = 'claude-sonnet-4-6'

    fake_config_path = tmp_path / 'config.json'
    fake_config_path.write_text('{}', encoding='utf-8')
    monkeypatch.setattr('lemonclaw.config.loader.get_config_path', lambda: fake_config_path)

    policy = {
        'defaults': {
            'chat': 'gpt-5.2',
            'vision': 'gemini-3.1-pro-preview',
            'fast': 'gpt-4.1-mini',
            'reasoning': 'claude-opus-4-6',
            'coding': 'claude-sonnet-4-6',
            'consolidation': 'llama-3.3-70b-versatile',
        },
        'catalog': [
            {'id': 'gpt-5.2', 'label': 'GPT-5.2', 'tier': 'flagship', 'enabled': True, 'visible': True, 'description': 'x', 'capabilities': ['chat']},
            {'id': 'gpt-4.1-mini', 'label': 'GPT-4.1 Mini', 'tier': 'economy', 'enabled': True, 'visible': True, 'description': 'y', 'capabilities': ['chat']},
        ],
        'profiles': {'standard_chat': ['gpt-5.2', 'gpt-4.1-mini']},
        'sceneProfiles': {'chat': 'standard_chat'},
        'modelProfileOverrides': {},
    }

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {'policy': policy}

    captured = {}

    def fake_get(url, *, headers, timeout):
        captured['url'] = url
        captured['headers'] = headers
        captured['timeout'] = timeout
        return FakeResponse()

    monkeypatch.setattr('lemonclaw.config.sync.httpx.get', fake_get)

    changed = _sync_runtime_model_policy(config)

    assert changed is True
    assert captured['url'] == 'https://api.lemondata.cc/v1/claw/runtime-policy'
    assert captured['headers']['Authorization'] == 'Bearer sk-test'
    assert config.agents.defaults.model == 'gpt-5.2'
    assert config.lemondata.default_model == 'gpt-5.2'
    assert get_runtime_default_model('chat') == 'gpt-5.2'
    assert (tmp_path / 'runtime-model-policy.json').exists()
    assert (tmp_path / '.managed-runtime-default-model').read_text(encoding='utf-8') == 'gpt-5.2'

def test_sync_runtime_model_policy_clears_stale_override_without_hosted_credentials(monkeypatch, tmp_path: Path):
    from lemonclaw.config.sync import _sync_runtime_model_policy

    config = Config()
    config.agents.defaults.model = 'gpt-5.2'
    config.lemondata.default_model = 'gpt-5.2'

    fake_config_path = tmp_path / 'config.json'
    fake_config_path.write_text('{}', encoding='utf-8')
    (tmp_path / 'runtime-model-policy.json').write_text('{"defaults":{"chat":"gpt-5.2"}}', encoding='utf-8')
    (tmp_path / '.managed-runtime-default-model').write_text('gpt-5.2', encoding='utf-8')

    monkeypatch.setattr('lemonclaw.config.loader.get_config_path', lambda: fake_config_path)
    apply_runtime_model_policy({
        'defaults': {'chat': 'gpt-5.2'},
        'catalog': [{'id': 'gpt-5.2', 'label': 'GPT-5.2', 'tier': 'flagship', 'enabled': True, 'visible': True, 'description': 'x'}],
        'profiles': {'standard_chat': ['gpt-5.2']},
        'sceneProfiles': {'chat': 'standard_chat'},
        'modelProfileOverrides': {},
    })

    changed = _sync_runtime_model_policy(config)

    assert changed is True
    assert get_runtime_default_model('chat') == 'claude-sonnet-4-6'
    assert config.agents.defaults.model == 'claude-sonnet-4-6'
    assert config.lemondata.default_model == 'claude-sonnet-4-6'
    assert not (tmp_path / 'runtime-model-policy.json').exists()
    assert not (tmp_path / '.managed-runtime-default-model').exists()


def test_sync_model_config_preserves_custom_api_bases(monkeypatch, tmp_path: Path):
    from lemonclaw.config.sync import _sync_model_config

    config = Config()
    config.providers.lemondata.api_key = 'sk-test'
    config.lemondata.api_base_url = 'https://staging.example.com'
    config.providers.lemondata.api_base = 'https://staging.example.com/v1'
    config.providers.lemondata_claude.api_base = 'https://staging.example.com'
    config.providers.lemondata_minimax.api_base = 'https://staging.example.com'
    config.providers.lemondata_gemini.api_base = 'https://staging.example.com'
    config.tools.coding.api_base = 'https://claude-proxy.example.com'

    fake_config_path = tmp_path / 'config.json'
    fake_config_path.write_text('{}', encoding='utf-8')
    monkeypatch.setattr('lemonclaw.config.loader.get_config_path', lambda: fake_config_path)

    _sync_model_config(config)

    assert config.providers.lemondata.api_base == 'https://staging.example.com/v1'
    assert config.providers.lemondata_claude.api_base == 'https://staging.example.com'
    assert config.providers.lemondata_minimax.api_base == 'https://staging.example.com'
    assert config.providers.lemondata_gemini.api_base == 'https://staging.example.com'
    assert config.tools.coding.api_base == 'https://claude-proxy.example.com'

