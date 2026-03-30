from __future__ import annotations

import base64
import json

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

    def test_chat_stream_surfaces_progress_kind(self, make_agent_loop):
        loop, _manager, client = _make_agentbridge_app(make_agent_loop)

        async def _fake_process_direct(*args, **kwargs):
            on_progress = kwargs["on_progress"]
            on_chunk = kwargs["on_chunk"]
            await on_progress("tool starts", tool_start=True)
            await on_chunk("chunk-1", first=True)
            return "done"

        loop.process_direct = _fake_process_direct

        headers = {"Authorization": "Bearer secret-token"}
        resp = client.post(
            "/api/agentbridge/chat/stream",
            headers=headers,
            json={"client_id": "codex", "thread_id": "progress-demo", "message": "hello"},
        )

        assert resp.status_code == 200
        assert '"progress_kind": "tool_start"' in resp.text or '"progress_kind":"tool_start"' in resp.text
        assert '"progress_kind": "chunk"' in resp.text or '"progress_kind":"chunk"' in resp.text

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

    def test_chat_injects_session_context_into_process_direct(self, make_agent_loop):
        loop, _manager, client = _make_agentbridge_app(make_agent_loop)
        captured: dict[str, object] = {}

        async def _fake_process_direct(*args, **kwargs):
            captured["metadata"] = kwargs["metadata"]
            return "ok"

        loop.process_direct = _fake_process_direct

        headers = {"Authorization": "Bearer secret-token"}
        resp = client.post(
            "/api/agentbridge/chat",
            headers=headers,
            json={
                "client_id": "codex",
                "workspace_id": "default",
                "thread_id": "ctx-demo",
                "message": "hello",
                "timezone": "Asia/Shanghai",
                "run_mode": "detached",
            },
        )

        assert resp.status_code == 200
        metadata = captured["metadata"]
        assert isinstance(metadata, dict)
        assert metadata["timezone"] == "Asia/Shanghai"
        assert metadata["run_mode"] == "detached"
        assert metadata["agentbridge"]["session_context"] == {
            "timezone": "Asia/Shanghai",
            "run_mode": "detached",
        }

    def test_chat_stream_injects_session_context_into_process_direct(self, make_agent_loop):
        loop, _manager, client = _make_agentbridge_app(make_agent_loop)
        captured: dict[str, object] = {}

        async def _fake_process_direct(*args, **kwargs):
            captured["metadata"] = kwargs["metadata"]
            return "streamed"

        loop.process_direct = _fake_process_direct

        headers = {"Authorization": "Bearer secret-token"}
        resp = client.post(
            "/api/agentbridge/chat/stream",
            headers=headers,
            json={
                "client_id": "codex",
                "workspace_id": "default",
                "thread_id": "ctx-stream-demo",
                "message": "hello",
                "timezone": "UTC",
                "run_mode": "system",
            },
        )

        assert resp.status_code == 200
        assert '"type": "done"' in resp.text or '"type":"done"' in resp.text
        metadata = captured["metadata"]
        assert isinstance(metadata, dict)
        assert metadata["timezone"] == "UTC"
        assert metadata["run_mode"] == "system"
        assert metadata["agentbridge"]["session_context"] == {
            "timezone": "UTC",
            "run_mode": "system",
        }

    def test_chat_persists_run_mode_in_task_resume_context(self, make_agent_loop):
        loop, _manager, client = _make_agentbridge_app(make_agent_loop)
        headers = {"Authorization": "Bearer secret-token"}

        resp = client.post(
            "/api/agentbridge/chat",
            headers=headers,
            json={
                "client_id": "codex",
                "workspace_id": "default",
                "thread_id": "resume-mode-demo",
                "message": "hello",
                "timezone": "Asia/Shanghai",
                "run_mode": "detached",
            },
        )

        assert resp.status_code == 200
        task = loop.ledger.read_task(resp.json()["task_id"])
        assert task is not None
        assert task["resume_context"]["timezone"] == "Asia/Shanghai"
        assert task["resume_context"]["run_mode"] == "detached"

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

    def test_agentbridge_chat_loads_repo_change_memory_sidecar(self, make_agent_loop):
        loop, _manager, client = _make_agentbridge_app(make_agent_loop)
        headers = {"Authorization": "Bearer secret-token"}
        sidecar = loop.workspace / ".lemonclaw-state" / "repo-change-memory"
        sidecar.mkdir(parents=True, exist_ok=True)
        (sidecar / "codex__default__repo-demo.json").write_text(
            json.dumps(
                {
                    "summary": "Prefer service adapters over direct route edits.",
                    "preferred_internal_apis": ["service.adapters.run"],
                    "path_conventions": ["services/**"],
                    "historical_patch_patterns": ["adapter-first refactors"],
                }
            ),
            encoding="utf-8",
        )

        resp = client.post(
            "/api/agentbridge/chat",
            headers=headers,
            json={"client_id": "codex", "thread_id": "repo-demo", "message": "continue"},
        )

        assert resp.status_code == 200
        task = loop.ledger.read_task(resp.json()["task_id"])
        assert task is not None
        retrieval = dict(task.get("metadata") or {}).get("retrieval") or {}
        assert retrieval["repo_change_memory_count"] == 1
        assert "repo_change_memory" in retrieval["hit_sources"]
        repo_change = retrieval["structured"]["retrieval_objects"][-1]
        assert repo_change["kind"] == "repo_change_memory"
        assert repo_change["preferred_internal_apis"] == ["service.adapters.run"]
