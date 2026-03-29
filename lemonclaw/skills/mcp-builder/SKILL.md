---
name: mcp-builder
description: Build MCP servers in Python or TypeScript. Use when designing a new MCP server, wrapping an external API as MCP tools, or integrating MCP into LemonClaw.
metadata: {"lemonclaw":{"pattern":"pipeline"}}
triggers: "创建mcp,mcp服务,mcp开发,mcp server,build mcp server,fastmcp,model context protocol,mcp工具,mcp sdk,Python,TypeScript"
---

# MCP Builder

This skill is a `pipeline` with a small `reviewer` step at the end.

## Entry Rule

Use this skill when the user wants to:
- create a new MCP server
- expose an API or service as MCP tools
- add MCP integration guidance for LemonClaw

## Runtime Boundary

- Skill owns: design sequence, tool-shaping rules, validation checklist.
- Runtime owns: durable orchestration, retries, and long-lived deployment promotion.

## Pipeline

### Step 1: Scope the server

Clarify:
- what service or API is being exposed
- read-only vs write operations
- expected auth model
- expected result size, pagination, and filtering

### Step 2: Design the tool surface

Prefer:
- clear names
- focused inputs
- structured outputs
- pagination for list operations
- actionable errors

Do not dump raw upstream payloads when a narrower contract is better.

### Step 3: Implement

TypeScript:
```bash
npx @anthropic-ai/create-mcp-server my-server
cd my-server && npm install
```

Python:
```bash
pip install fastmcp
```

### Step 4: Review

Check:
- no overlapping tools
- input/output schemas are explicit
- destructive operations are clearly marked
- filtering and pagination exist where needed
- errors suggest a next action

### Step 5: Integrate

For LemonClaw config:

```json
{
  "tools": {
    "mcp_servers": {
      "my-server": {
        "command": "node",
        "args": ["path/to/build/index.js"],
        "tool_timeout": 30
      }
    }
  }
}
```

## Guardrails

- Ask missing API/auth questions before generating server code.
- Prefer one coherent tool surface over maximum endpoint count.
- If a flow requires retries, checkpoints, or approval gates, keep that logic out of the skill and put it in runtime/workflow code.
