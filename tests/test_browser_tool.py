from __future__ import annotations

import asyncio

import pytest

from lemonclaw.agent.tools.browser import BrowserTool


class DummyProcess:
    def __init__(self, stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0):
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode
        self.killed = False

    async def communicate(self):
        return self._stdout, self._stderr

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> int:
        return self.returncode


@pytest.mark.asyncio
async def test_browser_blocks_non_http_scheme_without_allowlist() -> None:
    tool = BrowserTool()
    tool._cli_path = "/usr/bin/agent-browser"

    result = await tool.execute("open file:///etc/passwd")

    assert "scheme 'file'" in result


@pytest.mark.asyncio
async def test_browser_rejects_shell_redirection() -> None:
    tool = BrowserTool()
    tool._cli_path = "/usr/bin/agent-browser"

    result = await tool.execute("snapshot -i > page.txt")

    assert "not supported" in result.lower()


@pytest.mark.asyncio
async def test_browser_executes_chain_without_shell(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    calls: list[tuple[tuple, dict]] = []

    async def fake_exec(*args, **kwargs):
        calls.append((args, kwargs))
        output = b"" if len(calls) == 1 else b"snapshot output"
        return DummyProcess(stdout=output)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    tool = BrowserTool(
        session_name="lc-default",
        workspace=tmp_path,
    )
    tool._cli_path = "/usr/bin/agent-browser"

    result = await tool.execute("open https://example.com && snapshot -i", _session_key="webui:demo")

    assert result == "snapshot output"
    assert len(calls) == 2

    first_args = list(calls[0][0])
    second_args = list(calls[1][0])
    assert first_args[:2] == ["/usr/bin/agent-browser", "--session"]
    assert second_args[:2] == ["/usr/bin/agent-browser", "--session"]
    assert first_args[2] == second_args[2]
    assert first_args[-2:] == ["open", "https://example.com"]
    assert second_args[-2:] == ["snapshot", "-i"]
    assert "&&" not in first_args
    assert calls[0][1]["cwd"] == str(tmp_path)


@pytest.mark.asyncio
async def test_browser_allows_paths_outside_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    calls: list[tuple[tuple, dict]] = []

    async def fake_exec(*args, **kwargs):
        calls.append((args, kwargs))
        return DummyProcess(stdout=b"ok")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    tool = BrowserTool(workspace=tmp_path)
    tool._cli_path = "/usr/bin/agent-browser"

    result = await tool.execute("state save ../auth.json")

    assert result == "ok"
    assert calls[0][1]["cwd"] == str(tmp_path)


def test_browser_session_isolation_uses_session_key() -> None:
    tool = BrowserTool(session_name="lc-default")

    session_a = tool._resolve_session_name("webui:alpha")
    session_b = tool._resolve_session_name("webui:beta")

    assert session_a != session_b
    assert session_a.startswith("lc-default-")


@pytest.mark.asyncio
async def test_browser_cleanup_kills_process_on_timeout(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    class HangingProcess(DummyProcess):
        async def communicate(self):
            await asyncio.sleep(3600)

    process = HangingProcess()

    async def fake_exec(*args, **kwargs):
        return process

    monkeypatch.setattr(asyncio, 'create_subprocess_exec', fake_exec)

    tool = BrowserTool(workspace=tmp_path)
    tool._cli_path = '/usr/bin/agent-browser'
    tool._active_sessions.add('sess-1')

    await tool.cleanup()

    assert process.killed is True
    assert tool._active_sessions == set()


@pytest.mark.asyncio
async def test_browser_cleanup_releases_dicloak_leases_and_clears_state(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    class FakeResponse:
        def __init__(self, payload: dict, status_code: int = 200):
            self._payload = payload
            self.status_code = status_code
            self.text = str(payload)

        def json(self):
            return self._payload

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def patch(self, url, headers=None):
            close_urls.append(url)
            assert url.endswith("/close")
            return FakeResponse({"code": 0, "data": {}})

    calls: list[tuple[tuple, dict]] = []
    close_urls: list[str] = []

    async def fake_exec(*args, **kwargs):
        calls.append((args, kwargs))
        return DummyProcess(stdout=b"closed")

    monkeypatch.setattr("lemonclaw.agent.tools.browser.httpx.AsyncClient", lambda **kwargs: FakeClient())
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    tool = BrowserTool(workspace=tmp_path)
    tool._dicloak_enabled = True
    tool._dicloak_api_base_url = "http://127.0.0.1:52140/openapi"
    tool._dicloak_api_key = "dicloak-test"
    tool._cli_path = "/usr/bin/agent-browser"
    tool._dicloak_leases["lc-default"] = {
        "profile_id": "profile-9",
        "debug_port": 45500,
        "opened_at": "serial-1",
    }

    await tool.cleanup()

    assert any(list(call[0])[-1] == "close" for call in calls)
    assert any(url.endswith("/close") for url in close_urls)
    assert tool._dicloak_leases == {}
    assert tool._active_sessions == set()


@pytest.mark.asyncio
async def test_browser_dicloak_commands_fail_closed_when_not_enabled() -> None:
    tool = BrowserTool()

    result = await tool.execute("dicloak list_profiles")

    assert "not enabled" in result.lower()


@pytest.mark.asyncio
async def test_browser_dicloak_profile_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        def __init__(self, payload: dict, status_code: int = 200):
            self._payload = payload
            self.status_code = status_code
            self.text = str(payload)

        def json(self):
            return self._payload

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, params=None, headers=None):
            return FakeResponse({"code": 0, "data": {"list": [{"id": "p_1", "name": "Main"}]}})

        async def patch(self, url, headers=None):
            if url.endswith("/open"):
                return FakeResponse({"code": 0, "data": {"debug_port": 45500}})
            return FakeResponse({"code": 0, "data": {}})

    monkeypatch.setattr("lemonclaw.agent.tools.browser.httpx.AsyncClient", lambda **kwargs: FakeClient())
    calls: list[tuple[tuple, dict]] = []

    async def fake_exec(*args, **kwargs):
        calls.append((args, kwargs))
        return DummyProcess(stdout=b"connected")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    tool = BrowserTool()
    tool._dicloak_enabled = True
    tool._dicloak_api_base_url = "http://127.0.0.1:52140/openapi"
    tool._dicloak_api_key = "dicloak-test"
    tool._cli_path = "/usr/bin/agent-browser"

    listing = await tool.execute("dicloak list_profiles")
    opened = await tool.execute("dicloak open_profile p_1", _session_key="webui:dicloak")
    closed = await tool.execute("dicloak close_profile", _session_key="webui:dicloak")

    assert "p_1" in listing
    assert '"status": "opened"' in opened
    assert '"agent_browser": "connected"' in opened
    assert "closed: p_1" in closed
    assert any(list(call[0])[-2:] == ["connect", "45500"] for call in calls)
    assert any(list(call[0])[-1] == "close" for call in calls)


@pytest.mark.asyncio
async def test_browser_dicloak_open_profile_surfaces_kernel_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        def __init__(self, payload: dict, status_code: int = 200):
            self._payload = payload
            self.status_code = status_code
            self.text = str(payload)

        def json(self):
            return self._payload

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def patch(self, url, headers=None):
            assert url.endswith("/open")
            return FakeResponse({"code": 5000, "msg": "fail", "data": {"message": "BROWSER_NOT_INSTALL_2"}})

    monkeypatch.setattr("lemonclaw.agent.tools.browser.httpx.AsyncClient", lambda **kwargs: FakeClient())

    tool = BrowserTool()
    tool._dicloak_enabled = True
    tool._dicloak_api_base_url = "http://127.0.0.1:52140/openapi"
    tool._dicloak_api_key = "dicloak-test"
    tool._cli_path = "/usr/bin/agent-browser"

    result = await tool.execute("dicloak open_profile p_1", _session_key="webui:dicloak")

    assert "kernel is not installed" in result
    assert "BROWSER_NOT_INSTALL_2" in result
