# LemonClaw WebUI API Contract

> 从后端源码提取 | 2026-03-05 | 前端重构参考文档

## 认证机制

所有 `/api/*` 端点（除 `/api/auth` 和 `/api/auth/check`）需要 cookie 认证。

- Cookie 名: `lc_session`
- 格式: `base64(created_ts:last_ts:nonce:hmac_sha256)`
- 空闲超时: 4 小时
- 绝对超时: 7 天
- 每次成功请求自动续期 (last_ts 更新)
- 无 auth_token 配置时跳过认证 (localhost 模式)

---

## Auth API

### POST /api/auth — 登录

```
Request:  { "token": "your-gateway-token" }
Response: { "ok": true }  + Set-Cookie: lc_session=...
Error:    { "error": "Invalid token" }  401
```

### DELETE /api/auth — 登出

```
Response: { "ok": true }  + Clear-Cookie
```

### GET /api/auth/check — 检查认证状态

```
Response (已认证):   { "ok": true, "auth_required": true }
Response (无需认证): { "ok": true, "auth_required": false }
Response (未认证):   { "ok": false, "auth_required": true }  401
```

---

## Chat API (SSE Streaming)

### POST /api/chat/stream — 发送消息 (SSE)

```
Request: {
  "message": "你好",
  "session_key": "webui:xxx",     // 可选，默认 "webui:default"
  "model": "anthropic/claude-sonnet-4-20250514",  // 可选，per-session 模型覆盖
  "timezone": "Asia/Shanghai",    // 可选
  "media": ["/tmp/lemonclaw_uploads_xxx/file.png"]  // 可选，上传文件路径列表
}

Response: text/event-stream
  data: {"type": "content", "data": "你"}
  data: {"type": "content", "data": "好"}
  data: {"type": "thinking", "data": "Let me think..."}
  data: {"type": "tool_hint", "data": "🔧 Searching..."}
  data: {"type": "tool_start", "data": "web_search(\"query\")"}
  data: {"type": "tool_result", "data": "Found 3 results..."}
  data: {"type": "done", "data": "完整回复内容"}
  data: {"type": "error", "data": "错误信息"}
```

SSE 事件类型:
| type | 说明 |
|------|------|
| `content` | 流式文本片段 |
| `thinking` | 模型思考过程 (Anthropic extended thinking) |
| `tool_hint` | 工具执行提示 |
| `tool_start` | 工具调用开始 (函数名+参数) |
| `tool_result` | 工具执行结果 |
| `done` | 完整最终回复 |
| `error` | 错误信息 |

注意:
- `session_key` 强制 `webui:` 前缀，防止跨 channel 访问
- 客户端断开连接时自动取消 agent task
- 新 session 首条消息会异步生成标题 (Groq LLM, 5s 超时, fallback 截断)

### POST /api/chat/upload — 上传文件

```
Request: {
  "data": "data:image/png;base64,xxxxx",  // 或纯 base64
  "filename": "screenshot.png"             // 可选
}

Response: { "path": "/tmp/lemonclaw_uploads_xxx/abc123_screenshot.png", "size": 12345 }
Error:    { "error": "File too large (max 10MB)" }  400
```

限制: 10MB，文件 1 小时后自动清理。

---

## Session API

### GET /api/sessions — 列出 WebUI 会话

```
Response: {
  "sessions": [
    {
      "key": "webui:abc123",
      "title": "聊天标题",
      "updated_at": "2026-03-05T10:00:00",
      "message_count": 42,
      "model": "anthropic/claude-sonnet-4-20250514"
    }
  ]
}
```

只返回 `webui:` 前缀的 session。

### GET /api/sessions/{key}/messages — 获取会话消息

```
Response: {
  "messages": [
    { "role": "user", "content": "你好" },
    { "role": "assistant", "content": "你好！有什么可以帮你的？" }
  ],
  "system_prompt_override": ""  // per-session 系统提示覆盖
}
```

只返回 user/assistant 消息，过滤 tool/system。多模态内容提取文本部分。

### PATCH /api/sessions/{key} — 更新会话元数据

```
Request: {
  "title": "新标题",                    // 可选，max 60 chars
  "system_prompt_override": "你是..."   // 可选，max 4000 chars，空字符串清除
}

Response: { "ok": true }
```

### DELETE /api/sessions/{key} — 删除会话

```
Response: { "deleted": true }
```

### GET /api/sessions/{key}/export — 导出会话

```
Query: ?format=md  (默认) 或 ?format=json

Response (md):   text/markdown, Content-Disposition: attachment
Response (json): application/json, Content-Disposition: attachment
```

---

## Models API

### GET /api/models — 列出可用模型

```
Response: {
  "models": [
    {
      "id": "anthropic/claude-sonnet-4-20250514",
      "label": "Claude Sonnet 4",
      "tier": "standard",
      "description": "Fast and capable"
    }
  ],
  "current": "anthropic/claude-sonnet-4-20250514"  // 当前配置的默认模型
}
```

`current` 从 config.json 读取（不受 env 覆盖影响），fallback 到 agent_loop.model。

---

## Settings API

### GET /api/settings — 获取配置

```
Response: {
  "settings": {
    "agents": {
      "defaults": {
        "model": "anthropic/claude-sonnet-4-20250514",
        "temperature": 0.1,
        "max_tokens": 8192,
        "memory_window": 100,
        "max_tool_iterations": 40,
        "token_budget_per_session": null,
        "cost_budget_per_day": null,
        "input_cost_per_1k_tokens": 0.003,
        "output_cost_per_1k_tokens": 0.015,
        "system_prompt": "",
        "disabled_skills": []
      }
    },
    "channels": { ... },
    "providers": {
      "lemondata": { "api_key": "sk-x****xxxx", ... }
    },
    "tools": { ... }
  },
  "effective_model": "anthropic/claude-sonnet-4-20250514"  // 运行时实际模型 (可能被 env 覆盖)
}
```

敏感字段 (api_key, token, secret 等) 自动掩码: `sk-x****xxxx`。
不返回 `lemondata` 和 `gateway` 平台级配置。

### PATCH /api/settings — 更新配置

```
Request: {
  "agents.defaults.model": "anthropic/claude-opus-4-5",
  "agents.defaults.temperature": 0.3,
  "providers.lemondata": { "api_key": "sk-x****xxxx", "api_base": "..." }
}

Response: { "saved": true }
Error:    { "error": "Forbidden paths: xxx" }  403
Error:    { "error": "Validation failed: ..." }  422
```

可写路径白名单:
- `agents.defaults.*` (model, provider, temperature, max_tokens, timezone, memory_window, max_tool_iterations, token_budget_per_session, cost_budget_per_day, input_cost_per_1k_tokens, output_cost_per_1k_tokens, system_prompt, disabled_skills)
- `channels.{name}` (11 个 channel 的完整对象替换)
- `providers.{name}` (21 个 provider 的完整对象替换)
- `tools.*` (web.search, coding, exec, mcp_servers 等)

掩码值回写保护: 如果 provider/channel 对象中的敏感字段值包含 `****`，自动保留原始值。

### POST /api/settings/apply — 应用设置

```
Request: { "changed_paths": ["agents.defaults.model", "channels.telegram"] }

Response (热重载): { "reloaded": true, "restart_required": false }
Response (需重启): { "reloaded": true, "restart_required": true, "restart_fields": ["channels.telegram"] }
```

需重启的字段: `channels.*` (除 send_progress/send_tool_hints/auto_pairing), `tools.mcp_servers`, `tools.coding`。
重启方式: 0.5s 后发送 SIGTERM，由 K8s/systemd 自动重启。

### GET /api/settings/skills — 列出 Skills

```
Response: {
  "skills": [
    {
      "name": "media",
      "source": "builtin",       // "builtin" | "workspace"
      "description": "Media processing skill",
      "enabled": true,
      "available": true
    }
  ]
}
```

### PATCH /api/settings/skills/{name} — 启用/禁用 Skill

```
Request:  { "enabled": false }
Response: { "name": "media", "enabled": false }
```

### POST /api/settings/skills — 安装 Skill (git clone)

```
Request:  { "url": "https://github.com/user/skill-name" }
Response: { "installed": "skill-name" }  201
Error:    { "error": "No SKILL.md found in repository" }  422
```

Skill 名从 URL 最后一段提取，必须匹配 `^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$`。

### DELETE /api/settings/skills/{name} — 删除 Skill

```
Response: { "deleted": "skill-name" }
Error:    { "error": "Cannot delete built-in skills" }  403
```

只能删除 workspace skills。

---

## Memory API

### GET /api/memory — 获取所有记忆层

```
Response: {
  "core": "核心记忆内容 (core.md)",
  "long_term": "长期记忆 (MEMORY.md)",
  "today": "今日日志",
  "history": ["entry1", "entry2", ...],  // 最新在前，最多 50 条
  "entities": [
    {
      "name": "Vincent",
      "type": "person",
      "keywords": ["developer", "AI"],
      "access_count": 5,
      "body": "实体卡片内容"
    }
  ],
  "rules": [
    { "trigger": "用户问...", "lesson": "应该...", "action": "执行..." }
  ]
}
```

### PATCH /api/memory/core — 更新核心记忆

```
Request:  { "content": "新的核心记忆内容" }
Response: { "ok": true }
```

### PATCH /api/memory/entities/{name} — 更新实体卡片

```
Request:  { "body": "更新后的实体内容" }
Response: { "ok": true }
Error:    { "error": "Entity not found" }  404
```

---

## MCP API

### GET /api/mcp/status — MCP 连接状态

```
Response: {
  "connected": true,
  "servers": [
    { "name": "filesystem", "type": "stdio" }
  ],
  "tools": [
    { "name": "mcp_filesystem_read", "server": "filesystem", "tool": "read" }
  ]
}
```

---

## Activity Feed API

### GET /api/activity/sessions — IM Channel 会话列表

```
Response: {
  "sessions": [
    {
      "key": "telegram:12345",
      "channel": "telegram",
      "title": "会话标题",
      "updated_at": "2026-03-05T10:00:00",
      "message_count": 15
    }
  ]
}
```

过滤掉 `webui:`, `api:`, `cron:` 前缀的 session，只显示 IM channel 会话。

### GET /api/activity/messages — 获取 IM 会话消息

```
Query: ?session_key=telegram:12345&limit=50  (limit max 200)

Response: {
  "messages": [
    { "role": "user", "content": "消息内容", "timestamp": "..." },
    { "role": "assistant", "content": "回复内容", "timestamp": "..." },
    { "role": "tool_call", "content": "web_search(\"query\")", "timestamp": "..." }
  ]
}
```

禁止访问 `webui:`, `api:`, `cron:` 前缀的 session (403)。

### WebSocket /ws/activity — 实时事件流

```
认证: Cookie (lc_session)
心跳: 30s 无事件时发送 {"type": "ping"}

事件格式 (由 ActivityBus 推送):
{
  "type": "message_in" | "message_out" | "tool_call" | "error" | "ping",
  "channel": "telegram",
  "session_key": "telegram:12345",
  "content": "...",
  "timestamp": "..."
}
```

---

## Conductor API

### GET /api/conductor/agents — Agent 列表

```
Response: {
  "agents": [
    {
      "id": "default",
      "role": "general",
      "model": "anthropic/claude-sonnet-4-20250514",
      "status": "idle",
      "skills": ["media", "memory"],
      "task_count": 5,
      "success_rate": 0.95,
      "last_active_ms": 1709640000000,
      "created_at_ms": 1709600000000
    }
  ]
}
```

### GET /api/conductor/plans — 编排计划列表

```
Response: {
  "plans": [
    {
      "request_id": "req-abc123",
      "phase": "EXECUTING",
      "message": "原始用户消息 (截断 200 字)",
      "complexity": "complex",
      "subtasks": [
        {
          "id": "st-1",
          "description": "子任务描述 (截断 100 字)",
          "status": "completed",
          "assigned_agent": "agent-1",
          "depends_on": []
        }
      ],
      "progress": 0.5
    }
  ]
}
```

---

## Infrastructure API (Bearer Token 认证)

以下端点使用 `Authorization: Bearer <gateway_token>` 认证，不使用 cookie。

### GET /health — 存活探针

```
Response: "ok"  200  (始终返回)
```

### GET /readyz — 就绪探针

```
Response: { "ready": true, "channels": [...] }  200
Response: { "ready": false, "error": "..." }  503
```

### GET /api/status — 实例状态

```
Response: {
  "uptime_s": 3600.5,
  "channels": ["telegram", "discord"],
  "version": "2026.2.28.1",
  "model": "anthropic/claude-sonnet-4-20250514",
  "instance_id": "claw-test3"
}
```

### GET /api/usage — 用量统计

```
Query: ?session=api:test  (可选，指定 session)

Response: {
  "uptime_s": 3600.5,
  "prompt_tokens": 50000,
  "completion_tokens": 10000,
  "total_tokens": 60000,
  "llm_calls": 25,
  "estimated_cost_today": 0.45,
  "budgets": {
    "token_budget_per_session": null,
    "cost_budget_per_day": 5.0,
    "input_cost_per_1k_tokens": 0.003,
    "output_cost_per_1k_tokens": 0.015
  },
  "sessions": [
    { "key": "telegram:123", "prompt_tokens": 1000, "completion_tokens": 500, ... }
  ]
}
```

### POST /api/chat — 同步聊天 (测试用)

```
Request: {
  "message": "你好",
  "session": "api:test",  // 可选，强制 api: 前缀
  "timeout": 120           // 可选，max 300s
}

Response: { "response": "你好！", "session": "api:test" }
Error:    { "error": "timeout after 120s" }  504
```

---

## Webhook API

### GET /webhook/wecom — 企业微信 URL 验证

```
Query: msg_signature, timestamp, nonce, echostr (企业微信回调验证参数)
Response: PlainText (解密后的 echostr)
```

### POST /webhook/wecom — 企业微信消息回调

```
Body: XML (企业微信加密消息)
Query: msg_signature, timestamp, nonce
Response: PlainText (加密响应)
```

---

## Memo API

### GET /api/memo/yesterday — 昨日摘要

```
Response: {
  "yesterday": ["昨日记录条目1", "昨日记录条目2"],
  "today": "今日日志内容",
  "date": "2026-03-04"
}
```

---

## Info API

### GET /api/info — 实例信息 + 用量

```
Query: ?session=webui:abc123  (可选)

Response: {
  "version": "2026.2.28.1",
  "uptime_s": 3600.5,
  "prompt_tokens": 50000,
  "completion_tokens": 10000,
  "total_tokens": 60000,
  "llm_calls": 25,
  "estimated_cost_today": 0.45,
  "budgets": { ... },
  "session_usage": {           // 仅当 ?session 参数存在时
    "prompt_tokens": 1000,
    "completion_tokens": 500,
    "total_tokens": 1500,
    "llm_calls": 3,
    "estimated_cost": 0.0105
  }
}
```

---

## 通用约定

- 所有 JSON 响应带 `Cache-Control: no-store, private` 防止 CDN 缓存
- 错误格式统一: `{ "error": "描述" }` + HTTP status code
- session_key 前缀隔离: `webui:` (WebUI), `api:` (REST API), `cron:` (定时任务), `telegram:` / `discord:` 等 (IM channels)
- 敏感字段掩码: 包含 `****` 的值在 PATCH 时自动保留原始值
