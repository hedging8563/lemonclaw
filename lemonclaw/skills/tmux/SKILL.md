---
name: tmux
description: Drive interactive terminal sessions with tmux. Use when the task requires a persistent TTY, interactive CLI control, or pane output polling.
metadata: {"lemonclaw":{"emoji":"🧵","pattern":"tool-wrapper","os":["darwin","linux"],"requires":{"bins":["tmux"]}}}
triggers: "tmux,终端会话,terminal session,分屏,split pane,attach,session,pane,多窗口终端,interactive tty"
---

# tmux

This is a `tool-wrapper` skill.

## Entry Rule

Use tmux only when an interactive TTY is genuinely needed.

Prefer normal `exec` for non-interactive background work.

## Runtime Boundary

- Skill owns: socket convention, targeting, send/capture patterns.
- Runtime owns: higher-level orchestration and durable task state.

## Quick Start

```bash
SOCKET_DIR="${LEMONCLAW_TMUX_SOCKET_DIR:-${TMPDIR:-/tmp}/lemonclaw-tmux-sockets}"
mkdir -p "$SOCKET_DIR"
SOCKET="$SOCKET_DIR/lemonclaw.sock"
SESSION=lemonclaw-shell

tmux -S "$SOCKET" new -d -s "$SESSION" -n shell
tmux -S "$SOCKET" capture-pane -p -J -t "$SESSION":0.0 -S -200
```

## Core Rules

- Use the private socket under `LEMONCLAW_TMUX_SOCKET_DIR`.
- Keep session names short.
- Prefer literal `send-keys -l --`.
- Re-check pane output after every important interaction.

## Useful Commands

```bash
tmux -S "$SOCKET" list-sessions
tmux -S "$SOCKET" list-panes -a
tmux -S "$SOCKET" send-keys -t "$SESSION":0.0 -l -- "$cmd"
tmux -S "$SOCKET" capture-pane -p -J -t "$SESSION":0.0 -S -200
```

## Guardrails

- Do not use tmux just to keep a long-running non-interactive process alive.
- When orchestrating multiple sessions, prefer separate workdirs/worktrees.
- Print monitor commands after creating a session so humans can attach if needed.
