import pytest
from starlette.testclient import TestClient

from lemonclaw.bus.queue import MessageBus
from lemonclaw.channels.whatsapp_bridge_runtime import WhatsAppBridgeError
from lemonclaw.config.loader import load_config, save_config
from lemonclaw.config.schema import Config, GitAuthProfileConfig, GovernanceSandboxProfileConfig, GovernanceSecretProfileConfig
from lemonclaw.gateway.runtime_notifications import broadcast_restart_notice, maybe_broadcast_startup_restart_notice
from lemonclaw.gateway.server import create_app
from lemonclaw.gateway.runtime_state import load_runtime_state, mark_runtime_healthy
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


def test_weixin_pairing_get_is_read_only_and_repair_registers_runtime_channel(monkeypatch, tmp_path):
    config_path = tmp_path / 'config.json'
    cfg = Config()
    cfg.channels.weixin.enabled = True
    save_config(cfg, config_path)

    class _FakeChannelManager:
        def __init__(self) -> None:
            self.bus = MessageBus()
            self.trigger_runtime = None
            self._channels = {}
            self.ensure_calls: list[str] = []

        def get_channel(self, name: str):
            return self._channels.get(name)

        async def ensure_channel(self, name: str, channel):
            self.ensure_calls.append(name)
            self._channels[name] = channel

    def _fake_state(config, *, start_if_needed=False, wait_timeout=10.0, force=False, account_id=None):
        return {
            'status': 'connected',
            'accounts': [{'accountId': 'wx-1'}],
            'account': {'accountId': 'wx-1'},
            'running': False,
        }

    monkeypatch.setattr('lemonclaw.gateway.weixin_pairing.get_weixin_pairing_state', _fake_state)

    channel_manager = _FakeChannelManager()
    app = create_app(config_path=config_path, auth_token=None, channel_manager=channel_manager)
    client = TestClient(app)

    resp = client.get('/api/weixin/pairing')
    assert resp.status_code == 200
    assert resp.json()['status'] == 'connected'
    assert channel_manager.ensure_calls == []

    resp = client.post('/api/weixin/repair')
    assert resp.status_code == 200
    assert resp.json()['status'] == 'connected'
    assert channel_manager.ensure_calls == ['weixin']



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


def test_session_ws_rejects_system_sessions(tmp_path):
    from lemonclaw.gateway.server import create_app

    mgr = SessionManager(tmp_path)

    from types import SimpleNamespace
    app = create_app(auth_token=None, session_manager=mgr, agent_loop=SimpleNamespace(workspace=tmp_path), webui_enabled=True)
    with TestClient(app).websocket_connect('/ws/session?session_key=system:heartbeat&known_count=0') as ws:
        message = ws.receive()
        assert message["type"] == "websocket.close"
        assert message["code"] == 4403
        assert message["reason"] == "access denied"



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


def test_settings_exposes_runtime_inventory(monkeypatch, tmp_path):
    config_path = tmp_path / 'config.json'
    save_config(Config(), config_path)

    monkeypatch.setattr(
        'lemonclaw.gateway.webui.settings._read_mount_info_text',
        lambda: "\n".join([
            "overlay /home/lemonclaw overlay rw,relatime 0 0",
            "overlay /tmp overlay rw,relatime 0 0",
            "overlay /var overlay rw,relatime 0 0",
            "overlay /usr overlay rw,relatime 0 0",
            "overlay /opt overlay rw,relatime 0 0",
        ]),
    )

    binaries = {
        'agent-browser': '/usr/local/bin/agent-browser',
        'claude': '/usr/local/bin/claude',
        'ssh': '/usr/bin/ssh',
        'rsync': '/usr/bin/rsync',
        'kubectl': '/usr/local/bin/kubectl',
        'rg': '/usr/bin/rg',
        'jq': '/usr/bin/jq',
    }
    monkeypatch.setattr('shutil.which', lambda cmd: binaries.get(cmd))

    app = create_app(config_path=config_path, auth_token=None)
    client = TestClient(app)
    resp = client.get('/api/settings')

    assert resp.status_code == 200
    payload = resp.json()
    inventory = payload['runtime_inventory']
    assert [item['path'] for item in inventory['persistent_prefixes']] == [
        '/home/lemonclaw',
        '/tmp',
        '/var',
        '/usr',
        '/opt',
    ]
    assert all(item['mounted'] is True for item in inventory['persistent_prefixes'])
    assert inventory['binary_inventory']['ssh']['binary'] == '/usr/bin/ssh'
    assert inventory['binary_inventory']['kubectl']['binary'] == '/usr/local/bin/kubectl'
    assert payload['tool_status']['browser']['binary'] == '/usr/local/bin/agent-browser'
    assert payload['tool_status']['coding']['binary'] == '/usr/local/bin/claude'
    assert payload['restart_status']['status'] == 'healthy'


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


def test_load_config_preserves_explicit_default_model_when_env_default_model_is_set(monkeypatch, tmp_path):
    config_path = tmp_path / 'config.json'
    cfg = Config()
    cfg.agents.defaults.model = 'gpt-5.4'
    save_config(cfg, config_path)

    monkeypatch.setenv('DEFAULT_MODEL', 'claude-sonnet-4-6')

    loaded = load_config(config_path)

    assert loaded.agents.defaults.model == 'gpt-5.4'


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


def test_settings_exposes_effective_weixin_pairing_runtime_state(monkeypatch, tmp_path):
    import json

    monkeypatch.setenv('HOME', str(tmp_path))
    config_path = tmp_path / 'config.json'
    cfg = Config()
    cfg.channels.weixin.enabled = True
    save_config(cfg, config_path)

    pairing_dir = tmp_path / '.lemonclaw' / 'pairing'
    pairing_dir.mkdir(parents=True, exist_ok=True)
    (pairing_dir / 'weixin.json').write_text(json.dumps({
        'owner': 'wx-owner',
        'owner_notify_target': 'bot-1|wx-owner',
        'approved': ['wx-owner'],
        'pending': {},
    }), encoding='utf-8')

    app = create_app(config_path=config_path, auth_token=None)
    client = TestClient(app)
    resp = client.get('/api/settings')
    assert resp.status_code == 200
    runtime = resp.json()['channel_runtime']['weixin']
    assert runtime['effective_dm_policy'] == 'pairing'
    assert runtime['source'] == 'auto_pairing'
    assert runtime['approved_count'] == 1


def test_pairing_state_route_exposes_raw_owner_and_pending(monkeypatch, tmp_path):
    import json

    monkeypatch.setenv('HOME', str(tmp_path))
    config_path = tmp_path / 'config.json'
    cfg = Config()
    cfg.channels.telegram.enabled = True
    cfg.channels.auto_pairing = True
    save_config(cfg, config_path)

    pairing_dir = tmp_path / '.lemonclaw' / 'pairing'
    pairing_dir.mkdir(parents=True, exist_ok=True)
    (pairing_dir / 'telegram.json').write_text(json.dumps({
        'owner': 'owner-1|phone',
        'owner_notify_target': 'owner-dm',
        'approved': ['owner-1|phone'],
        'pending': {'user-2': {'display_name': 'User 2', 'notify_target': 'dm-2'}},
    }), encoding='utf-8')

    app = create_app(config_path=config_path, auth_token=None)
    client = TestClient(app)

    resp = client.get('/api/settings/channels/telegram/pairing-state')
    assert resp.status_code == 200
    body = resp.json()
    assert body['channel'] == 'telegram'
    assert body['pairing']['owner'] == 'owner-1|phone'
    assert body['pairing']['owner_notify_target'] == 'owner-dm'
    assert body['pairing']['pending']['user-2']['notify_target'] == 'dm-2'


def test_pairing_break_glass_can_replace_owner(monkeypatch, tmp_path):
    import json

    monkeypatch.setenv('HOME', str(tmp_path))
    config_path = tmp_path / 'config.json'
    cfg = Config()
    cfg.channels.telegram.enabled = True
    cfg.channels.auto_pairing = True
    save_config(cfg, config_path)

    pairing_dir = tmp_path / '.lemonclaw' / 'pairing'
    pairing_dir.mkdir(parents=True, exist_ok=True)
    (pairing_dir / 'telegram.json').write_text(json.dumps({
        'owner': 'owner-1|phone',
        'owner_notify_target': 'owner-dm',
        'approved': ['owner-1|phone'],
        'pending': {'user-2': {'display_name': 'User 2', 'notify_target': 'dm-2'}},
    }), encoding='utf-8')

    app = create_app(config_path=config_path, auth_token=None)
    client = TestClient(app)

    resp = client.post('/api/settings/channels/telegram/pairing-break-glass', json={
        'owner': 'new-owner|laptop',
        'notify_target': 'new-dm',
        'clear_pending': True,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body['break_glass']['owner_set'] == 'new-owner|laptop'
    assert body['pairing']['owner'] == 'new-owner|laptop'
    assert body['pairing']['owner_notify_target'] == 'new-dm'
    assert body['pairing']['pending_count'] == 0
    assert 'new-owner|laptop' in body['pairing']['approved']


def test_pairing_recovery_code_route_issues_one_time_code(monkeypatch, tmp_path):
    import json

    monkeypatch.setenv('HOME', str(tmp_path))
    config_path = tmp_path / 'config.json'
    cfg = Config()
    cfg.channels.telegram.enabled = True
    cfg.channels.auto_pairing = True
    save_config(cfg, config_path)

    pairing_dir = tmp_path / '.lemonclaw' / 'pairing'
    pairing_dir.mkdir(parents=True, exist_ok=True)
    (pairing_dir / 'telegram.json').write_text(json.dumps({
        'owner': 'owner-1|phone',
        'owner_notify_target': 'owner-dm',
        'approved': ['owner-1|phone'],
        'pending': {},
    }), encoding='utf-8')

    app = create_app(config_path=config_path, auth_token=None)
    client = TestClient(app)

    resp = client.post('/api/settings/channels/telegram/pairing-recovery-code', json={'ttl_s': 120})
    assert resp.status_code == 200
    body = resp.json()
    assert body['break_glass']['active'] is True
    assert body['break_glass']['code'].startswith('lc_recovery_')
    assert body['pairing']['break_glass']['active'] is True


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
        'tools.git': {
            'timeout': 30,
            'max_output': 60000,
            'auth_profiles': {'origin': {'username': 'x-access-token', 'password': 'secret'}},
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

    class FakeAgentLoop:
        def __init__(self) -> None:
            self.refresh_calls = []
            self.defaults_calls = []

        async def refresh_runtime_config(self, config, *, changed_paths):
            self.refresh_calls.append(list(changed_paths))
            return {
                'http': {'status': 'reloaded', 'enabled': True},
                'git': {'status': 'reloaded', 'enabled': True},
                'db': {'status': 'disabled', 'enabled': False},
            }

        def update_defaults(self, **kwargs):
            self.defaults_calls.append(kwargs)

    class FakeChannelManager:
        def __init__(self) -> None:
            self.refresh_calls = []

        async def refresh_channels_from_config(self, config, *, changed_paths, source='settings_apply'):
            self.refresh_calls.append((list(changed_paths), source))
            return {}

    kill_calls = []
    monkeypatch.setattr('os.kill', lambda pid, sig: kill_calls.append((pid, sig)))
    fake_loop = FakeAgentLoop()
    fake_channels = FakeChannelManager()

    app = create_app(config_path=config_path, auth_token=None, agent_loop=fake_loop, channel_manager=fake_channels)
    client = TestClient(app)

    resp = client.post('/api/settings/apply', json={
        'changed_paths': ['tools.http', 'tools.git', 'tools.db', 'tools.k8s', 'tools.notify'],
    })

    assert resp.status_code == 200
    body = resp.json()
    assert body['reloaded'] is True
    assert body['restart_required'] is False
    assert body['runtime_status'] == 'healthy'
    assert body['runtime_errors'] == []
    assert body['tool_updates']['http']['status'] == 'reloaded'
    assert body['tool_updates']['git']['status'] == 'reloaded'
    assert fake_loop.refresh_calls == [['tools.http', 'tools.git', 'tools.db', 'tools.k8s', 'tools.notify']]
    assert fake_channels.refresh_calls == [(['tools.http', 'tools.git', 'tools.db', 'tools.k8s', 'tools.notify'], 'settings_apply')]
    assert kill_calls == []


def test_restart_regex_includes_operator_tools():
    assert _RESTART_FIELDS.match('tools.mcp_servers')
    assert not _RESTART_FIELDS.match('tools.http')
    assert not _RESTART_FIELDS.match('tools.git')
    assert not _RESTART_FIELDS.match('tools.notify')
    assert not _RESTART_FIELDS.match('tools.db')
    assert not _RESTART_FIELDS.match('tools.k8s')


def test_apply_settings_marks_mcp_servers_as_restart_required(monkeypatch, tmp_path):
    config_path = tmp_path / 'config.json'
    save_config(Config(), config_path)

    kill_calls = []
    monkeypatch.setattr('os.kill', lambda pid, sig: kill_calls.append((pid, sig)))

    app = create_app(config_path=config_path, auth_token=None)
    client = TestClient(app)

    resp = client.post('/api/settings/apply', json={
        'changed_paths': ['tools.mcp_servers'],
    })

    assert resp.status_code == 200
    body = resp.json()
    assert body['restart_required'] is True
    assert body['restart_fields'] == ['tools.mcp_servers']
    assert body['runtime_status'] == 'submitted'
    assert body['restart_state']['status'] == 'submitted'
    assert body['restart_state']['restart_fields'] == ['tools.mcp_servers']

    state = load_runtime_state(config_path)
    assert state['status'] == 'submitted'
    assert state['restart_fields'] == ['tools.mcp_servers']


def test_apply_settings_persists_failed_runtime_state(monkeypatch, tmp_path):
    config_path = tmp_path / 'config.json'
    save_config(Config(), config_path)

    class FakeAgentLoop:
        async def refresh_runtime_config(self, config, *, changed_paths):
            raise RuntimeError("tool refresh boom")

        def update_defaults(self, **kwargs):
            return None

    app = create_app(config_path=config_path, auth_token=None, agent_loop=FakeAgentLoop())
    client = TestClient(app)

    resp = client.post('/api/settings/apply', json={
        'changed_paths': ['tools.http'],
    })

    assert resp.status_code == 200
    body = resp.json()
    assert body['restart_required'] is False
    assert body['runtime_status'] == 'failed'
    assert any('tool refresh failed' in item for item in body['runtime_errors'])
    assert body['restart_state']['status'] == 'failed'

    state = load_runtime_state(config_path)
    assert state['status'] == 'failed'
    assert any('tool refresh failed' in item for item in state['runtime_errors'])


def test_apply_settings_restart_state_tracks_recent_notify_targets(monkeypatch, tmp_path):
    config_path = tmp_path / 'config.json'
    save_config(Config(), config_path)

    sessions = SessionManager(tmp_path)
    session = sessions.get_or_create('telegram:123')
    session.add_message('user', 'hello')
    sessions.save(session)

    class FakeAgentLoop:
        def __init__(self) -> None:
            self.sessions = sessions
            self.bus = MessageBus()

        async def refresh_runtime_config(self, config, *, changed_paths):
            return {}

        def update_defaults(self, **kwargs):
            return None

    kill_calls = []
    monkeypatch.setattr('os.kill', lambda pid, sig: kill_calls.append((pid, sig)))

    app = create_app(config_path=config_path, auth_token=None, agent_loop=FakeAgentLoop())
    client = TestClient(app)

    resp = client.post('/api/settings/apply', json={
        'changed_paths': ['tools.mcp_servers'],
    })

    assert resp.status_code == 200
    body = resp.json()
    assert body['restart_state']['notify_targets'][0]['session_key'] == 'telegram:123'
    assert body['restart_state']['notify_targets'][0]['channel'] == 'telegram'
    assert body['restart_state']['notify_targets'][0]['chat_id'] == '123'


def test_apply_settings_restart_state_includes_pairing_owner_notify_target(monkeypatch, tmp_path):
    from lemonclaw.channels.auto_pairing import AutoPairing

    config_path = tmp_path / 'config.json'
    cfg = Config()
    cfg.channels.auto_pairing = True
    cfg.channels.telegram.enabled = True
    save_config(cfg, config_path)

    monkeypatch.setattr('lemonclaw.utils.helpers.get_data_path', lambda: tmp_path)
    pairing = AutoPairing('telegram', tmp_path)
    assert pairing.check_or_pair('owner|phone', notify_target='owner-dm') == 'paired'

    sessions = SessionManager(tmp_path)

    class FakeAgentLoop:
        def __init__(self) -> None:
            self.sessions = sessions
            self.bus = MessageBus()

        async def refresh_runtime_config(self, config, *, changed_paths):
            return {}

        def update_defaults(self, **kwargs):
            return None

    kill_calls = []
    monkeypatch.setattr('os.kill', lambda pid, sig: kill_calls.append((pid, sig)))

    app = create_app(config_path=config_path, auth_token=None, agent_loop=FakeAgentLoop())
    client = TestClient(app)

    resp = client.post('/api/settings/apply', json={
        'changed_paths': ['tools.mcp_servers'],
    })

    assert resp.status_code == 200
    body = resp.json()
    targets = body['restart_state']['notify_targets']
    assert any(item['channel'] == 'telegram' and item['chat_id'] == 'owner-dm' and item.get('source') == 'pairing_owner' for item in targets)


@pytest.mark.asyncio
async def test_broadcast_restart_notice_publishes_to_recent_session(tmp_path):
    sessions = SessionManager(tmp_path)
    session = sessions.get_or_create('telegram:123')
    session.metadata['lang'] = 'zh'
    sessions.save(session)
    bus = MessageBus()

    fake_loop = type('Loop', (), {'sessions': sessions, 'bus': bus})()
    sent = await broadcast_restart_notice(
        fake_loop,
        stage='submitted',
        state={
            'restart_fields': ['tools.mcp_servers'],
            'notify_targets': [{'session_key': 'telegram:123', 'channel': 'telegram', 'chat_id': '123'}],
        },
    )

    assert sent == 1
    outbound = await bus.consume_outbound()
    assert outbound.channel == 'telegram'
    assert outbound.chat_id == '123'
    assert '重启已提交' in outbound.content


@pytest.mark.asyncio
async def test_startup_runtime_notice_derives_pairing_owner_targets(monkeypatch, tmp_path):
    from lemonclaw.channels.auto_pairing import AutoPairing

    config_path = tmp_path / 'config.json'
    cfg = Config()
    cfg.channels.auto_pairing = True
    cfg.channels.telegram.enabled = True
    save_config(cfg, config_path)

    monkeypatch.setattr('lemonclaw.utils.helpers.get_data_path', lambda: tmp_path)
    pairing = AutoPairing('telegram', tmp_path)
    assert pairing.check_or_pair('owner|phone', notify_target='owner-dm') == 'paired'

    sessions = SessionManager(tmp_path)
    bus = MessageBus()
    fake_loop = type('Loop', (), {'sessions': sessions, 'bus': bus})()

    mark_runtime_healthy(config_path, version='1.2.3')

    sent = await maybe_broadcast_startup_restart_notice(
        fake_loop,
        config_path=config_path,
        config=cfg,
    )

    assert sent == 1
    outbound = await bus.consume_outbound()
    assert outbound.channel == 'telegram'
    assert outbound.chat_id == 'owner-dm'
    assert 'completed successfully' in outbound.content.lower()
    state = load_runtime_state(config_path)
    assert any(item['chat_id'] == 'owner-dm' and item.get('source') == 'pairing_owner' for item in state['notify_targets'])
    assert int((state.get('notifications') or {}).get('healthy') or 0) == int(state.get('last_restart_completed_at_ms') or 0)


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


def test_settings_masks_git_auth_profiles_and_preserves_on_patch(tmp_path):
    config_path = tmp_path / 'config.json'
    cfg = Config()
    cfg.tools.git.auth_profiles = {
        'origin': GitAuthProfileConfig(username='x-access-token', password='github_pat_super_secret_123456789')
    }
    save_config(cfg, config_path)

    app = create_app(config_path=config_path, auth_token=None)
    client = TestClient(app)

    resp = client.get('/api/settings')
    assert resp.status_code == 200
    git_settings = resp.json()['settings']['tools']['git']
    assert git_settings['auth_profiles']['origin']['username'] == 'x-access-token'
    assert git_settings['auth_profiles']['origin']['password'] == 'gith****6789'

    resp = client.patch('/api/settings', json={
        'tools.git': {
            'timeout': 45,
            'max_output': 70000,
            'auth_profiles': git_settings['auth_profiles'],
        }
    })
    assert resp.status_code == 200

    updated = load_config(config_path)
    assert updated.tools.git.timeout == 45
    assert updated.tools.git.max_output == 70000
    assert updated.tools.git.auth_profiles['origin'].username == 'x-access-token'
    assert updated.tools.git.auth_profiles['origin'].password == 'github_pat_super_secret_123456789'
