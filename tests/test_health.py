from __future__ import annotations

from pathlib import Path

from starlette.testclient import TestClient

from lemonclaw.config.loader import save_config
from lemonclaw.config.schema import Config
from lemonclaw.gateway.runtime_state import mark_runtime_failed
from lemonclaw.gateway.server import create_app


class _FakeChannelManager:
    def __init__(self, channel_status: dict[str, dict[str, object]]) -> None:
        self._channel_status = channel_status
        self.enabled_channels = [
            name
            for name, status in channel_status.items()
            if bool(status.get("configured_enabled"))
        ]

    def get_channel_status(self) -> dict[str, dict[str, object]]:
        return {name: dict(status) for name, status in self._channel_status.items()}


def _make_client(tmp_path: Path, channel_status: dict[str, dict[str, object]]) -> TestClient:
    config_path = tmp_path / "config.json"
    save_config(Config(), config_path)
    app = create_app(
        config_path=config_path,
        auth_token=None,
        channel_manager=_FakeChannelManager(channel_status),
    )
    return TestClient(app)


def test_readyz_succeeds_when_channels_are_usable_and_restart_state_is_healthy(tmp_path):
    client = _make_client(
        tmp_path,
        {
                "telegram": {
                    "configured_enabled": True,
                    "configured_complete": True,
                    "registered": True,
                    "available": True,
                    "running": True,
                    "error": "",
                }
        },
    )

    resp = client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json()["checks"] == {
        "channels_configured": True,
        "channels_usable": True,
        "restart_state_healthy": True,
    }


def test_readyz_fails_when_enabled_channel_is_unusable(tmp_path):
    client = _make_client(
        tmp_path,
        {
                "telegram": {
                    "configured_enabled": True,
                    "configured_complete": True,
                    "registered": True,
                    "available": False,
                    "running": False,
                    "error": "missing dependency",
                }
        },
    )

    resp = client.get("/readyz")
    assert resp.status_code == 503
    assert resp.json()["checks"] == {
        "channels_configured": True,
        "channels_usable": False,
        "restart_state_healthy": True,
    }


def test_readyz_fails_when_restart_state_is_failed(tmp_path):
    config_path = tmp_path / "config.json"
    save_config(Config(), config_path)
    client = TestClient(
        create_app(
            config_path=config_path,
            auth_token=None,
            channel_manager=_FakeChannelManager(
                {
                    "telegram": {
                        "configured_enabled": True,
                        "configured_complete": True,
                        "registered": True,
                        "available": True,
                        "running": True,
                        "error": "",
                    }
                },
            ),
        )
    )
    mark_runtime_failed(config_path, runtime_errors=["startup failed"], source="settings_apply")

    resp = client.get("/readyz")
    assert resp.status_code == 503
    assert resp.json()["checks"] == {
        "channels_configured": True,
        "channels_usable": True,
        "restart_state_healthy": False,
    }
