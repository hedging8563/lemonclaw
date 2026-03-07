---
name: mcp-builder
description: Guide for creating MCP (Model Context Protocol) servers that enable LLMs to interact with external services. Use when building MCP servers to integrate APIs or services, in Python (FastMCP) or TypeScript (MCP SDK). Also triggers on 创建MCP、MCP服务、MCP开发.
---

# MCP Server Development Guide

Create MCP servers that enable LLMs to interact with external services through well-designed tools.

## Workflow

### Phase 1: Research and Planning

**API Coverage vs. Workflow Tools:**
Balance comprehensive API endpoint coverage with specialized workflow tools. When uncertain, prioritize comprehensive API coverage.

**Tool Naming:**
Clear, descriptive names with consistent prefixes (e.g., `github_create_issue`, `github_list_repos`).

**Context Management:**
Return focused, relevant data. Support filtering and pagination.

**Error Messages:**
Guide agents toward solutions with specific suggestions and next steps.

**Study MCP docs:**
Start with `https://modelcontextprotocol.io/sitemap.xml`, then fetch pages with `.md` suffix.

### Phase 2: Implementation

**TypeScript (recommended):**
```bash
npx @anthropic-ai/create-mcp-server my-server
cd my-server && npm install
```

Key patterns:
- Use Zod for input/output schemas
- Support pagination for list operations
- Include tool annotations (`readOnlyHint`, `destructiveHint`)
- Handle errors with actionable messages

**Python (FastMCP):**
```bash
pip install fastmcp
```

Key patterns:
- Use Pydantic for schemas
- Decorate tools with `@mcp.tool()`
- Return structured data, not raw API responses

### Phase 3: Review and Test

```bash
# TypeScript
npm run build

# Python
python -m py_compile server.py

# Test with MCP Inspector
npx @modelcontextprotocol/inspector
```

Verify: no duplication, consistent error handling, full type coverage.

### Phase 4: Integration

For LemonClaw, add to `config.json`:
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

For HTTP servers:
```json
{
  "tools": {
    "mcp_servers": {
      "my-server": {
        "url": "http://localhost:3100/mcp",
        "tool_timeout": 30
      }
    }
  }
}
```

## References

For language-specific implementation details, read the MCP specification at `https://modelcontextprotocol.io/specification/draft.md`.
