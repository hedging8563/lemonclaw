from pathlib import Path

from lemonclaw.config.schema import Config
from lemonclaw.providers.catalog import apply_runtime_model_policy, get_runtime_default_model, get_runtime_memory_policy


def teardown_function():
    apply_runtime_model_policy(None)


def test_sync_runtime_model_policy_prefers_direct_config_payload_and_updates_defaults(monkeypatch, tmp_path: Path):
    from lemonclaw.config.sync import _sync_runtime_model_policy

    config = Config()
    config.providers.lemondata.api_key = 'sk-test'
    config.lemondata.api_base_url = 'https://api.lemondata.cc'
    config.agents.defaults.model = 'gpt-5.4'

    fake_config_path = tmp_path / 'config.json'
    fake_config_path.write_text('{}', encoding='utf-8')
    monkeypatch.setattr('lemonclaw.config.loader.get_config_path', lambda: fake_config_path)

    direct_config = {
        'chat': {
            'defaultModel': 'gpt-5.2',
            'availableModels': ['gpt-5.2', 'gpt-5.4', 'claude-sonnet-4-6'],
        },
        'vision': {
            'chain': ['gemini-3.1-pro-preview', 'gpt-4.1-mini'],
        },
        'memory': {
            'indexMode': 'hybrid',
            'embeddingOrder': ['text-embedding-005', 'gemini-embedding-001'],
        },
    }

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {'config': direct_config}

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
    assert get_runtime_default_model('vision') == 'gemini-3.1-pro-preview'
    assert get_runtime_memory_policy()['embeddingOrder'] == ['text-embedding-005', 'gemini-embedding-001']
    assert (tmp_path / 'runtime-model-policy.json').exists()
    assert (tmp_path / '.managed-runtime-default-model').read_text(encoding='utf-8') == 'gpt-5.2'


def test_sync_runtime_model_policy_uses_legacy_policy_to_migrate_coding_model(monkeypatch, tmp_path: Path):
    from lemonclaw.config.sync import _sync_runtime_model_policy

    config = Config()
    config.providers.lemondata.api_key = 'sk-test'
    config.lemondata.api_base_url = 'https://api.lemondata.cc'
    config.tools.coding.model = 'claude-sonnet-4-6'

    fake_config_path = tmp_path / 'config.json'
    fake_config_path.write_text('{}', encoding='utf-8')
    monkeypatch.setattr('lemonclaw.config.loader.get_config_path', lambda: fake_config_path)

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                'config': {
                    'chat': {'defaultModel': 'gpt-5.4', 'availableModels': ['gpt-5.4']},
                    'vision': {'chain': ['gpt-4.1-mini']},
                    'memory': {'indexMode': 'auto', 'embeddingOrder': ['text-embedding-005']},
                },
                'policy': {
                    'defaults': {'coding': 'gpt-5.3-codex'},
                },
            }

    monkeypatch.setattr('lemonclaw.config.sync.httpx.get', lambda *args, **kwargs: FakeResponse())

    changed = _sync_runtime_model_policy(config)

    assert changed is True
    assert config.tools.coding.model == 'gpt-5.3-codex'


def test_sync_runtime_model_policy_repairs_managed_bad_coding_model(monkeypatch, tmp_path: Path):
    from lemonclaw.config.sync import _sync_runtime_model_policy

    config = Config()
    config.providers.lemondata.api_key = 'sk-test'
    config.lemondata.api_base_url = 'https://api.lemondata.cc'
    config.tools.coding.model = 'gpt-5.4'

    fake_config_path = tmp_path / 'config.json'
    fake_config_path.write_text('{}', encoding='utf-8')
    monkeypatch.setattr('lemonclaw.config.loader.get_config_path', lambda: fake_config_path)

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                'config': {
                    'chat': {'defaultModel': 'gpt-5.4', 'availableModels': ['gpt-5.4']},
                    'vision': {'chain': ['gpt-4.1-mini']},
                    'memory': {'indexMode': 'auto', 'embeddingOrder': ['text-embedding-005']},
                },
                'policy': {
                    'defaults': {'coding': 'claude-opus-4-6'},
                },
            }

    monkeypatch.setattr('lemonclaw.config.sync.httpx.get', lambda *args, **kwargs: FakeResponse())

    changed = _sync_runtime_model_policy(config)

    assert changed is True
    assert config.tools.coding.model == 'claude-opus-4-6'


def test_sync_runtime_model_policy_clears_stale_override_without_hosted_credentials(monkeypatch, tmp_path: Path):
    from lemonclaw.config.sync import _sync_runtime_model_policy

    config = Config()
    config.agents.defaults.model = 'gpt-5.2'
    config.lemondata.default_model = 'gpt-5.2'

    fake_config_path = tmp_path / 'config.json'
    fake_config_path.write_text('{}', encoding='utf-8')
    (tmp_path / 'runtime-model-policy.json').write_text('{"chat":{"defaultModel":"gpt-5.2","availableModels":["gpt-5.2"]}}', encoding='utf-8')
    (tmp_path / '.managed-runtime-default-model').write_text('gpt-5.2', encoding='utf-8')

    monkeypatch.setattr('lemonclaw.config.loader.get_config_path', lambda: fake_config_path)
    apply_runtime_model_policy({
        'chat': {'defaultModel': 'gpt-5.2', 'availableModels': ['gpt-5.2']},
        'vision': {'chain': ['gpt-4.1-mini']},
        'memory': {'indexMode': 'auto', 'embeddingOrder': ['text-embedding-005']},
    })

    changed = _sync_runtime_model_policy(config)

    assert changed is True
    assert get_runtime_default_model('chat') == 'gpt-5.4'
    assert config.agents.defaults.model == 'gpt-5.4'
    assert config.lemondata.default_model == 'gpt-5.4'
    assert not (tmp_path / 'runtime-model-policy.json').exists()
    assert not (tmp_path / '.managed-runtime-default-model').exists()


def test_sync_model_config_preserves_custom_api_bases(monkeypatch, tmp_path: Path):
    from lemonclaw.config.sync import _sync_model_config

    config = Config()
    config.providers.lemondata.api_key = 'sk-test'
    config.lemondata.api_base_url = 'https://staging.example.com'
    config.providers.lemondata.api_base = 'https://staging.example.com/v1'
    config.providers.lemondata_response.api_base = 'https://staging.example.com/v1'
    config.providers.lemondata_claude.api_base = 'https://staging.example.com'
    config.providers.lemondata_minimax.api_base = 'https://staging.example.com'
    config.providers.lemondata_gemini.api_base = 'https://staging.example.com'
    config.tools.coding.api_base = 'https://claude-proxy.example.com'

    fake_config_path = tmp_path / 'config.json'
    fake_config_path.write_text('{}', encoding='utf-8')
    monkeypatch.setattr('lemonclaw.config.loader.get_config_path', lambda: fake_config_path)

    _sync_model_config(config)

    assert config.providers.lemondata.api_base == 'https://staging.example.com/v1'
    assert config.providers.lemondata_response.api_base == 'https://staging.example.com/v1'
    assert config.providers.lemondata_claude.api_base == 'https://staging.example.com'
    assert config.providers.lemondata_minimax.api_base == 'https://staging.example.com'
    assert config.providers.lemondata_gemini.api_base == 'https://staging.example.com'
    assert config.tools.coding.api_base == 'https://claude-proxy.example.com'


def test_sync_runtime_model_policy_clears_managed_default_when_api_returns_none(monkeypatch, tmp_path: Path):
    from lemonclaw.config.sync import _sync_runtime_model_policy

    config = Config()
    config.providers.lemondata.api_key = 'sk-test'
    config.lemondata.api_base_url = 'https://api.lemondata.cc'
    config.agents.defaults.model = 'gpt-5.2'
    config.lemondata.default_model = 'gpt-5.2'

    fake_config_path = tmp_path / 'config.json'
    fake_config_path.write_text('{}', encoding='utf-8')
    (tmp_path / 'runtime-model-policy.json').write_text('{"chat":{"defaultModel":"gpt-5.2","availableModels":["gpt-5.2"]}}', encoding='utf-8')
    (tmp_path / '.managed-runtime-default-model').write_text('gpt-5.2', encoding='utf-8')
    monkeypatch.setattr('lemonclaw.config.loader.get_config_path', lambda: fake_config_path)

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {'config': None, 'policy': None}

    monkeypatch.setattr('lemonclaw.config.sync.httpx.get', lambda *args, **kwargs: FakeResponse())

    changed = _sync_runtime_model_policy(config)

    assert changed is True
    assert get_runtime_default_model('chat') == 'gpt-5.4'
    assert config.agents.defaults.model == 'gpt-5.4'
    assert config.lemondata.default_model == 'gpt-5.4'
    assert not (tmp_path / 'runtime-model-policy.json').exists()
    assert not (tmp_path / '.managed-runtime-default-model').exists()
