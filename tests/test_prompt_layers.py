from pathlib import Path

from lemonclaw.agent.context import ContextBuilder


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
