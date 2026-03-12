from __future__ import annotations

import subprocess

import pytest

from lemonclaw.agent.tools.git_tool import GitTool
from lemonclaw.governance.runtime import GovernanceRuntime


def _init_repo(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True, capture_output=True)


@pytest.mark.asyncio
async def test_git_status_reports_changes(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "file.txt").write_text("hello", encoding="utf-8")
    tool = GitTool(working_dir=str(tmp_path))
    result = await tool.execute("status")
    assert result["ok"] is True
    assert "file.txt" in result["raw"]["body"]


@pytest.mark.asyncio
async def test_git_log_returns_recent_commits(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "file.txt").write_text("hello", encoding="utf-8")
    subprocess.run(["git", "add", "file.txt"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)

    tool = GitTool(working_dir=str(tmp_path))
    result = await tool.execute("log", limit=5)
    assert result["ok"] is True
    assert "init" in result["raw"]["stdout"]


@pytest.mark.asyncio
async def test_git_branch_current(tmp_path):
    _init_repo(tmp_path)
    tool = GitTool(working_dir=str(tmp_path))
    result = await tool.execute("branch", target="current")
    assert result["ok"] is True


@pytest.mark.asyncio
async def test_git_commit_stages_paths_and_commits(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "file.txt").write_text("hello", encoding="utf-8")
    tool = GitTool(working_dir=str(tmp_path))

    result = await tool.execute("commit", message="add file", paths=["file.txt"])

    assert result["ok"] is True
    log = subprocess.run(["git", "log", "--oneline", "-1"], cwd=tmp_path, check=True, capture_output=True, text=True)
    assert "add file" in log.stdout


@pytest.mark.asyncio
async def test_git_apply_patch_updates_file(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "file.txt").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "file.txt"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)

    patch = """--- a/file.txt
+++ b/file.txt
@@ -1 +1 @@
-hello
+world
"""
    tool = GitTool(working_dir=str(tmp_path))
    result = await tool.execute("apply_patch", patch=patch)

    assert result["ok"] is True
    assert (tmp_path / "file.txt").read_text(encoding="utf-8") == "world\n"


def test_git_resolves_write_capability():
    tool = GitTool()
    assert tool.resolve_capability({"action": "status"}) == "git.read"
    assert tool.resolve_capability({"action": "commit"}) == "git.write.local"


def test_governance_marks_git_write_local_as_local_mutation(tmp_path):
    cfg = type("Cfg", (), {
        "enabled": True,
        "default_autonomy_cap": "L1",
        "token_ttl_seconds": 60,
        "kill_switch_file": str(tmp_path / "governance.json"),
        "audit_log_path": str(tmp_path / "audit.jsonl"),
        "budgets": type("Budgets", (), {"default_task_usd": None})(),
        "capability_overrides": {},
    })()
    runtime = GovernanceRuntime(workspace=tmp_path, config=cfg, agent_id="default")
    token = runtime.issue_token(task_id="task_1")
    decision = runtime.authorize(capability_id="git.write.local", tool_name="git", token=token, mode="operator")
    assert decision.capability.risk_level.value == "local_mutation"
