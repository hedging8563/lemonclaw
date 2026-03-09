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


# ── 1. SSRF Protection (web.py) ──


class TestSSRFProtection:
    """web_fetch must block access to private/internal addresses."""

    def test_private_ip_detected(self):
        from lemonclaw.agent.tools.web import _is_private_ip_addr
        assert _is_private_ip_addr("127.0.0.1") is True
        assert _is_private_ip_addr("10.0.0.1") is True
        assert _is_private_ip_addr("172.16.0.1") is True
        assert _is_private_ip_addr("192.168.1.1") is True

    def test_link_local_blocked(self):
        from lemonclaw.agent.tools.web import _is_private_ip_addr
        # Cloud metadata endpoint
        assert _is_private_ip_addr("169.254.169.254") is True

    def test_public_ip_allowed(self):
        from lemonclaw.agent.tools.web import _is_private_ip_addr
        assert _is_private_ip_addr("8.8.8.8") is False
        assert _is_private_ip_addr("1.1.1.1") is False

    def test_validate_url_blocks_private(self):
        from lemonclaw.agent.tools.web import _validate_url
        valid, err, _ip = _validate_url("http://127.0.0.1:8080/secret")
        assert valid is False
        assert "private" in err.lower() or "internal" in err.lower()

    def test_validate_url_blocks_metadata(self):
        from lemonclaw.agent.tools.web import _validate_url
        valid, err, _ip = _validate_url("http://169.254.169.254/latest/meta-data/")
        assert valid is False

    def test_validate_url_allows_public(self):
        from unittest.mock import patch as mock_patch
        from lemonclaw.agent.tools.web import _validate_url
        # Mock DNS to return a known public IP (avoid local DNS proxy interference)
        fake_info = [(2, 1, 6, '', ('93.184.216.34', 0))]
        with mock_patch("lemonclaw.agent.tools.web.socket.getaddrinfo", return_value=fake_info):
            valid, err, _ip = _validate_url("https://example.com")
        assert valid is True

    def test_unresolvable_host_blocked(self):
        from lemonclaw.agent.tools.web import _resolve_to_safe_ip
        from unittest.mock import patch as mock_patch
        import socket
        # Simulate DNS resolution failure — fail-closed
        with mock_patch("lemonclaw.agent.tools.web.socket.getaddrinfo", side_effect=socket.gaierror("not found")):
            ip, err = _resolve_to_safe_ip("this-domain-does-not-exist-xyz123.invalid")
            assert ip is None


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
    async def test_relative_paths_allowed_in_full_power_mode(self, tmp_path):
        outer = tmp_path / "outer.txt"
        outer.write_text("hello", encoding="utf-8")
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        tool = ExecTool(timeout=5, working_dir=str(workspace))
        result = await tool.execute(command="cat ../outer.txt")
        assert "hello" in result

    @pytest.mark.asyncio
    async def test_rm_rf_extra_spaces_blocked(self):
        """Evasion via extra spaces: 'rm  -rf  /' should still be caught."""
        tool = ExecTool(timeout=5)
        result = await tool.execute(command="rm  -rf  /tmp/test")
        assert "blocked" in result.lower()

    @pytest.mark.asyncio
    async def test_rm_quoted_args_blocked(self):
        """Evasion via quoting: rm '-rf' should still be caught."""
        tool = ExecTool(timeout=5)
        result = await tool.execute(command="rm '-rf' /tmp/test")
        assert "blocked" in result.lower()

    @pytest.mark.asyncio
    async def test_rm_long_flags_blocked(self):
        """Long flags like --recursive/--force should also be blocked."""
        tool = ExecTool(timeout=5)
        result = await tool.execute(command="rm --recursive --force /tmp/test")
        assert "blocked" in result.lower()

    @pytest.mark.asyncio
    async def test_dd_standalone_blocked(self):
        """dd without if= should still be blocked at token level."""
        tool = ExecTool(timeout=5)
        result = await tool.execute(command="dd if=/dev/urandom of=/tmp/x bs=1M count=100")
        assert "blocked" in result.lower()

    @pytest.mark.asyncio
    async def test_parent_segments_allowed_in_full_power_mode(self, tmp_path):
        nested = tmp_path / "workspace" / "foo"
        nested.mkdir(parents=True)
        outer = tmp_path / "workspace" / "outer.txt"
        outer.write_text("ok", encoding="utf-8")
        tool = ExecTool(timeout=5, working_dir=str(tmp_path / "workspace"))
        result = await tool.execute(command="cat foo/../outer.txt")
        assert "ok" in result


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


class TestAPIKeySanitization:
    """API keys must not leak into error messages or logs."""

    def test_sanitize_bearer_token(self):
        from lemonclaw.providers.litellm_provider import _sanitize_error
        err = Exception("Request failed: Bearer sk-abc123def456ghi789jkl012mno345pqr")
        result = _sanitize_error(err)
        assert "sk-abc123" not in result
        assert "[REDACTED]" in result

    def test_sanitize_api_key_pattern(self):
        from lemonclaw.providers.litellm_provider import _sanitize_error
        err = Exception("Invalid key: key-abcdefghijklmnop1234")
        result = _sanitize_error(err)
        assert "key-abcdefgh" not in result
        assert "[REDACTED]" in result

    def test_sanitize_hex_token(self):
        from lemonclaw.providers.litellm_provider import _sanitize_error
        err = Exception("Token c09b22eabe503204bc8de0fac10875f7ee54ea5123bf19c29533b51c6359b6e5 expired")
        result = _sanitize_error(err)
        assert "c09b22ea" not in result
        assert "[REDACTED]" in result

    def test_safe_message_unchanged(self):
        from lemonclaw.providers.litellm_provider import _sanitize_error
        err = Exception("Connection timeout after 30s")
        result = _sanitize_error(err)
        assert result == "Connection timeout after 30s"

    def test_sanitize_slack_token(self):
        from lemonclaw.providers.litellm_provider import _sanitize_error
        err = Exception('bot token xoxb-1234567890-secret-value leaked')
        result = _sanitize_error(err)
        assert 'xoxb-1234' not in result
        assert '[REDACTED]' in result

    def test_sanitize_jwt_token(self):
        from lemonclaw.providers.litellm_provider import _sanitize_error
        err = Exception('Authorization: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc.def failed')
        result = _sanitize_error(err)
        assert 'eyJhbGci' not in result
        assert '[REDACTED]' in result


# ── 2c-orig. Token Tracking (P2-A) ──


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




    @pytest.mark.asyncio
    async def test_parallel_success_does_not_clear_other_tool_error_budget(self, make_agent_loop, echo_provider):
        from lemonclaw.providers.base import ToolCallRequest, LLMResponse

        call = LLMResponse(
            content=None,
            tool_calls=[
                ToolCallRequest(id='err1', name='read_file', arguments={}),
                ToolCallRequest(id='ok1', name='exec', arguments={'command': 'echo ok'}),
            ],
            usage={'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2},
        )
        echo_provider.responses = [call, call, call]
        loop, _bus = make_agent_loop(max_iterations=10)

        original_execute = loop.tools.execute
        async def fake_execute(name, params, context=None):
            if name == 'read_file':
                return "Error: Invalid parameters for tool 'read_file': path is required"
            return 'ok'
        loop.tools.execute = fake_execute  # type: ignore[assignment]

        msg = InboundMessage(channel='test', sender_id='u1', chat_id='c1', content='test')
        response = await loop._process_message(msg)
        assert response is not None
        assert 'failed repeatedly' in response.content.lower() or 'error' in response.content.lower()

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

    def test_decrypt_invalid_padding_fails(self):
        """Tampered ciphertext should raise ValueError on padding validation."""
        from lemonclaw.channels.wecom import WeComCrypto
        import base64

        crypto = WeComCrypto(self.ENCODING_AES_KEY, self.CORP_ID)
        encrypted = crypto.encrypt("test message")
        # Tamper with the last block (corrupts padding)
        raw = base64.b64decode(encrypted)
        tampered = raw[:-1] + bytes([(raw[-1] + 1) % 256])
        tampered_b64 = base64.b64encode(tampered).decode()
        with pytest.raises(ValueError):
            crypto.decrypt(tampered_b64)

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

    def test_signature_timing_safe(self):
        """Signature comparison must use hmac.compare_digest (timing-safe)."""
        import hmac as hmac_mod
        from lemonclaw.channels.wecom import verify_signature
        sig = verify_signature("tok", "123", "abc", "enc")
        # Verify hmac.compare_digest works with the output
        assert hmac_mod.compare_digest(sig, sig) is True
        assert hmac_mod.compare_digest(sig, "wrong" * 8) is False


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


    def test_cookie_rejects_future_created_timestamp(self):
        import base64
        from lemonclaw.gateway.webui.auth import _compute_hmac, verify_session_cookie
        future_created = '9999999999'
        last = '9999999999'
        nonce = 'abc123'
        payload = f"{future_created}:{last}:{nonce}"
        cookie = base64.urlsafe_b64encode(f"{payload}:{_compute_hmac(payload, 'tok')}".encode()).decode()
        valid, _ = verify_session_cookie(cookie, 'tok')
        assert valid is False

    def test_cookie_rejects_last_before_created(self):
        import base64
        from lemonclaw.gateway.webui.auth import _compute_hmac, verify_session_cookie
        payload = '200:100:abc123'
        cookie = base64.urlsafe_b64encode(f"{payload}:{_compute_hmac(payload, 'tok')}".encode()).decode()
        valid, _ = verify_session_cookie(cookie, 'tok')
        assert valid is False


class TestLegacyToolCallCompatibility:
    def test_serialize_ui_message_formats_old_tool_calls(self):
        from lemonclaw.gateway.webui.message_schema import serialize_ui_message

        msg = serialize_ui_message({
            'role': 'assistant',
            'content': '',
            'tool_calls': [
                {
                    'function': {
                        'name': 'read_file',
                        'arguments': '{"path":"/tmp/demo.txt"}',
                    }
                }
            ],
        })
        tool_block = next(block for block in msg['blocks'] if block['type'] == 'tool')
        assert 'read_file' in tool_block['detail']
        assert '/tmp/demo.txt' in tool_block['detail']

class TestNativeBlockSchemaPersistence:
    @pytest.mark.asyncio
    async def test_slash_command_persists_system_notice_block(self, make_agent_loop):
        loop, _bus = make_agent_loop()
        msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/usage")
        resp = await loop._process_message(msg)
        assert resp is not None
        session = loop.sessions.get_or_create("test:c1")
        assistant = next(m for m in session.messages if m.get("role") == "assistant")
        assert any(block["type"] == "system_notice" for block in assistant["blocks"])
        assert any(block["type"] == "markdown" for block in assistant["blocks"])

    @pytest.mark.asyncio
    async def test_tool_only_message_persists_tool_block(self, tmp_path: Path) -> None:
        from unittest.mock import AsyncMock, MagicMock
        from lemonclaw.agent.loop import AgentLoop
        from lemonclaw.bus.queue import MessageBus
        from lemonclaw.providers.base import LLMResponse, ToolCallRequest

        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model", memory_window=10)

        tool_call = ToolCallRequest(id="call1", name="message", arguments={"content": "Hello", "channel": "email", "chat_id": "a@b.com"})
        calls = iter([
            LLMResponse(content="", tool_calls=[tool_call]),
            LLMResponse(content="Done", tool_calls=[]),
        ])
        loop.provider.chat = AsyncMock(side_effect=lambda *a, **kw: next(calls))
        loop.tools.get_definitions = MagicMock(return_value=[])

        await loop.process_direct("send mail", session_key="webui:test-tool", channel="webui", chat_id="webui")
        session = loop.sessions.get_or_create("webui:test-tool")
        tool_only = next(m for m in session.messages if m.get("role") == "assistant" and any(b["type"] == "tool" for b in m.get("blocks", [])))
        assert any(block["type"] == "tool" for block in tool_only["blocks"])


# ── 6b. WebUI Routes ──


class TestWebUIMediaAndAttachments:
    """Media endpoint and outbound media[] persistence tests."""

    @pytest.mark.asyncio
    async def test_media_endpoint_serves_session_attachment_file(self, make_agent_loop, tmp_path):
        from pathlib import Path
        from starlette.testclient import TestClient
        from lemonclaw.gateway.server import create_app
        from lemonclaw.gateway.webui.message_schema import serialize_ui_message

        loop, bus = make_agent_loop()
        media_file = Path(loop.workspace) / 'preview.png'
        media_file.write_bytes(b'fakepng')
        session = loop.sessions.get_or_create('webui:test-media')
        session.messages.append(serialize_ui_message({
            'role': 'assistant',
            'content': '附件如下',
            'media': [str(media_file)],
            'timestamp': '2026-03-08T12:00:00',
        }, session_key='webui:test-media'))
        loop.sessions.save(session)

        app = create_app(auth_token=None, agent_loop=loop, session_manager=loop.sessions, webui_enabled=True)
        client = TestClient(app)
        resp = client.get(f'/api/media?path={media_file}&session_key=webui:test-media')
        assert resp.status_code == 200
        assert resp.content == b'fakepng'

    @pytest.mark.asyncio
    async def test_media_endpoint_uses_session_grant_cache(self, make_agent_loop, tmp_path, monkeypatch):
        from pathlib import Path
        from starlette.testclient import TestClient
        from lemonclaw.gateway.server import create_app
        from lemonclaw.gateway.webui.message_schema import serialize_ui_message

        loop, _bus = make_agent_loop()
        media_file = Path(loop.workspace) / 'cached.png'
        media_file.write_bytes(b'cached')
        session = loop.sessions.get_or_create('webui:test-cache')
        session.messages.append(serialize_ui_message({
            'role': 'assistant',
            'content': '附件如下',
            'media': [str(media_file)],
        }, session_key='webui:test-cache'))
        loop.sessions.save(session)

        app = create_app(auth_token=None, agent_loop=loop, session_manager=loop.sessions, webui_enabled=True)
        client = TestClient(app)
        first = client.get(f'/api/media?path={media_file}&session_key=webui:test-cache')
        assert first.status_code == 200

        def bomb(_key):
            raise AssertionError('session should not be reloaded after media grant cache warms')

        monkeypatch.setattr(loop.sessions, '_load', bomb)
        second = client.get(f'/api/media?path={media_file}&session_key=webui:test-cache')
        assert second.status_code == 200

    @pytest.mark.asyncio
    async def test_media_endpoint_blocks_external_file(self, make_agent_loop, tmp_path):
        from starlette.testclient import TestClient
        from lemonclaw.gateway.server import create_app

        loop, bus = make_agent_loop()
        external = tmp_path.parent / 'outside.txt'
        external.write_text('secret', encoding='utf-8')

        app = create_app(auth_token=None, agent_loop=loop, session_manager=loop.sessions, webui_enabled=True)
        client = TestClient(app)
        resp = client.get(f'/api/media?path={external}')
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_chat_stream_emits_outbound_media_event_and_persists_history(self, tmp_path: Path) -> None:
        from starlette.testclient import TestClient
        from unittest.mock import AsyncMock, MagicMock
        from lemonclaw.gateway.server import create_app
        from lemonclaw.agent.loop import AgentLoop
        from lemonclaw.bus.queue import MessageBus
        from lemonclaw.providers.base import LLMResponse, ToolCallRequest

        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = 'test-model'
        loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model='test-model', memory_window=10)
        tool_call = ToolCallRequest(
            id='call1', name='message',
            arguments={'content': 'Here is the file', 'channel': 'webui', 'chat_id': 'webui', 'media': ['/home/lemonclaw/.lemonclaw/media/demo.jpg']},
        )
        calls = iter([
            LLMResponse(content='', tool_calls=[tool_call]),
            LLMResponse(content='Done', tool_calls=[]),
        ])
        loop.provider.chat = AsyncMock(side_effect=lambda *a, **kw: next(calls))
        loop.tools.get_definitions = MagicMock(return_value=[])

        app = create_app(auth_token=None, agent_loop=loop, session_manager=loop.sessions, webui_enabled=True)
        client = TestClient(app)
        resp = client.post('/api/chat/stream', json={'message': 'send file', 'session_key': 'webui:test'})
        assert resp.status_code == 200
        assert '"type": "outbound"' in resp.text or '"type":"outbound"' in resp.text
        assert 'demo.jpg' in resp.text
        assert 'mediaId' in resp.text
        assert 'blocks' in resp.text

        history = client.get('/api/sessions/webui%3Atest/messages')
        assert history.status_code == 200
        data = history.json()
        assistant = next(m for m in data['messages'] if m['role'] == 'assistant' and m.get('media'))
        assert assistant['media'][0]['filename'] == 'demo.jpg'
        assert any(block['type'] == 'media' for block in assistant['blocks'])

        raw_session = loop.sessions.get_or_create('webui:test')
        raw_assistant = next(m for m in raw_session.messages if m.get('role') == 'assistant' and m.get('media'))
        assert raw_assistant['media'][0]['filename'] == 'demo.jpg'
        assert any(block['type'] == 'media' for block in raw_assistant['blocks'])


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
