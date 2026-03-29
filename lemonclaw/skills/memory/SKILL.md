---
name: memory
description: Two-layer memory system with grep-based recall.
always: true
metadata: {"lemonclaw":{"pattern":"tool-wrapper"}}
---

# Memory

This is a `tool-wrapper` skill for LemonClaw memory surfaces.

## Runtime Boundary

- Skill owns: when to read or update `MEMORY.md` / `HISTORY.md`.
- Runtime owns: compaction, summary extraction, and automatic consolidation.

## Structure

- `memory/MEMORY.md` — Long-term facts (preferences, project context, relationships). Always loaded into your context.
- `memory/HISTORY.md` — Append-only event log. NOT loaded into context. Search it with grep.

## Inspect First

```bash
grep -i "keyword" memory/HISTORY.md
```

Use the `exec` tool to run grep. Combine patterns: `grep -iE "meeting|deadline" memory/HISTORY.md`

## Update Rule

Write important facts immediately using `edit_file` or `write_file`:
- User preferences ("I prefer dark mode")
- Project context ("The API uses OAuth2")
- Relationships ("Alice is the project lead")

Do not write transient chatter or every turn summary into `MEMORY.md`.

## Auto-consolidation

Old conversations are automatically summarized and appended to HISTORY.md when the session grows large. Long-term facts are extracted to MEMORY.md. You don't need to manage this.
