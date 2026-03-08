<div align="center">
  <img src="assets/logo.svg" width="128" height="128" alt="LemonClaw Logo">
  <h1>LemonClaw</h1>
  <p>Open-source AI agent for self-hosted and K8s deployments</p>
  <p>
    <img src="https://img.shields.io/badge/python-≥3.11-blue" alt="Python">
    <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
  </p>
</div>

LemonClaw is a hard fork of [nanobot](https://github.com/HKUDS/nanobot) (MIT), rebuilt into a lightweight AI agent runtime with native MCP support, local tools, WebUI, and 10 IM channels. It ships well for dedicated self-hosted machines and K8s-style single-tenant deployments.

## Quick Start

### One-line self-hosted install

```bash
curl -fsSL https://raw.githubusercontent.com/hedging8563/lemonclaw/main/deploy/self-hosted/install.sh | bash
```

The installer will:

- reuse Python `>=3.11` if present, otherwise try to install it
- prefer `uv tool install` when `uv` is available
- otherwise install into an isolated venv under `~/.local/share/lemonclaw/venv`
- run `lemonclaw init` at the end

### Manual install

```bash
# Option A: uv
uv tool install --upgrade lemonclaw

# Option B: pip user install
python3 -m pip install --user --upgrade lemonclaw

# Then run the setup wizard
lemonclaw init
```

### Install from source

```bash
git clone https://github.com/hedging8563/lemonclaw.git
cd lemonclaw
python3 -m pip install -e .
lemonclaw init
```

## Self-Hosted in 3 Steps

```bash
lemonclaw init      # interactive setup wizard
lemonclaw gateway   # start the gateway
lemonclaw status    # inspect runtime status
```

Generated runtime data lives under:

- config: `~/.lemonclaw/config.json`
- workspace: `~/.lemonclaw/workspace/`
- sessions: `~/.lemonclaw/workspace/sessions/`
- logs: `~/.lemonclaw/lemonclaw.log`

## Common Commands

| Command | Description |
|---------|-------------|
| `lemonclaw init` | Interactive setup wizard |
| `lemonclaw gateway` | Start gateway server |
| `lemonclaw agent` | Interactive chat mode |
| `lemonclaw agent -m "..."` | Single message mode |
| `lemonclaw doctor` | Pre-flight diagnostics |
| `lemonclaw doctor --fix` | Auto-fix common issues |
| `lemonclaw status` | Show runtime status |
| `lemonclaw cron add/list/remove` | Scheduled tasks |
| `lemonclaw channels login` | Link WhatsApp (QR scan) |
| `lemonclaw channels status` | Show channel status |
| `lemonclaw provider login <name>` | OAuth login for providers |

## Service Management

### macOS (`launchd`)

```bash
launchctl start cc.lemondata.lemonclaw
launchctl stop cc.lemondata.lemonclaw
launchctl kickstart -k gui/$(id -u)/cc.lemondata.lemonclaw
```

### Linux (`systemd --user`)

```bash
systemctl --user start lemonclaw
systemctl --user stop lemonclaw
systemctl --user restart lemonclaw
systemctl --user status lemonclaw
```

The `init` wizard will create these service definitions for you.

## Supported Channels

Telegram, Discord, WhatsApp, Feishu, Slack, DingTalk, Email, QQ, Matrix, Mochat, WeCom (企业微信)

## Architecture

```text
User Message → Channel (Telegram/Discord/...) → Message Bus → Agent Loop → LLM Provider → Tool Execution → Response
                                                     ↑                          ↑
                                              Session Manager            MCP / provider routing
                                              + Compaction
```

## Full-Power Local Tools

LemonClaw is designed for dedicated deployments.

- local tools are treated as **full-power** within the current machine / container boundary
- `workspace` is the default working directory, not a hard sandbox boundary
- for K8s deployments, the real security boundary is the Pod / container / host configuration

If you run LemonClaw on a machine that also contains unrelated sensitive data, assume the agent may reach that local data.

## Configuration Notes

Config file: `~/.lemonclaw/config.json`

Default LemonData provider names used by the setup wizard:

- `lemondata` — OpenAI-compatible (`/v1`)
- `lemondata_claude` — Anthropic-compatible
- `lemondata_minimax` — MiniMax native / Anthropic-compatible
- `lemondata_gemini` — Gemini native format

## Docker / K8s

- single-container local build: `Dockerfile`
- local compose example: `docker-compose.yml`
- K8s deployment should be integrated through your own manifests / deployment repo

## Repository Layout

```text
lemonclaw/
├── agent/        # Core agent loop, tools, context, memory, subagent
├── bus/          # Message bus
├── channels/     # IM channel integrations
├── cli/          # CLI commands
├── config/       # Config schema, loader, defaults, sync
├── gateway/      # HTTP gateway + WebUI
├── providers/    # LLM providers
├── session/      # Session manager + compaction
├── skills/       # Built-in skills
├── watchdog/     # Health monitoring
├── conductor/    # Multi-agent orchestration
├── telemetry/    # Usage tracking
└── memory/       # Memory system
```

## Upgrade

```bash
# uv install
uv tool install --upgrade lemonclaw

# pip install
python3 -m pip install --user --upgrade lemonclaw
```

If you used the one-line installer without `uv`, rerun the installer to refresh the isolated venv.

## License

MIT — forked from [nanobot](https://github.com/HKUDS/nanobot) by HKUDS.
