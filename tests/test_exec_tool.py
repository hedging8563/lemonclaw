from __future__ import annotations

import pytest

from lemonclaw.agent.tools.shell import ExecTool


@pytest.mark.asyncio
async def test_exec_supports_shell_pipeline() -> None:
    tool = ExecTool(timeout=5)

    result = await tool.execute("printf hello | cat")

    assert "hello" in result


@pytest.mark.asyncio
async def test_exec_supports_shell_redirection(tmp_path) -> None:
    tool = ExecTool(timeout=5, working_dir=str(tmp_path))

    result = await tool.execute("echo hello > out.txt")

    assert result == "(no output)"
    assert (tmp_path / "out.txt").read_text().strip() == "hello"


@pytest.mark.asyncio
async def test_exec_allows_cd_builtin() -> None:
    tool = ExecTool(timeout=5)

    result = await tool.execute("cd /tmp && pwd")

    assert "/tmp" in result


@pytest.mark.asyncio
async def test_exec_honors_working_dir_parameter(tmp_path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    tool = ExecTool(timeout=5, working_dir=str(tmp_path))

    result = await tool.execute("pwd", working_dir="nested")

    assert str(nested) in result
