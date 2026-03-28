from __future__ import annotations

import base64

from starlette.testclient import TestClient

from lemonclaw.channels.manager import ChannelManager
from lemonclaw.config.schema import Config
from lemonclaw.gateway.server import create_app


def _make_agentbridge_app(make_agent_loop):
    loop, bus = make_agent_loop()
    manager = ChannelManager(Config(), bus)
    app = create_app(
        auth_token="secret-token",
        agent_loop=loop,
        session_manager=loop.sessions,
        channel_manager=manager,
        usage_tracker=loop.usage_tracker,
    )
    return loop, manager, TestClient(app)


class TestAgentBridgeRoutes:
    def test_chat_requires_bearer_auth(self, make_agent_loop):
        _loop, _manager, client = _make_agentbridge_app(make_agent_loop)
        resp = client.post(
            "/api/agentbridge/chat",
            json={"client_id": "codex", "thread_id": "demo", "message": "hello"},
        )
        assert resp.status_code == 401

    def test_chat_stream_returns_sse_and_persists_messages(self, make_agent_loop):
        _loop, _manager, client = _make_agentbridge_app(make_agent_loop)
        headers = {"Authorization": "Bearer secret-token"}
        resp = client.post(
            "/api/agentbridge/chat/stream",
            headers=headers,
            json={"client_id": "codex", "thread_id": "demo", "message": "hello"},
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        assert '"type": "meta"' in resp.text or '"type":"meta"' in resp.text
        assert '"type": "done"' in resp.text or '"type":"done"' in resp.text

        history = client.get(
            "/api/agentbridge/messages",
            headers=headers,
            params={"client_id": "codex", "thread_id": "demo"},
        )
        assert history.status_code == 200
        payload = history.json()
        assert payload["session_key"] == "agentbridge:codex:default:demo"
        assert any(msg.get("role") == "assistant" and msg.get("content") for msg in payload["messages"])

    def test_chat_rejects_cross_provider_model_switch(self, make_agent_loop):
        loop, _manager, client = _make_agentbridge_app(make_agent_loop)
        session = loop.sessions.get_or_create("agentbridge:codex:default:demo")
        session.messages.append({"role": "user", "content": "hello"})
        session.metadata["current_model"] = "claude-sonnet-4-6"
        loop.sessions.save(session)

        headers = {"Authorization": "Bearer secret-token"}
        resp = client.post(
            "/api/agentbridge/chat",
            headers=headers,
            json={
                "client_id": "codex",
                "thread_id": "demo",
                "message": "switch",
                "model": "gpt-5.2",
            },
        )
        assert resp.status_code == 409
        assert resp.json()["error"] == "provider_family_conflict"

    def test_usage_accepts_agentbridge_session_key(self, make_agent_loop):
        _loop, _manager, client = _make_agentbridge_app(make_agent_loop)
        headers = {"Authorization": "Bearer secret-token"}
        chat = client.post(
            "/api/agentbridge/chat",
            headers=headers,
            json={"client_id": "codex", "thread_id": "usage-demo", "message": "hello"},
        )
        assert chat.status_code == 200

        usage = client.get(
            "/api/usage",
            headers=headers,
            params={"session": "agentbridge:codex:default:usage-demo"},
        )
        assert usage.status_code == 200
        payload = usage.json()
        assert payload["session"]["key"] == "agentbridge:codex:default:usage-demo"

    def test_usage_does_not_preserve_webui_prefix_under_bearer_auth(self, make_agent_loop):
        loop, _manager, client = _make_agentbridge_app(make_agent_loop)
        session = loop.sessions.get_or_create("webui:hidden")
        session.messages.append({"role": "user", "content": "hello"})
        loop.sessions.save(session)

        usage = client.get(
            "/api/usage",
            headers={"Authorization": "Bearer secret-token"},
            params={"session": "webui:hidden"},
        )
        assert usage.status_code == 200
        payload = usage.json()
        assert payload["session"]["key"] == "api:webui:hidden"
        assert payload["session"]["error"] == "not found"

    def test_media_rejects_user_supplied_file_tokens(self, make_agent_loop):
        _loop, _manager, client = _make_agentbridge_app(make_agent_loop)
        headers = {"Authorization": "Bearer secret-token"}
        chat = client.post(
            "/api/agentbridge/chat",
            headers=headers,
            json={"client_id": "codex", "thread_id": "media-deny", "message": "leak [file:/etc/hosts]"},
        )
        assert chat.status_code == 200
        session_key = chat.json()["session_key"]

        media = client.get(
            "/api/agentbridge/media",
            headers=headers,
            params={"path": "/etc/hosts", "session_key": session_key},
        )
        assert media.status_code == 403
        assert media.json()["error"] == "access denied"

    def test_media_allows_uploaded_attachments(self, make_agent_loop):
        _loop, _manager, client = _make_agentbridge_app(make_agent_loop)
        headers = {"Authorization": "Bearer secret-token"}
        encoded = base64.b64encode(b"hello agentbridge").decode()
        upload = client.post(
            "/api/agentbridge/uploads",
            headers=headers,
            json={"data": encoded, "filename": "note.txt"},
        )
        assert upload.status_code == 200
        attachment_id = upload.json()["attachments"][0]["id"]

        chat = client.post(
            "/api/agentbridge/chat",
            headers=headers,
            json={
                "client_id": "codex",
                "thread_id": "media-allow",
                "message": "see attachment",
                "attachments": [attachment_id],
            },
        )
        assert chat.status_code == 200
        session_key = chat.json()["session_key"]

        history = client.get(
            "/api/agentbridge/messages",
            headers=headers,
            params={"client_id": "codex", "thread_id": "media-allow"},
        )
        assert history.status_code == 200
        media_path = next(
            media["path"]
            for message in history.json()["messages"]
            if message.get("role") == "user"
            for media in message.get("media", [])
        )

        media = client.get(
            "/api/agentbridge/media",
            headers=headers,
            params={"path": media_path, "session_key": session_key},
        )
        assert media.status_code == 200
        assert media.content == b"hello agentbridge"
