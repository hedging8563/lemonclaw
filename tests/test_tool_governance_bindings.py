from lemonclaw.agent.tools.browser import BrowserTool
from lemonclaw.agent.tools.cron import CronTool
from lemonclaw.agent.tools.message import MessageTool
from lemonclaw.agent.tools.shell import ExecTool
from lemonclaw.agent.tools.spawn import SpawnTool


class _DummyCronService:
    def add_job(self, **kwargs):
        raise NotImplementedError

    def list_jobs(self):
        return []

    def remove_job(self, job_id):
        return False


class _DummySpawnManager:
    async def spawn(self, **kwargs):
        raise NotImplementedError


def test_exec_resolves_governance_capabilities():
    tool = ExecTool()
    assert tool.resolve_capability({"command": "ls -la"}) == "exec.read"
    assert tool.resolve_capability({"command": "curl https://example.com"}) == "exec.network"
    assert tool.resolve_capability({"command": 'bash -c "curl https://example.com"'}) == "exec.network"
    assert tool.resolve_capability({"command": "npm install"}) == "exec.package"
    assert tool.resolve_capability({"command": "sh -c 'npm install'"}) == "exec.package"
    assert tool.resolve_capability({"command": "systemctl restart nginx"}) == "exec.system"
    assert tool.resolve_capability({"command": "zsh -c 'systemctl restart nginx'"}) == "exec.system"
    assert tool.resolve_capability({"command": "mkdir build"}) == "exec.write"


def test_browser_resolves_governance_capabilities():
    tool = BrowserTool()
    assert tool.resolve_capability({"command": "open https://example.com"}) == "browser.read"
    assert tool.resolve_capability({"command": "click @e1"}) == "browser.interact"


def test_cron_message_and_spawn_resolve_governance_capabilities():
    cron = CronTool(_DummyCronService())
    message = MessageTool()
    spawn = SpawnTool(_DummySpawnManager())

    assert cron.resolve_capability({"action": "list"}) == "cron.read"
    assert cron.resolve_capability({"action": "add"}) == "cron.write"
    assert message.resolve_capability({"content": "hello"}) == "message.send"
    assert spawn.resolve_capability({"task": "Summarize logs"}) == "spawn.agent"
