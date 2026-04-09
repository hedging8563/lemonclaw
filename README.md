<div align="center">
  <img src="assets/logo.svg" width="128" height="128" alt="LemonClaw Logo">
  <h1>LemonClaw</h1>
  <p>Open-source AI agent for self-hosted and K8s deployments</p>
  <p>
    <img src="https://img.shields.io/badge/python-≥3.11-blue" alt="Python">
    <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
  </p>
</div>

LemonClaw is a hard fork of [nanobot](https://github.com/HKUDS/nanobot) (MIT), rebuilt into a lightweight AI agent runtime with native MCP support, local tools, WebUI, and 12 IM channels. It ships well for dedicated self-hosted machines and K8s-style single-tenant deployments.

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
| `/runtime [inventory|mcp|health|recovery]` | Show bot-facing runtime, MCP, health, and recovery truth |
| `/tasks` | Show recent task and recovery hints in chat |
| `/resume [task_id]` | Execute the safest available resume action in chat |
| `/retry-outbox [task_id]` | Retry failed outbox delivery in chat when it is safe |
| `/recheck [task_id]` | Re-run completion/recovery checks in chat when it is safe |
| `/abandon [task_id]` | Abandon the latest active outbox event for a task in chat |
| `/export [task_id] [md|json]` | Render the full task export artifact in chat |
| `/bundle [task_id] [md|json]` | Show a compact summary or the full task bundle artifact in chat |
| `/postmortem [task_id] [md|json]` | Show a concise summary or the full postmortem artifact in chat |
| `/pairing status` | Show current pairing state in chat |
| `/pairing pending` | Show pending pairing requests in chat (owner only) |
| `/pairing transfer <user_id>` | Transfer owner role in chat (owner only) |
| `/pairing recovery-code [ttl_seconds]` | Issue a one-time owner recovery code directly from chat (owner only) |
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

Telegram, Discord, WhatsApp, Feishu, Slack, DingTalk, Email, QQ, Matrix, Mochat, WeCom (企业微信), Weixin (微信)

## Current Product Surface

The current LemonClaw product surface is centered on four areas:

- chat and session management in WebUI
- long-running task / recovery / operator workflows
- knowledge ingestion, retrieval, and long-term memory
- lightweight runtime governance and kill switch visibility

In the current WebUI inspector:

- `Notes` / `备忘录` holds time-based working notes: today notes, yesterday summary, and history
- `Knowledge` / `知识` holds durable, structured information: sources, search, detail, and long-term memory cards/rules
- `Tasks & Recovery` / `任务与恢复` is the operator-facing task lifecycle and outbox/recovery surface
- `Current Work` / `当前执行` summarizes conductor / plan / agent activity

This split is intentional:

- notes are timeline-oriented
- knowledge is long-term and searchable
- task recovery is operational state

LemonClaw now also repairs legacy WebUI task/tool-prelude history on startup so older sessions gradually stop showing duplicated draft text from tool runs.

Hosted control-plane surfaces now also expose the most important runtime-adjacent actions without turning Dashboard/Admin back into the main work surface:

- instance cards can show DICloak runtime status and Weixin connection state
- hosted Dashboard instance cards support Weixin QR connect, AgentBridge runtime credentials, and an "other channels" docs entry
- `/admin/claw` includes a unified debug drawer for instance summary, runtime state, Weixin/DICloak, and raw container logs

Recent runtime fixes worth knowing:

- session-level `current_model` now routes through the matching provider family instead of always reusing the startup provider
- malformed provider content blocks such as serialized `[{\"type\":\"text\",...}]` are normalized before they reach WebUI/session history
- channel configuration failures (for example an invalid Telegram token) no longer trigger watchdog-driven full instance restart loops

## WebUI Notes

The current WebUI is not just a chat shell. It includes:

- sessions, activity, operator queue, and triggers in the left sidebar
- a right-side inspector for notes, task recovery, current work, and knowledge
- knowledge source management with ingestion, pinning, search, detail, and retrieval previews
- knowledge governance controls for retrying failed ingests, ingesting pending sources, refreshing due sources, and reingesting all
- task export / bundle / postmortem surfaces for operator review and chat-native artifact rendering
- settings split into `Basic` / `Advanced`

`Basic` shows the settings most users actually change. `Advanced` adds budgets, timeouts, proxies, bridge settings, MCP, and shell/runtime controls.

Knowledge lifecycle states currently surfaced in WebUI:

- `registered` — source saved but not ingested yet
- `ingesting` — ingest job is running
- `ingested` — chunks/facts are available for retrieval
- `error` — the last ingest failed and needs review or retry

## Browser Modes

LemonClaw currently has one unified browser tool surface, but two runtime paths behind it:

- `agent-browser` is the default path for normal browsing, snapshots, clicks, forms, and screenshots
- `DICloak` is the optional enhanced path for leased profiles, persistent login state, and higher-friction browsing

Current bot guidance:

- use normal `browser open/snapshot/click/fill/...` commands for ordinary web tasks
- use DICloak only when the task explicitly needs a profile or persistent login state
- the expected DICloak flow is:
  - `dicloak list_profiles`
  - `dicloak open_profile <profile_id>`
  - normal browser commands in the same session
  - `dicloak close_profile`

When DICloak is unavailable, explicit DICloak commands fail closed. Ordinary browser tasks still continue to use `agent-browser`.
The current browser skill also tells the agent to direct the user back to hosted instance settings when DICloak is not enabled/configured.

## Single-Instance Swarm

LemonClaw now treats **single-instance swarm** as the next collaboration layer ahead of peer teams:

- conductor can attach swarm templates and role hints to subtasks
- WebUI surfaces can show active team / goal / role hints
- the current direction is still one instance = one work studio, with leader + specialist workers sharing the same session / ledger / recovery / knowledge substrate

## AgentBridge Runtime Truth

Hosted Dashboard only exposes an entry into the AgentBridge runtime, not a second control plane.

- AgentBridge uses a runtime-only bearer token, not an organization API key
- the canonical session key template is `agentbridge:<client_id>:<workspace_id>:<thread_id>`
- the primary interactive route is `POST /api/agentbridge/chat/stream`
- uploads, messages, events, media, and stop continue to share the same runtime session / ledger / recovery semantics as the main `AgentLoop`

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

Governance in LemonClaw is intentionally **observability-first**:

- capability execution is observable and auditable
- kill switch and capability metadata remain available for operators, but are not the primary execution boundary in Full-Power mode
- secret / sandbox profiles are policy metadata and observability context
- missing sandbox / secret bindings warn and audit; they do not block the default full-power loop

LemonClaw is not designed to turn every high-risk action into a mandatory manual approval flow by default.

If you run LemonClaw on a machine that also contains unrelated sensitive data, assume the agent may reach that local data.

## Configuration Notes

Config file: `~/.lemonclaw/config.json`

Default chat model:

- `gpt-5.4`

Default LemonData provider names used by the setup wizard:

- `lemondata` — OpenAI-compatible (`/v1`)
- `lemondata_response` — OpenAI Responses API (`/v1`), used by the `gpt-5.4` family by default
- `lemondata_claude` — Anthropic-compatible
- `lemondata_minimax` — MiniMax native / Anthropic-compatible
- `lemondata_gemini` — Gemini native format

Current routing defaults:

- `gpt-5.4` / `gpt-5.4-pro` default to `lemondata_response`
- platform-managed LemonData providers expose grouped configuration in WebUI settings

Session model notes:

- `agents.defaults.model` controls the default model for new sessions and new default WebUI entrypoints
- session `current_model` is still a per-conversation override
- when an old default WebUI session is still pinned to another family (for example `claude-sonnet-4-6`), the safe migration pattern is:
  - archive the old `webui:default`
  - create a fresh `webui:default` using the current default model
  - keep the archived session intact instead of rewriting its model in place

## Docker / K8s

- single-container local build: `Dockerfile`
- local compose example: `docker-compose.yml`
- K8s deployment should be integrated through your own manifests / deployment repo

For the LemonData runtime workflow used in this repository, the release/deploy entry point is:

```bash
./deploy/k3s/claw/lemonclaw-runtime/build-and-deploy.sh
```

Typical contributor flow:

- build from local LemonClaw source
- publish a version record
- deploy one instance with `--deploy claw-<name>` or all managed instances with `--deploy-all`

Operational notes from the current LemonData fleet workflow:

- `--deploy-all` still prompts for confirmation unless you set `FORCE=1`
- if build/publish already succeeded and rollout was interrupted, you can resume safely by reusing the published digest instead of rebuilding
- current targeted-rollout practice is to roll one designated production instance before a fleet-wide reconcile; `test3` is now treated as a formal production instance, not a canary-only environment

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
