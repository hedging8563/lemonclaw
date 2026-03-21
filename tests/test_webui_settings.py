from starlette.testclient import TestClient

from lemonclaw.channels.whatsapp_bridge_runtime import WhatsAppBridgeError
from lemonclaw.config.loader import load_config, save_config
from lemonclaw.config.schema import Config, GovernanceSandboxProfileConfig, GovernanceSecretProfileConfig
from lemonclaw.gateway.server import create_app
from lemonclaw.gateway.webui.settings import _RESTART_FIELDS
from lemonclaw.governance import GovernanceRuntime
from lemonclaw.session.manager import SessionManager


def test_whatsapp_pairing_settings_routes(monkeypatch, tmp_path):
    config_path = tmp_path / 'config.json'
    cfg = Config()
    cfg.channels.whatsapp.enabled = True
    save_config(cfg, config_path)

    calls = []

    def _fake_state(config, *, start_if_needed=False, wait_timeout=15.0):
        calls.append((start_if_needed, wait_timeout, config.enabled))
        return {'status': 'qr' if start_if_needed else 'starting', 'qr': 'raw-qr', 'running': True, 'account': {'id': '123@wa', 'phone': '123'}}

    monkeypatch.setattr('lemonclaw.gateway.webui.settings.get_whatsapp_pairing_state', _fake_state)

    app = create_app(config_path=config_path, auth_token=None)
    client = TestClient(app)

    resp = client.get('/api/settings/channels/whatsapp/pairing')
    assert resp.status_code == 200
    assert resp.json()['status'] == 'starting'

    resp = client.post('/api/settings/channels/whatsapp/pairing')
    assert resp.status_code == 200
    assert resp.json()['status'] == 'qr'
    assert calls[0][0] is False
    assert calls[1][0] is True


def test_whatsapp_pairing_settings_route_surfaces_bridge_error(monkeypatch, tmp_path):
    config_path = tmp_path / 'config.json'
    cfg = Config()
    cfg.channels.whatsapp.enabled = True
    save_config(cfg, config_path)

    def _raise(config, *, start_if_needed=False, wait_timeout=15.0):
        raise WhatsAppBridgeError('npm not found')

    monkeypatch.setattr('lemonclaw.gateway.webui.settings.get_whatsapp_pairing_state', _raise)

    app = create_app(config_path=config_path, auth_token=None)
    client = TestClient(app)
    resp = client.post('/api/settings/channels/whatsapp/pairing')
    assert resp.status_code == 400
    assert resp.json()['error'] == 'npm not found'


def test_whatsapp_disconnect_and_repair_routes(monkeypatch, tmp_path):
    from lemonclaw.config.loader import save_config
    from lemonclaw.config.schema import Config

    config_path = tmp_path / 'config.json'
    cfg = Config()
    cfg.channels.whatsapp.enabled = True
    save_config(cfg, config_path)

    monkeypatch.setattr('lemonclaw.gateway.webui.settings.disconnect_whatsapp', lambda: {'status': 'disconnected', 'qr': None, 'account': None, 'running': False})
    monkeypatch.setattr('lemonclaw.gateway.webui.settings.restart_whatsapp_pairing', lambda config, wait_timeout=20.0: {'status': 'qr', 'qr': 'new-qr', 'account': None, 'running': True})

    app = create_app(config_path=config_path, auth_token=None)
    client = TestClient(app)

    resp = client.post('/api/settings/channels/whatsapp/disconnect')
    assert resp.status_code == 200
    assert resp.json()['status'] == 'disconnected'

    resp = client.post('/api/settings/channels/whatsapp/repair')
    assert resp.status_code == 200
    assert resp.json()['status'] == 'qr'


def test_whatsapp_disconnect_surfaces_stop_failure(monkeypatch, tmp_path):
    config_path = tmp_path / 'config.json'
    cfg = Config()
    cfg.channels.whatsapp.enabled = True
    save_config(cfg, config_path)

    monkeypatch.setattr('lemonclaw.gateway.webui.settings.disconnect_whatsapp', lambda: (_ for _ in ()).throw(WhatsAppBridgeError('Failed to stop running WhatsApp bridge process.')))

    app = create_app(config_path=config_path, auth_token=None)
    client = TestClient(app)
    resp = client.post('/api/settings/channels/whatsapp/disconnect')
    assert resp.status_code == 400
    assert 'Failed to stop running WhatsApp bridge process.' in resp.json()['error']



def test_session_ws_streams_incremental_messages(tmp_path):
    from lemonclaw.gateway.server import create_app

    mgr = SessionManager(tmp_path)
    session = mgr.get_or_create('telegram:123')
    session.messages.append({'role': 'user', 'content': 'first'})
    mgr.save(session)

    from types import SimpleNamespace
    app = create_app(auth_token=None, session_manager=mgr, agent_loop=SimpleNamespace(workspace=tmp_path), webui_enabled=True)
    with TestClient(app).websocket_connect('/ws/session?session_key=telegram:123&known_count=1') as ws:
        session = mgr.get_or_create('telegram:123')
        session.messages.append({'role': 'assistant', 'content': 'second'})
        mgr.save(session)
        payload = ws.receive_json()
        assert payload['type'] == 'messages'
        assert payload['session_key'] == 'telegram:123'
        assert len(payload['messages']) == 1
        assert payload['messages'][0]['content'] == 'second'



def test_feishu_settings_returns_unmasked_subscription_tokens(tmp_path):
    config_path = tmp_path / 'config.json'
    cfg = Config()
    cfg.channels.feishu.enabled = True
    cfg.channels.feishu.encrypt_key = '39de1234567890abcdef79c7'
    cfg.channels.feishu.verification_token = '95aa1234567890abcdefefdb'
    save_config(cfg, config_path)

    app = create_app(config_path=config_path, auth_token=None)
    client = TestClient(app)

    resp = client.get('/api/settings')
    assert resp.status_code == 200
    settings = resp.json()['settings']
    assert settings['channels']['feishu']['encrypt_key'] == '39de1234567890abcdef79c7'
    assert settings['channels']['feishu']['verification_token'] == '95aa1234567890abcdefefdb'



def test_install_skill_rejects_non_allowlisted_hosts(tmp_path):
    from types import SimpleNamespace

    config_path = tmp_path / 'config.json'
    save_config(Config(), config_path)
    fake_agent = SimpleNamespace(context=SimpleNamespace(skills=SimpleNamespace(workspace_skills=tmp_path / 'skills')))

    app = create_app(config_path=config_path, auth_token=None, agent_loop=fake_agent)
    client = TestClient(app)
    resp = client.post('/api/settings/skills', json={'url': 'https://127.0.0.1:5000/owner/repo.git'})
    assert resp.status_code == 400
    assert 'Only ' in resp.json()['error']


def test_feishu_tokens_are_initialized_before_first_get(tmp_path):
    config_path = tmp_path / 'config.json'
    save_config(Config(), config_path)

    app = create_app(config_path=config_path, auth_token=None)

    from lemonclaw.config.loader import load_config
    cfg = load_config(config_path)
    assert cfg.channels.feishu.encrypt_key
    assert cfg.channels.feishu.verification_token

    client = TestClient(app)
    resp = client.get('/api/settings')
    assert resp.status_code == 200


def test_settings_exposes_managed_lemondata_provider_bases(monkeypatch, tmp_path):
    config_path = tmp_path / 'config.json'
    save_config(Config(), config_path)

    monkeypatch.setenv('API_KEY', 'sk-platform')
    monkeypatch.setenv('API_BASE_URL', 'https://staging.example.com')

    app = create_app(config_path=config_path, auth_token=None)
    client = TestClient(app)
    resp = client.get('/api/settings')

    assert resp.status_code == 200
    providers = resp.json()['settings']['providers']
    assert providers['lemondata']['api_key'] == '(auto-configured by platform)'
    assert providers['lemondata']['api_base'] == 'https://staging.example.com/v1'
    assert providers['lemondata_response']['api_base'] == 'https://staging.example.com/v1'
    assert providers['lemondata_claude']['api_base'] == 'https://staging.example.com'
    assert providers['lemondata_minimax']['api_base'] == 'https://staging.example.com'
    assert providers['lemondata_gemini']['api_base'] == 'https://staging.example.com'


def test_settings_exposes_dicloak_runtime_without_credentials(tmp_path):
    from types import SimpleNamespace

    class FakeBrowserTool:
        def get_dicloak_runtime_status(self):
            return {
                'enabled': True,
                'lease_count': 1,
                'leases': [{'session_name': 'lc-webui-abc', 'profile_id': 'profile-1', 'debug_port': 45010}],
                'last_open': {'ok': True, 'profile_id': 'profile-1', 'debug_port': 45010},
                'last_close': {'ok': False, 'profile_id': 'profile-1', 'error': 'close failed'},
            }

    class FakeTools:
        def get(self, name):
            return FakeBrowserTool() if name == 'browser' else None

    config_path = tmp_path / 'config.json'
    save_config(Config(), config_path)

    fake_agent = SimpleNamespace(tools=FakeTools(), model='gpt-5.4')
    app = create_app(config_path=config_path, auth_token=None, agent_loop=fake_agent)
    client = TestClient(app)
    resp = client.get('/api/settings')

    assert resp.status_code == 200
    runtime = resp.json()['dicloak_runtime']
    assert runtime['enabled'] is True
    assert runtime['lease_count'] == 1
    assert runtime['leases'][0]['profile_id'] == 'profile-1'
    assert runtime['last_open']['ok'] is True
    assert runtime['last_close']['ok'] is False


def test_save_config_strips_env_injected_lemondata_response_key(monkeypatch, tmp_path):
    config_path = tmp_path / 'config.json'
    save_config(Config(), config_path)

    monkeypatch.setenv('API_KEY', 'sk-platform')
    monkeypatch.setenv('API_BASE_URL', 'https://staging.example.com')

    cfg = load_config(config_path)
    assert cfg.providers.lemondata_response.api_key == 'sk-platform'

    save_config(cfg, config_path)
    saved = config_path.read_text(encoding='utf-8')

    assert 'lemondataResponse' in saved
    assert '"apiKey": ""' in saved


def test_settings_exposes_effective_telegram_pairing_runtime_state(monkeypatch, tmp_path):
    import json

    monkeypatch.setenv('HOME', str(tmp_path))
    config_path = tmp_path / 'config.json'
    cfg = Config()
    cfg.channels.telegram.enabled = True
    save_config(cfg, config_path)

    pairing_dir = tmp_path / '.lemonclaw' / 'pairing'
    pairing_dir.mkdir(parents=True, exist_ok=True)
    (pairing_dir / 'telegram.json').write_text(json.dumps({
        'owner': '5693302436|kksharp_cam',
        'owner_notify_target': '5693302436',
        'approved': ['5693302436|kksharp_cam'],
        'pending': {},
    }), encoding='utf-8')

    app = create_app(config_path=config_path, auth_token=None)
    client = TestClient(app)
    resp = client.get('/api/settings')
    assert resp.status_code == 200
    runtime = resp.json()['channel_runtime']['telegram']
    assert runtime['effective_dm_policy'] == 'pairing'
    assert runtime['source'] == 'auto_pairing'
    assert runtime['approved_count'] == 1


def test_settings_exposes_qq_group_runtime_state(tmp_path):
    config_path = tmp_path / 'config.json'
    cfg = Config()
    cfg.channels.qq.enabled = True
    cfg.channels.qq.group_policy = 'allowlist'
    cfg.channels.qq.group_require_mention = True
    cfg.channels.qq.group_allow_from = ['GROUP1', 'GROUP2']
    save_config(cfg, config_path)

    app = create_app(config_path=config_path, auth_token=None)
    client = TestClient(app)
    resp = client.get('/api/settings')

    assert resp.status_code == 200
    group_runtime = resp.json()['group_runtime']['qq']
    assert group_runtime['effective_group_policy'] == 'allowlist'
    assert group_runtime['effective_group_require_mention'] is True
    assert group_runtime['group_allow_from_count'] == 2


def test_settings_exposes_channel_status_snapshot(tmp_path):
    from types import SimpleNamespace

    config_path = tmp_path / 'config.json'
    cfg = Config()
    cfg.channels.telegram.enabled = True
    save_config(cfg, config_path)

    channel_manager = SimpleNamespace(
        get_channel_status=lambda: {
            'telegram': {
                'configured_enabled': True,
                'registered': True,
                'running': True,
                'available': True,
                'error': '',
            },
            'wecom': {
                'configured_enabled': True,
                'registered': False,
                'running': False,
                'available': False,
                'error': 'missing dependency',
            },
        }
    )

    app = create_app(config_path=config_path, auth_token=None, channel_manager=channel_manager)
    client = TestClient(app)
    resp = client.get('/api/settings')
    assert resp.status_code == 200
    data = resp.json()
    assert data['channel_status']['telegram']['running'] is True
    assert data['channel_status']['wecom']['available'] is False
    assert data['channel_status']['wecom']['error'] == 'missing dependency'


def test_patch_settings_accepts_operator_tool_paths(tmp_path):
    config_path = tmp_path / 'config.json'
    save_config(Config(), config_path)

    app = create_app(config_path=config_path, auth_token=None)
    client = TestClient(app)

    resp = client.patch('/api/settings', json={
        'tools.http': {
            'enabled': True,
            'timeout': 25,
            'allow_domains': ['api.example.com'],
            'auth_profiles': {'svc': {'Authorization': 'Bearer token'}},
        },
        'tools.k8s.default_namespace': 'claw',
        'tools.k8s.allowed_namespaces': ['claw'],
        'tools.db': {
            'enabled': True,
            'timeout': 10,
            'sqlite_profiles': {'local': '/tmp/test.db'},
            'postgres_profiles': {
                'analytics_ro': {
                    'host': 'db.example.internal',
                    'port': 5432,
                    'dbname': 'analytics',
                    'user': 'reader',
                    'password': 'secret',
                    'sslmode': 'require',
                }
            },
        },
        'tools.notify.allow_webhook_domains': ['hooks.example.com'],
    })

    assert resp.status_code == 200


def test_settings_masks_governance_secret_profile_values(tmp_path):
    config_path = tmp_path / 'config.json'
    cfg = Config()
    cfg.governance.secret_profiles = {
        'ops_http': GovernanceSecretProfileConfig(
            kind='headers',
            values={'Authorization': 'Bearer top-secret', 'X-API-Key': 'abc123'},
            description='ops profile',
        )
    }
    save_config(cfg, config_path)

    app = create_app(config_path=config_path, auth_token=None)
    client = TestClient(app)
    resp = client.get('/api/settings')

    assert resp.status_code == 200
    profile = resp.json()['settings']['governance']['secret_profiles']['ops_http']
    assert profile['values']['Authorization'].startswith('Bear')
    assert 'top-secret' not in profile['values']['Authorization']
    assert profile['values']['X-API-Key'] == '****'


def test_governance_routes_expose_runtime_views(tmp_path):
    config_path = tmp_path / 'config.json'
    cfg = Config()
    cfg.governance.kill_switch_file = str(tmp_path / 'governance.json')
    cfg.governance.audit_log_path = str(tmp_path / 'audit.jsonl')
    cfg.governance.secret_profiles = {
        'ops_http': GovernanceSecretProfileConfig(
            kind='headers',
            values={'Authorization': 'Bearer top-secret'},
        )
    }
    cfg.governance.sandbox_profiles = {
        'runtime_default': GovernanceSandboxProfileConfig(
            allowed_domains=['api.example.com'],
            allowed_paths=['/tmp'],
            blocked_commands=['rm -rf'],
        )
    }
    cfg.governance.capability_overrides = {
        'http.write': {
            'secret_profile': 'ops_http',
            'sandbox_profile': 'runtime_default',
        }
    }
    save_config(cfg, config_path)

    governance = GovernanceRuntime(workspace=tmp_path, config=cfg.governance, agent_id='test3')
    agent_loop = type('Loop', (), {'governance': governance, 'model': 'gpt-5.4'})()
    app = create_app(config_path=config_path, auth_token=None, agent_loop=agent_loop)
    client = TestClient(app)

    resp = client.get('/api/governance')
    assert resp.status_code == 200
    data = resp.json()
    assert data['overview']['secret_profiles']['count'] == 1
    assert data['overview']['sandbox_profiles']['count'] == 1
    assert data['kill_switch']['global'] is False

    caps = client.get('/api/governance/capabilities')
    assert caps.status_code == 200
    http_write = next(item for item in caps.json()['capabilities'] if item['capability_id'] == 'http.write')
    assert http_write['secret_profile_status']['state'] == 'configured'
    assert http_write['sandbox_profile_status']['state'] == 'configured'


def test_governance_kill_switch_patch_updates_state(tmp_path):
    config_path = tmp_path / 'config.json'
    cfg = Config()
    cfg.governance.kill_switch_file = str(tmp_path / 'governance.json')
    cfg.governance.audit_log_path = str(tmp_path / 'audit.jsonl')
    save_config(cfg, config_path)

    governance = GovernanceRuntime(workspace=tmp_path, config=cfg.governance, agent_id='test3')
    agent_loop = type('Loop', (), {'governance': governance, 'model': 'gpt-5.4'})()
    app = create_app(config_path=config_path, auth_token=None, agent_loop=agent_loop)
    client = TestClient(app)

    resp = client.post('/api/governance/kill-switch', json={'global': True, 'capabilities': {'exec.system': True}})
    assert resp.status_code == 200
    assert resp.json()['state']['global'] is True
    assert resp.json()['state']['capabilities']['exec.system'] is True

    get_resp = client.get('/api/governance/kill-switch')
    assert get_resp.status_code == 200
    assert get_resp.json()['kill_switch']['global'] is True


def test_apply_settings_marks_operator_tools_as_restart_required(monkeypatch, tmp_path):
    config_path = tmp_path / 'config.json'
    save_config(Config(), config_path)

    kill_calls = []
    monkeypatch.setattr('os.kill', lambda pid, sig: kill_calls.append((pid, sig)))

    app = create_app(config_path=config_path, auth_token=None)
    client = TestClient(app)

    resp = client.post('/api/settings/apply', json={
        'changed_paths': ['tools.http', 'tools.db', 'tools.k8s', 'tools.notify'],
    })

    assert resp.status_code == 200
    body = resp.json()
    assert body['reloaded'] is True
    assert body['restart_required'] is True
    assert body['restart_fields'] == ['tools.http', 'tools.db', 'tools.k8s', 'tools.notify']


def test_restart_regex_includes_operator_tools():
    assert _RESTART_FIELDS.match('tools.http')
    assert _RESTART_FIELDS.match('tools.notify')
    assert _RESTART_FIELDS.match('tools.db')
    assert _RESTART_FIELDS.match('tools.k8s')


def test_settings_masks_http_auth_profiles_and_preserves_on_patch(tmp_path):
    config_path = tmp_path / 'config.json'
    cfg = Config()
    cfg.tools.http.enabled = True
    cfg.tools.http.auth_profiles = {
        'svc': {
            'Authorization': 'Bearer super-secret-token',
            'X-API-Key': 'abc123456789',
        }
    }
    save_config(cfg, config_path)

    app = create_app(config_path=config_path, auth_token=None)
    client = TestClient(app)

    resp = client.get('/api/settings')
    assert resp.status_code == 200
    http_settings = resp.json()['settings']['tools']['http']
    assert http_settings['auth_profiles']['svc']['Authorization'] == 'Bear****oken'
    assert http_settings['auth_profiles']['svc']['X-API-Key'] == 'abc1****6789'

    resp = client.patch('/api/settings', json={
        'tools.http': {
            'enabled': True,
            'timeout': 45,
            'allow_domains': ['api.example.com'],
            'auth_profiles': http_settings['auth_profiles'],
        }
    })
    assert resp.status_code == 200

    from lemonclaw.config.loader import load_config
    updated = load_config(config_path)
    assert updated.tools.http.timeout == 45
    assert updated.tools.http.auth_profiles['svc']['Authorization'] == 'Bearer super-secret-token'
    assert updated.tools.http.auth_profiles['svc']['X-API-Key'] == 'abc123456789'
