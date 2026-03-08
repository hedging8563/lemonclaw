from starlette.testclient import TestClient

from lemonclaw.config.loader import save_config
from lemonclaw.config.schema import Config
from lemonclaw.gateway.server import create_app
from lemonclaw.channels.whatsapp_bridge_runtime import WhatsAppBridgeError


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
