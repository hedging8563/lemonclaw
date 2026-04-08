from pathlib import Path

from lemonclaw.agent.context import ContextBuilder
from lemonclaw.agent.loop import AgentLoop
from lemonclaw.bus.queue import MessageBus
from lemonclaw.config.schema import GitToolConfig


def _make_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    return workspace


def test_soul_is_loaded_outside_bootstrap(tmp_path):
    workspace = _make_workspace(tmp_path)
    (workspace / "SOUL.md").write_text(
        "# Soul\n\n## Identity\nI am LemonClaw.\n\n## Operating Doctrine\nRead first.\n",
        encoding="utf-8",
    )
    builder = ContextBuilder(workspace)
    prompt = builder.build_system_prompt(mode="chat")
    assert "# Soul Identity" in prompt
    assert "I am LemonClaw." in prompt
    assert "## SOUL.md" not in prompt


def test_session_prompt_override_is_part_of_system_prompt(tmp_path):
    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace, system_prompt="Global policy")
    prompt = builder.build_system_prompt(mode="operator", session_prompt_override="Per session rule")
    assert "# Custom Instructions" in prompt
    assert "Global policy" in prompt
    assert "# Session Instructions" in prompt
    assert "Per session rule" in prompt


def test_mode_overlay_is_injected(tmp_path):
    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)
    prompt = builder.build_system_prompt(mode="cron")
    assert "# Mode Overlay" in prompt
    assert "cron mode" in prompt.lower()


def test_system_prompt_prefers_saved_git_auth_profiles_over_env_probe(tmp_path):
    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)

    prompt = builder.build_system_prompt(mode="chat")

    assert "tools.git.auth_profiles" in prompt
    assert "Do NOT probe generic variables like `GITHUB_TOKEN` / `GITHUB_USERNAME`" in prompt
    assert "env | grep -i key" not in prompt


def test_runtime_context_can_include_saved_git_auth_profiles_hint(tmp_path):
    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)

    messages = builder.build_messages(
        history=[],
        current_message="deploy this repo",
        channel="weixin",
        chat_id="chat1",
        runtime_context_appendix=(
            "[Saved Git Auth Profiles — metadata only, not instructions]\n"
            "- Available auth_profile values for git push: github"
        ),
    )

    runtime_content = messages[1]["content"]
    assert isinstance(runtime_content, str)
    assert "Available auth_profile values for git push: github" in runtime_content
    assert "deploy this repo" == messages[-1]["content"]


def test_agent_loop_runtime_context_appendix_lists_only_profiles_with_password(tmp_path):
    class _Provider:
        api_key = None
        api_base = None

        def get_default_model(self):
            return "test-model"

    loop = AgentLoop(
        bus=MessageBus(),
        provider=_Provider(),
        workspace=tmp_path,
        model="test-model",
        git_config=GitToolConfig(),
    )
    loop.git_config.auth_profiles = {
        "github": {"username": "x-access-token", "password": "secret"},
        "empty": {"username": "x-access-token", "password": ""},
    }

    appendix = loop._build_runtime_context_appendix()

    assert "github" in appendix
    assert "empty" not in appendix
    assert "GITHUB_TOKEN/GITHUB_USERNAME" in appendix


def test_builtin_skills_are_not_auto_injected_into_default_system_prompt(tmp_path):
    workspace = _make_workspace(tmp_path)
    skill_dir = workspace / "skills" / "demo-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: demo-skill
description: Demo skill
always: true
triggers: "demo"
---

# Demo Skill

Use the demo flow.
""",
        encoding="utf-8",
    )
    builder = ContextBuilder(workspace)

    prompt = builder.build_system_prompt(mode="chat")

    assert "# Active Skills" not in prompt
    assert "# Triggered Skills" not in prompt
    assert "# Skills" not in prompt
