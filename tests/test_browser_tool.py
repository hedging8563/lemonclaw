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
        restrict_to_workspace=True,
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
async def test_browser_blocks_paths_outside_workspace(tmp_path) -> None:
    tool = BrowserTool(workspace=tmp_path, restrict_to_workspace=True)
    tool._cli_path = "/usr/bin/agent-browser"

    result = await tool.execute("state save ../auth.json")

    assert "outside the workspace" in result


def test_browser_session_isolation_uses_session_key() -> None:
    tool = BrowserTool(session_name="lc-default")

    session_a = tool._resolve_session_name("webui:alpha")
    session_b = tool._resolve_session_name("webui:beta")

    assert session_a != session_b
    assert session_a.startswith("lc-default-")
