from __future__ import annotations

import subprocess
from pathlib import Path

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


@pytest.mark.asyncio
async def test_git_push_to_local_remote(tmp_path):
    worktree = tmp_path / "repo"
    worktree.mkdir()
    _init_repo(worktree)
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)

    (worktree / "file.txt").write_text("hello", encoding="utf-8")
    subprocess.run(["git", "add", "file.txt"], cwd=worktree, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=worktree, check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=worktree, check=True, capture_output=True)
    branch = subprocess.run(["git", "branch", "--show-current"], cwd=worktree, check=True, capture_output=True, text=True).stdout.strip()

    tool = GitTool(working_dir=str(worktree))
    result = await tool.execute("push", remote="origin", target=branch)

    assert result["ok"] is True
    pushed = subprocess.run(["git", "--git-dir", str(remote), "log", "--oneline", "-1"], check=True, capture_output=True, text=True)
    assert "init" in pushed.stdout


@pytest.mark.asyncio
async def test_git_push_uses_auth_profile_without_putting_token_in_args(monkeypatch, tmp_path):
    _init_repo(tmp_path)
    tool = GitTool(
        working_dir=str(tmp_path),
        auth_profiles={"origin": {"username": "x-access-token", "password": "super-secret-token"}},
    )
    captured: dict[str, object] = {}

    async def _fake_run_action(*, cwd, action, args, stdin=None, env=None):
        del cwd, stdin
        if action == "remote_get_url":
            return {
                "ok": True,
                "summary": "git remote_get_url -> exit 0",
                "raw": {"stdout": "https://github.com/example/repo.git", "stderr": "", "exit_code": 0, "body": ""},
            }
        if action == "push":
            captured["args"] = args
            captured["env"] = env
            captured["askpass"] = env["GIT_ASKPASS"] if env else ""
            return {
                "ok": True,
                "summary": "git push -> exit 0",
                "raw": {"stdout": "ok", "stderr": "", "exit_code": 0, "body": "ok"},
            }
        raise AssertionError(f"unexpected action {action}")

    monkeypatch.setattr(tool, "_run_action", _fake_run_action)
    result = await tool.execute("push", remote="origin", target="main", auth_profile="origin")

    assert result["ok"] is True
    assert captured["env"]["LC_GIT_PASSWORD"] == "super-secret-token"
    assert "super-secret-token" not in " ".join(captured["args"])
    assert not Path(str(captured["askpass"])).exists()


def test_git_resolves_write_capability():
    tool = GitTool()
    assert tool.resolve_capability({"action": "status"}) == "git.read"
    assert tool.resolve_capability({"action": "commit"}) == "git.write.local"
    assert tool.resolve_capability({"action": "push"}) == "git.write.remote"


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
    token = runtime.issue_token(task_id="task_1", allowed_capabilities=["git.write.local"])
    decision = runtime.authorize(capability_id="git.write.local", tool_name="git", token=token, mode="operator")
    assert decision.capability.risk_level.value == "local_mutation"
