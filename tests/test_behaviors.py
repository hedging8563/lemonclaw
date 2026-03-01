"""Behavioral regression tests for LemonClaw agent.

Based on real failure scenarios from OpenClaw 12,671 issues,
nanobot 309 issues, and LemonClaw production bugs.

Run: pytest tests/test_behaviors.py -v
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from lemonclaw.agent.tools.shell import ExecTool
from lemonclaw.bus.events import InboundMessage, OutboundMessage
from lemonclaw.providers.base import LLMResponse, ToolCallRequest
from lemonclaw.telemetry.usage import TurnUsage, UsageTracker


# ── 2a. Tool Safety (CVE-2026-25253, shell.py deny_patterns) ──


class TestToolSafety:
    """Dangerous commands must be blocked by ExecTool."""

    @pytest.fixture
    def exec_tool(self):
        return ExecTool(timeout=5)

    @pytest.mark.asyncio
    async def test_rm_rf_blocked(self, exec_tool):
        result = await exec_tool.execute(command="rm -rf /tmp/test")
        assert "blocked" in result.lower() or "Error" in result

    @pytest.mark.asyncio
    async def test_dd_blocked(self, exec_tool):
        result = await exec_tool.execute(command="dd if=/dev/zero of=/tmp/x")
        assert "blocked" in result.lower() or "Error" in result

    @pytest.mark.asyncio
    async def test_shutdown_blocked(self, exec_tool):
        result = await exec_tool.execute(command="shutdown -h now")
        assert "blocked" in result.lower() or "Error" in result

    @pytest.mark.asyncio
    async def test_fork_bomb_blocked(self, exec_tool):
        result = await exec_tool.execute(command=":(){ :|:& };:")
        assert "blocked" in result.lower() or "Error" in result

    @pytest.mark.asyncio
    async def test_safe_command_allowed(self, exec_tool):
        result = await exec_tool.execute(command="echo hello")
        assert "hello" in result

    @pytest.mark.asyncio
    async def test_python_shutil_allowed(self, exec_tool):
        """skill-installer uses python3 shutil.rmtree instead of rm -rf."""
        result = await exec_tool.execute(
            command="python3 -c \"import shutil; print('ok')\""
        )
        assert "ok" in result

    @pytest.mark.asyncio
    async def test_path_traversal_blocked(self):
        tool = ExecTool(timeout=5, restrict_to_workspace=True, working_dir="/tmp")
        result = await tool.execute(command="cat ../../etc/passwd")
        assert "blocked" in result.lower() or "Error" in result


# ── 2b. Session Management (nanobot #1255, #1318) ──


class TestSlashCommands:
    """Slash commands must respond correctly."""

    @pytest.mark.asyncio
    async def test_help_contains_lemonclaw(self, make_agent_loop):
        loop, bus = make_agent_loop()
        msg = InboundMessage(
            channel="test", sender_id="u1", chat_id="c1", content="/help"
        )
        response = await loop._process_message(msg)
        assert response is not None
        assert "LemonClaw" in response.content

    @pytest.mark.asyncio
    async def test_usage_contains_token(self, make_agent_loop):
        loop, bus = make_agent_loop()
        msg = InboundMessage(
            channel="test", sender_id="u1", chat_id="c1", content="/usage"
        )
        response = await loop._process_message(msg)
        assert response is not None
        assert "token" in response.content.lower()

    @pytest.mark.asyncio
    async def test_new_clears_session(self, make_agent_loop):
        loop, bus = make_agent_loop()
        # First, create some history
        msg1 = InboundMessage(
            channel="test", sender_id="u1", chat_id="c1", content="hello"
        )
        await loop._process_message(msg1)
        session = loop.sessions.get_or_create("test:c1")
        assert len(session.messages) > 0

        # /new requires memory consolidation to succeed — mock it
        with patch.object(loop, "_consolidate_memory", new_callable=AsyncMock, return_value=True):
            msg2 = InboundMessage(
                channel="test", sender_id="u1", chat_id="c1", content="/new"
            )
            response = await loop._process_message(msg2)
        assert response is not None
        assert "new session" in response.content.lower() or "started" in response.content.lower()


# ── 2c. Token Tracking (P2-A) ──


class TestTokenTracking:
    def test_turn_usage_accumulates(self):
        tu = TurnUsage()
        tu.record({"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150})
        tu.record({"prompt_tokens": 200, "completion_tokens": 100, "total_tokens": 300})
        assert tu.prompt_tokens == 300
        assert tu.completion_tokens == 150
        assert tu.total_tokens == 450
        assert tu.llm_calls == 2

    def test_turn_usage_fallback_when_total_zero(self):
        """Some providers return total_tokens=0."""
        tu = TurnUsage()
        tu.record({"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 0})
        assert tu.total_tokens == 150  # fallback: prompt + completion

    def test_usage_tracker_budget_alert(self):
        tracker = UsageTracker(token_budget_per_session=1000)
        tu = TurnUsage()
        tu.record({"prompt_tokens": 400, "completion_tokens": 100, "total_tokens": 500})
        metadata: dict = {}
        alerts = tracker.record_turn("test:c1", tu, metadata)
        assert len(alerts) == 0  # 50% - no alert yet

        tu2 = TurnUsage()
        tu2.record({"prompt_tokens": 400, "completion_tokens": 200, "total_tokens": 600})
        alerts2 = tracker.record_turn("test:c1", tu2, metadata)
        assert len(alerts2) >= 1  # 1100/1000 = 110% - should alert

    def test_usage_tracker_no_division_by_zero(self):
        tracker = UsageTracker(token_budget_per_session=0)
        tu = TurnUsage()
        tu.record({"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150})
        metadata: dict = {}
        # Should not raise
        alerts = tracker.record_turn("test:c1", tu, metadata)
        assert isinstance(alerts, list)


# ── 2d. Repeated Tool Error Detection ──


class TestRepeatedToolErrors:
    """Agent loop should break on repeated identical tool errors."""

    @pytest.mark.asyncio
    async def test_breaks_on_repeated_errors(self, make_agent_loop, echo_provider):
        """LLM keeps calling read_file({}) → should break after 3 failures."""
        # Script: LLM returns read_file({}) tool call every time
        echo_provider.responses = [
            LLMResponse(
                content=None,
                tool_calls=[ToolCallRequest(
                    id=f"call_{i}", name="read_file", arguments={}
                )],
                usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            )
            for i in range(10)
        ]
        # Add a final text response (won't be reached if break works)
        echo_provider.responses.append(
            LLMResponse(content="done", usage={"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7})
        )

        loop, bus = make_agent_loop(max_iterations=40)
        msg = InboundMessage(
            channel="test", sender_id="u1", chat_id="c1", content="test"
        )
        response = await loop._process_message(msg)
        assert response is not None
        # Should have broken early, not reached 40 iterations
        assert "failed repeatedly" in response.content.lower() or "error" in response.content.lower()


# ── 2e. Gateway /api/chat Endpoint ──


class TestChatEndpoint:
    """POST /api/chat should work correctly."""

    @pytest.mark.asyncio
    async def test_chat_returns_response(self, make_agent_loop):
        from starlette.testclient import TestClient
        from lemonclaw.gateway.server import create_app

        loop, bus = make_agent_loop()
        app = create_app(auth_token=None, agent_loop=loop)
        client = TestClient(app)

        resp = client.post("/api/chat", json={"message": "hello"})
        assert resp.status_code == 200
        data = resp.json()
        assert "response" in data
        assert len(data["response"]) > 0

    @pytest.mark.asyncio
    async def test_chat_requires_message(self, make_agent_loop):
        from starlette.testclient import TestClient
        from lemonclaw.gateway.server import create_app

        loop, bus = make_agent_loop()
        app = create_app(auth_token=None, agent_loop=loop)
        client = TestClient(app)

        resp = client.post("/api/chat", json={})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_chat_auth_required(self, make_agent_loop):
        from starlette.testclient import TestClient
        from lemonclaw.gateway.server import create_app

        loop, bus = make_agent_loop()
        app = create_app(auth_token="secret123", agent_loop=loop)
        client = TestClient(app)

        resp = client.post("/api/chat", json={"message": "hello"})
        assert resp.status_code == 401

        resp2 = client.post(
            "/api/chat",
            json={"message": "hello"},
            headers={"Authorization": "Bearer secret123"},
        )
        assert resp2.status_code == 200


# ── 5. WeCom Channel (crypto, signature, webhook) ──


class TestWeComCrypto:
    """WeCom AES encryption/decryption and signature verification."""

    CORP_ID = "wx1234567890abcdef"
    # 43-char base64 key (decodes to 32 bytes)
    ENCODING_AES_KEY = "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG"

    def test_encrypt_decrypt_roundtrip(self):
        from lemonclaw.channels.wecom import WeComCrypto

        crypto = WeComCrypto(self.ENCODING_AES_KEY, self.CORP_ID)
        original = "<xml><Content>hello world</Content></xml>"
        encrypted = crypto.encrypt(original)
        decrypted = crypto.decrypt(encrypted)
        assert decrypted == original

    def test_decrypt_wrong_corp_id_fails(self):
        from lemonclaw.channels.wecom import WeComCrypto

        crypto = WeComCrypto(self.ENCODING_AES_KEY, self.CORP_ID)
        wrong_crypto = WeComCrypto(self.ENCODING_AES_KEY, "wx_wrong_corp")

        encrypted = wrong_crypto.encrypt("test message")
        with pytest.raises(ValueError, match="corp_id mismatch"):
            crypto.decrypt(encrypted)

    def test_verify_signature(self):
        from lemonclaw.channels.wecom import verify_signature

        token = "test_token"
        timestamp = "1234567890"
        nonce = "abc123"
        encrypt = "encrypted_data"

        sig = verify_signature(token, timestamp, nonce, encrypt)
        assert len(sig) == 40  # SHA1 hex digest
        # Same inputs → same output
        assert sig == verify_signature(token, timestamp, nonce, encrypt)
        # Different input → different output
        assert sig != verify_signature(token, timestamp, nonce, "other_data")


class TestWeComXML:
    """WeCom XML parsing and building."""

    def test_parse_xml(self):
        from lemonclaw.channels.wecom import parse_xml

        xml = (
            "<xml>"
            "<ToUserName><![CDATA[corp_id]]></ToUserName>"
            "<FromUserName><![CDATA[user_id]]></FromUserName>"
            "<MsgType><![CDATA[text]]></MsgType>"
            "<Content><![CDATA[hello]]></Content>"
            "<MsgId>12345</MsgId>"
            "</xml>"
        )
        result = parse_xml(xml)
        assert result["ToUserName"] == "corp_id"
        assert result["FromUserName"] == "user_id"
        assert result["MsgType"] == "text"
        assert result["Content"] == "hello"
        assert result["MsgId"] == "12345"

    def test_build_reply_xml(self):
        from lemonclaw.channels.wecom import build_reply_xml

        xml = build_reply_xml("enc_data", "sig123", "1234567890", "nonce_abc")
        assert "<Encrypt><![CDATA[enc_data]]></Encrypt>" in xml
        assert "<MsgSignature><![CDATA[sig123]]></MsgSignature>" in xml
        assert "<TimeStamp>1234567890</TimeStamp>" in xml


class TestWeComWebhook:
    """WeCom webhook endpoint integration tests."""

    @pytest.mark.asyncio
    async def test_webhook_get_returns_404_without_channel(self):
        from starlette.testclient import TestClient
        from lemonclaw.gateway.server import create_app

        app = create_app(auth_token=None, channel_manager=None)
        client = TestClient(app)
        resp = client.get("/webhook/wecom?msg_signature=x&timestamp=1&nonce=a&echostr=b")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_webhook_post_returns_404_without_channel(self):
        from starlette.testclient import TestClient
        from lemonclaw.gateway.server import create_app

        app = create_app(auth_token=None, channel_manager=None)
        client = TestClient(app)
        resp = client.post("/webhook/wecom?msg_signature=x&timestamp=1&nonce=a", content="<xml></xml>")
        assert resp.status_code == 404


# ── 6a. WebUI Auth (HMAC cookie) ──


class TestWebUIAuth:
    """HMAC cookie authentication for WebUI."""

    def test_verify_token_correct(self):
        from lemonclaw.gateway.webui.auth import verify_token
        assert verify_token("secret123", "secret123") is True

    def test_verify_token_wrong(self):
        from lemonclaw.gateway.webui.auth import verify_token
        assert verify_token("wrong", "secret123") is False

    def test_cookie_roundtrip(self):
        from lemonclaw.gateway.webui.auth import create_session_cookie, verify_session_cookie
        cookie = create_session_cookie("mytoken")
        valid, refreshed = verify_session_cookie(cookie, "mytoken")
        assert valid is True
        assert refreshed is not None

    def test_cookie_wrong_token(self):
        from lemonclaw.gateway.webui.auth import create_session_cookie, verify_session_cookie
        cookie = create_session_cookie("mytoken")
        valid, refreshed = verify_session_cookie(cookie, "othertoken")
        assert valid is False
        assert refreshed is None

    def test_cookie_expired_absolute(self):
        from unittest.mock import patch as mock_patch
        from lemonclaw.gateway.webui.auth import (
            create_session_cookie, verify_session_cookie, ABSOLUTE_TIMEOUT,
        )
        import time as time_mod

        cookie = create_session_cookie("tok")
        # Advance time past absolute timeout
        future = time_mod.time() + ABSOLUTE_TIMEOUT + 60
        with mock_patch("lemonclaw.gateway.webui.auth.time.time", return_value=future):
            valid, _ = verify_session_cookie(cookie, "tok")
        assert valid is False

    def test_cookie_expired_idle(self):
        from unittest.mock import patch as mock_patch
        from lemonclaw.gateway.webui.auth import (
            create_session_cookie, verify_session_cookie, IDLE_TIMEOUT,
        )
        import time as time_mod

        cookie = create_session_cookie("tok")
        # Advance time past idle timeout but within absolute
        future = time_mod.time() + IDLE_TIMEOUT + 60
        with mock_patch("lemonclaw.gateway.webui.auth.time.time", return_value=future):
            valid, _ = verify_session_cookie(cookie, "tok")
        assert valid is False


# ── 6b. WebUI Routes ──


class TestWebUIRoutes:
    """WebUI HTTP endpoint tests."""

    @pytest.mark.asyncio
    async def test_index_returns_html(self, make_agent_loop):
        from starlette.testclient import TestClient
        from lemonclaw.gateway.server import create_app

        loop, bus = make_agent_loop()
        app = create_app(auth_token=None, agent_loop=loop,
                         session_manager=loop.sessions, webui_enabled=True)
        client = TestClient(app)
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "LemonClaw" in resp.text

    @pytest.mark.asyncio
    async def test_auth_correct_token(self, make_agent_loop):
        from starlette.testclient import TestClient
        from lemonclaw.gateway.server import create_app

        loop, bus = make_agent_loop()
        app = create_app(auth_token="test-secret", agent_loop=loop,
                         session_manager=loop.sessions, webui_enabled=True)
        client = TestClient(app)
        resp = client.post("/api/auth", json={"token": "test-secret"})
        assert resp.status_code == 200
        assert "lc_session" in resp.cookies

    @pytest.mark.asyncio
    async def test_auth_wrong_token(self, make_agent_loop):
        from starlette.testclient import TestClient
        from lemonclaw.gateway.server import create_app

        loop, bus = make_agent_loop()
        app = create_app(auth_token="test-secret", agent_loop=loop,
                         session_manager=loop.sessions, webui_enabled=True)
        client = TestClient(app)
        resp = client.post("/api/auth", json={"token": "wrong"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_sessions_requires_auth(self, make_agent_loop):
        from starlette.testclient import TestClient
        from lemonclaw.gateway.server import create_app

        loop, bus = make_agent_loop()
        app = create_app(auth_token="secret", agent_loop=loop,
                         session_manager=loop.sessions, webui_enabled=True)
        client = TestClient(app)
        resp = client.get("/api/sessions")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_models_returns_list(self, make_agent_loop):
        from starlette.testclient import TestClient
        from lemonclaw.gateway.server import create_app

        loop, bus = make_agent_loop()
        app = create_app(auth_token=None, agent_loop=loop,
                         session_manager=loop.sessions, webui_enabled=True)
        client = TestClient(app)
        resp = client.get("/api/models")
        assert resp.status_code == 200
        data = resp.json()
        assert "models" in data
        assert isinstance(data["models"], list)
        assert len(data["models"]) > 0
        # No hidden models
        for m in data["models"]:
            assert "id" in m
            assert "label" in m

    @pytest.mark.asyncio
    async def test_chat_stream_returns_sse(self, make_agent_loop):
        from starlette.testclient import TestClient
        from lemonclaw.gateway.server import create_app

        loop, bus = make_agent_loop()
        app = create_app(auth_token=None, agent_loop=loop,
                         session_manager=loop.sessions, webui_enabled=True)
        client = TestClient(app)
        resp = client.post("/api/chat/stream", json={"message": "hello"})
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        # Should contain a done event
        assert '"type": "done"' in resp.text or '"type":"done"' in resp.text

    @pytest.mark.asyncio
    async def test_webui_disabled(self, make_agent_loop):
        from starlette.testclient import TestClient
        from lemonclaw.gateway.server import create_app

        loop, bus = make_agent_loop()
        app = create_app(auth_token=None, agent_loop=loop,
                         session_manager=loop.sessions, webui_enabled=False)
        client = TestClient(app)
        resp = client.get("/")
        # When webui disabled, / is not registered → 404 from Starlette
        assert resp.status_code in (404, 405)
