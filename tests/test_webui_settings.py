from starlette.testclient import TestClient

from lemonclaw.channels.whatsapp_bridge_runtime import WhatsAppBridgeError
from lemonclaw.config.loader import save_config
from lemonclaw.config.schema import Config
from lemonclaw.gateway.server import create_app
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

