from __future__ import annotations

import pytest

from lemonclaw.agent.tools.shell import ExecTool


@pytest.mark.asyncio
async def test_exec_blocks_shell_pipeline() -> None:
    tool = ExecTool(timeout=5)

    result = await tool.execute("printf hello | cat")

    assert "shell operators are not supported" in result.lower()


@pytest.mark.asyncio
async def test_exec_blocks_shell_redirection() -> None:
    tool = ExecTool(timeout=5)

    result = await tool.execute("echo hello > out.txt")

    assert "shell operators are not supported" in result.lower()


@pytest.mark.asyncio
async def test_exec_rejects_cd_builtin() -> None:
    tool = ExecTool(timeout=5)

    result = await tool.execute("cd /tmp")

    assert "working_dir" in result


@pytest.mark.asyncio
async def test_exec_honors_working_dir_parameter(tmp_path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    tool = ExecTool(timeout=5, working_dir=str(tmp_path), restrict_to_workspace=True)

    result = await tool.execute("pwd", working_dir="nested")

    assert str(nested) in result
